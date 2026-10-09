"""Draw docs/images/indicators_map.png from publication/indicators_lsoa.parquet.

python docs/make_map.py
"""

from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    lsoa = gpd.read_parquet(ROOT / "publication" / "indicators_lsoa.parquet")
    districts = lsoa.dissolve("parent_code")
    fig, axes = plt.subplots(1, 2, figsize=(14, 6.4))
    for ax, column, title, cmap, vmin, vmax in (
        (axes[0], "GSA_300M", "Residents within 300 m of public green space ≥ 0.5 ha (%)", "YlGn", 0, 100),
        (axes[1], "NDVI_MEAN", "Mean summer NDVI, Sentinel-2, 2024", "Greens", 0.3, 0.85),
    ):
        lsoa.plot(
            column=column,
            ax=ax,
            cmap=cmap,
            vmin=vmin,
            vmax=vmax,
            linewidth=0.05,
            edgecolor="#999",
            legend=True,
            legend_kwds={"shrink": 0.6},
            missing_kwds={"color": "#ddd"},
        )
        districts.boundary.plot(ax=ax, color="#333", linewidth=0.6)
        ax.set_title(title, fontsize=11)
        ax.set_axis_off()
    fig.text(
        0.5,
        0.06,
        "Devon, by LSOA (2021). Contains ONS, OS and Copernicus Sentinel-2 data.",
        ha="center",
        fontsize=8,
        color="#555",
    )
    out = ROOT / "docs" / "images" / "indicators_map.png"
    fig.savefig(out, dpi=110, bbox_inches="tight")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
