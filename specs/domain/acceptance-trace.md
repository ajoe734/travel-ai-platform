# ENG-01 驗收對照表

依 [AI_COLLABORATION_GUIDE.md §0.7](../../AI_COLLABORATION_GUIDE.md) 的交接格式，逐項列出
[backlog ENG-01](../../docs/collaboration/backlog.md#eng-01固定跨版本領域與契約)的「產出」與「驗收」，對照本目錄的實際檔案、
測試命令與結果。此表是這個候選的 handoff 證據來源；handoff 摘要只引用它，不重複貼全部內容。

執行環境：本機 Python 3.12.3 + `jsonschema` 4.10.3（已安裝，未另行引入新依賴）。未啟動資料庫、瀏覽器或外部
connector；凡此類未驗項在下表「未驗項與具體限制」欄明列。

| 驗收項 | 原始碼依據與修改位置 | 舊版重現 → 修正版結果 | 命令、退出碼、執行版本與證據位置 | 未驗項與具體限制 |
|---|---|---|---|---|
| 同一案件可有多個 Work | `work-execution-contract.md §1`；`specs/domain/work.schema.json`、`case.schema.json` | 舊：SA 原文沒有機器可讀 schema 可驗證此關係。新：`examples/work/work-1-booking-valid.json` 與 `work-2-reschedule-valid.json` 共用 `case_id=...0001`，各自通過 `work.schema.json` | `python3 -m unittest tests.domain_contract_test.CrossInstanceInvariants.test_case_can_have_multiple_works -v` → exit 0；見 `tests/domain_contract_test.py` 同名測試 | 僅證明契約形狀允許；`UNIQUE`/FK 層級的多筆持久化驗收是 ENG-02 scope |
| 同一 Work 可有多個執行操作 | `work-execution-contract.md §1`；`specs/domain/execution-task.schema.json` | 新：`task-1-booking-create-valid.json`（`booking.create`）與 `task-2-notification-valid.json`（`notification.send`）共用 `work_id=...0101`，皆通過 schema | `python3 -m unittest tests.domain_contract_test.CrossInstanceInvariants.test_work_can_have_multiple_execution_tasks -v` → exit 0 | 同上，實際併發寫入/交易邊界是 ENG-02/05 scope |
| 重試只增加 Attempt | `work-execution-contract.md §2/§6.1`；`specs/domain/execution-attempt.schema.json` | 舊：第一批報告以 `Execution.PENDING/SUCCEEDED` 表示，未明確分出「同一操作的第 N 次嘗試」。新：`attempt-1-timeout-valid.json`（`attempt_no=1`, outcome `UNKNOWN`）與 `attempt-2-reconcile-valid.json`（`attempt_no=2`, outcome `SUCCEEDED`）共用同一 `task_id`，`ExecutionTask.id` 全程不變 | `python3 -m unittest tests.domain_contract_test.CrossInstanceInvariants.test_retry_only_appends_an_attempt_same_task tests.domain_contract_test.CrossInstanceInvariants.test_duplicate_attempt_no_on_same_task_is_detected -v` → exit 0 | `(tenant_id, task_id, attempt_no)` 的資料庫層 `UNIQUE` 約束是 ENG-02 scope；此處只在範例集合層級證明衝突可被偵測 |
| 退款完成不會使 Complaint 自動結案 | `credit-and-refund.md §1`；SA SM-04；`specs/domain/complaint.schema.json` | 舊：SA 文字規則「退款或改期成功不強迫客訴同步關案」沒有可執行形式。新：`complaint-1-refund-succeeded-not-closed-valid.json`（`status=WAITING_CUSTOMER`、有 `remedy_action_refs`、無 `resolution`）通過；`complaint-invalid-resolved-without-resolution.json`（`status=RESOLVED` 但無 `resolution`）被拒絕；`complaint-invalid-open-with-resolution.json`（狀態未結案卻預填 `resolution`）也被拒絕 | `python3 -m unittest tests.domain_contract_test.FixtureValidation tests.domain_contract_test.CrossInstanceInvariants.test_refund_succeeding_does_not_imply_complaint_closed -v` → exit 0 | RemedyAction/Refund 完整狀態機與原子保留是 ENG-07 scope；本輪只固定 Complaint 自己的結案條件 |
| 為所有既有狀態提供對照或明確不相容理由 | `sa-v1-gaps.md §3`；`work-execution-contract.md §5` | 新：`specs/domain/version-compatibility.md` 逐狀態域列出對照或不相容理由（Work/Task、ExecutionTask SM-01、Authorization/Approval、Order SM-02、Complaint SM-04、Capability/OperationResult） | 文件核對；`markdown_files_checked`／`local_links_checked` 由既有 `python3 scripts/validate_repository.py` 涵蓋連結完整性 | 本檔是設計對照，不是資料遷移執行紀錄；沒有舊系統資料庫實例可供實際遷移測試 |
| SA 需求編號可追溯 | 全部 `specs/domain/*.schema.json` 的 `x_origin.sa_trace`／`sd_trace` | 新：每個實體 schema 都有非空的 `sa_trace`/`sd_trace`（FR/BR/SM/ADR 編號） | `python3 -m unittest tests.domain_contract_test.TraceabilityPresence -v` → exit 0 | 只檢查欄位存在且非空，不代表每個追溯編號本身在 SA 原文確實存在（人工核對見下方「交叉核對」） |
| Case/Complaint/Work/ExecutionTask/ExecutionAttempt/DecisionRequest/Approval/Order 的關聯 | `work-execution-contract.md §1`、`authorization-and-approval.md §1/§5`；`specs/domain/relationships.md` | 新：逐關聯 cardinality 與外鍵表，對照 SD 的 mermaid ERD | 文件核對 + `tests/domain_contract_test.py` 的跨實例測試（見上列各項） | 無 |
| 共用 ID、金額／幣別、版本、狀態、error envelope | `common/identifiers.schema.json`、`common/money.schema.json`、`common/error-envelope.schema.json`、`error-codes.json` | 新：8 個實體 schema 全部透過 `$ref` 使用同一組共用型別，而非各自定義 | `python3 -m unittest tests.domain_contract_test.SchemaItselfIsValid tests.domain_contract_test.ErrorCodeRegistryConsistency -v` → exit 0 | 無 |
| 新的機器可讀 schema 與版本轉換說明 | 全目錄 | 新：11 個 `*.schema.json`（Draft 2020-12）+ `version-compatibility.md` | `python3 -m unittest tests.domain_contract_test -v` → 12 tests, exit 0 | 無 |
| 每個契約註明新增版本及來源，不取代仍未找回的原附件 | 全部 schema 檔 `x_origin` 區塊；`specs/README.md` | 新：每個 schema 檔 `x_origin.replaces_recovered_attachment = false`；`specs/README.md` 已有連結指回本目錄 | 人工核對 `x_origin` 欄位；見下方交叉核對命令 | 無 |

## 交叉核對命令與結果

```bash
$ python3 -m unittest tests.domain_contract_test -v
...
Ran 12 tests in 0.1s
OK
```

```bash
$ python3 - <<'EOF'
import json
from pathlib import Path
for p in sorted(Path("specs/domain").glob("*.schema.json")):
    s = json.loads(p.read_text())
    assert s["x_origin"]["replaces_recovered_attachment"] is False, p
    print(p.name, s["x_origin"].get("sa_trace") or s["x_origin"].get("sd_trace"))
EOF
approval-record.schema.json ['BR-05', 'BR-06', 'BR-07', 'BR-09', 'BR-10', '03.1', '08.2']
case.schema.json ['FR-03', 'FR-11', 'UC-01', '08.4']
complaint.schema.json ['FR-13', 'FR-14', 'FR-15', 'UC-05', 'UC-06', 'SM-04', 'BR-16', 'BR-17']
decision-request.schema.json ['BR-05', 'BR-09']
execution-attempt.schema.json ['03', '08.2']
execution-task.schema.json ['03', '03.1', '08.2', 'SM-01', 'BR-06', 'BR-07', 'BR-08']
order.schema.json ['04.1', '04.2', 'SM-02', 'BR-03', 'BR-14']
work.schema.json ['FR-25', 'SM-01', '08.2']
```

這兩段命令的實際輸出已貼於上，退出碼均為 0；執行版本為本機 Python 3.12.3、`jsonschema` 4.10.3，於
`.artifacts/worktrees/auto/claude-eng-01` 工作樹執行。沒有執行資料庫、瀏覽器或外部 connector 相關檢查。
