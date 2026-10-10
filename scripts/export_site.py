"""Export the indicators for the web demo (site/).

Reads outputs/view.gpkg (from qgis/export_view.py) and writes WGS84 GeoJSON to site/data/:
lsoa.geojson (729 LSOAs with the four indicators), districts.geojson and green_sites.geojson.
Shapes are simplified in British National Grid (tolerance in metres) before reprojecting, and
coordinates are rounded to 5 decimals (~1 m), which is plenty for a choropleth.
"""

from pathlib import Path

import geopandas as gpd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "outputs" / "view.gpkg"
OUT = ROOT / "site" / "data"
INDICATORS = ["GSA_300M", "NDVI_MEAN", "NDVI_VEG_PCT", "NDVI_CLEAR_PCT"]

LAYERS = {  # layer: (output name, columns, simplify tolerance in m)
    "lsoa_indicators": ("lsoa", ["area_code", "area_name", "parent_code", *INDICATORS], 8),
    "districts": ("districts", ["area_code", "area_name", *INDICATORS], 25),
    "green_sites": ("green_sites", ["types", "area_m2"], 2),
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for layer, (name, columns, tolerance) in LAYERS.items():
        gdf = gpd.read_file(SRC, layer=layer)[[*columns, "geometry"]]
        gdf["geometry"] = gdf.geometry.simplify(tolerance, preserve_topology=True)
        for col in set(columns) & {*INDICATORS, "area_m2"}:
            gdf[col] = gdf[col].round(3 if col == "NDVI_MEAN" else 1)
        path = OUT / f"{name}.geojson"
        path.unlink(missing_ok=True)
        gdf.to_crs("EPSG:4326").to_file(
            path,
            driver="GeoJSON",
            engine="pyogrio",
            layer_options={"COORDINATE_PRECISION": 5, "RFC7946": "YES"},
        )
        print(f"{len(gdf):>5,} {name:<12} {path.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
