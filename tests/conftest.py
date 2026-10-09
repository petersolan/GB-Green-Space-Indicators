"""Tests run on tiny synthetic data in a temporary local lake.

The Azurite test (test_lake_azurite) runs only when the emulator is reachable
(docker compose up -d azurite, or the CI service container).
"""

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Point, box

CRS = "EPSG:27700"


@pytest.fixture(autouse=True)
def local_lake(tmp_path, monkeypatch):
    """Every test gets its own empty local lake."""
    monkeypatch.setenv("LAKE_BACKEND", "local")
    monkeypatch.setenv("LAKE_DIR", str(tmp_path / "lake"))
    from greenidx import lake

    lake.backend.cache_clear()
    lake.filesystem.cache_clear()
    yield
    lake.backend.cache_clear()
    lake.filesystem.cache_clear()


@pytest.fixture
def sites() -> gpd.GeoDataFrame:
    """One 100 x 100 m green site (1 ha) with its corner at the origin."""
    return gpd.GeoDataFrame(
        {"site_id": [1], "area_m2": [10_000.0], "types": ["Public Park Or Garden"]},
        geometry=[box(0, 0, 100, 100)],
        crs=CRS,
    )


@pytest.fixture
def addresses() -> gpd.GeoDataFrame:
    """Addresses east of the site: 50 m, 299 m and 301 m from its edge, and one far away."""
    xs = [150, 399, 401, 5_000]
    return gpd.GeoDataFrame(
        {
            "uprn": pd.array([1, 2, 3, 4], dtype="int64"),
            "lad26cd": ["E07000041"] * 4,
            "lsoa21cd": ["E01000001", "E01000001", "E01000002", "E01000002"],
            "msoa21cd": ["E02000001"] * 4,
            "population": [2.0, 3.0, 4.0, 1.0],
        },
        geometry=[Point(x, 50) for x in xs],
        crs=CRS,
    )
