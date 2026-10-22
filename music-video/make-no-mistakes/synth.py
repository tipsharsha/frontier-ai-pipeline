"""A small numpy/numba synthesizer: oscillators, filters, drums and effects."""

import numpy as np
from numba import njit
from scipy.ndimage import minimum_filter1d
from scipy.signal import butter, lfilter, oaconvolve, sosfilt

SR = 48000


def midi_hz(m):
    return 440.0 * 2.0 ** ((np.asarray(m, dtype=float) - 69.0) / 12.0)


def secs(n):
    return np.arange(n) / SR


# ---------------------------------------------------------------- oscillators

def _blep(t, dt):
    y = np.zeros_like(t)
    m = t < dt
    x = t[m] / dt[m]
    y[m] = x + x - x * x - 1.0
    m = t > 1.0 - dt
    x = (t[m] - 1.0) / dt[m]
    y[m] = x * x + x + x + 1.0
    return y


def _phase(freq, phase0):
    dt = freq / SR
    return (phase0 + np.cumsum(dt) - dt[0]) % 1.0, dt


def saw(freq, phase0=0.0):
    t, dt = _phase(freq, phase0)
    return 2.0 * t - 1.0 - _blep(t, dt)


def square(freq, width=0.5, phase0=0.0):
    t, dt = _phase(freq, phase0)
    y = np.where(t < width, 1.0, -1.0)
    return y + _blep(t, dt) - _blep((t + 1.0 - width) % 1.0, dt)


def sine(freq, phase0=0.0):
    t, _ = _phase(freq, phase0)
    return np.sin(2 * np.pi * t)


def adsr(n, a=0.005, d=0.1, s=0.7, r=0.1, curve=4.0):
    """Envelope for a note held n samples, followed by an r-second release."""
    na, nd, nr = int(a * SR), int(d * SR), int(r * SR)
    env = np.empty(n + nr)
    k = np.arange(n)
    att = k < na
    env[:n][att] = k[att] / max(na, 1)
    dec = ~att
    env[:n][dec] = s + (1 - s) * np.exp(-curve * (k[dec] - na) / max(nd, 1))
    last = env[n - 1] if n else 0.0
    env[n:] = last * np.exp(-6.0 * np.arange(nr) / max(nr, 1))
    return env


# ---------------------------------------------------------------- filters

@njit(cache=True)
def svf(x, cutoff, q, mode):
    """Zavalishin TPT state-variable filter with per-sample cutoff.

    mode: 0 lowpass, 1 bandpass, 2 highpass.
    """
    y = np.empty_like(x)
    ic1 = 0.0
    ic2 = 0.0
    k = 1.0 / q
    for n in range(len(x)):
        c = cutoff[n]
        if c > 0.45 * SR:
            c = 0.45 * SR
        g = np.tan(np.pi * c / SR)
        a1 = 1.0 / (1.0 + g * (g + k))
        a2 = g * a1
        a3 = g * a2
        v3 = x[n] - ic2
        v1 = a1 * ic1 + a2 * v3
        v2 = ic2 + a2 * ic1 + a3 * v3
        ic1 = 2.0 * v1 - ic1
        ic2 = 2.0 * v2 - ic2
        if mode == 0:
            y[n] = v2
        elif mode == 1:
            y[n] = v1
        else:
            y[n] = x[n] - k * v1 - v2
    return y


def lp(x, f, order=2):
    return sosfilt(butter(order, f, "low", fs=SR, output="sos"), x, axis=0)


def hp(x, f, order=2):
    return sosfilt(butter(order, f, "high", fs=SR, output="sos"), x, axis=0)


def bp(x, lo, hi, order=2):
    return sosfilt(butter(order, [lo, hi], "band", fs=SR, output="sos"), x, axis=0)


