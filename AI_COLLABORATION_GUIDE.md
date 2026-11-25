# AI Collaboration Guide

Status: canonical collaboration rules for 旅行平台 Travel AI Platform (`travel-ai-platform`) under the
development orchestrator in `tools/development-orchestrator/` (supervisor + auto workers + dashboard,
installed from drts-fleet-platform). Product rules live in `AGENTS.md` and the documents below; this
file only defines how lanes coordinate.

## 0. Repository Scope

You are in the `travel-ai-platform` repo. `AGENTS.md` is the binding engineering instruction and wins
over this guide on product, scope and external-boundary questions.

Trunk: task branches open PRs to `dev`; `main` is promoted from `dev`
by a human. See `docs/ops/branch-strategy.md`.

## 0.5 Machine Truth Discipline

The dashboard and supervisor are only allowed to speak from machine truth.

Hard rules:

- if the repo has official remaining work, that work must exist in `ai-status.json` before anyone claims the project is incomplete
- if the repo has official accepted backlog, that backlog may be summarized into `current-work.md` and `docs-site/current-work.md` through the normal sync flow
- if a discussion round creates or confirms new official backlog, the supervisor must record those tasks in `ai-status.json` before returning to execution or reporting status to a human
- no lane may keep authoritative backlog only in chat, memory, or ad hoc notes
- if verbal status and control-plane status diverge, fix `ai-status.json` first, then continue discussion or execution
- `docs-site/*` is a read-only mirror; update the machine truth and let sync regenerate the mirror
- runtime inboxes, local logs, PID files, and ephemeral queue artifacts are not commit evidence and must not be treated as durable delivery output

This means:

- `done` in the dashboard means only the currently recorded backlog is done
- if more work is known to be required, it must be added to the task board immediately instead of explained only in prose

## 0.6 Delivery Compliance Gate For All Sessions

These rules apply in supervisor-managed execution, direct Codex/Claude/etc chat sessions, and any ad hoc repo work. They are not limited to supervisor wakeups.

- If you touch a fragile surface from `docs/ops/branch-strategy.md` §11.1, or make a multi-file design-intent change, do not leave the work only in the working tree at end of turn.
- Before yielding, switching tasks, or describing the work as complete, create a task-scoped anchor commit or closeout commit, whichever matches the current lifecycle state.
- Existing unrelated dirty files are not a valid reason to skip the commit. Stage only task-owned files, or move the task to a clean branch/worktree and continue.
- If a safe task-scoped commit or normal non-force push is not possible, explicitly record and report a blocker/progress state. Do not describe the work as complete.

## 0.7 交付品質與退修規範

本節是 owner、reviewer 與 Supervisor 共用的交付品質規範，適用於既有
`task_spec_ref`、`write_scopes`、`required_acceptance` 及
[candidate lifecycle](tools/development-orchestrator/skills/candidate-lifecycle.md)。
依任務板保留角色分工；指定 agy 實作、Codex 審查的任務，仍由原 owner 實修，
reviewer 唯讀核對候選。這些要求是既有流程的工作規則，不新增狀態、排程或平行驗收清單。

### 修改前：核對實際依據

- 讀本次候選的最新完整退修、正式設計與相關原始碼。逐項記下檔案與 symbol：
  實際呼叫端、元件 props／可編輯能力、API 型別及允許值、migration／資料型別、
  身分與資料歸屬的權威來源。檔名或舊摘要不能代替讀碼。
- 沿用現有實作；修改共用 constructor、契約或授權函式時，搜尋所有受影響的
  callers、替代入口與測試。需要額外檔案時，由 Supervisor 核對平行任務衝突並
  更新原 task 的 `write_scopes`；既有授權內的協調不轉成人工許可等待。

### 實作中：同一任務逐項修復

- 在原 task brief／驗收文件內，以缺陷觸發情境識別各項 finding，保留相鄰候選的
  SHA 與審查來源。依相依關係，一次完成一個可獨立驗證的修復單元；緊密相依的
  修改可成組處理。每項完成窄範圍檢查後再進下一項，最後跑受影響的整體回歸。
