#!/usr/bin/env bash
# Register ComfyUI as a Vast supervisor service behind Caddy auth.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
[[ -f "${ROOT}/.env" ]] && source "${ROOT}/.env"
# shellcheck disable=SC1091
source "${ROOT}/.env.example"

COMFYUI_DIR="${COMFYUI_DIR:-/workspace/ComfyUI}"
COMFYUI_PORT="${COMFYUI_PORT:-18188}"
COMFYUI_EXTERNAL_PORT="${COMFYUI_EXTERNAL_PORT:-10100}"

if [[ ! -d "${COMFYUI_DIR}" ]]; then
  echo "ComfyUI not found at ${COMFYUI_DIR}. Run scripts/install.sh first." >&2
  exit 1
fi

# Pick a free open port if the configured one is taken / unset
pick_port() {
  local want="$1"
  local mapped in_use
  mapped="$(printenv "VAST_TCP_PORT_${want}" 2>/dev/null || true)"
  if [[ -n "${mapped}" ]]; then
    in_use="$(vast-capabilities 2>/dev/null | jq -r --arg p "${want}" '
      [.instance.open_ports[]? | select((.container_port|tostring)==$p) | .in_use] | .[0] // "false"
    ' || echo false)"
    if [[ "${in_use}" == "false" ]]; then
      echo "${want}"
      return
    fi
  fi
  vast-capabilities 2>/dev/null | jq -r '
    [.instance.open_ports[]?
      | select(.in_use==false and (.self_mapped!=true) and ((.container_port|tonumber) > 1000 and (.container_port|tonumber) < 65536))]
    | sort_by(.container_port) | .[0].container_port // empty
  '
}

CHOSEN="$(pick_port "${COMFYUI_EXTERNAL_PORT}")"
if [[ -z "${CHOSEN}" ]]; then
  echo "No free Vast open port available. Request an extra port when creating the instance." >&2
  exit 1
fi
COMFYUI_EXTERNAL_PORT="${CHOSEN}"
echo "Using external_port=${COMFYUI_EXTERNAL_PORT} (public: \$VAST_TCP_PORT_${COMFYUI_EXTERNAL_PORT})"

# Install supervisor wrapper + conf from this repo
install -m 0755 "${ROOT}/vast/comfyui.sh" /opt/supervisor-scripts/comfyui.sh
# Rewrite paths into the installed wrapper via env file
cat > /workspace/.env.minimax-comfyui <<EOF
COMFYUI_DIR="${COMFYUI_DIR}"
COMFYUI_HOST="127.0.0.1"
COMFYUI_PORT="${COMFYUI_PORT}"
COMFYUI_ARGS="--disable-auto-launch --enable-cors-header --listen 127.0.0.1 --port ${COMFYUI_PORT}"
EOF
# Ensure workspace .env sources our vars
touch /workspace/.env
grep -q 'COMFYUI_DIR=' /workspace/.env 2>/dev/null || cat >> /workspace/.env <<EOF

# MiniMax / ComfyUI (managed by Min-Max/scripts/setup_vast_service.sh)
COMFYUI_DIR="${COMFYUI_DIR}"
COMFYUI_PORT="${COMFYUI_PORT}"
COMFYUI_EXTERNAL_PORT="${COMFYUI_EXTERNAL_PORT}"
COMFYUI_ARGS="--disable-auto-launch --enable-cors-header --listen 127.0.0.1 --port ${COMFYUI_PORT}"
EOF

install -m 0644 "${ROOT}/vast/comfyui.conf" /etc/supervisor/conf.d/comfyui.conf

# Portal entry (Caddy auth edge)
python3 - <<PY
import yaml
path = "/etc/portal.yaml"
with open(path) as f:
    d = yaml.safe_load(f) or {"applications": {}}
apps = d.setdefault("applications", {})
apps["ComfyUI"] = {
    "hostname": "localhost",
    "external_port": int("${COMFYUI_EXTERNAL_PORT}"),
    "internal_port": int("${COMFYUI_PORT}"),
    "open_path": "/",
    "name": "ComfyUI",
}
with open(path, "w") as f:
    yaml.safe_dump(d, f, sort_keys=False)
print("portal.yaml updated: ComfyUI -> external", ${COMFYUI_EXTERNAL_PORT}, "internal", ${COMFYUI_PORT})
PY

# Clear any prior skip marker
rm -f /tmp/supervisor-skip/comfyui /tmp/supervisor-skip/ComfyUI || true

supervisorctl reread
supervisorctl update
supervisorctl restart caddy || true
sleep 2
supervisorctl restart comfyui || supervisorctl start comfyui
sleep 3
supervisorctl status comfyui || true

PUBLIC_IP="${PUBLIC_IPADDR:-$(curl -s ifconfig.me 2>/dev/null || echo YOUR_IP)}"
PUB_PORT="$(printenv "VAST_TCP_PORT_${COMFYUI_EXTERNAL_PORT}" || true)"
echo ""
echo "=== ComfyUI should be reachable at ==="
echo "  http://${PUBLIC_IP}:${PUB_PORT}/"
echo "Auth: Authorization: Bearer \$OPEN_BUTTON_TOKEN   (or ?token=\$OPEN_BUTTON_TOKEN)"
echo "Logs: tail -f /var/log/portal/comfyui.log"
echo "Status: supervisorctl status comfyui"
