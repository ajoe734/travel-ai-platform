# Connector 結果與外部核對契約

版本：2026-11-22，新增 SD 設計。保留 [SA v1.0](../sa/sa-v1.0.md) BR-03/04/08、07/07.1/07.2、08.8 及 SA-AT-006/014/015/022/040/049/055/056/058/059 的要求；修正[第一批報告](../research/2026-11-21-engineering-batch1.md)的三態結果與 `token`/`reconciliationToken` 差異。此文件是本平台抽象，不代表任何廠商已支援或帳號已取得權限。

## 1. 三個層次不可混合

| 層次 | 問題 | 本次欄位 |
|---|---|---|
| Capability | 這個帳號與環境可不可以做、有哪些限制？ | support、authorization_state、mode、constraints、verification |
| OperationResult | 這一次呼叫已知的執行結果是什麼？ | SUCCEEDED / PENDING / UNKNOWN / FAILED |
| Domain state | 訂位、付款、退款或渠道目前的正式狀態？ | 各 domain 自己的狀態及來源版本 |

`SUPPORTED` 與 `UNSUPPORTED` 只能是能力資訊，不用作業務操作結果。HTTP 200/202 是傳輸結果，不等於 business success。操作回 SUCCEEDED 還需要 domain verifier 核對該 Work/task 的 postcondition。

## 2. CapabilityDescriptor

能力以 `(tenant_id, connector_account_id, environment, capability_key, contract_version)` 辨識。

| 欄位 | 規則 |
|---|---|
| capability_key | 例如 availability.read、booking.create、booking.lookup、refund.create、refund.lookup、publication.update、publication.read；逐項登記 |
| support | SUPPORTED / UNSUPPORTED / UNVERIFIED；原廠文件不能把本帳號變成 SUPPORTED |
| authorization_state | ACTIVE / MISSING / EXPIRED / REVOKED；與技術支援分開 |
| mode | SYNC / ASYNC / MANUAL / CONTROLLED_BROWSER；人工完成不計為全自動 |
| inventory_model | TIMESLOT／ROOM_NIGHT 等已定義模型；供應商額外欄位留在 adapter mapping |
| writable_fields / readable_fields | 每欄是否可寫、可讀回、誰是 authoritative；內容可寫不代表價格可寫 |
| side_effect | READ / WRITE；核對函式不得暗中觸發寫入 |
| idempotency | 是否支援固定 client operation key、key 範圍與保留期間、衝突語意；未知就標未知 |
| lookup | 可用 external_ref/business reference 查詢的方式、唯一性、可見延遲與終態判定 |
| version_control | 是否支援 expected revision/conditional update；不支援時記錄 read-before-write 及衝突風險 |
| restrictions | 金額/幣別/時區/資源/渠道等具名限制，不寫任意自由文字替代機器檢核 |
| verification | account/environment/API product version、checked_at、沙盒證據與正式啟用狀態 |

支援度、帳號權限及讀回方式都符合，才啟用對應自動寫入。無可靠 lookup/idempotency 的不可逆操作不得以通用自動重試補足；提供有責任人的人工核對路徑。

## 3. OperationResult 契約

以下為新的 SDK 設計介面示意，尚未是可引用的已安裝 SDK。HTTP 使用 snake_case；SDK 可用 camelCase，但 mapping 明列且只保留一種 canonical 欄位。

```typescript
type OperationResult<T> =
  | {
      status: 'SUCCEEDED';
      externalReference: string;
      sourceRevision?: string;
      data: T;
      evidenceRefs: string[];
      observedAt: string;
    }
  | {
      status: 'PENDING';
      externalReference: string;
      reconciliationToken: string;
      pendingReason: string;
      evidenceRefs: string[];
      nextCheckAt?: string;
      observedAt: string;
    }
  | {
      status: 'UNKNOWN';
      externalReference?: string;
      reconciliationToken: string;
      reasonCode: string;
      dispatchEvidenceRef: string;
      observedAt: string;
    }
  | {
      status: 'FAILED';
      code: string;
      message: string;
      retryable: boolean;
      sideEffectDisposition: 'NOT_APPLIED' | 'REVERSED';
      evidenceRefs: string[];
      observedAt: string;
    };
```

寫入成功必須有正式物件/操作參考與 evidence。唯讀查詢可使用獨立 ReadResult，沒有副作用時逾時可回查詢失敗；不能以唯讀結果語意套用退款/預訂。

`reconciliationToken` 是平台保存核對上下文的 opaque ID，不是外部登入 token，也不是自行授權憑證。它指向已持久化的 tenant/account/environment/operation/business key/external ref/lookup strategy。HTTP 對應 `reconciliation_token`，廢除報告中不明確的 `r.token`。

