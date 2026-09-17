#!/usr/bin/env bash
# Install ComfyUI + deps for MiniMax H3 on a Vast.ai PyTorch instance.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
[[ -f "${ROOT}/.env" ]] && source "${ROOT}/.env"
# shellcheck disable=SC1091
source "${ROOT}/.env.example"

COMFYUI_DIR="${COMFYUI_DIR:-/workspace/ComfyUI}"
COMFYUI_REF="${COMFYUI_REF:-v0.36.0}"
PROFILE="${PROFILE:-standard}"

source /venv/main/bin/activate

echo "=== GPU / torch check ==="
python - <<'PY'
import torch
print("torch", torch.__version__, "cuda", torch.version.cuda, "avail", torch.cuda.is_available())
if torch.cuda.is_available():
    print("gpu", torch.cuda.get_device_name(0), "vram_gb", round(torch.cuda.get_device_properties(0).total_memory/1e9,1))
PY

echo "=== Clone / update ComfyUI (${COMFYUI_REF}) ==="
if [[ ! -d "${COMFYUI_DIR}/.git" ]]; then
  git clone --depth 1 --branch "${COMFYUI_REF}" https://github.com/comfyanonymous/ComfyUI.git "${COMFYUI_DIR}"
else
  git -C "${COMFYUI_DIR}" fetch --depth 1 origin "refs/tags/${COMFYUI_REF}:refs/tags/${COMFYUI_REF}" || true
  git -C "${COMFYUI_DIR}" checkout "${COMFYUI_REF}" || true
fi

echo "=== Python deps ==="
cd "${COMFYUI_DIR}"
uv pip install -r requirements.txt
# Helpful extras for H3 / video
uv pip install "huggingface_hub[cli]" imageio-ffmpeg av sageattention || \
  uv pip install "huggingface_hub[cli]" imageio-ffmpeg av
# ComfyUI-Manager (optional but useful)
mkdir -p "${COMFYUI_DIR}/custom_nodes"
if [[ ! -d "${COMFYUI_DIR}/custom_nodes/ComfyUI-Manager" ]]; then
  git clone --depth 1 https://github.com/ltdrdata/ComfyUI-Manager.git \
    "${COMFYUI_DIR}/custom_nodes/ComfyUI-Manager" || true
fi

# Install prompt-writing skill docs from official MiniMax-H3 (no weights)
if [[ ! -d /workspace/MiniMax-H3/.git ]]; then
  git clone --depth 1 https://github.com/MiniMax-AI/MiniMax-H3.git /workspace/MiniMax-H3 || true
fi
mkdir -p "${ROOT}/docs"
if [[ -d /workspace/MiniMax-H3/skills/h3-prompt-writing ]]; then
  cp -a /workspace/MiniMax-H3/skills/h3-prompt-writing "${ROOT}/docs/" 2>/dev/null || true
fi

# Seed workflows into ComfyUI user folder
mkdir -p "${COMFYUI_DIR}/user/default/workflows"
cp -f "${ROOT}/workflows/"*.json "${COMFYUI_DIR}/user/default/workflows/" 2>/dev/null || true

echo "=== Download models (PROFILE=${PROFILE}) ==="
bash "${ROOT}/scripts/download_models.sh"

echo "=== Install finished ==="
echo "Next: bash ${ROOT}/scripts/setup_vast_service.sh"
