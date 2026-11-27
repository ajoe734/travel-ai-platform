# ENG-09 部署與營運 Runbook

狀態：2026-11-27；對應 `docs/collaboration/backlog.md#eng-09`、SA FR-25／FR-29／FR-31，以及 SD `work-execution-contract.md` §4、§6、§7。

## 範圍與安全界線

本 repository 的可部署部分是 PostgreSQL schema、migration runner、repository 與 mock/in-process service。尚未有 HTTP API、常駐 outbox dispatcher、排程器、集中 metrics exporter 或真實 OTA/PMS/金流帳號。因此本 runbook 的「啟動」是建立乾淨 database schema 並跑 repository 驗證，不能宣稱平台服務或正式第三方已上線。

只可用 `MOCK` 或 `SANDBOX` 做本輪演練。`PRODUCTION` 需另有確認過的 connector account、capability、merchant policy、備份保留與變更核准；不可因 `.env.example` 出現變數就推定已獲授權。不得把 DSN、token、cookie、卡號或原始敏感 payload 寫進 git、outbox snapshot 或值班紀錄。

## 建置與全新環境資料庫基線

需求鎖定於 `db/requirements.txt`：`psycopg[binary]==3.2.3`、`pytest==8.3.4`、`jsonschema==4.23.0`。使用 Python 3 與 PostgreSQL 16（CI 的已驗證版本）；migration 需能建立 role、extension 與 RLS，runtime 則以可 `SET ROLE app_role` 的非 superuser 登入。

```bash
python3 -m venv .venv
.venv/bin/pip install -r db/requirements.txt
cp .env.example .env
# Set DATABASE_URL / ENG02_ADMIN_DATABASE_URL to migration-admin URLs, and
# TRAVEL_APP_DATABASE_URL to the non-superuser login role that SET ROLEs app_role.
.venv/bin/python scripts/eng09_preflight.py --env-file .env
export DATABASE_URL='postgresql://<migration-admin>:<secret>@<host>:5432/<empty-db>'
.venv/bin/python db/migrate.py upgrade
.venv/bin/python db/migrate.py status
ENG02_ADMIN_DATABASE_URL="$DATABASE_URL" .venv/bin/python -m pytest tests/db -v
```

預期 `status` 列出 0001 至 0008 為 `applied`，而 DB suite 在 disposable database 跑過。每個 migration 的 rollback 邊界見相鄰的 `db/migrations/*.md`；全量 `downgrade --to 0` **只限空的 disposable verification database**，不可當作有商務資料環境的復原手段。

部署前後應執行：

```bash
.venv/bin/python scripts/verify_eng09.py
git diff --check
```

正式 rollout 應先在已備份的 sandbox 以 `upgrade` 前進；不接受以 edit/re-run 舊 migration 或手工改 `schema_migrations` 取代 forward fix。新的 migration、connector 或常駐程序需另補 health/readiness contract 與版本化 release artifact，才可把本文件的 DB 基線擴稱完整服務啟動。

## 可觀測性與告警

每次 request／worker action 的結構化 log 必須帶入已存在的 `tenant_id`、`case_id`、`work_id`、`task_id`、`attempt_id`（若有）、`operation`、`business_key`、`environment`，以及 SA event envelope 定義的 `correlation_id`／`causation_id`（若有）。不得以旅客姓名、原始對話、付款資料或 connector credential 作為 trace 欄位。外部 reference 可由 `execution_attempt_observation.external_ref`、`completion_evidence.external_ref` 與 publication 的 `external_reference` 查回。

目前沒有 exporter；`db.repository.ops_repository.operational_alerts` 提供同一個 app_role/RLS 邊界下的 read-only 偵測投影，部署 owner 必須將它接到既有受控監控帳號／告警系統，並設定值班 owner、門檻與通知渠道。數字門檻不是產品政策，依環境容量與 provider SLA 設定並記錄版本。`services.ops.logging.structured_operation_log` 只允許 correlation 欄位並會遮蔽 credential/PII，不能把原始 payload 寫入 log。

