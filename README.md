# Skiplum Site Marker

Streamlit app to build a Skiplum **basepoint / nullpunkt cylinder marker** as an
IFC4 file — the "golden cylinder" concept from HI90 and Sophies Minde, generalized
and parameterized.

```
streamlit run app.py
```

## Flow

Persistent header + a persistent 3D viewer (the marker); the other two columns swap
content per step. State persists between steps and you can jump via the stepper:

1. **Markørdesign** — geometry, colors, text, control marker
2. **Referanse & struktur** — upload a reference IFC to inherit project/site/building +
   **all floors** *and* discover any existing MapConversion/CRS (via **ifcfast**);
   edit the spatial structure
3. **Plassering** — georef CRS + coordinates (pre-filled from the reference IFC if found),
   Kartverket address search + OSM map, or a local origin
4. **Last ned** — review, build, download

Putting the reference IFC before placement means an inherited georef pre-fills the CRS
and coordinates in step 3.

## What it does

- **Cylinder marker** — solid cylinder with configurable **diameter, height**, and
  separate colors for **cylinder / north arrow / text**.
- **Voxel text** — a 5×7 bitmap font (incl. Æ Ø Å) rendered as 3D voxels with
  curve-aware spacing that wraps correctly around any cylinder radius:
  - top label (default `Lokalt nullpunkt`)
  - project name + shorthand, TEXT 1 (e.g. owner), TEXT 2 (e.g. info) wrapped on the wall
- **North arrow** on the top face, pointing grid-north (+Y).
- **Spatial structure** — set IfcProject / Site / Building names and **all floors**
  (name + elevation), or **upload an IFC to inherit** the full structure incl. every
  storey (a popup lets you accept or edit before applying). Markers are placed in the
  floor nearest elevation 0.
- **Control marker** toggle — adds a second cylinder (`Lokal rotasjonskontroll`) at a
  configurable offset.
- **Georeferencing** toggle:
  - Norwegian CRS dropdown (NTM 5–20, UTM 32–36) resolved through **pyproj**.
  - Enter basepoint world coordinates, or use **Kartverket address search** to drop
    the point — shown on an **OpenStreetMap** map with the cylinder footprint at true
    scale and color.
  - Export **local** (basepoint at 0,0,0 + `IfcMapConversion` carrying the world offset)
    or **world** coordinates. IFC4 by default.
  - Without georef: a plain marker at an editable origin.

## Architecture (React-portable)

All logic is UI-agnostic in [`core/`](core/). The UI only assembles a
`MarkerConfig` and calls `build_marker_ifc()`. A future React frontend would POST the
same JSON config to a FastAPI wrapper and stream back the `.ifc` bytes — no logic
needs to move.

| File | Responsibility |
|---|---|
| `core/config.py` | `MarkerConfig` dataclasses — the JSON contract (`to_dict`/`from_dict`) |
| `core/marker_builder.py` | `build_marker_ifc(config) -> ifcopenshell.file`, `ifc_to_bytes()` |
| `core/fonts.py` | 5×7 voxel font |
| `core/geo.py` | CRS registry, pyproj transforms, Kartverket address search |
| `core/ifc_inspect.py` | inherit structure from an IFC — **ifcfast** for project + all floors (fast on big files), text scan for site/building + MapConversion/CRS, ifcopenshell fallback |
| `core/preview.py` | Plotly 3D preview from a config |
| `app.py` | Streamlit UI |

## Notes

- Georef datum assumed EUREF89 / NN2000 (Norwegian standard).
- Marker entity: `IfcGeographicElement` + shared `IfcGeographicElementType`
  ("Skiplum prosjektmarkør"), `NOSKI_Georef` pset per marker.
- Generated IFCs and upload scratch land in `output/` (not auto-deleted).
