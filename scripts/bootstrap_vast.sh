#!/usr/bin/env bash
# One-shot bootstrap on a fresh Vast.ai PyTorch instance.
# Usage:
#   git clone https://github.com/Amany10408/Min-Max.git /workspace/Min-Max
#   bash /workspace/Min-Max/scripts/bootstrap_vast.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

cp -n "${ROOT}/.env.example" "${ROOT}/.env" 2>/dev/null || true

# shellcheck disable=SC1091
source "${ROOT}/.env"

echo "PROFILE=${PROFILE:-standard}"
bash "${ROOT}/scripts/install.sh"
bash "${ROOT}/scripts/setup_vast_service.sh"

echo ""
echo "Bootstrap complete. Open ComfyUI and load a workflow from:"
echo "  Template Library → Video → MiniMax H3 (I2V / T2V / R2V)"
echo "  or ${COMFYUI_DIR:-/workspace/ComfyUI}/user/default/workflows/"
