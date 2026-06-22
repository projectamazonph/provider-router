#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# setup_local_llm.sh — Download Gemma 3 4B and start llama-server
# ─────────────────────────────────────────────────────────────────────────────
set -e

MODEL_DIR="/root/hermes/workspace/projects/provider-router/models"
MODEL_FILE="gemma-3-4b-it-Q4_K_M.gguf"
MODEL_URL="https://huggingface.co/bartowski/gemma-3-4b-it-GGUF/resolve/main/gemma-3-4b-it-Q4_K_M.gguf"
SERVER_PORT=8080
CONTEXT_SIZE=8192

mkdir -p "$MODEL_DIR"

# Check if model already exists
if [ -f "$MODEL_DIR/$MODEL_FILE" ]; then
    SIZE=$(du -h "$MODEL_DIR/$MODEL_FILE" | cut -f1)
    echo "✅ Model already exists: $MODEL_DIR/$MODEL_FILE ($SIZE)"
else
    echo "📥 Downloading Gemma 3 4B Q4_K_M (~2.5GB)..."
    echo "   URL: $MODEL_URL"
    echo "   Destination: $MODEL_DIR/$MODEL_FILE"
    echo ""
    echo "   This will take a few minutes on Android..."
    
    # Try huggingface-cli first, fall back to wget
    if command -v huggingface-cli &>/dev/null; then
        huggingface-cli download bartowski/gemma-3-4b-it-GGUF "$MODEL_FILE" \
            --local-dir "$MODEL_DIR" --local-dir-use-symlinks False
    else
        wget -O "$MODEL_DIR/$MODEL_FILE" "$MODEL_URL" --progress=bar:force 2>&1
    fi
    
    echo "✅ Download complete!"
fi

# Check if llama-server is available
if ! command -v llama-server &>/dev/null; then
    echo "⚠️  llama-server not found in PATH"
    echo "   Will use Python llama-cpp-python as fallback"
    
    # Start via Python
    python3 -c "
from llama_cpp import Llama
import sys
print('Loading model...')
llm = Llama(
    model_path='$MODEL_DIR/$MODEL_FILE',
    n_ctx=$CONTEXT_SIZE,
    n_threads=4,
    n_gpu_layers=0,
    verbose=False
)
print('Model loaded. Starting OpenAI-compatible server...')
# Note: llama-cpp-python doesn't have a built-in server
# We'll use the llama-server binary instead
" 2>&1 || echo "Python fallback not available either"
    
    echo ""
    echo "⚠️  You need llama-server binary. Install via:"
    echo "   git clone https://github.com/ggml-org/llama.cpp"
    echo "   cd llama.cpp && cmake -B build && cmake --build build --config Release"
    echo "   Then run: ./build/bin/llama-server -m $MODEL_DIR/$MODEL_FILE --port $SERVER_PORT -c $CONTEXT_SIZE"
    exit 1
fi

# Start llama-server
echo "🚀 Starting llama-server on port $SERVER_PORT..."
echo "   Model: $MODEL_DIR/$MODEL_FILE"
echo "   Context: $CONTEXT_SIZE tokens"
echo "   URL: http://localhost:$SERVER_PORT"
echo ""
echo "   Press Ctrl+C to stop"
echo ""

llama-server \
    -m "$MODEL_DIR/$MODEL_FILE" \
    --port "$SERVER_PORT" \
    --host 0.0.0.0 \
    -c "$CONTEXT_SIZE" \
    -t 4 \
    --cont-batching \
    --log-disable
