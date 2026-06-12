"""Parameterized IFC4 builder for the Skiplum basepoint / nullpunkt cylinder marker.

Single entry point: `build_marker_ifc(config) -> ifcopenshell.file`.
`ifc_to_bytes(f)` serializes it for download.

Geometry per marker:
  - solid cylinder (diameter, height, color)
  - flat north arrow on the top face (color), pointing grid-north (+Y)
  - voxel top label on the top face (e.g. "Lokalt nullpunkt")
  - three voxel rows wrapped around the wall (project+shorthand, owner, info)

Spatial:  IfcProject -> IfcSite -> IfcBuilding -> IfcBuildingStorey (names from config)
Georef:   optional IfcProjectedCRS + IfcMapConversion (pyproj-resolved EPSG)
Markers:  basepoint always; control marker (rotation) optional, at a local offset.
"""
from __future__ import annotations

import math
import time
import uuid

import ifcopenshell
import ifcopenshell.guid

from .config import MarkerConfig
from .voxel import (
    iter_voxels_flat, iter_voxels_on_cylinder,
    wall_char_height, wall_band_zs,
)

SCHEMA_DEFAULT = "IFC4"
_GUID_NS = uuid.UUID("9b7a0e7e-1f3c-4f76-9e11-5a17e0000001")


def stable_guid(seed: str) -> str:
    return ifcopenshell.guid.compress(uuid.uuid5(_GUID_NS, seed).hex)


def hex_to_rgb(h: str) -> tuple[float, float, float]:
    h = (h or "#000000").lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r = int(h[0:2], 16) / 255.0
    g = int(h[2:4], 16) / 255.0
    b = int(h[4:6], 16) / 255.0
    return (r, g, b)


# ── styling ─────────────────────────────────────────────────────────────────────

def make_surface_style(f, rgb):
    r, g, b = rgb
    colour = f.create_entity("IfcColourRgb", Red=float(r), Green=float(g), Blue=float(b))
    rendering = f.create_entity(
        "IfcSurfaceStyleRendering",
        SurfaceColour=colour, Transparency=0.0,
        DiffuseColour=colour, ReflectanceMethod="FLAT",
    )
    return f.create_entity("IfcSurfaceStyle", Side="BOTH", Styles=[rendering])


def _pt(f, x, y, z):
    return f.create_entity("IfcCartesianPoint", Coordinates=[float(x), float(y), float(z)])


def _face(f, loop_pts):
    loop = f.create_entity("IfcPolyLoop", Polygon=loop_pts)
    ob = f.create_entity("IfcFaceOuterBound", Bound=loop, Orientation=True)
    return f.create_entity("IfcFace", Bounds=[ob])


def _surface_model(f, faces):
    if not faces:
        return None
    fs = f.create_entity("IfcConnectedFaceSet", CfsFaces=faces)
    return f.create_entity("IfcFaceBasedSurfaceModel", FbsmFaces=[fs])


# ── cylinder ─────────────────────────────────────────────────────────────────────

