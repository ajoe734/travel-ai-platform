# ENG-07 unblock diagnosis

Date: 2026-11-27

## Scope and observation

This helper only diagnoses the parent `ENG-07` integration blocker.  It does
not alter the locked parent candidate or product implementation.

| Item | Observed evidence |
| --- | --- |
| Parent candidate | `f142ea7fcecf9a652fbc7e9853435550678e6487` on `origin/codex/eng-07` and PR #13 head are identical. |
| Candidate verification | Hosted run `45994232134` is successful for `validate`, the empty-DB `0 -> 7 -> 0 -> 7` lifecycle, and 43 DB repository tests. |
| PR state | PR #13 is open and `CONFLICTING`, not failing its candidate checks. |
| Current integration base | `origin/dev` is `7f78459`; it contains migrations `0001` through `0008`. |

## Reproduction and cause

From this helper worktree after `git fetch origin --prune`:

```bash
git merge-tree --write-tree origin/dev codex/eng-07
```

Exit status is `1`.  The sole textual conflict is
`.github/workflows/repository-validation.yml`: the parent candidate expects
seven migrations while `origin/dev` expects eight.

The textual conflict is not the whole integration boundary: the parent branch
contains `0007_remedy_credit_complaint.*`, whereas `origin/dev` already owns
`0007_service_version_publication.*` and `0008_publication_dispatch_claim.*`.
Resolving only the workflow hunk would leave duplicate migration version `0007`
with different names, which the migration lifecycle correctly rejects.  On the
new base, ENG-07's remedy/Credit/complaint migration must become `0009`, and
the lifecycle count must become `9`.

## Unblocked next step for ENG-07

The locked SHA cannot be rewritten.  The assigned reviewer should explicitly
reopen `ENG-07` for the integration repair, preserving this diagnosis.  The
parent owner can then perform one new candidate generation on
`codex/eng-07`:

1. merge `origin/dev` normally (no rebase or force push);
2. rename ENG-07's `0007_remedy_credit_complaint.{up,down,md}.sql` to migration
   version `0009` and update only its version references;
3. resolve the workflow to the complete migration count `9`, retaining all
   existing ENG-08 test scope;
4. run the applicable static checks locally and let a new same-SHA PR CI run
   verify the PostgreSQL lifecycle and repository suite; then hand off the
   new SHA to Antigravity.

This is a parent-task source/integration repair, not a reason to claim that
`f142ea7` has been merged or that its old CI applies to a new SHA.

## Helper verification

| Acceptance item | Evidence | Result / limitation |
| --- | --- | --- |
| Diagnose dependency-ready parent block | `ai-status.sh show ENG-07`; PR #13 inspection; `git merge-tree` reproduction above | Parent dependencies are ready; the PR conflict is the remaining blocker. |
| Minimum scoped change | This artifact only | No parent source or locked candidate was changed. |
| Parent concrete next step | This artifact's **Unblocked next step** section | The dispatched-worker guard correctly rejects a helper mutating a different task; Supervisor must write this next step to the parent through its canonical resolution metadata. |
| Canonical helper delivery | Task branch commit and PR, recorded at helper handoff | Pending after this artifact is committed and pushed. |

