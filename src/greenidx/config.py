"""Settings: the area, indicator definitions and where the lake lives.

Storage comes from the environment (.env), so the same code runs against a
local folder, the Azurite emulator or a real Azure storage account.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"  # downloads and local inputs; never part of the lake
CRS = "EPSG:27700"  # British National Grid: metres, as GB statistics and mapping use

# Devon: the eight districts of Devon County plus the two unitary authorities
AREAS = {
    "E07000040": "East Devon",
    "E07000041": "Exeter",
    "E07000042": "Mid Devon",
    "E07000043": "North Devon",
    "E07000044": "South Hams",
    "E07000045": "Teignbridge",
    "E07000046": "Torridge",
    "E07000047": "West Devon",
    "E06000026": "Plymouth",
    "E06000027": "Torbay",
}

# Outputs of the GB-Census-Population-Map project: population per address
CENSUS_DIR = Path(os.environ.get("CENSUS_DIR", ROOT.parent / "Census-distribution" / "data" / "processed"))
# OS Open Zoomstack (green space layer)
ZOOMSTACK = Path(
    os.environ.get(
        "ZOOMSTACK_GPKG",
        ROOT.parent / "Census-distribution" / "data" / "footprints" / "OS_Open_Zoomstack.gpkg",
    )
)

# ONS Open Geography Portal feature services (boundaries, generalised to 20 m)
LAD_SERVICE = (
    "https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services/"
    "LAD_MAY_2025_UK_BGC_V2/FeatureServer/0/query"
)
LSOA_SERVICE = (
    "https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services/"
    "Lower_layer_Super_Output_Areas_December_2021_Boundaries_EW_BGC_V5/FeatureServer/0/query"
)


@dataclass(frozen=True)
class GreenSpaceIndicator:
    """Residents within a straight-line distance of public green space of a minimum size.

    WHO Europe (Urban green spaces: a brief for action, 2017) suggests everyone
    should live within 300 m of a public green space of at least 0.5 ha.
    """

    distance_m: float = 300.0
    min_area_m2: float = 5_000.0  # 0.5 ha
    # Zoomstack green space types open to the public for recreation. Golf
    # courses, tennis courts and bowling greens are restricted; cemeteries and
    # religious grounds are open but not for play or sport, so they're left out
    public_types: tuple[str, ...] = (
        "Public Park Or Garden",
        "Playing Field",
        "Play Space",
        "Allotments Or Community Growing Spaces",
        "Other Sports Facility",
    )


@dataclass(frozen=True)
class NdviIndicator:
    """Summer greenness from Sentinel-2: median NDVI of clear observations."""

    collection: str = "sentinel-2-l2a"
    start: str = "2024-06-01"
    end: str = "2024-08-31"
    max_cloud_pct: float = 30.0
    resolution_m: float = 20.0
    vegetated_ndvi: float = 0.5  # NDVI above this counts as vegetation


@dataclass(frozen=True)
class Settings:
    green: GreenSpaceIndicator = field(default_factory=GreenSpaceIndicator)
    ndvi: NdviIndicator = field(default_factory=NdviIndicator)
    reference_year: int = 2024
