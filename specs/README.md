# 機器可讀工程契約的取得狀態

2026-11-22：已取得 SA-v1.0 的原始 Word／PDF 與[完整文字](../docs/sa/sa-v1.0.md)。其中包含 API、事件、狀態及驗收主文，可作為工程設計來源。

原 SA 主文列出的獨立 OpenAPI、SQL、JSON schema、traceability、state_transitions 與驗收／驗證程式附件，目前尚未取得可核對的原始檔案；本目錄不建立空白替代檔，也不將從摘要重新撰寫的內容標成原附件。完整名稱與狀態見[原檔匯入紀錄](../docs/provenance/README.md)。

後續以 [ENG-01](../docs/collaboration/backlog.md#eng-01固定跨版本領域與契約) 產生明確標記版本的新版契約，並依 [SD 文件](../docs/sd/README.md) 與原始 SA 做對照。如果找回舊附件，先逐檔校驗並記錄來源，再決定相容方式，不能直接覆蓋。

ENG-01 的實際產出在 [domain/](domain/README.md)：Case／Complaint／Work／ExecutionTask／ExecutionAttempt／DecisionRequest／
Approval／Order 的機器可讀 JSON Schema、共用 ID／金額／error envelope 契約、[關聯圖](domain/relationships.md)、
[既有狀態對照與不相容理由](domain/version-compatibility.md)及[驗收對照表](domain/acceptance-trace.md)。這些是本輪新增版本，
不是前一段所述尚未取回的原附件；可用 `python3 -m unittest tests.domain_contract_test -v` 驗證。

ENG-03 的實際產出在 [authorization/](authorization/README.md)：建於上述 domain 契約之上的授權判定服務、
DecisionRequest API 契約、canonical payload hash 與批准／拒絕／過期／撤回紀錄、執行前再檢查及競態處理，
程式本體在 [`services/authorization/`](../services/authorization/)；可用
`python3 -m unittest tests.authorization_service_test -v` 驗證，逐項驗收見
[authorization/acceptance-trace.md](authorization/acceptance-trace.md)。

ENG-04 的實際產出在 [connector/](connector/README.md)：供應商中立的 typed SDK（`connectors/`）與三個固定行為的
mock connector，對照 [SD connector-result-and-reconciliation.md](../docs/sd/connector-result-and-reconciliation.md)。
可用 `python3 -m unittest tests.connector_contract_test -v` 驗證；驗收逐項對照見
[connector/acceptance-trace.md](connector/acceptance-trace.md)。

ENG-06 的實際產出在 [workbench/](workbench/README.md)：商家工作台服務層（`services/workbench/`）與取代
UX 2.1 `localStorage`／`setTimeout` 假後端的前端雛形（`prototypes/merchant-assistant/workbench/`），直接
建構在 ENG-01 的 Work／DecisionRequest／ExecutionTask 契約與 ENG-04 的連接器 mock 上。可用
`python3 -m unittest tests.workbench_service_test -v` 與 `node tests/workbench_frontend_test.cjs` 驗證；
驗收逐項對照見 [workbench/acceptance-trace.md](workbench/acceptance-trace.md)。

ENG-05 的實際產出在 [fulfillment/](fulfillment/README.md)：第一條接單耐久流程（`services/fulfillment/`），
把 ENG-02 的 `db/repository`（新增 `work_repository.py`／`fulfillment_repository.py`，擴充
`execution_repository.py` 的 lease／fence／狀態轉移函式）、ENG-03 的 `decision_request`／`approval_record`
SQL 與 ENG-04 的 `ExperienceReservationMock` 接成一條可重啟、可核對的 Case → Work → quote → consent →
mock 預訂 → 核對 → 完成證據流程。可用 `pytest tests/db/test_fulfillment_workflow.py -v`（需真實 Postgres，
見 [db/README.md 本機無法執行的部分](../db/README.md#本機無法執行的部分)）驗證；驗收逐項對照見
[fulfillment/acceptance-trace.md](fulfillment/acceptance-trace.md)。

ENG-08 的實際產出在 [publication/](publication/README.md)：不可變 ServiceVersion 與每渠道獨立的
publication projection、渠道使用權限、已知審核中與未知結果分流，以及必須與正式讀回版本一致才標記 LIVE。
程式本體在 [`services/publication/`](../services/publication/) 與
[`db/repository/publication_repository.py`](../db/repository/publication_repository.py)；可用
`python3 -m unittest tests.publication_service_test -v` 驗證，逐項證據與 PostgreSQL/外部渠道限制見
[publication/acceptance-trace.md](publication/acceptance-trace.md)。

ENG-10 的實際產出在 [voice/](voice/README.md)：以 tenant-scoped Postgres 記錄 WebRTC、**SIP_TEST**、
語音回合、改口中斷、驗證後接續、轉接實際結果、非同步音訊收件與安全付款連結交接。它不包含或宣稱
已連通真實電信帳號；驗收與限制見 [voice/acceptance-trace.md](voice/acceptance-trace.md)。

ENG-11 的實際產出在 [insights/](insights/README.md)：受控查詢結果的可重現洞察、證據與假說分離的
商家提案／追問、缺口素材請求、掃描後的版本化素材權利及連至 ENG-08 ServiceVersion 的內容建構。它不
包含真實 BI warehouse、防毒服務、媒體處理器或渠道帳號；驗收與限制見 [insights/acceptance-trace.md](insights/acceptance-trace.md)。
