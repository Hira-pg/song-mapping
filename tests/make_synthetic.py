"""Generate synthetic test tracks with known BPM, key, energy and genre tags."""
import os
import subprocess
import sys

import numpy as np
import soundfile as sf

SR = 22050
PITCHES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def tone(freq, dur, sr=SR):
    t = np.arange(int(dur * sr)) / sr
    return np.sin(2 * np.pi * freq * t) + 0.3 * np.sin(4 * np.pi * freq * t)


def make(path, bpm, root, minor, energy, seconds=40):
    n = int(seconds * SR)
    y = np.zeros(n)
    beat = 60 / bpm
    # Kick on every beat.
    kick_t = np.arange(int(0.15 * SR)) / SR
    kick = np.sin(2 * np.pi * (50 + 80 * np.exp(-kick_t * 30)) * kick_t) * np.exp(-kick_t * 20)
    hats = energy > 4
    rng = np.random.default_rng(0)
    for i in range(int(seconds / beat)):
        s = int(i * beat * SR)
        e = min(n, s + len(kick))
        y[s:e] += kick[: e - s] * 0.9
        if hats:  # off-beat hats raise onset density and brightness
            h = int((i + 0.5) * beat * SR)
            hl = min(n - h, int(0.05 * SR))
            if hl > 0:
                y[h:h + hl] += rng.normal(0, 0.15 * energy / 10, hl) * np.exp(-np.arange(hl) / 200)
            if energy > 7:
                for q in (0.25, 0.75):
                    h = int((i + q) * beat * SR)
                    hl = min(n - h, int(0.03 * SR))
                    if hl > 0:
                        y[h:h + hl] += rng.normal(0, 0.1, hl) * np.exp(-np.arange(hl) / 150)
    # Sustained triad pad (root, third, fifth) plus scale-tone arpeggio.
    rp = PITCHES.index(root)
    third = 3 if minor else 4
    base = 220 * 2 ** ((rp - 9) / 12)
    pad = sum(tone(base * 2 ** (s / 12), seconds) for s in (0, third, 7, 12))
    y += 0.12 * pad / 4
    scale = [0, 2, 3, 5, 7, 8, 10] if minor else [0, 2, 4, 5, 7, 9, 11]
    for i in range(int(seconds / beat)):
        f = base * 2 ** (scale[[0, 2, 4, 2, 0, 4, 6, 4][i % 8]] / 12) * 2
        s = int(i * beat * SR)
        seg = tone(f, beat * 0.9)[: n - s] * np.exp(-np.arange(min(int(beat * 0.9 * SR), n - s)) / (SR * 0.2))
        y[s:s + len(seg)] += 0.1 * seg
    y *= 10 ** ((energy - 10) * 1.5 / 20)  # quieter for low energy
    y /= max(1.0, np.abs(y).max())
    sf.write(path, y.astype(np.float32), SR)


TRACKS = [  # name, bpm, root, minor, energy, genre
    ("Alpha - Warmup", 120, "A", True, 3, "Deep House"),
    ("Bravo - Groove", 122, "E", True, 5, "Deep House"),
    ("Charlie - Lift", 124, "A", True, 6, "Tech House"),
    ("Delta - Peak", 126, "B", True, 8, "Tech House"),
    ("Echo - Rave", 128, "E", True, 9, "Techno"),
    ("Foxtrot - Sunset", 118, "C", False, 4, "Nu Disco"),
    ("Golf - Steppers", 140, "F", True, 7, "Dubstep"),
    ("Hotel - Roller", 174, "D", True, 8, "Drum & Bass"),
]

if __name__ == "__main__":
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    from mutagen.easyid3 import EasyID3
    for name, bpm, root, minor, energy, genre in TRACKS:
        wav = os.path.join(out, name + ".wav")
        mp3 = os.path.join(out, name + ".mp3")
        make(wav, bpm, root, minor, energy)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", wav, "-b:a", "192k", mp3], check=True)
        os.remove(wav)
        tags = EasyID3()
        artist, title = name.split(" - ")
        tags["artist"], tags["title"], tags["genre"] = artist, title, genre
        tags.save(mp3)
        print(f"{name}: {bpm} BPM, {root}{'m' if minor else ''}, energy~{energy}, {genre}")
