"""Transition scoring: how well does track B follow track A?

Each signal produces a 0-1 sub-score plus a human-readable reason, and the
overall score is a weighted blend (0-100). Weights live in DEFAULT_WEIGHTS so
they can be tuned without touching the logic.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from . import genres, keys
from .models import Track

DEFAULT_WEIGHTS = {"key": 0.30, "tempo": 0.30, "energy": 0.25, "genre": 0.15}

# Target energy change (on the 1-10 scale) for each intent: (ideal delta, tolerance).
INTENTS = {
    "boost": (1.5, 1.0),
    "maintain": (0.0, 0.75),
    "lower": (-1.5, 1.0),
}


@dataclass
class TempoMatch:
    ratio: float          # 1.0 normal, 2.0 / 0.5 for half/double-time
    pitch_pct: float      # % the incoming track must be sped up (+) or slowed (-)
    score: float
    reason: str


@dataclass
class TransitionScore:
    a: Track
    b: Track
    total: float                       # 0-100
    parts: dict = field(default_factory=dict)    # signal -> 0-1
    reasons: dict = field(default_factory=dict)  # signal -> text
    tempo: Optional[TempoMatch] = None
    key_relation: str = ""
    key_energy_hint: int = 0
    energy_delta: Optional[float] = None
    intent: Optional[str] = None


def tempo_match(bpm_a: float, bpm_b: float) -> TempoMatch:
    """Best of straight, half- and double-time; score by pitch change needed."""
    best = None
    for ratio in (1.0, 2.0, 0.5):
        target = bpm_b * ratio
        pct = (bpm_a - target) / target * 100     # speed B up by this to match A
        if best is None or abs(pct) < abs(best[1]):
            best = (ratio, pct)
    ratio, pct = best
    d = abs(pct)
    # Within +/-2% is inaudible; 6% is the edge of comfortable; >10% is a cut.
    if d <= 2:
        s = 1.0
    elif d <= 6:
        s = 1.0 - (d - 2) * 0.1          # 1.0 -> 0.6
    elif d <= 10:
        s = 0.6 - (d - 6) * 0.1          # 0.6 -> 0.2
    else:
        s = max(0.0, 0.2 - (d - 10) * 0.02)
    if ratio != 1.0:
        s *= 0.8                          # half/double time works but is a statement
    kind = {1.0: "", 2.0: " (half-time)", 0.5: " (double-time)"}[ratio]
    return TempoMatch(ratio, round(pct, 2), round(s, 3),
                      f"{bpm_a:.1f} -> {bpm_b:.1f} BPM{kind}, {pct:+.1f}% pitch on incoming")


def energy_fit(delta: float, intent: Optional[str]) -> tuple[float, str]:
    if intent is None:
        # No intent: reward smoothness, penalise big jumps either way.
        s = max(0.0, 1 - max(0.0, abs(delta) - 1) / 4)
        return s, f"energy {delta:+.1f}"
    ideal, tol = INTENTS[intent]
    off = abs(delta - ideal)
    s = 1.0 if off <= tol else max(0.0, 1 - (off - tol) / 3)
    return s, f"energy {delta:+.1f} (target {ideal:+.1f} for {intent})"


def score_transition(a: Track, b: Track, intent: Optional[str] = None,
                     weights: Optional[dict] = None) -> TransitionScore:
    w = dict(weights or DEFAULT_WEIGHTS)
    parts, reasons = {}, {}
    ts = TransitionScore(a=a, b=b, total=0.0, intent=intent)

    if a.key and b.key:
        label, s, hint = keys.relation(a.key, b.key)
        parts["key"], reasons["key"] = s, f"{a.key} -> {b.key}: {label}"
        ts.key_relation, ts.key_energy_hint = label, hint

    if a.bpm and b.bpm:
        tm = tempo_match(a.bpm, b.bpm)
        parts["tempo"], reasons["tempo"] = tm.score, tm.reason
        ts.tempo = tm

    if a.energy is not None and b.energy is not None:
        delta = b.energy - a.energy
        ts.energy_delta = round(delta, 2)
        s, r = energy_fit(delta, intent)
        # A key move that lifts (or drops) in the asked-for direction helps a little.
        if intent in ("boost", "lower") and ts.key_energy_hint:
            want = 1 if intent == "boost" else -1
            s = min(1.0, max(0.0, s + 0.1 * want * ts.key_energy_hint))
        parts["energy"], reasons["energy"] = s, r

    s, r = genres.similarity(a.genre, b.genre)
    parts["genre"], reasons["genre"] = s, r

    # Missing signals drop out and the remaining weights are rescaled.
    total_w = sum(w[k] for k in parts)
    ts.total = round(100 * sum(w[k] * parts[k] for k in parts) / total_w, 1) if total_w else 0.0
    # A hard clash in key or tempo shouldn't be rescued by the other signals.
    worst = min(parts.get("key", 1), parts.get("tempo", 1))
    if worst < 0.3:
        ts.total = round(ts.total * (0.7 + worst), 1)
    ts.parts = {k: round(v, 3) for k, v in parts.items()}
    ts.reasons = reasons
    return ts
