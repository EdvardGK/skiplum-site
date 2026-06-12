"""Inspect an uploaded IFC to inherit its spatial structure (project/site/building + all floors).

Floors and project name come from **ifcfast** (Rust-backed tier-1 parse, ~0.5 s cold /
~50 ms cached on big files — ifcopenshell.open is far slower). Site/building names and
georeferencing (IfcMapConversion / IfcProjectedCRS) come from a lightweight regex scan
of the STEP text. ifcopenshell is used only as a fallback if ifcfast is unavailable.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class InheritedSpatial:
    project_name: str = ""
    site_name: str = ""
    building_name: str = ""
    storeys: list = field(default_factory=list)   # [{"name", "elevation"}]
    # georef, if the source file carries an IfcMapConversion
    epsg: Optional[int] = None
    crs_label: Optional[str] = None
    easting: Optional[float] = None
    northing: Optional[float] = None
    height: Optional[float] = None

    def to_dict(self) -> dict:
        return asdict(self)


def _output_dir() -> str:
    d = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output")
    os.makedirs(d, exist_ok=True)
    return d


# ── STEP text scan for the bits ifcfast doesn't surface ──────────────────────────
_RE_SITE = re.compile(r"IFCSITE\('[^']*',[^,]*,'([^']*)'", re.IGNORECASE)
_RE_BUILDING = re.compile(r"IFCBUILDING\('[^']*',[^,]*,'([^']*)'", re.IGNORECASE)
_RE_MAPCONV = re.compile(
    r"IFCMAPCONVERSION\([^,]*,[^,]*,([-\d.eE+]+),([-\d.eE+]+),([-\d.eE+]*)", re.IGNORECASE)
_RE_PROJCRS = re.compile(r"IFCPROJECTEDCRS\('([^']*)'", re.IGNORECASE)


# Spatial structure, contexts and IfcMapConversion are defined early in the file
# (before the geometry bulk), so a head-window scan is enough and stays O(1) on size.
_SCAN_HEAD_BYTES = 8 * 1024 * 1024


def _scan_text(path: str, res: InheritedSpatial) -> None:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            text = fh.read(_SCAN_HEAD_BYTES)
    except Exception:
        return

    if not res.site_name:
        m = _RE_SITE.search(text)
        if m:
            res.site_name = m.group(1)
    if not res.building_name:
        m = _RE_BUILDING.search(text)
        if m:
            res.building_name = m.group(1)

    m = _RE_MAPCONV.search(text)
    if m:
        try:
            res.easting = float(m.group(1))
            res.northing = float(m.group(2))
            res.height = float(m.group(3)) if m.group(3) else 0.0
        except ValueError:
            pass
    m = _RE_PROJCRS.search(text)
    if m:
        name = m.group(1)
        res.crs_label = name
        digits = "".join(ch for ch in name if ch.isdigit())
        if digits:
            res.epsg = int(digits)


def inspect_ifc_bytes(data: bytes) -> InheritedSpatial:
    """Parse raw IFC bytes and return the inherited spatial structure (all floors)."""
    tmp = os.path.join(_output_dir(), "_upload_tmp.ifc")
    with open(tmp, "wb") as fh:
        fh.write(data)

    res = InheritedSpatial()

    # ── fast path: ifcfast for project name + all storeys ──
    try:
        import ifcfast

        m = ifcfast.open(tmp)
        summary = m.summary()
        res.project_name = summary.get("project_name") or ""
        scale = summary.get("unit_scale") or 1.0
        storeys = [
            {"name": r.name or "", "elevation": round((r.elevation or 0.0) * scale, 4)}
            for r in m.storeys
        ]
        storeys.sort(key=lambda s: s["elevation"])
        res.storeys = storeys
        _scan_text(tmp, res)
        if res.storeys:
            return res
    except Exception:
        pass

    # ── fallback: ifcopenshell ──
    return _inspect_ifcopenshell(tmp)


def _inspect_ifcopenshell(path: str) -> InheritedSpatial:
    import ifcopenshell

    f = ifcopenshell.open(path)

    def first_name(cls):
        for e in f.by_type(cls):
            if getattr(e, "Name", None):
                return e.Name
        return ""

    storeys = []
    for s in f.by_type("IfcBuildingStorey"):
        try:
            elev = float(s.Elevation) if s.Elevation is not None else 0.0
        except (TypeError, ValueError):
            elev = 0.0
        storeys.append({"name": s.Name or "", "elevation": elev})
    storeys.sort(key=lambda x: x["elevation"])

    res = InheritedSpatial(
        project_name=first_name("IfcProject"),
        site_name=first_name("IfcSite"),
        building_name=first_name("IfcBuilding"),
        storeys=storeys,
    )
    try:
        mcs = f.by_type("IfcMapConversion")
        if mcs:
            mc = mcs[0]
            res.easting = float(mc.Eastings) if mc.Eastings is not None else None
            res.northing = float(mc.Northings) if mc.Northings is not None else None
            res.height = float(mc.OrthogonalHeight) if mc.OrthogonalHeight is not None else None
            crs = mc.TargetCRS
            if crs is not None:
                name = getattr(crs, "Name", "") or ""
                res.crs_label = getattr(crs, "Description", None) or name
                digits = "".join(ch for ch in name if ch.isdigit())
                if digits:
                    res.epsg = int(digits)
    except Exception:
        pass
    return res
