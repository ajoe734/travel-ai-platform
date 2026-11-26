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
Ran 13 tests in 0.1s
OK
```

（R1 退修後新增 `FixtureCoverage` 測試，見下方「R1 退修逐項驗證」一節；12 → 13。）

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

## R1 退修逐項驗證（Antigravity review，candidate `cee3e4e2bff7fb6589df2ceefcb78cc70b2e0bc8`）

依 AI_COLLABORATION_GUIDE.md §0.7，逐項記錄 R1 審查的 6 個 finding（F1-F6）：原始碼依據、舊版（R1 審查當時的
`cee3e4e2` 版本，下稱「舊版」）實際行為 → 本次修正版結果、命令與退出碼、未驗項。所有命令於本機
`.artifacts/worktrees/auto/claude-eng-01` 工作樹、Python 3.12.3、`jsonschema` 4.10.3 執行。

| Finding | 原始碼依據與修改位置 | 舊版重現 → 修正版結果 | 命令、退出碼與證據位置 | 未驗項與具體限制 |
|---|---|---|---|---|
| F1 | `specs/domain/approval-record.schema.json` L59-91（`ExecutionAuthorization`）：移除 `required` 中的 `approval_refs`；`grant_refs` 加 `minItems:1`；新增 `anyOf: [{required:[grant_refs]}, {required:[approval_refs]}]` | 舊版 `required` 強制 `approval_refs`：R1 review 本身已貼出的 probe（`grant_refs`+`consent_refs` 無 `approval_refs`）回 `"'approval_refs' is a required property"`，等同拒絕 SD-A-10 的「政策已允許，不逐案要求人核准」路徑。新版：新增 `examples/approval/execution-authorization-2-policy-only-valid.json`（只有 `grant_refs`，無 `approval_refs`）通過；`examples/approval/execution-authorization-invalid-no-basis.json`（兩者都無）被拒絕 | `python3 -m unittest tests.domain_contract_test.FixtureValidation -v` → exit 0（新 FIXTURES 兩筆都在其中）；逐檔 diff 見 `git show cee3e4e2:specs/domain/approval-record.schema.json` 對照現版 L59-91 | 舊版對照是用 R1 review 文字記錄的 probe 結果比對新舊 schema 原始碼差異（靜態核對），不是本輪重新對舊 SHA 執行一次指令；嘗試用獨立 Python 腳本動態跑舊版 schema 比對時，本機 Bash 工具的 `orchestrator_approval_broker` 連續兩次在同一類指令上卡滿 1800 秒逾時中止，故採 §0.7 允許的「精確靜態證據」替代動態重現 |
| F2 | `specs/domain/approval-record.schema.json` L112-130（`ApprovalRecord`）新增必填 `approved_payload`；`decision-request.schema.json` L59-63 新增選用 `display_payload` | 舊版 `ApprovalRecord` 無 `approved_payload` 欄位且 `additionalProperties:false`：帶入該欄位必被拒絕（SD §2/§3.1 要求的審計內容無處存放）。新版：`examples/approval/approval-record-1-valid.json` 已補 `approved_payload` 並通過；`decision-request.schema.json` 新增可選 `display_payload`，不影響既有 fixture | `python3 -m unittest tests.domain_contract_test.FixtureValidation -v` → exit 0 | `display_payload` 未在任一 fixture 填入（SD 原文只說「考慮」），僅確認其為合法可選欄位，不影響既有驗收 |
| F3 | `specs/domain/execution-task.schema.json` L31（`request_snapshot` 加入 `required`）、L78-82（新增 `manifest_item_id`）、L94-98（`allOf`：有 `authorization_use_id` 則必有 `manifest_item_id`）；`approval-record.schema.json` L139-154（`scope_manifest` item 新增選用 `resource_revision`/`account`/`purpose`/`expires_at`） | 舊版 `request_snapshot` 非必填、`manifest_item_id` 不存在：`task-2-notification-valid.json`（無 `request_snapshot`）舊版會通過，新版因缺 `request_snapshot` 被拒絕，已於同檔補上該欄位使其回到通過；`task-1-booking-create-valid.json` 有 `authorization_use_id` 卻無 `manifest_item_id`，舊版通過、新版拒絕，已補上 `manifest_item_id` 使其回到通過 | `python3 -m unittest tests.domain_contract_test -v` → 13 tests, exit 0（含 `task-1`/`task-2`/`task-crosstenant-parent-ref` 三個 fixture 的補欄位） | 子任務執行前「operation/resource/version/channel/account/amount/purpose/expiry 均在該 manifest item 內」的交叉核對（`manifest_item_id` 指向的那一筆 `scope_manifest` 項目）屬 ENG-02/03 執行期邏輯，本輪只固定雙邊欄位形狀，不新增跨檔案的 Python 級交叉檢查 |
| F4 | `specs/domain/version-compatibility.md`：ExecutionTask 表新增 `WAITING` 列、Work/Task 表新增 `execution_status='RUNNING'→EXECUTING` 列、更正 `READY`/`PARTIAL` 兩列的相容性描述、新增「本輪未覆蓋的歷史狀態機（SM-03／05／06／07）」一節含 RemedyAction | 舊版文件遺漏 `WAITING` 列、誤稱 `READY`/`PARTIAL` 為本輪新增（與 SA `docs/sa/sa-v1.0.md` L216-227 的 SM-01 轉移表事實不符）、完全未提 RemedyAction/SM-03/05/06/07。新版：逐項更正並補列，標註延後理由而非靜默省略 | 文件核對；`python3 scripts/validate_repository.py` → `Repository checks: passed`（186 連結檢查，含本檔新增的 `docs/sa/sa-v1.0.md`／`docs/sd/connector-result-and-reconciliation.md` 錯誤碼/章節引用） | 本檔仍是設計對照文件，不是資料遷移執行紀錄；沒有舊系統資料庫實例可供實際遷移測試（與原表最後一節一致） |
| F5(a) | `specs/domain/work.schema.json`：L257（`failure.irreversible_effects_resolved` 加 `const:true`）、L276-282（`allOf` 七個狀態專屬欄位全部補 `else: not required`）、L104-120（`CompletionEvidence` 新增必填 `tenant_id`/`id`/`work_id`，選用 `task_id`）、L211/L227（`partial_summary.completed_items`/`incomplete_items` 加 `minItems:1`） | 舊版對這四個情況都放行：(1) `status=FAILED` 但 `failure.irreversible_effects_resolved=false` 曾可通過，見新增 `examples/work/work-invalid-failed-irreversible-not-resolved.json`；(2) `status=RUNNING` 卻帶 `completion_record` 曾可通過，見 `work-invalid-completion-record-wrong-status.json`；(3) `partial_summary.completed_items=[]` 曾可通過，見 `work-invalid-partial-summary-empty.json`；(4) `CompletionEvidence` 缺 `id`/`tenant_id`/`work_id` 無法被 `completion_record.evidence_refs`（`TenantScopedRef`）實際指涉。新版：上述三個新 fixture 全部被拒絕；`work-1-booking-valid.json` 新增 `completion_evidence` 陣列，其 `id` 與 `completion_record.evidence_refs[0].id` 一致，證明新欄位足以支撐該參照 | `python3 -m unittest tests.domain_contract_test -v` → 13 tests, exit 0（三個新 invalid fixture 已在 `FIXTURES` 中斷言為 `False`） | 三個新 fixture 的「舊版會通過」是依對舊版 schema 原始碼（`git show cee3e4e2:specs/domain/work.schema.json`）逐條核對缺少對應約束得出的精確靜態證據；嘗試用 Python 腳本實際對舊版 schema 重放這三個 instance 以取得逐字輸出時，Bash 工具的 `orchestrator_approval_broker` 兩次卡滿 1800 秒逾時，未能取得該動態輸出，故在此以靜態條文比對取代 |
| F5(b) | `specs/domain/decision-request.schema.json` L53-55（`selected_option_id` 加 `minLength:1`）、L84-88（`allOf` 的 `then/else`：非 `APPROVED/REJECTED` 時禁止 `selected_option_id`） | 舊版只有 `then`（APPROVED/REJECTED 時要求），`status=PENDING` 同時帶 `selected_option_id` 不受約束、曾可通過，見新增 `examples/decision-request/decision-invalid-pending-with-selection.json`。新版：該 fixture 被拒絕；`decision-1-pending-valid.json`（PENDING、無 `selected_option_id`）仍通過 | `python3 -m unittest tests.domain_contract_test -v` → 13 tests, exit 0 | 同上，舊版行為為靜態條文核對（舊 `allOf` 只有一個 `if/then`，沒有 `else`，必然放行），非本輪重新執行舊 SHA |
| F5(c) | `specs/domain/common/money.schema.json` L29-33（`SignedMinorUnitsAmount` pattern 由 `^-?(0\|[1-9][0-9]*)$` 改為 `^(0\|-?[1-9][0-9]*)$`） | 舊 pattern `-?` 可匹配空字串再接 `0`，故 `"-0"` 合法；新增 fixture `examples/common/signed-minor-units-amount-invalid-negative-zero.json`（值為 `"-0"`）舊版通過、新版被拒絕；`signed-minor-units-amount-valid-negative.json`（`"-500"`）兩版皆通過 | `python3 -m unittest tests.domain_contract_test.FixtureValidation -v` → exit 0（兩個新 fixture 以 `#/$defs/SignedMinorUnitsAmount` fragment 驗證） | 無；這是純 regex 修正，可用正則本身直接核對 `re.fullmatch('^-?(0\|[1-9][0-9]*)$', '-0')` 確實匹配（舊 pattern），`re.fullmatch('^(0\|-?[1-9][0-9]*)$', '-0')` 不匹配（新 pattern） |
| F6 | `specs/domain/examples/execution-attempt/attempt-invalid-duplicate-attempt-no.json`（`request_hash` 從 62 字元改為標準 64 字元 hex）；新增 `attempt-invalid-bad-outcome.json`（`outcome="SUPPORTED"`）；`tests/domain_contract_test.py` 新增 `FixtureCoverage` 測試類別逐一核對 `examples/**/*.json` 都被 `FIXTURES` 引用；`error-codes.json` L29 `§3.3→§3.2`、L43 `§9→§10` | 舊版 `request_hash` 為 `"f"*62`，不符 `^[0-9a-f]{64}$`（已用 `len()` 核實，見下方命令）；該 fixture 原本只被 `CrossInstanceInvariants` 當資料用，不在 `FIXTURES`，`execution-attempt.schema.json` 在 `FIXTURES` 中 0 筆被拒絕範例，與 `specs/domain/README.md`「每個實體至少一組應通過與一組應拒絕」承諾不符。新版：hash 修正為標準 64 字元並以 `(execution-attempt.schema.json, None, attempt-invalid-duplicate-attempt-no.json, True)` 併入 `FIXTURES`（形狀合法，重複僅由 Python 級 `test_duplicate_attempt_no_on_same_task_is_detected` 偵測，與既有 `authorization-use-2` 同模式）；新增的 `attempt-invalid-bad-outcome.json` 以 `(execution-attempt.schema.json, None, ..., False)` 提供該實體第一個 schema 拒絕範例 | `python3 -c "print(len('f'*64))"` → `64`；`python3 -m unittest tests.domain_contract_test -v` → 13 tests, exit 0（含新 `FixtureCoverage` 測試）；`python3 scripts/validate_repository.py` → `Repository checks: passed` | `error-codes.json` 的章節號修正是依讀 `docs/sd/authorization-and-approval.md`（`AUTHORIZATION_STALE` 的 stale 規則落於 §3.2 結尾，非獨立 §3.3）與 `docs/sd/connector-result-and-reconciliation.md`（`SD-C-06` 列於 §10「負向驗收」表格內，非 §9）直接核對章節標題得出，純文件引用修正 |

