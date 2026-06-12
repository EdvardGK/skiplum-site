"""Plotly 3D preview of the marker from a MarkerConfig.

Renders the cylinder(s) at correct color/dimensions, a north arrow, and text
labels (as 3D text rather than full voxel geometry, for speed). The Streamlit app
embeds this; a future React app would render its own three.js scene from the same
config, so this stays a thin, optional convenience.
"""
from __future__ import annotations

import math

import numpy as np
import plotly.graph_objects as go

from .config import MarkerConfig
from .voxel import iter_voxels_on_cylinder, wall_char_height, wall_band_zs

# 6 box faces as quads of (dA, dB, dV) corner signs; each quad -> 2 triangles.
_QUADS = [
    ((-1, -1, +1), (+1, -1, +1), (+1, +1, +1), (-1, +1, +1)),
    ((-1, +1, -1), (+1, +1, -1), (+1, -1, -1), (-1, -1, -1)),
    ((+1, -1, -1), (+1, +1, -1), (+1, +1, +1), (+1, -1, +1)),
    ((-1, +1, -1), (-1, -1, -1), (-1, -1, +1), (-1, +1, +1)),
    ((-1, -1, -1), (+1, -1, -1), (+1, -1, +1), (-1, -1, +1)),
    ((+1, +1, -1), (-1, +1, -1), (-1, +1, +1), (+1, +1, +1)),
]


