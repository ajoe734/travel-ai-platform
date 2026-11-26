# ENG-06 驗收對照表

依 [AI_COLLABORATION_GUIDE.md §0.7](../../AI_COLLABORATION_GUIDE.md) 的交接格式，逐項列出
[backlog ENG-06](../../docs/collaboration/backlog.md#eng-06商家工作台接真實工作狀態) 的「產出」與「驗收」，對照本次
實際檔案、測試命令與結果。此表是這個候選的 handoff 證據來源；handoff 摘要只引用它，不重複貼全部內容。

執行環境：本機 Python 3.12（`jsonschema` 4.10.3，已安裝，未另行引入新依賴）、Node `v24.22.3`。未啟動資料庫、
瀏覽器或外部 connector（連接器用的是 ENG-04 既有 `OtaDelayedPublicationMock`，非真實渠道）。

## 產出對照

| 產出（backlog 原文） | 原始碼依據與修改位置 | 驗證 |
|---|---|---|
| 商家工作清單 | `services/workbench/service.py::get_home_view` | `tests.workbench_service_test.RefreshResumesWork` |
| 補資料 | `services/workbench/service.py::submit_missing_input`；`specs/workbench/service-revision.schema.json` 的 `asset_ref`/`asset_waived`/`rights_confirmed` 完整性規則 | `tests.workbench_service_test.DecisionLifecycleGuards.test_submitting_input_while_already_waiting_on_decision_is_rejected` 等 |
| 決策卡 | `services/workbench/service.py::request_decision`/`submit_decision`；`specs/domain/decision-request.schema.json`（ENG-01，未改動） | `tests.workbench_service_test.DecisionLifecycleGuards`、`ProposalPreservesVerbatimContent` |
| 執行進度 | `services/workbench/service.py::advance_execution`/`get_work_status`；`specs/domain/execution-task.schema.json`（ENG-01，未改動）；`connectors/mocks/ota_delayed_publication.py`（ENG-04，未改動） | `tests.workbench_service_test.PendingNeverShownAsSuccess`、`PartialResultsAreHonest` |
| 完成證據 | `services/workbench/service.py::_apply_operation_result`（`Succeeded`→`CompletionEvidence`）；`specs/domain/work.schema.json#/$defs/CompletionEvidence`（ENG-01，未改動） | `tests.workbench_service_test.StoredEntitiesMatchDomainSchemas` |
| 沿用 UX 2.1 可驗證互動，補 Work 模型，不照搬 localStorage／timer | `prototypes/merchant-assistant/workbench/index.html`（新檔，`ux-v2.1/index.html` 原檔未改動）；對照見 `docs/verification/prototype-audit.md` §6.1、§9 | `tests/workbench_frontend_test.cjs`；`node tests/prototype-regression.cjs` 仍對原 UX 2.1 檔案 18/18 通過（未受影響） |

## 驗收對照

| 驗收項（backlog 原文） | 原始碼依據 | 命令、結果 | 未驗項與具體限制 |
|---|---|---|---|
| 後端仍 pending 時首頁不顯示已成功 | `services/workbench/service.py` 的 `_CHANNEL_DISPLAY_STATE`（只有 `ExecutionTask.status=DONE` 才顯示 `live`）；前端 `renderWorkStatus`/`channelLine` 同一套映射 | `python3 -m unittest tests.workbench_service_test.PendingNeverShownAsSuccess -v` → 3 tests OK；`node tests/workbench_frontend_test.cjs` → `Pending status never renders as live until a terminal readback lands` PASS | 僅驗證應用層狀態映射；真正的渠道審核 SLA、webhook 到達延遲是 ENG-04/09 範圍 |
| 刷新可恢復工作 | `services/workbench/repository.py`（狀態只存在伺服器端記憶體，前端不寫 `localStorage`）；前端 `let homeItems` 無任何持久化語句 | `python3 -m unittest tests.workbench_service_test.RefreshResumesWork -v` → 2 tests OK；`node tests/workbench_frontend_test.cjs` → `A second page load resumes the same work from the server, no localStorage` PASS | 這裡的「刷新」是重新建立一個綁同一份 store 的 `WorkbenchService`／重跑前端腳本，模擬同一後端被重新讀取；沒有真實瀏覽器 reload 或伺服器重啟，兩者的差異留給 ENG-02（真正持久化）驗收 |
| 模型解析出的內容可核對且不被固定範例覆蓋 | `services/workbench/service.py::propose_service_revision` 強制 `fields['content'] == merchant_text`；`display_payload` 直接是商家送入的 `draft`，不經任何改寫 | `python3 -m unittest tests.workbench_service_test.ProposalPreservesVerbatimContent -v` → 2 tests OK；`node tests/workbench_frontend_test.cjs` → `Merchant's own text is shown verbatim, not a canned example` PASS | 本服務不做任何自然語言「解析」——結構化欄位（價格/時長/容量等）由呼叫端（未來的 NLU 層或商家表單）提供並與 `content` 一起送入；本輪只保證伺服器與前端都不會拿固定範例覆蓋它，解析正確性本身不在 ENG-06 範圍 |
| 容量等不合法值在前後端都被拒絕 | 後端：`services/workbench/service.py::_validate_bounds` 以 `specs/workbench/service-revision.schema.json`（`capacity` 1–8、`duration_minutes` 15–300）+ Python 層價格 ≥ 1 檢查；前端：`validateProposal()` 同一組邊界，送出前即擋下 | `python3 -m unittest tests.workbench_service_test.InvalidFieldsRejectedByBackend -v` → 5 tests OK；`node tests/workbench_frontend_test.cjs` → `Zero/over-cap capacity is rejected client-side...` 與 `A hostile client bypassing the form...` 均 PASS（後者模擬跳過表單直接打 API，證明後端獨立擋下） | 容量上限 8 人是沿用原型的示範資源設定，不是正式庫存規則（見 schema 檔內註記）；正式容量/庫存檢查是 ENG-02 資源表範圍 |
| 正常工作不用商家逐步按執行按鈕 | `services/workbench/service.py::advance_execution`/`simulate_channel_review_result` 明確標記「worker tick／測試專用，非商家端點」；`specs/workbench/api-contract.md` 的「不是商家端點」一節；前端完全不提供渠道層級的「執行」按鈕 | `python3 -m unittest tests.workbench_service_test.NormalFlowNeedsNoPerStepExecuteButton -v` → 1 test OK；`node tests/workbench_frontend_test.cjs` → `Approving never renders a per-channel execute button` PASS（以正規表示式核對渲染出的 `data-act` 只有 `decide`/`request-decision`/`provide-asset`/`waive-asset`，沒有任何 `execute` 字樣） | 本輪的「worker」是測試或呼叫端顯式呼叫 `advance_execution`；正式排程器（cron/queue）是 ENG-05/09 範圍，這裡只保證介面形狀不要求商家操作 |

## 自檢發現並修正的缺陷（實作中自測，非外部 review）

| 觸發情境 | 原始碼位置 | 修正前 → 修正後 | 驗證 |
|---|---|---|---|
| 商家已補齊素材（或選擇不提供英文版）後，尚未呼叫 `request_decision` 前查詢首頁 | `services/workbench/service.py::submit_missing_input`/`get_home_view` | 修正前：`work["waiting_input"]["missing_fields"] = _missing_fields(draft) or work["waiting_input"]["missing_fields"]` 在已補齊（`_missing_fields` 回空陣列）時因 `[] or X` 取到舊值，首頁會持續顯示「需要你提供素材」，即使商家已處理；修正後：該欄位只在仍有缺項時更新（滿足 `work.schema.json` 的 `missing_fields minItems:1`），`get_home_view` 改為即時用 `_missing_fields(draft)` 重新計算顯示值，不信任可能過期的快取欄位 | `python3 -m unittest tests.workbench_service_test.HomeViewReflectsActualMissingFields -v` → 2 tests OK（分別覆蓋「一次補齊」與「先補素材、後補用途確認」兩種到達完整的路徑） |

## 交叉核對命令

```bash
$ python3 -m unittest tests.workbench_service_test -v
...
Ran 22 tests in 2.5s
OK

$ node tests/workbench_frontend_test.cjs
...
{"checks": 6, "passed": 6, "failed": 0}
(exit code 0)

$ python3 -m unittest tests.domain_contract_test tests.connector_contract_test -v
...
Ran 54 tests
OK

$ node tests/prototype-regression.cjs
...
{"checks": 18, "passed": 18, "failed": 0, "observations": [...]}
(exit code 0; UX 2.1 原檔未改動，既有兩項 documented_limitation 不受影響)

$ python3 scripts/validate_repository.py
Repository checks: passed
Original files verified: 12
Local documentation links checked: 196
JavaScript scripts checked: 4
```

## 候選同步紀錄：與 dev 合併（ENG-02 落地後）

PR #8 於 2026-11-26 交接審查後，`dev` 併入 ENG-02（#7，`06de29d`：可執行 DB baseline、repository
層、多租戶 RLS），導致 `claude/eng-06`（原候選 `d3aa041`）與 `origin/dev` 產生衝突
（`mergeStateStatus=DIRTY`，`mergeable=CONFLICTING`）。無任何 review 已核准此候選
（`reviewDecision` 為空、`reviews: []`），故依指引在本 task worktree 以
`git merge origin/dev` 同步，非 rebase/force-push。

| 項目 | 內容 |
|---|---|
| 衝突檔案 | `specs/domain/error-codes.json`（唯一衝突）：ENG-06 與 ENG-02 各自在同一陣列尾端新增錯誤碼。解法：兩邊都保留——ENG-06 的 `INVALID_SERVICE_REVISION_FIELD`／`MISSING_REQUIRED_INPUT`／`DECISION_NOT_PENDING`／`DECISION_OPTION_UNKNOWN`／`WORK_NOT_FOUND`／`WORK_PHASE_MISMATCH`，加上 ENG-02 的 `IMMUTABLE_RECORD`。合併後 19 碼無重複（`python3 -c` 核對 `len(codes)==len(set(codes))==19`）。 |
| 非衝突變更 | `db/`、`tests/db/`、`.github/workflows/repository-validation.yml`（新增 `db-migration-lifecycle` job）為 ENG-02 新增，與 `services/workbench/`、`prototypes/merchant-assistant/workbench/` 無交集；ENG-06 的 in-memory `services/workbench/repository.py` 未被要求改接 ENG-02 的 `db/repository/`（整合驗收仍待 ENG-05，見下方「未驗項」）。 |
| 新 candidate SHA | `c67b4a2`（merge commit，base 為 `d3aa041` + `origin/dev@06de29d`），已 push 到 `origin/claude/eng-06`（非 force push） |
| 回歸結果 | 下列「交叉核對命令」已在合併後的工作樹重跑：22/22、6/6、54/54、18/18 不變；`validate_repository.py` 仍 passed，`Local documentation links checked` 由 196 增至 211（dev 新增 `db/README.md` 等文件連結，非 ENG-06 範圍變動） |
| 未執行 | `.github/workflows/repository-validation.yml` 新增的 `db-migration-lifecycle` job 需要 PostgreSQL service container；本 VM 限制不可啟動 DB/Docker，僅能交由 hosted CI 執行並讀結果，不在本機宣稱通過 |

## 未驗項總覽（不重複上表逐項備註）

- 沒有啟動 PostgreSQL／Docker／瀏覽器（VM 限制）；`services/workbench/repository.py` 的持久層語意與
  `prototypes/merchant-assistant/workbench/index.html` 的真實瀏覽器互動（鍵盤、螢幕閱讀器、檔案上傳）
  未經實測，僅有 Node `vm` 的 headless 核對。
- 沒有真正的 HTTP 伺服器把 `specs/workbench/api-contract.md` 的端點接到 `services/workbench/service.py`；
  `tests/workbench_frontend_test.cjs` 的 `FakeWorkbenchServer` 是測試替身，不是產品會出貨的第二套實作。
- `AuthorizationUse`／跨 Work 政策重用（ENG-03 的 `services/authorization`）尚未與本服務整合；本服務核准路徑
  直接消費自己的 `DecisionRequest`，未來接上 ENG-03 時需要再核對兩者的 `tenant_id`/`revision` 語意是否一致。
- `services/workbench/canonical_json.py` 不是 SD-A-09 要求的跨語言驗證過的正式 canonical encoder。
