#!/bin/bash
# Free, private LLM endpoint for development: llama.cpp's OpenAI-compatible server on CPU.
#
# The application only speaks the OpenAI-compatible chat API (through LiteLLM, see
# config/models.yaml), so this dev server is interchangeable with what a company would run:
# vLLM or TGI on a GPU, or a managed endpoint in its own cloud tenant (docs/HANDOFF.md §2).
#
# First run: builds llama-server from a pinned release tag and downloads the model weights
# from Hugging Face (about 4.7 GB, two shards). Later runs start in seconds. Everything lives under
# $AVANT_OFFRE_TOOLS (default ~/.cache/avant-offre), outside the repository.
#
#   scripts/llm_local.sh            # build if needed, download if needed, serve on :8080
#   scripts/llm_local.sh --prepare  # build and download only (CI images, slow networks)
set -euo pipefail

TOOLS="${AVANT_OFFRE_TOOLS:-$HOME/.cache/avant-offre}"
LLAMA_CPP_TAG="${LLAMA_CPP_TAG:-b11699}"
MODEL_REPO="${LLM_MODEL_REPO:-Qwen/Qwen2.5-7B-Instruct-GGUF}"
MODEL_FILE="${LLM_MODEL_FILE:-qwen2.5-7b-instruct-q4_k_m-00001-of-00002.gguf}"
MODEL_ALIAS="${LLM_MODEL_ALIAS:-qwen2.5-7b-instruct}"  # the name config/models.yaml uses
PORT="${LLM_PORT:-8080}"
CONTEXT="${LLM_CONTEXT:-8192}"

SRC="$TOOLS/llama.cpp-$LLAMA_CPP_TAG"
SERVER="$SRC/build/bin/llama-server"
MODEL="$TOOLS/models/$MODEL_FILE"

if [ ! -x "$SERVER" ]; then
  echo "building llama-server $LLAMA_CPP_TAG in $SRC" >&2
  mkdir -p "$TOOLS"
  [ -d "$SRC" ] || git clone --depth 1 --branch "$LLAMA_CPP_TAG" \
    https://github.com/ggml-org/llama.cpp "$SRC"
  cmake -S "$SRC" -B "$SRC/build" -DCMAKE_BUILD_TYPE=Release -DLLAMA_CURL=OFF \
    -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=OFF >&2
  cmake --build "$SRC/build" --target llama-server -j "$(nproc)" >&2
fi

# Large models are split in shards (name-00001-of-00003.gguf): fetch every shard, load the first.
FILES=("$MODEL_FILE")
if [[ "$MODEL_FILE" =~ ^(.*)-00001-of-([0-9]{5})\.gguf$ ]]; then
  FILES=()
  for ((i = 1; i <= 10#${BASH_REMATCH[2]}; i++)); do
    FILES+=("$(printf '%s-%05d-of-%s.gguf' "${BASH_REMATCH[1]}" "$i" "${BASH_REMATCH[2]}")")
  done
fi
mkdir -p "$TOOLS/models"
for f in "${FILES[@]}"; do
  if [ ! -f "$TOOLS/models/$f" ]; then
    echo "downloading $MODEL_REPO/$f" >&2
    curl -fL --retry 5 --retry-delay 5 -C - -o "$TOOLS/models/$f.part" \
      "https://huggingface.co/$MODEL_REPO/resolve/main/$f"
    mv "$TOOLS/models/$f.part" "$TOOLS/models/$f"
  fi
done

if [ "${1:-}" = "--prepare" ]; then
  echo "ready: $SERVER, $MODEL" >&2
  exit 0
fi

# One request at a time on a small CPU box; raise --parallel on bigger hosts.
exec "$SERVER" -m "$MODEL" --alias "$MODEL_ALIAS" --host 127.0.0.1 --port "$PORT" \
  -c "$CONTEXT" -t "$(nproc)" --parallel 1
