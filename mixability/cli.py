"""Command line: python -m mixability <command> ..."""
from __future__ import annotations

import argparse
import json
import os
import sys

from .keys import normalize_key
from .library import Library
from .recommend import Recommendation, evaluate_set, recommend_all, recommend_next
from .scoring import score_transition
from .transitions import recommend_technique

DEFAULT_LIB = os.environ.get("MIXABILITY_LIBRARY", "library.json")


def _fmt_track(t) -> str:
    bits = [f"{t.bpm:.1f} BPM" if t.bpm else "? BPM", t.key or "?",
            f"E{t.energy:g}" if t.energy is not None else "E?", t.genre or "-"]
    return f"{t.label}  [{', '.join(bits)}]"


def _print_rec(i: int, r: Recommendation) -> None:
    s = r.score
    print(f"  {i}. {_fmt_track(r.track)}  score {s.total:.0f}")
    for k in ("key", "tempo", "energy", "genre"):
        if k in s.reasons:
            print(f"       {k:<7}{s.parts[k]:.2f}  {s.reasons[k]}")
    print(f"       mix: {r.technique.describe()}")


def _rec_json(r: Recommendation) -> dict:
    s = r.score
    return {"track": r.track.to_dict(), "score": s.total, "parts": s.parts, "reasons": s.reasons,
            "technique": {"name": r.technique.name, "length": r.technique.length, "steps": r.technique.steps}}


def cmd_analyze(lib: Library, a) -> None:
    from .sources.local import import_local
    n = import_local(lib, a.paths, prefer_tags=not a.ignore_tags, force=a.force)
    lib.save()
    print(f"added {n} tracks; library has {len(lib)}")


def cmd_playlist(lib: Library, a) -> None:
    if a.cmd == "tidal":
        from .sources.tidal import import_playlist
    else:
        from .sources.spotify import import_playlist
    tracks = import_playlist(lib, a.playlist)
    lib.save()
    missing = [t for t in tracks if not t.is_scorable]
    no_energy = [t for t in tracks if t.is_scorable and t.energy is None]
    print(f"imported {len(tracks)} tracks into {lib.path}")
    if no_energy:
        print(f"{len(no_energy)} have BPM/key but no energy (analyse their audio or use `edit --energy`)")
    for t in missing:
        print("  missing BPM/key:", t.label)


def cmd_lookup(lib: Library, a) -> None:
    from .sources.lookup import fill_missing
    n = fill_missing(lib)
    lib.save()
    still = [t for t in lib if not t.is_scorable]
    print(f"filled data for {n} tracks; {len(still)} still missing BPM or key")


def cmd_list(lib: Library, a) -> None:
    for t in sorted(lib, key=lambda t: (t.bpm or 0, t.key or "")):
        print(_fmt_track(t))


def cmd_recommend(lib: Library, a) -> None:
    cur = lib.get(a.track)
    if a.intent == "all":
        res = recommend_all(cur, lib, n=a.n)
    else:
        res = {a.intent: recommend_next(cur, lib, a.intent, n=a.n)}
    if a.json:
        print(json.dumps({"current": cur.to_dict(), **{k: [_rec_json(r) for r in v] for k, v in res.items()}}, indent=1))
        return
    print("Now playing:", _fmt_track(cur))
    for intent, recs in res.items():
        print(f"\n{intent.upper()}")
        if not recs:
            print("  (no suitable tracks in the library)")
        for i, r in enumerate(recs, 1):
            _print_rec(i, r)


def cmd_score(lib: Library, a) -> None:
    x, y = lib.get(a.a), lib.get(a.b)
    ts = score_transition(x, y, a.intent)
    print(f"{_fmt_track(x)}\n  -> {_fmt_track(y)}")
    _print_rec(1, Recommendation(ts, recommend_technique(ts)))


