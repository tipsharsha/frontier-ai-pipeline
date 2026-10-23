"""Render "Make No Mistakes": vocals, instruments, mix, master and timing data.

    python build_audio.py [--fresh-vocals]

Writes build/song.wav, build/timing.json and build/features.json.
"""

import json
import os
import pickle
import sys
import time
import zlib
from pathlib import Path

import numpy as np
import pyloudnorm as pyln
import soundfile as sf

import singer
import song
import synth as sy
from singer import KokoroSpeaker, Note, PiperSpeaker, Singer, Style
from song import BAR, BEAT, S16, at
from synth import SR, mix_into

HERE = Path(__file__).resolve().parent
BUILD = Path(os.environ.get("BUILD_DIR", HERE / "build"))
VOICES_DIR = Path(os.environ.get("VOICES_DIR", HERE / "voices"))  # Piper models, if used
LENGTH = song.END_TIME + 3.0
N = int(LENGTH * SR)
FPS = 30

# "engine:voice". Kokoro-82M voices (Apache-2.0); the AI's spoken asides use the
# singer's voice, robot-processed. "piper:en_US-ljspeech-high" also works.
VOICES = {"lead": "kokoro:af_heart", "ai": "kokoro:af_heart", "user": "kokoro:am_michael"}


def make_speaker(spec):
    engine, name = spec.split(":", 1)
    if engine == "kokoro":
        return KokoroSpeaker(name, lexicon=song.PRONOUNCE)
    if engine == "piper":
        return PiperSpeaker(VOICES_DIR / f"{name}.onnx")
    raise ValueError(f"unknown TTS engine in {spec!r}")


KIND_STYLE = {
    "lead": dict(glide=0.045, vibrato=0.22, scoop=0.45, jitter=0.03),
    "double": dict(glide=0.04, vibrato=0.12, scoop=0.3, jitter=0.03),
    "harmony": dict(glide=0.05, vibrato=0.15, scoop=0.3, jitter=0.03),
    "backing": dict(glide=0.008, vibrato=0.0, scoop=0.0, jitter=0.0, formant=1.12),
    "chop": dict(),
}


def log(*a):
    print(f"[{time.strftime('%H:%M:%S')}]", *a, flush=True)


# ------------------------------------------------------------------ vocals

def _sung_text(text):
    return song.tts_text(text).replace(",", "").replace("!", "").replace(".", "")


def _sung_words(text, mel):
    out, k = [], 0
    for w in text.split():
        n = len(w.split("-"))
        notes = [note for syl in mel[k:k + n] for note in syl]
        out.append({"w": w.replace("-", ""), "t0": notes[0][0], "t1": notes[-1][0] + notes[-1][1]})
        k += n
    return out


def _spoken_words(singer, text, t0, length_scale=1.0):
    _, phones = singer.speak(song.tts_text(text), length_scale=length_scale)
    t0 -= singer.lead_silence(song.tts_text(text), length_scale)  # say() trims it
    words = text.split()
    groups, cur = [], []
    for ph, a, b in phones:
        if ph in ("^", "$"):
            continue
        if ph == " " or ph in ".,!?":
            if cur:
                groups.append((cur[0], cur[-1]))
                cur = []
            continue
        cur.append(a if not cur else b)
        if len(cur) == 1:
            cur.append(b)
    if cur:
        groups.append((cur[0], cur[-1]))
    if len(groups) == len(words):
        return [{"w": w, "t0": t0 + a, "t1": t0 + b} for w, (a, b) in zip(words, groups)]
    # espeak merged some words: spread the voiced span by character count
    a, b = groups[0][0], groups[-1][1]
    lens = np.array([len(w) for w in words], dtype=float)
    edges = a + (b - a) * np.concatenate([[0], np.cumsum(lens) / lens.sum()])
    return [{"w": w, "t0": t0 + edges[i], "t1": t0 + edges[i + 1]} for i, w in enumerate(words)]


def _part_key(p):
    """Everything that changes how a part sounds (not where it sits in the mix)."""
    return repr((p.kind, p.voice, round(p.bar, 4), p.text, p.melody, p.transpose, sorted(p.style.items()),
                 song.KEY, VOICES[p.voice], sorted(song.PRONOUNCE.items()), sorted(KIND_STYLE.get(p.kind, {}).items()),
                 singer.VERSION))


