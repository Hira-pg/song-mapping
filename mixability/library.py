"""A JSON-backed track library."""
from __future__ import annotations

import json
import os
from typing import Iterable, List, Optional

import numpy as np

from .models import Track


class Library:
    def __init__(self, path: str):
        self.path = path
        self.tracks: dict[str, Track] = {}
        if os.path.exists(path):
            with open(path) as f:
                for d in json.load(f).get("tracks", []):
                    t = Track.from_dict(d)
                    self.tracks[t.id] = t

    def save(self) -> None:
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"version": 1, "tracks": [t.to_dict() for t in self.tracks.values()]}, f, indent=1)
        os.replace(tmp, self.path)

    def add(self, track: Track) -> None:
        self.tracks[track.id] = track

    def __iter__(self):
        return iter(self.tracks.values())

    def __len__(self):
        return len(self.tracks)

    def has_path(self, path: str) -> bool:
        p = os.path.abspath(path)
        return any(t.path == p for t in self)

    def find(self, query: str) -> List[Track]:
        """Look a track up by id, exact label, or case-insensitive substring."""
        if query in self.tracks:
            return [self.tracks[query]]
        q = query.lower()
        exact = [t for t in self if t.label.lower() == q or t.title.lower() == q]
        if exact:
            return exact
        return [t for t in self if q in t.label.lower() or (t.path and q in os.path.basename(t.path).lower())]

    def get(self, query: str) -> Track:
        hits = self.find(query)
        if not hits:
            raise KeyError(f"no track matches {query!r}")
        if len(hits) > 1:
            names = "\n  ".join(t.label for t in hits[:10])
            raise KeyError(f"{query!r} matches {len(hits)} tracks, be more specific:\n  {names}")
        return hits[0]

    def normalise_energy(self, min_tracks: int = 8) -> None:
        """Rescale analysed energy across the library to use the full 1-10 range.

        A fixed formula can't know that your whole library is peak-time techno,
        so once there are enough analysed tracks, energy becomes relative to
        the library (5th percentile -> 1, 95th -> 10). Tag energy (e.g. from
        Mixed In Key) is left untouched.
        """
        analysed = [t for t in self if t.provenance.get("energy") == "analysis"
                    and t.features.get("raw_energy") is not None]
        if len(analysed) < min_tracks:
            return
        raws = np.array([t.features["raw_energy"] for t in analysed])
        lo, hi = np.percentile(raws, 5), np.percentile(raws, 95)
        if hi - lo < 1e-6:
            return
        for t in analysed:
            t.energy = round(float(np.clip(1 + 9 * (t.features["raw_energy"] - lo) / (hi - lo), 1, 10)), 1)
