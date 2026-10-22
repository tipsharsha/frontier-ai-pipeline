"""Make a Piper TTS voice sing.

Each lyric line is spoken by Piper as one phrase (so words flow naturally), then
re-timed and re-pitched with the WORLD vocoder: Piper's phoneme alignments tell
us where every syllable's consonants and vowel sit, the vowel nucleus is placed
on the beat and stretched to the note length, and F0 is replaced by the melody.
"""

from dataclasses import dataclass

import numpy as np
import pyworld as pw
from piper import PiperVoice, SynthesisConfig
from scipy.signal import resample_poly

OUT_SR = 48000
FRAME = 0.005  # WORLD frame period in seconds
VERSION = 2  # bump when the singing changes, so cached renders are redone
HOLD_SPEED = 0.15  # how fast long notes drift through the vowel (1 = speaking rate)

VOWELS = set("aeiouyæɐɑɒɔəɘɚɛɜɝɞɤɨɪʉʊʌʏɯøœɶᵻ")
MODIFIERS = set("ːˑʲ̃")
SYLLABIC = "̩"
STRESS = set("ˈˌ")
PUNCT = set(".,!?;:")


def midi_to_hz(m):
    return 440.0 * 2.0 ** ((np.asarray(m, dtype=float) - 69.0) / 12.0)


@dataclass
class Note:
    t: float  # vowel onset on the song timeline (s)
    dur: float  # seconds
    midi: float


@dataclass
class Style:
    glide: float = 0.05  # portamento between notes (s)
    vibrato: float = 0.3  # depth in semitones
    vibrato_rate: float = 5.4
    scoop: float = 0.6  # semitones below target at a phrase/leap onset
    jitter: float = 0.04  # slow random pitch drift (semitones)
    formant: float = 1.0  # >1 raises formants (smaller / more robotic)
    whisper: bool = False
    monotone: float | None = None  # fixed MIDI pitch for robot speech
    breath: float = 0.0  # aspiration noise mixed into voiced frames (0..1)
    consonant_db: float = 4.5  # lift unvoiced frames so consonants survive the mix
    length_scale: float = 1.0  # Piper speaking rate before re-timing
    seed: int = 0


@dataclass
class Syllable:
    o0: float  # onset consonants start (source seconds)
    v0: float  # vowel start
    h0: float  # hold region start (the part that gets stretched)
    h1: float  # hold region end
    n1: float  # vowel end
    c1: float = 0.0  # coda end (filled in once the next onset is known)


def _is_vowel_start(ph):
    return ph[:1] in VOWELS


def _syllabify(phones, expected):
    """Group (phoneme, t0, t1) items into syllables around vowel nuclei."""
    items = [p for p in phones if p[0] not in ("^", "$")]
    nuclei = []  # [start, end) index ranges of vowel runs (incl. modifiers)
    i = 0
    while i < len(items):
        ph = items[i][0]
        syllabic_c = i + 1 < len(items) and items[i + 1][0] == SYLLABIC
        if _is_vowel_start(ph) or syllabic_c:
            j = i + 1
            while j < len(items) and (
                _is_vowel_start(items[j][0]) or items[j][0] in MODIFIERS or items[j][0] == SYLLABIC
            ):
                j += 1
            nuclei.append([i, j])
            i = j
        else:
            i += 1

    # Too few nuclei: split vowel runs that espeak merged (e.g. hiatus "iə").
    while len(nuclei) < expected:
        best = None
        for n, (a, b) in enumerate(nuclei):
            starts = [k for k in range(a + 1, b) if _is_vowel_start(items[k][0])]
            if starts and (best is None or (b - a) > (best[2] - best[1])):
                best = (n, a, b, starts[0])
        if best is None:
            break
        n, a, b, k = best
        nuclei[n : n + 1] = [[a, k], [k, b]]
    if len(nuclei) != expected:
        text = "".join(p[0] for p in items)
        raise ValueError(f"expected {expected} syllables, found {len(nuclei)} in /{text}/")

    sylls = []
    first = 0
    while first < len(items) and items[first][0] in PUNCT | {" "}:
        first += 1
    onset_start = first
    for n, (a, b) in enumerate(nuclei):
        vowel_items = [k for k in range(a, b) if _is_vowel_start(items[k][0])]
        # Group each vowel letter with its trailing modifiers into elements.
        elems = []
        for k in vowel_items:
            e = k + 1
            while e < b and not _is_vowel_start(items[e][0]):
                e += 1
            elems.append((items[k][1], items[e - 1][2], items[k][0]))
        if not elems:  # syllabic consonant
            elems = [(items[a][1], items[b - 1][2], items[a][0])]
        # Hold the steady part of the main vowel: the first element of a
        # diphthong ("ma-a-ake"), but the schwa of a centring one ("mil-yuun").
        if len(elems) > 1 and elems[-1][2] in "əɚ":
            e0, e1, _ = elems[-1]
            h0, h1 = e0 + 0.15 * (e1 - e0), e0 + 0.7 * (e1 - e0)
        elif len(elems) > 1:
            e0, e1, _ = elems[0]
            h0, h1 = e0 + 0.25 * (e1 - e0), e0 + 0.85 * (e1 - e0)
        else:
            e0, e1, _ = elems[0]
            h0, h1 = e0 + 0.3 * (e1 - e0), e0 + 0.7 * (e1 - e0)
        sylls.append(
            Syllable(
                o0=items[onset_start][1] if onset_start < a else items[a][1],
                v0=items[a][1],
                h0=h0,
                h1=h1,
                n1=items[b - 1][2],
            )
        )
        # Split the consonant cluster before the next nucleus.
        if n + 1 < len(nuclei):
            nxt = nuclei[n + 1][0]
            cluster = list(range(b, nxt))
            spaces = [k for k in cluster if items[k][0] == " "]
            cons = [k for k in cluster if items[k][0] not in STRESS | PUNCT | {" "}]
            if spaces:
                split = spaces[-1] + 1
            elif len(cons) <= 1:
                split = b
            else:
                split = cons[1]
            # Stress marks belong to the following syllable's onset.
            while split > b and items[split - 1][0] in STRESS:
                split -= 1
            onset_start = split
            sylls[-1].c1 = items[split - 1][2] if split > b else items[b - 1][2]
        else:
            last = len(items)
            while last > b and items[last - 1][0] in PUNCT:
                last -= 1
            sylls[-1].c1 = items[last - 1][2]
    return sylls