| 偵測項目 | 最小查詢／訊號 | 告警後的第一步 |
| --- | --- | --- |
| 查核超時或 UNKNOWN | `execution_task` 的 `status IN ('UNKNOWN','WAITING')` 且 `deadline < now()`，或 `next_run_at < now()` | 停止重送，依 task 的固定 business key/external reference 進行唯讀查核；建立/確認 escalation。 |
| 授權失效 | `approval_revocation`、過期 `decision_request`、過期 `execution_authorization` 影響 `NEW/VALIDATING/READY` task | 不繞過閘門；核對 decision/approval/revocation 與 snapshot hash，需要時建立新版決策。 |
| outbox 堆積 | `outbox_event WHERE published_at IS NULL` 的 count 與最早 `created_at` | 確認 dispatcher 是否存在、DB/RLS/consumer 健康；修復後以原 event ID 發送，不重建商務操作。 |
| inbox 衝突/隔離 | `inbox_event.processing_status IN ('QUARANTINED','DEAD_LETTER')` 或 `inbox_event_conflict` 新增 | 保留原 payload/hash，停止套用衝突事件，核對 provider 簽章與 source event identity。 |
| lease 卡住／發布卡住 | `EXECUTING` task 的 `lease_until <= now()`；`DISPATCHING/PENDING/UNKNOWN` publication 長時間未更新 | 僅由 fence-aware worker 接手；先 reconciliation lookup，不能新 dispatch。 |

診斷 trace 時呼叫 `assemble_trace(tenant_id, task_id)`：`execution_task.work_id → work.case_id`，並以 `execution_attempt.id → execution_attempt_observation.attempt_id` 串接；回傳 completion evidence、同 Case 的 order/payment/refund 外部參照與同業務鍵 publication 外部參照。操作人員不得跨 tenant 直接掃資料；若需支援存取，先取得可追溯的臨時授權。

## 備份、復原與錯誤演練

由基礎設施擁有者提供已加密、具保留期與定期 restore 演練的 PostgreSQL backup；repository 不含任何雲端 backup provider 設定。每次 release 前至少記錄 backup ID、schema migration version、restore target 與演練負責人。復原到隔離環境後先跑 `db/migrate.py status`，再以應用 role 驗證 RLS；不得把測試資料或 mock evidence 複製回 production。

| 情境 | 安全處置 | 不可做的事 | 恢復證據 |
| --- | --- | --- | --- |
| migration 失敗 | 停止 rollout；按該 migration `.md` 的 rollback/forward-fix 邊界處置，保留 log 與 schema 版本 | 對有資料環境直接 `downgrade --to 0`、修改已執行 SQL | 受控 sandbox restore/upgrade、`status`、DB suite/hosted CI 結果 |
| 外部呼叫逾時 | 保留 `UNKNOWN`、operation key、attempt 與 lease evidence；唯讀 lookup/reconcile | 以新 key 重送訂位、退款或發布 | provider/readback reference 與 append-only observation/evidence |
| 授權撤回或過期 | 停止未 dispatch action，保存撤回與 decision 版本 | 以模型文字、舊 approval 或前端 flag 放行 | 新 decision/approval 或明確 escalation |
| outbox backlog | 先修 dispatcher/connection/RLS，重送同一 event identity | 直接重跑上游訂位/退款命令 | published timestamp、consumer dedupe 與業務 state 未重複 |
| DB 遺失/毀損 | 依已核准 backup 還原至隔離環境、核對 schema/tenant/RLS，再依 incident approval 切換 | 未核對資料完整性就把 restore 宣稱正式恢復 | restore log、migration status、抽樣 tenant isolation 與業務 reconciliation |

## 交接與變更紀錄

每次 deployment/incident 記錄 candidate/commit、環境（MOCK/SANDBOX/PRODUCTION）、migration version、backup ID（若適用）、操作者、開始/結束時間、trace/correlation IDs、外部 reference、結果與待追蹤 escalation。將「API 接受」、「外部執行完成」、「結果驗證」、「通知送達」分開紀錄；HTTP 200 或 connector accepted 不是 Work completed。

具體驗收與本次可證明範圍見 [ENG-09 驗收對照](eng-09-acceptance-matrix.md)。
