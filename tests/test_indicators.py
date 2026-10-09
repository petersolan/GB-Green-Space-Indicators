"""Green space sites, access and NDVI zonal statistics on hand-made data."""

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import xarray as xr
from odc.geo.geobox import GeoBox
from odc.geo.xr import xr_zeros
from shapely.geometry import box

from greenidx import gold_access, gold_ndvi, silver
from greenidx.config import Settings

CRS = "EPSG:27700"


def test_touching_parcels_merge_into_one_site():
    # Two 50 x 60 m parcels (0.3 ha each) touch: one 0.6 ha site, which qualifies.
    # A separate 0.3 ha parcel is too small, and the golf course isn't public
    green = gpd.GeoDataFrame(
        {"type": ["Public Park Or Garden", "Playing Field", "Play Space", "Golf Course"]},
        geometry=[box(0, 0, 50, 60), box(50, 0, 100, 60), box(500, 0, 550, 60), box(0, 500, 200, 700)],
        crs=CRS,
    )
    sites = silver.green_sites(green, Settings())
    assert len(sites) == 1
    assert sites.loc[0, "area_m2"] == pytest.approx(6_000)
    assert sites.loc[0, "types"] == "Playing Field; Public Park Or Garden"


def test_addresses_schema_rejects_duplicates(addresses):
    lad = gpd.GeoDataFrame({"lad_code": ["E07000041"]}, geometry=[box(-1e4, -1e4, 1e4, 1e4)], crs=CRS)
    with pytest.raises(Exception, match="uprn"):
        silver.addresses(pd.concat([addresses, addresses]), lad)


def test_within_300m_uses_the_site_edge(addresses, sites):
    within = gold_access.within_distance(addresses, sites, 300.0)
    assert within.tolist() == [True, True, False, False]


def test_nearest_distance_capped(addresses, sites):
    d = gold_access.nearest_site(addresses, sites)
    assert d.iloc[:3].tolist() == pytest.approx([50, 299, 301])
    assert np.isnan(d.iloc[3])  # beyond 2 km


def test_aggregate_shares_by_residents(addresses, sites):
    detail = pd.DataFrame(
        {
            "uprn": addresses["uprn"],
            "lad26cd": addresses["lad26cd"],
            "lsoa21cd": addresses["lsoa21cd"],
            "population": addresses["population"],
            "within_300m": gold_access.within_distance(addresses, sites, 300.0),
            "nearest_site_m": gold_access.nearest_site(addresses, sites),
        }
    )
    areas = pd.DataFrame(
        {
            "area_type": ["LAD", "LSOA", "LSOA"],
            "area_code": ["E07000041", "E01000001", "E01000002"],
            "area_name": ["Exeter", "A", "B"],
            "parent_code": [None, "E07000041", "E07000041"],
        }
    )
    out = gold_access.aggregate(detail, areas).set_index("area_code")
    assert out.loc["E01000001", "share_within_300m_pct"] == 100
    assert out.loc["E01000002", "share_within_300m_pct"] == 0
    # District: 5 of 10 residents
    assert out.loc["E07000041", "share_within_300m_pct"] == pytest.approx(50)


def test_weighted_median_counts_far_residents_as_furthest():
    # NaN (further than 2 km) sorts last, so it can be the median
    assert gold_access.weighted_median(np.array([10.0, np.nan]), np.array([1.0, 3.0])) != 10.0
    assert gold_access.weighted_median(np.array([10.0, 20.0, 30.0]), np.array([1.0, 1.0, 1.0])) == 20.0


def test_ndvi_zonal_statistics():
    # 4 x 4 pixels of 20 m: left half NDVI 0.8, right half 0.2, one pixel cloudy
    geobox = GeoBox.from_bbox((0, 0, 80, 80), crs=CRS, resolution=20)
    ndvi = xr_zeros(geobox, dtype="float32")
    ndvi[:, :2] = 0.8
    ndvi[:, 2:] = 0.2
    ndvi[0, 0] = np.nan
    areas = gpd.GeoDataFrame(
        {"area_type": ["LSOA"], "area_code": ["E01000001"], "area_name": ["A"], "parent_code": ["E07000041"]},
        geometry=[box(0, 0, 80, 80)],
        crs=CRS,
    )
    stats = gold_ndvi.zonal(xr.DataArray(ndvi), areas, threshold=0.5).iloc[0]
    assert stats["pixels"] == 16
    assert stats["clear_coverage_pct"] == pytest.approx(100 * 15 / 16)
    assert stats["mean_ndvi"] == pytest.approx((7 * 0.8 + 8 * 0.2) / 15, abs=1e-6)
    assert stats["vegetated_pct"] == pytest.approx(100 * 7 / 15)
