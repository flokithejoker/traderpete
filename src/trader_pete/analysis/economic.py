from __future__ import annotations

import re

WRAPPER_MARKERS = {
    "bstock",
    "bstocks",
    "xstock",
    "xstocks",
    "tokenized",
    "tokenised",
    "stock",
    "stocks",
    "equity",
    "share",
    "shares",
    "token",
}

# Deterministic aliases are deliberately small. Unknown wrappers collapse to one
# ambiguous bucket and therefore cannot inflate breadth until an explicit mapping
# adapter supplies the economic underlying.
UNDERLYING_ALIASES = {
    "aapl": "aapl",
    "alphabet": "googl",
    "amzn": "amzn",
    "amazon": "amzn",
    "apple": "aapl",
    "google": "googl",
    "googl": "googl",
    "meta": "meta",
    "microsoft": "msft",
    "msft": "msft",
    "nvidia": "nvda",
    "nvda": "nvda",
    "spacex": "spacex",
    "tesla": "tsla",
    "tsla": "tsla",
}


def economic_underlying_key(*, asset_id: str, name: str, symbol: str) -> str:
    """Collapse multiple wrappers of the same off-chain economic exposure.

    Ordinary crypto assets retain their exact provider ID. Only names that explicitly look like
    tokenized equity wrappers are normalized, which avoids merging unrelated similarly named coins.
    """
    raw = f"{asset_id} {name}".lower()
    looks_wrapped = any(
        marker in raw
        for marker in ("bstock", "xstock", "tokenized stock", "tokenised stock", "tokenized equity")
    )
    if not looks_wrapped:
        return asset_id
    words = re.findall(r"[a-z0-9]+", f"{name} {asset_id}".lower())
    meaningful = [word for word in words if word not in WRAPPER_MARKERS]
    for word in meaningful:
        if word in UNDERLYING_ALIASES:
            return f"wrapped:{UNDERLYING_ALIASES[word]}"
    return "wrapped:ambiguous"


def wrapper_issuer_key(*, asset_id: str, name: str) -> str:
    raw = f"{asset_id} {name}".lower()
    for marker in ("xstocks", "xstock", "bstocks", "bstock"):
        if marker in raw:
            return marker.rstrip("s")
    return asset_id