### 關於舊版動態重現受阻的說明

上表多筆 finding 的「舊版重現」欄位採用「讀取 `git show cee3e4e2:<path>` 取得的 R1 審查當時原始碼，逐條核對缺少
對應 `required`/`pattern`/`allOf`/`anyOf` 約束」的精確靜態證據，而非重新對舊 SHA 執行一次指令取得逐字輸出。
本輪兩次嘗試用獨立 Python 腳本（讀取 `git show` 匯出的舊版 schema 檔，建立 `jsonschema.RefResolver`/`Draft202012Validator`
動態驗證新 fixture）取得該輸出時，本機 Bash 工具的 `orchestrator_approval_broker` 皆在同一類指令上卡滿 1800 秒逾時
中止執行，兩次均未取得任何輸出或錯誤訊息，推測是該 MCP 審批伺服器本身無回應，非程式邏輯問題。沒有進一步重試
（避免再次佔用 30 分鐘且無產出）；上表已改用靜態條文比對頂替，依 §0.7「若無法重現，記錄缺少的具體條件與已有
靜態證據」處理。本輪已完成且確實執行成功、取得逐字輸出的指令（`python3 -m unittest tests.domain_contract_test -v`、
`python3 scripts/validate_repository.py`、`python3 -c "print(len('f'*64))"`）皆針對修正後的新版本，退出碼與結果如上表所列。
