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
| 已有政策覆蓋時不產生多餘人工作業 | `services/authorization/service.py` `AuthorizationService.try_issue_policy_covered_authorization`（SD §1/§5, SD-A-10） | `tests/authorization_service_test.py::ExecutionAuthorizationTests::test_policy_covered_work_issues_authorization_without_any_decision`（L384）：僅憑 `repository.put_grant` 的 reusable grant 直接核發 `ExecutionAuthorization`，全程未呼叫 `create_decision`；`test_each_work_rechecks_its_own_grant_budget_independently`（L423）證明「每案仍有獨立核對」——第二個 Work 因 grant 預算用盡回 `None`，不是被第一次使用永久鎖死 | `python3 -m unittest tests.authorization_service_test -v` → 39 tests, exit 0 | `AuthorityGrant` 正式 schema／政策管理 UI 不在本輪；此處是 ENG-03 內部最小 dict 替身（見 `repository.py` 模組說明） |
| 新承諾才需批准（已核准/已存在的內容重送不需要新批准） | `AuthorizationService.approve_decision` 的 idempotency-first 分支（`service.py` L218-226） | `test_same_key_same_payload_replay_returns_the_same_approval`（L313，SD-A-03）：同 key 同 payload 回同一筆 `ApprovalRecord`，未建立第二筆 | 同上 | 無 |
| 舊 ETag | `approve_decision` 的 `expected_revision`／`if_match_revision` 一致性檢查（`service.py` L210，SD §4、SD-A-02） | `test_old_revision_can_never_be_approved_once_superseded`（L228）：`propose_revision` 把內容改成 B 後，用 A 版核發的舊 nonce 核准，回 `AUTHORIZATION_STALE` | 同上 | `If-Match` header 本身的解析是 ENG-05 handler 範圍；本輪只驗證 `expected_revision`/`if_match_revision` 兩值不一致時拒絕的服務層規則（程式碼見 `service.py` L210），未對該分支另寫獨立測試（與 `expected_revision` 本身過期的檢查共用同一條 `AUTHORIZATION_STALE`/`VERSION_CONFLICT` 路徑，已由其他案例間接覆蓋） |
| 變更金額 | `approve_decision` 同一 Idempotency-Key、不同 `scope_manifest`（含金額變動即屬內容變動）的 `request_hash` 比對（SD-A-04） | `test_same_key_different_amount_is_idempotency_conflict`（L332）：同 key 改 `scope_manifest`（新增一個 manifest item，等同內容/金額變動）回 `IDEMPOTENCY_CONFLICT` | 同上 | 無 |
| 錯 tenant | `create_decision`／`approve_decision`／`issue_execution_authorization` 的 `tenant_id` 比對（SA 08.3；`CROSS_TENANT_REFERENCE_REJECTED`） | `test_cross_tenant_display_payload_is_rejected`（L202）、`test_approving_another_tenants_decision_id_is_rejected_without_disclosure`（L615）、`test_issuing_authorization_against_another_tenants_grant_is_rejected`（L633） | 同上 | 「不揭露存在性」只驗證回應 code 相同（404 CROSS_TENANT_REFERENCE_REJECTED），未驗證 HTTP 層 detail 文字本身不洩漏，因為本輪沒有 HTTP 層（ENG-05 範圍） |
| 授權撤回 | `revoke_approval` + `precheck_before_dispatch` 共用 `repository.lock_for` 的競態序（SD §6, SD-A-07/08） | `test_revoke_before_dispatch_blocks_the_not_yet_sent_action`（L530）：撤回先成立，之後的 `precheck_before_dispatch` 回 `AUTHORIZATION_REVOKED`；`test_dispatch_before_revoke_lets_the_inflight_action_proceed_but_blocks_new_ones`（L547）：dispatch 先成立，撤回回 `DISPATCHED_PROCEEDS_TO_RECONCILIATION`（不假稱取消已送出動作），但下一次 `precheck_before_dispatch`（模擬重試）仍被擋下 | 同上 | 本輪的鎖是同進程 `threading.Lock`，模擬 SD §6「短 DB transaction」描述的先後順序；真正跨 worker 行程、跨節點的 DB transaction／lease 是 ENG-02/05 範圍，此處只驗證「先後順序一旦確定，結果正確」這個邏輯本身 |
| 重複批准 | `approve_decision` 的 `put_approval_if_absent`（UNIQUE(tenant_id, decision_id, reviewed_revision) 原子檢查） | `test_duplicate_approval_under_a_different_idempotency_key_is_conflict`（L355）：第二次核准用完全不同的 Idempotency-Key（非重送），仍被 `VERSION_CONFLICT` 擋下，且第一筆核准不受影響 | 同上 | 無 |
| 不得以模型文字或前端旗標授權交易 | `approve_decision` 要求 `nonce_id` 必須是 `create_decision`/`propose_revision` 核發過的有效 nonce（SD §1, SD-A-01） | `test_approve_without_a_real_confirmation_nonce_is_rejected`（L248）：傳入模型／前端自造的字串當 `nonce_id` 回 `UNVERIFIED_APPROVAL_REJECTED`；`test_approve_consumes_the_nonce_so_it_cannot_be_replayed_for_a_second_approval`（L256）：同一 nonce 用過一次後不能核准第二個決策 | 同上 | 本輪沒有模擬「受信任 UI 確認端點／語音確認服務」本身如何核發／展示 nonce 給使用者；只驗證「服務只接受自己核發且未用過的 nonce」這個後端規則 |

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
Ran 39 tests in 0.022s

OK
```

```bash
$ python3 -m unittest tests.domain_contract_test -v
...
Ran 13 tests in 0.139s

OK
```

```bash
$ python3 scripts/validate_repository.py
Repository checks: passed
Original files verified: 12
Local documentation links checked: 186
JavaScript scripts checked: 3
These checks do not verify a production application or external integration.
```

這三個指令的實際輸出已貼於上，退出碼均為 0；執行版本為本機 Python 3.12.3、`jsonschema` 4.10.3，於
`.artifacts/worktrees/auto/claude-eng-03` 工作樹執行。`domain_contract_test`／`validate_repository.py`
的通過證明本輪新增的 4 個 `error-codes.json` 條目（`UNVERIFIED_APPROVAL_REJECTED`／
`ACTOR_ROLE_MISMATCH`／`AUTHORIZATION_REVOKED`／`REVOCATION_NOT_PERMITTED`，皆標 `x_added_by: ENG-03`）
未破壞 ENG-01 既有的 registry 一致性檢查與連結完整性檢查。

## 未驗項總表（非逐項重複，彙整）

- 沒有啟動 PostgreSQL；所有「原子」行為（UNIQUE 約束、AuthorizationUse 唯一性、撤回/dispatch 先後序）
  是用 Python `threading.Lock` 與 dict 在單一進程內模擬，不是資料庫交易隔離等級下的實測。ENG-02 換上
  真正的 repository 實作後，這些測試案例的「給定呼叫順序 → 預期結果」仍應成立，但需要 ENG-02 自己對
  真正的資料庫交易重新驗證並發場景。
- 沒有 HTTP 伺服器、瀏覽器或外部 connector；`specs/authorization/api-contract.md` 只是契約文件，
  實際 handler 接線與其整合測試是 ENG-05 範圍。
- `AuthorityGrant`/`PolicyVersion` 沒有正式 schema，`nonce` 核發／消耗沒有真正的 UI／語音確認傳輸層；
  兩者在本輪都只是支撐「政策覆蓋」與「不得以模型文字授權」這兩條驗收規則的最小可測替身。