def _rbj(kind, f, gain_db, q):
    A = 10 ** (gain_db / 40)
    w = 2 * np.pi * f / SR
    cw, sw = np.cos(w), np.sin(w)
    alpha = sw / (2 * q)
    if kind == "peak":
        b = [1 + alpha * A, -2 * cw, 1 - alpha * A]
        a = [1 + alpha / A, -2 * cw, 1 - alpha / A]
    elif kind == "low":
        sa = 2 * np.sqrt(A) * alpha
        b = [A * ((A + 1) - (A - 1) * cw + sa), 2 * A * ((A - 1) - (A + 1) * cw), A * ((A + 1) - (A - 1) * cw - sa)]
        a = [(A + 1) + (A - 1) * cw + sa, -2 * ((A - 1) + (A + 1) * cw), (A + 1) + (A - 1) * cw - sa]
    else:  # high shelf
        sa = 2 * np.sqrt(A) * alpha
        b = [A * ((A + 1) + (A - 1) * cw + sa), -2 * A * ((A - 1) + (A + 1) * cw), A * ((A + 1) + (A - 1) * cw - sa)]
        a = [(A + 1) - (A - 1) * cw + sa, 2 * ((A - 1) - (A + 1) * cw), (A + 1) - (A - 1) * cw - sa]
    return np.array(b) / a[0], np.array(a) / a[0]


def eq(x, kind, f, gain_db, q=0.8):
    b, a = _rbj(kind, f, gain_db, q)
    return lfilter(b, a, x, axis=0)


# ---------------------------------------------------------------- dynamics

@njit(cache=True)
def _follow(level, attack, release):
    out = np.empty_like(level)
    ga = np.exp(-1.0 / (attack * SR))
    gr = np.exp(-1.0 / (release * SR))
    e = 0.0
    for n in range(len(level)):
        v = level[n]
        g = ga if v > e else gr
        e = g * e + (1.0 - g) * v
        out[n] = e
    return out


def compressor(x, threshold_db=-18.0, ratio=3.0, attack=0.005, release=0.12, makeup_db=0.0, knee=6.0):
    det = np.abs(x) if x.ndim == 1 else np.max(np.abs(x), axis=1)
    env = _follow(det, attack, release)
    lvl = 20 * np.log10(np.maximum(env, 1e-9))
    over = lvl - threshold_db
    gr = np.where(
        over <= -knee / 2, 0.0,
        np.where(over >= knee / 2, over * (1 - 1 / ratio), (1 - 1 / ratio) * (over + knee / 2) ** 2 / (2 * knee)),
    )
    g = 10 ** ((makeup_db - gr) / 20)
    return x * (g if x.ndim == 1 else g[:, None])


@njit(cache=True)
def _release(g, release):
    out = np.empty_like(g)
    r = np.exp(-1.0 / (release * SR))
    cur = 1.0
    for n in range(len(g)):
        t = g[n]
        if t < cur:
            cur = t
        else:
            cur = r * cur + (1.0 - r) * t
        out[n] = cur
    return out


def limiter(x, ceiling_db=-1.0, lookahead=0.004, release=0.06):
    ceiling = 10 ** (ceiling_db / 20)
    la = int(lookahead * SR)
    peak = np.max(np.abs(x), axis=1)
    target = np.minimum(1.0, ceiling / np.maximum(peak, 1e-9))
    g = minimum_filter1d(target, size=2 * la + 1, mode="nearest")
    g = _release(g, release)
    # smooth attack over the lookahead window
    k = np.hanning(la * 2 + 1)
    g = np.minimum(g, oaconvolve(g, k / k.sum(), mode="same"))
    return x * g[:, None]


def saturate(x, drive=1.0):
    return np.tanh(drive * x) / np.tanh(drive)


# ---------------------------------------------------------------- space

def pan(x, p):
    """Equal-power pan of a mono signal, p in [-1, 1]."""
    a = (p + 1) * np.pi / 4
    return np.stack([x * np.cos(a), x * np.sin(a)], axis=1)


def reverb_ir(decay=1.8, predelay=0.02, damp=0.5, seed=1):
    n = int(decay * 1.3 * SR)
    t = secs(n)
    r = np.random.default_rng(seed)
    ir = np.zeros((n, 2))
    bands = [(None, 500, 1.0), (500, 2500, 0.9), (2500, 7000, 1 - 0.5 * damp), (7000, None, 1 - 0.8 * damp)]
    for ch in range(2):
        noise = r.standard_normal(n)
        for lo, hi, mult in bands:
            if lo is None:
                b = lp(noise, hi)
            elif hi is None:
                b = hp(noise, lo)
            else:
                b = bp(noise, lo, hi)
            ir[:, ch] += b * np.exp(-6.9 * t / (decay * mult))
    ir[: int(0.004 * SR)] *= np.linspace(0, 1, int(0.004 * SR))[:, None]
    d = int(predelay * SR)
    ir = np.concatenate([np.zeros((d, 2)), ir])
    return ir / np.sqrt(np.sum(ir**2) / 2)


