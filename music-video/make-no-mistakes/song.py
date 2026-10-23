"""Make No Mistakes: the score.

120 BPM. Written in F# minor and sounding a whole step lower (E minor, see KEY),
with a lift of two semitones for the last chorus.
Melodies are written as "PITCH:DUR" tokens in sixteenth notes, "rN" for rests and
"~PITCH:DUR" to carry the previous syllable onto another note. Lyrics are
hyphenated into syllables; each syllable takes the next pitch token.
"""

from dataclasses import dataclass, field

BPM = 120
BEAT = 60 / BPM
BAR = 4 * BEAT
S16 = BEAT / 4
KEY = -2  # sounding transposition of everything written below

TITLE = "Make No Mistakes"


def at(bar, beat=0.0):
    return bar * BAR + beat * BEAT


# name, first bar, length in bars, transpose (semitones), chords (one per bar)
SECTIONS = [
    ("intro", 0, 4, 0, "F#m D A E"),
    ("verse1", 4, 8, 0, "F#m F#m D D A A E E"),
    ("pre1", 12, 4, 0, "Bm Bm D E"),
    ("chorus1", 16, 8, 0, "D E F#m A D E F#m F#m"),
    ("post1", 24, 4, 0, "D E F#m F#m"),
    ("verse2", 28, 8, 0, "F#m F#m D D A A E E"),
    ("pre2", 36, 4, 0, "Bm Bm D E"),
    ("chorus2", 40, 8, 0, "D E F#m A D E F#m F#m"),
    ("post2", 48, 4, 0, "D E F#m F#m"),
    ("bridge", 52, 8, 0, "D D A A E E F#m F#m"),
    ("final", 60, 8, 2, "D E F#m A D E F#m F#m"),
    ("outro", 68, 4, 2, "D E F#m F#m"),
    ("tag", 72, 4, 2, "F#m F#m F#m F#m"),
]
END_TIME = at(76)


def section_at(bar):
    for s in SECTIONS:
        if s[1] <= bar < s[1] + s[2]:
            return s
    return SECTIONS[-1]


def chord_at(bar):
    """(chord symbol, transpose) sounding in a given bar."""
    name, first, _, tr, chords = section_at(bar)
    return chords.split()[bar - first], tr + KEY


@dataclass
class Part:
    kind: str  # lead | double | harmony | backing | chop | spoken | robot | whisper
    bar: float  # start bar (sung parts: where the melody's first token sits)
    text: str  # hyphenated lyric (sung) or plain text (spoken)
    melody: str = ""
    voice: str = "lead"  # lead | ai | user
    section: str = ""
    transpose: int = 0
    gain: float = 1.0
    pan: float = 0.0
    style: dict = field(default_factory=dict)
    display: bool = True  # show these words on screen


HOOK = "A4:4 F#4:4 E4:2 F#4:10 r12"
HOOK_HARM = "F#4:4 D4:4 C#4:2 D4:10 r12"
HOOK_HARM_MINOR = "F#4:4 C#4:4 C#4:2 C#4:10 r12"
BACKING_E = "B4:1 B4:1 B4:1 B4:2 G#4:2 B4:2"
BACKING_FM = "C#5:1 C#5:1 C#5:1 C#5:2 A4:2 C#5:2"
SHIP = "F#4:2 F#4:2 E4:2 F#4:6 E4:2 F#4:2 E4:2 C#4:2 E4:12"
SHIP_HARM = "C#4:2 C#4:2 C#4:2 C#4:6 C#4:2 D4:2 C#4:2 A3:2 C#4:12"
SHOT = "A4:4 F#4:4 E4:2 F#4:6 r2 E4:2 F#4:2 A4:2 B4:8"
SHOT_HARM = "F#4:4 D4:4 C#4:2 D4:6 r2 C#4:2 D4:2 F#4:2 G#4:8"
CHOP = "A4:2 F#4:2 r2 A4:2 F#4:2 r2 A4:2 F#4:2 E4:2 F#4:10 r4"


def chorus(first_bar, section, tr=0, final=False):
    word = "new" if final else "no"
    l2 = "Break it to-night, what-ev-er it takes" if final else "Ship it to-night, what-ev-er it takes"
    l3 = "Fall down, get up, for heav-en's sake" if final else "One shot, one take, for heav-en's sake"
    hook = f"Make {word} mis-takes"
    lines = [
        (0, hook, HOOK, HOOK_HARM),
        (2, l2, SHIP, SHIP_HARM),
        (4, l3, SHOT, SHOT_HARM),
        (6, hook, HOOK, HOOK_HARM_MINOR),
    ]
    parts = []
    for off, text, mel, harm in lines:
        b = first_bar + off
        parts.append(Part("lead", b, text, mel, section=section, transpose=tr))
        for i, pan in enumerate((-0.45, 0.45)):
            parts.append(
                Part("double", b, text, mel, section=section, transpose=tr, gain=0.34, pan=pan,
                     style={"seed": 11 + i + off, "vibrato": 0.15}, display=False)
            )
        parts.append(
            Part("harmony", b, text, harm, section=section, transpose=tr, gain=0.3, pan=0.2 if off % 4 else -0.2,
                 style={"seed": 31 + off}, display=False)
        )
    # The robot's reply fills the gap after the hook ("-LUTE-" and "RIGHT" on beats 3
    # and 4), ending an eighth note before the next line.
    for off, mel in ((1, BACKING_E), (7, BACKING_FM)):
        parts.append(
            Part("backing", first_bar + off + 5 / 16, "You're ab-so-lute-ly right!", mel, voice="ai",
                 section=section, transpose=tr, gain=0.55, pan=0.3)
        )
    return parts


