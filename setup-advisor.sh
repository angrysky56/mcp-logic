#!/usr/bin/env bash
# setup-advisor.sh — Install the onboard logic advisor (TwIL-LM3)
#
# Auto-detects platform and GPU, installs llama-cpp-python with the
# appropriate acceleration backend (CUDA/Metal/CPU), plus huggingface-hub.
#
# Usage:
#   ./setup-advisor.sh          # auto-detect everything
#   ./setup-advisor.sh --cpu    # force CPU-only (no GPU acceleration)
#   ./setup-advisor.sh --skip-download  # install deps but don't download model

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${GREEN}[ADVISOR SETUP]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARNING]${NC} $1"; }
err()   { echo -e "${RED}[ERROR]${NC} $1"; }
step()  { echo -e "${CYAN}→${NC} $1"; }

FORCE_CPU=false
SKIP_DOWNLOAD=false

for arg in "$@"; do
    case "$arg" in
        --cpu)           FORCE_CPU=true ;;
        --skip-download) SKIP_DOWNLOAD=true ;;
        -h|--help)
            echo "Usage: $0 [--cpu] [--skip-download]"
            echo "  --cpu            Force CPU-only (no GPU acceleration)"
            echo "  --skip-download  Install deps only, skip model download"
            exit 0
            ;;
    esac
done

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"

# ── Step 1: Detect platform and GPU ────────────────────────────────────
info "Detecting platform..."

OS="$(uname -s)"
ARCH="$(uname -m)"
CMAKE_ARGS=""
ACCEL_NAME="CPU (no acceleration)"

if [ "$FORCE_CPU" = true ]; then
    step "CPU-only mode forced via --cpu flag"
elif [ "$OS" = "Darwin" ]; then
    # macOS — use Metal on Apple Silicon
    if [ "$ARCH" = "arm64" ]; then
        CMAKE_ARGS="-DGGML_METAL=on"
        ACCEL_NAME="Metal (Apple Silicon)"
        step "Detected macOS Apple Silicon → Metal acceleration"
    else
        CMAKE_ARGS="-DGGML_METAL=on"
        ACCEL_NAME="Metal (Intel Mac)"
        step "Detected macOS Intel → Metal acceleration (limited)"
    fi
elif [ "$OS" = "Linux" ]; then
    if command -v nvidia-smi &>/dev/null; then
        CMAKE_ARGS="-DGGML_CUDA=on"
        ACCEL_NAME="CUDA (NVIDIA GPU)"
        GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1)
        step "Detected NVIDIA GPU: ${GPU_NAME:-unknown} → CUDA acceleration"
    else
        step "No NVIDIA GPU detected → CPU-only mode"
    fi
else
    step "Unknown platform ($OS) → CPU-only mode"
fi

info "Acceleration: ${ACCEL_NAME}"

# ── Step 2: Check for uv ───────────────────────────────────────────────
if ! command -v uv &>/dev/null; then
    err "'uv' is not installed. Install it first:"
    echo "  curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

# ── Step 3: Ensure venv exists ─────────────────────────────────────────
if [ ! -d "${PROJECT_DIR}/.venv" ]; then
    info "Creating virtual environment..."
    uv venv --directory "${PROJECT_DIR}"
fi

# ── Step 4: Install llama-cpp-python ───────────────────────────────────
info "Installing llama-cpp-python (this may take a few minutes to compile)..."
step "CMAKE_ARGS=\"${CMAKE_ARGS:-<none>}\""

if [ -n "$CMAKE_ARGS" ]; then
    # --no-binary is REQUIRED: without it uv installs the prebuilt CPU-only
    # wheel from PyPI and CMAKE_ARGS is silently ignored, so the advisor runs
    # on CPU while the script claims GPU acceleration.
    warn "Building llama-cpp-python from source — this takes 10-20 minutes."
    CMAKE_ARGS="$CMAKE_ARGS" uv pip install \
        --directory "${PROJECT_DIR}" \
        --reinstall-package llama-cpp-python \
        --no-binary llama-cpp-python \
        "llama-cpp-python>=0.3.0"
else
    uv pip install \
        --directory "${PROJECT_DIR}" \
        --reinstall-package llama-cpp-python \
        "llama-cpp-python>=0.3.0"
fi

# ── Step 4b: Verify the acceleration we claimed actually got compiled ──
if [ -n "$CMAKE_ARGS" ]; then
    if uv run --directory "${PROJECT_DIR}" python -c \
        "from llama_cpp import llama_cpp as c; raise SystemExit(0 if c.llama_supports_gpu_offload() else 1)" \
        2>/dev/null; then
        info "Verified: GPU offload is compiled in."
    else
        warn "GPU offload is NOT available in the installed build — the"
        warn "advisor will run on CPU (roughly 10x slower). Check the build"
        warn "log above for compiler errors, and that nvcc is on your PATH."
    fi
fi

# ── Step 5: Install huggingface-hub ────────────────────────────────────
info "Installing huggingface-hub..."
uv pip install --directory "${PROJECT_DIR}" "huggingface-hub>=0.24.0"

# ── Step 6: Download model (optional) ─────────────────────────────────
MODEL_DIR="${HOME}/.cache/mcp-logic/models"
MODEL_FILE="${MODEL_DIR}/TwIL-LM3-Q8_0.gguf"

if [ "$SKIP_DOWNLOAD" = true ]; then
    warn "Skipping model download (--skip-download). Model will auto-download on first use."
elif [ -f "$MODEL_FILE" ]; then
    info "Model already downloaded: ${MODEL_FILE}"
else
    info "Downloading TwIL-LM3-Q8_0.gguf (~3.3 GB)..."
    step "Destination: ${MODEL_DIR}/"
    mkdir -p "${MODEL_DIR}"
    uv run --directory "${PROJECT_DIR}" python -c "
from huggingface_hub import hf_hub_download
hf_hub_download(
    repo_id='webAI-Official/TwIL-LM3',
    filename='TwIL-LM3-Q8_0.gguf',
    local_dir='${MODEL_DIR}',
)
print('Download complete!')
"
fi

# ── Done ───────────────────────────────────────────────────────────────
echo ""
info "✅ Logic advisor setup complete!"
echo ""
echo "  Acceleration:  ${ACCEL_NAME}"
if [ -f "$MODEL_FILE" ]; then
    echo "  Model:         ${MODEL_FILE}"
else
    echo "  Model:         Will auto-download on first use"
fi
echo ""
echo "  The advisor is now available as the 'ask_logic_advisor' MCP tool."
echo "  To disable it, add --no-advisor when starting the server."
echo ""
