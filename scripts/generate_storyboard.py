#!/usr/bin/env python3
"""Queue MiniMax H3 FL2VA clips in ComfyUI, then concat into one long video.

H3 maxes out around 15s per sample. Longer stories are N clips chained:

  clip[i].last_frame  ->  clip[i+1].first_frame

After each clip we extract the generated last frame and feed it as the next
first frame so motion continuity survives the cut. Concatenate with ffmpeg.

    python scripts/generate_storyboard.py \\
        --storyboard storyboards/survival_as_barb.json \\
        --images /workspace/survival_barb/clean \\
        --comfy http://127.0.0.1:18188
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import time
import urllib.request
import uuid
from pathlib import Path

import cv2


UNET = "minimax_h3_fl2va_pruned_bf16.safetensors"
TEXT_ENCODER = "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"
VIDEO_VAE = "minimax_h3_video_vae_fp16.safetensors"
AUDIO_VAE = "minimax_h3_audio_vae_fp32.safetensors"
TURBO_LORA = "minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16.safetensors"


def h3_length(seconds: float) -> int:
    n = max(5, int(round(seconds * 24)))
    return n + (5 - (n % 17)) % 17


def comfy(method: str, url: str, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"} if data else {},
        method=method,
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        raw = r.read().decode()
        return json.loads(raw) if raw else {}


def upload_image(comfy_url: str, path: Path, name: str) -> str:
    boundary = uuid.uuid4().hex
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="image"; filename="{name}"\r\n'
        "Content-Type: image/png\r\n\r\n"
    ).encode() + path.read_bytes() + (
        f"\r\n--{boundary}\r\n"
        'Content-Disposition: form-data; name="overwrite"\r\n\r\n'
        "true\r\n"
        f"--{boundary}--\r\n"
    ).encode()
    req = urllib.request.Request(
        f"{comfy_url}/upload/image",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        out = json.loads(r.read().decode())
    return out.get("name") or name


def build_graph(
    *,
    first_name: str,
    last_name: str | None,
    prompt: str,
    width: int,
    height: int,
    length: int,
    seed: int,
    steps: int,
    prefix: str,
    use_lora: bool,
) -> dict:
    model_node = "6"
    g: dict = {
        "6": {
            "class_type": "UNETLoader",
            "inputs": {"unet_name": UNET, "weight_dtype": "default"},
        },
        "13": {
            "class_type": "CLIPLoader",
            "inputs": {"clip_name": TEXT_ENCODER, "type": "minimax", "device": "default"},
        },
        "10": {"class_type": "VAELoader", "inputs": {"vae_name": VIDEO_VAE}},
        "11": {"class_type": "VAELoader", "inputs": {"vae_name": AUDIO_VAE}},
        "114": {"class_type": "LoadImage", "inputs": {"image": first_name}},
        "104": {
            "class_type": "MiniMaxH3ImageToVideo",
            "inputs": {
                "clip": ["13", 0],
                "vae": ["10", 0],
                "first_frame": ["114", 0],
                "prompt": prompt,
                "width": width,
                "height": height,
                "length": length,
            },
        },
        "14": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "15": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["12", 0], "vae": ["10", 0]}},
        "9": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["12", 0], "vae": ["11", 0]}},
        "91": {
            "class_type": "CreateVideo",
            "inputs": {"images": ["8", 0], "fps": 24.0, "audio": ["9", 0], "bit_depth": 8},
        },
        "92": {
            "class_type": "SaveVideo",
            "inputs": {
                "video": ["91", 0],
                "filename_prefix": prefix,
                "format": "auto",
                "codec": "auto",
            },
        },
    }
    if last_name:
        g["115"] = {"class_type": "LoadImage", "inputs": {"image": last_name}}
        g["104"]["inputs"]["last_frame"] = ["115", 0]
    if use_lora:
        g["121"] = {
            "class_type": "LoraLoaderModelOnly",
            "inputs": {"model": ["6", 0], "lora_name": TURBO_LORA, "strength_model": 1.0},
        }
        model_node = "121"
    g["16"] = {
        "class_type": "BasicGuider",
        "inputs": {"model": [model_node, 0], "conditioning": ["104", 0]},
    }
    g["17"] = {
        "class_type": "BasicScheduler",
        "inputs": {
            "model": [model_node, 0],
            "scheduler": "simple",
            "steps": steps,
            "denoise": 1.0,
        },
    }
    g["12"] = {
        "class_type": "SamplerCustomAdvanced",
        "inputs": {
            "noise": ["15", 0],
            "guider": ["16", 0],
            "sampler": ["14", 0],
            "sigmas": ["17", 0],
            "latent_image": ["104", 1],
        },
    }
    return g


def wait_history(comfy_url: str, prompt_id: str, timeout: int = 7200) -> dict:
    t0 = time.time()
    while time.time() - t0 < timeout:
        hist = comfy("GET", f"{comfy_url}/history/{prompt_id}")
        if prompt_id in hist:
            return hist[prompt_id]
        time.sleep(3)
    raise TimeoutError(prompt_id)


def find_saved_video(hist: dict, output_dir: Path) -> Path | None:
    for node in (hist.get("outputs") or {}).values():
        for key in ("videos", "gifs", "images"):
            for item in node.get(key, []):
                fn = item.get("filename")
                if not fn:
                    continue
                sub = item.get("subfolder") or ""
                p = output_dir / sub / fn if sub else output_dir / fn
                if p.exists():
                    return p
    return None


def extract_last_frame(video: Path, dest: Path) -> Path:
    cap = cv2.VideoCapture(str(video))
    last = None
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        last = frame
    cap.release()
    if last is None:
        raise RuntimeError(f"no frames in {video}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(dest), last)
    return dest


def concat_clips(clips: list[Path], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    lst = out.with_suffix(".txt")
    lst.write_text("".join(f"file '{p}'\n" for p in clips))
    subprocess.check_call(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(out)]
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--storyboard", required=True)
    ap.add_argument("--images", required=True)
    ap.add_argument("--comfy", default="http://127.0.0.1:18188")
    ap.add_argument("--output-dir", default="/workspace/ComfyUI/output")
    ap.add_argument("--final", default="/workspace/survival_barb/output/prologue.mp4")
    ap.add_argument("--clip-id", default="")
    ap.add_argument("--no-lora", action="store_true")
    ap.add_argument("--steps", type=int, default=4)
    ap.add_argument("--seed", type=int, default=10408)
    ap.add_argument("--no-chain-generated-frames", action="store_true")
    ap.add_argument("--skip-existing", action="store_true")
    args = ap.parse_args()

    sb = json.loads(Path(args.storyboard).read_text())
    img_dir = Path(args.images)
    out_dir = Path(args.output_dir)
    clips_out: list[Path] = []
    prev_generated_last: Path | None = None

    for i, shot in enumerate(sb["clips"]):
        if args.clip_id and shot["id"] != args.clip_id:
            continue
        dest = Path(args.final).parent / "clips" / f"{i:02d}_{shot['id']}.mp4"
        chain_last = Path(args.final).parent / "chain_frames" / f"{shot['id']}_last.png"
        if args.skip_existing and dest.exists():
            print(f"=== skip existing {dest}")
            clips_out.append(dest)
            if chain_last.exists():
                prev_generated_last = chain_last
            continue
        first_src = img_dir / shot["first"]
        last_src = img_dir / shot["last"]
        if (
            not args.no_chain_generated_frames
            and prev_generated_last
            and prev_generated_last.exists()
        ):
            first_src = prev_generated_last
        if not first_src.exists() or not last_src.exists():
            raise FileNotFoundError(
                f"{first_src} or {last_src} missing — run clean_manhwa.py first"
            )

        first_name = upload_image(args.comfy, first_src, f"sb_{shot['id']}_first.png")
        last_name = upload_image(args.comfy, last_src, f"sb_{shot['id']}_last.png")
        length = h3_length(shot["duration_s"])
        graph = build_graph(
            first_name=first_name,
            last_name=last_name,
            prompt=shot["prompt"],
            width=sb["width"],
            height=sb["height"],
            length=length,
            seed=args.seed + i * 17,
            steps=args.steps,
            prefix=f"survival_barb/{shot['id']}",
            use_lora=not args.no_lora,
        )
        print(
            f"=== {shot['id']}  {shot['duration_s']}s  length={length}  "
            f"{first_src.name} -> {last_src.name}"
        )
        res = comfy("POST", f"{args.comfy}/prompt", {"prompt": graph})
        if "error" in res:
            raise RuntimeError(res)
        pid = res["prompt_id"]
        hist = wait_history(args.comfy, pid)
        status = hist.get("status") or {}
        if status.get("status_str") == "error" or status.get("completed") is False:
            msgs = status.get("messages") or hist.get("messages")
            raise RuntimeError(json.dumps(msgs or status, indent=2)[:4000])
        video = find_saved_video(hist, out_dir)
        if not video:
            cands = sorted(
                out_dir.rglob(f"*{shot['id']}*"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            video = next((p for p in cands if p.suffix.lower() in {".mp4", ".webm", ".mkv"}), None)
        if not video:
            raise RuntimeError(
                f"no video for {shot['id']}: {json.dumps(hist.get('outputs'), default=str)[:2000]}"
            )
        dest = Path(args.final).parent / "clips" / f"{i:02d}_{shot['id']}{video.suffix}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(video, dest)
        clips_out.append(dest)
        prev_generated_last = extract_last_frame(
            dest, Path(args.final).parent / "chain_frames" / f"{shot['id']}_last.png"
        )
        print(f"  saved {dest}")

    if len(clips_out) > 1:
        concat_clips(clips_out, Path(args.final))
        print("FINAL", args.final)
    elif len(clips_out) == 1:
        shutil.copy2(clips_out[0], args.final)
        print("FINAL", args.final)


if __name__ == "__main__":
    main()