def convolve(x, ir):
    x2 = x if x.ndim == 2 else np.stack([x, x], axis=1)
    out = np.stack([oaconvolve(x2[:, c], ir[:, c])[: len(x2)] for c in range(2)], axis=1)
    return out


def echo(x, delay, feedback=0.4, taps=6, tone=4000.0, pingpong=True):
    """Feedback-style delay built from decaying, darkening taps (stereo in/out)."""
    x2 = x if x.ndim == 2 else np.stack([x, x], axis=1)
    out = np.zeros_like(x2)
    d = int(delay * SR)
    tap = x2.copy()
    for k in range(1, taps + 1):
        tap = lp(tap, max(tone * 0.8 ** k, 600.0), order=1) * feedback
        shifted = np.zeros_like(tap)
        shifted[k * d:] = tap[: len(tap) - k * d] if k * d < len(tap) else 0
        if pingpong and k % 2:
            shifted = shifted[:, ::-1]
        out += shifted
    return out


def widen(x, amount=0.3):
    m = (x[:, 0] + x[:, 1]) / 2
    s = (x[:, 0] - x[:, 1]) / 2 * (1 + amount)
    return np.stack([m + s, m - s], axis=1)


# ---------------------------------------------------------------- drums

def kick(length=0.45, f0=150.0, f1=46.0, pdecay=0.04, adecay=0.32, click=0.5, drive=1.8):
    n = int(length * SR)
    t = secs(n)
    f = f1 + (f0 - f1) * np.exp(-t / pdecay)
    body = np.sin(2 * np.pi * np.cumsum(f) / SR)
    env = np.where(t < 0.015, 1.0, np.exp(-(t - 0.015) / adecay))
    ck = hp(np.random.default_rng(3).standard_normal(n), 1500) * np.exp(-t / 0.0025)
    y = saturate(body * env + click * ck, drive)
    return y * np.minimum(1, (n - np.arange(n)) / 200)


def snare(length=0.35, tone=190.0, snappy=0.75, decay=0.16, seed=4):
    n = int(length * SR)
    t = secs(n)
    r = np.random.default_rng(seed)
    body = (np.sin(2 * np.pi * tone * t) + 0.5 * np.sin(2 * np.pi * tone * 1.7 * t)) * np.exp(-t / 0.05)
    noise = bp(r.standard_normal(n), 1200, 9000) * np.exp(-t / decay)
    return saturate(0.6 * body + snappy * 1.6 * noise, 1.3)


def clap(length=0.45, seed=5):
    n = int(length * SR)
    t = secs(n)
    r = np.random.default_rng(seed)
    noise = bp(r.standard_normal(n), 900, 6000)
    env = np.zeros(n)
    for k, off in enumerate((0.0, 0.009, 0.019, 0.03)):
        m = t >= off
        env[m] += np.exp(-(t[m] - off) / (0.006 if k < 3 else 0.12)) * (0.8 if k < 3 else 1.0)
    return saturate(noise * env * 1.8, 1.2)


_METAL = np.array([205.3, 304.4, 369.6, 522.7, 540.0, 800.0])


def metal(n):
    t = secs(n)
    return sum(np.sign(np.sin(2 * np.pi * f * 1.47 * t + i)) for i, f in enumerate(_METAL)) / 6


def hat(length=0.06, open_=False, seed=6):
    n = int((0.45 if open_ else length) * SR)
    t = secs(n)
    r = np.random.default_rng(seed)
    src = 0.6 * metal(n) + 0.7 * r.standard_normal(n)
    y = hp(bp(src, 6500, 15000), 7000)
    return y * np.exp(-t / (0.13 if open_ else 0.018)) * 0.9


