# Min-Max — MiniMax H3 + ComfyUI on Vast.ai

Portable **code-only** repo to recreate **image + text → video** (and text-only video) on any Vast.ai GPU VM.

Weights are **never** stored in this repo. `scripts/bootstrap_vast.sh` downloads them from Hugging Face on each new machine.

| Piece | Source |
| --- | --- |
| Model (open weights) | [MiniMax-AI/MiniMax-H3](https://github.com/MiniMax-AI/MiniMax-H3) |
| ComfyUI packs | [Comfy-Org/MiniMax-H3](https://huggingface.co/Comfy-Org/MiniMax-H3) |
| UI | [ComfyUI](https://github.com/comfyanonymous/ComfyUI) ≥ `v0.30` (pinned `v0.36.0`) |
| Guide | [ComfyUI MiniMax H3 docs](https://docs.comfy.org/tutorials/video/minimax/minimax-h3) |

Modes:

- **T2V** — text → video + stereo audio  
- **I2V / FL2VA** — first (optional last) **image + text** → video  
- **R2V** — reference media + text → video (`PROFILE=full`)

---

## What is (and isn’t) in GitHub

| In this repo (~250 KB) | Not in git (downloaded on the VM) |
| --- | --- |
| `scripts/` install + Vast service | `*.safetensors` model weights (~60 GB for `standard`) |
| `vast/` supervisor wrapper | Full ComfyUI runtime under `/workspace/ComfyUI` |
| `workflows/` I2V / T2V / R2V JSON | Outputs, caches, `.env` secrets |
| `docs/` prompt guides + README | |

---

## New Vast.ai VM — one command

**GPU:** ≥ 80 GB VRAM (e.g. RTX PRO 6000 96GB).  
**Image:** Vast **PyTorch**, CUDA **≥ 12.8** on Blackwell.  
**Disk:** ≥ 200 GB. Keep a free TCP port (default `10100`).  
**Persistence:** attach a **volume** to `/workspace` if you don’t want to re-download models after destroy/recycle.

```bash
git clone https://github.com/Amany10408/Min-Max.git /workspace/Min-Max
cd /workspace/Min-Max
cp -n .env.example .env   # optional: edit PROFILE / ports
bash scripts/bootstrap_vast.sh
```

That will:

1. Install ComfyUI → `/workspace/ComfyUI`  
2. Download MiniMax H3 weights for `PROFILE` (default `standard`)  
3. Register ComfyUI under **supervisor + Caddy** (token auth)  
4. Copy workflows into ComfyUI  

Open UI:

```bash
echo "http://$PUBLIC_IPADDR:$VAST_TCP_PORT_10100/"
echo "token: $OPEN_BUTTON_TOKEN"
```

Auth: `Authorization: Bearer $OPEN_BUTTON_TOKEN`, or `?token=...`, or the Vast portal cookie.

---

## Make a video from an image + text

1. Open ComfyUI → **Template Library → Video → MiniMax H3 → Image to Video**,  
   or load `workflows/video_minimax_h3_i2v.json`.  
2. Drop your image on the first-frame / keyframe input.  
3. Write a motion / camera / audio prompt (`docs/h3-prompt-writing`).  
4. Confirm loaders:

   | Role | File |
   | --- | --- |
   | UNET / diffusion | `minimax_h3_fl2va_pruned_bf16.safetensors` |
   | Text encoder | `qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors` |
   | Video VAE | `minimax_h3_video_vae_fp16.safetensors` |
   | Audio VAE | `minimax_h3_audio_vae_fp32.safetensors` |
   | Optional turbo | `minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16.safetensors` |

5. Queue prompt → output in `ComfyUI/output/`.

**Text only:** use the **T2V** template (same FL2VA weights).

---

## Model profiles (`PROFILE` in `.env`)

| Profile | Disk (approx) | Use when |
| --- | --- | --- |
| `lite` | ~45 GB | Smaller disk / faster pull (pruned FP8) |
| `standard` (default) | ~60 GB | Best for ~96 GB VRAM (this setup) |
| `full` | ~105 GB | Also need Ref2VA (R2V) |
| `quality` | ~130 GB | Full BF16 + BF16 text encoder |

```bash
PROFILE=full bash scripts/download_models.sh
```

Optional faster HF downloads:

```bash
echo 'HF_TOKEN=hf_xxx' >> /workspace/.env
```

---

## Ops on the running VM

```bash
supervisorctl status comfyui
tail -f /var/log/portal/comfyui.log
supervisorctl restart comfyui
```

SSH tunnel (no public port / no token):

```bash
ssh -p $VAST_TCP_PORT_22 -L 8188:127.0.0.1:18188 root@$PUBLIC_IPADDR
# http://localhost:8188
```

---

## Repo layout

```
Min-Max/
├── README.md
├── .env.example
├── scripts/
│   ├── bootstrap_vast.sh      # one-shot on a new VM
│   ├── install.sh
│   ├── download_models.sh     # HF only — not git LFS
│   └── setup_vast_service.sh
├── vast/
│   ├── comfyui.sh
│   └── comfyui.conf
├── workflows/                 # official Comfy templates
└── docs/h3-prompt-writing/
```

---

## Moving to another VM

```bash
git clone https://github.com/Amany10408/Min-Max.git /workspace/Min-Max
bash /workspace/Min-Max/scripts/bootstrap_vast.sh
```

If `/workspace` is a persistent volume and models already exist, downloads skip existing files.

---

## License

MiniMax H3 has its own community license. Commercial use of local generations may need a MiniMax commercial license — see [ComfyUI H3 docs](https://docs.comfy.org/tutorials/video/minimax/minimax-h3) and [MiniMax-H3](https://github.com/MiniMax-AI/MiniMax-H3).
