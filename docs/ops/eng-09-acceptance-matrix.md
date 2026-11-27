# ENG-09 驗收對照

狀態：2026-11-27。此表將 `docs/collaboration/backlog.md#eng-09` 的交付和可驗證證據分開；未執行項目不以文件存在宣稱通過。

| Finding／驗收項 | 原始碼依據與修改位置 | 舊版重現 → 修正版結果 | 命令、退出碼、執行版本與證據位置 | 未驗項與具體限制 |
| --- | --- | --- | --- | --- |
| 可重現啟動／部署、依賴鎖定與環境範例 | `db/requirements.txt` 固定 psycopg/pytest；`.env.example` 明確區分 migration-admin、環境與非 secret deployment ID；`eng-09-deployment-runbook.md`「建置與全新環境資料庫基線」 | 先前只有空環境檔與分散 DB 說明，無 ENG-09 可交接基線；現在可按同一組命令建立 venv、升級 schema、查 status、跑 DB suite，且不把它誤稱為 HTTP 平台啟動 | 文件/引用檢查：`python3 scripts/validate_repository.py`；語法：`python3 -m py_compile ...`；本候選執行結果記於 task handoff | 本 VM 無 psycopg/PostgreSQL 且禁止 Docker Compose，需由 GitHub hosted PostgreSQL workflow 或受控 disposable DB 實跑；尚無 HTTP server/worker release artifact。 |
| 無真實憑證入庫 | `.env.example` 僅含 `CHANGE_ME`、非 secret ID 與使用界線；runbook「範圍與安全界線」 | 原本沒有部署期環境契約；現在範例不含 token/密碼，並禁止把 DSN/credentials 寫入 git 或 payload | `git diff --check`、人工內容檢查；repository validation 檢查新文件連結 | 自動 secret scanner 與 production secret manager integration 尚未在 repo 配置；production credentials/connector account 不在 ENG-09 授權內。 |
| trace 串 Case／Work／Execution／外部參照 | `db/migrations/0002_work_execution.up.sql`：`work.case_id`、`execution_task.work_id`、attempt observation/evidence external refs；runbook「可觀測性」 | 既有 schema 已可保留鏈路但沒有可交接的 operating procedure；現在明定 required structured fields、查詢鏈與 tenant 限制 | 靜態 schema/procedure 對照；DB 實證由 `pytest tests/db -v` 的 hosted PostgreSQL job 覆蓋持久化路徑 | 沒有 log exporter、API middleware 或 distributed tracing collector，不能宣稱已有 end-to-end trace。 |
| 查核超時、授權失效、outbox 堆積能被發現 | `execution_task` deadline/status/lease，`outbox_event` published state，`inbox_event` processing state，authorization error codes；runbook「可觀測性與告警」 | 既有 schema/服務有狀態但無告警運維映射；現在列出最小訊號、首步處置與不可重送規則 | 靜態對照 SD `work-execution-contract.md` §4/§6/§7 與 migration 0002/0005 | 尚未有常駐 dispatcher、scheduler、metrics exporter 或配置完成的 paging policy；門檻與值班 owner 必須由環境 owner 設定。 |
| 失敗後可操作復原 | runbook「備份、復原與錯誤演練」；各 `db/migrations/*.md` rollback/forward-fix 邊界 | 原先 DB README 只描述 migration lifecycle；現在將 migration、UNKNOWN、撤回、outbox、DB restore 的動作/禁止動作/證據形成 runbook | 靜態內容與交叉連結檢查 | 未對本 VM 執行 restore 或第三方 reconciliation；真實 backup provider 與 production recovery approval 尚未設定。 |
| 正式第三方與生產部署界線 | runbook「範圍與安全界線」；`docs/project/current-decisions.md` | 無改變：mock/sandbox evidence 不等於正式連通；明確列為未完成而非宣稱可上線 | 文件核對 | 需已確認帳號、能力、營運政策、監控/備份責任與獨立 production acceptance。 |
