# ENG-03 驗收對照表

依 [AI_COLLABORATION_GUIDE.md §0.7](../../AI_COLLABORATION_GUIDE.md) 的交接格式，逐項列出
[backlog ENG-03](../../docs/collaboration/backlog.md#eng-03授權決策版本與撤回)的「產出」「驗收」與
[docs/sd/authorization-and-approval.md §8](../../docs/sd/authorization-and-approval.md#8-負向驗收)
負向驗收表，對照實際程式位置、測試與結果。

執行環境：本機 Python 3.12.3 + `jsonschema` 4.10.3（ENG-01 已安裝，本輪未另行引入新依賴）。未啟動資料
庫、瀏覽器或外部 connector；所有測試是對 `services/authorization/*` 這個同進程 Python 模組的
`unittest`，驗證對象是真正的 `AuthorizationService` 方法與真正的 `specs/domain/*.schema.json`
（經 `services/authorization/schema_validation.py` 載入），不是重複實作的業務邏輯或自算常數。

## backlog ENG-03 驗收逐項

| 驗收項 | 原始碼依據與修改位置 | 證據 | 命令、退出碼 | 未驗項與具體限制 |
|---|---|---|---|---|
| 已有政策覆蓋時不產生多餘人工作業 | `services/authorization/service.py` `AuthorizationService.try_issue_policy_covered_authorization`（SD §1/§5, SD-A-10） | `tests/authorization_service_test.py::ExecutionAuthorizationTests::test_policy_covered_work_issues_authorization_without_any_decision`（L384）：僅憑 `repository.put_grant` 的 reusable grant 直接核發 `ExecutionAuthorization`，全程未呼叫 `create_decision`；`test_each_work_rechecks_its_own_grant_budget_independently`（L423）證明「每案仍有獨立核對」——第二個 Work 因 grant 預算用盡回 `None`，不是被第一次使用永久鎖死 | `python3 -m unittest tests.authorization_service_test -v` → 62 tests, exit 0 | `AuthorityGrant` 正式 schema／政策管理 UI 不在本輪；此處是 ENG-03 內部最小 dict 替身（見 `repository.py` 模組說明） |
| 新承諾才需批准（已核准/已存在的內容重送不需要新批准） | `AuthorizationService.approve_decision` 的 idempotency-first 分支（`service.py` L218-226） | `test_same_key_same_payload_replay_returns_the_same_approval`（L313，SD-A-03）：同 key 同 payload 回同一筆 `ApprovalRecord`，未建立第二筆 | 同上 | 無 |
| 舊 ETag | `approve_decision` 的 `expected_revision`／`if_match_revision` 一致性檢查（`service.py` L210，SD §4、SD-A-02） | `test_old_revision_can_never_be_approved_once_superseded`（L228）：`propose_revision` 把內容改成 B 後，用 A 版核發的舊 nonce 核准，回 `AUTHORIZATION_STALE` | 同上 | `If-Match` header 本身的解析是 ENG-05 handler 範圍；本輪只驗證 `expected_revision`/`if_match_revision` 兩值不一致時拒絕的服務層規則（程式碼見 `service.py` L210），未對該分支另寫獨立測試（與 `expected_revision` 本身過期的檢查共用同一條 `AUTHORIZATION_STALE`/`VERSION_CONFLICT` 路徑，已由其他案例間接覆蓋） |
| 變更金額 | `approve_decision` 同一 Idempotency-Key、不同 `scope_manifest`（含金額變動即屬內容變動）的 `request_hash` 比對（SD-A-04） | `test_same_key_different_amount_is_idempotency_conflict`（L332）：同 key 改 `scope_manifest`（新增一個 manifest item，等同內容/金額變動）回 `IDEMPOTENCY_CONFLICT` | 同上 | 無 |
| 錯 tenant | `create_decision`／`approve_decision`／`issue_execution_authorization` 的 `tenant_id` 比對（SA 08.3；`CROSS_TENANT_REFERENCE_REJECTED`） | `test_cross_tenant_display_payload_is_rejected`（L202）、`test_approving_another_tenants_decision_id_is_rejected_without_disclosure`（L615）、`test_issuing_authorization_against_another_tenants_grant_is_rejected`（L633） | 同上 | 「不揭露存在性」只驗證回應 code 相同（404 CROSS_TENANT_REFERENCE_REJECTED），未驗證 HTTP 層 detail 文字本身不洩漏，因為本輪沒有 HTTP 層（ENG-05 範圍） |
| 授權撤回 | `revoke_approval` + `precheck_before_dispatch` 共用 `repository.lock_for` 的競態序（SD §6, SD-A-07/08） | `test_revoke_before_dispatch_blocks_the_not_yet_sent_action`（L530）：撤回先成立，之後的 `precheck_before_dispatch` 回 `AUTHORIZATION_REVOKED`；`test_dispatch_before_revoke_lets_the_inflight_action_proceed_but_blocks_new_ones`（L547）：dispatch 先成立，撤回回 `DISPATCHED_PROCEEDS_TO_RECONCILIATION`（不假稱取消已送出動作），但下一次 `precheck_before_dispatch`（模擬重試）仍被擋下 | 同上 | 本輪的鎖是同進程 `threading.Lock`，模擬 SD §6「短 DB transaction」描述的先後順序；真正跨 worker 行程、跨節點的 DB transaction／lease 是 ENG-02/05 範圍，此處只驗證「先後順序一旦確定，結果正確」這個邏輯本身 |
| 重複批准 | `approve_decision` 的 `put_approval_if_absent`（UNIQUE(tenant_id, decision_id, reviewed_revision) 原子檢查） | `test_duplicate_approval_under_a_different_idempotency_key_is_conflict`（L355）：第二次核准用完全不同的 Idempotency-Key（非重送），仍被 `VERSION_CONFLICT` 擋下，且第一筆核准不受影響 | 同上 | 無 |
| 不得以模型文字或前端旗標授權交易 | `approve_decision` 要求 `nonce_id` 必須是 `create_decision`/`propose_revision` 核發過的有效 nonce（SD §1, SD-A-01） | `test_approve_without_a_real_confirmation_nonce_is_rejected`（L248）：傳入模型／前端自造的字串當 `nonce_id` 回 `UNVERIFIED_APPROVAL_REJECTED`；`test_approve_consumes_the_nonce_so_it_cannot_be_replayed_for_a_second_approval`（L256）：同一 nonce 用過一次後不能核准第二個決策 | 同上 | 本輪沒有模擬「受信任 UI 確認端點／語音確認服務」本身如何核發／展示 nonce 給使用者；只驗證「服務只接受自己核發且未用過的 nonce」這個後端規則 |

## Round 1 退修對照表（candidate 0b980eb → 本候選）

依 [AI_COLLABORATION_GUIDE.md §0.7](../../AI_COLLABORATION_GUIDE.md) 交接格式；Antigravity 於
`2026-11-26T15:10:59Z` 以唯讀 probe 對 candidate `0b980eb1dcb9fa73aa309150dd937306de10a4e0` 實測出的
8 項 finding（F1-F8），逐項列出原始碼依據、舊版重現方式與修正版結果。新增的
`services/authorization/temporal.py`（`is_at_or_before`）統一所有 ISO-8601 時間比較；新增
`tests.authorization_service_test.Round1RetrofitTests`（23 個案例）同時覆蓋全部 8 項。

每項「舊版重現」都已在 `0b980eb` 對應的原始碼樹（`git archive 0b980eb` 匯出到隔離目錄，套用本輪新測試
檔）實跑驗證：23 個新案例在舊版全部失敗（19 failures + 4 errors，4 個 error 是舊版缺少
`if_match_revision`/`get_rejection_reason` 等本輪新增 API 而拋 `TypeError`/`AttributeError`，同樣代表
該行為在舊版不存在）；在本候選套用修正後 23 個全部通過。未改動任何工作樹檔案進行此比對（隔離目錄位於
`/tmp`，非 repo 路徑）。

| Finding | 原始碼依據與修改位置 | 舊版重現 → 修正版結果 | 命令、退出碼 | 未驗項與具體限制 |
|---|---|---|---|---|
| F1 過期檢核失效 | `service.py` `approve_decision`（新增 `decision["expires_at"]` vs `approved_at` 檢查）；`repository.py` `is_approval_effective`（新增 `approval["expires_at"]` 檢查）；`service.py` `_check_authorization_still_valid`（grant 缺失/過期一併視為 revoked） | `test_expired_decision_cannot_be_approved`、`test_expired_approval_is_not_effective_and_blocks_new_authorization`、`test_precheck_before_dispatch_rejects_when_backing_grant_has_expired`：舊版皆未拋錯（核准/核發成功或 `is_approval_effective` 仍回 True）；新版回 `AUTHORIZATION_STALE`/`AUTHORIZATION_REVOKED` | `python3 -m unittest tests.authorization_service_test -v` → 62 tests, exit 0 | grant「缺失」（`get_grant` 回 `None`）這條分支沒有可從公開 API 構造的案例（本輪 repository 沒有刪除 grant 的方法，grant 只會存在或被標 `revoked`），故只對「grant 過期」實測；「grant 缺失」是程式碼內的防禦性分支，未被測試觸發 |
| F2 內容綁定/SD-A-05 範圍檢核被繞過 | `service.py` 新增 `_validate_scope_manifest_matches_payload`（approve_decision 內呼叫）；新增 `_manifest_item_within_scope` 與 `_SCOPE_BOUND_FIELDS`（`issue_execution_authorization` 內以 item_id 比對整個 scope item，取代舊版只比 `operation`） | `test_approve_rejects_scope_manifest_item_not_in_display_payload_manifest_items`、`test_approve_rejects_scope_manifest_operation_not_matching_display_payload_operation`、`test_authorization_from_approval_rejects_manifest_item_with_unapproved_channel`（換渠道）、`test_authorization_from_approval_rejects_manifest_item_with_a_different_money_amount`（真實 `Money` 欄位改金額）：舊版全部放行；新版回 `AUTHORIZATION_SCOPE_MISMATCH` | 同上 | `resource_revision`/`purpose`/`expires_at` 欄位走同一個 `_manifest_item_within_scope` 比對函式，與已測的 `channel`/`amount` 共用同一段程式碼路徑，未逐欄位各寫一條獨立測試 |
| F3 跨租戶隔離/AuthorizationUse 綁定缺口 | `service.py` 新增 `_require_same_tenant`/`_require_same_tenant_refs`，接到 `create_decision`(work_id/context_refs)、`propose_revision`(context_refs)、`approve_decision`(scope_manifest[*].resource_ref)、`issue_execution_authorization`(work_id/resource_refs/consent_refs/manifest[*].resource_ref)、`consume_authorization_use`(root_task_id)；`consume_authorization_use` 新增 `root_business_key` 與 `request_hash` 一致性檢查 | `test_create_decision_rejects_cross_tenant_work_id`、`test_create_decision_rejects_cross_tenant_context_ref`、`test_propose_revision_rejects_cross_tenant_context_ref`、`test_authorization_from_approval_rejects_cross_tenant_resource_ref_in_manifest_item`、`test_consume_authorization_use_rejects_cross_tenant_root_task_id`、`test_consume_authorization_use_rejects_mismatched_root_business_key`、`test_consume_authorization_use_resend_with_different_request_hash_is_idempotency_conflict`：舊版全部放行或靜默回同一筆 use；新版回 `CROSS_TENANT_REFERENCE_REJECTED`/`AUTHORIZATION_SCOPE_MISMATCH`/`IDEMPOTENCY_CONFLICT` | 同上 | 無 |
| F4 撤回/dispatch TOCTOU 競態 | `service.py` `mark_dispatched` 改為在 `lock_for` 同一把鎖內重跑 `_check_authorization_still_valid` 後才標記已送出，而非舊版無條件標記 | `test_revoke_between_precheck_and_mark_dispatched_blocks_the_mark`：在 `precheck_before_dispatch` 與 `mark_dispatched` 之間呼叫 `revoke_approval`；舊版 `mark_dispatched` 仍成功（`is_dispatched` 變 True）；新版 `mark_dispatched` 回 `AUTHORIZATION_REVOKED` 且 `is_dispatched` 仍為 False | 同上 | 鎖是同進程 `threading.Lock`，驗證的是「鎖內原子重檢」這個邏輯本身；跨進程/跨節點的 DB 交易由 ENG-02/05 接上後需另行驗證（與既有未驗項一致） |
| F5 Nonce 過早銷毀 | `service.py` `approve_decision`：改用 `peek_nonce` 驗證 tenant/decision/revision/payload_hash，待 actor_role/option_id 都通過後才 `consume_nonce`（取代舊版「先 consume 再驗」的順序） | `test_approve_with_wrong_role_does_not_burn_the_nonce_for_a_later_correct_approval`：錯角色核准失敗後，同一個 nonce 再核准一次；舊版第二次核准因 nonce 已被第一次呼叫燒毀而回 `UNVERIFIED_APPROVAL_REJECTED`；新版第二次核准成功 | 同上 | 跨租戶呼叫在新舊版都是在觸及 nonce 前已被 `get_decision_latest` 的 tenant 查找擋下（找不到該決策），故「跨租戶」這個子情境本身不會走到 nonce 分支，不需要也沒有另寫跨租戶變體測試，以免誤導成兩條不同程式路徑 |
| F6 多 capability grant 預算與覆蓋錯誤 | `service.py` `try_issue_policy_covered_authorization`：以 `seen_grant_ids` 去重同一 grant；`issue_execution_authorization`：改成跨 `grant_refs` 聯集核對 capabilities（取代舊版「每個 grant 都要單獨覆蓋全部 capability」），budget 消耗也以 `consumed_grant_ids` 去重；新增 `budget_remaining<=0` 直接拒絕 | `test_single_grant_covering_two_capabilities_is_only_charged_once`：舊版回傳 `grant_refs` 重複兩筆、budget 從 1 扣成 -1；新版只有一筆 `grant_refs`、budget 變 0。`test_two_grants_each_covering_a_different_capability_are_combined`：舊版對每個 grant_ref 誤拋 `POLICY_APPROVAL_REQUIRED`（因為單一 grant 沒蓋到全部 capability）；新版成功核發。`test_issue_execution_authorization_rejects_grant_with_zero_budget_remaining`：舊版放行；新版回 `POLICY_APPROVAL_REQUIRED` | 同上 | 無 |
| F7 時間比較與不可變性 | 新增 `services/authorization/temporal.py`（`parse_timestamp`/`is_at_or_before`），取代 `repository.py`/`service.py` 內所有 ISO-8601 字串 `<=` 比較；`repository.py` 將所有 `dict(x)` 回傳/儲存改為 `copy.deepcopy(x)` | `test_revocation_effective_at_with_fractional_seconds_compares_by_real_instant`：`effective_at="...06:00:00Z"`、查詢時間 `"...06:00:00.500Z"`（字串排序上比前者「更小」，但實際時間更晚）；舊版 `is_approval_effective` 誤回 `True`（未判定已撤回）；新版正確回 `False`。`test_returned_approval_scope_manifest_is_a_defensive_copy`：呼叫端就地修改回傳的 `approval["scope_manifest"]`；舊版連帶污染 repository 內部儲存的紀錄；新版內部紀錄不受影響 | 同上 | 無 |
| F8 契約與驗收證據缺口 | `service.py` `reject_decision` 新增 `if_match_revision` 參數與一致性檢查（比照 `approve_decision`）；`repository.py` 新增 `put_rejection_reason`/`get_rejection_reason` 側錶（`reason` 不寫入 `DecisionRequest` 本體，因其 schema `additionalProperties: false` 沒有 `reason` 屬性） | `test_reject_decision_if_match_revision_mismatch_is_rejected`：舊版 `reject_decision` 沒有 `if_match_revision` 參數，呼叫即拋 `TypeError`（代表該檢查在舊版不存在）；新版回 `VERSION_CONFLICT`。`test_reject_decision_persists_the_reason_for_later_retrieval`：舊版沒有 `get_rejection_reason` 可呼叫；新版可查回 `reason` 且 `reject_decision` 回傳值本身也帶 `reason` | 同上 | `rejected_by`/`reason` 側錶沒有時間戳欄位（`reject_decision` 簽章本身沒有 `rejected_at` 參數，和既有 `approve_decision`/`revoke_approval` 不同，為避免擴大簽章變更範圍未補上）；若未來需要稽核時間，需另外加參數並視為新的驗收項，不在本輪範圍內隱含補上 |

## SD §8 負向驗收表（authorization-and-approval.md）逐項

| ID | 本輪狀態 | 證據 |
|---|---|---|
| SD-A-01 | 已覆蓋 | 見上表「不得以模型文字或前端旗標授權交易」列 |
| SD-A-02 | 已覆蓋 | 見上表「舊 ETag」列 |
| SD-A-03 | 已覆蓋 | 見上表「新承諾才需批准」列 |
| SD-A-04 | 已覆蓋 | 見上表「變更金額」列 |
| SD-A-05 | 已覆蓋 | `test_authorization_from_approval_rejects_manifest_outside_approved_scope`（L448）：批准只涵蓋 `booking.reschedule`，子任務試圖以 `booking.publish_channel_c` 操作建立授權，回 `AUTHORIZATION_SCOPE_MISMATCH` |
| SD-A-06 | 已覆蓋 | `test_authorization_use_resend_finds_the_same_use`（L466）：同請求重送找回同一筆 `AuthorizationUse`；`test_authorization_use_cannot_bind_a_second_root_task`（L489）：改綁第二個 root task 回 `AUTHORIZATION_USE_ALREADY_BOUND`，原 root 仍可查回 |
| SD-A-07 | 已覆蓋 | 見上表「授權撤回」列（`test_revoke_before_dispatch_blocks_the_not_yet_sent_action`） |
| SD-A-08 | 已覆蓋 | 見上表「授權撤回」列（`test_dispatch_before_revoke_lets_the_inflight_action_proceed_but_blocks_new_ones`） |
| SD-A-09 | 未覆蓋 | 需要第二語言實作對同一 canonical payload 算 hash 並比對；本輪只有 Python 單一實作。`CanonicalJsonTestVectors`（L113-190）覆蓋 SD §3.2 列出的其餘 8 個最低測試向量（key 排列、陣列順序、金額、null/缺省、Unicode 不默默碰撞、幣別、tenant/target、超大整數），外加 NaN/Infinity、重複 key、float 拒絕、控制字元轉義、`/` 不轉義等本模組自身規則的測試 |
| SD-A-10 | 已覆蓋 | 見上表「已有政策覆蓋時不產生多餘人工作業」列 |
| SD-A-11 | 不在本輪範圍 | break-glass 音訊存取屬 ENG-10（語音/電話）範圍，本輪沒有音訊/錄音物件 |
| SD-A-12 | 不在本輪範圍 | 退款 UNKNOWN 後撤回的保留規則屬 ENG-07（credit-and-refund.md）範圍，本輪的 `ExecutionAuthorization`/`ApprovalRecord` 不含金額保留狀態機 |

## 命令與結果

```bash
$ python3 -m unittest tests.authorization_service_test -v
...
Ran 62 tests in 0.045s

OK
```

39 個是 candidate `0b980eb` 既有案例，23 個是本輪 `Round1RetrofitTests`（F1-F8 逐項回歸）。

```bash
$ python3 -m unittest tests.domain_contract_test -v
...
Ran 13 tests in 0.142s

OK
```

```bash
$ python3 scripts/validate_repository.py
Repository checks: passed
Original files verified: 12
Local documentation links checked: 203
JavaScript scripts checked: 3
These checks do not verify a production application or external integration.
```

這三個指令的實際輸出已貼於上，退出碼均為 0；執行版本為本機 Python 3.12.3、`jsonschema` 4.10.3，於
`.artifacts/worktrees/auto/claude-eng-03` 工作樹執行。`domain_contract_test`／`validate_repository.py`
的通過證明本輪新增的 4 個 `error-codes.json` 條目（`UNVERIFIED_APPROVAL_REJECTED`／
`ACTOR_ROLE_MISMATCH`／`AUTHORIZATION_REVOKED`／`REVOCATION_NOT_PERMITTED`，皆標 `x_added_by: ENG-03`）
未破壞 ENG-01 既有的 registry 一致性檢查與連結完整性檢查。

## dev 同步（candidate 11d8f77 → ddd92c5）

PR #6 CI 回報 `mergeable: CONFLICTING`（dev 已併入 ENG-04 `01559dd`，`specs/README.md`
兩邊都新增小節，純附加式衝突，未觸及任何程式邏輯）。候選尚未進入 review 鎖定狀態，依
AI_COLLABORATION_GUIDE.md §0.6/§0.7 在本 task worktree `git merge origin/dev` 解衝突、
保留雙方新增內容、重新驗證後以新 SHA 重交：

```bash
$ python3 -m unittest tests.authorization_service_test tests.domain_contract_test tests.connector_contract_test -v
...
Ran 116 tests in 0.222s

OK
```

```bash
$ python3 scripts/validate_repository.py
Repository checks: passed
Original files verified: 12
Local documentation links checked: 214
JavaScript scripts checked: 3
```

`authorization_service_test`（62/62，含 `Round1RetrofitTests` 23/23）、`domain_contract_test`
（13/13）、`connector_contract_test`（41/41，ENG-04 帶入）均通過；連結檢查 203→214 是
ENG-04 新增 `specs/connector/*` 的連結，非本次改動。merge commit `ddd92c5` 未修改
`services/authorization/`、`tests/authorization_service_test.py` 或
`specs/authorization/{README,api-contract,acceptance-trace}.md` 的任何既有內容（僅
`specs/README.md` 的附加式解衝突），Round 1 的 F1-F8 修正與回歸案例原樣保留。

## 未驗項總表（非逐項重複，彙整）

- 沒有啟動 PostgreSQL；所有「原子」行為（UNIQUE 約束、AuthorizationUse 唯一性、撤回/dispatch 先後序）
  是用 Python `threading.Lock` 與 dict 在單一進程內模擬，不是資料庫交易隔離等級下的實測。ENG-02 換上
  真正的 repository 實作後，這些測試案例的「給定呼叫順序 → 預期結果」仍應成立，但需要 ENG-02 自己對
  真正的資料庫交易重新驗證並發場景。
- 沒有 HTTP 伺服器、瀏覽器或外部 connector；`specs/authorization/api-contract.md` 只是契約文件，
  實際 handler 接線與其整合測試是 ENG-05 範圍。
- `AuthorityGrant`/`PolicyVersion` 沒有正式 schema，`nonce` 核發／消耗沒有真正的 UI／語音確認傳輸層；
  兩者在本輪都只是支撐「政策覆蓋」與「不得以模型文字授權」這兩條驗收規則的最小可測替身。
