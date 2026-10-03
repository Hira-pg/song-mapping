"""Audio analysis: BPM, key, energy and tag reading for local files.

Tags written by DJ software (Mixed In Key, Rekordbox, Serato, Traktor) are
used when present because they are usually more accurate than a quick
analysis pass; set prefer_tags=False to always analyse the audio.
"""
from __future__ import annotations

import hashlib
import os
import re
from typing import Optional

import numpy as np

from .keys import normalize_key, to_camelot
from .models import Track

AUDIO_EXTS = {".mp3", ".flac", ".wav", ".aiff", ".aif", ".m4a", ".ogg"}

# Krumhansl-Kessler key profiles.
_MAJOR_PROFILE = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
_MINOR_PROFILE = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


def track_id_for_path(path: str) -> str:
    return "local:" + hashlib.sha1(os.path.abspath(path).encode()).hexdigest()[:12]


# --------------------------------------------------------------------------- tags

def read_tags(path: str) -> dict:
    """Return whatever of title/artist/genre/bpm/key/energy the tags carry."""
    try:
        import mutagen
    except ImportError:
        return {}
    try:
        f = mutagen.File(path, easy=True)
    except Exception:
        return {}
    if f is None or f.tags is None:
        return {}

    def first(*names):
        for n in names:
            v = f.tags.get(n)
            if v:
                return str(v[0]).strip()
        return None

    out = {
        "title": first("title"),
        "artist": first("artist"),
        "genre": first("genre"),
    }
    bpm = first("bpm")
    if bpm:
        try:
            out["bpm"] = float(bpm)
        except ValueError:
            pass
    out["key"] = normalize_key(first("initialkey", "key"))

    # Mixed In Key writes "8A - Energy 6" into the comment (non-easy tag).
    try:
        raw = mutagen.File(path)
        comments = [str(v) for k, v in (raw.tags or {}).items() if k.startswith("COMM")]
        for c in comments:
            m = re.search(r"energy\s*(\d{1,2})", c, re.I)
            if m:
                out["energy"] = float(m.group(1))
            if not out.get("key"):
                m = re.match(r"\s*(\d{1,2}[AB])\b", c)
                if m:
                    out["key"] = normalize_key(m.group(1))
    except Exception:
        pass
    return {k: v for k, v in out.items() if v}


# ----------------------------------------------------------------------- analysis

def detect_key(chroma_mean: np.ndarray) -> tuple[str, float]:
    """Correlate a 12-bin chroma vector with every major/minor profile."""
    best = (-2.0, 0, "major")
    for pc in range(12):
        for mode, prof in (("major", _MAJOR_PROFILE), ("minor", _MINOR_PROFILE)):
            r = np.corrcoef(chroma_mean, np.roll(prof, pc))[0, 1]
            if r > best[0]:
                best = (r, pc, mode)
    r, pc, mode = best
    return to_camelot(pc, mode), float(r)


def _refine_bpm(y, sr, coarse: float, beat_times: np.ndarray) -> float:
    if len(beat_times) < 8 or not coarse:
        return coarse
    idx = np.arange(len(beat_times))
    slope, _ = np.polyfit(idx, beat_times, 1)
    fine = 60.0 / slope
    if abs(fine - coarse) / coarse > 0.05:   # fit went wrong, keep the estimate
        return coarse
    # Most dance music is produced at whole-number tempos.
    return float(round(fine)) if abs(fine - round(fine)) < 0.15 else fine


