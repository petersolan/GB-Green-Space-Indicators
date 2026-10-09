"""Gold: green space access, per address and aggregated to LSOA and district.

Indicator GSA_300M: share of residents living within 300 m (straight line) of
a public green space site of at least 0.5 ha.

The distance test runs in DuckDB's spatial extension: sites are buffered by
300 m and joined to address points with ST_Intersects, which DuckDB executes
as an indexed spatial join. Each address's distance to its nearest site (up
to 2 km) comes from GeoPandas, for the distribution in the report.

Delta tables written to gold/:
  access_address   one row per address: residents, within_300m, nearest_site_m
  access_area      one row per LSOA and LAD: residents, residents within 300 m,
                   share (%), median distance for residents (m)
"""

from __future__ import annotations

import logging

import duckdb
import geopandas as gpd
import numpy as np
import pandas as pd

from greenidx import lake
from greenidx.config import Settings

log = logging.getLogger(__name__)
NEAREST_MAX_M = 2_000.0


def within_distance(addr: gpd.GeoDataFrame, sites: gpd.GeoDataFrame, distance_m: float) -> pd.Series:
    """True for each address within distance_m of any site (DuckDB spatial join)."""
    con = duckdb.connect()
    con.install_extension("spatial")
    con.load_extension("spatial")
    con.register("addr_df", pd.DataFrame({"uprn": addr["uprn"].values, "wkb": addr.geometry.to_wkb().values}))
    con.register(
        "site_df", pd.DataFrame({"site_id": sites["site_id"].values, "wkb": sites.geometry.to_wkb().values})
    )
    hits = con.execute(
        """
        WITH addr AS (SELECT uprn, ST_GeomFromWKB(wkb) AS geom FROM addr_df),
             reach AS (SELECT site_id, ST_Buffer(ST_GeomFromWKB(wkb), ?) AS geom FROM site_df)
        SELECT DISTINCT addr.uprn
        FROM addr JOIN reach ON ST_Intersects(addr.geom, reach.geom)
        """,
        [distance_m],
    ).fetchnumpy()["uprn"]
    con.close()
    return addr["uprn"].isin(hits)


def nearest_site(addr: gpd.GeoDataFrame, sites: gpd.GeoDataFrame) -> pd.Series:
    """Distance (m) to the nearest site, NaN beyond NEAREST_MAX_M."""
    j = gpd.sjoin_nearest(
        addr[["uprn", "geometry"]],
        sites[["geometry"]],
        how="left",
        max_distance=NEAREST_MAX_M,
        distance_col="d",
    )
    return j.groupby(level=0)["d"].min().reindex(addr.index)


def weighted_median(values: np.ndarray, weights: np.ndarray) -> float:
    """Median of values weighted by residents (NaN = further than NEAREST_MAX_M)."""
    order = np.argsort(np.nan_to_num(values, nan=np.inf))
    v, w = values[order], weights[order]
    if w.sum() <= 0:
        return np.nan
    cum = np.cumsum(w)
    return float(v[np.searchsorted(cum, cum[-1] / 2)])


def aggregate(detail: pd.DataFrame, areas: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for area_type, key in (("LSOA", "lsoa21cd"), ("LAD", "lad26cd")):
        for code, d in detail.groupby(key):
            residents = d["population"].sum()
            within = d.loc[d["within_300m"], "population"].sum()
            rows.append(
                dict(
                    area_type=area_type,
                    area_code=code,
                    addresses=len(d),
                    residents=residents,
                    residents_within_300m=within,
                    share_within_300m_pct=100 * within / residents if residents else np.nan,
                    median_distance_m=weighted_median(
                        d["nearest_site_m"].to_numpy(), d["population"].to_numpy()
                    ),
                )
            )
    # Reporting areas only: addresses coded to LSOAs outside the area still count
    # towards their district, but those LSOAs aren't reported
    out = pd.DataFrame(rows).merge(
        areas[["area_type", "area_code", "area_name", "parent_code"]],
        on=["area_type", "area_code"],
        how="inner",
    )
    return out[
        [
            "area_type",
            "area_code",
            "area_name",
            "parent_code",
            "addresses",
            "residents",
            "residents_within_300m",
            "share_within_300m_pct",
            "median_distance_m",
        ]
    ]


def run(settings: Settings | None = None) -> dict[str, str]:
    settings = settings or Settings()
    addr = lake.read_geoparquet("silver", "addresses")
    sites = lake.read_geoparquet("silver", "green_sites")
    areas = lake.read_geoparquet("silver", "areas")

    detail = pd.DataFrame(
        {
            "uprn": addr["uprn"].values,
            "lad26cd": addr["lad26cd"].values,
            "lsoa21cd": addr["lsoa21cd"].values,
            "population": addr["population"].values,
            "within_300m": within_distance(addr, sites, settings.green.distance_m).values,
            "nearest_site_m": nearest_site(addr, sites).values,
        }
    )
    summary = aggregate(detail, areas)
    total = summary[summary["area_type"] == "LAD"]
    log.info(
        "Residents within %.0f m of public green space >= %.1f ha: %.1f%% of %s",
        settings.green.distance_m,
        settings.green.min_area_m2 / 1e4,
        100 * total["residents_within_300m"].sum() / total["residents"].sum(),
        f"{total['residents'].sum():,.0f}",
    )
    return {
        "access_address": lake.write_delta(detail, "gold", "access_address"),
        "access_area": lake.write_delta(summary, "gold", "access_area"),
    }
