# Make No Mistakes

An original song and music video about the "make no mistakes" prompt meme, in two
versions that share one animation:

- **Synthesized** (2:35): the lyrics, music, vocals and animation are all generated
  by the code in this folder; no samples, stock footage or music models are used.
- **Sung**: the same lyrics sung by [Suno](https://suno.com) from
  [SUNO_PROMPT.md](SUNO_PROMPT.md), with the video re-timed to that take
  ([below](#sung-version-suno)).

Both are 1920×1080 at 30 fps. Lyrics: [LYRICS.md](LYRICS.md)

## How it is made

| File | Role |
| --- | --- |
| `song.py` | The score: sections, chords, hyphenated lyrics and melodies on a sixteenth-note grid. |
| `singer.py` | The singing voice. A TTS voice (Kokoro, or Piper) speaks each line and reports when every phoneme starts and ends; the WORLD vocoder puts every vowel on its beat, stretches it to the note length and replaces the pitch with the melody (with glides, vibrato and doubles). |
| `synth.py` | A small numpy/numba synthesizer: drums, bass, supersaw pads, plucks, an FM electric piano, risers, reverb, delay, compression and a limiter. |
| `build_audio.py` | Arranges the instruments, produces and mixes the vocals, masters the song, and exports the per-word lyric timings and audio features that drive the picture. |
| `visuals/video.js` | The video. Every frame is a pure function of time on a 2D canvas, cut to the same word timings, kicks and snares as the audio. |
| `render_video.mjs` | Renders the frames in headless Chromium and muxes them with the song using ffmpeg. |
| `suno_sync.py` | For the sung version: finds when each word is sung in a Suno take and where its bars fall, and writes the same timing and feature files. |

## Rebuild

Kokoro needs Python 3.10–3.12.

```sh
python3.12 -m venv .venv && . .venv/bin/activate
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
python build_audio.py        # build/song.wav, timing.json, features.json
npm install playwright && npx playwright install chromium
node render_video.mjs        # build/make-no-mistakes.mp4
```

The first run downloads the Kokoro model from Hugging Face. Vocal renders are
cached per part in `build/vocals.pkl` (pass `--fresh-vocals` to redo them all).
`node render_video.mjs --sheet 33,45,120` writes a contact sheet of those moments,
and `--still 33` a single full-size frame.

## Voices

Both voices are from [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M)
(Apache-2.0): `af_heart` sings and voices the AI's asides, and `am_michael` is the
person typing the prompts. `VOICES` in `build_audio.py` picks them; Piper models
also work, e.g. `piper:en_US-ljspeech-high` with the model in `./voices`.
Everything else is synthesized from scratch.

For a real singing voice, see the sung version below.

## Sung version (Suno)

1. Generate the song in Suno's Custom mode with [SUNO_PROMPT.md](SUNO_PROMPT.md)
   and download it (WAV if your plan has it; MP3 works).
2. Isolate the vocal with
   [audio-separator](https://github.com/nomadkaraoke/python-audio-separator). It
   needs NumPy 2, so give it its own environment:

   ```sh
   python3 -m venv .venv-sep && .venv-sep/bin/pip install "audio-separator[cpu]"
   .venv-sep/bin/audio-separator take.wav -m Kim_Vocal_2.onnx --single_stem Vocals \
       --output_format WAV --output_dir build/suno/stems
   ```

3. Sync and render, in the main environment:

   ```sh
   pip install -r requirements-suno.txt
   python suno_sync.py take.wav --vocals "build/suno/stems/take_(Vocals)_Kim_Vocal_2.wav"
   BUILD_DIR=build/suno node render_video.mjs
   ```

`suno_sync.py` finds the words with forced alignment: Whisper large-v3-turbo
transcribes the vocal to locate each section, then wav2vec2 aligns the known
lyrics inside it letter by letter. It tracks every beat rather than assuming a
grid, since Suno's tempo drifts (124 to 130 BPM in this take), and voices the typed
prompt before the take and the typo tag after it in the same Kokoro voices.

Suno improvises around the lyrics it is given. `TAKE` at the top of the script
lists what this take sings in each section and the bar each section starts on, so
a different take needs that list checked against what it actually sings.
