#!/usr/bin/env python3
"""Draw the H3 Studio app icons from scratch (pure Python, no fonts, no third-party artwork).

    python3 tools/make_icons.py        # rewrites static/icon-{180,192,512}.png

The glyphs are blocks on a 3x5 grid; everything is computed from the shapes below, so the icons are original work
released under the project's MIT license.
"""
import struct
import zlib
from pathlib import Path

BG, FILL, EDGE, INK = (19, 26, 36), (55, 119, 224), (140, 187, 255), (245, 248, 255)
# letters on a 5-row grid, 1 = ink.  H is 3 wide, the "3" is 3 wide, 1 column gap
H = ["101", "101", "111", "101", "101"]
THREE = ["111", "001", "011", "001", "111"]


def inside_round_rect(x, y, x0, y0, x1, y1, r):
    if not (x0 <= x <= x1 and y0 <= y <= y1):
        return False
    cx = min(max(x, x0 + r), x1 - r)
    cy = min(max(y, y0 + r), y1 - r)
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r


def pixel(u, v):
    """Colour at unit coordinates (0..1, 0..1)."""
    x0, y0, x1, y1, r, b = 0.13, 0.13, 0.87, 0.87, 0.16, 0.012
    if not inside_round_rect(u, v, x0, y0, x1, y1, r):
        return BG
    if not inside_round_rect(u, v, x0 + b, y0 + b, x1 - b, y1 - b, r - b):
        return EDGE
    cell, gx, gy = 0.07, 0.5 - 7 * 0.07 / 2, 0.5 - 5 * 0.07 / 2     # 7 columns (3+1+3) x 5 rows, centred
    col, row = (u - gx) / cell, (v - gy) / cell
    if 0 <= row < 5 and 0 <= col < 7:
        r_, c_ = int(row), int(col)
        if c_ < 3 and H[r_][c_] == "1":
            return INK
        if c_ >= 4 and THREE[r_][c_ - 4] == "1":
            return INK
    return FILL


def render(size, ss=3):
    rows = []
    for j in range(size):
        row = bytearray([0])
        for i in range(size):
            acc = [0, 0, 0]
            for sj in range(ss):
                for si in range(ss):
                    c = pixel((i + (si + .5) / ss) / size, (j + (sj + .5) / ss) / size)
                    for k in range(3):
                        acc[k] += c[k]
            row += bytes(a // (ss * ss) for a in acc)
        rows.append(bytes(row))
    return b"".join(rows)


def png(size):
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(render(size), 9)) + chunk(b"IEND", b""))


if __name__ == "__main__":
    out = Path(__file__).resolve().parent.parent / "static"
    for s in (180, 192, 512):
        (out / f"icon-{s}.png").write_bytes(png(s))
        print("wrote", out / f"icon-{s}.png")