def crash(length=2.4, seed=8):
    n = int(length * SR)
    t = secs(n)
    r = np.random.default_rng(seed)
    src = 0.5 * metal(n) + r.standard_normal(n)
    y = hp(src, 3500)
    return y * (np.exp(-t / 0.7) * 0.8 + 0.2 * np.exp(-t / 0.08)) * 0.55


def tom(f=120.0, length=0.4):
    n = int(length * SR)
    t = secs(n)
    f_t = f * (0.75 + 0.25 * np.exp(-t / 0.06))
    return np.sin(2 * np.pi * np.cumsum(f_t) / SR) * np.exp(-t / 0.18)


def shaker(length=0.08, seed=9):
    n = int(length * SR)
    t = secs(n)
    y = bp(np.random.default_rng(seed).standard_normal(n), 5000, 11000)
    return y * np.minimum(t / 0.012, 1) * np.exp(-t / 0.03)


# ---------------------------------------------------------------- instruments

def supersaw(midi, dur, voices=7, detune=0.18, cutoff=2600.0, attack=0.04, release=0.35, seed=0):
    """Stereo detuned-saw chord tone."""
    n = int(dur * SR)
    r = np.random.default_rng(seed)
    out = np.zeros((n + int(release * SR), 2))
    env = adsr(n, attack, 0.3, 0.85, release)
    m = len(env)
    for v in range(voices):
        off = (v - (voices - 1) / 2) / ((voices - 1) / 2) * detune
        f = np.full(m, midi_hz(midi + off))
        y = saw(f, r.random()) * env
        p = (v / (voices - 1)) * 1.6 - 0.8
        out += pan(y, p) / voices
    cut = np.full(m, cutoff)
    return np.stack([svf(out[:, c], cut, 0.7, 0) for c in range(2)], axis=1)


def pluck(midi, dur, bright=1.0, decay=0.22, seed=0):
    n = int(max(dur, 0.05) * SR)
    m = n + int(0.12 * SR)
    t = secs(m)
    f = np.full(m, midi_hz(midi))
    y = 0.6 * saw(f) + 0.4 * square(f, 0.3)
    cut = 500 + 5500 * bright * np.exp(-t / 0.09)
    y = svf(y, cut, 1.2, 0)
    env = np.exp(-t / decay) * np.minimum(t / 0.002, 1)
    env[n:] *= np.exp(-np.arange(m - n) / (0.03 * SR))
    return y * env


def bass(midi, dur, cutoff=320.0, env_amt=900.0, glide_from=None):
    n = int(dur * SR)
    m = n + int(0.04 * SR)
    t = secs(m)
    f = np.full(m, midi_hz(midi))
    if glide_from is not None:
        f = midi_hz(midi + (glide_from - midi) * np.exp(-t / 0.03))
    y = 0.7 * saw(f) + 0.6 * square(f / 2) + 0.4 * np.sin(2 * np.pi * np.cumsum(f / 2) / SR)
    cut = cutoff + env_amt * np.exp(-t / 0.08)
    y = svf(y, cut, 1.0, 0)
    env = adsr(n, 0.003, 0.15, 0.75, 0.04)[:m]
    return saturate(y * env, 1.4)


def lead(notes, length, vibrato=0.12, cutoff=3800.0):
    """Monophonic lead; notes = [(start, dur, midi)] relative to clip start."""
    n = int(length * SR)
    t = secs(n)
    pitch = np.full(n, notes[0][2], dtype=float)
    gate = np.zeros(n)
    for s, d, m in notes:
        a, b = int(s * SR), min(int((s + d) * SR), n)
        pitch[a:] = m
        gate[a:b] = 1
    k = np.hanning(int(0.03 * SR))
    pitch = np.convolve(np.pad(pitch, (len(k), len(k)), mode="edge"), k / k.sum(), mode="same")[len(k):-len(k)]
    pitch = pitch + vibrato * np.sin(2 * np.pi * 5.5 * t) * np.clip((t % 1.0) * 2, 0, 1)
    f = midi_hz(pitch)
    y = 0.45 * saw(f) + 0.45 * saw(f * 1.006, 0.3) + 0.3 * square(f * 2, 0.5)
    env = _follow(gate, 0.004, 0.06)
    return svf(y, np.full(n, cutoff), 0.9, 0) * env


