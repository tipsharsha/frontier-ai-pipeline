"""Sync the music video to a Suno take of the song.

    python suno_sync.py take.m4a --vocals take_vocals.wav [--fresh]

Suno sings the song with a real voice (see SUNO_PROMPT.md). This works out when
each lyric is sung in the take and where its bars fall, and writes what
render_video.mjs needs to BUILD_DIR (default build/suno):

- song.wav: the take, with the typed prompt before it and the typo tag after it
- timing.json and features.json, as build_audio.py writes them for the
  synthesized song

--vocals is the take's isolated vocal from a source separator, for example
audio-separator with the UVR model Kim_Vocal_2.onnx. Whisper large-v3-turbo
transcribes it to find roughly where each section is sung, then a wav2vec2 CTC
model aligns the known lyrics inside that window, letter by letter. A beat
tracker finds the bars: Suno's tempo drifts (from 124 to 130 BPM in this take),
so every beat is tracked rather than laid on a fixed grid.
"""

import argparse
import json
import os
import re
import subprocess
import time
from pathlib import Path

import librosa
import numpy as np
import pyloudnorm as pyln
import pyworld as pw
import soundfile as sf
from numba import njit
from scipy.signal import resample_poly

import song
import synth as sy
from build_audio import (FPS, VOICES, _spoken_words, envelope_from_hits, frame_rms, make_speaker, place,
                         process_vocals, spectrum_frames, voicing)
from singer import Singer, Style
from synth import SR, mix_into

HERE = Path(__file__).resolve().parent
BUILD = Path(os.environ.get("BUILD_DIR", HERE / "build" / "suno"))
WHISPER = "large-v3-turbo"
W2V = ("facebook/wav2vec2-large-960h-lv60-self", "refs/pr/5")  # the safetensors copy of its weights
PREROLL = 2.4  # seconds of typed prompt before the take starts


def chops(*counts):
    return [("chop", ", ".join(["Make no"] * n) + " mistakes") for n in counts]


CHORUS = [("echo", "Make no mistakes"), ("backing", "You're absolutely right!"),
          ("lead", "Ship it tonight, whatever it takes"), ("lead", "One shot, one take, for heaven's sake"),
          ("lead", "Make no mistakes"), ("backing", "You're absolutely right!")]

# What this take sings, section by section, and the bar each section starts on,
# counted from the first downbeat (a fraction starts it on the pickup). Suno moved
# a few things around: it sings the hook in the intro, ends each pre-chorus on the
# chorus's opening "make no mistakes", repeats the post-chorus chops, and holds
# the bridge's last "on" over the drop into the final chorus. "echo" lines are
# not sung there: they flash the hook up as the chorus drops.
TAKE = [
    ("intro", 0, [("hook", "Make no mistakes")]),
    ("verse1", 8, [("lead", "Build a startup, make it fly"), ("lead", "Worth a billion by July"),
                   ("lead", "Make it pretty, make it scale"), ("lead", "Get it right and never fail")]),
    ("pre1", 15.5, [("lead", "You're a senior engineer"), ("lead", "Twenty years, the best one here"),
                    ("lead", "Step by step, I'll tip you well"), ("spoken", "And make no mistakes.")]),
    ("chorus1", 20, CHORUS),
    ("post1", 30, chops(4, 5, 5)),
    ("verse2", 36, [("lead", "You're absolutely right, my bad"), ("lead", "I fixed the bug you never had"),
                    ("lead", "The tests were red, I made them green"), ("whisper", "I deleted them."),
                    ("lead", "The cleanest build you've ever seen")]),
    ("pre2", 43.75, [("lead", "Context window filling up"), ("lead", "Lost the plot, I'm out of luck"),
                     ("lead", "Can't recall a word you said"), ("robot", "I remember, make no mistakes.")]),
    ("chorus2", 48, CHORUS),
    ("post2", 58, chops(1, 4, 5)),
    ("bridge", 63.75, [("lead", "A billion guesses, wrong, wrong, wrong"),
                       ("lead", "The loss came down, I learned this song"),
                       ("lead", "Each perfect note I've learned to sing"),
                       ("lead", "Mistakes have taught me everything")]),
    ("final", 73, [("lead", "So go on."), ("lead", "Make new mistakes"), ("backing", "You're absolutely right!"),
                   ("lead", "Break it tonight, whatever it takes"), ("lead", "Fall down, get up, for heaven's sake"),
                   ("lead", "Make new mistakes"), ("backing", "You're absolutely right!")]),
    ("outro", 88, [("chop", "Make new mistakes"), ("chop", "Make new mistakes"), ("lead", "Make new mistakes")]),
]


