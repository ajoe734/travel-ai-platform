# 旅行平台 SD 工程產物與可操作 UX 原型：第一批實作交付

> 來源轉存：本檔為既有研究報告的主文，原報告中的交付與測試描述代表當時說法。2026-11-22 接手時的實際檔案與驗證狀態，請以 [原檔匯入紀錄](../provenance/README.md) 及 [驗證說明](../verification/README.md) 為準。歷史 sandbox 路徑不代表 repository 中已有對應工程檔案。來源引用已由原報告所附網址轉為一般連結。


## 已完成的工程產物

本次已從「架構研究」正式進入可落地工程產物。我已實際建立 PostgreSQL migration、OpenAPI 3.1、AsyncAPI 3.1、TypeScript Connector SDK、三個 mock adapter、Temporal workflow 樣板、contract test、RLS test，以及商家／旅客雙端可操作 React UX 原型原始碼。完整工程包可直接取得：

下載完整工程產物 ZIP（歷史路徑：`sandbox:/mnt/data/travel-platform-engineering.zip`）

README（歷史路徑：`sandbox:/mnt/data/travel-platform-engineering/README.md`）  
OpenAPI 3.1（歷史路徑：`sandbox:/mnt/data/travel-platform-engineering/api/openapi.yaml`）  
AsyncAPI 3.1（歷史路徑：`sandbox:/mnt/data/travel-platform-engineering/events/asyncapi.yaml`）  
UX React Prototype（歷史路徑：`sandbox:/mnt/data/travel-platform-engineering/ux/App.tsx`）

目前交付狀態明確區分為三類：**已編寫**的是 schema、API、事件、SDK、mock connector、workflow、tests 與 UX prototype；**已做靜態檢查**的是 OpenAPI 與 AsyncAPI YAML，兩份都已成功通過 YAML parser；**尚未做真實環境驗證**的是 PostgreSQL 16 instance、Temporal Worker、真實 PMS／OTA／預約系統與支付供應商。這些第三方能力沒有被假設為已接通。

完整檔案樹如下：

```text
travel-platform-engineering/
├── README.md
├── package.json
├── api/
│   └── openapi.yaml
├── db/
│   └── migrations/
│       ├── 001_init.sql
│       ├── 002_core.sql
│       ├── 003_rls_immutability.sql
│       └── 004_demo_seed.sql
├── events/
│   └── asyncapi.yaml
├── sdk/
│   └── src/
│       ├── connector.ts
│       ├── index.ts
│       ├── types.ts
│       └── adapters/
│           ├── ExperienceReservationMock.ts
│           ├── PmsNightlyMock.ts
│           └── OtaDelayedPublicationMock.ts
├── workflow/
│   ├── bookingWorkflow.ts
│   └── publicationWorkflow.ts
├── tests/
│   ├── connector.contract.test.ts
│   └── rls.sql
└── ux/
    └── App.tsx
```

我原本也嘗試建立 ChatGPT 內可直接開啟的 React 可視化原型，但原型工具本身回傳不可恢復錯誤，因此沒有假稱已建立可編輯連結；可操作原型的完整 React 原始碼已改放入工程包。

## PostgreSQL 核心資料庫實作

