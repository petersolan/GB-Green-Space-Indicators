"""Silver: cleaned, validated and conformed to the indicator definitions.

  areas         LADs and LSOAs in one table (area_type, area_code, area_name)
  addresses     addresses with residents; checked for duplicates, coordinates
                and that they fall in their district
  green_sites   public green space as sites: touching parcels of public types
                merge into one site (a park next to a playing field is one
                place to visit), then sites under the minimum size are dropped

Checks use pandera schemas, so a bad input stops the run with a clear message
rather than producing quietly wrong indicators.
"""

from __future__ import annotations

import logging

import geopandas as gpd
import numpy as np
import pandas as pd
import pandera.pandas as pa
import shapely

from greenidx import lake
from greenidx.config import CRS, Settings

log = logging.getLogger(__name__)
MAX_OUTSIDE_SHARE = 0.005  # addresses allowed outside their district (boundary generalisation)

ADDRESSES = pa.DataFrameSchema(
    {
        "uprn": pa.Column("int64", unique=True),
        "lad26cd": pa.Column(str, pa.Check.str_matches(r"^E0[67]\d{6}$")),
        "lsoa21cd": pa.Column(str, pa.Check.str_matches(r"^E01\d{6}$")),
        "msoa21cd": pa.Column(str, pa.Check.str_matches(r"^E02\d{6}$")),
        "population": pa.Column(float, pa.Check.ge(0)),
    },
    strict=False,
)
GREEN_SITES = pa.DataFrameSchema(
    {
        "site_id": pa.Column("int64", unique=True),
        "area_m2": pa.Column(float, pa.Check.gt(0)),
        "types": pa.Column(str),
    },
    strict=False,
)


def areas(lad: gpd.GeoDataFrame, lsoa: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """One table of reporting areas, each LSOA tagged with the district it lies in.

    LSOAs nest exactly in districts, so an LSOA's parent is the district that
    contains a point inside it. LSOAs that come in only because a few addresses
    near the county edge are coded to them (in Cornwall, Dorset, Somerset) lie
    outside every district and are not reporting areas.
    """
    points = lsoa.assign(geometry=lsoa.representative_point())
    parent = (
        points.sjoin(lad[["lad_code", "geometry"]], predicate="within").groupby(level=0)["lad_code"].first()
    )
    lsoa = lsoa.assign(parent_code=parent.reindex(lsoa.index))
    outside = lsoa["parent_code"].isna()
    if outside.any():
        log.info(
            "%s LSOAs outside the area dropped: %s",
            int(outside.sum()),
            ", ".join(lsoa.loc[outside, "lsoa_name"]),
        )
    lad = lad.assign(area_type="LAD", parent_code=None).rename(
        columns={"lad_code": "area_code", "lad_name": "area_name"}
    )
    lsoa = (
        lsoa[~outside]
        .assign(area_type="LSOA")
        .rename(columns={"lsoa_code": "area_code", "lsoa_name": "area_name"})
    )
    out = pd.concat([lad, lsoa], ignore_index=True)[
        ["area_type", "area_code", "area_name", "parent_code", "geometry"]
    ]
    out["geometry"] = out.geometry.make_valid()
    return gpd.GeoDataFrame(out, geometry="geometry", crs=CRS)


def addresses(addr: gpd.GeoDataFrame, lad: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    addr = addr.dropna(subset=["lsoa21cd"]).copy()
    addr["population"] = addr["population"].fillna(0).astype(float)
    ADDRESSES.validate(addr)
    if np.isnan(addr.geometry.x).any():
        raise ValueError("Addresses without coordinates")
    # Each address should lie in its own district (allowing for generalised boundaries)
    joined = addr.sjoin(
        lad[["lad_code", "geometry"]].assign(geometry=lad.buffer(100)), how="left", predicate="within"
    )
    own = joined["lad_code"] == joined["lad26cd"]
    inside = own.groupby(level=0).any().reindex(addr.index, fill_value=False)
    outside = 1 - inside.mean()
    if outside > MAX_OUTSIDE_SHARE:
        raise ValueError(f"{outside:.2%} of addresses fall outside their district")
    log.info(
        "Addresses: %s, residents %s; %.3f%% outside their district (tolerated)",
        f"{len(addr):,}",
        f"{addr['population'].sum():,.0f}",
        100 * outside,
    )
    return addr


def green_sites(green: gpd.GeoDataFrame, settings: Settings) -> gpd.GeoDataFrame:
    """Public green space parcels merged into sites; sites under the minimum size dropped."""
    g = settings.green
    public = green[green["type"].isin(g.public_types)].copy()
    public["geometry"] = public.geometry.make_valid()
    # Parcels that touch or overlap form one site
    sites = shapely.get_parts(shapely.union_all(public.geometry.values))
    sites = gpd.GeoDataFrame(geometry=sites[shapely.get_type_id(sites) == 3], crs=CRS)
    parcels = public.sjoin(sites.reset_index(names="site"), predicate="intersects")
    types = parcels.groupby("site")["type"].agg(lambda t: "; ".join(sorted(set(t))))
    sites["types"] = types.reindex(sites.index).fillna("")
    sites["area_m2"] = sites.area
    kept = sites[sites["area_m2"] >= g.min_area_m2].reset_index(drop=True)
    kept.insert(0, "site_id", np.arange(1, len(kept) + 1, dtype="int64"))
    GREEN_SITES.validate(kept)
    log.info(
        "Green space: %s public parcels -> %s sites, %s of at least %.1f ha (%.1f km2)",
        f"{len(public):,}",
        f"{len(sites):,}",
        f"{len(kept):,}",
        g.min_area_m2 / 1e4,
        kept["area_m2"].sum() / 1e6,
    )
    return kept


def run(settings: Settings | None = None) -> dict[str, str]:
    settings = settings or Settings()
    lad = lake.read_geoparquet("bronze", "boundaries_lad")
    lsoa = lake.read_geoparquet("bronze", "boundaries_lsoa")
    addr = addresses(lake.read_geoparquet("bronze", "addresses"), lad)
    out = {
        "areas": areas(lad, lsoa),
        "addresses": addr,
        "green_sites": green_sites(lake.read_geoparquet("bronze", "greenspace"), settings),
    }
    return {name: lake.write_geoparquet(gdf, "silver", name) for name, gdf in out.items()}