- 小單元是實作順序，不另開一套任務或每修一項就交審。保留全部未解 finding，
  不用新的「全部修好」摘要覆蓋它們；checkpoint commit 仍不是 review candidate。
- 安全邊界須同時保留合法正向與拒絕情境；例如同一 handoff 的所有消耗入口、
  logout／帳戶切換、跨 tenant／partner／entry／subject，及歷史資料歸屬。

### 驗證：測到正式行為

- 行為缺陷先以最小回歸案例或可重跑 probe 重現。案例須呼叫正式函式、API 或
  repository；證明舊候選因該缺陷失敗、修正版通過。缺套件或 fixture 錯誤不算
  重現成功。先後候選的案例、命令、版本與結果都要可追溯，且不得 reset 活躍工作樹。
- 外部邊界可以 mock，但必須說明模擬範圍；不能 mock 掉被驗證的邏輯。
  比較常數、`expect(true)`、自行複製業務 SQL／另造不符正式 migration 的資料表，
  都不能作為產品驗收證據。PG 行為須用正式 schema 與 production repository 路徑；
  UI 互動須核對真正可操作的元件及實際送出的契約。
- 選擇與變更相稱的 checks，等它們結束並讀結果。scoped pass 不代表完整回歸、
  DB、browser 或真實外部驗收通過。skip、未執行、失敗與通過分開記錄。
  文件／提示文字等低風險變更採內容、引用和既有適用檢查，不為了湊證據新增鏡像測試。
- 本 VM 的服務限制照常適用；需要 runtime／PG／browser 的項目使用既有授權
  hosted workflow。若無法重現，記錄缺少的具體條件與已有靜態證據，交 reviewer
  判定尚未滿足的驗收，不能聲稱測試通過或降低原驗收要求。

### 交接：證據與候選一致

在原 task 的驗收文件／review artifact 記錄下表，handoff 摘要引用它即可。
每個未解 finding 及每項 `required_acceptance` 都須有對應；純文件變更使用適用的
內容核對，非適用欄位須說明原因。

| Finding／驗收項                                | 原始碼依據與修改位置   | 舊版重現 → 修正版結果                     | 命令、退出碼、執行版本與證據位置                            | 未驗項與具體限制               |
| ---------------------------------------------- | ---------------------- | ----------------------------------------- | ----------------------------------------------------------- | ------------------------------ |
| 原 finding 編號或觸發情境／既有 acceptance key | 路徑、symbol、正式契約 | 舊／新 SHA 的實際結果；文件核對可標不適用 | 本機結果或 hosted run／job／artifact；pass／fail／skip 分列 | 所需環境或外部交付；不填假通過 |

- owner 核對本機完整 SHA、已推送遠端分支與 PR head 一致後，才以既有 `handoff`
  鎖候選。候選交審後保持不變；後續修正須走原退修／新候選流程，保留發布歷史。
- 已啟動且屬本輪必要檢查的結果須讀完再交接；由 handoff 才觸發的 hosted CI
  可列 pending，由原 GitHub bus 收錄結果，不建立相互等待的前置條件。
  CI 與 reviewer 最終結論須對應該候選；merge SHA 另記，不能冒充 candidate SHA。
- reviewer 逐項核對實際差異與證據，包含前輪已修項的回歸，並對新候選重新確認
  finding 是否仍存在。任務摘要、worker 終端 SUCCESS、commit 數量或舊 SHA 的綠燈
  都不是完成證據。報告任務則核對指定絕對路徑、內容 hash 及 handoff generation，
  沿既有 noncanonical lifecycle，不製造空 commit／PR。

### 同一缺陷連續兩輪退修

- 判準是相同觸發條件／失敗行為，在兩個相鄰候選的獨立 review 都未消除；
  finding 改名不重置計數，不同的新問題也不算同一缺陷。
