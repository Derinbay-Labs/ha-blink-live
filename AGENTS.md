# ha-blink-live — project instructions

This file adds repository-specific context to the Derinbay Labs constitution (installed
globally as `~/.claude/CLAUDE.md` or `~/.codex/AGENTS.md`); it never overrides it. `CLAUDE.md`
only imports this file (`@AGENTS.md`); repo-local skills live in `.agents/skills/`.

## Product map

Home Assistant custom integration (HACS) for live Blink camera streams. Not a Go/Next.js/mobile product: the company stack templates other than the baseline CI do
not apply, and the repo keeps its own workflows beside the baseline ones.

## Repository ownership

| Path | Owner |
|---|---|
| `.github/`, root tooling | devops-engineer |
| everything else | the owning developer named on the issue |

## Metrics

`docs/metrics/outcome.txt` holds one line, the weekly outcome (downloads, active users,
crash-free rate, revenue); a figure not measurable yet is `unavailable`.
