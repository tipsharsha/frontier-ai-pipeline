#!/usr/bin/env bash
# Download the Piper voices used by build_audio.py into ./voices.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p voices
base=https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US
for v in ljspeech/high/en_US-ljspeech-high bryce/medium/en_US-bryce-medium; do
  name=$(basename "$v")
  curl -fsSL -o "voices/$name.onnx" "$base/$v.onnx"
  curl -fsSL -o "voices/$name.onnx.json" "$base/$v.onnx.json"
done
