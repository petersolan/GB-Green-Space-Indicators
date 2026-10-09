"""Export the results for viewing: outputs/view.gpkg and outputs/ndvi_summer.tif.

    python qgis/export_view.py        (greenidx environment; reads the lake)

Layers in view.gpkg:
  districts        LAD boundaries with their indicators
  lsoa_indicators  LSOAs with all four indicators
  green_sites      public green space sites of at least 0.5 ha
  reach_300m       the area within 300 m of a site (dissolved)
  addresses        every address with residents, within_300m and distance
"""

from pathlib import Path

import geopandas as gpd

from greenidx import lake
from greenidx.config import Settings

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"


def main() -> None:
    OUT.mkdir(exist_ok=True)
    gpkg = OUT / "view.gpkg"
    gpkg.unlink(missing_ok=True)
    settings = Settings()

    areas = lake.read_geoparquet("silver", "areas")
    table = lake.read_delta("gold", "indicators")
    wide = table.pivot_table(index="area_code", columns="indicator", values="value").reset_index()
    layers = {}
    for name, area_type in (("districts", "LAD"), ("lsoa_indicators", "LSOA")):
        layers[name] = areas[areas["area_type"] == area_type].merge(wide, on="area_code", how="left")

    sites = lake.read_geoparquet("silver", "green_sites")
    layers["green_sites"] = sites
    reach = sites.buffer(settings.green.distance_m).union_all()
    layers["reach_300m"] = gpd.GeoDataFrame(
        {"distance_m": [settings.green.distance_m]}, geometry=[reach], crs=sites.crs
    )

    addr = lake.read_geoparquet("silver", "addresses")[["uprn", "lsoa21cd", "geometry"]]
    detail = lake.read_delta("gold", "access_address")[
        ["uprn", "population", "within_300m", "nearest_site_m"]
    ]
    layers["addresses"] = addr.merge(detail, on="uprn")

    for name, gdf in layers.items():
        gdf.to_file(gpkg, layer=name, driver="GPKG")
        print(f"{name}: {len(gdf):,} features")
    (OUT / "ndvi_summer.tif").write_bytes(lake.read_bytes("silver", "ndvi_summer.tif"))
    print(f"Wrote {gpkg} and {OUT / 'ndvi_summer.tif'}")


if __name__ == "__main__":
    main()