FAILED 必須足以證明本操作沒有未明的副作用；僅遇 5xx、connection reset、response parse error 或時間到，不能填 NOT_APPLIED。若上游可能已成功，就回 UNKNOWN。補償已執行且正式驗證完成才可填 REVERSED；它仍保留原影響及補償 ID。

## 4. PENDING 與 UNKNOWN

| 情境 | 結果 | 下一步 |
|---|---|---|
| 供應商返回可查的申請 ID，明確 waiting review | PENDING | 等 webhook 或排定查詢，同一 operation，不再 create |
| HTTP 202 只有泛用「accepted」，無法確認對應哪次操作 | 視契約；缺少可識別結果則 UNKNOWN | 以預存 business reference 核對 |
| 請求送出後 timeout，但上游可能已建單 | UNKNOWN | 查 operation key/reference；不重送新 key |
| 請求在本地驗證前被拒絕、完全未送網路 | FAILED/NOT_APPLIED 或 validation error | 修正/重新授權後依同業務邏輯執行 |
| 上游明確拒絕且查得無建單 | FAILED/NOT_APPLIED | 依 code 決定替代、人工或安全重試 |
| 查詢暫時找不到，但上游有 eventual visibility | UNKNOWN | 在提供者可見延遲與核對條件內繼續；一次 not-found 不能當失敗 |
| 上游確認已退，金額/幣別不符 | 保留原結果及例外，不完成本退款 | escalation、禁止再次退款，核對差異 |

已知 PENDING 可在後續查不到來源時進 UNKNOWN；不能為維持漂亮狀態而保留假進度。晚到的正確終態可以解決 PENDING/UNKNOWN，但須驗證來源及關聯。

## 5. 核對演算法

1. 從持久化 task/context 取 tenant、account、environment、固定 operation key、request hash 與批准範圍。不要由使用者傳入任意 external URL/ID 選擇核對對象。
2. 取得該 task 的 reconciliation lease/fence；確認查詢能力、憑證與目的仍有效。已送出合法動作的核對不重新消耗一次批准。
3. 優先消化已驗簽且已入 inbox 的對應事件，再以正式 lookup 讀回。事件與查詢衝突時以指定 source-of-truth 與資源版本核對，建立 conflict 事件，不能由 LLM 猜。
4. 以 account+environment+entity_type+external_id 唯一映射到原操作；同姓名、同金額或同日期不能作唯一合併依據。
5. 結果已終止則保存不可變 evidence，由 domain verifier 比對 postcondition；PENDING/UNKNOWN 則寫 next_check_at 並釋放 lease。
6. 遵守 provider retry-after、設定的退避與 deadline。deadline 超過建立 Escalation、保留核對責任；不自動變 FAILED，不釋放未知金額。
7. 不以無限 LLM 輪詢等待。排程器/Temporal timer 消化等待；只有需要解釋例外或新方案才喚醒模型。

重試間隔、最大自動查詢頻率、期限、值班角色由 capability/operation policy 設定；不把舊報告固定 5 秒或 10 秒迴圈當正式策略。長期未知的處理結果需有人工查核來源與證據，不允許按「已解決」就解除限制。

## 6. Dispatch 與重啟

執行順序沿用 SA：domain transaction → task/outbox → worker claim → dispatch intent → external call → evidence/outcome transaction。dispatch intent 在發送前記錄穩定 reference。若 worker 在發送前後不明位置死亡，接手者先核對；單靠本地「還沒有 response」無法知道是否送出。

若提供者支援冪等且原 key 仍有效，可在明確的 adapter 策略下重送**相同 key 與完全相同 payload**，這是找回同一 operation，不能更換 key。策略需透過「外部已成功、回覆遺失」測試驗證。若 provider key 已過期，禁止把它視為可安全新建。

實際 Temporal Activity 可能重跑，所以每次 Activity 都先讀平台 task/業務鍵，不能以新 Workflow Run ID 自動創造新 business key。Temporal history 不能當第三方已執行證據。

## 7. Webhook 與事件

入口按 connector account 驗 provider 原始簽章，tenant/environment 由設定導出，不信任 payload 自稱 tenant。保存 source event ID、raw hash、producer、received_at 與必要加密原文參考後回 ACK，不在 webhook request 內等待模型。

Inbox 去重唯一鍵包含 tenant、account/environment、producer、source_event_id。同 ID 同 hash 回相同 ACK；同 ID 不同 hash 隔離並告警；不支援 major schema 進 dead letter，不猜欄位。payload 大小與附件類型有部署限制。

outbox 與業務變更同一 transaction；每個 consumer 有獨立去重紀錄。跨來源描述同一訂單，使用 canonical mapping 合併，不能靠 event ID 不同就建兩個訂單/佣金。事件重播不重複副作用、通知或計費。

