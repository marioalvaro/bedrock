---
name: implement
description: Checklist-driven implementation of Bedrock requirements: area docs → checklist → test-first iteration → verification → doc update. Use when asked to implement, build or start an FR-… requirement, a milestone (M0–M9), or any feature from the PRD.
---

# Implement

Every Bedrock implementation follows these steps in order. The docs are the spec; the **checklist** is the contract for the session.

## 1. Scope
Resolve the request into requirement IDs.
- Milestone work runs **one step at a time** from [docs/progress/CURRENT.md](../../../docs/progress/CURRENT.md).
  - Take the requested step, or else the first `todo` step whose dependencies are `done`. That step's Build and Verify lines seed the checklist.
  - If `CURRENT.md` is missing, or covers a different milestone, run the `plan-milestone` skill first.
  - Unchecked prerequisites block the step: ask the user to resolve them.
- Milestone acceptance criteria → its row in [docs/PRD.md §8](../../../docs/PRD.md#8-milestone-roadmap).
- Feature described in words → find its `FR-…` IDs in the area table in `CLAUDE.md`.
- Nothing in the PRD matches → the request is new product scope. Ask the user whether to add it to the PRD before building.

**Done when** you hold a list of `FR-…` IDs and, for a milestone, its acceptance criteria.

## 2. Read
For each area the IDs touch, read the PRD + ERD pair from the `CLAUDE.md` area table. Open `docs/ERD.md` only for stack, project structure, data-model conventions or coding conventions.

**Done when** every ID is traced to concrete tables, interfaces, flows and routes in its ERD split. A gap (the docs are silent) or a conflict (docs disagree with each other or with the code) is a decision for the user: ask, and record the answer in the owning doc.

## 3. Checklist
Write the in-session task list **before any code**, then show it to the user and begin.
- Order the items along the layering: model + migration → pure engine (tests first) → service → API route + schema → regenerate the API client → UI.
- Each item names its `FR-…` IDs, one concrete deliverable, and an observable completion criterion: a named test passes, an endpoint returns a stated payload, a grid renders a stated row. "Works" or "implemented" is not a criterion.
- Always end with three items: **verify** (step 5), **docs** (step 6), **report** (step 7).

## 4. Iterate
Work one item at a time: mark it in progress, do it, observe its criterion, mark it done.
- Engine code (mapping, statements, ratios, analysis, forecast, valuation, backtest) runs through the `tdd` skill: red test first, then green.
- Tests use recorded fixtures only; no network.
- Discovered work becomes a new checklist item. A blocker is recorded on its item and raised with the user.
- XBRL mapping trouble (unmapped item, wrong value, unbalanced balance sheet) → the `map-xbrl` skill.

**Done when** every item is done, or explicitly deferred with the user's agreement.

## 5. Verify
- Run the full backend and frontend lint, typecheck and test commands (take them from `backend/pyproject.toml` and `frontend/package.json`).
- Observe each milestone acceptance criterion directly: run the app, call the endpoint, look at the page.
- Run `python3 scripts/check_docs.py`.

**Done when** all three are green. A failing test is fixed or reported to the user with its output; it is never skipped or deleted.

## 6. Docs
- Update the owning doc for every decision made along the way: the area split, or the index for cross-cutting content.
- For step work, update `docs/progress/CURRENT.md`: set the step's status, fill its **Log** (date, what was done, deviations, follow-ups), and set the milestone status. When the last step is done, work through "Milestone acceptance" before marking the milestone `done`.
- On milestone completion, update "Current milestone" in `CLAUDE.md`.
- Re-run `scripts/check_docs.py` after editing docs.

## 7. Report
Tell the user:
- the `FR-…` IDs delivered, with the evidence (tests, observed behaviour);
- the checklist outcome, including any deferred items;
- deviations from the docs and the doc edits made;
- what comes next.
