# ERD · Analysis

> Split of [ERD.md](../ERD.md), originally §4 (comps and guidance tables), §6 (ratio registry) and §7 (analysis routes).
> Product counterpart: [prd/analysis.md](../prd/analysis.md) (`FR-ANL`). Inputs are canonical statements from [erd/data.md](data.md).
> Code: `backend/src/bedrock/ratios/` (ratio definitions registry + calculator), `backend/src/bedrock/analysis/` (`qoe.py` · `capital_allocation.py` · `multiples.py` · `comps.py`).

## Tables (orig. §4)
| Table | Key columns | Notes |
|---|---|---|
| `comps_set` / `comps_member` | id, company_id, name / comps_set_id, peer_company_id | M3 |
| `guidance` | id, company_id, metric (canonical_code or kpi), fiscal_year, fiscal_period, low, high, given_on, source_note | M3 |

## Ratio registry (orig. §6)
Ratios are declared in a registry, not hand-written per ratio, e.g. `Ratio(code="roic", numerator=..., denominator=..., avg_denominator=True, unit="pct")`. This keeps the ratio library data-driven and golden-testable.

## API (orig. §7)
- `GET /companies/{ticker}/ratios`, `/flags`, `/capital-allocation`
- `CRUD /companies/{ticker}/guidance`