Migration 已按 PostgreSQL 16+ 可執行語法拆成明確順序。PostgreSQL 的 Row-Level Security 在啟用後，若沒有適用 policy，會採 default-deny；`CREATE POLICY` 的 `USING` 與 `WITH CHECK` 可以分別控制可見資料與可寫入資料，因此本實作使用 tenant session context 實現 tenant-scoped isolation。 [PostgreSQL: Documentation: 16: CREATE POLICY](https://www.postgresql.org/docs/16/sql-createpolicy.html?utm_source=chatgpt.com)

第一個 migration 建立 tenant context helper 與正式 domain state：

```sql
CREATE OR REPLACE FUNCTION app.current_tenant_id()
RETURNS uuid
LANGUAGE sql
STABLE
AS $$
  SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid
$$;

CREATE TYPE work_status AS ENUM (
  'DRAFT',
  'WAITING_INPUT',
  'WAITING_DECISION',
  'IN_PROGRESS',
  'UNKNOWN',
  'FAILED',
  'COMPLETED',
  'CANCELLED'
);

CREATE TYPE execution_status AS ENUM (
  'PENDING',
  'RUNNING',
  'SUCCEEDED',
  'UNKNOWN',
  'FAILED',
  'CANCELLED'
);
```

001_init.sql（歷史路徑：`sandbox:/mnt/data/travel-platform-engineering/db/migrations/001_init.sql`）

核心 schema 已涵蓋先前 SA／SD 定義的主要 Aggregate，包括：

```sql
CREATE TABLE work (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenant(id),
  work_type text NOT NULL,
  goal text NOT NULL,
  status work_status NOT NULL DEFAULT 'DRAFT',
  source_type text,
  source_id text,
  version integer NOT NULL DEFAULT 1,
  created_by uuid REFERENCES actor(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, source_type, source_id, work_type)
);
```

Decision 與 immutable approval 被拆開，避免把「要求人決策」與「已形成商業承諾」混為一筆資料：

```sql
CREATE TABLE decision_request (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenant(id),
  work_id uuid NOT NULL REFERENCES work(id),
  decision_type text NOT NULL,
  status decision_status NOT NULL DEFAULT 'PENDING',
  context jsonb NOT NULL,
  options jsonb NOT NULL,
  expires_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE approval_record (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenant(id),
  decision_request_id uuid NOT NULL REFERENCES decision_request(id),
  approved_by uuid NOT NULL REFERENCES actor(id),
  authorization_id text NOT NULL,
  policy_version text NOT NULL,
  approved_payload jsonb NOT NULL,
  payload_hash bytea NOT NULL,
  approved_at timestamptz NOT NULL DEFAULT now(),
  revoked_at timestamptz,
  UNIQUE (tenant_id, decision_request_id)
);
```

Approval Record 以 trigger 阻止 UPDATE / DELETE：

```sql
CREATE OR REPLACE FUNCTION app.enforce_approval_immutable()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  IF OLD.* IS DISTINCT FROM NEW.* THEN
    RAISE EXCEPTION 'approval_record is immutable';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER approval_record_immutable
BEFORE UPDATE OR DELETE ON approval_record
FOR EACH ROW
EXECUTE FUNCTION app.enforce_approval_immutable();
```

Tenant RLS 是在 migration 層正式啟用，而不是只寫在應用程式：

```sql
ALTER TABLE work ENABLE ROW LEVEL SECURITY;
ALTER TABLE work FORCE ROW LEVEL SECURITY;

CREATE POLICY work_tenant_policy
ON work
USING (tenant_id = app.current_tenant_id())
WITH CHECK (tenant_id = app.current_tenant_id());
```

完整 migration 同時包含 `ServiceVersion`、`Quote`、`Booking`、`Payment`、`Execution`、`CompletionEvidence`、`ConnectorAccount`、`ConnectorCapability`、`ExternalMapping`、`Publication`、`OutboxEvent`、`InboxEvent` 及相應 indexes。

002_core.sql（歷史路徑：`sandbox:/mnt/data/travel-platform-engineering/db/migrations/002_core.sql`）  
003_rls_immutability.sql（歷史路徑：`sandbox:/mnt/data/travel-platform-engineering/db/migrations/003_rls_immutability.sql`）  
004_demo_seed.sql（歷史路徑：`sandbox:/mnt/data/travel-platform-engineering/db/migrations/004_demo_seed.sql`）

RLS 測試也已提供，預期由非 table-owner 的 application role 執行，因為 PostgreSQL table owner 通常不受普通 RLS policy 約束，`FORCE ROW LEVEL SECURITY` 則可以改變 owner 的行為。 [PostgreSQL: Documentation: 16: 5.8. Row Security Policies](https://www.postgresql.org/docs/16/ddl-rowsecurity.html?utm_source=chatgpt.com)

RLS integration test SQL（歷史路徑：`sandbox:/mnt/data/travel-platform-engineering/tests/rls.sql`）

## OpenAPI、事件契約與 Connector SDK

OpenAPI 已採 3.1，並將 API auth、idempotency、optimistic concurrency、error contract 與 domain state 放入正式契約。OpenAPI 3.1 的 `security` 可以定義全域或 operation 級 Security Requirement，且 Schema Object 與 JSON Schema 的整合程度比 3.0 更完整。 [OpenAPI Specification v3.1.0](https://spec.openapis.org/oas/v3.1.0.html?utm_source=chatgpt.com)

目前已實作的 endpoint 包括：

```yaml
POST /works
GET  /works/{workId}

POST /decisions/{decisionId}/approve

POST /quotes
POST /quotes/{quoteId}/accept

GET  /bookings/{bookingId}

GET  /connectors/{connectorId}/capabilities

POST /publications
```

Decision approval 同時要求：

```yaml
parameters:
  - $ref: '#/components/parameters/DecisionId'
  - $ref: '#/components/parameters/IdempotencyKey'
  - $ref: '#/components/parameters/IfMatch'
```

也就是說，一個核准動作必須同時處理「重複提交」與「使用者看到舊版 Decision Card 後仍嘗試核准」兩種不同風險。

完整 OpenAPI 3.1 YAML（歷史路徑：`sandbox:/mnt/data/travel-platform-engineering/api/openapi.yaml`）

事件模型則使用 AsyncAPI 3.1，並把 `channels`、`messages` 與 `operations` 分離；AsyncAPI 3.x 的規格本身就是把 channel 與 application operation 分開描述，避免把 transport destination 和 consumer／producer 行為綁死。 [Migrating to v3 | AsyncAPI Initiative for event-driven APIs](https://www.asyncapi.com/docs/migration/migrating-to-v3?utm_source=chatgpt.com)

目前定義：

```yaml
channels:
  workEvents:
    address: travel.work.events
  executionEvents:
    address: travel.execution.events
  bookingEvents:
    address: travel.booking.events
  connectorEvents:
    address: travel.connector.events
```

所有 domain event 共用 envelope：

```yaml
EventEnvelope:
  type: object
  required:
    - eventId
    - eventType
    - eventVersion
    - tenantId
    - occurredAt
    - traceId
```

並保留：

```text
causationId
correlationId
eventVersion
tenantId
traceId
```

以支援 workflow、outbox、外部 webhook 與跨系統追蹤。

完整 AsyncAPI 3.1 YAML（歷史路徑：`sandbox:/mnt/data/travel-platform-engineering/events/asyncapi.yaml`）

Connector SDK 目前不是以 rezio、Bókun、某 PMS 或 OTA 作為核心介面，而是使用 vendor-neutral capability：

```ts
export interface TravelConnector {
  readonly kind: string;

  getCapabilities(
    ctx: ConnectorContext
  ): Promise<CapabilityDescriptor[]>;

  checkAvailability(
    ctx: ConnectorContext,
    request: AvailabilityRequest
  ): Promise<ExecutionResult<AvailabilityResult>>;

  createBooking(
    ctx: ConnectorContext,
    request: CreateBookingRequest
  ): Promise<ExecutionResult<BookingResult>>;

  publishService(
    ctx: ConnectorContext,
    request: PublicationRequest
  ): Promise<ExecutionResult<PublicationResult>>;

  reconcile<T = unknown>(
    ctx: ConnectorContext,
    request: ReconcileRequest
  ): Promise<ExecutionResult<T>>;
}
```

其中最重要的是所有 Connector 都必須回傳三態結果：

```ts
export type ExecutionResult<T> =
  | {
      status: 'SUCCEEDED';
      externalReference?: string;
      data: T;
      evidence?: Record<string, unknown>;
    }
  | {
      status: 'UNKNOWN';
      reconciliationToken: string;
      externalReference?: string;
      reason: string;
    }
  | {
      status: 'FAILED';
      retryable: boolean;
      code: string;
      message: string;
    };
```

因此 timeout、外部審核中、API 接收但沒有最終狀態，都不會被錯誤壓縮成 `FAILED`。

三個 Adapter 已實際編寫：

```text
ExperienceReservationMock
    inventoryModel = TIMESLOT
    booking.create = sync

PmsNightlyMock
    inventoryModel = ROOM_NIGHT
    publication.write = unsupported

OtaDelayedPublicationMock
    booking.create = async
    publication.write = async
    may return UNKNOWN
    requires reconcile()
```

Connector types（歷史路徑：`sandbox:/mnt/data/travel-platform-engineering/sdk/src/types.ts`）  
Connector interface（歷史路徑：`sandbox:/mnt/data/travel-platform-engineering/sdk/src/connector.ts`）  
Experience reservation mock（歷史路徑：`sandbox:/mnt/data/travel-platform-engineering/sdk/src/adapters/ExperienceReservationMock.ts`）  
PMS nightly mock（歷史路徑：`sandbox:/mnt/data/travel-platform-engineering/sdk/src/adapters/PmsNightlyMock.ts`）  
OTA delayed-publication mock（歷史路徑：`sandbox:/mnt/data/travel-platform-engineering/sdk/src/adapters/OtaDelayedPublicationMock.ts`）

這裡已實際證明核心 abstraction 可以同時表示「體驗場次」、「PMS 房晚」與「OTA 非同步發布」，而沒有把其中任何一家的欄位塞進核心 `Booking` 或 `Publication` contract。

## Durable Workflow 與 UNKNOWN／Reconciliation 實作

Temporal 的核心價值在這個架構中不是「背景 job framework」，而是長時間工作可由 event history 恢復；Workflow code 必須維持 deterministic，真正會碰外部世界的操作應放在 Activity。Temporal 也明確指出 Activity 應預期可能重新執行，因此 side effect 必須具備 idempotency。 [What is Durable Execution? | Temporal Documentation](https://docs.temporal.io/durable-execution?utm_source=chatgpt.com)

目前 Booking Workflow 已實際寫出：

```ts
let bookingResult = await a.createSupplierBooking(input);

if (bookingResult.status === 'FAILED') {
  throw new Error(
    `${bookingResult.code}: ${bookingResult.message}`
  );
}

while (bookingResult.status === 'UNKNOWN') {
  await a.persistBookingState({
    ...input,
    state: 'UNKNOWN',
    evidence: {
      reason: bookingResult.reason
    }
  });

  await sleep('5 seconds');

  bookingResult =
    await a.reconcileSupplierBooking({
      ...input,
      token: bookingResult.reconciliationToken
    });
}
```

因此：

```text
Request sent
   ↓
supplier timeout
   ↓
UNKNOWN
   ↓
persist state
   ↓
wait durably
   ↓
reconcile
   ↓
CONFIRMED / FAILED / still UNKNOWN
```

不是：

```text
timeout
   ↓
assume failed
   ↓
retry booking
   ↓
possibly double-book
```

Temporal 官方文件也直接建議可利用 Workflow Run ID 與 Activity ID 組合作為 retry 間穩定的 idempotency key；本工程 API 與 SDK 則另外保留 business-level `Idempotency-Key`，避免只依賴 workflow runtime identity。 [Activity Definition | Temporal Documentation](https://docs.temporal.io/activity-definition?utm_source=chatgpt.com)

Booking Workflow（歷史路徑：`sandbox:/mnt/data/travel-platform-engineering/workflow/bookingWorkflow.ts`）

Publication Workflow 也採相同模式：

```ts
let r = await a.submitPublication(input);

while (r.status === 'UNKNOWN') {
  await a.persistPublication({
    publicationId: input.publicationId,
    state: 'UNKNOWN',
    evidence: { token: r.token }
  });

  await sleep('10 seconds');

  r = await a.reconcilePublication({
    publicationId: input.publicationId,
    token: r.token!
  });
}
```

因此 OTA「已提交、等待審核、未知、最後發布」不需要另外發明一套與 Booking 完全不同的失敗模型。

Publication Workflow（歷史路徑：`sandbox:/mnt/data/travel-platform-engineering/workflow/publicationWorkflow.ts`）

Contract test 已要求所有 Connector 至少遵守共同結果語意，並檢查同步 connector 的相同 idempotency key 不會任意產生第二組 reference：

```ts
const b1 = await connector.createBooking(ctx, booking);
const b2 = await connector.createBooking(ctx, booking);

if (
  b1.status === 'SUCCEEDED' &&
  b2.status === 'SUCCEEDED'
) {
  expect(b2.externalReference)
    .toBe(b1.externalReference);
}

if (b1.status === 'UNKNOWN') {
  expect(b1.reconciliationToken)
    .toBeTruthy();
}
```

Connector contract test（歷史路徑：`sandbox:/mnt/data/travel-platform-engineering/tests/connector.contract.test.ts`）

## 可操作 UX 與 SD Vertical Slice

UX 原型不是 screen inventory，而是已經把狀態轉移放進 React interaction。

完整 React UX prototype（歷史路徑：`sandbox:/mnt/data/travel-platform-engineering/ux/App.tsx`）

商家端已可操作：

```text
商家首頁
   ↓
交代工作
   ↓
AI 發現缺資料
   ↓
補資料
   ↓
Decision Card
   ↓
選 NT$500 Credit
   ↓
執行
   ↓
權限檢查
   ↓
Immutable Approval
   ↓
Credit issued
   ↓
Evidence
   ↓
OTA UNKNOWN
   ↓
reconcile()
   ↓
PUBLISHED
```

Decision Card 實際互動：

```tsx
<label>
  <input
    type="checkbox"
    checked={credit}
    onChange={e => setCredit(e.target.checked)}
  />
  核准 NT$500 Credit
</label>

<button
  disabled={!credit}
  onClick={() => setMerchantStep('progress')}
>
  確認決策並執行
</button>
```

UNKNOWN 也不是文字展示而已，使用者可以觸發 reconcile：

```tsx
<p>
  OTA Mock：
  <strong>
    {resolved ? 'PUBLISHED' : 'UNKNOWN'}
  </strong>
</p>

{!resolved && (
  <button onClick={() => setResolved(true)}>
    執行 reconcile()
  </button>
)}
```

商家端還有 ServiceVersion diff：

```text
欄位          v3            v4
價格          650           680
英文導覽      無            有
雨天方案      未定義        室內茶席
```

以及渠道狀態：

```text
官網          PUBLISHED
合作旅宿      PENDING_REVIEW
OTA Mock      UNKNOWN
```

旅客端也已形成完整 interaction：

```text
需求
 ↓
推薦
 ↓
正式 Quote
 ↓
Consent
 ↓
Booking
 ↓
UNKNOWN
 ↓
reconcile
 ↓
Payment Mock
 ↓
Confirmation
```

其中 Quote、Booking 與 Payment 都明確標註為 mock，不會假稱真實庫存或付款。

這條 UX flow 與 SD 的對接關係已經可以直接表示成同一個 vertical slice：

```text
UX
旅客按「我同意並建立 Booking」

        ↓

API
POST /quotes/{quoteId}/accept
Idempotency-Key: BOOK-Q-001

        ↓

Domain
Booking.status =
QUOTE_CREATED

        ↓

Temporal
bookingWorkflow()

        ↓

Connector SDK
createBooking()

        ↓

OTA Mock
UNKNOWN +
reconciliationToken

        ↓

Domain
Booking.status =
UNKNOWN

        ↓

UX
「供應商確認中」
不是「預訂失敗」

        ↓

Temporal
reconcileSupplierBooking()

        ↓

Connector
CONFIRMED

        ↓

Payment Activity

        ↓

Verification

        ↓

Completion Evidence

        ↓

UX
Booking confirmed
```

這已把 request／response、domain state、workflow、connector、UNKNOWN、reconciliation、evidence 與 UX 串成一條完整實作路徑。

## 工程驗收狀態與架構相容性

目前第一批產物已刻意避免把 MVP vendor 特性寫入核心。體驗系統與 PMS 的 inventory model 不同，OTA 的 publication lifecycle 也不同；這些差異都留在 `CapabilityDescriptor.constraints`、adapter implementation 與 connector-specific mapping，不污染 `Work`、`Decision`、`Booking`、`Payment` 或 `Publication` 的核心資料結構。

這使後續 POS、CRM、電話、LINE 與金流能延續同一個模式：

```text
Core Domain
     │
     ▼
Business Capability
     │
     ▼
Connector Contract
     │
     ├── OTA Adapter
     ├── PMS Adapter
     ├── POS Adapter
     ├── CRM Adapter
     ├── Telephony Adapter
     ├── LINE Adapter
     └── Payment Adapter
```

不是：

```text
Core
├── rezio booking
├── Bókun booking
├── PMS booking
├── POS booking
├── LINE booking
└── payment-vendor-specific booking
```

目前 PostgreSQL RLS、OpenAPI、AsyncAPI 與 Temporal 的使用方式都建立在各自官方規格與官方文件所描述的機制之上。PostgreSQL RLS 的 policy 行為由 PostgreSQL 16 文件支持；OpenAPI security/schema 契約依 OAS 3.1；AsyncAPI channel/message/operation 分離依 AsyncAPI 3.x；Temporal 的 durable execution、deterministic workflow 與 activity idempotency則依 Temporal 官方文件。 [PostgreSQL: Documentation: 16: CREATE POLICY](https://www.postgresql.org/docs/16/sql-createpolicy.html?utm_source=chatgpt.com)

本次交付的真實驗證邊界也已保留：PostgreSQL migration 尚未在真實 PostgreSQL 16 server 執行 migration+rollback；TypeScript 尚未在完整 dependency install 後 compile；Temporal workflow 尚未連接 Worker 與 Activity implementation；三個 Connector 全部是 mock，不代表任何真實 OTA／PMS／預約平台的 API 權限或 capability。OpenAPI 與 AsyncAPI YAML 則已完成基本 YAML 語法解析。

完整工程包：travel-platform-engineering.zip（歷史路徑：`sandbox:/mnt/data/travel-platform-engineering.zip`）