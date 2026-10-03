"""Spotify playlist import (needs credentials; not yet tested against the live API).

What Spotify gives us: track titles, artists, durations and artist genres.
What it no longer gives new apps: BPM, key and energy. The audio-features
endpoint was restricted for newly created apps in November 2024, so tempo and
key have to come from a matching local file (or another analysis service).

Setup: create an app at https://developer.spotify.com/dashboard and export
SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET. Client-credentials auth reads
public playlists; private playlists need a user OAuth token (pass it as
SPOTIFY_ACCESS_TOKEN).
"""
from __future__ import annotations

import base64
import json
import os
import re
import urllib.parse
import urllib.request
from typing import List

from ..library import Library

try:  # python.org builds on macOS ship without root certificates
    import certifi, ssl
    urllib.request.install_opener(urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=certifi.where()))))
except ImportError:
    pass
from ..models import Track

API = "https://api.spotify.com/v1"


def _token() -> str:
    if os.environ.get("SPOTIFY_ACCESS_TOKEN"):
        return os.environ["SPOTIFY_ACCESS_TOKEN"]
    cid, secret = os.environ.get("SPOTIFY_CLIENT_ID"), os.environ.get("SPOTIFY_CLIENT_SECRET")
    if not cid or not secret:
        raise RuntimeError("set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET (or SPOTIFY_ACCESS_TOKEN)")
    req = urllib.request.Request(
        "https://accounts.spotify.com/api/token",
        data=b"grant_type=client_credentials",
        headers={"Authorization": "Basic " + base64.b64encode(f"{cid}:{secret}".encode()).decode(),
                 "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req) as r:
        return json.load(r)["access_token"]


def _get(url: str, token: str) -> dict:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req) as r:
        return json.load(r)


def playlist_id(url_or_id: str) -> str:
    m = re.search(r"playlist[/:]([A-Za-z0-9]+)", url_or_id)
    return m.group(1) if m else url_or_id


def _norm(s: str) -> str:
    s = re.sub(r"\(.*?\)|\[.*?\]| - .*remaster.*", "", s.lower())
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def import_playlist(library: Library, playlist: str) -> List[Track]:
    token = _token()
    url = f"{API}/playlists/{playlist_id(playlist)}/tracks?limit=100"
    items = []
    while url:
        page = _get(url, token)
        items += [i["track"] for i in page["items"] if i.get("track") and i["track"].get("id")]
        url = page.get("next")

    # Artist genres, 50 artists per request.
    artist_ids = sorted({a["id"] for t in items for a in t["artists"] if a.get("id")})
    genres = {}
    for i in range(0, len(artist_ids), 50):
        q = urllib.parse.urlencode({"ids": ",".join(artist_ids[i:i + 50])})
        for a in _get(f"{API}/artists?{q}", token).get("artists", []):
            if a:
                genres[a["id"]] = a.get("genres", [])

    local = {(_norm(t.artist), _norm(t.title)): t for t in library if t.source == "local"}
    out = []
    for it in items:
        artist = ", ".join(a["name"] for a in it["artists"])
        g = next((gs[0] for a in it["artists"] for gs in [genres.get(a["id"], [])] if gs), None)
        match = local.get((_norm(it["artists"][0]["name"]), _norm(it["name"]))) or \
            local.get((_norm(artist), _norm(it["name"])))
        if match:
            # Enrich the analysed local file rather than duplicating it.
            if not match.genre and g:
                match.genre, match.provenance["genre"] = g, "spotify"
            out.append(match)
            continue
        t = Track(id=f"spotify:{it['id']}", title=it["name"], artist=artist, source="spotify",
                  genre=g, duration=it["duration_ms"] / 1000,
                  provenance={"genre": "spotify"} if g else {})
        library.add(t)
        out.append(t)
    return out
