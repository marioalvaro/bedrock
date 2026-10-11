"""Refresh the vendored edgartools concept table (needs network).

Usage (from backend/):  uv run python scripts/update_edgartools_mappings.py v5.61.1

Downloads `edgar/xbrl/standardization/gaap_mappings.json` and `LICENSE.txt` of the given edgartools
release tag into src/bedrock/mapping/vendor/, rewrites vendor/README.md with the tag and commit, and
then validates the crosswalk against the new table. A standard concept the crosswalk does not list
(or lists but the table dropped) fails with its name: add it to `mapping/crosswalk.yaml` as a code
or as `unmapped` with a reason, then run the tests.
"""

import json
import sys
import urllib.request
from datetime import date
from pathlib import Path

from bedrock.mapping.candidates import (
    DEFAULT_CROSSWALK_PATH,
    DEFAULT_VENDOR_PATH,
    load_candidate_index,
)
from bedrock.mapping.config import DEFAULT_ITEMS_PATH, MappingConfigError, load_canonical_items

REPO = "dgunning/edgartools"
TABLE_PATH = "edgar/xbrl/standardization/gaap_mappings.json"
VENDOR_DIR = DEFAULT_VENDOR_PATH.parent


def _get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "Bedrock vendor refresh"})
    with urllib.request.urlopen(request, timeout=60) as response:
        body: bytes = response.read()
    return body


def readme(tag: str, commit: str, table: dict[str, object]) -> str:
    meta = table.get("_metadata")
    meta = meta if isinstance(meta, dict) else {}
    return f"""# Vendored edgartools concept table

`{DEFAULT_VENDOR_PATH.name}` is `{TABLE_PATH}` from [{REPO}](https://github.com/{REPO}), copied
unchanged. It is licensed under MIT, see `LICENSE-edgartools`. Bedrock has no runtime dependency on
the `edgartools` package.

| | |
|---|---|
| Release tag | `{tag}` |
| Commit | `{commit}` |
| Table version | `{meta.get("version", "?")}` (built {str(meta.get("build_date", "?"))[:10]}) |
| Vendored on | {date.today().isoformat()} |

The table is a **candidate source only**: `mapping/candidates.py` turns it into suggested codes via
`mapping/crosswalk.yaml`, and nothing in it is applied to statements. See docs/erd/data.md,
"Candidate concepts".

Refresh: `cd backend && uv run python scripts/update_edgartools_mappings.py <tag>`.
"""


def main(tag: str) -> None:
    commit = json.loads(_get(f"https://api.github.com/repos/{REPO}/git/ref/tags/{tag}"))["object"][
        "sha"
    ]
    raw = f"https://raw.githubusercontent.com/{REPO}/{tag}"
    table_bytes = _get(f"{raw}/{TABLE_PATH}")
    DEFAULT_VENDOR_PATH.write_bytes(table_bytes)
    (VENDOR_DIR / "LICENSE-edgartools").write_bytes(_get(f"{raw}/LICENSE.txt"))
    (VENDOR_DIR / "README.md").write_text(readme(tag, commit, json.loads(table_bytes)))
    print(f"wrote {DEFAULT_VENDOR_PATH.relative_to(Path.cwd())} ({tag}, {commit[:10]})")
    try:
        index = load_candidate_index(
            DEFAULT_VENDOR_PATH,
            DEFAULT_CROSSWALK_PATH,
            load_canonical_items(DEFAULT_ITEMS_PATH),
        )
    except MappingConfigError as error:
        sys.exit(f"crosswalk needs an update: {error}")
    print(f"crosswalk ok: {len(index)} concepts have a candidate code")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
