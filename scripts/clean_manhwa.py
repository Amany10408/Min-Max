#!/usr/bin/env python3
"""Remove baked-in manhwa captions, bubbles, SFX, and phone chrome.

Does not live in Git LFS — only this script is committed. Run on a GPU VM:

    python scripts/clean_manhwa.py --input /path/to/raw --output /path/to/clean
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


def natural_key(p: Path):
    return [float(x) if re.fullmatch(r"\d+(?:\.\d+)?", x) else x for x in re.findall(r"\d+(?:\.\d+)?|\D+", p.name)]


def crop_phone_chrome(bgr: np.ndarray) -> np.ndarray:
    """Drop status / nav bars common on mobile webtoon screenshots."""
    h, w = bgr.shape[:2]
    top = 0
    bot = h
    if w >= 500:
        # Status bar + screenshot-edit pencil chip
        top = min(max(88, int(round(h * 0.055))), 130)
        bot = h - min(int(round(h * 0.012)), 28)
    if bot - top < h * 0.55:
        return bgr
    return bgr[top:bot]


def _fill_boxes(mask: np.ndarray, boxes, pad: int) -> None:
    h, w = mask.shape
    for x, y, bw, bh in boxes:
        x0 = max(0, x - pad)
        y0 = max(0, y - pad)
        x1 = min(w, x + bw + pad)
        y1 = min(h, y + bh + pad)
        mask[y0:y1, x0:x1] = 255


def detect_caption_boxes(bgr: np.ndarray) -> np.ndarray:
    """Heuristic mask: black narration bars only. No 'white wall' blobs."""
    h, w = bgr.shape[:2]
    mask = np.zeros((h, w), np.uint8)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    area = h * w

    # Black narration bars only: short, wide, parked at top or bottom.
    dark = (gray < 22).astype(np.uint8) * 255
    dark = cv2.morphologyEx(dark, cv2.MORPH_CLOSE, np.ones((7, 25), np.uint8))
    contours, _ = cv2.findContours(dark, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for c in contours:
        x, y, bw, bh = cv2.boundingRect(c)
        a = bw * bh
        if a < area * 0.015 or a > area * 0.22:
            continue
        aspect = bw / max(bh, 1)
        if aspect < 2.4 or bh > h * 0.22:
            continue
        near_edge = y < h * 0.16 or (y + bh) > h * 0.78
        if near_edge and bw > w * 0.40:
            _fill_boxes(mask, [(x, y, bw, bh)], pad=6)

    # Pale UI chips (AOS / RPG), small only
    pale = cv2.inRange(hsv, (0, 0, 165), (180, 50, 255))
    pale = cv2.morphologyEx(pale, cv2.MORPH_CLOSE, np.ones((5, 9), np.uint8))
    contours, _ = cv2.findContours(pale, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for c in contours:
        x, y, bw, bh = cv2.boundingRect(c)
        a = bw * bh
        if a < 800 or a > area * 0.04:
            continue
        aspect = bw / max(bh, 1)
        if 1.4 < aspect < 8 and bh < h * 0.08 and bw < w * 0.45:
            _fill_boxes(mask, [(x, y, bw, bh)], pad=4)

    return mask


def detect_ocr_boxes(bgr: np.ndarray, reader) -> np.ndarray:
    h, w = bgr.shape[:2]
    mask = np.zeros((h, w), np.uint8)
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    try:
        results = reader.readtext(rgb, paragraph=False)
    except Exception as exc:  # noqa: BLE001
        print(f"  OCR failed: {exc}")
        return mask
    for box, text, conf in results:
        if conf < 0.25:
            continue
        if not str(text).strip():
            continue
        pts = np.array(box, dtype=np.int32)
        x, y, bw, bh = cv2.boundingRect(pts)
        if bw * bh > h * w * 0.12:
            continue
        cv2.fillPoly(mask, [pts], 255)
        _fill_boxes(mask, [(x, y, bw, bh)], pad=14)
    return mask


def inpaint(bgr: np.ndarray, mask: np.ndarray, lama) -> np.ndarray:
    if mask.max() == 0:
        return bgr
    mask = cv2.dilate(mask, np.ones((7, 7), np.uint8), iterations=1)
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    pil_img = Image.fromarray(rgb)
    pil_mask = Image.fromarray(mask)
    out = lama(pil_img, pil_mask)
    if isinstance(out, Image.Image):
        arr = np.array(out)
    else:
        arr = np.asarray(out)
        if arr.dtype != np.uint8:
            arr = np.clip(arr, 0, 255).astype(np.uint8)
    if arr.ndim == 2:
        arr = cv2.cvtColor(arr, cv2.COLOR_GRAY2RGB)
    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)


def process_one(path: Path, out_path: Path, lama, reader, save_mask: Path | None) -> None:
    bgr = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if bgr is None:
        raise RuntimeError(f"Could not read {path}")
    bgr = crop_phone_chrome(bgr)
    mask = detect_caption_boxes(bgr)
    if reader is not None:
        mask = cv2.bitwise_or(mask, detect_ocr_boxes(bgr, reader))
    coverage = mask.mean() / 255.0
    print(f"  {path.name}: mask={coverage:.1%}")
    if coverage > 0.18:
        ocr = detect_ocr_boxes(bgr, reader) if reader is not None else np.zeros_like(mask)
        geo = detect_caption_boxes(bgr)
        mask = cv2.bitwise_or(geo, ocr)
        print(f"    clamped, now {mask.mean()/255:.1%}")
    # Paint caption holes on already-white pages instead of hallucinating art
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    white_page = gray.mean() > 200
    if white_page:
        cleaned = bgr.copy()
        cleaned[mask > 0] = 255
    else:
        cleaned = inpaint(bgr, mask, lama)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ok, buf = cv2.imencode(".png", cleaned)
    if not ok:
        raise RuntimeError(f"encode failed {out_path}")
    buf.tofile(str(out_path))
    if save_mask is not None:
        save_mask.parent.mkdir(parents=True, exist_ok=True)
        cv2.imencode(".png", mask)[1].tofile(str(save_mask))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--masks", default="")
    ap.add_argument("--no-ocr", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    src = Path(args.input)
    dst = Path(args.output)
    files = sorted(
        [p for p in src.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}],
        key=natural_key,
    )
    if args.limit:
        files = files[: args.limit]
    print(f"Cleaning {len(files)} images -> {dst}")

    from simple_lama_inpainting import SimpleLama

    print("Loading LaMa…")
    lama = SimpleLama()
    reader = None
    if not args.no_ocr:
        import easyocr

        print("Loading EasyOCR (en+ko)…")
        reader = easyocr.Reader(["en", "ko"], gpu=True)

    mask_dir = Path(args.masks) if args.masks else None
    for p in files:
        out = dst / (p.stem + ".png")
        mpath = (mask_dir / (p.stem + "_mask.png")) if mask_dir else None
        process_one(p, out, lama, reader, mpath)
    print("done")


if __name__ == "__main__":
    main()
