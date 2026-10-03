"""Core data model for a track in the library."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional


@dataclass
class Track:
    id: str                       # stable id (path hash, Spotify id, TIDAL id...)
    title: str
    artist: str = ""
    source: str = "local"         # local | spotify | tidal
    path: Optional[str] = None    # local audio file, if any

    bpm: Optional[float] = None
    key: Optional[str] = None     # Camelot notation, e.g. "8A"
    energy: Optional[float] = None  # 1-10 scale
    genre: Optional[str] = None
    duration: Optional[float] = None  # seconds

    # Raw analysis features, kept so energy can be re-normalised per library.
    features: dict = field(default_factory=dict)
    # Where each attribute came from ("tag", "analysis", "spotify", "manual").
    provenance: dict = field(default_factory=dict)

    @property
    def label(self) -> str:
        return f"{self.artist} - {self.title}" if self.artist else self.title

    @property
    def is_scorable(self) -> bool:
        return self.bpm is not None and self.key is not None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Track":
        return cls(**d)
