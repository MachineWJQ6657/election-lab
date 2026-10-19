"""Shared candidate matching keys; preserve original spelling for display."""

import re
import unicodedata


def candidate_key(value: object) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode().casefold()
    tokens = re.findall(r"[a-z]+", text)
    if (
        text in {"nan", "none", "null"}
        or not tokens
        or any(token in {"tbd", "unknown", "nominee"} for token in tokens)
    ):
        return ""
    while tokens and tokens[-1] in {"jr", "sr", "ii", "iii", "iv"}:
        tokens.pop()
    return tokens[-1] if tokens else ""