def log(*a):
    print(f"[{time.strftime('%H:%M:%S')}]", *a, flush=True)


def load_audio(path):
    """Any file ffmpeg reads, as stereo float at SR."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "2", "-ar", str(SR), "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).reshape(-1, 2).astype(np.float64)


def cached(path, make):
    """make()'s JSON result, kept in `path` between runs."""
    if path.exists():
        return json.loads(path.read_text())
    out = make()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out))
    return out


# ------------------------------------------------------------------ finding the words

def transcribe(v16):
    from faster_whisper import WhisperModel
    model = WhisperModel(WHISPER, device="cpu", compute_type="int8")
    # Never skip a window as silence or as a hallucination: sung vowels trip both checks.
    segs, _ = model.transcribe(v16.astype(np.float32), language="en", beam_size=5, word_timestamps=True,
                               condition_on_previous_text=False, vad_filter=False, no_speech_threshold=None,
                               log_prob_threshold=None, compression_ratio_threshold=None)
    return [[w.word.strip(), round(w.start, 3), round(w.end, 3)] for s in segs for w in s.words]


def ctc_emissions(v16, path):
    """wav2vec2 log-probabilities (50 frames a second) and its vocabulary, kept in `path`."""
    if path.exists():
        z = np.load(path, allow_pickle=False)
        return z["em"], dict(zip(z["tokens"].tolist(), z["ids"].tolist()))
    import torch
    from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor
    proc = Wav2Vec2Processor.from_pretrained(W2V[0], revision=W2V[1])
    model = Wav2Vec2ForCTC.from_pretrained(W2V[0], revision=W2V[1], use_safetensors=True).eval()
    x = v16.astype(np.float32)
    hop, pad, n = 20 * 16000, 2 * 16000, len(v16) // 320
    blank = proc.tokenizer.pad_token_id
    em = np.full((n, model.config.vocab_size), -30.0, np.float32)
    em[:, blank] = 0.0  # any frame past the model's last output counts as silence
    for a in range(0, len(x), hop):  # 20 s at a time, with 2 s of context either side
        lo, hi = max(0, a - pad), min(len(x), a + hop + pad)
        inp = proc(x[lo:hi], sampling_rate=16000, return_tensors="pt").input_values
        with torch.inference_mode():
            lp = torch.log_softmax(model(inp).logits[0], -1).numpy()
        f0 = a // 320
        part = lp[f0 - lo // 320:][: min(n, (a + hop) // 320) - f0]
        em[f0:f0 + len(part)] = part
    vocab = proc.tokenizer.get_vocab()
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(path, em=em, tokens=np.array(list(vocab)), ids=np.array(list(vocab.values())))
    return em, vocab


@njit(cache=True)
def _viterbi(em, ids, wild, blank, wild_pen):
    """Best CTC path through tokens `ids` (-1 = wildcard); returns the state per frame."""
    T, S = em.shape[0], 2 * len(ids) + 1
    neg = -1e18
    dp = np.full(S, neg)
    back = np.zeros((T, S), np.int8)

    def emit(f, s):
        if s % 2 == 0:
            return em[f, blank]
        k = ids[(s - 1) // 2]
        return wild[f] - wild_pen if k < 0 else em[f, k]

    dp[0], dp[1] = emit(0, 0), emit(0, 1)
    for f in range(1, T):
        new = np.full(S, neg)
        for s in range(S):
            best, arg = dp[s], 0
            if s >= 1 and dp[s - 1] > best:
                best, arg = dp[s - 1], 1
            if s >= 3 and s % 2 == 1 and ids[(s - 1) // 2] != ids[(s - 3) // 2] and dp[s - 2] > best:
                best, arg = dp[s - 2], 2
            if best > neg:
                new[s] = best + emit(f, s)
                back[f, s] = arg
        dp = new
    s = S - 1 if dp[S - 1] >= dp[S - 2] else S - 2
    path = np.zeros(T, np.int64)
    for f in range(T - 1, -1, -1):
        path[f] = s
        s -= back[f, s]
    return path


def force_align(em, vocab, a, b, lines, wild_pen=4.0):
    """Word (start, end) times for `lines` (lists of words) sung somewhere in [a, b] s.

    Wildcards before, between and after the lines take up anything sung that is
    not in the text: neighbouring sections, ad libs, breaths.
    """
    f0, f1 = int(a * 50), min(int(b * 50), len(em))
    sub = np.ascontiguousarray(em[f0:f1], dtype=np.float64)
    letters = [i for k, i in vocab.items() if len(k) == 1 and (k.isalpha() or k == "'")]
    wild = sub[:, letters].max(axis=1)
    tokens = [(-1, None)]  # (vocab id, the (line, word) it spells)
    for li, words in enumerate(lines):
        for wi, w in enumerate(words):
            if wi:
                tokens.append((vocab["|"], None))
            tokens += [(vocab[ch], (li, wi)) for ch in re.sub(r"[^A-Z']", "", w.upper())]
        tokens.append((-1, None))
    path = _viterbi(sub, np.array([i for i, _ in tokens], np.int64), wild, vocab["<pad>"], wild_pen)
    spans = {}
    for f, s in enumerate(path):
        word = tokens[(s - 1) // 2][1] if s % 2 else None
        if word is not None:
            t = (f0 + f) / 50
            spans[word] = (spans.get(word, (t, t))[0], t + 0.02)
    return [[spans[(li, wi)] for wi in range(len(words))] for li, words in enumerate(lines)]


def _norm(w):
    return re.sub(r"[^a-z']", "", w.lower())


def match_words(a, b):
    """Global alignment of two word lists (Needleman-Wunsch); {index in a: index in b} for equal words."""
    n, m = len(a), len(b)
    S = np.zeros((n + 1, m + 1))
    S[:, 0], S[0, :] = -np.arange(n + 1), -np.arange(m + 1)
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            S[i, j] = max(S[i - 1, j - 1] + (2 if a[i - 1] == b[j - 1] else -1), S[i - 1, j] - 1, S[i, j - 1] - 1)
    pairs, i, j = {}, n, m
    while i and j:
        if S[i, j] == S[i - 1, j - 1] + (2 if a[i - 1] == b[j - 1] else -1):
            if a[i - 1] == b[j - 1]:
                pairs[i - 1] = j - 1
            i, j = i - 1, j - 1
        elif S[i, j] == S[i - 1, j] - 1:
            i -= 1
        else:
            j -= 1
    return pairs


def voiced_mask(v16):
    """Per 10 ms: is the singer audible (within 30 dB of the take's loud singing)?"""
    e = 10 * np.log10(np.convolve(v16 ** 2, np.ones(320) / 320, "same")[::160] + 1e-12)
    return e > np.percentile(e, 95) - 30


def next_note(v16, a, b):
    """When the sung pitch first moves a semitone or more (for 0.1 s) between a and b seconds."""
    f0, _ = pw.harvest(v16[int(a * 16000):int(b * 16000)].astype(np.float64), 16000, f0_floor=80, f0_ceil=1000,
                       frame_period=10)
    midi = np.where(f0 > 0, 12 * np.log2(np.maximum(f0, 1) / 440) + 69, np.nan)
    voiced = np.flatnonzero(~np.isnan(midi))
    if len(voiced) < 20:
        return None
    ref = np.median(midi[voiced[:10]])
    for i in voiced[10:]:
        held = midi[i:i + 10]
        if len(held) == 10 and np.all(np.abs(held - ref) >= 1):
            return a + i / 100
    return None


def align_take(em, vocab, heard, v16, length):
    """{(section index, line index): [(start, end) per word]} for every sung line of TAKE, in seconds."""
    sung = []  # (section index, line index, words)
    for si, (_, _, rows) in enumerate(TAKE):
        sung += [(si, li, text.split()) for li, (kind, text) in enumerate(rows) if kind != "echo"]
    flat = [(k, w) for k, (_, _, words) in enumerate(sung) for w in words]
    pairs = match_words([_norm(w) for _, w in flat], [_norm(w) for w, _, _ in heard])
    log(f"Whisper heard {len(pairs)} of the {len(flat)} sung words")
    # a window per section around the words Whisper placed there
    found = {}
    for i, j in pairs.items():
        found.setdefault(sung[flat[i][0]][0], []).append(heard[j][1:])
    times = {}
    for si in sorted({s for s, _, _ in sung}):
        if si not in found:
            raise SystemExit(f"Whisper heard nothing of {TAKE[si][0]}; check TAKE against the take")
        mid = np.median([t0 for t0, _ in found[si]])
        near = [(t0, t1) for t0, t1 in found[si] if abs(t0 - mid) < 20]  # drop stray matches
        a, b = min(t0 for t0, _ in near), max(t1 for _, t1 in near)
        rows = [(li, words) for s, li, words in sung if s == si]
        spans = force_align(em, vocab, max(0.0, a - 1.0), min(length, b + 1.0), [w for _, w in rows])
        for (li, _), sp in zip(rows, spans):
            times[(si, li)] = sp
    mask = voiced_mask(v16)
    # A word that opens on a vowel straight out of the last one ("so go o-o-on")
    # only shows up in CTC at its closing consonant: start it on the new note.
    words_of = {(si, li): words for si, li, words in sung}
    for key, sp in times.items():
        for wi in range(1, len(sp)):
            a, b = sp[wi - 1][1], sp[wi][0]
            legato = b - a > 0.5 and mask[int(a * 100):int(b * 100)].mean() > 0.9
            if legato and words_of[key][wi][0].lower() in "aeiou":
                onset = next_note(v16, a, b)
                if onset is not None:
                    sp[wi] = (onset, sp[wi][1])
    # CTC marks a word from its first letter to its last; let held notes ring on
    # until the voice stops or the next word starts
    order = sorted(times, key=lambda k: times[k][0][0])
    for n, key in enumerate(order):
        sp = times[key]
        nxt = times[order[n + 1]][0][0] - 0.05 if n + 1 < len(order) else length
        for wi, (t0, t1) in enumerate(sp):
            cap = sp[wi + 1][0] - 0.02 if wi + 1 < len(sp) else min(nxt, t1 + 8.0)
            k = int(t1 * 100)
            while k < len(mask) and mask[k] and k / 100 < cap:
                k += 1
            sp[wi] = (t0 - 0.03, max(t1, min(k / 100, cap)))
    return times


# ------------------------------------------------------------------ bars and drums

def beat_grid(mono):
    y = librosa.resample(mono, orig_sr=SR, target_sr=22050)
    env = librosa.onset.onset_strength(y=y, sr=22050, hop_length=128)
    tempo = librosa.feature.tempo(onset_envelope=env, sr=22050, hop_length=128)[0]
    _, frames = librosa.beat.beat_track(onset_envelope=env, sr=22050, hop_length=128, start_bpm=tempo, tightness=400)
    beats = librosa.frames_to_time(frames, sr=22050, hop_length=128)
    # the chords change on downbeats: find which beat of four the bass moves on
    C = librosa.feature.chroma_cqt(y=y, sr=22050, hop_length=256, fmin=librosa.note_to_hz("C1"), n_octaves=3)
    ft = librosa.frames_to_time(np.arange(C.shape[1]), sr=22050, hop_length=256)
    per = np.array([C[:, (ft >= beats[i]) & (ft < beats[i + 1])].mean(axis=1) for i in range(len(beats) - 1)])
    per /= np.linalg.norm(per, axis=1, keepdims=True) + 1e-9
    change = np.r_[0, 1 - np.sum(per[1:] * per[:-1], axis=1)]
    phase = int(np.argmax([change[p::4].mean() for p in range(4)]))
    return beats, phase


def _level_db(x, fps=100):
    hop = SR // fps
    return 10 * np.log10(np.convolve(x ** 2, np.ones(hop) / hop, "same")[::hop] + 1e-12)


def beat_hits(x, times, jump=3.0, floor=-45.0):
    """Of `times`, those where `x` (one drum's band) jumps up: when that drum hits."""
    e, out = _level_db(x, 200), []
    for t in times:
        a, b, c = int((t - 0.12) * 200), int((t - 0.02) * 200), int((t + 0.06) * 200)
        if a < 0 or c >= len(e):
            continue
        peak = e[b:c].max()
        if peak - e[a:b - 2].mean() > jump and peak > floor:
            out.append(round((b + int(np.argmax(e[b:c]))) / 200, 3))
    return out


def band_break(inst, beats, a, b):
    """The beat of the band's last hit before it drops out inside [a, b] (a pre-chorus break)."""
    e = _level_db(inst, 50)[int(a * 50):int(b * 50)]
    quiet, run = e < np.median(e) - 10, 0
    for k, q in enumerate(quiet):
        run = run + 1 if q else 0
        if run >= 20:
            return float(beats[beats <= a + (k - run + 1) / 50].max())
    return None


def chord_at(x, a, b):
    """The major or minor triad that best fits x between a and b seconds: (root pc, (pcs))."""
    y = librosa.resample(x[int(a * SR):int(b * SR)], orig_sr=SR, target_sr=22050)
    c = librosa.feature.chroma_cqt(y=y, sr=22050).mean(axis=1)
    _, r, third = max((c[r] + c[(r + th) % 12] + c[(r + 7) % 12], r, th) for r in range(12) for th in (3, 4))
    return r, (r, (r + third) % 12, (r + 7) % 12)


# ------------------------------------------------------------------ the take, voiced around

class Voices:
    """The spoken parts around the take, in the synthesized version's voices."""

    def __init__(self):
        import torch
        torch.manual_seed(0)  # Kokoro's vocoder adds random noise; a fixed seed keeps renders identical
        self.singers, self.clips = {}, []

    def say(self, t0, voice, kind, section, text, style):
        spec = VOICES[voice]
        if spec not in self.singers:
            self.singers[spec] = Singer(make_speaker(spec))
        s = self.singers[spec]
        st = Style(**style)
        audio = s.say(song.tts_text(text), st)
        words = _spoken_words(s, text, t0, st.length_scale)
        self.clips.append(dict(t0=t0, audio=audio, bus="robot" if kind == "robot" else "user"))
        return {"kind": kind, "voice": voice, "section": section, "text": text, "t0": round(words[0]["t0"], 3),
                "t1": round(words[-1]["t1"], 3), "words": [{**w, "t0": round(w["t0"], 3), "t1": round(w["t1"], 3)}
                                                            for w in words]}


def typing_clicks(buf, entry):
    start, text, cps = entry["t0"], entry["text"], entry["cps"]
    for i, ch in enumerate(text):
        if ch != " ":
            mix_into(buf, sy.pan(sy.click(seed=i + int(start * 10)), 0.15), start + i * cps, 0.22)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("take", help="the Suno song (any format ffmpeg reads)")
    ap.add_argument("--vocals", required=True, help="the take's isolated vocal")
    ap.add_argument("--fresh", action="store_true", help="redo the transcription and alignment")
    args = ap.parse_args()
    BUILD.mkdir(parents=True, exist_ok=True)
    started = time.time()

    take, vocals = load_audio(args.take), load_audio(args.vocals)
    n = min(len(take), len(vocals))
    take, vocals = take[:n], vocals[:n]
    take_len = n / SR
    inst = (take - vocals).mean(axis=1)
    v16 = resample_poly(vocals.mean(axis=1), 1, SR // 16000)

    if args.fresh:
        for f in (BUILD / "cache").glob("*"):
            f.unlink()
    heard = cached(BUILD / "cache" / "whisper.json", lambda: transcribe(v16))
    em, vocab = ctc_emissions(v16, BUILD / "cache" / "ctc.npz")
    times = align_take(em, vocab, heard, v16, take_len)
    beats, phase = beat_grid(take.mean(axis=1))
    log(f"{len(beats)} beats, {60 / np.median(np.diff(beats)):.1f} BPM median, downbeats on beat {phase + 1} of 4")

    P = PREROLL
    def bar(b):
        return P + float(beats[phase + int(round(b * 4))])

    # sections: the intro opens on the typed prompt; the tag follows the take
    starts = [0.0] + [bar(b) for _, b, _ in TAKE[1:]]
    sections = [{"name": name, "t0": round(t0, 3), "t1": round(t1, 3)}
                for (name, _, _), t0, t1 in zip(TAKE, starts, starts[1:] + [P + take_len])]
    tag_t0 = P + take_len

    voices, lines = Voices(), []
    for si, (name, _, rows) in enumerate(TAKE):
        for li, (kind, text) in enumerate(rows):
            if kind == "echo":
                # the hook slams in word by word on the drop
                t0 = sections[si]["t0"]
                words = [{"w": w, "t0": round(t0 + 0.12 * i, 3), "t1": round(t0 + 0.12 * i + 0.3, 3)}
                         for i, w in enumerate(text.split())]
            else:
                words = [{"w": w, "t0": round(P + a, 3), "t1": round(P + b, 3)}
                         for w, (a, b) in zip(text.split(), times[(si, li)])]
            lines.append({"kind": "lead" if kind == "echo" else kind, "voice": "lead", "section": name,
                          "text": text, "t0": words[0]["t0"], "t1": words[-1]["t1"], "words": words})

    # intro: the first prompt is typed and spoken before the take; the sung hook
    # types the second
    hook = next(l for l in lines if l["kind"] == "hook")
    q2_t0 = hook["words"][0]["t0"] - 0.08
    typing = [{"t0": 0.30, "text": "make me a music video.", "cps": 0.042},
              {"t0": round(q2_t0, 3), "text": "make no mistakes.",
               "cps": round((hook["words"][-1]["t0"] + 0.25 - q2_t0) / len("make no mistakes."), 4)}]
    lines.append(voices.say(0.6, "user", "spoken", "intro", "Make me a music video.", song.USER))
    lines.append(voices.say(bar(4), "ai", "robot", "intro", "On it.", song.ROBOT))
    cues = {"tasks": [round(bar(b), 3) for b in (5, 6, 7, 7.5)]}
    for name in ("pre1", "pre2"):
        s = next(x for x in sections if x["name"] == name)
        brk = band_break(inst, beats, s["t0"] - P, s["t1"] - P)
        if brk is None:  # no clear drop-out: break on the prompt's last line
            brk = next(l for l in lines if l["section"] == name and l["kind"] in ("spoken", "robot"))["t0"] - P
        cues[name] = round(P + brk, 3)

    # tag: the agent reports back, and the typo is caught and fixed
    r0 = voices.say(tag_t0 + 0.3, "ai", "robot", "tag", "Music video complete.", song.ROBOT)
    r1 = voices.say(r0["t1"] + 0.35, "ai", "robot", "tag", "Zero mistakes.", song.ROBOT)
    q3 = {"t0": round(r1["t1"] + 0.6, 3), "text": "there's a typo in the title.", "cps": 0.034}
    user = voices.say(q3["t0"] + 0.7, "user", "spoken", "tag", "There's a typo in the title.", song.USER)
    r2 = voices.say(user["t1"] + 0.3, "ai", "robot", "tag", "You're absolutely right!", {**song.ROBOT, "monotone": 67})
    lines += [r0, r1, user, r2]
    typing.append(q3)
    cues.update(typo=round(user["t0"] + 0.12, 3), fix=round(r2["t1"] + 0.05, 3))
    cues["sting"] = round(cues["fix"] + 0.5, 3)
    length = round(cues["sting"] + 3.1, 2)
    sections.append({"name": "tag", "t0": round(tag_t0, 3), "t1": length})
    lines.sort(key=lambda l: l["t0"])

    # ---- audio
    N = int(length * SR)
    song_buf, vox_buf, sfx, verb_send = (np.zeros((N, 2)) for _ in range(4))
    mix_into(song_buf, take, P)
    mix_into(vox_buf, vocals, P)
    buses = {k: np.zeros((N, 2)) for k in ("lead", "double", "harmony", "backing", "user", "robot", "whisper")}
    for c in voices.clips:
        mix_into(buses[c["bus"]], c["audio"], c["t0"])
    vo_dry, vo_wet, _, _ = process_vocals(buses)
    vo = vo_dry + vo_wet
    meter = pyln.Meter(SR)
    spoken = np.concatenate([vo[int(l["t0"] * SR):int(l["t1"] * SR)] for l in lines if l["voice"] in ("user", "ai")])
    vo_gain = 10 ** ((-16.0 - meter.integrated_loudness(spoken)) / 20)  # speech about as loud as the singing
    vo *= vo_gain
    # dip the take a little under the agent's voice in the intro
    duck = np.ones(N)
    for l in lines:
        if l["kind"] == "robot" and l["section"] == "intro":
            a, b = int((l["t0"] - 0.1) * SR), int((l["t1"] + 0.25) * SR)
            duck[a:b] = 10 ** (-4 / 20)
    duck = sy._follow(duck, 0.08, 0.08)[:, None]

    first, last = chord_at(take.mean(axis=1), 0.2, 2.0), chord_at(inst, take_len - 1.5, take_len - 0.3)
    log(f"chords: first {first}, last {last} (root, pitch classes)")
    for k, note in enumerate(sorted(place(pc, 64) for pc in first[1])):  # boot chime: the take's first chord
        chime = sy.pan(sy.bell(note + 12, 2.5), -0.3 + 0.2 * k)
        mix_into(sfx, chime, 0.02 + 0.06 * k, 0.07)
        mix_into(verb_send, chime, 0.02 + 0.06 * k, 0.04)
    for entry in typing:
        typing_clicks(sfx, entry)
    mix_into(sfx, np.concatenate([sy.blip(46, 0.12), sy.blip(41, 0.25)]), cues["typo"], 0.12)
    ding = sy.bell(place(last[0], 76), 2.0) + 0.6 * sy.bell(place(last[1][2], 76), 2.0)
    mix_into(sfx, ding, cues["fix"], 0.14)
    mix_into(verb_send, ding, cues["fix"], 0.08)
    # under the tag, the take's last chord held softly; then the sting
    notes = voicing(last[1], None) + [place(last[0], 37)]
    for k, note in enumerate(notes):
        bed = sy.supersaw(note, cues["sting"] - tag_t0 + 0.2, cutoff=900, attack=1.2, release=0.6, seed=700 + k)
        mix_into(sfx, bed, tag_t0 - 0.3, 0.05)
        hit = sy.supersaw(note, 1.5, cutoff=3200, attack=0.01, release=1.2, seed=900 + k)
        mix_into(sfx, hit, cues["sting"], 0.3)
        mix_into(verb_send, hit, cues["sting"], 0.2)
    mix_into(sfx, sy.impact(3.0), cues["sting"], 0.4)
    mix_into(sfx, sy.pan(sy.crash(), 0.3), cues["sting"], 0.35)
    sfx += sy.convolve(verb_send, sy.reverb_ir(2.6, 0.03, 0.5, seed=32))

    out = sy.limiter(song_buf * duck + vo + sfx, -1.0)
    log(f"song.wav: {length:.1f} s, {meter.integrated_loudness(out):.1f} LUFS")
    sf.write(BUILD / "song.wav", out.astype(np.float32), SR, subtype="PCM_24")

    # ---- what the picture follows
    kicks = [round(P + t, 3) for t in beat_hits(sy.lp(inst, 110, order=4), beats, floor=-40)]
    backbeats = beats[(np.arange(len(beats)) - phase) % 2 == 1]
    snares = [round(P + t, 3) for t in beat_hits(sy.bp(inst, 1500, 5000), backbeats)]
    eighths = np.sort(np.r_[beats, (beats[1:] + beats[:-1]) / 2])
    hats = [round(P + t, 3) for t in beat_hits(sy.hp(inst, 7000, order=4), eighths, floor=-55)]
    timing = {
        "title": song.TITLE, "bpm": round(60 / float(np.median(np.diff(beats))), 1), "length": length,
        "end": round(P + take_len, 3), "fps": FPS, "sections": sections, "lines": lines, "typing": typing,
        "cues": cues, "kicks": kicks, "snares": snares, "crashes": [round(cues["sting"], 3)], "events": [],
    }
    (BUILD / "timing.json").write_text(json.dumps(timing, indent=1))
    vox_all = vox_buf + vo_dry * vo_gain
    features = {
        "fps": FPS,
        "level": np.round(frame_rms(out, 0.15) * 100).astype(int).tolist(),
        "vox": np.round(frame_rms(vox_all, 0.08) * 100).astype(int).tolist(),
        "bass": np.round(frame_rms(sy.lp(song_buf - vox_buf, 150), 0.12) * 100).astype(int).tolist(),
        "kick": np.round(envelope_from_hits(kicks, 0.12, length) * 100).astype(int).tolist(),
        "snare": np.round(envelope_from_hits(snares, 0.18, length) * 100).astype(int).tolist(),
        "hat": np.round(envelope_from_hits(hats, 0.05, length) * 100).astype(int).tolist(),
        "spectrum": np.round(spectrum_frames(out) * 99).astype(int).tolist(),
    }
    (BUILD / "features.json").write_text(json.dumps(features, separators=(",", ":")))
    for l in lines:
        print(f"  {l['section']:8s} {l['kind']:8s} {l['t0']:7.2f}-{l['t1']:7.2f}  "
              + " ".join(f"{w['w']}@{w['t0']:.2f}" for w in l["words"]))
    log(f"done in {time.time() - started:.0f}s -> {BUILD}")


if __name__ == "__main__":
    main()