def build_cylinder_mesh(f, cx, cy, z_bot, z_top, r_out, r_in=0.0, slices=72):
    """Cylinder as IfcFaceBasedSurfaceModel.

    r_in <= 0  -> solid disc (top/bottom disc + outer wall).
    r_in  > 0  -> hollow ring/shell (outer wall + inner wall + top & bottom annulus).
    """
    out_top, out_bot = [], []
    for i in range(slices):
        a = 2 * math.pi * i / slices
        ca, sa = math.cos(a), math.sin(a)
        out_top.append(_pt(f, cx + r_out * ca, cy + r_out * sa, z_top))
        out_bot.append(_pt(f, cx + r_out * ca, cy + r_out * sa, z_bot))

    faces = []

    if r_in <= 0:
        ctr_top = _pt(f, cx, cy, z_top)
        ctr_bot = _pt(f, cx, cy, z_bot)
        for i in range(slices):
            j = (i + 1) % slices
            faces.append(_face(f, [ctr_top, out_top[i], out_top[j]]))      # top disc
            faces.append(_face(f, [ctr_bot, out_bot[j], out_bot[i]]))      # bottom disc
            faces.append(_face(f, [out_bot[i], out_bot[j], out_top[j], out_top[i]]))  # wall
        return _surface_model(f, faces)

    in_top, in_bot = [], []
    for i in range(slices):
        a = 2 * math.pi * i / slices
        ca, sa = math.cos(a), math.sin(a)
        in_top.append(_pt(f, cx + r_in * ca, cy + r_in * sa, z_top))
        in_bot.append(_pt(f, cx + r_in * ca, cy + r_in * sa, z_bot))
    for i in range(slices):
        j = (i + 1) % slices
        faces.append(_face(f, [out_bot[i], out_bot[j], out_top[j], out_top[i]]))   # outer wall
        faces.append(_face(f, [in_bot[j], in_bot[i], in_top[i], in_top[j]]))       # inner wall
        faces.append(_face(f, [out_top[i], out_top[j], in_top[j], in_top[i]]))     # top annulus
        faces.append(_face(f, [out_bot[j], out_bot[i], in_bot[i], in_bot[j]]))     # bottom annulus
    return _surface_model(f, faces)


# ── north arrow (flat, on top face, pointing +Y) ─────────────────────────────────

def build_north_arrow_mesh(f, cx, cy, z_bot, z_top, radius):
    """A triangle pointing grid-north (+Y) on the NORTH rim of the shell.

    Full shell height (z_bot -> z_top), apex at the outer north edge. Length and
    width scale with the shell radius so it tracks the diameter.
    """
    L = radius * 0.45          # triangle length (base -> apex)
    w = radius * 0.22          # half base width
    apex = (cx, cy + radius + L)             # points north, OUTSIDE the shell
    bl = (cx - w, cy + radius)               # base on the outer north rim
    br = (cx + w, cy + radius)
    tri = [apex, bl, br]
    top = [_pt(f, x, y, z_top) for x, y in tri]
    bot = [_pt(f, x, y, z_bot) for x, y in tri]
    faces = [
        _face(f, [top[0], top[1], top[2]]),   # top
        _face(f, [bot[0], bot[2], bot[1]]),   # bottom
    ]
    for i in range(3):
        j = (i + 1) % 3
        faces.append(_face(f, [bot[i], bot[j], top[j], top[i]]))  # side walls
    return _surface_model(f, faces)


# ── voxel text ───────────────────────────────────────────────────────────────────

def build_voxel_text_flat(f, cx, cy, z_top, text, angle, char_height,
                          voxel_thickness=0.05):
    """Flat voxel text laid along `angle`, centered at (cx, cy), on the top face."""
    faces = []
    for spec in iter_voxels_flat(cx, cy, z_top, text, angle, char_height, voxel_thickness):
        faces.extend(_voxel_box(f, *spec))
    return _surface_model(f, faces)


def build_voxel_text_on_cylinder(f, cx, cy, z_center, text, radius,
                                 char_height=0.40, voxel_depth=0.04,
                                 face_compass_deg=180.0):
    """Voxel text wrapped on the cylinder wall, centered on a compass bearing.
    Default faces south (compass 180) — the typical plan/entrance viewpoint."""
    faces = []
    for spec in iter_voxels_on_cylinder(cx, cy, z_center, text, radius,
                                        char_height, voxel_depth, face_compass_deg):
        faces.extend(_voxel_box(f, *spec))
    return _surface_model(f, faces)