class Singer:
    def __init__(self, model_path, speaker_id=None):
        self.voice = PiperVoice.load(model_path, include_alignments=True)
        self.sr = self.voice.config.sample_rate
        self.speaker_id = speaker_id
        self._cache = {}

    def speak(self, text, length_scale=1.0, noise=0.667, noise_w=0.8, take=0):
        """Piper speech plus a (phoneme, start, end) list in seconds.

        Piper samples fresh noise on every call, so each `take` is a slightly
        different performance (used for double-tracked vocals).
        """
        key = (text, length_scale, noise, noise_w, take)
        if key in self._cache:
            return self._cache[key]
        cfg = SynthesisConfig(
            speaker_id=self.speaker_id,
            length_scale=length_scale,
            noise_scale=noise,
            noise_w_scale=noise_w,
            normalize_audio=False,
        )
        audio, phones, t = [], [], 0.0
        for chunk in self.voice.synthesize(text, cfg, include_alignments=True):
            audio.append(chunk.audio_float_array.astype(np.float64))
            for al in chunk.phoneme_alignments or []:
                d = al.num_samples / self.sr
                phones.append((al.phoneme, t, t + d))
                t += d
        if not phones:
            raise RuntimeError(f"no alignments for {text!r}")
        out = (np.concatenate(audio), phones)
        self._cache[key] = out
        return out

    def say(self, text, style=Style(), pitch_shift=0.0):
        """Spoken line (optionally robot-monotone / whispered / formant-shifted)."""
        audio, _ = self.speak(text, length_scale=style.length_scale)
        if style.monotone is None and not style.whisper and style.formant == 1.0 and pitch_shift == 0:
            return self._to_out(audio)
        f0, sp, ap = self._analyze(audio)
        if style.whisper:
            f0 = np.zeros_like(f0)
        elif style.monotone is not None:
            voiced = f0 > 0
            m = np.full(len(f0), float(style.monotone))
            f0 = np.where(voiced, midi_to_hz(m), 0.0)
        elif pitch_shift:
            f0 = f0 * 2 ** (pitch_shift / 12)
        sp, ap = self._formant(sp, ap, style.formant)
        y = pw.synthesize(f0, sp, ap, self.sr, FRAME * 1000)
        return self._to_out(y)

    def sing(self, text, syllables, style=Style()):
        """Sing `text`; `syllables` is a list (one per syllable) of Note lists.

        Returns (start_time, audio) where start_time is on the song timeline.
        """
        rng = np.random.default_rng(style.seed)
        audio, phones = self.speak(text, length_scale=style.length_scale, take=style.seed)
        sylls = _syllabify(phones, len(syllables))
        f0s, sp, ap = self._analyze(audio)

        starts = [notes[0].t for notes in syllables]
        ends = [notes[-1].t + notes[-1].dur for notes in syllables]
        n = len(sylls)

        # Place consonant clusters: they borrow time from the previous note,
        # which keeps at least a short vowel (singers clip vowels, not consonants).
        def room_in(note_len):
            return note_len - max(0.04, 0.3 * note_len)

        onset_t = [0.0] * n  # target onset durations
        coda_end = [0.0] * n  # target time where each syllable's coda ends
        coda_len = [0.0] * n
        for k in range(n):
            O = sylls[k].v0 - sylls[k].o0
            if k == 0:
                onset_t[k] = min(O, 0.3)
                continue
            C = sylls[k - 1].c1 - sylls[k - 1].n1
            prev_len = ends[k - 1] - starts[k - 1]
            gap = starts[k] - ends[k - 1]
            if gap < 0.06:  # legato: coda + onset sit just before this note
                room = max(room_in(prev_len), 0.45 * prev_len) + max(gap, 0.0)
                s = min(1.0, room / max(C + O, 1e-6))
                onset_t[k] = O * s
                coda_len[k - 1] = C * s
                coda_end[k - 1] = starts[k] - onset_t[k]
            else:  # rest: coda ends the previous note, onset leads into this one
                coda_len[k - 1] = min(C, max(room_in(prev_len), 0.45 * prev_len))
                coda_end[k - 1] = ends[k - 1]
                onset_t[k] = min(O, gap, 0.3)
        C = sylls[-1].c1 - sylls[-1].n1
        coda_len[-1] = min(C, max(room_in(ends[-1] - starts[-1]), 0.45 * (ends[-1] - starts[-1])))
        coda_end[-1] = ends[-1]

        t0 = starts[0] - onset_t[0]
        t1 = coda_end[-1] + 0.02
        nf = int(np.ceil((t1 - t0) / FRAME))
        tt = t0 + np.arange(nf) * FRAME
        src = np.full(nf, -1.0)  # source time per target frame; -1 = silence
        owner = np.full(nf, -1)  # syllable index per frame

        for k, s in enumerate(sylls):
            a = starts[k] - onset_t[k]
            nuc_end = coda_end[k] - coda_len[k]
            D = nuc_end - starts[k]
            pre, hold, post = s.h0 - s.v0, s.h1 - s.h0, s.n1 - s.h1
            if D >= pre + post + 0.25 * hold:
                P, Hh, Q = pre, D - pre - post, post
            else:
                sc = max(D, 1e-3) / max(s.n1 - s.v0, 1e-6)
                P, Hh, Q = pre * sc, hold * sc, post * sc
            m = (tt >= a) & (tt < coda_end[k])
            owner[m] = k
            x = tt[m]
            out = np.empty_like(x)
            # onset: linear (possibly compressed)
            seg = x < starts[k]
            out[seg] = np.interp(x[seg], [a, starts[k]], [s.o0, s.v0])
            seg = (x >= starts[k]) & (x < starts[k] + P)
            out[seg] = np.interp(x[seg], [starts[k], starts[k] + P], [s.v0, s.h0])
            hs = starts[k] + P
            seg = (x >= hs) & (x < hs + Hh)
            if np.any(seg):
                u = (x[seg] - hs) / max(Hh, 1e-6)
                if Hh > 2.5 * hold and hold > 0:
                    # Long note: drift slowly back and forth through the steady
                    # part of the vowel instead of freezing on one frame (faster
                    # drift makes the formants wobble audibly).
                    cycles = max(1, int(round(Hh * HOLD_SPEED / hold)))
                    cycles += 1 - cycles % 2
                    u = 0.5 - 0.5 * np.cos(np.pi * cycles * u)
                out[seg] = s.h0 + hold * u
            seg = (x >= hs + Hh) & (x < nuc_end)
            out[seg] = np.interp(x[seg], [hs + Hh, nuc_end], [s.h1, s.n1])
            seg = x >= nuc_end
            out[seg] = np.interp(x[seg], [nuc_end, coda_end[k]], [s.n1, s.c1])
            src[m] = out

        # Resample WORLD parameters along the warped time axis.
        nsrc = len(f0s)
        pos = np.clip(src / FRAME, 0, nsrc - 1)
        i0 = np.floor(pos).astype(int)
        i1 = np.minimum(i0 + 1, nsrc - 1)
        w = (pos - i0)[:, None]
        logsp = np.log(np.maximum(sp, 1e-16))
        sp_t = np.exp((1 - w) * logsp[i0] + w * logsp[i1])
        ap_t = (1 - w) * ap[i0] + w * ap[i1]
        voiced = f0s[np.rint(pos).astype(int)] > 0
        silent = src < 0
        sp_t[silent] = 1e-16
        ap_t[silent] = 1.0
        voiced &= ~silent
        if style.consonant_db:
            sp_t[~voiced & ~silent] *= 10 ** (style.consonant_db / 10)

        midi = self._melody_curve(tt, syllables, starts, ends, owner, style, rng)
        f0 = np.where(voiced, midi_to_hz(midi), 0.0)
        if style.whisper:
            f0[:] = 0.0
        if style.breath > 0:
            ap_t = np.clip(ap_t + style.breath * (1 - ap_t) * np.linspace(0.3, 1, ap_t.shape[1]), 0, 1)
        sp_t, ap_t = self._formant(sp_t, ap_t, style.formant)
        y = pw.synthesize(np.ascontiguousarray(f0), np.ascontiguousarray(sp_t), np.ascontiguousarray(ap_t), self.sr, FRAME * 1000)
        return t0, self._to_out(y)

    def _melody_curve(self, tt, syllables, starts, ends, owner, style, rng):
        # Step curve: each frame takes the pitch of the note sounding at that time;
        # onset consonants already take their syllable's first note.
        step = np.zeros(len(tt))
        flat = [(note.t, note.dur, note.midi) for notes in syllables for note in notes]
        for k, notes in enumerate(syllables):
            m = owner == k
            step[m] = notes[0].midi
            for note in notes[1:]:
                step[m & (tt >= note.t)] = note.midi
        # Silent frames inherit the next pitch so glides start cleanly.
        idx = np.where(owner >= 0)[0]
        if len(idx):
            step = np.interp(np.arange(len(tt)), idx, step[idx])
        # Portamento: smooth the steps with a short window.
        g = max(1, int(round(style.glide / FRAME)))
        if g > 1:
            win = np.hanning(g + 2)[1:-1]
            win /= win.sum()
            pad = np.pad(step, (g, g), mode="edge")
            step = np.convolve(pad, win, mode="same")[g:-g]
        curve = step.copy()
        prev_end, prev_m = -1e9, None
        for t, d, mm in flat:
            rel = tt - t
            on = rel >= 0
            if style.scoop and (t - prev_end > 0.05 or (prev_m is not None and abs(mm - prev_m) > 2)):
                curve[on] -= style.scoop * np.exp(-rel[on] / 0.045)
            if style.vibrato and d > 0.32:
                inside = on & (rel < d)
                ramp = np.clip((rel[inside] - 0.16) / 0.3, 0, 1)
                curve[inside] += style.vibrato * ramp * np.sin(2 * np.pi * style.vibrato_rate * rel[inside])
            prev_end, prev_m = t + d, mm
        if style.jitter:
            drift = np.cumsum(rng.normal(0, 1, len(tt)))
            drift -= np.convolve(drift, np.ones(40) / 40, mode="same")
            curve += style.jitter * drift / (np.std(drift) + 1e-9)
        return curve

    def _analyze(self, audio):
        x = np.ascontiguousarray(audio, dtype=np.float64)
        f0, t = pw.harvest(x, self.sr, f0_floor=60.0, f0_ceil=700.0, frame_period=FRAME * 1000)
        sp = pw.cheaptrick(x, f0, t, self.sr)
        ap = pw.d4c(x, f0, t, self.sr)
        return f0, sp, ap

    @staticmethod
    def _formant(sp, ap, factor):
        if factor == 1.0:
            return sp, ap
        bins = sp.shape[1]
        src = np.clip(np.arange(bins) / factor, 0, bins - 1)
        i0 = np.floor(src).astype(int)
        i1 = np.minimum(i0 + 1, bins - 1)
        w = src - i0
        sp2 = np.exp((1 - w) * np.log(np.maximum(sp[:, i0], 1e-16)) + w * np.log(np.maximum(sp[:, i1], 1e-16)))
        ap2 = (1 - w) * ap[:, i0] + w * ap[:, i1]
        return np.ascontiguousarray(sp2), np.ascontiguousarray(ap2)

    def _to_out(self, y):
        y = resample_poly(np.asarray(y, dtype=np.float64), OUT_SR, self.sr)
        fade = int(0.008 * OUT_SR)
        if len(y) > 2 * fade:
            ramp = np.linspace(0, 1, fade)
            y[:fade] *= ramp
            y[-fade:] *= ramp[::-1]
        return y
