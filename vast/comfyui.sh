#!/bin/bash
# Vast supervisor wrapper for ComfyUI (MiniMax H3)
utils=/opt/supervisor-scripts/utils
. "${utils}/logging.sh"
. "${utils}/environment.sh"
. "${utils}/exit_portal.sh" "ComfyUI"

COMFYUI_DIR="${COMFYUI_DIR:-${WORKSPACE}/ComfyUI}"
COMFYUI_PORT="${COMFYUI_PORT:-18188}"
COMFYUI_ARGS="${COMFYUI_ARGS:---disable-auto-launch --enable-cors-header --listen 127.0.0.1 --port ${COMFYUI_PORT}}"

source /venv/main/bin/activate

# Wait for provisioning if present
while [ -f "/.provisioning" ]; do
  echo "$PROC_NAME startup paused until /.provisioning is cleared"
  sleep 5
done

if [ ! -f "${COMFYUI_DIR}/main.py" ]; then
  echo "ERROR: ComfyUI not installed at ${COMFYUI_DIR}. Run Min-Max/scripts/install.sh"
  sleep 30
  exit 1
fi

cd "${COMFYUI_DIR}"
# Prefer tcmalloc when available
if ldconfig -p 2>/dev/null | grep -q libtcmalloc_minimal; then
  export LD_PRELOAD=libtcmalloc_minimal.so.4
fi

pty python main.py ${COMFYUI_ARGS} 2>&1
