---
name: plan-milestone
description: Breaks a Bedrock milestone (M0–M9) into the largest self-contained, testable implementation steps, written to docs/progress/CURRENT.md, and archives the previous milestone's progress. Use when starting a milestone, when asked to plan or break down a milestone, or when every step in CURRENT.md is done.
---

# Plan milestone

Turns one roadmap row ([docs/PRD.md §8](../../../docs/PRD.md#8-milestone-roadmap)) into **steps**: the largest chunks of work that a less capable model can implement and test in one session, working only from the step text and the docs the step names. The `implement` skill executes one step at a time.

## Files
- `docs/progress/CURRENT.md` holds the one milestone in progress: its steps, their status and their logs. There is exactly one current milestone.
- `docs/progress/archive/M<n>.md` holds finished or superseded milestones. It is history, read only when the user asks.

## 1. Archive the previous milestone
If `CURRENT.md` exists:
- **All steps done and acceptance verified**: set its status to `done`, then move it to `archive/M<n>.md`.
- **Unfinished steps remain**: ask the user whether to carry them into the new milestone or drop them. Record the answer in the file's `Status` line, then archive it.

## 2. Gather
Read:
- the milestone's roadmap row, including its acceptance criteria;
- the PRD + ERD split for every area its `FR-…` IDs touch (see the area table in `CLAUDE.md`);
- `docs/ERD.md` §2–§3 (stack, structure);
- the code that already exists.

Check the local toolchain the steps depend on (`command -v` plus versions). A missing tool becomes a **prerequisite**, which the user resolves.

## 3. Cut the steps
A step is right-sized when **all** of these hold:
- **Testable alone**: it ends in an observable, automated or scripted check: a test suite, a curl, a build, a page that loads.
- **Self-contained**: the implementer makes no design decisions. Every choice (library, file path, endpoint shape, config key, command) is already fixed in the step text or in a doc the step names.
- **Largest possible**: merge adjacent work whenever the merged step is still testable and still fits one session (roughly ≤ 25 files and one layer or vertical slice). Split only at a verification boundary, i.e. where the first half can be tested before the second half starts.
- **Ordered**: steps follow the layering: backend foundation → domain/engine → service/API → client → UI → infra. Dependencies are explicit.

Typical milestones produce 3–6 steps. More than 8 means the steps are too small.

## 4. Write `CURRENT.md`
Use this exact layout:

```markdown
# M<n> — <Name> · Progress

> Source: [PRD.md §8](../PRD.md#8-milestone-roadmap) · Status: `planned` | `in progress` | `done` · Planned: <date>
> Areas: [prd/…](../prd/…) + [erd/…](../erd/…)

## Prerequisites
- [ ] <tool or credential the user must provide>

## Steps
| # | Step | Requirements | Depends on | Status |
|---|---|---|---|---|
| S1 | … | FR-… | — | `todo` |

## S1 — <title>
**Goal**: one sentence.
**Read**: the exact doc sections needed; nothing else.
**Build**:
- concrete files, modules, endpoints, config and decisions
**Verify**:
- command → expected result (exit code, output, HTTP status)
**Done when**: every Verify line passes and all earlier steps' tests still pass.
**Log**: _(filled by the implementer: date, what was done, deviations, follow-ups)_

## Milestone acceptance
- [ ] each acceptance criterion from the roadmap, as a command or manual check
```

Status values: `todo` → `in progress` → `done`, or `blocked: <reason>`.

**Done when** every requirement ID in the milestone's scope appears in at least one step, and every acceptance criterion appears under "Milestone acceptance".

## 5. Hand off
- Run `python3 scripts/check_docs.py`.
- Update "Current milestone" in `CLAUDE.md`.
- Show the user the step table and the prerequisites. The user decides when implementation starts.