def render_vocals(fresh=False):
    """Render every vocal part, reusing cached renders of unchanged parts."""
    cache_file = BUILD / "vocals.pkl"
    cache = {} if fresh or not cache_file.exists() else pickle.loads(cache_file.read_bytes())
    if not isinstance(cache, dict):
        cache = {}
    singers = {}
    clips, used = [], {}
    for i, p in enumerate(song.build_parts()):
        key = _part_key(p)
        if key not in cache:
            spec = VOICES[p.voice]
            if spec not in singers:
                singers[spec] = Singer(make_speaker(spec))
            s = singers[spec]
            rng = np.random.default_rng(zlib.crc32(key.encode()))
            if p.kind in ("spoken", "robot", "whisper"):
                st = Style(**p.style)
                t0 = p.bar * BAR
                y = s.say(song.tts_text(p.text), st)
                words = _spoken_words(s, p.text, t0, st.length_scale)
            else:
                style = Style(**{**KIND_STYLE[p.kind], **p.style})
                mel = song.parse_melody(p)
                shift, detune = 0.0, 0.0
                if p.kind in ("double", "harmony"):
                    shift = rng.uniform(-0.014, 0.014)
                    detune = rng.choice([-1, 1]) * rng.uniform(0.04, 0.09)
                notes = [[Note(t + shift, d, m + detune) for t, d, m in syl] for syl in mel]
                t0, y = s.sing(_sung_text(p.text), notes, style)
                words = _sung_words(p.text, mel)
            cache[key] = dict(t0=t0, audio=y, words=words)
            log(f"vocal {i:3d} {p.kind:8s} {t0:7.2f}s {p.text}")
        used[key] = cache[key]
        c = cache[key]
        clips.append(dict(kind=p.kind, voice=p.voice, section=p.section, text=p.text, t0=c["t0"], audio=c["audio"],
                          gain=p.gain, pan=p.pan, display=p.display, words=c["words"]))
    BUILD.mkdir(parents=True, exist_ok=True)
    cache_file.write_bytes(pickle.dumps(used))
    return clips


def vocal_buses(clips):
    buses = {k: np.zeros((N, 2)) for k in ("lead", "double", "harmony", "backing", "user", "robot", "whisper")}
    route = {"lead": "lead", "chop": "lead", "double": "double", "harmony": "harmony", "backing": "backing",
             "spoken": "user", "robot": "robot", "whisper": "whisper"}
    for c in clips:
        bus = route[c["kind"]]
        if c["kind"] == "spoken" and c["voice"] == "lead":
            bus = "whisper"  # the soft "So go on." shares the whisper's treatment
        mix_into(buses[bus], sy.pan(c["audio"], c["pan"]), c["t0"], c["gain"])
    return buses


def process_vocals(b):
    plate = sy.reverb_ir(1.7, 0.035, 0.6, seed=21)
    lead = sy.hp(b["lead"], 110)
    lead = sy.eq(lead, "peak", 320, -2.5, 1.0)
    lead = sy.eq(lead, "peak", 3200, 3.5, 0.9)
    lead = sy.eq(lead, "high", 7000, 3.0, 0.7)
    lead = sy.compressor(lead, -22, 3.5, 0.003, 0.1, makeup_db=6)
    lead = sy.saturate(lead * 1.2, 1.1)

    dbl = sy.eq(sy.hp(b["double"], 160), "peak", 3000, 2.0, 0.9)
    dbl = sy.compressor(dbl, -24, 5, 0.003, 0.08, makeup_db=7)
    harm = sy.eq(sy.hp(b["harmony"], 180), "peak", 2500, 1.5, 0.9)
    harm = sy.compressor(harm, -24, 4, 0.004, 0.1, makeup_db=6)

    bk = sy.bp(b["backing"], 350, 7500)
    bk = sy.eq(bk, "peak", 1800, 5, 1.2)
    bk = sy.compressor(bk, -24, 6, 0.002, 0.06, makeup_db=8)
    bk = bk + 0.35 * sy.echo(bk, BEAT / 2, 0.35, taps=4, tone=3500)

    user = sy.bp(b["user"], 170, 6500)
    user = sy.eq(user, "peak", 2500, 3, 1.0)
    user = sy.compressor(user, -24, 4, 0.003, 0.1, makeup_db=7)
    room = sy.reverb_ir(0.5, 0.008, 0.7, seed=22)
    user = user + 0.12 * sy.convolve(user, room)

    robot = sy.hp(b["robot"], 150)
    robot = sy.eq(robot, "peak", 2200, 4, 1.0)
    robot = sy.compressor(robot, -24, 5, 0.002, 0.08, makeup_db=8)
    robot = robot + 0.25 * sy.echo(robot, 0.11, 0.3, taps=3, tone=5000)

    wh = sy.eq(sy.hp(b["whisper"], 300), "peak", 4000, 4, 0.8)
    wh = sy.compressor(wh, -26, 4, 0.003, 0.1, makeup_db=8)

    main = lead + bk * 0.8 + user + robot + wh * 1.2
    dry = main + dbl * 0.8 + harm * 0.7
    verb_send = lead * 0.18 + dbl * 0.25 + harm * 0.35 + bk * 0.2 + wh * 0.5 + robot * 0.1
    delay_send = lead * 0.1 + bk * 0.1
    wet = sy.convolve(verb_send, plate) + sy.echo(sy.hp(delay_send, 300), 0.375, 0.3, taps=5, tone=3000)
    return dry, wet, lead, main


