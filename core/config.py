"""MarkerConfig — the single JSON-serializable contract between UI and builder.

A React frontend would POST exactly this shape; `MarkerConfig.from_dict` rebuilds
it server-side and hands it to `build_marker_ifc`. Colors are hex strings (UI- and
JSON-friendly); the builder converts to 0..1 RGB internally.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional


# ── Text ──────────────────────────────────────────────────────────────────────

@dataclass
class TextConfig:
    """The four editable voxel-text slots.

    top_label   — text on the cylinder TOP face (per-marker; defaults differ for
                  the basepoint vs the control marker).
    row1/2/3    — three rows wrapped around the cylinder WALL.
    """
    top_label: str = "Lokalt nullpunkt"
    row1: str = "Prosjektnavn (PRO)"      # project name + shorthand
    row2: str = "Byggherre"               # TEXT 1, e.g. project owner
    row3: str = "Info"                    # TEXT 2, e.g. extra info

    def wall_rows(self) -> list[str]:
        return [self.row1, self.row2, self.row3]


# ── Spatial structure (IfcProject -> Site -> Building -> Storey) ───────────────

@dataclass
class SpatialConfig:
    project_name: str = "Prosjekt"
    site_name: str = "Tomt"
    building_name: str = "Bygning"
    # one entry per floor: {"name": str, "elevation": float}
    storeys: list = field(default_factory=lambda: [{"name": "Referanse", "elevation": 0.0}])

    @classmethod
    def from_dict(cls, d) -> "SpatialConfig":
        d = dict(d or {})
        # migrate legacy single storey_name -> storeys list
        if "storeys" not in d and "storey_name" in d:
            d["storeys"] = [{"name": d.get("storey_name") or "Referanse", "elevation": 0.0}]
        d.pop("storey_name", None)
        storeys = d.get("storeys") or [{"name": "Referanse", "elevation": 0.0}]
        # normalize entries
        norm = []
        for s in storeys:
            name = (s.get("name") or "").strip() if isinstance(s, dict) else str(s).strip()
            if not name:
                continue
            elev = float(s.get("elevation") or 0.0) if isinstance(s, dict) else 0.0
            norm.append({"name": name, "elevation": elev})
        d["storeys"] = norm or [{"name": "Referanse", "elevation": 0.0}]
        return cls(**d)

    def storey_names(self) -> list[str]:
        return [s["name"] for s in self.storeys]


# ── Control marker (Rotasjonspunkt / rotation control) ────────────────────────

@dataclass
class ControlMarkerConfig:
    enabled: bool = False
    top_label: str = "Lokal rotasjonskontroll"
    # Offset of the control marker from the basepoint, in metres (local frame).
    dx: float = 50.0
    dy: float = 0.0
    dz: float = 0.0


# ── Georeferencing ────────────────────────────────────────────────────────────

@dataclass
class GeorefConfig:
    """When enabled, the marker carries an IfcProjectedCRS + IfcMapConversion.

    easting/northing/height are the basepoint expressed in WORLD coordinates of
    the chosen CRS.

    export_local:
        True  -> basepoint geometry sits at (0,0,0); world position is carried
                 entirely by IfcMapConversion (Eastings/Northings/Height).
        False -> basepoint geometry sits at the world coordinates; IfcMapConversion
                 declares the CRS with a zero shift.
    """
    enabled: bool = False
    epsg: int = 5110                       # default NTM10
    crs_label: str = "ETRS89 / NTM zone 10"
    easting: float = 0.0
    northing: float = 0.0
    height: float = 0.0
    export_local: bool = True
    # For display / map only — basepoint as lat/lon (EPSG:4326), filled by the UI.
    lat: Optional[float] = None
    lon: Optional[float] = None


# ── No-georef origin (editable) ───────────────────────────────────────────────

@dataclass
class OriginConfig:
    """Basepoint position when georef is OFF (defaults to 0,0,0, editable)."""
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


# ── Top-level config ──────────────────────────────────────────────────────────

@dataclass
class MarkerConfig:
    # Geometry
    diameter_m: float = 10.0
    height_m: float = 3.0
    wall_thickness_m: float = 0.5   # ring wall; 0 (or >= radius) => solid disc

    # Colors (hex, e.g. "#E69930")
    cylinder_color: str = "#E69930"        # gold
    arrow_color: str = "#26A69A"           # teal
    text_color: str = "#FFE600"            # bright yellow

    # Content
    text: TextConfig = field(default_factory=TextConfig)
    spatial: SpatialConfig = field(default_factory=SpatialConfig)
    control: ControlMarkerConfig = field(default_factory=ControlMarkerConfig)
    georef: GeorefConfig = field(default_factory=GeorefConfig)
    origin: OriginConfig = field(default_factory=OriginConfig)

    schema: str = "IFC4"

    # ── (de)serialization ────────────────────────────────────────────────────
    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "MarkerConfig":
        d = dict(d or {})
        d["text"] = TextConfig(**(d.get("text") or {}))
        d["spatial"] = SpatialConfig.from_dict(d.get("spatial"))
        d["control"] = ControlMarkerConfig(**(d.get("control") or {}))
        d["georef"] = GeorefConfig(**(d.get("georef") or {}))
        d["origin"] = OriginConfig(**(d.get("origin") or {}))
        return cls(**d)

    # ── derived helpers ────────────────────────────────────────────────────────
    # diameter_m is the INNER (hole) diameter — the ring grows OUTWARD from it by
    # wall_thickness_m. So a modeler can place an R = d/2 marker at 0,0,z that sits
    # inside the hole without clashing with the ring.
    @property
    def inner_radius_m(self) -> float:
        """The marked inner edge: radius = diameter / 2."""
        return self.diameter_m / 2.0

    @property
    def radius_m(self) -> float:
        """Outer radius (arrow / text / footprint sit here) = inner + wall."""
        return self.inner_radius_m + max(0.0, self.wall_thickness_m)

    @property
    def is_solid(self) -> bool:
        return self.wall_thickness_m <= 0.0

    def basepoint_xyz(self) -> tuple[float, float, float]:
        """Where the basepoint geometry is placed in the IFC model frame."""
        if self.georef.enabled and not self.georef.export_local:
            return (self.georef.easting, self.georef.northing, self.georef.height)
        if not self.georef.enabled:
            return (self.origin.x, self.origin.y, self.origin.z)
        return (0.0, 0.0, 0.0)  # georef + local export

    def map_conversion_offset(self) -> Optional[tuple[float, float, float]]:
        """IfcMapConversion Eastings/Northings/Height, or None if no georef."""
        if not self.georef.enabled:
            return None
        if self.georef.export_local:
            return (self.georef.easting, self.georef.northing, self.georef.height)
        return (0.0, 0.0, 0.0)  # world export: geometry already absolute
