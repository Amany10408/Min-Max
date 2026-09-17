#!/usr/bin/env bash
# Download MiniMax H3 weights for ComfyUI into $COMFYUI_DIR/models
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
[[ -f "${ROOT}/.env" ]] && set -a && source "${ROOT}/.env" && set +a
# Defaults from example (do not override already-set env)
set -a
# shellcheck disable=SC1091
source "${ROOT}/.env.example"
set +a

COMFYUI_DIR="${COMFYUI_DIR:-/workspace/ComfyUI}"
PROFILE="${PROFILE:-standard}"
HF_REPO="${HF_REPO:-Comfy-Org/MiniMax-H3}"
MODELS="${COMFYUI_DIR}/models"

source /venv/main/bin/activate

if ! command -v hf >/dev/null 2>&1; then
  uv pip install -q "huggingface_hub[cli]"
fi

mkdir -p \
  "${MODELS}/diffusion_models" \
  "${MODELS}/text_encoders" \
  "${MODELS}/vae" \
  "${MODELS}/loras" \
  "${MODELS}/embeddings" \
  "${MODELS}/model_patches"

need() {
  local rel="$1"
  if [[ -f "${MODELS}/${rel}" ]]; then
    echo "[skip] ${rel}"
    return 1
  fi
  return 0
}

download_one() {
  local rel="$1"
  if ! need "${rel}"; then
    return 0
  fi
  echo "[dl] ${HF_REPO}/${rel}"
  hf download "${HF_REPO}" "${rel}" --local-dir "${MODELS}"
}

VAE_FILES=(
  "vae/minimax_h3_video_vae_fp16.safetensors"
  "vae/minimax_h3_audio_vae_fp32.safetensors"
)
TE_NVFP4="text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"
TE_BF16="text_encoders/qwen3vl_32b_minimax_h3_bf16.safetensors"
FL2VA_PRUNED_BF16="diffusion_models/minimax_h3_fl2va_pruned_bf16.safetensors"
FL2VA_PRUNED_FP8="diffusion_models/minimax_h3_fl2va_pruned_fp8_scaled.safetensors"
REF2VA_PRUNED_BF16="diffusion_models/minimax_h3_ref2va_pruned_bf16.safetensors"
TURBO_LORA="loras/minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16.safetensors"

case "${PROFILE}" in
  lite)
    FILES=("${FL2VA_PRUNED_FP8}" "${TE_NVFP4}" "${VAE_FILES[@]}" "${TURBO_LORA}")
    ;;
  standard)
    FILES=("${FL2VA_PRUNED_BF16}" "${TE_NVFP4}" "${VAE_FILES[@]}" "${TURBO_LORA}")
    ;;
  full)
    FILES=("${FL2VA_PRUNED_BF16}" "${REF2VA_PRUNED_BF16}" "${TE_NVFP4}" "${VAE_FILES[@]}" "${TURBO_LORA}")
    ;;
  quality)
    FILES=(
      "diffusion_models/minimax_h3_fl2va_bf16.safetensors"
      "${TE_BF16}"
      "${VAE_FILES[@]}"
      "${TURBO_LORA}"
    )
    ;;
  *)
    echo "Unknown PROFILE=${PROFILE}. Use lite|standard|full|quality" >&2
    exit 1
    ;;
esac

echo "=== MiniMax H3 download profile: ${PROFILE} ==="
echo "Target: ${MODELS}"
for f in "${FILES[@]}"; do
  download_one "${f}"
done

echo "=== embeddings (optional) ==="
hf download "${HF_REPO}" --include "embeddings/*" --local-dir "${MODELS}" || true

echo "=== done ==="
du -sh "${MODELS}"/* 2>/dev/null || true
find "${MODELS}" -name '*.safetensors' | sort
