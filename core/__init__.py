"""Skiplum site-marker core.

Pure-Python, UI-agnostic. Everything the Streamlit app does is a thin wrapper
over these modules, so the same logic can later back a FastAPI/React frontend:
the React client POSTs a JSON `MarkerConfig`, the server calls
`build_marker_ifc(config)` and streams back the .ifc bytes.
"""
from .config import (
    MarkerConfig,
    TextConfig,
    SpatialConfig,
    ControlMarkerConfig,
    GeorefConfig,
)
from .marker_builder import build_marker_ifc, ifc_to_bytes

__all__ = [
    "MarkerConfig",
    "TextConfig",
    "SpatialConfig",
    "ControlMarkerConfig",
    "GeorefConfig",
    "build_marker_ifc",
    "ifc_to_bytes",
]
