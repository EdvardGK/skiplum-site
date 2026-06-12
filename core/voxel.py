"""Shared voxel-text placement.

Pure geometry: yields one spec per filled voxel as
    (vx, vy, vz, ax, ay, bx, by, ha, hb, hv)
where (ax,ay) and (bx,by) are the two in-plane unit axes, Z is vertical, and
ha/hb/hv are half-extents along A/B/Z.

Both the IFC builder (-> IfcFace boxes) and the Plotly preview (-> Mesh3d boxes)
consume these generators, so the rendered text and the exported text are identical.
"""
from __future__ import annotations

import math

from .fonts import FONT_5X7


def fit_top_char_height(radius: float, text: str) -> float:
    """Auto-fit the top-label character height so long labels still fit across
    the marker. Mirrors the builder's logic exactly."""
    avail = 1.8 * radius * 0.9
    default_h = max(0.18, radius * 0.12)
    req = (len(text or "") + 1) * 6.0 * default_h / 7.0
    char_h = default_h * min(1.0, avail / max(req, 1e-6))
    return max(0.12, char_h)


def wall_char_height(height: float) -> float:
    return min(0.40, height * 0.16)


def wall_band_zs(z_bot: float, height: float, n: int,
                 top_frac: float = 0.80, bot_frac: float = 0.20) -> list[float]:
    """Evenly spaced z-centers for `n` text rows down the cylinder wall."""
    if n <= 0:
        return []
    if n == 1:
        return [z_bot + height * (top_frac + bot_frac) / 2.0]
    return [z_bot + height * (top_frac - (top_frac - bot_frac) * i / (n - 1))
            for i in range(n)]


def iter_voxels_flat(cx, cy, z_top, text, angle, char_height, voxel_thickness=0.05):
    """Flat text laid along `angle`, centered at (cx, cy), on the top face."""
    text = (text or "").upper()
    if not text:
        return
    voxel = char_height / 7.0
    char_w = 5 * voxel
    pitch = char_w + voxel
    total = len(text) * pitch - voxel
    dax, day = math.cos(angle), math.sin(angle)        # advance (left->right)
    pax, pay = -math.sin(angle), math.cos(angle)       # row up
    start = -total / 2.0
    z = z_top + voxel_thickness / 2.0
    hr = ht = voxel / 2.0
    hv = voxel_thickness / 2.0
    for ci, ch in enumerate(text):
        pattern = FONT_5X7.get(ch, FONT_5X7[" "])
        char_left = start + ci * pitch
        for row in range(7):
            for col in range(5):
                if pattern[row][col] != "1":
                    continue
                along = char_left + (col + 0.5) * voxel
                perp = (3 - row) * voxel
                vx = cx + along * dax + perp * pax
                vy = cy + along * day + perp * pay
                yield (vx, vy, z, dax, day, pax, pay, hr, ht, hv)


def iter_voxels_on_cylinder(cx, cy, z_center, text, radius,
                            char_height=0.40, voxel_depth=0.04,
                            face_compass_deg=180.0):
    """Text wrapped on the cylinder wall, centered on a compass bearing.

    Curve-aware: each column's angular position is arc_length / radius, so letter
    spacing stays correct at any diameter.
    """
    text = (text or "").upper()
    if not text:
        return
    voxel = char_height / 7.0
    char_w = 5 * voxel
    pitch = char_w + voxel
    total_arc = len(text) * pitch
    center_angle = math.radians(90.0 - face_compass_deg)   # compass -> math angle
    start_angle = center_angle - total_arc / (2 * radius)
    for ci, ch in enumerate(text):
        pattern = FONT_5X7.get(ch, FONT_5X7[" "])
        char_left_angle = start_angle + (ci * pitch) / radius
        for row in range(7):
            for col in range(5):
                if pattern[row][col] != "1":
                    continue
                a = char_left_angle + ((col + 0.5) * voxel) / radius
                z = z_center + (3 - row) * voxel
                ca, sa = math.cos(a), math.sin(a)
                tx, ty = -sa, ca           # tangent (text advance)
                rx, ry = ca, sa            # radial (depth)
                bx = cx + radius * ca
                by = cy + radius * sa
                ht = voxel / 2.0
                hr = voxel_depth / 2.0
                hv = voxel / 2.0
                yield (bx, by, z, tx, ty, rx, ry, ht, hr, hv)
