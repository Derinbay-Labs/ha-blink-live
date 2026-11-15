## What & why

<One paragraph: what changed and why. Link the PRD section / RFC / ADR that asked for it.>

Closes #NN

## How

- <key implementation point a reviewer needs to know>
- <trade-off taken and why>

## Acceptance criteria covered

| AC | Where it is verified |
|---|---|
| AC-1.1 | `backend/internal/x/handler_test.go:TestCreate_Ok` |
| AC-1.2 | `web/e2e/transaction.spec.ts` |

## Test evidence

```
<paste the test/coverage summary for changed packages>
```

## Risk & rollback

- Feature flag: `<flag_name>` (default off) / not flagged because <reason>.
- Migration: none / `NNNN_name.sql`, forward-only, rollback = <compensating step>.
- Rollback: <how to undo>.

## Definition of Done

- [ ] Branch matches `^(feat|fix|chore|docs)/[0-9]+-[a-z0-9-]+$` with a real issue id
- [ ] PR title is a valid Conventional Commit (it becomes the squash commit)
- [ ] `Closes #N` present; all acceptance criteria implemented
- [ ] Scope limited to this issue
- [ ] Unit tests; integration tests for DB/network; e2e for critical flows
- [ ] Coverage ≥ 90 % lines and branches on changed packages
- [ ] Lint/format clean for every changed language
- [ ] Generated OpenAPI code regenerated, not hand-edited
- [ ] `api/openapi.yaml` change reviewed by architect (or n/a)
- [ ] No existing migration edited; new migration only
- [ ] Money as decimal with explicit ISO 4217 currency; no floats
- [ ] No secrets or PII in code, logs or this PR
- [ ] New deps at latest stable, verified today; lockfile committed
- [ ] Docs updated (PRD/ADR/RFC, README, `docs/versions.md` if toolchain moved)
- [ ] CI green
- [ ] Board item in **In Review**

## Reviewer notes

<Anything you want the code-reviewer to look at hardest, or a known follow-up with its issue number.>
