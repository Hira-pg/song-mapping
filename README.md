# Mixability

Scores how well two tracks mix, recommends what to play next to **boost**,
**maintain** or **lower** the energy of a set, and says how to do the transition.

## Quick start

```bash
pip install -r requirements.txt          # also needs ffmpeg for MP3 decoding
python3 -m mixability analyze ~/Music/DJ          # builds library.json
python3 -m mixability recommend "Artist - Title"  # boost / maintain / lower picks
python3 -m mixability recommend "Title" --intent boost -n 5 --json
python3 -m mixability score "Track A" "Track B"
python3 -m mixability set my_set.txt     # m3u, or one track name per line
python3 -m mixability edit "Title" --key 8A --energy 7 --genre "Tech House"
```

Try it without audio: `python3 -m mixability --library examples/synthetic_library.json recommend Charlie`.

## How a transition is scored (0-100)

| Signal | Weight | What it measures |
|---|---|---|
| Key | 30% | Camelot wheel relation: same key 1.0; ±1 or relative major/minor 0.9; diagonal 0.7; +2 / +7 "energy boost" 0.55-0.65; anything else is a clash |
| Tempo | 30% | Pitch change needed on the incoming track, trying straight, half- and double-time. ≤2% is free, 6% is the comfortable limit, >10% can't be blended |
| Energy | 25% | Energy change (1-10 scale) against the intent: boost aims for +1.5, maintain for 0, lower for -1.5. Key moves that lift or drop in the right direction add a little |
| Genre |15% | Same genre 1.0, same family 0.85, neighbouring families 0.55, distant 0.2, unknown 0.6 |

A hard key or tempo clash caps the total so good genre/energy can't hide it.
Weights are `DEFAULT_WEIGHTS` in `mixability/scoring.py`; genre families are in
`mixability/genres.py`.

Each recommendation also gets a technique: long blend, bass-swap lift, filter
fade, short percussive blend, drop swap, half/double-time switch, or echo out,
with the BPM to set the incoming deck to.

## Where the numbers come from

- **Tags first**: BPM, key (`initialkey`, Camelot/Open Key/names) and Mixed In
  Key's "Energy N" comment are used when present. `--ignore-tags` forces analysis.
- **Audio analysis** (librosa): beat tracking with a line-fit refinement for
  BPM, Krumhansl key profiles on harmonic chroma for key, and loudness, onset
  density, brightness, compression and tempo for energy.
- **Energy is library-relative**: once 8+ tracks are analysed, analysed energy
  is rescaled so your quietest tracks sit near 1 and your hardest near 10.
- Genre comes from the file's genre tag (or Spotify artist genres).

## Streaming sources

- **Spotify** (`python3 -m mixability spotify <playlist-url>`): needs
  `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET` from a Spotify developer app.
  Spotify no longer gives new apps BPM/key/energy (audio-features was restricted
  in Nov 2024), so playlist tracks are matched by artist and title to your
  analysed local files; unmatched tracks are listed as needing audio. Not yet
  tested against the live API.
- **TIDAL** (`python3 -m mixability tidal <playlist-url>`): needs
  `TIDAL_CLIENT_ID` / `TIDAL_CLIENT_SECRET` (optional `TIDAL_COUNTRY`, default US).
  TIDAL returns BPM and key per track, so playlist tracks can be scored on key
  and tempo with no audio file; energy still comes from matching local files
  (or `edit --energy`). Public playlists work with client credentials. For your
  own private playlists run `python3 -m mixability tidal-login` once: it opens
  TIDAL's sign-in in your browser and saves a token to
  `~/.mixability/tidal_token.json` (auto-refreshed). Your TIDAL app must list
  `http://localhost:8765/callback` as a redirect URI. Tested against a mocked API
  only so far.

## Filling BPM / key / energy for streaming tracks

TIDAL's public API does not return BPM or key, so after a `tidal` import run:

```bash
python3 -m mixability lookup
```

For each track it:
1. finds the track on Deezer (by ISRC, else artist + title) for BPM and a
   30-second preview, and runs the normal audio analysis on that preview to
   get key and energy (works for remixes and underground tracks too; no
   ffmpeg needed);
2. if `GETSONGBPM_API_KEY` is set, asks GetSongBPM for the original version's
   BPM and key, which is preferred over the preview for non-remix tracks.

Energy for all lookup tracks comes from the preview analysis, so it is on one
scale. Running `analyze` on your own files replaces lookup values for every
song it can match by artist and title. `--no-previews` skips the downloads.

## Tests

`python3 tests/test_core.py` (no audio needed). `tests/make_synthetic.py <dir>`
generates 8 MP3s with known BPM/key/energy/genre; analysis recovers every BPM
and key exactly.

## Credits

Song data from [GetSongBPM](https://getsongbpm.com) and [Deezer](https://www.deezer.com).