資源 revision 與正式查詢決定新舊；occurred_at 只提供線索。沒有可靠 revision 時讀回來源；外部取消晚於平台 confirmed 屬新業務變更，保存新事件並啟動既定後續，不把它當「舊事件」丟棄。

## 8. 每渠道獨立發布

Publication 的業務鍵包含 offer/channel/account/environment、operation 與已批准 service_version。保存：desired_version/hash、submitted_version/hash、observed_version/hash、observed_sales_state、source_revision、task、approval/manifest item、evidence。

推薦狀態沿用 SA 可見語意：`DRAFT, READY, SUBMITTED, PENDING_REVIEW, VERIFYING, LIVE_VERIFIED, PAUSED_VERIFIED, FAILED, UNKNOWN`。這是 Publication domain 狀態，與 task WAITING/DONE 分開。publish 工作需 LIVE_VERIFIED；pause 工作需 PAUSED_VERIFIED，不能只看到物件存在即成功。

發布前比對原渠道版本。發現店員已改版，回 VERSION_CONFLICT，保留差異並要求新的決策；不採最後寫入覆蓋。只支援文字、不支援改價時，文字和價格逐項列完成與未完成，不顯示整商品一致。原批准可否允許先發布可完成部分，必須在 manifest 明列，不由 adapter 擅自決定。

素材或渠道用途撤回後，停止新發布並建立逐渠道撤下/替換工作。已發布內容的撤下需要讀回證據，不把本地 entitlement revoke 當外部已刪除。已成立訂單依原成交快照繼續履約。

## 9. Mock 與正式 adapter 的驗收邊界

| Adapter | 必交 mock 行為 | 不能由 mock 推定 |
|---|---|---|
| ExperienceReservationMock | 場次資源、同步 booking、同業務鍵相同 reference、資源衝突 | 任一實際體驗平台已授權 |
| PmsNightlyMock | 房晚模型、跨晚查詢、明確不支援 publication | PMS 可以任意改 OTA 價格 |
| OtaDelayedPublicationMock | 已受理 PENDING、回覆遺失 UNKNOWN、延遲讀回、拒絕與部分渠道結果 | OTA 審核時間或 API 寫入權 |

正式啟用需逐能力記錄 account、environment、API產品/版本、scope、實測證據與 feature flag。受控 browser 有獨立授權/範本/讀回要求；遇登入驗證或結構不符交回適當人，不繞過。金融副作用僅走既定 financial adapter 流程。

## 10. 負向驗收

| ID | Given／When | 必須結果 | 追溯 |
|---|---|---|---|
| SD-C-01 | 上游建單成功但 response timeout | UNKNOWN；lookup 找回同單；新 create 次數不增加 | AT-006 |
| SD-C-02 | provider 已給申請 ID、waiting review | PENDING；不標失敗或不明；保持同操作 | FR-22 |
| SD-C-03 | 第一次 lookup not-found，但有來源延遲 | 保留 UNKNOWN，退避核對；不能釋放或重做 | BR-08 |
| SD-C-04 | 同 webhook ID 換 payload | 隔離告警，不更新交易 | AT-055 |
| SD-C-05 | sandbox event 指向 production order | 拒絕環境不符，不把假付款當真付款 | FR-29 |
| SD-C-06 | PMS 不支援 publication，模型仍呼叫 | 執行前回 capability unavailable；不發外部 request | FR-24 |
| SD-C-07 | 渠道已被人工修改基礎版本 | 版本衝突，保留新設定與 proposed diff | AT-014 |
| SD-C-08 | A發布成功、B審核、C拒絕 | 各自狀態；重試C不再送A/B | AT-015/040 |
| SD-C-09 | worker重啟／DB還原在已送出之前 | 先查外部 operation reference；對帳前不重扣/重建 | AT-056 |
| SD-C-10 | 來源查詢名為lookup但實際有副作用 | 不列為唯讀 reconcile；必須另走寫入授權 | 本次新增 |
| SD-C-11 | 相同外部訂單由渠道與預約系統回流 | canonical mapping 合併，不重建訂單/結算 | AT-049 |
| SD-C-12 | 任務deadline到仍 UNKNOWN | escalation有owner與due，UNKNOWN及保留不清掉 | FR-25 |
| SD-C-13 | 某欄不可寫/不可讀回，但其他欄成功 | 明示未完成欄位，不能標整版本 LIVE_VERIFIED | AT-058 |
| SD-C-14 | 來源自己寄通知、平台收到同事件 | 依 notification_owner 去重，不雙寄或矛盾通知 | AT-059 |

## 11. 後續實作

需完成 SDK 與 HTTP schema、各 adapter 契約測試、provider 原文驗簽、mapping 唯一約束、inbox/outbox、reconciliation worker/timer、source verifier、每渠道讀回與 incident UI。原報告沒有完整 Activity implementation，本文件也不冒充這些實作已存在。
