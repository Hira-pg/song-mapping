"""Import a folder (or list) of local audio files."""
from __future__ import annotations

import os
import re
import sys
from typing import Iterable, List

from ..analysis import AUDIO_EXTS, analyse_file
from ..library import Library


def iter_audio(paths: Iterable[str]) -> List[str]:
    out = []
    for p in paths:
        if os.path.isdir(p):
            for root, _, files in os.walk(p):
                out += [os.path.join(root, f) for f in sorted(files)
                        if os.path.splitext(f)[1].lower() in AUDIO_EXTS]
        elif os.path.splitext(p)[1].lower() in AUDIO_EXTS:
            out.append(p)
    return out


def _norm(s: str) -> str:
    s = re.sub(r"\(.*?\)|\[.*?\]", "", (s or "").lower())
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _matching_stream_track(library: Library, t):
    title = _norm(t.title)
    artist = _norm(t.artist)
    for s in library:
        if s.source == "local" or _norm(s.title) != title:
            continue
        names = [_norm(a) for a in s.artist.split(",")]
        if artist in names or artist == _norm(s.artist):
            return s
    return None


def import_local(library: Library, paths: Iterable[str], prefer_tags: bool = True,
                 force: bool = False, log=sys.stderr) -> int:
    files = iter_audio(paths)
    added = 0
    for i, f in enumerate(files, 1):
        if not force and library.has_path(f):
            continue
        try:
            t = analyse_file(f, prefer_tags=prefer_tags)
        except Exception as e:  # keep going on a bad file
            print(f"[{i}/{len(files)}] skipped {f}: {e}", file=log)
            continue
        stream = _matching_stream_track(library, t)
        if stream:
            # Audio analysis beats online lookups; manual edits still win.
            for attr in ("bpm", "key", "energy", "genre", "duration"):
                val = getattr(t, attr)
                if val is not None and stream.provenance.get(attr) != "manual":
                    setattr(stream, attr, val)
                    if attr in t.provenance:
                        stream.provenance[attr] = t.provenance[attr]
            stream.path = t.path
            stream.features.update(t.features)
            t = stream
        else:
            library.add(t)
        added += 1
        print(f"[{i}/{len(files)}] {t.label}: {t.bpm} BPM, {t.key}, energy {t.energy}", file=log)
    library.normalise_energy()
    return added
