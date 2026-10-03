"""Fill missing BPM / key / energy for streaming tracks from online sources.

- Deezer (no key needed): finds the track by ISRC (or artist + title) and
  returns `bpm`, `gain` (loudness) and a 30-second `preview` MP3. The preview
  is run through the same audio analysis as local files, which gives key and
  energy even for remixes and underground tracks the databases don't know.
- GetSongBPM (free API key from https://getsongbpm.com/api, set
  GETSONGBPM_API_KEY): searches by artist and title and returns `tempo`,
  `key_of`, `open_key` and `danceability`. Their terms ask for a visible
  backlink to getsongbpm.com wherever the data is shown.

Preview analysis is less accurate than a full file; analysing a local
copy with `analyze` replaces it. Only empty fields are filled, so
tags, analysis and manual edits always win. Not yet run against the live APIs.
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import time
import unicodedata
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


def _fold(s: str) -> str:
    """Lowercase, strip accents and punctuation: "Tiësto" -> "tiesto"."""
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def clean_title(title: str) -> str:
    """Drop "(feat. X)", "[Remix]", "(Radio Edit)" and similar suffixes."""
    t = re.sub(r"\s*[\(\[][^\)\]]*[\)\]]", "", title)
    return re.sub(r"\s+-\s+.*$", "", t).strip() or title


def is_alt_version(title: str) -> bool:
    """Remixes and bootlegs differ from the original in BPM and key."""
    t = title.lower()
    return bool(re.search(r"remix|bootleg|flip|vip|recut|rework|mashup|\bmix\)|\bdubstep\)", t))


def _artists(artist: str) -> list:
    parts = re.split(r",|&| feat\.? | x | and ", artist, flags=re.I)
    return [p.strip() for p in parts if p.strip()]


def getsongbpm(artist: str, title: str, api_key: str) -> dict:
    """Search by title plus each credited artist; only accept a hit whose artist matches."""
    want = {_fold(a) for a in _artists(artist)}
    song = clean_title(title)
    queries = [f"song:{song} artist:{a}" for a in _artists(artist)[:3]] + [f"song:{song}"]
    hit = None
    for lookup in queries:
        q = urllib.parse.urlencode({"api_key": api_key, "type": "both", "lookup": lookup})
        d = _get_json(f"{GETSONG}/search/?{q}") or {}
        hits = d.get("search")
        if not isinstance(hits, list):
            continue
        for h in hits:
            name = _fold((h.get("artist") or {}).get("name", "")) if isinstance(h.get("artist"), dict) else ""
            if _fold(h.get("title", "")) == _fold(song) and (not name or name in want or any(w in name for w in want)):
                hit = h
                break
        if hit:
            break
    if not hit:
        return {}
    out = {}
    try:
        if hit.get("tempo"):
            out["bpm"] = float(hit["tempo"])
    except ValueError:
        pass
    # key_of ("F♯m") is unambiguous; open_key could be Open Key or Camelot.
    key = normalize_key(hit.get("key_of") or "") or normalize_key(hit.get("open_key") or "")
    if key:
        out["key"] = key
    if hit.get("danceability") not in (None, ""):
        try:
            out["danceability"] = float(hit["danceability"])
        except ValueError:
            pass
    return out


def deezer_track(isrc: Optional[str], artist: str, title: str) -> dict:
    """Deezer track by ISRC, falling back to an artist + title search."""
    if isrc:
        d = _get_json(f"{DEEZER}/track/isrc:{urllib.parse.quote(isrc)}") or {}
        if not d.get("error") and d.get("id"):
            return d
    q = urllib.parse.urlencode({"q": f'artist:"{_artists(artist)[0] if artist else ""}" track:"{clean_title(title)}"'})
    d = _get_json(f"{DEEZER}/search?{q}") or {}
    want = {_fold(a) for a in _artists(artist)}
    for h in d.get("data") or []:
        if _fold((h.get("artist") or {}).get("name", "")) in want:
            return h
    return {}


def analyse_preview(url: str) -> Optional[dict]:
    """Download a 30-second preview and run the normal audio analysis on it."""
    from ..analysis import analyse_audio
    fd, path = tempfile.mkstemp(suffix=".mp3")
    os.close(fd)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "mixability/0.1"})
        with urllib.request.urlopen(req, timeout=30) as r, open(path, "wb") as f:
            f.write(r.read())
        return analyse_audio(path)
    except Exception as e:  # report, but keep going with the other tracks
        print(f"    preview analysis failed: {type(e).__name__}: {e}", file=sys.stderr)
        return None
    finally:
        os.remove(path)


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


_TRUSTED = {"analysis", "tag", "manual"}


def fill_missing(library: Library, log=sys.stderr, delay: float = 0.2, previews: bool = True) -> int:
    """Fill BPM/key/energy for tracks that have no local audio.

    Order of trust: tags/analysis/manual edits are never touched; GetSongBPM
    (full-track data) is preferred for key and BPM of original versions;
    the Deezer 30s preview analysis supplies energy for every track (so energy
    is on one consistent scale) and fills key/BPM where nothing else did,
    including remixes, whose key and tempo often differ from the original.
    """
    from ..analysis import energy_from_raw, raw_energy

    api_key = os.environ.get("GETSONGBPM_API_KEY")
    if not api_key:
        print("GETSONGBPM_API_KEY not set: skipping GetSongBPM", file=log)
    changed = 0
    todo = [t for t in library if t.bpm is None or t.key is None
            or t.provenance.get("energy") not in _TRUSTED]
    for i, t in enumerate(todo, 1):
        updated = []

        def put(attr, val, src, overwrite=False):
            if val is None or t.provenance.get(attr) in _TRUSTED:
                return
            if getattr(t, attr) is None or overwrite:
                setattr(t, attr, val)
                t.provenance[attr] = src
                updated.append(attr)

        dz = deezer_track(t.features.get("isrc"), t.artist, t.title)
        if dz.get("bpm"):
            put("bpm", float(dz["bpm"]), "deezer")
        if dz.get("gain") is not None:
            t.features["gain_db"] = float(dz["gain"])

        if api_key and not is_alt_version(t.title):
            g = getsongbpm(t.artist, t.title, api_key)
            put("bpm", g.get("bpm"), "getsongbpm")
            put("key", g.get("key"), "getsongbpm")
            if g.get("danceability") is not None:
                t.features["danceability"] = g["danceability"]

        preview = dz.get("preview") if previews else None
        a = analyse_preview(preview) if preview else None
        if a:
            t.features.update({f"preview_{k}": v for k, v in a["features"].items()})
            put("bpm", a["bpm"], "preview")
            put("key", a["key"], "preview")
            raw = raw_energy(a["features"], t.bpm)
            t.features["raw_energy"] = round(raw, 4)
            # "analysis" so library-wide energy normalisation includes it.
            put("energy", energy_from_raw(raw), "analysis", overwrite=True)
            t.features["energy_source"] = "deezer preview"
        elif t.energy is None:
            put("energy", approx_energy(t.bpm, t.features.get("danceability"), t.features.get("gain_db")), "lookup")

        if updated:
            changed += 1
        print(f"[{i}/{len(todo)}] {t.label}: {', '.join(dict.fromkeys(updated)) or 'nothing found'}", file=log)
        time.sleep(delay)
    library.normalise_energy()
    return changed