- 第二輪 reviewer 在原 review artifact 補齊「候選 SHA、最小重現或精確靜態證據、
  實際呼叫路徑、預期／實際差異、修正邊界與必要回歸」，再用既有 `reopen` 退回。
  reviewer 不代寫產品碼、不修改候選；無法動態重現時明列缺條件，不假造證據。
- Supervisor 核對該定位與 owner 的下一個小修復單元、scope 及相依項，再讓原 owner
  續做。停止的是原封不動重送／盲目重試；保留 `in_progress` 和可執行工作，
  不因品質退修自動停用 provider、判定 quota 不足或要求使用者再授權。
- Supervisor 報進度時說明「哪些缺陷已由證據確認消除、哪些仍在修、哪些待驗」，
  並區分實作、review、CI／merge、acceptance；worker 存活不能代表交付合格。


## 1. Canonical Read Order

1. `AGENTS.md`
2. `docs/project/current-decisions.md`
3. `docs/README.md`
4. `docs/sd/README.md`
5. `docs/sd/sa-v1-gaps.md`
6. `docs/adr/`
7. `docs/collaboration/herdr-handoff.md`
8. `docs/collaboration/backlog.md`
9. `docs/sa/README.md`
10. `specs/README.md`

## 2. Conflict Precedence

1. Latest explicit user decision recorded in the repository
2. `AGENTS.md`
3. The canonical documents in section 1, in order
4. This guide and `tools/development-orchestrator/` skills (process only)

Unresolved business choices go to `docs/project/current-decisions.md`; implement configurable behaviour and
never mark a pending decision as approved.

## 3. Capability Lanes

- `Claude`: main implementation and architecture review (Anthropic account 1)
- `Claude2`: implementation, separate Claude account/quota
- `Codex`: contracts, schema, state system, acceptance
- `Codex2`: implementation/review, separate Codex account/quota
- `Pi`: pi coding agent; provider/model switchable
- `Gemini`: runtime packaging, CI/CD (requires gemini CLI on the host)

Owner and reviewer of a task are always different lanes (prefer different model families).

## 3.5 Two-Mode Supervisor

1. `discussion_planning`
2. `supervisor_managed_execution`

See `SUPERVISOR_OPERATING_MODEL.md`. This repository starts in `supervisor_managed_execution`
because its specifications and task packets are already accepted.

## 5. Candidate evidence and integration

- Follow the single [candidate lifecycle](tools/development-orchestrator/skills/candidate-lifecycle.md):
  `backlog/todo -> in_progress -> review -> integrating -> acceptance -> done`.
- The owner verifies and pushes the task commit, then supplies the full `CANDIDATE_SHA`,
  `CANDIDATE_BRANCH` and PR reference to `handoff`.
- Commit body trailers: `LLM-Agent: <lane>`, `Task-ID: <task-id>`, `Reviewer: <reviewer>`.
- The reviewer approves that exact `REVIEWED_SHA` without editing the candidate.
- The GitHub bus records matching candidate CI and merge. Never call `done` directly.

## 6. Status Commands

```bash
python3 tools/development-orchestrator/bin/ai_status.py prompt
./tools/development-orchestrator/bin/ai-status.sh sync
AI_NAME="$TASK_OWNER" "$STATUS_CLI" start "$TASK_ID" "Current repair unit"
AI_NAME="$TASK_OWNER" "$STATUS_CLI" progress "$TASK_ID" "Verified finding and remaining work"
AI_NAME="$TASK_OWNER" CANDIDATE_SHA="$FULL_SHA" CANDIDATE_BRANCH="$PUSHED_BRANCH" PR_URL="$PR_URL" \
  "$STATUS_CLI" handoff "$TASK_ID" "$TASK_REVIEWER" "Evidence artifact; pending hosted checks"
AI_NAME="$TASK_REVIEWER" REVIEWED_SHA="$FULL_SHA" "$STATUS_CLI" approve "$TASK_ID" "Same-SHA review evidence"
```
