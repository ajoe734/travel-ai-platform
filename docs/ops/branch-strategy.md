# Branch Strategy

## 3. Branches

- `dev`: integration trunk. Every task branch opens a PR to `dev`; CI must pass.
- `main`: release/spec baseline. A human promotes `dev` to `main`.
- Task branches: `<lane>/<task-id-kebab>`, created by the supervisor in `.artifacts/worktrees/auto/`.

## 4. Workflows

`.github/workflows/` defines the CI that gates PRs to `dev`. The supervisor's GitHub bus
records candidate CI and merge results; workers never force-push or merge their own PRs.

## 5. Promotion gates

- task → `dev`: PR, green CI, reviewer approval of the exact candidate SHA.
- `dev` → `main`: human decision only.

## 11. Anchor commit protocol (worker hygiene)

In a multi-worker repo, the working tree is a fragile asset. Supervisor reassignments, agent crashes, and parallel edits on the same file (e.g. `supervisor.py` routing) routinely cause in-session diffs to be lost or to require manual reconciliation. The protocol below treats branch + commit, not the working tree, as the unit of progress. In v4 every worker PRs against the single `dev` trunk, so the protocol is uniform across backend / frontend / docs.

### 11.1 When to anchor commit

Anchor commit at the first describable middle state — do not wait for completion — when **any** of the following hold:

- The change touches a **fragile surface**: `tools/development-orchestrator/control_plane/runtime/supervisor_runtime.py` (esp. routing/dispatch), `tools/development-orchestrator/skills/*.md`, `tools/development-orchestrator/templates/*`, `.orchestrator/config*.json`, `.orchestrator/branch_routing.py`, `docs/ops/branch-strategy.md`, `docs/**`, `.github/workflows/**`, `.husky/*`.
- The change spans **more than one file** with shared design intent.
- The change is expected to take **more than one supervisor cycle** to land.
- The worker is **about to yield** to another task (planned reassignment, blocker, end-of-shift).

If any answer is yes and there is no branch yet, **stop editing and create the branch first**:

```bash
git switch -c <lane>/<task-id-kebab> origin/dev
```

Then commit the first describable state:

```bash
git add <task-owned files only>
git commit -m "wip(<TASK-ID>): anchor <scope>" \
  -m "LLM-Agent: <lane>" -m "Task-ID: <TASK-ID>" -m "Reviewer: <reviewer>"
```

The anchor commit is **not the candidate**; it is a recoverability checkpoint that says "this lane has a claim on this surface." The owner locks the final pushed head with `CANDIDATE_SHA` at handoff; review, CI, and merge evidence are valid only for that exact SHA.

### 11.2 Do not stash design-intent diffs

`git stash` is acceptable **only** for tiny, throwaway, no-design-intent edits (e.g. a `console.log` you forgot to remove). Any diff touching the fragile surfaces in §11.1 must become a commit, never a stash. Reason: stash entries are anonymous, unreviewable, and almost always require manual rework once mainline advances.

If the supervisor reassigns a worker that has design-intent diffs in flight, the worker must anchor-commit **before** yielding. The supervisor's `worker_tree_guard` config (added by OPS-GIT-WORKFLOW-006) will block dispatch if a fragile-surface diff is uncommitted, and its chatbox sibling (`worker_tree_guard.chatbox_enabled`, added by OPS-GIT-WORKFLOW-007) refuses chatbox-driven `Edit`/`Write`/`MultiEdit`/`NotebookEdit` calls in the same condition.

### 11.3 Same-file parallel designers — declare the layer in the commit body

When two lanes touch the same file at different layers (e.g. one lane edits `supervisor.py` routing, another lane edits `supervisor.py` chair-review), the anchor commit body must declare which slice is claimed. Template:

```
wip(<TASK-ID>): anchor <scope>

Touches <file>: <slice>.
Does not change <other slices>.
Intended to compose with <PR# or task-id> on <other-slice>.

LLM-Agent: <lane>
Task-ID: <TASK-ID>
Reviewer: <reviewer>
```

The body lets the other lane (and future reviewers) tell at a glance whether the two patches are compatible.

### 11.4 Preserve published history when `dev` advances

When `dev` has advanced while a lane was paused, fetch first and inspect the
remote task branch, existing PR and candidate/CI state:

```bash
git fetch origin
```

- A candidate under review or CI stays at its exact SHA while awaiting results.
  Trunk movement alone does not require synchronization or restarting CI.
- Published commits, including pushed anchors, must not be rebased, amended or
  force-pushed. If synchronization is necessary before candidate handoff, merge
  `origin/dev` in the owner task worktree, resolve conflicts, validate and push
  normally. The resulting SHA requires new review and CI.
