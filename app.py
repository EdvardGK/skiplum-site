"""Skiplum Site Marker — Streamlit host for a custom HTML/CSS component.

The whole control UI (geometry, colors, text, georef, structure) is a bidirectional
Streamlit component under `frontend/` (HTML/CSS/JS, Three.js + Leaflet + proj4). It
returns the live MarkerConfig to Python. Streamlit keeps the file-handling logic:
`st.file_uploader` (inherit structure/georef from an IFC, via ifcfast) and
`st.download_button` (the built IFC). All IFC logic stays in `core/`.

Run:  streamlit run app.py
"""
from __future__ import annotations

import os

import streamlit as st
import streamlit.components.v1 as components

from core.config import MarkerConfig
from core.marker_builder import build_marker_ifc, ifc_to_bytes
from core.ifc_inspect import inspect_ifc_bytes

st.set_page_config(page_title="Lokasjonsplan-generator", page_icon="🟡",
                   layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
<style>
  .block-container { max-width: 1700px; padding: 1.0rem 2.2rem 2rem; }
  header[data-testid="stHeader"] { background: transparent; }
  #MainMenu, footer, .stDeployButton { visibility: hidden; }
  [data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"] { display: none; }
  iframe { border: none; }
  .app-header { background: linear-gradient(135deg,#E69930 0%,#d8b066 100%);
    color:#1f2937; padding:0.7rem 1.2rem; border-radius:10px; margin-bottom:0.6rem; }
  .app-header h1 { margin:0; font-size:1.18rem; font-weight:700; }
  .app-header p { margin:0.1rem 0 0; font-size:0.76rem; opacity:0.82; }
</style>
<div class="app-header"><h1>🟡 Lokasjonsplan-generator</h1>
<p>Basepoint-/nullpunkt-markør med voxel-tekst, nordpil og georef → IFC4</p></div>
""", unsafe_allow_html=True)

ss = st.session_state

_FRONTEND = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend")
_marker_component = components.declare_component("skiplum_site_marker", path=_FRONTEND)

# ── upload reference IFC (Streamlit + ifcfast) → inherited structure/georef ──────
up = st.file_uploader("Last opp referanse-IFC for å arve struktur + georef (ifcfast)", type=["ifc"])
if up is not None and ss.get("_last_upload") != up.name:
    ss["_last_upload"] = up.name
    try:
        with st.spinner("Leser IFC med ifcfast…"):
            inh = inspect_ifc_bytes(up.getvalue())
        ss["inherited"] = inh.to_dict()
        st.success(f"Arvet {len(inh.storeys)} etasje(r)"
                   + (f", georef EPSG:{inh.epsg}" if inh.epsg else ""))
    except Exception as e:
        st.error(f"Kunne ikke lese IFC: {e}")

# ── build + download toolbar (Streamlit) — kept ABOVE the component so it stays in
#    view; uses the latest config the component returned (no scrolling to act). ──────
cfg_dict = ss.get("config")
if cfg_dict:
    cfg = MarkerConfig.from_dict(cfg_dict)
    default_name = f"{cfg.spatial.project_name.replace(' ', '_')}_BIMK_Nullpunkt.ifc"
    c1, c2, c3 = st.columns([3, 1, 1])
    fname = c1.text_input("Filnavn", default_name, label_visibility="collapsed")
    if c2.button("⚙️ Bygg IFC", type="primary", use_container_width=True):
        with st.spinner("Bygger IFC…"):
            f = build_marker_ifc(cfg)
            ss["ifc_data"], ss["ifc_name"] = ifc_to_bytes(f), fname
        st.toast(f"Bygget {len(f.by_type('IfcGeographicElement'))} markør(er) · "
                 f"{len(ss['ifc_data'])/1024:.0f} KB · {len(cfg.spatial.storeys)} etasje(r)")
    if ss.get("ifc_data"):
        c3.download_button("⬇️ Last ned IFC", data=ss["ifc_data"],
                           file_name=ss.get("ifc_name", default_name),
                           mime="application/x-step", use_container_width=True)
else:
    st.caption("Juster markøren under — bygg og last ned vises her når konfigurasjonen er klar.")

# ── the custom UI component (returns the live config) ────────────────────────────
# A stable key keeps the iframe from remounting (and resetting its JS state, e.g.
# the local/world toggle) when sibling widgets above it change.
config = _marker_component(inherited=ss.get("inherited"), default=None, key="marker")
if config:
    ss["config"] = config
