"""Gold: summer greenness from Sentinel-2, read from Microsoft Planetary Computer.

Nothing is downloaded in bulk: the STAC API finds the scenes, odc-stac opens
the cloud-optimised GeoTIFFs lazily as an Xarray cube (Dask chunks), and only
the pixels inside the area's bounding box are read.

  1. Search summer scenes over the area with little cloud, and keep the
     clearest days (CLEAREST_DAYS) to bound the data read.
  2. Load red (B04), near infrared (B08) and the scene classification (SCL)
     at 20 m on the British National Grid; mask cloud, shadow and no-data
     pixels with SCL.
  3. NDVI = (NIR - red) / (NIR + red) per day, then the median over days.
  4. Zonal statistics per LSOA and district: mean NDVI, share of vegetated
     pixels (NDVI above the threshold), and the share of pixels with a clear
     observation (coverage), so gaps are reported rather than hidden.

Writes the NDVI composite to silver/ndvi_summer.tif (Cloud Optimised GeoTIFF)
and the statistics to the Delta table gold/ndvi_area.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

import numpy as np
import odc.stac
import pandas as pd
import planetary_computer
import pystac_client
import xarray as xr
from rasterio.features import rasterize

from greenidx import lake
from greenidx.config import CRS, Settings

log = logging.getLogger(__name__)
STAC_API = "https://planetarycomputer.microsoft.com/api/stac/v1"
CLEAREST_DAYS = 8
# Sentinel-2 scene classes kept: vegetation, bare soil, water, unclassified.
# Dropped: no data, saturated, dark/shadow, cloud (medium, high), cirrus, snow
CLEAR_SCL = [4, 5, 6, 7]
# Processing baseline 04.00 (from January 2022) adds 1000 to every reflectance
BOA_OFFSET = 1000


def search(bbox_wgs84: tuple[float, float, float, float], settings: Settings) -> list:
    s = settings.ndvi
    catalog = pystac_client.Client.open(STAC_API, modifier=planetary_computer.sign_inplace)
    items = list(
        catalog.search(
            collections=[s.collection],
            bbox=bbox_wgs84,
            datetime=f"{s.start}/{s.end}",
            query={"eo:cloud_cover": {"lt": s.max_cloud_pct}},
        ).items()
    )
    if not items:
        raise RuntimeError("No Sentinel-2 scenes found")
    # Keep the clearest days (mean cloud cover over the day's scenes)
    days = pd.DataFrame(
        {"day": [i.datetime.date() for i in items], "cloud": [i.properties["eo:cloud_cover"] for i in items]}
    )
    best = days.groupby("day")["cloud"].mean().nsmallest(CLEAREST_DAYS).index
    chosen = [i for i in items if i.datetime.date() in set(best)]
    log.info(
        "%s scenes on %s days found; using %s scenes on the %s clearest days: %s",
        len(items),
        days["day"].nunique(),
        len(chosen),
        len(best),
        ", ".join(str(d) for d in sorted(best)),
    )
    return chosen


def composite(items: list, bounds_bng: tuple[float, float, float, float], settings: Settings) -> xr.DataArray:
    """Median NDVI over the chosen days, cloud-masked, on a 20 m BNG grid."""
    cube = odc.stac.load(
        items,
        bands=["B04", "B08", "SCL"],
        crs=CRS,
        resolution=settings.ndvi.resolution_m,
        x=(bounds_bng[0], bounds_bng[2]),
        y=(bounds_bng[1], bounds_bng[3]),
        groupby="solar_day",
        chunks={"x": 2048, "y": 2048},
        resampling={"SCL": "nearest", "*": "bilinear"},
    )
    clear = cube["SCL"].isin(CLEAR_SCL)
    red = (cube["B04"].astype("float32") - BOA_OFFSET).clip(min=0)
    nir = (cube["B08"].astype("float32") - BOA_OFFSET).clip(min=0)
    ndvi = ((nir - red) / (nir + red)).where(clear & (nir + red > 0))
    return ndvi.median("time", skipna=True).compute()


def zonal(ndvi: xr.DataArray, areas: pd.DataFrame, threshold: float) -> pd.DataFrame:
    """Mean NDVI, vegetated share and clear coverage for each area (LSOA and LAD)."""
    transform = ndvi.odc.geobox.transform
    values = ndvi.values
    valid = np.isfinite(values)
    rows = []
    for area_type, group in areas.groupby("area_type"):
        ids = rasterize(
            ((g, i + 1) for i, g in enumerate(group.geometry)),
            out_shape=values.shape,
            transform=transform,
            dtype="int32",
        )
        n = len(group) + 1
        pixels = np.bincount(ids.ravel(), minlength=n)
        clear = np.bincount(ids[valid], minlength=n)
        total = np.bincount(ids[valid], weights=values[valid], minlength=n)
        green = np.bincount(ids[valid], weights=(values[valid] > threshold), minlength=n)
        with np.errstate(invalid="ignore", divide="ignore"):
            rows.append(
                pd.DataFrame(
                    {
                        "area_type": area_type,
                        "area_code": group["area_code"].values,
                        "area_name": group["area_name"].values,
                        "parent_code": group["parent_code"].values,
                        "pixels": pixels[1:],
                        "clear_coverage_pct": 100 * clear[1:] / pixels[1:],
                        "mean_ndvi": total[1:] / clear[1:],
                        "vegetated_pct": 100 * green[1:] / clear[1:],
                    }
                )
            )
    return pd.concat(rows, ignore_index=True)


def write_cog(ndvi: xr.DataArray) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "ndvi.tif"
        ndvi.astype("float32").rio.write_crs(CRS).rio.to_raster(path, driver="COG", compress="DEFLATE")
        return lake.write_bytes(path.read_bytes(), "silver", "ndvi_summer.tif")


def run(settings: Settings | None = None) -> dict[str, str]:
    import rioxarray  # noqa: F401  (registers .rio)

    settings = settings or Settings()
    areas = lake.read_geoparquet("silver", "areas")
    lad = areas[areas["area_type"] == "LAD"]
    items = search(tuple(lad.to_crs("EPSG:4326").total_bounds), settings)
    ndvi = composite(items, tuple(lad.total_bounds), settings)
    stats = zonal(ndvi, areas, settings.ndvi.vegetated_ndvi)
    in_area = stats[stats["area_type"] == "LAD"]
    log.info(
        "NDVI composite %s x %s px; district coverage %.1f-%.1f%%, mean NDVI %.2f-%.2f",
        *ndvi.shape[::-1],
        in_area["clear_coverage_pct"].min(),
        in_area["clear_coverage_pct"].max(),
        in_area["mean_ndvi"].min(),
        in_area["mean_ndvi"].max(),
    )
    return {"ndvi_summer": write_cog(ndvi), "ndvi_area": lake.write_delta(stats, "gold", "ndvi_area")}
