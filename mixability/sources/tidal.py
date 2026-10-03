"""TIDAL playlist import via the TIDAL developer API (openapi.tidal.com/v2).

Setup: export TIDAL_CLIENT_ID and TIDAL_CLIENT_SECRET from your app at
https://developer.tidal.com. Client-credentials auth reads public playlists.
For your own private playlists, run `python3 -m mixability tidal-login` once
(signs in through the browser and saves a refreshable token), or pass a
user token as TIDAL_ACCESS_TOKEN.
TIDAL_COUNTRY (default US) sets the catalogue region.

Unlike Spotify, TIDAL's track resource carries `bpm`, `key` and `keyScale`, so
playlist tracks can be scored on key and tempo without local audio. Energy
still needs audio, so tracks are matched to analysed local files by artist
and title when possible; otherwise energy stays unknown and drops out of the
score. Field names follow TIDAL's published API reference; this has not yet
been run against the live API.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import List, Optional

from ..keys import normalize_key
from ..library import Library

try:  # python.org builds on macOS ship without root certificates
    import certifi, ssl
    urllib.request.install_opener(urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=certifi.where()))))
except ImportError:
    pass
from ..models import Track

API = "https://openapi.tidal.com/v2"
TOKEN_URL = "https://auth.tidal.com/v1/oauth2/token"


def _env(*names: str) -> Optional[str]:
    return next((os.environ[n] for n in names if os.environ.get(n)), None)


TOKEN_FILE = os.path.expanduser(os.environ.get("TIDAL_TOKEN_FILE", "~/.mixability/tidal_token.json"))
AUTHORIZE_URL = "https://login.tidal.com/authorize"
REDIRECT_URI = os.environ.get("TIDAL_REDIRECT_URI", "http://localhost:8765/callback")
SCOPES = os.environ.get("TIDAL_SCOPES", "playlists.read")


def _post_token(data: dict) -> dict:
    req = urllib.request.Request(TOKEN_URL, data=urllib.parse.urlencode(data).encode(),
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req) as r:
        tok = json.load(r)
    tok["expires_at"] = time.time() + tok.get("expires_in", 3600) - 60
    return tok


def _save_user_token(tok: dict) -> None:
    os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
    with open(TOKEN_FILE, "w") as f:
        json.dump(tok, f)
    os.chmod(TOKEN_FILE, 0o600)


def _user_token() -> Optional[str]:
    """Saved sign-in from `mixability tidal-login`, refreshed when expired."""
    if not os.path.exists(TOKEN_FILE):
        return None
    with open(TOKEN_FILE) as f:
        tok = json.load(f)
    if tok.get("expires_at", 0) > time.time():
        return tok["access_token"]
    if not tok.get("refresh_token"):
        return None
    new = _post_token({"grant_type": "refresh_token", "refresh_token": tok["refresh_token"],
                       "client_id": _env("TIDAL_CLIENT_ID") or tok.get("client_id", "")})
    new.setdefault("refresh_token", tok["refresh_token"])
    new["client_id"] = tok.get("client_id")
    _save_user_token(new)
    return new["access_token"]


def login(open_browser: bool = True, timeout: float = 300) -> None:
    """Sign in to TIDAL (authorization code + PKCE) so private playlists can be read.

    Your app at developer.tidal.com must list REDIRECT_URI as a redirect URI.
    """
    from http.server import BaseHTTPRequestHandler, HTTPServer

    cid = _env("TIDAL_CLIENT_ID")
    if not cid:
        raise RuntimeError("set TIDAL_CLIENT_ID first")
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    url = AUTHORIZE_URL + "?" + urllib.parse.urlencode({
        "response_type": "code", "client_id": cid, "redirect_uri": REDIRECT_URI, "scope": SCOPES,
        "code_challenge_method": "S256", "code_challenge": challenge, "state": state},
        quote_via=urllib.parse.quote)  # %20 not "+" between scopes

    result = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            result.update({k: v[0] for k, v in q.items()})
            ok = result.get("state") == state and "code" in result
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Signed in to TIDAL, you can close this tab." if ok
                             else b"TIDAL sign-in failed, check the terminal.")

        def log_message(self, *a):
            pass

    parsed = urllib.parse.urlparse(REDIRECT_URI)
    server = HTTPServer((parsed.hostname, parsed.port or 80), Handler)
    server.timeout = timeout
    print("Opening TIDAL sign-in. If no browser opens, visit:\n" + url)
    if open_browser:
        import webbrowser
        webbrowser.open(url)
    server.handle_request()
    server.server_close()
    if result.get("state") != state or "code" not in result:
        raise RuntimeError(f"sign-in did not complete: {result.get('error_description') or result.get('error') or 'no code'}")

    tok = _post_token({"grant_type": "authorization_code", "client_id": cid, "code": result["code"],
                       "redirect_uri": REDIRECT_URI, "code_verifier": verifier})
    tok["client_id"] = cid
    _save_user_token(tok)
    print(f"Signed in. Token saved to {TOKEN_FILE}")


def _token() -> str:
    tok = _env("TIDAL_ACCESS_TOKEN") or _user_token()
    if tok:
        return tok
    cid = _env("TIDAL_CLIENT_ID")
    secret = _env("TIDAL_CLIENT_SECRET")
    if not cid or not secret:
        raise RuntimeError("set TIDAL_CLIENT_ID and TIDAL_CLIENT_SECRET (or TIDAL_ACCESS_TOKEN)")
    req = urllib.request.Request(
        TOKEN_URL, data=b"grant_type=client_credentials",
        headers={"Authorization": "Basic " + base64.b64encode(f"{cid}:{secret}".encode()).decode(),
                 "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req) as r:
        return json.load(r)["access_token"]


def _get(path_or_url: str, token: str, params: Optional[dict] = None) -> dict:
    url = path_or_url if path_or_url.startswith("http") else API + path_or_url
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params, safe="[],")
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}",
                                               "Accept": "application/vnd.api+json"})
    with urllib.request.urlopen(req) as r:
        return json.load(r)


def playlist_id(url_or_id: str) -> str:
    m = re.search(r"playlist/([0-9a-fA-F-]{36})", url_or_id)
    return m.group(1) if m else url_or_id.strip()


def parse_duration(iso: Optional[str]) -> Optional[float]:
    """ISO 8601 duration like PT3M5S -> seconds."""
    m = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?", iso or "")
    if not m or not any(m.groups()):
        return None
    h, mi, s = (float(x) if x else 0.0 for x in m.groups())
    return h * 3600 + mi * 60 + s


def parse_key(key: Optional[str], scale: Optional[str]) -> Optional[str]:
    """TIDAL keys look like "FSharp" or "Ab", with scale "MINOR"/"MAJOR"."""
    if not key or key.upper() == "UNKNOWN":
        return None
    root = re.sub("sharp", "#", key, flags=re.I)
    root = re.sub("flat", "b", root, flags=re.I)
    minor = bool(scale) and "MINOR" in scale.upper()
    return normalize_key(root + ("m" if minor else ""))


def _norm(s: str) -> str:
    s = re.sub(r"\(.*?\)|\[.*?\]", "", s.lower())
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _playlist_track_ids(pid: str, token: str, country: str) -> List[str]:
    ids, url, params = [], f"/playlists/{pid}/relationships/items", {"countryCode": country}
    while url:
        page = _get(url, token, params)
        ids += [d["id"] for d in page.get("data", []) if d.get("type") == "tracks"]
        nxt = (page.get("links") or {}).get("next")
        url = None if not nxt else (nxt if nxt.startswith("http") else API + nxt)
        params = None  # the next link already carries the query
    return ids


def import_playlist(library: Library, playlist: str) -> List[Track]:
    token = _token()
    country = _env("TIDAL_COUNTRY") or "US"
    try:
        ids = _playlist_track_ids(playlist_id(playlist), token, country)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403, 404) and not (_env("TIDAL_ACCESS_TOKEN") or os.path.exists(TOKEN_FILE)):
            raise RuntimeError(f"TIDAL returned {e.code} for this playlist. If it is private, run "
                               "`python3 -m mixability tidal-login` once, then retry.") from e
        raise

    tracks, artists = {}, {}
    for i in range(0, len(ids), 20):  # the /tracks filter takes up to 20 ids
        page = _get("/tracks", token, {"countryCode": country, "filter[id]": ",".join(ids[i:i + 20]),
                                        "include": "artists"})
        for d in page.get("data", []):
            tracks[d["id"]] = d
        for inc in page.get("included", []):
            if inc.get("type") == "artists":
                artists[inc["id"]] = inc.get("attributes", {}).get("name", "")

    local = {(_norm(t.artist), _norm(t.title)): t for t in library if t.source == "local"}
    out = []
    for tid in ids:
        d = tracks.get(tid)
        if not d:
            continue
        at = d.get("attributes", {})
        title = at.get("title", "") + (f" ({at['version']})" if at.get("version") else "")
        rel = ((d.get("relationships") or {}).get("artists") or {}).get("data") or []
        names = [artists[r["id"]] for r in rel if artists.get(r["id"])]
        artist = ", ".join(names)
        bpm = float(at["bpm"]) if at.get("bpm") else None
        key = parse_key(at.get("key"), at.get("keyScale"))

        match = next((local[k] for k in ((_norm(a), _norm(at.get("title", ""))) for a in names[:1] + [artist])
                      if k in local), None)
        if match:
            # Local analysis supplies energy; fill any gaps from TIDAL.
            for attr, val in (("bpm", bpm), ("key", key)):
                if val and getattr(match, attr) is None:
                    setattr(match, attr, val)
                    match.provenance[attr] = "tidal"
            out.append(match)
            continue

        t = Track(id=f"tidal:{tid}", title=title, artist=artist, source="tidal",
                  bpm=bpm, key=key, duration=parse_duration(at.get("duration")),
                  features={"isrc": at["isrc"]} if at.get("isrc") else {})
        t.provenance = {k: "tidal" for k, v in (("bpm", bpm), ("key", key)) if v}
        library.add(t)
        out.append(t)
    return out
