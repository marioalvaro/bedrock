# Bedrock

Personal web app for deep fundamental analysis of a handful of US companies. It is TradingView-"Fundamentals"-like (no price charting), with a modular forecasting and valuation layer that keeps the 3 statements accounting-consistent and scores forecasts against actuals. Single user; FastAPI + SQLite backend and a React SPA frontend in one monorepo.

**Current milestone: M0 (Scaffold)**: planned, not started. Step-level plan and progress: [docs/progress/CURRENT.md](docs/progress/CURRENT.md). `docs/progress/archive/` holds finished milestones; read it only when asked.

## Docs (source of truth)
- [docs/PRD.md](docs/PRD.md): index for **what and why**: vision, users, use cases, NFRs, the milestone roadmap and its acceptance criteria.
- [docs/ERD.md](docs/ERD.md): index for **how**: architecture, stack, project structure, data-model and API conventions, coding conventions.
- [docs/brainstorm.md](docs/brainstorm.md): original ideation, for historical context only. Where it disagrees with the PRD/ERD, the PRD/ERD wins.

Area details are split into one PRD file and one ERD file per area. For a task, read the matching pair; open the indexes only for roadmap, stack or conventions.

| Area (requirement prefix) | Product | Engineering |
|---|---|---|
| Data & statements: ingestion, mapping, adjustments (`FR-DATA`, `FR-STMT`) | [prd/data.md](docs/prd/data.md) | [erd/data.md](docs/erd/data.md) |
| Ratios, QoE flags, capital allocation, comps, guidance (`FR-ANL`) | [prd/analysis.md](docs/prd/analysis.md) | [erd/analysis.md](docs/erd/analysis.md) |
| Drivers, scenarios, forecast engines Tiers 1–5 (`FR-FCST`) | [prd/forecasting.md](docs/prd/forecasting.md) | [erd/forecasting.md](docs/erd/forecasting.md) |
| DCF, multiples, sensitivity (`FR-VAL`) | [prd/valuation.md](docs/prd/valuation.md) | [erd/valuation.md](docs/erd/valuation.md) |
| Snapshots, backtesting, audit trail (`FR-ACC`) | [prd/accountability.md](docs/prd/accountability.md) | [erd/accountability.md](docs/erd/accountability.md) |
| Company list, notes, UX/design, frontend (`FR-WS`, `FR-NOTE`) | [prd/workspace.md](docs/prd/workspace.md) | [erd/workspace.md](docs/erd/workspace.md) |
| Login and sessions (`FR-AUTH`) | [prd/auth.md](docs/prd/auth.md) | [erd/auth.md](docs/erd/auth.md) |
| Config, testing, CI, Docker, deploy | [PRD.md §7](docs/PRD.md#7-non-functional-requirements) | [erd/platform.md](docs/erd/platform.md) |

## Workflow
- Each milestone is first broken into large, testable steps by the `plan-milestone` skill (writes `docs/progress/CURRENT.md`, archives the previous one).
- Every implementation runs the `implement` skill, one step at a time: area docs → checklist before any code → item-by-item iteration until every item is verified → doc update → report.
- XBRL mapping problems run the `map-xbrl` skill.
- `/docs-sync` (user-invoked) audits docs against code; `python3 scripts/check_docs.py` is the quick structural check.
- Code and docs never disagree: a changed decision is written into its owning doc in the same change.

## Invariants
- As-reported data (`raw_fact`) is append-only and keeps every filing vintage. User intent lives in adjustments, overrides, drivers and the audit log.
- Domain engines are pure (no DB, no network); routers and the CLI call services only.
- TDD for engine code. Tests use recorded fixtures with no network access and enforce accounting invariants (A = L + E, cash and RE roll-forwards, Q1..Q4 = FY).
- All financial calculation happens in the backend; the frontend only formats and displays.
- Test companies: AAPL, MSFT, COST, DE.