def _voxel_box(f, vx, vy, vz, ax, ay, bx, by, ha, hb, hv):
    """One voxel as 6 quad faces. (ax,ay)=axis A in-plane, (bx,by)=axis B in-plane,
    Z is vertical. ha/hb/hv are half-extents along A/B/Z."""
    corners = []
    for da in (-1, 1):
        for db in (-1, 1):
            for dv in (-1, 1):
                px = vx + da * ha * ax + db * hb * bx
                py = vy + da * ha * ay + db * hb * by
                pz = vz + dv * hv
                corners.append(_pt(f, px, py, pz))

    def C(da, db, dv):
        return corners[((da + 1) // 2) * 4 + ((db + 1) // 2) * 2 + (dv + 1) // 2]

    return [
        _face(f, [C(-1, -1, +1), C(+1, -1, +1), C(+1, +1, +1), C(-1, +1, +1)]),
        _face(f, [C(-1, +1, -1), C(+1, +1, -1), C(+1, -1, -1), C(-1, -1, -1)]),
        _face(f, [C(+1, -1, -1), C(+1, +1, -1), C(+1, +1, +1), C(+1, -1, +1)]),
        _face(f, [C(-1, +1, -1), C(-1, -1, -1), C(-1, -1, +1), C(-1, +1, +1)]),
        _face(f, [C(-1, -1, -1), C(+1, -1, -1), C(+1, -1, +1), C(-1, -1, +1)]),
        _face(f, [C(+1, +1, -1), C(-1, +1, -1), C(-1, +1, +1), C(+1, +1, +1)]),
    ]


# ── marker assembly ──────────────────────────────────────────────────────────────

def get_or_create_marker_type(f, owner_hist, project_name):
    cache = getattr(f, "_marker_type_cache", None)
    if cache is not None:
        return cache
    t = f.create_entity(
        "IfcGeographicElementType",
        GlobalId=stable_guid(f"{project_name}:type:Prosjektmarkør"),
        OwnerHistory=owner_hist,
        Name="Skiplum prosjektmarkør",
        Description="Sylindrisk basepoint-markør: sylinder + nordpil + voxel-tekst",
        ApplicableOccurrence="IfcGeographicElement",
        PredefinedType="USERDEFINED",
        ElementType="ProjectMarker",
    )
    f._marker_type_cache = t
    return t


def build_marker(f, owner_hist, body_ctx, placement, cfg: MarkerConfig,
                 seed_suffix, x, y, z, top_label):
    """Assemble one cylinder marker (geometry + styles + typed element)."""
    radius = cfg.radius_m
    height = cfg.height_m
    z_bot, z_top = z, z + height

    cyl_rgb = hex_to_rgb(cfg.cylinder_color)
    arrow_rgb = hex_to_rgb(cfg.arrow_color)
    text_rgb = hex_to_rgb(cfg.text_color)
    cyl_style = make_surface_style(f, cyl_rgb)
    arrow_style = make_surface_style(f, arrow_rgb)
    text_style = make_surface_style(f, text_rgb)

    body_items = []

    cyl = build_cylinder_mesh(f, x, y, z_bot, z_top, radius, r_in=cfg.inner_radius_m)
    if cyl is not None:
        f.create_entity("IfcStyledItem", Item=cyl, Styles=[cyl_style])
        body_items.append(cyl)

    arrow = build_north_arrow_mesh(f, x, y, z_bot, z_top, radius)
    if arrow is not None:
        f.create_entity("IfcStyledItem", Item=arrow, Styles=[arrow_style])
        body_items.append(arrow)

    # All text wraps the wall (facing south): top label first, then the rows.
    lines = [l for l in ([top_label] + cfg.text.wall_rows()) if l]
    wall_char_h = wall_char_height(height)
    text_radius = radius + 0.02
    for line, zlvl in zip(lines, wall_band_zs(z, height, len(lines))):
        mesh = build_voxel_text_on_cylinder(
            f, x, y, zlvl, line, text_radius,
            char_height=wall_char_h, voxel_depth=0.04, face_compass_deg=180.0,
        )
        if mesh is not None:
            f.create_entity("IfcStyledItem", Item=mesh, Styles=[text_style])
            body_items.append(mesh)

    body_rep = f.create_entity(
        "IfcShapeRepresentation",
        ContextOfItems=body_ctx, RepresentationIdentifier="Body",
        RepresentationType="SurfaceModel", Items=body_items,
    )
    prod_def = f.create_entity("IfcProductDefinitionShape", Representations=[body_rep])

    elem = f.create_entity(
        "IfcGeographicElement",
        GlobalId=stable_guid(f"{cfg.spatial.project_name}:marker:{seed_suffix}"),
        OwnerHistory=owner_hist,
        Name=f"{seed_suffix}: {top_label}" if top_label else seed_suffix,
        ObjectType=f"Skiplum prosjektmarkør - {seed_suffix}",
        ObjectPlacement=placement,
        Representation=prod_def,
        PredefinedType="USERDEFINED",
    )
    mtype = get_or_create_marker_type(f, owner_hist, cfg.spatial.project_name)
    f.create_entity(
        "IfcRelDefinesByType",
        GlobalId=stable_guid(f"{cfg.spatial.project_name}:type-rel:{seed_suffix}"),
        OwnerHistory=owner_hist, RelatingType=mtype, RelatedObjects=[elem],
    )
    return elem


# ── property sets ────────────────────────────────────────────────────────────────

def _prop(f, name, value, type_hint="IfcLabel"):
    if value is None or value == "":
        return None
    if type_hint == "IfcInteger":
        nv = f.create_entity("IfcInteger", int(value))
    elif type_hint == "IfcReal":
        nv = f.create_entity("IfcReal", float(value))
    elif type_hint == "IfcText":
        nv = f.create_entity("IfcText", str(value))
    else:
        nv = f.create_entity("IfcLabel", str(value)[:255])
    return f.create_entity("IfcPropertySingleValue", Name=name, NominalValue=nv)


def attach_pset(f, owner_hist, seed, related, pset_name, properties):
    props = [p for p in (_prop(f, n, v, t) for n, v, t in properties) if p is not None]
    if not props:
        return None
    pset = f.create_entity(
        "IfcPropertySet",
        GlobalId=stable_guid(f"{seed}:pset:{pset_name}"),
        OwnerHistory=owner_hist, Name=pset_name, HasProperties=props,
    )
    f.create_entity(
        "IfcRelDefinesByProperties",
        GlobalId=stable_guid(f"{seed}:psetrel:{pset_name}"),
        OwnerHistory=owner_hist, RelatingPropertyDefinition=pset, RelatedObjects=[related],
    )
    return pset


def build_georef_pset(f, owner_hist, cfg, marker, punkt_type, marker_offset):
    """marker_offset = this marker's offset from the basepoint (0,0,0 for Nullpunkt,
    (dx,dy,dz) for the control marker). Local* report the actual model-frame coords
    (which differ by export mode); E/N/H are the absolute world coords (mode-independent)."""
    g = cfg.georef
    bx, by, bz = cfg.basepoint_xyz()
    ox, oy, oz = marker_offset
    mx, my, mz = bx + ox, by + oy, bz + oz                  # model-frame (geometry) coords
    wx, wy, wz = g.easting + ox, g.northing + oy, g.height + oz  # absolute world coords
    props = [
        ("PunktType", punkt_type, "IfcLabel"),
        ("EPSG", f"EPSG:{g.epsg}", "IfcLabel"),
        ("CRS", g.crs_label, "IfcLabel"),
        ("GeodeticDatum", "EUREF89", "IfcLabel"),
        ("VerticalDatum", "NN2000", "IfcLabel"),
        ("LocalX_m", round(float(mx), 4), "IfcReal"),
        ("LocalY_m", round(float(my), 4), "IfcReal"),
        ("LocalZ_m", round(float(mz), 4), "IfcReal"),
        ("E_m", round(float(wx), 4), "IfcReal"),
        ("N_m", round(float(wy), 4), "IfcReal"),
        ("H_m", round(float(wz), 4), "IfcReal"),
    ]
    return attach_pset(f, owner_hist, f"{cfg.spatial.project_name}:{punkt_type}",
                       marker, "NOSKI_Georef", props)


# ── file scaffolding ─────────────────────────────────────────────────────────────

def new_file(cfg: MarkerConfig):
    f = ifcopenshell.file(schema=cfg.schema or SCHEMA_DEFAULT)

    person = f.create_entity("IfcPerson", FamilyName="Skiplum")
    org = f.create_entity("IfcOrganization", Name="Skiplum AS")
    pao = f.create_entity("IfcPersonAndOrganization", ThePerson=person, TheOrganization=org)
    app = f.create_entity(
        "IfcApplication", ApplicationDeveloper=org, Version="0.1",
        ApplicationFullName="Skiplum site marker", ApplicationIdentifier="skiplum-site-marker",
    )
    owner_hist = f.create_entity(
        "IfcOwnerHistory", OwningUser=pao, OwningApplication=app,
        ChangeAction="ADDED", CreationDate=int(time.time()),
    )

    length = f.create_entity("IfcSIUnit", UnitType="LENGTHUNIT", Name="METRE")
    area = f.create_entity("IfcSIUnit", UnitType="AREAUNIT", Name="SQUARE_METRE")
    volume = f.create_entity("IfcSIUnit", UnitType="VOLUMEUNIT", Name="CUBIC_METRE")
    angle = f.create_entity("IfcSIUnit", UnitType="PLANEANGLEUNIT", Name="RADIAN")
    units = f.create_entity("IfcUnitAssignment", Units=[length, area, volume, angle])

    origin = _pt(f, 0, 0, 0)
    z_dir = f.create_entity("IfcDirection", DirectionRatios=[0.0, 0.0, 1.0])
    x_dir = f.create_entity("IfcDirection", DirectionRatios=[1.0, 0.0, 0.0])
    wcs = f.create_entity("IfcAxis2Placement3D", Location=origin, Axis=z_dir, RefDirection=x_dir)

    model_ctx = f.create_entity(
        "IfcGeometricRepresentationContext", ContextType="Model",
        CoordinateSpaceDimension=3, Precision=1e-5, WorldCoordinateSystem=wcs,
        TrueNorth=f.create_entity("IfcDirection", DirectionRatios=[0.0, 1.0]),
    )
    body_ctx = f.create_entity(
        "IfcGeometricRepresentationSubContext", ContextIdentifier="Body",
        ContextType="Model", ParentContext=model_ctx, TargetView="MODEL_VIEW",
    )

    offset = cfg.map_conversion_offset()
    if offset is not None:
        projected = f.create_entity(
            "IfcProjectedCRS", Name=f"EPSG:{cfg.georef.epsg}",
            Description=cfg.georef.crs_label, GeodeticDatum="EUREF89",
            VerticalDatum="NN2000",
            MapUnit=f.create_entity("IfcSIUnit", UnitType="LENGTHUNIT", Name="METRE"),
        )
        f.create_entity(
            "IfcMapConversion", SourceCRS=model_ctx, TargetCRS=projected,
            Eastings=float(offset[0]), Northings=float(offset[1]),
            OrthogonalHeight=float(offset[2]),
            XAxisAbscissa=1.0, XAxisOrdinate=0.0, Scale=1.0,
        )

    project = f.create_entity(
        "IfcProject", GlobalId=stable_guid(f"{cfg.spatial.project_name}:project"),
        OwnerHistory=owner_hist, Name=cfg.spatial.project_name,
        UnitsInContext=units, RepresentationContexts=[model_ctx],
    )
    return f, project, owner_hist, body_ctx


def add_spatial(f, project, owner_hist, cfg: MarkerConfig):
    origin = _pt(f, 0, 0, 0)
    z_dir = f.create_entity("IfcDirection", DirectionRatios=[0.0, 0.0, 1.0])
    x_dir = f.create_entity("IfcDirection", DirectionRatios=[1.0, 0.0, 0.0])
    axes = f.create_entity("IfcAxis2Placement3D", Location=origin, Axis=z_dir, RefDirection=x_dir)
    placement = f.create_entity("IfcLocalPlacement", RelativePlacement=axes)
    s = cfg.spatial

    site = f.create_entity(
        "IfcSite", GlobalId=stable_guid(f"{s.project_name}:site"),
        OwnerHistory=owner_hist, Name=s.site_name, ObjectPlacement=placement,
        CompositionType="ELEMENT",
    )
    building = f.create_entity(
        "IfcBuilding", GlobalId=stable_guid(f"{s.project_name}:building"),
        OwnerHistory=owner_hist, Name=s.building_name, ObjectPlacement=placement,
        CompositionType="ELEMENT",
    )
    # One IfcBuildingStorey per inherited/configured floor, each at its elevation.
    storeys = []
    for i, st in enumerate(s.storeys):
        elev = float(st.get("elevation") or 0.0)
        st_axes = f.create_entity(
            "IfcAxis2Placement3D", Location=_pt(f, 0, 0, elev), Axis=z_dir, RefDirection=x_dir)
        st_placement = f.create_entity("IfcLocalPlacement", RelativePlacement=st_axes)
        storeys.append(f.create_entity(
            "IfcBuildingStorey", GlobalId=stable_guid(f"{s.project_name}:storey:{i}"),
            OwnerHistory=owner_hist, Name=st.get("name") or f"Etasje {i+1}",
            ObjectPlacement=st_placement, CompositionType="ELEMENT", Elevation=elev,
        ))

    f.create_entity(
        "IfcRelAggregates", GlobalId=stable_guid(f"{s.project_name}:agg:project-site"),
        OwnerHistory=owner_hist, RelatingObject=project, RelatedObjects=[site])
    f.create_entity(
        "IfcRelAggregates", GlobalId=stable_guid(f"{s.project_name}:agg:site-building"),
        OwnerHistory=owner_hist, RelatingObject=site, RelatedObjects=[building])
    f.create_entity(
        "IfcRelAggregates", GlobalId=stable_guid(f"{s.project_name}:agg:building-storeys"),
        OwnerHistory=owner_hist, RelatingObject=building, RelatedObjects=storeys)

    # Markers are contained in the floor nearest elevation 0 (the reference level).
    ref_storey = min(storeys, key=lambda st: abs(st.Elevation or 0.0))
    return ref_storey, placement


# ── top-level ─────────────────────────────────────────────────────────────────────

def build_marker_ifc(config) -> ifcopenshell.file:
    """Build the marker IFC from a MarkerConfig (or its dict form)."""
    cfg = config if isinstance(config, MarkerConfig) else MarkerConfig.from_dict(config)

    f, project, owner_hist, body_ctx = new_file(cfg)
    storey, placement = add_spatial(f, project, owner_hist, cfg)

    bx, by, bz = cfg.basepoint_xyz()
    base = build_marker(
        f, owner_hist, body_ctx, placement, cfg,
        seed_suffix="Nullpunkt", x=bx, y=by, z=bz,
        top_label=cfg.text.top_label,
    )
    related = [base]

    ctrl = None
    if cfg.control.enabled:
        cx = bx + cfg.control.dx
        cy = by + cfg.control.dy
        cz = bz + cfg.control.dz
        ctrl = build_marker(
            f, owner_hist, body_ctx, placement, cfg,
            seed_suffix="Rotasjonspunkt", x=cx, y=cy, z=cz,
            top_label=cfg.control.top_label,
        )
        related.append(ctrl)

    f.create_entity(
        "IfcRelContainedInSpatialStructure",
        GlobalId=stable_guid(f"{cfg.spatial.project_name}:contains:markers"),
        OwnerHistory=owner_hist, RelatingStructure=storey, RelatedElements=related,
    )

    if cfg.georef.enabled:
        build_georef_pset(f, owner_hist, cfg, base, "Nullpunkt", (0.0, 0.0, 0.0))
        if ctrl is not None:
            build_georef_pset(
                f, owner_hist, cfg, ctrl, "Rotasjonspunkt",
                (cfg.control.dx, cfg.control.dy, cfg.control.dz),
            )

    return f


def ifc_to_bytes(f: ifcopenshell.file) -> bytes:
    """Serialize an ifcopenshell file to SPF bytes for download."""
    try:
        return f.to_string().encode("utf-8")
    except Exception:
        import tempfile, os
        # fall back to a write/read round-trip in the app's own output dir
        out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output")
        os.makedirs(out_dir, exist_ok=True)
        tmp = os.path.join(out_dir, "_export_tmp.ifc")
        f.write(tmp)
        with open(tmp, "rb") as fh:
            return fh.read()
