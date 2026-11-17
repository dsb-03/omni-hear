#!/bin/bash
# Sets up a development environment for running omnihear from this checkout
# (Linux), next to an installed .deb without touching it: a .venv in the repo
# with the same deps the .deb's postinst installs, plus (optionally) the
# PyTorch stack for the Indic speech engine. Safe to re-run.
#
# Usage: ./scripts/dev-setup.sh [--indic] [--cpu | --gpu]
#   --indic   also install the Indic engine deps (torch, transformers, ...)
#             and log in to Hugging Face (the models are gated)
#   --cpu     CPU-only PyTorch (default when no NVIDIA GPU is found; much
#             smaller download)
#   --gpu     CUDA PyTorch (default when nvidia-smi finds a GPU)
#
# Then run it with ./scripts/dev-run.sh
set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$REPO_ROOT/.venv"
PIP="$VENV/bin/pip"
INDIC=0
TORCH=""

for arg in "$@"; do
    case "$arg" in
        --indic) INDIC=1 ;;
        --cpu) TORCH=cpu ;;
        --gpu) TORCH=gpu ;;
        -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
        *) echo "unknown option: $arg (see --help)" >&2; exit 2 ;;
    esac
done

python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' || {
    echo "omnihear needs Python 3.11+ (found $(python3 --version 2>&1))" >&2
    exit 1
}

if [ ! -x "$VENV/bin/python3" ]; then
    echo "==> Creating $VENV"
    python3 -m venv "$VENV" || {
        echo "venv creation failed — sudo apt install python3-venv" >&2
        exit 1
    }
fi
"$PIP" install --quiet --upgrade pip

echo "==> Installing omnihear's dependencies"
# Same as DEBIAN-template/postinst: pynput without its evdev dependency
# (no wheels, needs a compiler; only pynput's X11 backend is used).
grep -viE '^\s*pynput' "$REPO_ROOT/src/requirements.txt" > "$VENV/.requirements-dev.txt"
"$PIP" install --quiet -r "$VENV/.requirements-dev.txt"
"$PIP" install --quiet six python-xlib
"$PIP" install --quiet --no-deps pynput
rm -f "$VENV/.requirements-dev.txt"

if [ "$INDIC" = 1 ]; then
    if [ -z "$TORCH" ]; then
        if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L >/dev/null 2>&1; then
            TORCH=gpu
        else
            TORCH=cpu
        fi
    fi
    if [ "$TORCH" = cpu ]; then
        echo "==> Installing CPU-only PyTorch"
        "$PIP" install --quiet torch torchaudio \
            --index-url https://download.pytorch.org/whl/cpu
    else
        echo "==> Installing PyTorch with CUDA (a few GB)"
        "$PIP" install --quiet torch torchaudio
    fi
    echo "==> Installing transformers, sentencepiece, soundfile, huggingface_hub"
    "$PIP" install --quiet transformers sentencepiece soundfile huggingface_hub

    if [ -n "$HF_TOKEN" ] || [ -f "${HF_HOME:-$HOME/.cache/huggingface}/token" ]; then
        echo "==> Hugging Face token found"
    else
        echo
        echo "The Indic-Transcribe models are gated. First accept the license at"
        echo "  https://huggingface.co/bodhan-ai/indic-transcribe-flex"
        echo "then paste an access token (huggingface.co/settings/tokens, 'Read')."
        "$VENV/bin/hf" auth login || \
            echo "(login skipped — run $VENV/bin/hf auth login later)"
    fi
fi

echo
echo "==> Setup checks"
cd "$REPO_ROOT/src"
if [ "$INDIC" = 1 ]; then
    "$VENV/bin/python3" -m omnihear --asr-backend indic --doctor || true
else
    "$VENV/bin/python3" -m omnihear --doctor || true
fi

echo
echo "Done. Run omnihear from this checkout with:"
if [ "$INDIC" = 1 ]; then
    echo "  ./scripts/dev-run.sh --asr-backend indic"
else
    echo "  ./scripts/dev-run.sh"
fi