def post_chorus(first_bar, section, tr=0, word="no"):
    text = f"Make {word}, make {word}, make {word} mis-takes"
    parts = []
    for off in (0, 2):
        parts.append(
            Part("chop", first_bar + off, text, CHOP, section=section, transpose=tr, gain=0.85,
                 style={"glide": 0.012, "vibrato": 0.0, "scoop": 0.0, "formant": 1.06})
        )
        parts.append(
            Part("chop", first_bar + off, text, CHOP, section=section, transpose=tr - 12, gain=0.35,
                 pan=-0.3, style={"glide": 0.012, "vibrato": 0.0, "scoop": 0.0, "formant": 1.0, "seed": 5},
                 display=False)
        )
    return parts


def verse_lines(first_bar, section, lines):
    return [Part("lead", first_bar + 2 * i, text, mel, section=section) for i, (text, mel) in enumerate(lines)]


def pre_lines(first_bar, section, texts):
    mels = [
        "B3:2 B3:2 D4:2 C#4:2 B3:2 C#4:2 D4:4",
        "D4:2 D4:2 F#4:2 E4:2 F#4:2 E4:2 D4:4",
        "F#4:2 F#4:2 A4:2 A4:2 B4:2 A4:2 A4:4",
    ]
    parts = []
    for i, (text, mel) in enumerate(zip(texts, mels)):
        parts.append(Part("lead", first_bar + i, text, mel, section=section))
        parts.append(
            Part("double", first_bar + i, text, mel, section=section, gain=0.22, pan=0.35 if i % 2 else -0.35,
                 style={"seed": 7 + i}, display=False)
        )
    return parts


# Verse 1 is a trochaic chant (BUILD a START-up, MAKE it FLY): stresses on beats
# 2, 3 and 4, rhyme word on the next downbeat.
VERSE_1 = [
    ("Build a start-up, make it fly", "r4 C#4:2 C#4:2 E4:2 C#4:2 B3:2 A3:2 C#4:8 r8"),
    ("Worth a bil-lion by Ju-ly", "r4 B3:2 C#4:2 E4:2 C#4:2 B3:2 A3:2 A3:8 r8"),
    ("Make it pret-ty, make it scale", "r4 E4:2 E4:2 F#4:2 E4:2 C#4:2 B3:2 C#4:8 r8"),
    ("Get it right and nev-er fail", "r4 E4:2 E4:2 F#4:2 E4:2 D4:2 C#4:2 B3:8 r8"),
]

# Verse 2 is iambic (you're AB-so-LUTE-ly RIGHT, my BAD) with an eighth-note pickup.
VERSE_2 = [
    ("You're ab-so-lute-ly right, my bad", "r2 A3:2 C#4:2 B3:2 C#4:2 B3:2 A3:2 B3:2 C#4:8 r8"),
    ("I fixed the bug you nev-er had", "r2 A3:2 D4:2 C#4:2 D4:2 C#4:2 A3:2 B3:2 A3:8 r8"),
    ("The tests were red, I made them green", "r2 C#4:2 E4:2 C#4:2 B3:2 C#4:2 E4:2 F#4:2 A4:8 r8"),
    ("The clean-est build you've ev-er seen", "r2 B3:2 E4:2 D4:2 E4:2 D4:2 C#4:2 D4:2 B3:8 r8"),
]

# The bridge is half time: each line starts on an eighth-note pickup in the bar
# before, and its stresses fall on beats 1 and 3.
BRIDGE = [
    ("A bil-lion guess-es, wrong, wrong, wrong", "A3:2 D4:4 C#4:4 D4:4 E4:4 F#4:4 E4:4 D4:4 r4"),
    ("The loss came down, I learned this song", "C#4:2 E4:6 C#4:2 B3:6 C#4:2 E4:6 F#4:2 E4:4 r4"),
    ("Each per-fect note I've learned to sing", "B3:2 E4:6 D4:2 E4:6 F#4:2 G#4:6 F#4:2 G#4:4 r4"),
    ("Mis-takes have taught me ev-ery-thing", "A4:2 F#4:6 E4:2 E4:6 C#4:2 C#4:4 E4:2 F#4:4 r6"),
]

# Pronunciations for the TTS where its default does not fit the melody.
PRONOUNCE = {"everything": "ˈɛvɹiθˌɪŋ", "new": "nˈju"}