- Only a branch confirmed never published, with no PR or candidate, may use
  `git rebase origin/dev`.
- If the local task branch is missing but its remote branch exists, recreate it
  from that remote head, preserving published work rather than starting at trunk.
- If local history has already diverged from the published head, preserve both
  refs and report their SHAs and diff for history recovery. Do not reset,
  force-push or rebase again to make the push succeed.

Do **not** rely on `git stash pop` to recover paused work; the stash blob has no patch identity and almost always requires manual fixups against the moved trunk.

### 11.5 doc / skill / config — always branch + PR, never park in session

The three surface classes most often overwritten by parallel lanes are:

| Surface class                              | Examples                                                   | Why fragile                                      |
| ------------------------------------------ | ---------------------------------------------------------- | ------------------------------------------------ |
| `docs/**`                                  | `docs/ops/branch-strategy.md`, `docs/03-runbooks/**`       | chair-review and supervisor lanes both edit them |
| `tools/development-orchestrator/skills/**` | `candidate-lifecycle.md`, `chairman-operational-review.md` | supervisor/chair changes touch these             |
| `.orchestrator/config*.json`, schema files | `config.example.json`, provider/capability schema          | enabled-flag toggles by many lanes               |

For these, **never** keep edits in the working tree across more than one supervisor cycle. The required flow:

```bash
git switch -c <lane>/<topic> origin/dev
# edit
git add <files>
git commit -m "<TASK-ID>: <summary>" \
  -m "LLM-Agent: <lane>" -m "Task-ID: <TASK-ID>" -m "Reviewer: <reviewer>"
git push -u origin <lane>/<topic>
gh pr create --base dev --title "<TASK-ID>: <summary>" ...
```

### 11.6 Candidate lifecycle is the development closeout

The task state machine has one completion path:

`backlog/todo -> in_progress -> review -> integrating -> acceptance -> done`

The owner may push anchor commits while working. Once implementation verification
is complete, the owner records the pushed `CANDIDATE_SHA` and
`CANDIDATE_BRANCH` with `ai-status.sh handoff`. The reviewer checks that exact
SHA and records the same value as `REVIEWED_SHA`; reviewers never modify the
candidate branch.

The GitHub bus is the sole adapter that records PR head, CI, and merge evidence.
It accepts CI or merge only when the PR head equals `CANDIDATE_SHA`. A later push
invalidates prior review and CI evidence and returns the task to `in_progress`.
After same-SHA CI and merge, a task with `required_acceptance` enters
`acceptance`; it becomes `done` only when all named evidence keys are recorded.

This keeps code completion, integration, and external acceptance explicit
without a second owner-closeout transition or git-log inference.

### 11.7 Trigger checklist (before each significant save)

Worker prompts (wakeup + candidate lifecycle skill) carry this checklist; it is reproduced here for human reference:

1. Am I touching a fragile surface from §11.1?
2. Will this take more than one supervisor cycle?
3. Am I about to yield (reassignment, blocker, planned pause)?
4. Is this a doc / skill / config change per §11.5?

If **any** answer is yes and the current branch is not `<lane>/<task-id-kebab>`, stop editing and:

```bash
git switch -c <lane>/<task-id-kebab> origin/dev
```

### 11.8 Related artifacts

- [`tools/development-orchestrator/skills/worker-anchor-commit.md`](../../tools/development-orchestrator/skills/worker-anchor-commit.md) — owner-only operational skill for recoverable checkpoints
- [`tools/development-orchestrator/skills/candidate-lifecycle.md`](../../tools/development-orchestrator/skills/candidate-lifecycle.md) — locked SHA review, CI, merge, and acceptance protocol
- [`tools/development-orchestrator/templates/wakeup.txt`](../../tools/development-orchestrator/templates/wakeup.txt) — supervisor wakeup template that injects branch context (target of OPS-GIT-WORKFLOW-005)
- [`.orchestrator/worker_tree_guard.py`](../../tools/development-orchestrator/worker_tree_guard.py) — shared tree-guard primitives (extracted by OPS-GIT-WORKFLOW-007). Backs both surfaces:
  - `check_worker_tree_guard` — supervisor dispatch guard, gated by `branch_strategy.worker_tree_guard.enabled` (OPS-GIT-WORKFLOW-006, opt-in)
  - `check_chatbox_tree_guard` — Claude-Code PreToolUse hook (via `tools/development-orchestrator/permission_broker.py`) for chatbox-driven `Edit`/`Write`/`MultiEdit`/`NotebookEdit`, gated by `branch_strategy.worker_tree_guard.chatbox_enabled` (OPS-GIT-WORKFLOW-007, opt-in)

---


