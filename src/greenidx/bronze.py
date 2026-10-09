"""Bronze: source data as received, for the study area only.

  boundaries_lad   local authority districts (ONS, May 2025, generalised)
  boundaries_lsoa  LSOAs 2021 in those districts (ONS, generalised)
  addresses        every address (UPRN) in the districts with its statistical
                   geographies (ONSUD) and modelled population (census project)
  greenspace       OS Open Zoomstack green space polygons around the area

Each source is filtered on read, so only the area's data is fetched.
"""

from __future__ import annotations

import logging

import geopandas as gpd
import httpx
import pandas as pd
import pyarrow.compute as pc
import pyarrow.dataset as ds

from greenidx import lake
from greenidx.config import AREAS, CENSUS_DIR, CRS, LAD_SERVICE, LSOA_SERVICE, ZOOMSTACK

log = logging.getLogger(__name__)
BATCH = 200  # LSOA codes per request


def _arcgis(url: str, where: str, fields: str) -> gpd.GeoDataFrame:
    """All features matching `where` from an ArcGIS feature service, paging as needed."""
    frames, offset = [], 0
    with httpx.Client(timeout=120, transport=httpx.HTTPTransport(retries=3)) as client:
        while True:
            # POST: long IN (...) lists exceed the server's URL length limit
            r = client.post(
                url,
                data={
                    "where": where,
                    "outFields": fields,
                    "f": "geojson",
                    "resultOffset": offset,
                    "resultRecordCount": 2000,
                },
            )
            r.raise_for_status()
            feats = r.json().get("features", [])
            if not feats:
                break
            frames.append(gpd.GeoDataFrame.from_features(feats, crs="EPSG:4326"))
            offset += len(feats)
            if len(feats) < 2000:
                break
    return pd.concat(frames, ignore_index=True).to_crs(CRS)


def addresses() -> gpd.GeoDataFrame:
    """Addresses in the area with LSOA/MSOA/LAD codes and modelled residents."""
    codes = list(AREAS)
    onsud = ds.dataset(CENSUS_DIR / "onsud_uprn.parquet").to_table(
        filter=pc.field("lad26cd").isin(codes),
        columns=["uprn", "lad26cd", "lsoa21cd", "msoa21cd", "geometry"],
    )
    pop = (
        ds.dataset(CENSUS_DIR / "uprn_population.parquet")
        .to_table(filter=pc.field("uprn").isin(onsud["uprn"]), columns=["uprn", "population"])
        .to_pandas()
    )
    geom = onsud["geometry"].combine_chunks()
    df = onsud.drop_columns("geometry").to_pandas().merge(pop, on="uprn", how="left")
    gdf = gpd.GeoDataFrame(
        df, geometry=gpd.points_from_xy(geom.field("x").to_numpy(), geom.field("y").to_numpy()), crs=CRS
    )
    log.info("%s addresses, %s residents", f"{len(gdf):,}", f"{gdf['population'].sum():,.0f}")
    return gdf


def boundaries_lad() -> gpd.GeoDataFrame:
    codes = ",".join(f"'{c}'" for c in AREAS)
    gdf = _arcgis(LAD_SERVICE, f"LAD25CD IN ({codes})", "LAD25CD,LAD25NM")
    return gdf.rename(columns={"LAD25CD": "lad_code", "LAD25NM": "lad_name"})


def boundaries_lsoa(lsoa_codes: list[str]) -> gpd.GeoDataFrame:
    frames = []
    for i in range(0, len(lsoa_codes), BATCH):
        batch = ",".join(f"'{c}'" for c in lsoa_codes[i : i + BATCH])
        frames.append(_arcgis(LSOA_SERVICE, f"LSOA21CD IN ({batch})", "LSOA21CD,LSOA21NM"))
    gdf = pd.concat(frames, ignore_index=True)
    return gdf.rename(columns={"LSOA21CD": "lsoa_code", "LSOA21NM": "lsoa_name"})


def greenspace(bounds: tuple[float, float, float, float]) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(ZOOMSTACK, layer="greenspace", bbox=bounds)
    return gdf.to_crs(CRS)


def run() -> dict[str, str]:
    lad = boundaries_lad()
    missing = set(AREAS) - set(lad["lad_code"])
    if missing:
        raise ValueError(f"No boundary for {sorted(missing)}")
    addr = addresses()
    lsoa = boundaries_lsoa(sorted(addr["lsoa21cd"].dropna().unique()))
    # Green space just outside the area still serves residents near its edge
    minx, miny, maxx, maxy = lad.total_bounds
    pad = 1_000
    green = greenspace((minx - pad, miny - pad, maxx + pad, maxy + pad))
    written = {}
    for name, gdf in (
        ("boundaries_lad", lad),
        ("boundaries_lsoa", lsoa),
        ("addresses", addr),
        ("greenspace", green),
    ):
        written[name] = lake.write_geoparquet(gdf, "bronze", name)
        log.info("bronze/%s: %s rows", name, f"{len(gdf):,}")
    return written