def analyse_audio(path: str, max_seconds: float = 240.0) -> dict:
    """Extract bpm, key and raw energy features from an audio file."""
    import librosa

    y, sr = librosa.load(path, sr=22050, mono=True, duration=max_seconds)
    duration = librosa.get_duration(path=path)

    # Tempo: beat tracker, then fold into a typical DJ range (octave errors
    # are also tolerated later by half/double-time matching).
    onset_env = librosa.onset.onset_strength(y=y, sr=sr)
    tempo, beats = librosa.beat.beat_track(onset_envelope=onset_env, sr=sr, start_bpm=124)
    bpm = float(np.atleast_1d(tempo)[0])
    # The tempo estimate is quantised to the analysis grid (~2-3 BPM steps);
    # refine it with a line fit through the beat positions.
    bpm = _refine_bpm(y, sr, bpm, librosa.frames_to_time(beats, sr=sr))
    while bpm and bpm < 70:
        bpm *= 2
    while bpm > 190:
        bpm /= 2

    # Key: harmonic component only, so drums don't smear the chroma.
    y_harm = librosa.effects.harmonic(y)
    chroma = librosa.feature.chroma_cqt(y=y_harm, sr=sr)
    key, key_conf = detect_key(chroma.mean(axis=1))

    # Energy ingredients.
    rms = librosa.feature.rms(y=y)[0]
    loudness_db = float(20 * np.log10(np.mean(rms) + 1e-9))
    centroid = float(np.mean(librosa.feature.spectral_centroid(y=y, sr=sr)))
    onsets = librosa.onset.onset_detect(onset_envelope=onset_env, sr=sr)
    onset_rate = float(len(onsets) / (len(y) / sr))
    # Dynamic range: compressed, wall-of-sound tracks feel more energetic.
    dyn_range = float(np.percentile(rms, 95) / (np.percentile(rms, 10) + 1e-9))

    return {
        "bpm": round(bpm, 2),
        "key": key,
        "duration": round(duration, 1),
        "features": {
            "key_confidence": round(key_conf, 3),
            "loudness_db": round(loudness_db, 2),
            "brightness_hz": round(centroid, 1),
            "onset_rate": round(onset_rate, 3),
            "dynamic_range": round(dyn_range, 2),
        },
    }


def raw_energy(features: dict, bpm: Optional[float]) -> Optional[float]:
    """Combine features into an unscaled energy value (roughly 0-1)."""
    if not features or "loudness_db" not in features:
        return None

    def scale(v, lo, hi):
        return float(np.clip((v - lo) / (hi - lo), 0, 1))

    parts = [
        (0.35, scale(features["loudness_db"], -30, -8)),
        (0.25, scale(features["onset_rate"], 0.5, 5.0)),
        (0.15, scale(features["brightness_hz"], 1000, 3500)),
        (0.10, 1 - scale(features.get("dynamic_range", 4), 1.5, 12)),
        (0.15, scale(bpm or 120, 85, 150)),
    ]
    return sum(w * v for w, v in parts)


def energy_from_raw(raw: float) -> float:
    """Fixed mapping of raw energy to 1-10, used before library normalisation."""
    return round(1 + 9 * raw, 1)


def analyse_file(path: str, prefer_tags: bool = True) -> Track:
    tags = read_tags(path)
    stem = os.path.splitext(os.path.basename(path))[0]
    title, artist = tags.get("title"), tags.get("artist")
    if not title and " - " in stem:
        artist, title = stem.split(" - ", 1)
    t = Track(id=track_id_for_path(path), title=title or stem, artist=artist or "",
              source="local", path=os.path.abspath(path), genre=tags.get("genre"))
    if t.genre:
        t.provenance["genre"] = "tag"

    need = {"bpm", "key", "energy"}
    if prefer_tags:
        for attr in ("bpm", "key", "energy"):
            if tags.get(attr) is not None:
                setattr(t, attr, tags[attr])
                t.provenance[attr] = "tag"
                need.discard(attr)

    a = analyse_audio(path)
    t.duration = a["duration"]
    t.features = a["features"]
    for attr in ("bpm", "key"):
        if attr in need:
            setattr(t, attr, a[attr])
            t.provenance[attr] = "analysis"
    t.features["raw_energy"] = round(raw_energy(t.features, t.bpm), 4)
    if "energy" in need:
        t.energy = energy_from_raw(t.features["raw_energy"])
        t.provenance["energy"] = "analysis"
    return t
