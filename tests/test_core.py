"""Fast checks that need no audio. Run: python3 -m pytest tests  (or python3 tests/test_core.py)"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mixability import keys
from mixability.genres import similarity
from mixability.library import Library
from mixability.models import Track
from mixability.recommend import recommend_next
from mixability.scoring import score_transition, tempo_match


def test_key_names():
    assert keys.normalize_key("Am") == "8A"
    assert keys.normalize_key("A minor") == "8A"
    assert keys.normalize_key("C") == "8B"
    assert keys.normalize_key("F#m") == "11A"
    assert keys.normalize_key("Gbm") == "11A"
    assert keys.normalize_key("Bbmaj") == "6B"
    assert keys.normalize_key("1m") == "8A"    # Open Key
    assert keys.normalize_key("8a") == "8A"
    assert keys.camelot_to_name("4A") == "F minor"


def test_key_relations():
    assert keys.relation("8A", "8A")[1] == 1.0
    assert keys.relation("8A", "9A")[2] == 1
    assert keys.relation("8A", "7A")[2] == -1
    assert keys.relation("8A", "8B")[0] == "relative major"
    assert "energy boost" in keys.relation("8A", "10A")[0]
    assert "energy boost" in keys.relation("9A", "4A")[0]
    assert keys.relation("8A", "2A")[0] == "key clash"


def test_tempo():
    assert tempo_match(128, 128).score == 1.0
    assert tempo_match(128, 126).score == 1.0
    assert tempo_match(87, 174).ratio == 0.5   # incoming is double-time
    assert tempo_match(128, 140).score < 0.5


def test_genre():
    assert similarity("Tech House", "Deep House")[0] > similarity("Tech House", "Techno")[0]
    assert similarity("Techno", "Drum & Bass")[0] < 0.5


def _lib():
    lib = Library("/nonexistent/lib.json")
    for i, (bpm, key, e, g) in enumerate([(124, "8A", 5, "Tech House"), (125, "9A", 7, "Tech House"),
                                           (124, "8A", 5.2, "Tech House"), (122, "7A", 3, "Deep House"),
                                           (140, "2B", 9, "Dubstep")]):
        lib.add(Track(id=str(i), title=f"T{i}", bpm=bpm, key=key, energy=e, genre=g))
    return lib


def test_recommend_directions():
    lib = _lib()
    cur = lib.tracks["0"]
    assert recommend_next(cur, lib, "boost")[0].track.id == "1"
    assert recommend_next(cur, lib, "maintain")[0].track.id == "2"
    assert recommend_next(cur, lib, "lower")[0].track.id == "3"


def test_clash_is_penalised():
    lib = _lib()
    good = score_transition(lib.tracks["0"], lib.tracks["1"], "boost").total
    bad = score_transition(lib.tracks["0"], lib.tracks["4"], "boost").total
    assert good > 75 and bad < 45


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
