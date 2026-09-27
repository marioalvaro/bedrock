# ERD · Workspace, Notes & Frontend

> Split of [ERD.md](../ERD.md), originally §4 (`note` table) and §7 (notes route, API client codegen).
> Product counterpart: [prd/workspace.md](../prd/workspace.md) (`FR-NOTE`, `FR-WS`, UX & design). Frontend stack: [ERD.md §2](../ERD.md#2-tech-stack); frontend folder layout: [ERD.md §3](../ERD.md#3-project-structure).
> Code: `frontend/src/`, backend `api/v1/` notes router.

## Tables (orig. §4)
| Table | Key columns | Notes |
|---|---|---|
| `note` | id, company_id, body_md, canonical_code NULL, fiscal_year NULL, fiscal_period NULL, note_date, created_at, updated_at | M3 |

## API (orig. §7)
- `CRUD /companies/{ticker}/notes`
- Codegen: `bedrock export-openapi ../frontend/openapi.json` writes the schema, with no running server needed. `pnpm gen:api` regenerates `src/api/generated/` from it with `@hey-api/openapi-ts` + `@hey-api/client-fetch`. Both files are committed; CI fails if either differs after regeneration.
