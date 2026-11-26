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
| 容量等不合法值在前後端都被拒絕 | 後端：`services/workbench/service.py::_validate_bounds` 以 `specs/workbench/service-revision.schema.json`（`capacity` 1–8、`duration_minutes` 15–300）+ Python 層價格 ≥ 1 檢查；前端：`validateProposal()` 同一組邊界，送出前即擋下 | `python3 -m unittest tests.workbench_service_test.InvalidFieldsRejectedByBackend -v` → 5 tests OK；`node tests/workbench_frontend_test.cjs` → `Zero/over-cap capacity is rejected client-side...` 與 `A hostile client bypassing the form...` 均 PASS（後者是對 `FakeWorkbenchServer` 這個測試替身直接打 `fetch`，證明替身複製了同一組邊界；真正後端獨立擋下的證據是左欄 `InvalidFieldsRejectedByBackend` 對 `services/workbench/service.py` 本身的呼叫，不是這個前端替身測試） | 容量上限 8 人是沿用原型的示範資源設定，不是正式庫存規則（見 schema 檔內註記）；正式容量/庫存檢查是 ENG-02 資源表範圍 |
| 正常工作不用商家逐步按執行按鈕 | `services/workbench/service.py::advance_execution`/`simulate_channel_review_result` 明確標記「worker tick／測試專用，非商家端點」；`specs/workbench/api-contract.md` 的「不是商家端點」一節；前端完全不提供渠道層級的「執行」按鈕 | `python3 -m unittest tests.workbench_service_test.NormalFlowNeedsNoPerStepExecuteButton -v` → 1 test OK；`node tests/workbench_frontend_test.cjs` → `Approving never renders a per-channel execute button` PASS（實際斷言：`hasExecuteButton` 以正規表示式核對渲染出的 `data-act` 沒有任何含 `execute` 字樣；`onlyKnownActs` 核對核准後卡片渲染出的 `data-act` 只有 `decide`——這是決策卡自身按鈕的斷言，不是「全站只有這四種 data-act」的宣稱，`provide-asset`/`waive-asset`/`request-decision`/`confirm-rights` 只出現在 `WAITING_INPUT` 階段的卡片，兩者不同時渲染） | 本輪的「worker」是測試或呼叫端顯式呼叫 `advance_execution`；正式排程器（cron/queue）是 ENG-05/09 範圍，這裡只保證介面形狀不要求商家操作 |

## 自檢發現並修正的缺陷（實作中自測，非外部 review）

| 觸發情境 | 原始碼位置 | 修正前 → 修正後 | 驗證 |
|---|---|---|---|
| 商家已補齊素材（或選擇不提供英文版）後，尚未呼叫 `request_decision` 前查詢首頁 | `services/workbench/service.py::submit_missing_input`/`get_home_view` | 修正前：`work["waiting_input"]["missing_fields"] = _missing_fields(draft) or work["waiting_input"]["missing_fields"]` 在已補齊（`_missing_fields` 回空陣列）時因 `[] or X` 取到舊值，首頁會持續顯示「需要你提供素材」，即使商家已處理；修正後：該欄位只在仍有缺項時更新（滿足 `work.schema.json` 的 `missing_fields minItems:1`），`get_home_view` 改為即時用 `_missing_fields(draft)` 重新計算顯示值，不信任可能過期的快取欄位 | `python3 -m unittest tests.workbench_service_test.HomeViewReflectsActualMissingFields -v` → 2 tests OK（分別覆蓋「一次補齊」與「先補素材、後補用途確認」兩種到達完整的路徑） |

## R1 review reopen 逐項修復（Antigravity，候選 `d3aa041010e6`）

Reviewer 在 `d3aa041010e6` 上以 `reopen` 退回 F1–F5，逐項記錄原始碼依據、舊版重現與修正版結果；新
candidate SHA 見下方「交叉核對命令」後的 commit。