def cmd_set(lib: Library, a) -> None:
    with open(a.file) as f:
        lines = [l.strip() for l in f if l.strip() and not l.startswith("#")]
    tracks = []
    for l in lines:
        # m3u entries are paths; otherwise treat the line as a search query.
        hits = [t for t in lib if t.path and os.path.abspath(l) == t.path] or lib.find(l)
        if len(hits) != 1:
            sys.exit(f"set line {l!r} matched {len(hits)} tracks")
        tracks.append(hits[0])
    res = evaluate_set(tracks)
    for i, r in enumerate(res["transitions"], 1):
        s = r.score
        print(f"{i:>2}. {s.total:5.1f}  {s.a.label}  ->  {s.b.label}")
        print(f"        {' | '.join(s.reasons[k] for k in ('key', 'tempo', 'energy') if k in s.reasons)}")
        print(f"        mix: {r.technique.describe()}")
    print(f"\nset average {res['mean']}; weakest: {res['weakest'].score.a.label} -> {res['weakest'].score.b.label}"
          if res["weakest"] else "need at least two tracks")
    print("energy curve:", " ".join(f"{e:g}" for e in res["energy_curve"]))


def cmd_edit(lib: Library, a) -> None:
    t = lib.get(a.track)
    if a.bpm is not None:
        t.bpm, t.provenance["bpm"] = a.bpm, "manual"
    if a.key:
        k = normalize_key(a.key)
        if not k:
            sys.exit(f"can't parse key {a.key!r}")
        t.key, t.provenance["key"] = k, "manual"
    if a.energy is not None:
        t.energy, t.provenance["energy"] = a.energy, "manual"
    if a.genre:
        t.genre, t.provenance["genre"] = a.genre, "manual"
    lib.save()
    print(_fmt_track(t))


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="mixability", description=__doc__)
    p.add_argument("--library", default=DEFAULT_LIB, help="library JSON file (default %(default)s)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("analyze", help="analyse audio files or folders into the library")
    s.add_argument("paths", nargs="+")
    s.add_argument("--ignore-tags", action="store_true", help="analyse audio even if BPM/key tags exist")
    s.add_argument("--force", action="store_true", help="re-analyse files already in the library")
    s.set_defaults(fn=cmd_analyze)

    s = sub.add_parser("spotify", help="import a Spotify playlist (needs credentials)")
    s.add_argument("playlist", help="playlist URL or id")
    s.set_defaults(fn=cmd_playlist)

    s = sub.add_parser("tidal", help="import a TIDAL playlist (needs TIDAL_CLIENT_ID / TIDAL_CLIENT_SECRET)")
    s.add_argument("playlist", help="playlist URL or id")
    s.set_defaults(fn=cmd_playlist)

    s = sub.add_parser("tidal-login", help="sign in to TIDAL so private playlists can be imported")
    s.add_argument("--no-browser", action="store_true", help="print the sign-in URL instead of opening it")
    s.set_defaults(fn=lambda lib, a: __import__("mixability.sources.tidal", fromlist=["login"]).login(not a.no_browser))

    s = sub.add_parser("lookup", help="fill missing BPM/key/energy from Deezer and GetSongBPM")
    s.set_defaults(fn=cmd_lookup)

    s = sub.add_parser("list", help="list library tracks")
    s.set_defaults(fn=cmd_list)

    s = sub.add_parser("recommend", help="what to play next to boost, maintain or lower energy")
    s.add_argument("track", help="track id, 'Artist - Title', or part of it")
    s.add_argument("--intent", choices=["boost", "maintain", "lower", "all"], default="all")
    s.add_argument("-n", type=int, default=3)
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_recommend)

    s = sub.add_parser("score", help="score a single transition A -> B")
    s.add_argument("a")
    s.add_argument("b")
    s.add_argument("--intent", choices=["boost", "maintain", "lower"])
    s.set_defaults(fn=cmd_score)

    s = sub.add_parser("set", help="score every transition in a set (m3u or one track per line)")
    s.add_argument("file")
    s.set_defaults(fn=cmd_set)

    s = sub.add_parser("edit", help="correct a track's BPM, key, energy or genre")
    s.add_argument("track")
    s.add_argument("--bpm", type=float)
    s.add_argument("--key")
    s.add_argument("--energy", type=float)
    s.add_argument("--genre")
    s.set_defaults(fn=cmd_edit)

    a = p.parse_args(argv)
    lib = Library(a.library)
    try:
        a.fn(lib, a)
    except KeyError as e:
        sys.exit(str(e).strip("'\""))
    except RuntimeError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
