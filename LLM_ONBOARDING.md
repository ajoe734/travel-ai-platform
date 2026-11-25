# LLM Onboarding

First-stop guide for any LLM working inside `travel-ai-platform`.

## 1. Read Order

1. `AI_COLLABORATION_GUIDE.md`
2. `ai-status.json` (machine truth; `current-work.md` is only a human summary)
3. `AGENTS.md`
4. `docs/project/current-decisions.md`
5. `docs/README.md`
6. `docs/sd/README.md`
7. `docs/sd/sa-v1-gaps.md`
8. `docs/adr/`
9. `docs/collaboration/herdr-handoff.md`
10. `docs/collaboration/backlog.md`
11. `docs/sa/README.md`
12. `specs/README.md`

Current mode is `supervisor_managed_execution`.

## 2. First Prompt

```bash
python3 tools/development-orchestrator/bin/ai_status.py prompt
```

## 3. Shared Truth Rules

- Task state changes only through `tools/development-orchestrator/bin/ai-status.sh`.
- Work only inside your task worktree and its declared write scope.
- Follow `AGENTS.md` for product, data-safety and external-system boundaries.