| Finding | 原始碼依據與修改位置 | 舊版重現 → 修正版結果 | 命令與證據 | 未驗項 |
|---|---|---|---|---|
| F1(a) 跨租戶 case_id | `services/workbench/service.py::propose_service_revision`：新增 `case_id['tenant_id']==tenant_id` 檢查，否則 `CrossTenantReferenceRejectedError` | 舊版：對 `d3aa041010e6` 執行 `TenantAndApprovalTimingGuards.test_proposing_against_another_tenants_case_id_is_rejected` 失敗（`CrossTenantReferenceRejectedError not raised`，TENANT_A 成功建立引用 TENANT_B case_id 的 Work）；修正版：同測試通過 | `python3 -m unittest tests.workbench_service_test.TenantAndApprovalTimingGuards -v`（舊版跑法：`git show d3aa041:services/workbench/service.py` 暫代目前檔案再跑，見下方指令區塊） | — |
| F1(b) 過期決策仍可核准 | `services/workbench/service.py::submit_decision`：新增 `_parse_timestamp(now) >= _parse_timestamp(decision['expires_at'])` 檢查，否則 `DecisionNotPendingError`（error-codes.json 既有語意已含「過期」） | 舊版：`test_approving_an_expired_decision_is_rejected_not_run_into_running` 失敗（過期決策仍被核准進入 `RUNNING`）；修正版：通過，Work 停留 `WAITING_DECISION` | 同上 `TenantAndApprovalTimingGuards` | — |
| F2(a)/(b) advance_execution 狀態防呆與終態不可變 | `services/workbench/service.py::advance_execution` 開頭新增 `work["status"] not in ("RUNNING","WAITING_EXTERNAL")` 一併擋下兩種情境：非執行期狀態呼叫、終態重複 tick | 舊版：`ExecutionPhaseGuards` 4 個案例中 3 個因缺 GROUP task 丟出未捕獲 `StopIteration`（而非預期的 `WorkPhaseMismatchError`），第 4 個（終態重跑）`completed_at`/`revision` 被覆寫；修正版：4 個全部通過，终態 `completed_at`＝`rev` 不變 | `python3 -m unittest tests.workbench_service_test.ExecutionPhaseGuards -v` | 本服務沒有持久 lease/fence（ENG-02/05 範圍），此檢查只擋狀態不符，不處理多 worker 併發 |
| F3(a) 補資料權利狀態污染 | `services/workbench/service.py::submit_missing_input`：換 `asset_ref` 時不再沿用舊 `rights_confirmed`（改為 `bool(rights_confirmed)`），並拒絕空字串 `asset_ref` 與 `asset_ref`+`asset_waived` 同時提供 | 舊版：`test_replacing_the_asset_resets_rights_confirmation` 失敗（新素材仍顯示 `missing_fields=[]`，未重新要求授權確認）；`test_empty_asset_ref_is_rejected`／`test_asset_ref_and_asset_waived_together_is_rejected` 均未拋錯；修正版：3 個全部通過 | `python3 -m unittest tests.workbench_service_test.RightsConfirmationIsPerAsset -v` | — |
| F3(b) 前端補資料卡誤導至死路 | `prototypes/merchant-assistant/workbench/index.html::renderMissingInput`：依 `missing_fields` 內容分三支（缺素材／缺授權確認／已齊），缺授權確認時改渲染新的 `confirm-rights` 按鈕；`handle()` 新增 `confirm-rights` 分支呼叫 `/input` 帶 `rights_confirmed:true` | 舊版：`FakeWorkbenchServer` 不曾模擬「素材已給、授權未確認」這個 `missing_fields=['rights_confirmed']` 狀態（一律回 `[]`），測試替身本身就無法重現；已先補強替身後，再對照舊版前端跑同一案例失敗（`offersConfirmNotDeadEnd:false`，渲染出 `request-decision` 導向 422 死路）；修正版：通過 | `node tests/workbench_frontend_test.cjs` → `An asset that still needs rights confirmation offers a confirm button, not a dead-end request-decision` PASS | 未驗證真實瀏覽器點擊，只有 Node vm 核對渲染出的 `data-act` 與呼叫路徑 |
| F4(a) 前端錯誤被後續 refresh() 清空 | `index.html::refresh()` 移除其中的 `setError('')`；`handle()` 開頭改為在嘗試新動作時才 `setError('')` | 舊版：核准卡片用錯誤 hash 觸發 `AUTHORIZATION_STALE` 後，`catch` 設完錯誤訊息緊接著呼叫的 `refresh()` 會把訊息立刻清空（`errorSurvivesRefresh:false`）；修正版：錯誤訊息在下一次動作前持續顯示，下一動作開始時才清除 | `node tests/workbench_frontend_test.cjs` → `An error banner survives the refresh() that follows it, and clears when a new action starts` PASS | — |
| F4(b) PARTIAL 未完成原因雙重跳脫 | `index.html::renderWorkStatus` 的 `PARTIAL` 分支移除對已逐項 `esc()` 過的 `incomplete` 字串的外層再 `esc()` | 舊版：含單引號的拒絕原因會被轉成 `&amp;#39;`（雙重編碼）；修正版：只編碼一次 | `node tests/workbench_frontend_test.cjs` → `Incomplete-item reasons are escaped once, not double-encoded` PASS | 本測試的拒絕原因是 `FakeWorkbenchServer` 固定文字 `channel rejected`，不含單引號；驗證邏輯改為斷言輸出不含 `&amp;#39;`/`&amp;quot;` 這組雙重編碼特徵，而非真的送入含引號的原因文字（連接器的 `fail_reason` 內容不在本服務控制範圍） |
| F4(c) 遺失 objective、COMPLETED 未呈顯完成證據、WAITING_EXTERNAL 未區分 RESULT_UNKNOWN/KNOWN_PENDING | `index.html::renderWorkStatus` 改接收整個 `item`（含 `objective`）而非只有 `work_status`；`render()` 呼叫改為 `renderWorkStatus(item)`；`COMPLETED` 分支加上 `completion_record.completed_at` 文字；一般等待分支依 `waiting_external.waiting_reason` 顯示不同文字 | 舊版：三者皆無——`renderWorkStatus(ws)` 從未拿到 `item.objective`；`COMPLETED` 卡片只有渠道徽章；`RESULT_UNKNOWN`／`KNOWN_PENDING` 一律顯示同一句「核對中」；修正版：三者皆通過 | `node tests/workbench_frontend_test.cjs` → `A completed work shows its objective and completion evidence, a WAITING_EXTERNAL result-unknown is distinguished from known-pending` PASS | 完成證據目前只顯示 `completed_at`；逐渠道 `CompletionEvidence.external_ref`/`observed_at` 的完整呈現留給正式 HTTP 層落地後再擴充 UI |
| F5(a) 契約漂移：request-decision 缺 `expires_at` | `index.html::handle()` 的 `request-decision` 分支新增 `expires_at`（`Date.now()+24h` 的 ISO 字串）送入請求體，符合 `specs/workbench/api-contract.md` 的 `{tenant_id, expires_at}` | 舊版：前端從未送 `expires_at`；`tests/workbench_frontend_test.cjs` 的 `FakeWorkbenchServer.requestDecision` 補強為「缺 `expires_at` 即拋 422」後，對舊版前端重跑確實拋錯（`status_seen:"WAITING_INPUT"`，卡在原狀態）；修正版：通過，進到 `WAITING_DECISION` | `node tests/workbench_frontend_test.cjs` → `request-decision sends expires_at per specs/workbench/api-contract.md` PASS | 前端用 `Date.now()+24h` 當示範到期時間；正式到期政策（例如依商家角色/渠道不同）是呼叫端（未來 HTTP 層）決定，不是本次修正範圍 |
| F5(b) 驗收文件措辭與實際測試不符 | `specs/workbench/acceptance-trace.md` 本檔：改正上方「驗收對照」表「容量等不合法值在前後端都被拒絕」與「正常工作不用商家逐步按執行按鈕」兩列的描述，不再把 `FakeWorkbenchServer` 測試替身的結果說成「後端獨立擋下」，並把 `data-act` 白名單敘述改為對照 `workbench_frontend_test.cjs` 實際斷言（`hasExecuteButton`/`onlyKnownActs` 各自檢查什麼） | 舊版：措辭如 R1 finding 引用；修正版：見上方對應列 | 本檔 diff 本身 | 純文件修正，無可執行命令 |

## 交叉核對命令（修正 F1–F5 後）

```bash
$ python3 -m unittest tests.workbench_service_test -v
...
Ran 31 tests in 3.0s
OK

$ node tests/workbench_frontend_test.cjs
...
{"checks": 11, "passed": 11, "failed": 0}
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
Local documentation links checked: 211
JavaScript scripts checked: 4
```

舊版重現方式（F1/F2/F3a，Python 側）：暫時以 `git show d3aa041:services/workbench/service.py` 的內容取代
目前檔案後，單獨跑 `tests.workbench_service_test.TenantAndApprovalTimingGuards`／`ExecutionPhaseGuards`／
`RightsConfirmationIsPerAsset`，確認全部失敗（3 個失敗＋3 個 `StopIteration` error），再還原修正版重跑確認
全部通過；兩次執行之間未 reset 工作樹，只替換單一檔案內容後再還原。前端側（F3b/F5a）同理以
`git show d3aa041:prototypes/merchant-assistant/workbench/index.html` 暫代，確認對已補強的 `FakeWorkbenchServer`
测试替身失敗後還原。

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
