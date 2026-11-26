# 機器可讀工程契約的取得狀態

2026-11-22：已取得 SA-v1.0 的原始 Word／PDF 與[完整文字](../docs/sa/sa-v1.0.md)。其中包含 API、事件、狀態及驗收主文，可作為工程設計來源。

原 SA 主文列出的獨立 OpenAPI、SQL、JSON schema、traceability、state_transitions 與驗收／驗證程式附件，目前尚未取得可核對的原始檔案；本目錄不建立空白替代檔，也不將從摘要重新撰寫的內容標成原附件。完整名稱與狀態見[原檔匯入紀錄](../docs/provenance/README.md)。

後續以 [ENG-01](../docs/collaboration/backlog.md#eng-01固定跨版本領域與契約) 產生明確標記版本的新版契約，並依 [SD 文件](../docs/sd/README.md) 與原始 SA 做對照。如果找回舊附件，先逐檔校驗並記錄來源，再決定相容方式，不能直接覆蓋。

ENG-01 的實際產出在 [domain/](domain/README.md)：Case／Complaint／Work／ExecutionTask／ExecutionAttempt／DecisionRequest／
Approval／Order 的機器可讀 JSON Schema、共用 ID／金額／error envelope 契約、[關聯圖](domain/relationships.md)、
[既有狀態對照與不相容理由](domain/version-compatibility.md)及[驗收對照表](domain/acceptance-trace.md)。這些是本輪新增版本，
不是前一段所述尚未取回的原附件；可用 `python3 -m unittest tests.domain_contract_test -v` 驗證。
