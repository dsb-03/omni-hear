#!/bin/bash
# Sets up a development environment for running omnihear from this checkout
# (Linux), next to an installed .deb without touching it: a .venv in the repo
# with the same deps the .deb's postinst installs, plus (optionally) the
# PyTorch stack for the Indic speech engine. Safe to re-run.
#
# Usage: ./scripts/dev-setup.sh [--indic] [--cpu | --gpu] [--gguf [--vulkan] [MODEL.gguf]]
#   --indic   also install the Indic engine deps (torch, transformers, ...)
#             and log in to Hugging Face (the models are gated)
#   --cpu     CPU-only PyTorch (default when no NVIDIA GPU is found; much
#             smaller download)
#   --gpu     CUDA PyTorch (default when nvidia-smi finds a GPU)
#   --gguf    for an Indic-Transcribe .gguf instead (no PyTorch): clone
#             transcribe.cpp with its Indic-Transcribe PR into
#             .transcribe.cpp/, build the shared library (CUDA if nvcc is
#             found) and install its Python bindings into .venv
#   --vulkan  with --gguf: build the Vulkan GPU backend (AMD/Intel GPUs;
#             needs libvulkan-dev + glslc)
#   MODEL.gguf  path to your downloaded .gguf (implies --gguf); used for the
#             setup checks and the printed run command
#
# Then run it with ./scripts/dev-run.sh
set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$REPO_ROOT/.venv"
PIP="$VENV/bin/pip"
INDIC=0
TORCH=""
GGUF=0
VULKAN=0
TCPP="$REPO_ROOT/.transcribe.cpp"
TCPP_PR=245   # handy-computer/transcribe.cpp: Indic-Transcribe output modes
GGUF_MODEL=""

for arg in "$@"; do
    case "$arg" in
        --indic) INDIC=1 ;;
        --cpu) TORCH=cpu ;;
        --gpu) TORCH=gpu ;;
        --gguf) GGUF=1 ;;
        --vulkan) VULKAN=1 ;;
        *.gguf|*.GGUF) GGUF=1; GGUF_MODEL="$(realpath "$arg")" ;;
        -h|--help) sed -n '2,24p' "$0"; exit 0 ;;
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

if [ "$GGUF" = 1 ]; then
    for tool in git cmake c++; do
        command -v "$tool" >/dev/null 2>&1 || {
            echo "$tool not found — sudo apt install git cmake build-essential" >&2
            exit 1
        }
    done
    if [ ! -d "$TCPP/.git" ]; then
        echo "==> Cloning transcribe.cpp into $TCPP"
        git clone --quiet https://github.com/handy-computer/transcribe.cpp "$TCPP"
    fi
    echo "==> Updating transcribe.cpp to PR #$TCPP_PR (Indic-Transcribe)"
    git -C "$TCPP" fetch --quiet origin "pull/$TCPP_PR/head:indic-pr" --force
    git -C "$TCPP" checkout --quiet indic-pr
    FLAGS=(-DTRANSCRIBE_BUILD_SHARED=ON -DTRANSCRIBE_BUILD_TESTS=OFF
           -DTRANSCRIBE_BUILD_TOOLS=ON -DCMAKE_BUILD_TYPE=Release)
    if [ "$VULKAN" = 1 ]; then
        FLAGS+=(-DTRANSCRIBE_VULKAN=ON)
        echo "==> Building with Vulkan"
    elif command -v nvcc >/dev/null 2>&1; then
        FLAGS+=(-DTRANSCRIBE_CUDA=ON)
        echo "==> Building with CUDA (nvcc found)"
    else
        echo "==> Building for CPU (add --vulkan for an AMD/Intel GPU)"
    fi
    cmake -S "$TCPP" -B "$TCPP/build" "${FLAGS[@]}" > "$TCPP/build.log" 2>&1 || {
        echo "cmake failed — see $TCPP/build.log" >&2; exit 1; }
    cmake --build "$TCPP/build" -j"$(nproc)" >> "$TCPP/build.log" 2>&1 || {
        echo "build failed — see $TCPP/build.log" >&2; exit 1; }
    echo "==> Installing transcribe.cpp's Python bindings into .venv"
    "$PIP" install --quiet "$TCPP/bindings/python"
    TCPP_LIB="$TCPP/build/src/libtranscribe.so"
    [ -f "$TCPP_LIB" ] || TCPP_LIB="$(find "$TCPP/build" -name libtranscribe.so | head -1)"
    echo
    echo "transcribe.cpp library: $TCPP_LIB"
    echo "CLI (test a .wav):      $TCPP/build/bin/transcribe-cli"
    echo "quantize (e.g. Q8_0 -> Q5_K_M): $TCPP/build/bin/transcribe-quantize"
fi

echo
echo "==> Setup checks"
cd "$REPO_ROOT/src"
if [ "$GGUF" = 1 ]; then
    "$VENV/bin/python3" -m omnihear --asr-backend indic --language hi \
        --indic-model "${GGUF_MODEL:-/path/to/model.gguf}" \
        --indic-library "$TCPP_LIB" --doctor || true
elif [ "$INDIC" = 1 ]; then
    "$VENV/bin/python3" -m omnihear --asr-backend indic --doctor || true
else
    "$VENV/bin/python3" -m omnihear --doctor || true
fi

echo
echo "Done. Run omnihear from this checkout with:"
if [ "$GGUF" = 1 ]; then
    echo "  ./scripts/dev-run.sh --asr-backend indic --language hi \\"
    echo "      --indic-model ${GGUF_MODEL:-/path/to/indic_transcribe_flex-q5_k_m.gguf} \\"
    echo "      --indic-library $TCPP_LIB"
elif [ "$INDIC" = 1 ]; then
    echo "  ./scripts/dev-run.sh --asr-backend indic"
else
    echo "  ./scripts/dev-run.sh"
fi