NATURAL = {"vibrato": 0.3, "glide": 0.06, "scoop": 0.5, "breath": 0.06}
ROBOT = {"monotone": 64, "formant": 1.08, "jitter": 0.0}
USER = {"length_scale": 0.9}


def build_parts():
    p = []
    # Intro: the prompt.
    p.append(Part("spoken", at(0, 1.2) / BAR, "Make me a music video.", voice="user", section="intro", style=USER))
    p.append(Part("spoken", at(1, 2.4) / BAR, "Make no mistakes.", voice="user", section="intro", style=USER))
    p.append(Part("robot", at(3, 0.6) / BAR, "On it.", voice="ai", section="intro", gain=0.8, style=ROBOT))

    p += verse_lines(4, "verse1", VERSE_1)
    p += pre_lines(12, "pre1", ["You're a sen-ior en-gi-neer", "Twen-ty years, the best one here",
                                "Step by step, I'll tip you well"])
    p.append(Part("spoken", at(15, 0.5) / BAR, "And make no mistakes.", voice="user", section="pre1", style=USER))
    p += chorus(16, "chorus1")
    p += post_chorus(24, "post1")

    p += verse_lines(28, "verse2", VERSE_2)
    p.append(Part("whisper", at(33, 2.0) / BAR, "I deleted them.", voice="lead", section="verse2", gain=0.9,
                  pan=0.15, style={"whisper": True, "length_scale": 0.9}))
    p += pre_lines(36, "pre2", ["Con-text win-dow fill-ing up", "Lost the plot, I'm out of luck",
                                "Can't re-call a word you said"])
    p.append(Part("robot", at(39, 0.0) / BAR, "I remember, make no mistakes.", voice="ai", section="pre2",
                  style={**ROBOT, "length_scale": 0.82}))
    p += chorus(40, "chorus2")
    p += post_chorus(48, "post2")

    for i, (text, mel) in enumerate(BRIDGE):
        p.append(Part("lead", 52 + 2 * i - 1 / 8, text, mel, section="bridge", style=dict(NATURAL)))
    p.append(Part("spoken", at(59, 2.3) / BAR, "So go on.", voice="lead", section="bridge", gain=0.8,
                  style={"length_scale": 0.8}))

    p += chorus(60, "final", tr=2, final=True)
    p += post_chorus(68, "outro", tr=2, word="new")[:2]
    p.append(Part("lead", 70, "Make new mis-takes", "A4:4 F#4:4 E4:2 F#4:22", section="outro", transpose=2,
                  style=dict(NATURAL)))

    p.append(Part("robot", at(72, 0.5) / BAR, "Music video complete.", voice="ai", section="tag", style=ROBOT))
    p.append(Part("robot", at(73, 0.3) / BAR, "Zero mistakes.", voice="ai", section="tag", style=ROBOT))
    p.append(Part("spoken", at(74, 0.0) / BAR, "There's a typo in the title.", voice="user", section="tag", style=USER))
    p.append(Part("robot", at(75, 0.0) / BAR, "You're absolutely right!", voice="ai", section="tag",
                  style={**ROBOT, "monotone": 67}))
    return p


# Prompts typed into the on-screen terminal: (start time, text, seconds per character).
TYPING = [
    (0.30, "make me a music video.", 0.042),
    (2.85, "make no mistakes.", 0.045),
    (147.30, "there's a typo in the title.", 0.034),
]

NOTE_BASE = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def note_midi(name):
    pc = NOTE_BASE[name[0]]
    rest = name[1:]
    while rest and rest[0] in "#b":
        pc += 1 if rest[0] == "#" else -1
        rest = rest[1:]
    return 12 * (int(rest) + 1) + pc


def syllables(text):
    return [s for word in text.replace(",", "").replace("!", "").replace(".", "").split() for s in word.split("-")]


def words(text):
    return [w.replace("-", "") for w in text.split()]


def parse_melody(part):
    """List (one per syllable) of [(start_s, dur_s, midi)] for a sung part."""
    t = part.bar * BAR
    out = []
    for tok in part.melody.split():
        if tok.startswith("r"):
            t += int(tok[1:]) * S16
            continue
        pitch, d = tok.split(":")
        d = int(d) * S16
        cont = pitch.startswith("~")
        m = note_midi(pitch.lstrip("~")) + part.transpose + KEY
        if cont:
            out[-1].append((t, d, m))
        else:
            out.append([(t, d, m)])
        t += d
    return out


def tts_text(text):
    return text.replace("-", "")


CHORD_PCS = {"": (0, 4, 7), "m": (0, 3, 7)}


def chord_notes(symbol, tr=0):
    """Root pitch class and chord tones (pitch classes) of a symbol like F#m."""
    root = symbol[0]
    rest = symbol[1:]
    pc = NOTE_BASE[root]
    if rest.startswith("#"):
        pc += 1
        rest = rest[1:]
    elif rest.startswith("b"):
        pc -= 1
        rest = rest[1:]
    pc = (pc + tr) % 12
    return pc, [(pc + i) % 12 for i in CHORD_PCS[rest]]