# ------------------------------------------------------------------ harmony helpers

def bar_chord(bar):
    sym, tr = song.chord_at(bar)
    return song.chord_notes(sym, tr)


def place(pc, lo):
    """Lowest MIDI note >= lo with pitch class pc."""
    return lo + (pc - lo) % 12


def voicing(pcs, prev, lo=55, hi=76):
    cands = []
    for base in range(lo, lo + 12):
        if base % 12 not in pcs:
            continue
        v = [base]
        while len(v) < 3:
            nxt = v[-1] + 1
            while nxt % 12 not in pcs:
                nxt += 1
            v.append(nxt)
        v.append(v[0] + 12)
        if v[-1] <= hi:
            cands.append(v)
    if prev is None:
        return cands[len(cands) // 2]
    return min(cands, key=lambda v: sum(abs(a - b) for a, b in zip(v, prev)))


# ------------------------------------------------------------------ arrangement

ARR = {
    "intro": dict(drums="intro", bass=None, pad=0.42, cut=(450, 2400), arp=0.5, bright=(0.15, 0.9)),
    "verse1": dict(drums="verse", bass="pulse", pad=0.26, cut=(1300, 1600), arp=0.3, bright=(0.45, 0.6)),
    "pre1": dict(drums="pre", bass="pulse", pad=0.4, cut=(1500, 4200), arp=0.4, bright=(0.5, 1.0)),
    "chorus1": dict(drums="chorus", bass="octave", pad=0.55, cut=(3800, 3800), arp=0.3, bright=(0.9, 0.9)),
    "post1": dict(drums="chorus", bass="octave", pad=0.45, cut=(3800, 3800), arp=0.34, bright=(1, 1), lead=True),
    "verse2": dict(drums="verse2", bass="pulse", pad=0.26, cut=(1300, 1700), arp=0.3, bright=(0.5, 0.65)),
    "pre2": dict(drums="pre", bass="pulse", pad=0.4, cut=(1500, 4200), arp=0.4, bright=(0.5, 1.0)),
    "chorus2": dict(drums="chorus", bass="octave", pad=0.55, cut=(3800, 3800), arp=0.3, bright=(0.9, 0.9)),
    "post2": dict(drums="chorus", bass="octave", pad=0.45, cut=(3800, 3800), arp=0.34, bright=(1, 1), lead=True),
    "bridge": dict(drums="bridge", bass="long", pad=0.3, cut=(900, 2600), arp=0.0, keys=0.55),
    "final": dict(drums="chorus", bass="octave", pad=0.62, cut=(4600, 4600), arp=0.34, bright=(1, 1), octave_pad=True),
    "outro": dict(drums="outro", bass="octave", pad=0.5, cut=(4200, 700), arp=0.32, bright=(1, 0.2), lead=True),
    "tag": dict(drums=None, bass=None, pad=0.3, cut=(1400, 900), arp=0.0, keys=0.35),
}

EIGHTHS = list(range(0, 16, 2))
DRUMS = {
    "verse": [dict(kick=[0, 7, 10], snare=[4, 12], chh=EIGHTHS), dict(kick=[0, 3, 8, 10], snare=[4, 12], chh=EIGHTHS, ohh=[14])],
    "verse2": [dict(kick=[0, 7, 10], snare=[4, 12], chh=EIGHTHS, shk=list(range(16))),
               dict(kick=[0, 3, 8, 10], snare=[4, 12], chh=EIGHTHS, ohh=[14], shk=list(range(16)))],
    "chorus": [dict(kick=[0, 4, 8, 12], snare=[4, 12], clap=[4, 12], ohh=[2, 6, 10, 14], chh=[1, 3, 5, 7, 9, 11, 13, 15])],
    "pre": [dict(kick=[0, 4, 8, 12], snare=[4, 12], chh=EIGHTHS)],
    "bridge_a": [dict(kick=[0], snare=[8])],
    "bridge_b": [dict(kick=[0, 10], snare=[8], chh=EIGHTHS)],
}


class Mixer:
    def __init__(self):
        self.stems = {k: np.zeros((N, 2)) for k in ("drums", "bass", "pads", "arp", "lead", "keys", "fx", "verb_fx")}
        self.kicks, self.snares, self.crashes, self.hats, self.events = [], [], [], [], []
        r = np.random.default_rng(1)
        self.kick_s = sy.kick()
        self.snare_s = [sy.snare(seed=s) for s in (4, 14, 24)]
        self.clap_s = sy.clap()
        self.chh_s = [sy.hat(seed=s) for s in (6, 16, 26, 36)]
        self.ohh_s = sy.hat(open_=True)
        self.crash_s = sy.crash()
        self.shk_s = [sy.shaker(seed=s) for s in (9, 19)]
        self.rng = r

    def hit(self, name, t, vel=1.0, p=0.0):
        d = self.stems["drums"]
        rv = vel * (0.92 + 0.08 * self.rng.random())
        if name == "kick":
            mix_into(d, self.kick_s, t, 0.95 * rv)
            self.kicks.append(t)
        elif name == "snare":
            mix_into(d, sy.pan(self.snare_s[self.rng.integers(3)], 0.04), t, 0.5 * rv)
            self.snares.append(t)
        elif name == "clap":
            mix_into(d, sy.pan(self.clap_s, -0.05), t, 0.42 * rv)
        elif name == "chh":
            mix_into(d, sy.pan(self.chh_s[self.rng.integers(4)], 0.25), t, 0.18 * rv)
            self.hats.append(t)
        elif name == "ohh":
            mix_into(d, sy.pan(self.ohh_s, -0.2), t, 0.16 * rv)
            self.hats.append(t)
        elif name == "shk":
            mix_into(d, sy.pan(self.shk_s[self.rng.integers(2)], 0.45), t, 0.16 * rv)
        elif name == "crash":
            mix_into(d, sy.pan(self.crash_s, p or -0.3), t, 0.35 * rv)
            self.crashes.append(t)


def drum_bar(m, bar, kind, idx_in_section, n_bars):
    t0 = at(bar)
    if kind == "intro":
        if bar == 2:
            for s in EIGHTHS:
                m.hit("chh", t0 + s * S16, 0.5 + 0.2 * (s % 4 == 0))
        if bar == 3:
            for s in EIGHTHS:
                m.hit("chh", t0 + s * S16, 0.6)
            for k, s in enumerate(range(8, 16, 2)):
                m.hit("snare", t0 + s * S16, 0.25 + 0.12 * k)
        return
    if kind == "pre" and idx_in_section == n_bars - 1:
        return  # the break before the drop
    if kind == "pre" and idx_in_section == n_bars - 2:
        for s in range(16):
            m.hit("kick", t0 + s * S16, 0.9) if s % 4 == 0 else None
            if s % 2 == 0 or s >= 8:
                m.hit("snare", t0 + s * S16, 0.3 + 0.5 * s / 15)
        return
    if kind == "bridge":
        pat = DRUMS["bridge_a" if idx_in_section < 4 else "bridge_b"][0]
        if idx_in_section == n_bars - 1:
            for s in range(0, 16):
                if s < 8 and s % 4 == 0:
                    m.hit("kick", t0 + s * S16)
                if s >= 4:
                    m.hit("snare", t0 + s * S16, 0.2 + 0.6 * (s - 4) / 11)
            return
    elif kind == "outro":
        if idx_in_section >= 2:
            if idx_in_section == 2:
                m.hit("kick", t0)
            return
        pat = DRUMS["chorus"][0]
    else:
        pats = DRUMS[kind]
        pat = pats[idx_in_section % len(pats)]
    for name, steps in pat.items():
        for s in steps:
            vel = 1.0
            if name in ("chh", "shk"):
                vel = 1.0 if s % 4 == 0 else 0.7 if s % 2 == 0 else 0.55
            m.hit(name, t0 + s * S16, vel)
    if kind in ("verse", "verse2") and idx_in_section == n_bars - 1:
        for k, s in enumerate((12, 13, 14, 15)):
            mix_into(m.stems["drums"], sy.pan(sy.tom(150 - 18 * k), 0.4 - 0.25 * k), t0 + s * S16, 0.45)


def sidechain(kicks, depth=0.55, release=0.16):
    g = np.ones(N)
    rel = int(0.45 * SR)
    t = np.arange(rel) / SR
    att = np.minimum(t / 0.004, 1.0)
    curve = 1 - depth * att * np.exp(-t / release)
    for k in kicks:
        i = int(k * SR)
        n = min(rel, N - i)
        if n > 0:
            g[i:i + n] = np.minimum(g[i:i + n], curve[:n])
    return g


def arrange():
    m = Mixer()
    prev_voicing = None
    for name, first, nbars, tr, _ in song.SECTIONS:
        cfg = ARR[name]
        for j in range(nbars):
            bar = first + j
            t0 = at(bar)
            u = j / max(nbars - 1, 1)
            root, pcs = bar_chord(bar)
            is_break = name.startswith("pre") and j == nbars - 1
            if cfg.get("drums"):
                drum_bar(m, bar, cfg["drums"], j, nbars)
            if is_break:
                continue
            # pads
            v = voicing(pcs, prev_voicing)
            prev_voicing = v
            cut = cfg["cut"][0] + (cfg["cut"][1] - cfg["cut"][0]) * u
            dur = BAR + (0.02 if j < nbars - 1 else 0.0)
            pad_notes = v + ([v[1] + 12, v[2] + 12] if cfg.get("octave_pad") else [])
            for k, note in enumerate(pad_notes):
                y = sy.supersaw(note, dur, cutoff=cut, attack=0.05 if name != "intro" else 0.6, seed=bar * 10 + k)
                mix_into(m.stems["pads"], y, t0, cfg["pad"] / len(pad_notes) * 2.2)
            # bass
            b_root = place(root, 37)
            if cfg.get("bass") == "pulse":
                for s in EIGHTHS:
                    note = b_root + (12 if (s == 14 and j % 2) else 0)
                    mix_into(m.stems["bass"], sy.bass(note, 0.2, cutoff=280 + 300 * u), t0 + s * S16, 0.55)
            elif cfg.get("bass") == "octave":
                for s in EIGHTHS:
                    note = b_root + (12 if s % 4 == 2 else 0)
                    mix_into(m.stems["bass"], sy.bass(note, 0.2, cutoff=420, env_amt=1400), t0 + s * S16, 0.5)
            elif cfg.get("bass") == "long":
                if j < 4:
                    mix_into(m.stems["bass"], sy.bass(b_root, BAR * 0.98, cutoff=200, env_amt=200), t0, 0.55)
                else:
                    for s in EIGHTHS:
                        mix_into(m.stems["bass"], sy.bass(b_root, 0.22, cutoff=260, env_amt=500), t0 + s * S16, 0.5)
            # arp
            if cfg.get("arp", 0) > 0:
                tones = sorted({place(pc, 61) for pc in pcs})
                tones = tones + [x + 12 for x in tones]
                order = [0, 1, 2, 3, 4, 3, 2, 1, 0, 2, 1, 3, 2, 4, 3, 5]
                b0, b1 = cfg["bright"]
                for s in range(16):
                    note = tones[order[s] % len(tones)]
                    br = (b0 + (b1 - b0) * (j + s / 16) / nbars) * (1.0 if s % 4 == 0 else 0.8)
                    mix_into(m.stems["arp"], sy.pluck(note, S16 * 0.9, bright=br), t0 + s * S16,
                             cfg["arp"] * (1.0 if s % 2 == 0 else 0.75))
            # keys (bridge / tag)
            if cfg.get("keys"):
                kv = voicing(pcs, None, lo=54, hi=72)
                hits = [(0.0, 1.9), (2.5, 1.4)] if name == "bridge" else [(0.0, 3.9)]
                for beat, length in hits:
                    for note in kv[:3]:
                        mix_into(m.stems["keys"], sy.pan(sy.epiano(note, length * BEAT), 0.0), t0 + beat * BEAT,
                                 cfg["keys"] * (0.8 if beat else 1.0))
        # section lead hook (post-choruses / outro): the vocal chop an octave up
        if cfg.get("lead"):
            reps = [0, 2] if name != "outro" else [0]
            for off in reps:
                part = song.Part("lead", first + off, "x", song.CHOP, transpose=tr + 12)
                notes = [(t - at(first + off), d, mm) for syl in song.parse_melody(part) for (t, d, mm) in syl]
                y = sy.lead(notes, 2 * BAR + 0.3)
                mix_into(m.stems["lead"], sy.pan(y, 0.1), at(first + off), 0.2)
    return m


def fx(m):
    f = m.stems["fx"]
    ev = m.events

    def add(name, t, clip, gain, p=0.0, verb=0.0):
        mix_into(f, sy.pan(clip, p) if clip.ndim == 1 else clip, t, gain)
        if verb:
            mix_into(m.stems["verb_fx"], sy.pan(clip, p) if clip.ndim == 1 else clip, t, gain * verb)
        ev.append({"type": name, "t": round(t, 3)})

    # boot chime + typing
    for k, note in enumerate((54, 61, 66, 69)):
        add("chime", 0.02 + 0.06 * k, sy.bell(note + 12, 2.5), 0.07, p=-0.3 + 0.2 * k, verb=0.6)
    for start, text, cps in song.TYPING:
        for i, ch in enumerate(text):
            if ch != " ":
                mix_into(f, sy.pan(sy.click(seed=i + int(start * 10)), 0.15), start + i * cps, 0.22)
        ev.append({"type": "typing", "t": start})
    # transitions
    add("riser", at(3), sy.riser(BAR), 0.3, verb=0.4)
    for drop, build_from, gain in ((at(16), at(12), 0.32), (at(40), at(36), 0.32), (at(60), at(59), 0.2)):
        add("riser", build_from, sy.riser(drop - build_from), gain, verb=0.4)
        rc = sy.crash()[::-1][-int(1.6 * SR):]
        add("reverse", drop - 1.6, rc, 0.3, p=0.2)
        add("impact", drop, sy.impact(), 0.55, verb=0.5)
        m.hit("crash", drop, 1.0)
    for t in (at(4), at(28), at(52), at(68)):
        m.hit("crash", t, 0.8 if t != at(52) else 0.6, p=0.3)
    add("impact", at(4), sy.impact(), 0.35, verb=0.4)
    for t in (at(20), at(44), at(64)):
        m.hit("crash", t, 0.6)
    for t in (at(28), at(52), at(70)):
        add("down", t, sy.downlifter(2.5), 0.22, verb=0.4)
    # the story beats in verse 2 and the tag
    add("error", at(32, 1.5), np.concatenate([sy.blip(46, 0.12), sy.blip(41, 0.25)]), 0.12, p=0.2)
    add("ding", at(33, 0.0), sy.bell(85, 2.0) + 0.6 * sy.bell(90, 2.0), 0.12, p=-0.2, verb=0.6)
    add("glitch", at(33, 1.5), sy.glitch(0.3), 0.25, p=0.3)
    for k in range(6):
        add("glitch", at(39, 2.2 + 0.25 * k), sy.glitch(0.12, seed=30 + k), 0.12 + 0.03 * k, p=(-1) ** k * 0.4)
    cue = song.CUES
    add("error", cue["typo"], np.concatenate([sy.blip(46, 0.12), sy.blip(41, 0.25)]), 0.12)
    add("ding", cue["fix"], sy.bell(80, 2.0) + 0.6 * sy.bell(87, 2.0), 0.14, verb=0.6)
    # final sting: big chord + impact
    root, pcs = bar_chord(75)
    for k, note in enumerate(voicing(pcs, None) + [place(root, 37)]):
        mix_into(m.stems["pads"], sy.supersaw(note, 1.5, cutoff=3200, attack=0.01, release=1.2, seed=900 + k),
                 cue["sting"], 0.3)
    add("impact", cue["sting"], sy.impact(3.0), 0.4, verb=0.6)
    m.hit("crash", cue["sting"], 0.7)


# Bus levels into the master: set so the lead vocal sits a few dB above the band.
INST_DB = -6.0
VOX_DB = 6.5


def vocal_duck(lead_bus, depth=0.3):
    """Gain curve that dips pads and arps a little while the lead sings."""
    env = sy._follow(np.max(np.abs(lead_bus), axis=1), 0.02, 0.25)
    env = np.clip(env / (np.percentile(env, 95) + 1e-9), 0, 1)
    return 1 - depth * env


def master_mix(m, vox_dry, vox_wet, lead_bus):
    s = m.stems
    sc = sidechain(m.kicks)
    duck = vocal_duck(lead_bus)[:, None]
    room = sy.reverb_ir(1.0, 0.01, 0.6, seed=31)
    hall = sy.reverb_ir(2.6, 0.03, 0.5, seed=32)

    drums = sy.compressor(s["drums"], -14, 2.5, 0.01, 0.12, makeup_db=2)
    snare_verb = sy.convolve(sy.hp(drums, 600) * 0.12, room)
    bass = sy.hp(s["bass"], 32) * sc[:, None] ** 0.8
    pads = sy.eq(sy.hp(s["pads"], 200), "peak", 450, -3.0, 0.8) * sc[:, None] * duck
    arp = sy.hp(s["arp"], 250) * (1 - 0.4 * (1 - sc))[:, None] * duck
    arp = arp + 0.35 * sy.echo(arp, 0.375, 0.38, taps=5, tone=3500)
    lead = s["lead"] + 0.4 * sy.echo(s["lead"], 0.375, 0.35, taps=4, tone=4000)
    keys = sy.widen(s["keys"], 0.4) * duck

    inst = drums + snare_verb + bass * 0.9 + pads * 0.75 + arp * 0.6 + lead * 0.8 + keys + s["fx"]
    inst_verb = sy.convolve(pads * 0.12 + arp * 0.18 + lead * 0.2 + keys * 0.25 + s["verb_fx"], hall)
    inst = inst + inst_verb
    # make room for the voice
    inst = sy.eq(inst, "peak", 2800, -2.5, 0.7)

    mix = inst * 10 ** (INST_DB / 20) + (vox_dry + vox_wet) * 10 ** (VOX_DB / 20)
    mix = sy.compressor(mix, -12, 1.8, 0.02, 0.2, makeup_db=0)
    mix = sy.eq(mix, "low", 45, -2.0, 0.7)
    mix = sy.eq(mix, "peak", 150, 1.5, 0.9)
    mix = sy.eq(mix, "peak", 350, -1.5, 0.9)
    mix = sy.eq(mix, "high", 8000, -1.5, 0.7)

    meter = pyln.Meter(SR)
    out = mix
    gain_db = 0.0
    for _ in range(3):
        out = sy.limiter(mix * 10 ** (gain_db / 20), -1.0)
        lufs = meter.integrated_loudness(out)
        gain_db += -14.0 - lufs
    out = sy.limiter(mix * 10 ** (gain_db / 20), -1.0)
    log(f"master: {meter.integrated_loudness(out):.1f} LUFS, peak {20 * np.log10(np.abs(out).max()):.2f} dBFS")
    return out, {"inst": inst, "bass": bass}


# ------------------------------------------------------------------ timing + features for the visuals

def envelope_from_hits(times, decay, length=LENGTH):
    n = int(length * FPS) + 1
    t = np.arange(n) / FPS
    env = np.zeros(n)
    for h in times:
        m = t >= h
        env[m] = np.maximum(env[m], np.exp(-(t[m] - h) / decay))
    return env


def frame_rms(x, smooth=0.0):
    hop = SR // FPS
    mono = x.mean(axis=1) if x.ndim == 2 else x
    n = len(mono) // hop
    r = np.sqrt(np.mean(mono[: n * hop].reshape(n, hop) ** 2, axis=1))
    if smooth:
        a = np.exp(-1 / (smooth * FPS))
        for i in range(1, len(r)):
            r[i] = max(r[i], a * r[i - 1])
    return r / (r.max() + 1e-9)


def spectrum_frames(x, bands=24):
    hop = SR // FPS
    mono = x.mean(axis=1)
    n = len(mono) // hop
    win = np.hanning(2048)
    edges = np.geomspace(40, 14000, bands + 1)
    freqs = np.fft.rfftfreq(2048, 1 / SR)
    idx = [np.where((freqs >= edges[i]) & (freqs < edges[i + 1]))[0] for i in range(bands)]
    out = np.zeros((n, bands))
    pad = np.pad(mono, (1024, 1024))
    for f in range(n):
        seg = pad[f * hop: f * hop + 2048] * win
        mag = np.abs(np.fft.rfft(seg))
        out[f] = [mag[i].mean() if len(i) else 0 for i in idx]
    out = 20 * np.log10(out + 1e-6)
    out = np.clip((out - np.percentile(out, 5)) / (np.percentile(out, 99.5) - np.percentile(out, 5)), 0, 1)
    return out


def export_timing(clips, m):
    lines = []
    for c in clips:
        if not c["display"]:
            continue
        lines.append({
            "kind": c["kind"], "voice": c["voice"], "section": c["section"],
            "text": c["text"].replace("-", ""),
            "t0": round(min(w["t0"] for w in c["words"]), 3), "t1": round(max(w["t1"] for w in c["words"]), 3),
            "words": [{"w": w["w"], "t0": round(w["t0"], 3), "t1": round(w["t1"], 3)} for w in c["words"]],
        })
    lines.sort(key=lambda l: l["t0"])
    sections = [{"name": n, "t0": at(f), "t1": at(f + b), "transpose": tr, "chords": ch.split()}
                for n, f, b, tr, ch in song.SECTIONS]
    timing = {
        "title": song.TITLE, "bpm": song.BPM, "length": LENGTH, "end": song.END_TIME, "fps": FPS,
        "sections": sections, "lines": lines,
        "typing": [{"t0": t, "text": s, "cps": c} for t, s, c in song.TYPING],
        "cues": song.CUES,
        "kicks": [round(t, 3) for t in sorted(set(m.kicks))],
        "snares": [round(t, 3) for t in sorted(set(m.snares))],
        "crashes": [round(t, 3) for t in sorted(set(m.crashes))],
        "events": sorted(m.events, key=lambda e: e["t"]),
    }
    (BUILD / "timing.json").write_text(json.dumps(timing, indent=1))
    return timing


def main():
    BUILD.mkdir(parents=True, exist_ok=True)
    t = time.time()
    clips = render_vocals(fresh="--fresh-vocals" in sys.argv)
    log(f"vocals ready ({len(clips)} clips)")
    vox_dry, vox_wet, lead_bus, vox_main = process_vocals(vocal_buses(clips))
    m = arrange()
    log("instruments arranged")
    fx(m)
    out, buses = master_mix(m, vox_dry, vox_wet, lead_bus)
    sf.write(BUILD / "song.wav", out.astype(np.float32), SR, subtype="PCM_24")
    for name in ("drums", "bass", "pads", "arp", "lead", "keys", "fx"):
        sf.write(BUILD / f"stem_{name}.wav", m.stems[name].astype(np.float32), SR)
    sf.write(BUILD / "stem_vocals.wav", (vox_dry + vox_wet).astype(np.float32), SR)
    sf.write(BUILD / "stem_vocals_main.wav", vox_main.astype(np.float32), SR)
    sf.write(BUILD / "stem_instrumental.wav", buses["inst"].astype(np.float32), SR)
    export_timing(clips, m)
    features = {
        "fps": FPS,
        "level": np.round(frame_rms(out, 0.15) * 100).astype(int).tolist(),
        "vox": np.round(frame_rms(lead_bus, 0.08) * 100).astype(int).tolist(),
        "bass": np.round(frame_rms(sy.lp(buses["bass"], 150), 0.12) * 100).astype(int).tolist(),
        "kick": np.round(envelope_from_hits(m.kicks, 0.12) * 100).astype(int).tolist(),
        "snare": np.round(envelope_from_hits(m.snares, 0.18) * 100).astype(int).tolist(),
        "hat": np.round(envelope_from_hits(m.hats, 0.05) * 100).astype(int).tolist(),
        "spectrum": np.round(spectrum_frames(out) * 99).astype(int).tolist(),
    }
    (BUILD / "features.json").write_text(json.dumps(features, separators=(",", ":")))
    log(f"done in {time.time() - t:.0f}s -> {BUILD}")


if __name__ == "__main__":
    main()
