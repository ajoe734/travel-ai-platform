# ENG-06 工作台 API 契約

這是 `services/workbench/service.py` 的 `WorkbenchService` 方法與假定 REST 端點的對照；目前沒有實際 HTTP
伺服器（ENG-02/05 落地前），端點路徑是 `prototypes/merchant-assistant/workbench/index.html` 呼叫
`fetch()` 的實際路徑，由 `tests/workbench_frontend_test.cjs` 的 `FakeWorkbenchServer` 以同一契約的精簡版本
作測試替身。真正串接時，一個 HTTP 層只需把下表左欄位路由到右欄位方法，不應另造一套命名。

錯誤回應皆遵守 `specs/domain/common/error-envelope.schema.json`；`code` 對照
`specs/domain/error-codes.json`（本任務新增 `INVALID_SERVICE_REVISION_FIELD`、`MISSING_REQUIRED_INPUT`、
`DECISION_NOT_PENDING`、`DECISION_OPTION_UNKNOWN`、`WORK_NOT_FOUND`、`WORK_PHASE_MISMATCH`）。

| 端點 | 方法 | 請求 | 成功回應 | 主要拒絕 |
|---|---|---|---|---|
| `GET /v1/workbench/home?tenant_id=` | `get_home_view(tenant_id)` | — | 工作清單；`WAITING_INPUT` 含 `missing_fields`，`WAITING_DECISION` 含 `decision_card`（`display_payload`／`payload_hash`／`revision`），其餘含 `work_status` | — |
| `GET /v1/workbench/works/{id}/status` | `get_work_status(tenant_id, work_id)` | — | `status`、每渠道 `channels[channel]`（`not_started`／`pending`／`live`／`rejected`／`cancelled`，只在 `ExecutionTask.status=DONE` 時才是 `live`）、`waiting_*`／`partial_summary`／`failure`／`cancellation`／`completion_record` | `WORK_NOT_FOUND`（含跨租戶，不洩漏存在與否） |
| `POST /v1/workbench/works` | `propose_service_revision(tenant_id, case_id, actor, now, due_at, merchant_text, fields)` | `{tenant_id, case_id, actor, merchant_text, fields}`；`fields.content` 必須等於 `merchant_text` | 201 Work（`status=WAITING_INPUT`） | `INVALID_SERVICE_REVISION_FIELD`（容量/價格/時長/content 不符） |
| `POST /v1/workbench/works/{id}/input` | `submit_missing_input(tenant_id, work_id, now, asset_ref?, asset_waived?, rights_confirmed?)` | `{tenant_id, asset_ref?, asset_waived?, rights_confirmed?}` | Work（`missing_fields` 更新） | `WORK_NOT_FOUND`、`WORK_PHASE_MISMATCH`（非 `WAITING_INPUT`） |
| `POST /v1/workbench/works/{id}/request-decision` | `request_decision(tenant_id, work_id, now, expires_at)` | `{tenant_id, expires_at}` | `{work, decision}`（`status=WAITING_DECISION`） | `MISSING_REQUIRED_INPUT`、`WORK_PHASE_MISMATCH` |
| `POST /v1/workbench/decisions/{id}/submit` | `submit_decision(tenant_id, decision_id, now, selected_option_id, if_match_revision, if_match_payload_hash)` | `{tenant_id, selected_option_id, if_match_revision, if_match_payload_hash}` | Work（`approve`→`RUNNING` 並建立 `ExecutionTask`；`defer`→`CANCELLED`） | `DECISION_NOT_PENDING`、`AUTHORIZATION_STALE`（revision／hash 不符）、`DECISION_OPTION_UNKNOWN`、`WORK_PHASE_MISMATCH` |

## 不是商家端點

以下方法只給 worker／測試呼叫，不應出現在任何商家可觸發的 UI 動作或 HTTP 路由上（backlog ENG-06 驗收：
正常工作不用商家逐步按執行按鈕）：

- `advance_execution(tenant_id, work_id, now)`：一次 worker tick；對每個尚未終態的 `ExecutionTask` 呼叫
  connector 的 `submit_publication`／`reconcile`，並重新彙整 Work 的彙總狀態。
- `simulate_channel_review_result(tenant_id, work_id, channel, outcome)`：對應 UX 2.1「示範情境切換」的
  渠道審核完成，正式環境應由 webhook 或排程 `reconcile()` 觸發，不是一個商家可按的按鈕。

## 前端呼叫慣例

`prototypes/merchant-assistant/workbench/index.html` 只呼叫上表「端點」欄位列出的五個端點；沒有
`localStorage`，也沒有用 `setTimeout` 模擬執行完成。重新整理頁面等同重新呼叫 `GET /v1/workbench/home`，
直接顯示伺服器當下狀態（backlog ENG-06 驗收：刷新可恢復工作）。容量／價格／時長在送出 `POST
/v1/workbench/works` 前先做同一組邊界檢查（1–8 人、15–300 分鐘、價格 ≥ 1 元）；即使前端檢查被跳過，
`services/workbench/service.py` 的 `_validate_bounds()` 仍會用
`specs/workbench/service-revision.schema.json` 擋下（backlog ENG-06 驗收：容量等不合法值在前後端都被拒絕）。
