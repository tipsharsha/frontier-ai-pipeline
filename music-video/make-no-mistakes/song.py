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
BACKING_E = "B4:1 B4:1 B4:1 B4:2 G#4:1 B4:2"
BACKING_FM = "C#5:1 C#5:1 C#5:1 C#5:2 A4:1 C#5:2"
SHIP = "F#4:2 F#4:2 E4:2 F#4:6 E4:2 F#4:2 E4:2 C#4:2 E4:12"
SHIP_HARM = "C#4:2 C#4:2 C#4:2 C#4:6 C#4:2 D4:2 C#4:2 A3:2 C#4:12"
SHOT = "A4:4 F#4:4 E4:2 F#4:2 A4:4 B4:12 r4"
SHOT_HARM = "F#4:4 D4:4 C#4:2 D4:2 F#4:4 G#4:12 r4"
CHOP = "A4:2 F#4:2 r2 A4:2 F#4:2 r2 A4:2 F#4:2 E4:2 F#4:10 r4"


def chorus(first_bar, section, tr=0, final=False):
    word = "new" if final else "no"
    l2 = "Break it to-night, what-ev-er it takes" if final else "Ship it to-night, what-ev-er it takes"
    l3 = "Learn fast, for heav-en's sake" if final else "One shot, for heav-en's sake"
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
    # The robot's reply fills the gap after the hook, ending a beat before the next line.
    for off, mel in ((1, BACKING_E), (7, BACKING_FM)):
        parts.append(
            Part("backing", first_bar + off + 0.375, "You're ab-so-lute-ly right!", mel, voice="ai",
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


VERSE_1 = [
    ("Build me a start-up, make it worth a bil-lion",
     "r2 A3:2 A3:2 A3:2 C#4:2 B3:4 A3:2 A3:2 C#4:2 B3:2 A3:2 F#3:6 r2"),
    ("Fix ev-ery bug, I think there's like a mil-lion",
     "r2 A3:2 A3:2 A3:2 D4:4 C#4:2 A3:2 A3:2 D4:2 C#4:2 A3:2 F#3:6 r2"),
    ("Make it pret-ty, make it fast, make it scale",
     "C#4:2 C#4:2 E4:2 C#4:2 C#4:2 C#4:2 E4:4 E4:2 E4:2 C#4:8 r4"),
    ("Get it right on the first try, nev-er fail",
     "B3:2 B3:2 E4:2 D4:2 C#4:2 B3:2 G#3:4 B3:2 C#4:2 B3:8 r4"),
]

VERSE_2 = [
    ("You're ab-so-lute-ly right, I see it now",
     "A3:2 A3:2 A3:2 C#4:2 B3:2 A3:4 r2 A3:2 C#4:2 B3:2 F#3:6 r4"),
    ("I fixed the bug, don't ask me how",
     "r2 A3:2 A3:2 A3:2 D4:4 r2 D4:2 C#4:2 A3:2 A3:8 r4"),
    ("The tests were red, I made them green",
     "C#4:2 C#4:2 C#4:2 E4:4 C#4:2 C#4:2 C#4:2 E4:6 r10"),
    ("The clean-est build you've ev-er seen",
     "B3:2 E4:2 D4:2 B3:4 r2 B3:2 C#4:2 B3:2 B3:10 r4"),
]

BRIDGE = [
    ("Fun-ny thing a-bout the way I'm made", "A3:2 A3:2 D4:4 C#4:2 D4:2 E4:2 F#4:2 E4:2 D4:10 r4"),
    ("A bil-lion guess-es, wrong in ev-ery way", "C#4:2 C#4:2 E4:4 E4:2 C#4:2 E4:4 C#4:2 B3:2 A3:2 A3:8 r2"),
    ("The loss came down, I learned to sing", "B3:2 E4:4 E4:2 G#4:4 F#4:4 E4:4 F#4:2 G#4:10"),
    ("Mis-takes taught me ev-ery-thing", "A4:2 F#4:6 E4:4 C#4:4 C#4:2 E4:2 F#4:4 r8"),
]

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
    p.append(Part("whisper", at(32, 5.6) / BAR, "I deleted them.", voice="lead", section="verse2", gain=0.9,
                  pan=0.15, style={"whisper": True}))
    p += pre_lines(36, "pre2", ["Con-text win-dow fill-ing up", "Lost the plot, I'm out of luck",
                                "Can't re-call a word you said"])
    p.append(Part("robot", at(39, 0.0) / BAR, "I remember, make no mistakes.", voice="ai", section="pre2",
                  style={**ROBOT, "length_scale": 0.82}))
    p += chorus(40, "chorus2")
    p += post_chorus(48, "post2")

    for i, (text, mel) in enumerate(BRIDGE):
        p.append(Part("lead", 52 + 2 * i, text, mel, section="bridge", style=dict(NATURAL)))
    p.append(Part("spoken", at(59, 2.2) / BAR, "So go on.", voice="lead", section="bridge", gain=0.8))

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