def epiano(midi, dur, vel=1.0):
    """Two-operator FM electric piano."""
    n = int(dur * SR) + int(0.6 * SR)
    t = secs(n)
    f = midi_hz(midi)
    idx = (1.8 * vel) * np.exp(-t / 0.5) + 0.25
    mod = np.sin(2 * np.pi * f * t) * idx
    car = np.sin(2 * np.pi * f * t + mod) + 0.25 * np.sin(2 * np.pi * 2 * f * t + 0.5 * mod)
    env = np.exp(-t / 1.6) * np.minimum(t / 0.003, 1)
    env[int(dur * SR):] *= np.exp(-np.arange(n - int(dur * SR)) / (0.15 * SR))
    tine = np.sin(2 * np.pi * f * 7.0 * t) * np.exp(-t / 0.03) * 0.15
    return (car + tine) * env * 0.5


def bell(midi, length=1.5):
    n = int(length * SR)
    t = secs(n)
    f = midi_hz(midi)
    mod = np.sin(2 * np.pi * f * 3.5 * t) * 2.5 * np.exp(-t / 0.4)
    return np.sin(2 * np.pi * f * t + mod) * np.exp(-t / 0.6) * np.minimum(t / 0.002, 1)


# ---------------------------------------------------------------- fx

def riser(length, f0=300.0, f1=9000.0, seed=10):
    n = int(length * SR)
    u = np.linspace(0, 1, n)
    r = np.random.default_rng(seed)
    cut = f0 * (f1 / f0) ** (u**1.6)
    y = svf(r.standard_normal(n), cut, 2.5, 1)
    siren = saw(midi_hz(60 + 18 * u**1.3)) * 0.12
    y = (y * 0.8 + svf(siren, cut, 0.8, 0)) * u**2.2
    return y


def downlifter(length=2.0, seed=11):
    n = int(length * SR)
    u = np.linspace(0, 1, n)
    r = np.random.default_rng(seed)
    cut = 8000 * (200 / 8000) ** u
    return svf(r.standard_normal(n), cut, 1.5, 1) * (1 - u) ** 1.5


def impact(length=2.5, seed=12):
    n = int(length * SR)
    t = secs(n)
    f = 30 + 90 * np.exp(-t / 0.25)
    boom = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.9)
    noise = lp(np.random.default_rng(seed).standard_normal(n), 2500) * np.exp(-t / 0.35)
    return saturate(boom + 0.5 * noise, 1.5)


def click(seed=0, bright=1.0):
    """A mechanical key click for the typing sounds."""
    n = int(0.03 * SR)
    t = secs(n)
    r = np.random.default_rng(seed)
    y = bp(r.standard_normal(n), 1800 * bright, 7000) * np.exp(-t / 0.004)
    y += 0.3 * np.sin(2 * np.pi * (2800 + 600 * r.random()) * t) * np.exp(-t / 0.006)
    return y * 0.6


def blip(midi, length=0.12, wave="square"):
    n = int(length * SR)
    t = secs(n)
    f = np.full(n, midi_hz(midi))
    y = square(f, 0.5) if wave == "square" else sine(f)
    return y * np.exp(-t / (length / 3)) * np.minimum(t / 0.002, 1)


def glitch(length=0.25, seed=13):
    n = int(length * SR)
    r = np.random.default_rng(seed)
    seg = r.standard_normal(n // 8)
    y = np.repeat(seg, 8)[:n]
    y = np.round(y * 3) / 3
    return bp(y, 400, 6000) * 0.5


def mix_into(buf, clip, start, gain=1.0):
    """Add a mono or stereo clip into a stereo buffer at time `start` (s)."""
    i = int(round(start * SR))
    if i >= len(buf):
        return
    if clip.ndim == 1:
        clip = np.stack([clip, clip], axis=1)
    j0 = max(0, -i)
    i = max(i, 0)
    n = min(len(clip) - j0, len(buf) - i)
    if n > 0:
        buf[i:i + n] += gain * clip[j0:j0 + n]
