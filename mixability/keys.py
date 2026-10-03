"""Musical key handling on the Camelot wheel.

Camelot numbers 1-12 walk the circle of fifths; "A" is minor, "B" is major.
Moving +1 around the wheel is a fifth up (a subtle lift), switching A->B is
minor to relative major (brighter), and +2 / +7 are the classic "energy boost"
key changes (whole tone and semitone up).
"""
from __future__ import annotations

import re
from typing import Optional, Tuple

PITCHES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
_ALIASES = {"DB": "C#", "EB": "D#", "GB": "F#", "AB": "G#", "BB": "A#",
            "CB": "B", "FB": "E", "E#": "F", "B#": "C"}

# Camelot number for each pitch class, major (B) and minor (A).
_MAJOR_NUM = {0: 8, 7: 9, 2: 10, 9: 11, 4: 12, 11: 1, 6: 2, 1: 3, 8: 4, 3: 5, 10: 6, 5: 7}
_MINOR_NUM = {9: 8, 4: 9, 11: 10, 6: 11, 1: 12, 8: 1, 3: 2, 10: 3, 5: 4, 0: 5, 7: 6, 2: 7}


def to_camelot(pitch_class: int, mode: str) -> str:
    if mode.lower().startswith("maj"):
        return f"{_MAJOR_NUM[pitch_class % 12]}B"
    return f"{_MINOR_NUM[pitch_class % 12]}A"


def camelot_to_name(code: str) -> str:
    num, letter = parse_camelot(code)
    table = _MAJOR_NUM if letter == "B" else _MINOR_NUM
    pc = next(p for p, n in table.items() if n == num)
    return f"{PITCHES[pc]} {'major' if letter == 'B' else 'minor'}"


def parse_camelot(code: str) -> Tuple[int, str]:
    m = re.fullmatch(r"\s*(\d{1,2})\s*([AaBb])\s*", code)
    if not m or not 1 <= int(m.group(1)) <= 12:
        raise ValueError(f"not a Camelot key: {code!r}")
    return int(m.group(1)), m.group(2).upper()


def normalize_key(text: Optional[str]) -> Optional[str]:
    """Accept Camelot ("8A"), Open Key ("1m"), or names ("Am", "A minor", "F#maj")."""
    if not text:
        return None
    t = text.strip()
    try:
        n, l = parse_camelot(t)
        return f"{n}{l}"
    except ValueError:
        pass
    m = re.fullmatch(r"(\d{1,2})\s*([mMdD])", t)  # Open Key notation
    if m and 1 <= int(m.group(1)) <= 12:
        n = (int(m.group(1)) + 6) % 12 + 1
        return f"{n}{'A' if m.group(2).lower() == 'm' else 'B'}"
    m = re.fullmatch(r"([A-Ga-g])([#b♯♭]?)\s*(.*)", t)
    if not m:
        return None
    root = (m.group(1).upper() + m.group(2).replace("♯", "#").replace("♭", "b")).upper()
    root = _ALIASES.get(root, root)
    if root not in PITCHES:
        return None
    rest = m.group(3).strip().lower()
    minor = rest.startswith("m") and not rest.startswith("maj") or rest.startswith("min")
    return to_camelot(PITCHES.index(root), "minor" if minor else "major")


def relation(a: str, b: str) -> Tuple[str, float, int]:
    """Describe the move from key a to key b.

    Returns (label, compatibility 0-1, energy_hint) where energy_hint is
    +1 for a move that lifts the mood, -1 for one that lowers it, 0 neutral.
    """
    na, la = parse_camelot(a)
    nb, lb = parse_camelot(b)
    step = (nb - na) % 12            # clockwise distance
    same_letter = la == lb

    if same_letter and step == 0:
        return "same key", 1.0, 0
    if not same_letter and step == 0:
        lift = 1 if lb == "B" else -1
        return ("relative major" if lift > 0 else "relative minor"), 0.9, lift
    if same_letter and step == 1:
        return "+1 on wheel (fifth up)", 0.9, 1
    if same_letter and step == 11:
        return "-1 on wheel (fifth down)", 0.9, -1
    if not same_letter and step in (1, 11):
        lift = 1 if step == 1 else -1
        return "diagonal move", 0.7, lift
    if same_letter and step == 2:
        return "energy boost (+2, whole tone up)", 0.65, 1
    if same_letter and step == 10:
        return "-2 on wheel (whole tone down)", 0.55, -1
    if same_letter and step == 7:
        return "energy boost (+7, semitone up)", 0.55, 1
    if same_letter and step == 5:
        return "-7 on wheel (semitone down)", 0.45, -1
    # Anything else clashes; further around the wheel is worse.
    dist = min(step, 12 - step)
    return "key clash", max(0.0, 0.35 - 0.05 * dist), 0
