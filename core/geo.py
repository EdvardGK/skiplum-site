"""Geo helpers — Norwegian CRS registry, pyproj transforms, Kartverket address search.

All pure functions; no Streamlit. The CRS registry is the dropdown source; pyproj
does the actual lat/lon <-> projected conversions so address search can drop a
basepoint straight into the project CRS.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

from pyproj import Transformer
from pyproj.exceptions import ProjError

# ── Norwegian CRS registry ─────────────────────────────────────────────────────
# ETRS89-based, the datums actually used for Norwegian projects.
#   UTM   : ETRS89 / UTM zone NN   -> EPSG 258xx
#   NTM   : ETRS89 / NTM zone NN   -> EPSG 51xx  (zone z -> 5100 + z)
# Order matters: this list drives the dropdown.

@dataclass(frozen=True)
class CRSDef:
    epsg: int
    label: str
    short: str

CRS_REGISTRY: list[CRSDef] = [
    # NTM — preferred for building/site work (low distortion, local)
    CRSDef(5105, "ETRS89 / NTM zone 5", "NTM5"),
    CRSDef(5106, "ETRS89 / NTM zone 6", "NTM6"),
    CRSDef(5107, "ETRS89 / NTM zone 7", "NTM7"),
    CRSDef(5108, "ETRS89 / NTM zone 8", "NTM8"),
    CRSDef(5109, "ETRS89 / NTM zone 9", "NTM9"),
    CRSDef(5110, "ETRS89 / NTM zone 10", "NTM10"),
    CRSDef(5111, "ETRS89 / NTM zone 11", "NTM11"),
    CRSDef(5112, "ETRS89 / NTM zone 12", "NTM12"),
    CRSDef(5113, "ETRS89 / NTM zone 13", "NTM13"),
    CRSDef(5114, "ETRS89 / NTM zone 14", "NTM14"),
    CRSDef(5115, "ETRS89 / NTM zone 15", "NTM15"),
    CRSDef(5116, "ETRS89 / NTM zone 16", "NTM16"),
    CRSDef(5117, "ETRS89 / NTM zone 17", "NTM17"),
    CRSDef(5118, "ETRS89 / NTM zone 18", "NTM18"),
    CRSDef(5119, "ETRS89 / NTM zone 19", "NTM19"),
    CRSDef(5120, "ETRS89 / NTM zone 20", "NTM20"),
    # UTM — national / wide-area
    CRSDef(25832, "ETRS89 / UTM zone 32N", "UTM32"),
    CRSDef(25833, "ETRS89 / UTM zone 33N", "UTM33"),
    CRSDef(25834, "ETRS89 / UTM zone 34N", "UTM34"),
    CRSDef(25835, "ETRS89 / UTM zone 35N", "UTM35"),
    CRSDef(25836, "ETRS89 / UTM zone 36N", "UTM36"),
]

EPSG_GEODETIC = 4258   # ETRS89 lat/lon (Kartverket native)
EPSG_WGS84 = 4326      # for web maps / folium

_BY_EPSG = {c.epsg: c for c in CRS_REGISTRY}


def crs_by_epsg(epsg: int) -> Optional[CRSDef]:
    return _BY_EPSG.get(int(epsg))


def crs_labels() -> list[str]:
    return [f"{c.short} — {c.label} (EPSG:{c.epsg})" for c in CRS_REGISTRY]


def crs_from_label(label: str) -> CRSDef:
    for c in CRS_REGISTRY:
        if label.startswith(c.short + " "):
            return c
    return _BY_EPSG[5110]


# ── pyproj transforms ──────────────────────────────────────────────────────────

@lru_cache(maxsize=64)
def _transformer(src_epsg: int, dst_epsg: int) -> Transformer:
    # always_xy => inputs/outputs are (lon, lat) or (easting, northing)
    return Transformer.from_crs(src_epsg, dst_epsg, always_xy=True)


def latlon_to_crs(lat: float, lon: float, epsg: int) -> tuple[float, float]:
    """ETRS89 lat/lon -> (easting, northing) in target projected CRS."""
    t = _transformer(EPSG_GEODETIC, int(epsg))
    e, n = t.transform(lon, lat)
    return float(e), float(n)


def crs_to_latlon(easting: float, northing: float, epsg: int) -> tuple[float, float]:
    """(easting, northing) in source CRS -> WGS84 (lat, lon) for web maps."""
    t = _transformer(int(epsg), EPSG_WGS84)
    lon, lat = t.transform(easting, northing)
    return float(lat), float(lon)


def transform_xy(x: float, y: float, src_epsg: int, dst_epsg: int) -> tuple[float, float]:
    t = _transformer(int(src_epsg), int(dst_epsg))
    a, b = t.transform(x, y)
    return float(a), float(b)


# ── Kartverket address search ───────────────────────────────────────────────────
# https://ws.geonorge.no/adresser/v1/sok — returns representasjonspunkt in EPSG:4258.

KARTVERKET_URL = "https://ws.geonorge.no/adresser/v1/sok"


@dataclass
class AddressHit:
    label: str
    lat: float          # EPSG:4258
    lon: float
    municipality: str
    postnr: str
    poststed: str


def search_address(query: str, limit: int = 8, timeout: float = 8.0) -> list[AddressHit]:
    """Free-text address search via Kartverket. Returns hits with ETRS89 lat/lon.

    Network-dependent; raises requests exceptions on failure (caller handles).
    """
    import requests

    if not query or not query.strip():
        return []
    params = {
        "sok": query.strip(),
        "treffPerSide": limit,
        "side": 0,
        "asciiKompatibel": "false",
    }
    r = requests.get(KARTVERKET_URL, params=params, timeout=timeout,
                     headers={"User-Agent": "skiplum-site-marker/0.1"})
    r.raise_for_status()
    data = r.json()
    hits: list[AddressHit] = []
    for a in data.get("adresser", []):
        rp = a.get("representasjonspunkt") or {}
        lat, lon = rp.get("lat"), rp.get("lon")
        if lat is None or lon is None:
            continue
        text = a.get("adressetekst") or ""
        post = f'{a.get("postnummer", "")} {a.get("poststed", "")}'.strip()
        label = ", ".join(p for p in (text, post, a.get("kommunenavn", "")) if p)
        hits.append(AddressHit(
            label=label,
            lat=float(lat),
            lon=float(lon),
            municipality=a.get("kommunenavn", ""),
            postnr=str(a.get("postnummer", "")),
            poststed=a.get("poststed", ""),
        ))
    return hits


def suggest_ntm_zone(lon: float) -> int:
    """Recommend an NTM EPSG from longitude (NTM zone ~= round(lon)). Norway: 5..30."""
    zone = max(5, min(30, int(round(lon))))
    return 5100 + zone


def suggest_utm_zone(lon: float) -> int:
    """Recommend a UTM EPSG from longitude."""
    zone = int((lon + 180) // 6) + 1
    zone = max(31, min(36, zone))  # clamp to Norwegian range 32..36 roughly
    return 25800 + zone
