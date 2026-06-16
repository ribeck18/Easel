#!/usr/bin/env python3
"""Build assets/Easel.icns (and a 1024 master PNG) from assets/icon-source.png.

Pipeline:
  1. Remove the solid (white) background via a connected flood-fill seeded from
     the canvas border. Flood-fill is used instead of a global "white -> clear"
     so the light cream canvas in the centre (which is enclosed by the brown
     squircle) is never touched.
  2. Crop to the artwork, then place it onto a 1024x1024 transparent canvas at
     Apple's macOS safe-area proportions (~80% of the tile, centred, no
     distortion) so it sits optically with native Dock icons.
  3. Emit every size macOS asks for and pack them into a .icns with iconutil.

Resizing is done with premultiplied alpha so transparent edges never bleed a
white halo. Requires: Pillow, numpy, and macOS `iconutil`.

Regenerate with:  python3 assets/make_icns.py
"""
import os
import shutil
import subprocess

import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "icon-source.png")
ICNS = os.path.join(HERE, "Easel.icns")
MASTER_PNG = os.path.join(HERE, "Easel-1024.png")
ICONSET = "/tmp/Easel.iconset"

CANVAS = 1024          # final master canvas (px)
SAFE = 824             # artwork footprint inside the canvas (Apple grid ~80.5%)
FLOOD_THRESH = 250     # tolerance for the border flood-fill (sum of |Δ| per pixel)


def premult_resize(img, size):
    """Lanczos resize an RGBA image using premultiplied alpha (no edge halo)."""
    if isinstance(size, int):
        size = (size, size)
    a = np.asarray(img, np.float64)
    al = a[..., 3:4] / 255.0
    pm = Image.fromarray(np.clip(a[..., :3] * al, 0, 255).astype(np.uint8), "RGB").resize(size, Image.LANCZOS)
    am = Image.fromarray((al[..., 0] * 255).astype(np.uint8), "L").resize(size, Image.LANCZOS)
    pmr = np.asarray(pm, np.float64)
    alr = np.asarray(am, np.float64) / 255.0
    with np.errstate(divide="ignore", invalid="ignore"):
        un = np.where(alr[..., None] > 0, pmr / alr[..., None], 0)
    return Image.fromarray(np.dstack([np.clip(un, 0, 255), np.clip(alr * 255, 0, 255)]).astype(np.uint8), "RGBA")


def remove_background(src_path):
    im = Image.open(src_path).convert("RGB")
    w, h = im.size
    sentinel = (255, 0, 255)
    flood = im.copy()
    seeds = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1),
             (w // 2, 0), (0, h // 2), (w - 1, h // 2), (w // 2, h - 1)]
    for s in seeds:
        ImageDraw.floodfill(flood, s, sentinel, thresh=FLOOD_THRESH)
    arr = np.asarray(im, np.uint8)
    bg = np.all(np.asarray(flood, np.uint8) == np.array(sentinel, np.uint8), axis=-1)
    alpha = np.where(bg, 0, 255).astype(np.uint8)
    rgba = Image.fromarray(np.dstack([arr, alpha]), "RGBA")
    ys, xs = np.where(~bg)
    bbox = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
    return rgba.crop(bbox)


def build_master(art):
    aw, ah = art.size
    scale = SAFE / max(aw, ah)
    nw, nh = round(aw * scale), round(ah * scale)
    art_s = premult_resize(art, (nw, nh))
    master = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    master.paste(art_s, ((CANVAS - nw) // 2, (CANVAS - nh) // 2), art_s)
    return master


def build_icns(master):
    shutil.rmtree(ICONSET, ignore_errors=True)
    os.makedirs(ICONSET)
    specs = [
        (16, "icon_16x16.png"), (32, "icon_16x16@2x.png"),
        (32, "icon_32x32.png"), (64, "icon_32x32@2x.png"),
        (128, "icon_128x128.png"), (256, "icon_128x128@2x.png"),
        (256, "icon_256x256.png"), (512, "icon_256x256@2x.png"),
        (512, "icon_512x512.png"), (1024, "icon_512x512@2x.png"),
    ]
    for size, name in specs:
        img = master if size == CANVAS else premult_resize(master, size)
        img.save(os.path.join(ICONSET, name))
    subprocess.run(["iconutil", "-c", "icns", ICONSET, "-o", ICNS], check=True)


def main():
    art = remove_background(SRC)
    master = build_master(art)
    master.save(MASTER_PNG)
    build_icns(master)
    print(f"wrote {MASTER_PNG}")
    print(f"wrote {ICNS} ({os.path.getsize(ICNS)} bytes)")


if __name__ == "__main__":
    main()
