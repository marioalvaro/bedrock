---
name: docs-sync
description: Audit PRD/ERD docs against each other and against the code, then fix drift.
disable-model-invocation: true
---

# Docs sync

Goal: the docs and the code describe the same system. Every piece of drift gets resolved, never just noted.

## 1. Structural check
Run `python3 scripts/check_docs.py`. It checks links and anchors, that each requirement ID and each table is defined once, the table index, and the split headers. Fix every `FAIL`, then re-run.

**Done when** it prints `OK`.

## 2. Semantic check
For each area in the `CLAUDE.md` area table that has code, compare its ERD split against the code:
- **Tables**: ERD table rows vs. SQLAlchemy models in `backend/src/bedrock/models/` and the Alembic migrations (names, key columns, unique constraints).
- **Routes**: ERD API lists vs. routers in `backend/src/bedrock/api/v1/`.
- **Interfaces**: protocols and dataclasses in the ERD vs. `forecast/interface.py`, `valuation/interface.py`, `ingest/protocol.py`, and the ratio registry.
- **Config**: env vars in `erd/platform.md` vs. the settings class and `.env.example`.
- **Stack and structure**: `docs/ERD.md` §2–§3 vs. `pyproject.toml`, `package.json` and the actual directory tree.
- **Progress**: the milestone and requirement IDs actually delivered vs. "Current milestone" in `CLAUDE.md`.

Also check the PRD splits against the ERD splits: every `FR-…` requirement at or below the current milestone has an engineering home (table, flow, interface or route).

**Done when** every area with code has been compared on every bullet above.

## 3. Resolve
List each piece of drift with its direction:
- **Doc outdated**: the code reflects a deliberate decision. Update the owning doc.
- **Code wrong**: the code departs from the spec. Report it to the user, with the fix, as a follow-up.
- **Unclear**: ask the user which one is right.

Apply the doc updates, then re-run step 1.

## Report
Give a drift table: area, item, direction, action taken. End with the final `check_docs.py` result.
