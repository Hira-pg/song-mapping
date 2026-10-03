"""Fill missing BPM / key / energy for streaming tracks from online databases.

- Deezer (no key needed): looks a track up by ISRC and returns `bpm` and
  `gain` (loudness). https://api.deezer.com/track/isrc:<ISRC>
- GetSongBPM (free API key from https://getsongbpm.com/api, set
  GETSONGBPM_API_KEY): searches by artist and title and returns `tempo`,
  `key_of`, `open_key` and `danceability`. Their terms ask for a visible
  backlink to getsongbpm.com wherever the data is shown.

Energy from lookups is approximate (danceability, tempo and loudness); audio
analysis of a local file replaces it. Only empty fields are filled, so
tags, analysis and manual edits always win. Not yet run against the live APIs.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

from ..keys import normalize_key
from ..library import Library
from ..models import Track

try:  # python.org builds on macOS ship without root certificates
    import certifi, ssl
    urllib.request.install_opener(urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=certifi.where()))))
except ImportError:
    pass

DEEZER = "https://api.deezer.com"
GETSONG = os.environ.get("GETSONGBPM_BASE", "https://api.getsong.co")


def _get_json(url: str) -> Optional[dict]:
    req = urllib.request.Request(url, headers={"User-Agent": "mixability/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.load(r)
    except (urllib.error.URLError, ValueError):
        return None


def deezer_by_isrc(isrc: str) -> dict:
    d = _get_json(f"{DEEZER}/track/isrc:{urllib.parse.quote(isrc)}") or {}
    if d.get("error"):
        return {}
    out = {}
    if d.get("bpm"):
        out["bpm"] = float(d["bpm"])
    if d.get("gain") is not None:
        out["gain_db"] = float(d["gain"])
    return out


def _first_artist(artist: str) -> str:
    return artist.split(",")[0].split(" feat")[0].strip()


def getsongbpm(artist: str, title: str, api_key: str) -> dict:
    q = urllib.parse.urlencode({"api_key": api_key, "type": "both",
                                "lookup": f"song:{title} artist:{_first_artist(artist)}"})
    d = _get_json(f"{GETSONG}/search/?{q}") or {}
    hits = d.get("search")
    if not isinstance(hits, list) or not hits:
        return {}
    h = hits[0]
    out = {}
    if h.get("tempo"):
        try:
            out["bpm"] = float(h["tempo"])
        except ValueError:
            pass
    # key_of ("F♯m") is unambiguous; open_key could be Open Key or Camelot.
    key = normalize_key(h.get("key_of") or "") or normalize_key(h.get("open_key") or "")
    if key:
        out["key"] = key
    if h.get("danceability") not in (None, ""):
        out["danceability"] = float(h["danceability"])
    return out


def approx_energy(bpm: Optional[float], danceability: Optional[float], gain_db: Optional[float]) -> Optional[float]:
    parts = []
    if danceability is not None:
        parts.append((0.5, min(max(danceability / 100, 0), 1)))
    if bpm:
        parts.append((0.3, min(max((bpm - 85) / 65, 0), 1)))
    if gain_db is not None:  # Deezer gain: more negative = louder master
        parts.append((0.2, min(max((-gain_db - 4) / 10, 0), 1)))
    if not parts or danceability is None:
        return None
    w = sum(p[0] for p in parts)
    return round(1 + 9 * sum(a * b for a, b in parts) / w, 1)


def fill_missing(library: Library, log=sys.stderr, delay: float = 0.2) -> int:
    api_key = os.environ.get("GETSONGBPM_API_KEY")
    if not api_key:
        print("GETSONGBPM_API_KEY not set: BPM only (from Deezer), no key or energy", file=log)
    changed = 0
    todo = [t for t in library if t.bpm is None or t.key is None or t.energy is None]
    for i, t in enumerate(todo, 1):
        found = {}
        isrc = t.features.get("isrc")
        if isrc:
            found.update(deezer_by_isrc(isrc))
        if api_key:
            g = getsongbpm(t.artist, t.title.split(" (")[0], api_key)
            found.setdefault("bpm", g.get("bpm"))
            found.update({k: v for k, v in g.items() if k != "bpm"})
        updated = []
        for attr, src in (("bpm", "lookup"), ("key", "getsongbpm")):
            if getattr(t, attr) is None and found.get(attr):
                setattr(t, attr, found[attr])
                t.provenance[attr] = src
                updated.append(attr)
        for f in ("danceability", "gain_db"):
            if found.get(f) is not None:
                t.features[f] = found[f]
        if t.energy is None:
            e = approx_energy(t.bpm, t.features.get("danceability"), t.features.get("gain_db"))
            if e is not None:
                t.energy, t.provenance["energy"] = e, "lookup"
                updated.append("energy")
        if updated:
            changed += 1
        print(f"[{i}/{len(todo)}] {t.label}: {', '.join(updated) or 'nothing found'}", file=log)
        time.sleep(delay)
    return changed
