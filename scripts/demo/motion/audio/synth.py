"""Trilha e efeitos sonoros sintetizados em código, na mesma grade do vídeo (120 BPM). Sem samples e sem licença.

Uso: python synth.py test   -> public/audio/test.wav
Cada composição tem uma lista de deixas (CUES) em compassos/batidas, como STATES.md."""
import math
import random
import struct
import sys
import wave
from pathlib import Path

SR = 44100
BPM = 120
BEAT = 60 / BPM
BAR = BEAT * 4
random.seed(7)


def t_at(bar: float, beat: float = 1) -> float:
    return (bar - 1) * BAR + (beat - 1) * BEAT


class Mix:
    def __init__(self, seconds: float):
        self.buf = [0.0] * int(seconds * SR)

    def add(self, start: float, samples, gain: float = 1.0):
        i0 = int(start * SR)
        for i, v in enumerate(samples):
            j = i0 + i
            if 0 <= j < len(self.buf):
                self.buf[j] += v * gain

    def save(self, path: Path, fade_out: float = 0.6):
        peak = max(1e-9, max(abs(v) for v in self.buf))
        g = 0.89 / peak  # -1 dBFS
        n = len(self.buf)
        fo = int(fade_out * SR)
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            frames = bytearray()
            for i, v in enumerate(self.buf):
                if i > n - fo:
                    v *= (n - i) / fo
                frames += struct.pack("<h", int(max(-1, min(1, math.tanh(v * g))) * 32767))
            w.writeframes(bytes(frames))


def kick(dur=0.32):
    out, ph = [], 0.0
    for i in range(int(dur * SR)):
        t = i / SR
        f = 45 + 110 * math.exp(-t * 28)
        ph += 2 * math.pi * f / SR
        out.append(math.sin(ph) * math.exp(-t * 9))
    return out


def hat(dur=0.05):
    out, prev = [], 0.0
    for i in range(int(dur * SR)):
        n = random.uniform(-1, 1)
        out.append((n - prev) * math.exp(-i / SR * 70) * 0.5)  # diferença = passa-alta simples
        prev = n
    return out


def bass(freq, dur):
    out, ph, lp = [], 0.0, 0.0
    for i in range(int(dur * SR)):
        t = i / SR
        ph = (ph + freq / SR) % 1.0
        saw = 2 * ph - 1
        lp += (saw - lp) * 0.06  # passa-baixa de um polo: grave e redondo
        env = min(1, t * 200) * math.exp(-t * 3.2)
        out.append(lp * env)
    return out


def pad(freqs, dur, attack=0.05, release=2.5):
    out = []
    for i in range(int(dur * SR)):
        t = i / SR
        env = min(1, t / attack) * math.exp(-t / release)
        out.append(sum(math.sin(2 * math.pi * f * t) * (0.6 if k else 1) for k, f in enumerate(freqs)) / len(freqs) * env)
    return out


def whoosh(dur=0.45):
    out, lp = [], 0.0
    n = int(dur * SR)
    for i in range(n):
        x = i / n
        lp += (random.uniform(-1, 1) - lp) * (0.02 + 0.5 * x * x)  # o filtro abre: o ar sobe até o corte
        out.append(lp * math.sin(math.pi * x) ** 2)
    return out


def tick(freq=2100, dur=0.035):
    return [math.sin(2 * math.pi * freq * i / SR) * math.exp(-i / SR * 120) for i in range(int(dur * SR))]


A1, C2, D2, E2, G1 = 55.0, 65.41, 73.42, 82.41, 49.0
MOTIF = [A1, A1, C2, A1, D2, C2, E2, G1]  # oito colcheias por compasso
AMIN = [220.0, 261.63, 329.63]

CUES = {
    "test": {"bars": 7, "kick": [(1, 7)], "hats": [(2, 7)], "bass": [(3, 7)], "whoosh": [3, 5, 7], "hit": [3],
             "ticks": [(6, 1)], "resolve": 7},
    # 60 s: respira no compasso 16 ("What if an agent had a job?"), cresce e volta com mais energia
    "launch": {"bars": 30, "kick": [(1, 15), (17, 27)], "hats": [(2, 15), (17, 27)], "hats16": [(17, 27)],
               "bass": [(4, 15), (17, 27)], "whoosh": [2, 3, 4, 6, 9, 11, 13, 14, 16, 17, 19, 22, 24, 26, 28],
               "hit": [4, 28], "ticks": [(10, 1), (12, 1), (13, 2), (18, 1), (20, 1), (21, 1), (22, 3), (23, 1), (25, 1)],
               "swell": [16], "resolve": 28},
    "vertical": {"bars": 15, "kick": [(1, 4), (6, 12)], "hats": [(2, 4), (6, 12)], "hats16": [(6, 12)],
                 "bass": [(3, 4), (6, 12)], "whoosh": [2, 3, 5, 6, 9, 11, 13], "hit": [3, 13],
                 "ticks": [(7, 1), (8, 1), (9, 3), (10, 1), (12, 1)], "swell": [5], "resolve": 13},
}


def build(name: str) -> Path:
    c = CUES[name]
    mix = Mix(c["bars"] * BAR + 1.5)
    for a, b in c["kick"]:
        for bar in range(a, b + 1):
            for beat in range(1, 5):
                mix.add(t_at(bar, beat), kick(), 0.9)
    for a, b in c["hats"]:
        for bar in range(a, b + 1):
            for beat in range(1, 5):
                mix.add(t_at(bar, beat + 0.5), hat(), 0.35)
    for a, b in c.get("hats16", []):  # semicolcheias: mais energia depois da virada
        for bar in range(a, b + 1):
            for k in range(16):
                if k % 2:
                    mix.add(t_at(bar) + k * BEAT / 4, hat(0.03), 0.16)
    for a, b in c["bass"]:
        for bar in range(a, b + 1):
            for k, f in enumerate(MOTIF):
                mix.add(t_at(bar) + k * BEAT / 2, bass(f, BEAT / 2 * 0.95), 0.55)
    for bar in c["whoosh"]:
        mix.add(t_at(bar) - 0.45, whoosh(), 0.35)
    for bar in c["hit"]:
        mix.add(t_at(bar), kick(0.6), 1.0)
        mix.add(t_at(bar), pad([f * 2 for f in AMIN], 1.6, 0.005, 0.5), 0.45)
    for bar, beat in c["ticks"]:
        mix.add(t_at(bar, beat), tick(), 0.6)
    for bar in c.get("swell", []):  # um compasso que sobe até a volta da batida
        mix.add(t_at(bar), pad([110.0, 164.81, 220.0, 261.63], BAR, BAR * 0.95, 9), 0.55)
    mix.add(t_at(c["resolve"]), pad(AMIN, BAR * (c["bars"] - c["resolve"] + 1), 0.08, 2.4), 0.5)
    out = Path(__file__).resolve().parent.parent / "public" / "audio" / f"{name}.wav"
    mix.save(out)
    return out


if __name__ == "__main__":
    for n in (sys.argv[1:] or ["test", "launch", "vertical"]):
        print(build(n))
