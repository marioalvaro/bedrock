"""Per-company caveats attached to ratio rows (`caveats.yaml`). Pure apart from reading the file."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from bedrock.ratios.registry import RATIOS, RegistryError

DEFAULT_CAVEATS_PATH = Path(__file__).parent / "caveats.yaml"


@dataclass(frozen=True)
class Caveat:
    codes: frozenset[str]  # ratio codes the text applies to
    text: str


def load_caveats(path: Path = DEFAULT_CAVEATS_PATH) -> dict[str, tuple[Caveat, ...]]:
    """`{TICKER: [{codes: [...], text: ...}]}` -> {ticker (upper case): caveats}.

    Raises `RegistryError` (from `ratios/registry.py`) for a code that is not in `RATIOS`, an
    empty `codes` list or an empty text, a code in two caveats of one ticker (a row carries at most
    one caveat), or a file that is not that shape."""
    raw = yaml.safe_load(path.read_text())
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise RegistryError(f"{path.name} must map tickers to caveat lists")
    known = {ratio.code for ratio in RATIOS}
    result: dict[str, tuple[Caveat, ...]] = {}
    for ticker, entries in raw.items():
        if not isinstance(ticker, str) or not ticker.strip():
            raise RegistryError(f"{path.name}: ticker {ticker!r} must be a non-empty string")
        key = ticker.strip().upper()
        if key in result:
            raise RegistryError(f"{key}: duplicate ticker")
        if not isinstance(entries, list):
            raise RegistryError(f"{key}: caveats must be a list")
        caveats = tuple(_caveat(key, entry, known) for entry in entries)
        covered: set[str] = set()
        for caveat in caveats:
            if repeated := caveat.codes & covered:
                raise RegistryError(
                    f"{key}: ratio codes {sorted(repeated)} in more than one caveat"
                )
            covered |= caveat.codes
        result[key] = caveats
    return result


def _caveat(ticker: str, entry: Any, known: set[str]) -> Caveat:
    if not isinstance(entry, dict) or set(entry) != {"codes", "text"}:
        raise RegistryError(f"{ticker}: each caveat must be a mapping with exactly codes and text")
    codes, text = entry["codes"], entry["text"]
    if not isinstance(codes, list) or not codes:
        raise RegistryError(f"{ticker}: caveat codes must be a non-empty list")
    for code in codes:
        if not isinstance(code, str):
            raise RegistryError(f"{ticker}: caveat code {code!r} must be a string")
        if code not in known:
            raise RegistryError(f"{ticker}: unknown ratio code {code!r}")
    if not isinstance(text, str) or not text.strip():
        raise RegistryError(f"{ticker}: caveat text must be a non-empty string")
    return Caveat(codes=frozenset(codes), text=text.strip())
