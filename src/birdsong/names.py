from __future__ import annotations

import re
import unicodedata

_DASH_TRANSLATION = str.maketrans(
    {
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2015": "-",
        "\u2212": "-",
    }
)

_APOSTROPHES = {
    "'",
    "\u2018",
    "\u2019",
    "\u201b",
    "\u2032",
    "\u00b4",
    "`",
}


def normalize_name(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.translate(_DASH_TRANSLATION))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    pieces: list[str] = []
    for ch in value.casefold():
        if ch.isalnum():
            pieces.append(ch)
        elif ch in _APOSTROPHES:
            continue
        else:
            pieces.append(" ")
    normalized = "".join(pieces)
    return re.sub(r"\s+", " ", normalized).strip()


def sanitize_filename_component(value: str) -> str:
    value = value.translate(_DASH_TRANSLATION)
    cleaned = []
    for ch in value:
        if ch.isalnum() or ch in {" ", "-", "_", "."}:
            cleaned.append(ch)
        elif ch in _APOSTROPHES:
            continue
        else:
            cleaned.append("-")
    result = re.sub(r"[- ]+", " ", "".join(cleaned)).strip()
    return result or "unknown"
