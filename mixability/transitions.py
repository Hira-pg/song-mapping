"""Pick a concrete mixing technique for a scored transition."""
from __future__ import annotations

from dataclasses import dataclass

from .scoring import TransitionScore


@dataclass
class Technique:
    name: str
    length: str
    steps: list

    def describe(self) -> str:
        return f"{self.name} ({self.length}): " + "; ".join(self.steps)


def recommend_technique(ts: TransitionScore) -> Technique:
    key_s = ts.parts.get("key", 0.6)
    tm = ts.tempo
    pitch = abs(tm.pitch_pct) if tm else 0.0
    delta = ts.energy_delta or 0.0
    intent = ts.intent or ("boost" if delta >= 1 else "lower" if delta <= -1 else "maintain")
    match_step = (f"set incoming to {ts.a.bpm:.1f} BPM ({tm.pitch_pct:+.1f}%), key lock on"
                  if tm and tm.ratio == 1.0 and pitch > 0.3 else "beatmatch")

    # Half/double time: don't blend beats, use a loop and a hard switch.
    if tm and tm.ratio != 1.0 and pitch <= 6:
        return Technique("Half/double-time switch", "4-8 bars", [
            "loop the last phrase of the outgoing track",
            "bring the incoming track in on the one, its drums at the new feel",
            "kill the loop on the next phrase",
        ])

    # Tempo too far apart to blend cleanly.
    if tm and pitch > 8:
        return Technique("Echo out", "1-2 bars", [
            "on the last phrase of the outgoing track, add a 1-beat echo/delay",
            "pull the outgoing fader down as the echo trails",
            "drop the incoming track on its first downbeat at its own tempo",
        ])

    # Keys clash: keep the overlap short or percussive-only.
    if key_s < 0.4:
        if intent == "boost":
            return Technique("Drop swap", "on the drop", [
                match_step,
                "play both breakdowns' end together for at most 4 bars with the incoming melody low",
                "cut the outgoing track exactly as the incoming drop hits",
            ])
        return Technique("Short percussive blend", "8 bars", [
            match_step,
            "mix in over the outgoing outro or incoming intro where only drums play",
            "keep both melodic parts from overlapping; swap on the phrase",
        ])

    if intent == "boost":
        steps = [match_step,
                 "start the incoming intro under the outgoing breakdown",
                 "swap the bass at the start of a phrase, then cut the outgoing track as the incoming drop lands"]
        if "energy boost" in ts.key_relation:
            steps.insert(1, f"the {ts.key_relation} key change gives an extra lift; keep the overlap short")
        return Technique("Bass-swap lift", "8-16 bars", steps)

    if intent == "lower":
        return Technique("Filter fade", "16-32 bars", [
            match_step,
            "bring the incoming track in under the outgoing outro with its lows cut",
            "gradually high-pass the outgoing track while restoring the incoming lows",
            "let the outgoing track's tail fade out over the last phrase",
        ])

    return Technique("Long blend", "16-32 bars", [
        match_step,
        "start the incoming intro at a phrase boundary under the outgoing outro",
        "swap bass (EQ lows) halfway through, then ease out the outgoing mids/highs",
    ])