def _corner_idx(da, db, dv):
    return ((da + 1) // 2) * 4 + ((db + 1) // 2) * 2 + ((dv + 1) // 2)


def _voxel_mesh_arrays(specs):
    """Turn voxel specs into Mesh3d-ready (x,y,z,i,j,k) arrays."""
    xs, ys, zs, I, J, K = [], [], [], [], [], []
    base = 0
    for (vx, vy, vz, ax, ay, bx, by, ha, hb, hv) in specs:
        for da in (-1, 1):
            for db in (-1, 1):
                for dv in (-1, 1):
                    xs.append(vx + da * ha * ax + db * hb * bx)
                    ys.append(vy + da * ha * ay + db * hb * by)
                    zs.append(vz + dv * hv)
        for q in _QUADS:
            a = base + _corner_idx(*q[0])
            b = base + _corner_idx(*q[1])
            c = base + _corner_idx(*q[2])
            d = base + _corner_idx(*q[3])
            I += [a, a]; J += [b, c]; K += [c, d]
        base += 8
    return xs, ys, zs, I, J, K


def _cylinder_mesh(cx, cy, z0, z1, r, r_in=0.0, slices=64):
    theta = np.linspace(0, 2 * np.pi, slices, endpoint=False)
    ca, sa = np.cos(theta), np.sin(theta)
    xb = cx + r * ca
    yb = cy + r * sa

    if r_in <= 0:
        xs = np.concatenate([xb, xb, [cx], [cx]])
        ys = np.concatenate([yb, yb, [cy], [cy]])
        zs = np.concatenate([np.full(slices, z0), np.full(slices, z1), [z0], [z1]])
        ctr_bot, ctr_top = 2 * slices, 2 * slices + 1
        I, J, K = [], [], []
        for i in range(slices):
            j = (i + 1) % slices
            ti, tj = slices + i, slices + j
            I += [i, i]; J += [j, tj]; K += [tj, ti]   # side
            I += [ctr_bot]; J += [j]; K += [i]          # bottom
            I += [ctr_top]; J += [ti]; K += [tj]        # top
        return xs, ys, zs, I, J, K

    # hollow ring: outer-bot, outer-top, inner-bot, inner-top
    xi = cx + r_in * ca
    yi = cy + r_in * sa
    xs = np.concatenate([xb, xb, xi, xi])
    ys = np.concatenate([yb, yb, yi, yi])
    zs = np.concatenate([np.full(slices, z0), np.full(slices, z1),
                         np.full(slices, z0), np.full(slices, z1)])
    ob, ot, ib, it = 0, slices, 2 * slices, 3 * slices
    I, J, K = [], [], []
    for i in range(slices):
        j = (i + 1) % slices
        # outer wall
        I += [ob + i, ob + i]; J += [ob + j, ot + j]; K += [ot + j, ot + i]
        # inner wall
        I += [ib + j, ib + j]; J += [ib + i, it + i]; K += [it + i, it + j]
        # top annulus
        I += [ot + i, ot + i]; J += [ot + j, it + j]; K += [it + j, it + i]
        # bottom annulus
        I += [ob + j, ob + j]; J += [ob + i, ib + i]; K += [ib + i, ib + j]
    return xs, ys, zs, I, J, K


def _arrow_trace(cx, cy, z_bot, z_top, r, color):
    """Full-height triangular prism pointing north — matches the IFC geometry."""
    L = r * 0.45
    w = r * 0.22
    tri = [(cx, cy + r + L), (cx - w, cy + r), (cx + w, cy + r)]
    xs = [p[0] for p in tri] * 2
    ys = [p[1] for p in tri] * 2
    zs = [z_bot] * 3 + [z_top] * 3
    I, J, K = [0, 3], [1, 4], [2, 5]            # bottom + top tris
    for a in range(3):
        b = (a + 1) % 3
        I += [a, a]; J += [b, b + 3]; K += [b + 3, a + 3]   # side quads
    return go.Mesh3d(x=xs, y=ys, z=zs, i=I, j=J, k=K, color=color,
                     opacity=1.0, name="Nordpil", hoverinfo="name")


def _marker_traces(cfg: MarkerConfig, cx, cy, z, label, traces):
    r = cfg.radius_m
    h = cfg.height_m
    xs, ys, zs, I, J, K = _cylinder_mesh(cx, cy, z, z + h, r, r_in=cfg.inner_radius_m)
    traces.append(go.Mesh3d(
        x=xs, y=ys, z=zs, i=I, j=J, k=K,
        color=cfg.cylinder_color, opacity=1.0, flatshading=True,
        name=label, hoverinfo="name",
    ))
    traces.append(_arrow_trace(cx, cy, z, z + h, r, cfg.arrow_color))

    # real voxel text — same generators / layout as the IFC builder
    specs = []
    top_label = cfg.text.top_label if label == "Nullpunkt" else cfg.control.top_label
    lines = [l for l in ([top_label] + cfg.text.wall_rows()) if l]
    wch = wall_char_height(h)
    for line, zl in zip(lines, wall_band_zs(z, h, len(lines))):
        specs += list(iter_voxels_on_cylinder(cx, cy, zl, line, r + 0.02,
                                              char_height=wch, voxel_depth=0.04,
                                              face_compass_deg=180.0))
    if specs:
        xs, ys, zs, I, J, K = _voxel_mesh_arrays(specs)
        traces.append(go.Mesh3d(
            x=xs, y=ys, z=zs, i=I, j=J, k=K,
            color=cfg.text_color, flatshading=True,
            name="Tekst", hoverinfo="skip", showlegend=False,
        ))


def build_preview_figure(config, which: str = "nullpunkt") -> go.Figure:
    """Render ONE marker centered at the origin.

    which: "nullpunkt" (basepoint) or "control" (rotation/control marker). One at a
    time keeps the view clean — the two markers live at different coordinates.
    """
    cfg = config if isinstance(config, MarkerConfig) else MarkerConfig.from_dict(config)
    traces: list = []
    label = "Rotasjonspunkt" if which == "control" else "Nullpunkt"
    _marker_traces(cfg, 0.0, 0.0, 0.0, label, traces)

    fig = go.Figure(data=traces)
    fig.update_layout(
        scene=dict(
            aspectmode="data",
            xaxis_title="X / Øst (m)",
            yaxis_title="Y / Nord (m)",
            zaxis_title="Z (m)",
            camera=dict(eye=dict(x=1.6, y=-1.85, z=1.15)),
        ),
        margin=dict(l=0, r=0, t=10, b=10),
        showlegend=False,
        height=680,
    )
    return fig
