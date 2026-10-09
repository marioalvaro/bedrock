# Vendored edgartools concept table

`edgartools_gaap_mappings.json` is `edgar/xbrl/standardization/gaap_mappings.json` from [dgunning/edgartools](https://github.com/dgunning/edgartools), copied
unchanged. It is licensed under MIT, see `LICENSE-edgartools`. Bedrock has no runtime dependency on
the `edgartools` package.

| | |
|---|---|
| Release tag | `v5.61.1` |
| Commit | `7338aa335f6442c52dfa0695422cf1cd27e946e0` |
| Table version | `3.0.0` (built 2026-02-28) |
| Vendored on | 2026-10-09 |

The table is a **candidate source only**: `mapping/candidates.py` turns it into suggested codes via
`mapping/crosswalk.yaml`, and nothing in it is applied to statements. See docs/erd/data.md,
"Candidate concepts".

Refresh: `cd backend && uv run python scripts/update_edgartools_mappings.py <tag>`.
