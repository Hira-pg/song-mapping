"""Genre similarity.

Genres are mapped to a family, and families have hand-tuned neighbours. Edit
FAMILIES / NEIGHBOURS to match your own taste; that is the intended way to
tune this signal.
"""
from __future__ import annotations

import re
from typing import Optional, Tuple

FAMILIES = {
    "house": ["house", "deep house", "tech house", "progressive house", "afro house",
              "funky house", "jackin house", "soulful house", "garage house", "melodic house",
              "organic house", "electro house", "bass house", "future house", "dance"],
    "techno": ["techno", "melodic techno", "peak time techno", "hard techno", "minimal",
               "minimal techno", "industrial techno", "acid techno", "dub techno"],
    "trance": ["trance", "progressive trance", "psytrance", "psy trance", "uplifting trance",
               "hard trance", "goa"],
    "disco": ["disco", "nu disco", "nu-disco", "funk", "boogie", "italo disco", "indie dance"],
    "breaks": ["breaks", "breakbeat", "uk garage", "garage", "2-step", "speed garage", "bassline"],
    "dnb": ["drum and bass", "drum & bass", "dnb", "d&b", "jungle", "liquid", "neurofunk"],
    "bass": ["dubstep", "bass", "trap", "riddim", "future bass", "halftime"],
    "hiphop": ["hip hop", "hip-hop", "rap", "r&b", "rnb", "grime", "drill"],
    "pop": ["pop", "dance pop", "electropop", "synthpop", "indie pop", "edm", "big room"],
    "latin": ["reggaeton", "latin", "dembow", "baile funk", "moombahton", "dancehall", "afrobeats", "amapiano"],
    "downtempo": ["downtempo", "chillout", "ambient", "lo-fi", "lofi", "trip hop", "electronica"],
}

NEIGHBOURS = {
    ("house", "techno"), ("house", "disco"), ("house", "breaks"), ("house", "pop"),
    ("house", "latin"), ("techno", "trance"), ("breaks", "dnb"), ("breaks", "bass"),
    ("dnb", "bass"), ("bass", "hiphop"), ("hiphop", "latin"), ("hiphop", "pop"),
    ("pop", "latin"), ("disco", "pop"), ("downtempo", "house"), ("trance", "pop"),
}

_LOOKUP = {g: fam for fam, gs in FAMILIES.items() for g in gs}


def _clean(g: str) -> str:
    return re.sub(r"\s+", " ", g.strip().lower().replace("_", " "))


def family(genre: Optional[str]) -> Optional[str]:
    if not genre:
        return None
    g = _clean(genre)
    if g in _LOOKUP:
        return _LOOKUP[g]
    # Fall back to the longest known genre name contained in the string,
    # e.g. "Melodic House & Techno" -> house (first longest match).
    hits = sorted((k for k in _LOOKUP if re.search(rf"\b{re.escape(k)}\b", g)), key=len, reverse=True)
    return _LOOKUP[hits[0]] if hits else None


def similarity(a: Optional[str], b: Optional[str]) -> Tuple[float, str]:
    """Return (score 0-1, explanation)."""
    if not a or not b:
        return 0.6, "genre unknown"
    if _clean(a) == _clean(b):
        return 1.0, "same genre"
    fa, fb = family(a), family(b)
    if fa is None or fb is None:
        return 0.6, "genre not in map"
    if fa == fb:
        return 0.85, f"same family ({fa})"
    if (fa, fb) in NEIGHBOURS or (fb, fa) in NEIGHBOURS:
        return 0.55, f"neighbouring families ({fa} / {fb})"
    return 0.2, f"distant genres ({fa} / {fb})"
