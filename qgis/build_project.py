r"""Build outputs/green_space.qgz: the results styled in QGIS.

Run qgis/export_view.py first (greenidx environment), then with QGIS's Python:
    "C:\Program Files\QGIS 3.44.13\bin\python-qgis-ltr.bat" qgis\build_project.py

Layers, top to bottom (relative paths, so the project moves with the folder):
  Districts    boundaries, labelled
  Addresses    (shown from 1:25,000) green within 300 m, red beyond
  Green space  public green space sites >= 0.5 ha and the 300 m reach around them
  Indicators   LSOAs by green space access (on) and by summer NDVI (off),
               semi-transparent over the basemap
  Satellite    (off) Sentinel-2 summer NDVI composite, 20 m
  Basemap      OpenStreetMap
"""

import sys
from pathlib import Path

from qgis.core import (
    QgsApplication,
    QgsCategorizedSymbolRenderer,
    QgsColorRampShader,
    QgsCoordinateReferenceSystem,
    QgsFillSymbol,
    QgsGradientColorRamp,
    QgsGraduatedSymbolRenderer,
    QgsMarkerSymbol,
    QgsPalLayerSettings,
    QgsProject,
    QgsRasterLayer,
    QgsRasterShader,
    QgsReferencedRectangle,
    QgsRendererCategory,
    QgsRendererRange,
    QgsSingleBandPseudoColorRenderer,
    QgsVectorLayer,
    QgsVectorLayerSimpleLabeling,
)
from qgis.PyQt.QtGui import QColor

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
GPKG = OUT / "view.gpkg"
CRS = QgsCoordinateReferenceSystem("EPSG:27700")


def fill(color: str, outline: str, width: float = 0.2, alpha: int = 255):
    c = QColor(color)
    return QgsFillSymbol.createSimple(
        {
            "color": f"{c.red()},{c.green()},{c.blue()},{alpha}",
            "outline_color": outline,
            "outline_width": str(width),
            "style": "solid" if alpha else "no",
        }
    )


def layer(name: str, title: str) -> QgsVectorLayer:
    lyr = QgsVectorLayer(f"{GPKG}|layername={name}", title, "ogr")
    if not lyr.isValid():
        sys.exit(f"Could not open {name} in {GPKG}: run qgis/export_view.py first")
    return lyr


def graduated(lyr: QgsVectorLayer, field: str, breaks: list[tuple[float, float, str, str]]) -> None:
    # Semi-transparent, so the basemap shows through
    lyr.setRenderer(
        QgsGraduatedSymbolRenderer(
            field,
            [
                QgsRendererRange(lo, hi, fill(colour, "#777777", 0.05, 170), label)
                for lo, hi, colour, label in breaks
            ],
        )
    )


def districts_layer() -> QgsVectorLayer:
    lyr = layer("districts", "Districts")
    lyr.renderer().setSymbol(fill("#000000", "#222222", 0.6, 0))
    label = QgsPalLayerSettings()
    label.fieldName = "area_name"
    fmt = label.format()
    fmt.setSize(10)
    label.setFormat(fmt)
    lyr.setLabeling(QgsVectorLayerSimpleLabeling(label))
    lyr.setLabelsEnabled(True)
    return lyr


def indicator_layers() -> tuple[QgsVectorLayer, QgsVectorLayer]:
    access = layer("lsoa_indicators", "LSOA: residents within 300 m of green space (%)")
    graduated(
        access,
        "GSA_300M",
        [
            (0, 25, "#ffffcc", "under 25%"),
            (25, 50, "#c2e699", "25-50%"),
            (50, 75, "#78c679", "50-75%"),
            (75, 100.01, "#238443", "75-100%"),
        ],
    )
    ndvi = layer("lsoa_indicators", "LSOA: mean summer NDVI")
    graduated(
        ndvi,
        "NDVI_MEAN",
        [
            (-1, 0.5, "#f7fcf5", "under 0.5"),
            (0.5, 0.6, "#c7e9c0", "0.5-0.6"),
            (0.6, 0.7, "#74c476", "0.6-0.7"),
            (0.7, 1.01, "#238b45", "over 0.7"),
        ],
    )
    return access, ndvi


def green_layers() -> tuple[QgsVectorLayer, QgsVectorLayer]:
    sites = layer("green_sites", "Public green space sites (>= 0.5 ha)")
    sites.renderer().setSymbol(fill("#1b7837", "#0b3d1a", 0.2, 200))
    reach = layer("reach_300m", "Within 300 m of a site")
    reach.renderer().setSymbol(fill("#5aae61", "#1b7837", 0.3, 50))
    return sites, reach


def address_layer() -> QgsVectorLayer:
    addr = layer("addresses", "Addresses: within 300 m (green) or beyond (red)")
    cats = []
    for value, colour, text in ((True, "#1a9850", "within 300 m"), (False, "#d73027", "beyond 300 m")):
        sym = QgsMarkerSymbol.createSimple(
            {"name": "circle", "color": colour, "size": "1.2", "outline_style": "no"}
        )
        cats.append(QgsRendererCategory(value, sym, text))
    addr.setRenderer(QgsCategorizedSymbolRenderer("within_300m", cats))
    addr.setScaleBasedVisibility(True)
    addr.setMinimumScale(25_000)  # 882,000 points: only when zoomed in
    return addr


def ndvi_raster() -> QgsRasterLayer:
    raster = QgsRasterLayer(str(OUT / "ndvi_summer.tif"), "Sentinel-2 summer NDVI, 2024 (20 m)")
    shader_fn = QgsColorRampShader(0.0, 0.9, QgsGradientColorRamp(QColor("#a6611a"), QColor("#00441b")))
    shader_fn.classifyColorRamp(6)
    shader = QgsRasterShader()
    shader.setRasterShaderFunction(shader_fn)
    raster.setRenderer(QgsSingleBandPseudoColorRenderer(raster.dataProvider(), 1, shader))
    return raster


def build(project: QgsProject) -> bool:
    project.setTitle("Green space access and greenness, Devon, 2024")
    project.setCrs(CRS)
    project.writeEntryBool("Paths", "/Absolute", False)
    root = project.layerTreeRoot()

    def add(name: str, layers: list, visible: bool = True) -> None:
        group = root.addGroup(name)  # groups are added in drawing order, top first
        for lyr in layers:
            project.addMapLayer(lyr, False)
            group.addLayer(lyr).setItemVisibilityChecked(visible)

    districts = districts_layer()
    access, ndvi = indicator_layers()
    add("Districts", [districts])
    add("Addresses", [address_layer()])
    add("Green space", list(green_layers()))
    add("Indicators", [access])
    root.findGroup("Indicators").addLayer(ndvi).setItemVisibilityChecked(False)
    project.addMapLayer(ndvi, False)
    add("Satellite", [ndvi_raster()], visible=False)
    osm = QgsRasterLayer(
        "type=xyz&url=https://tile.openstreetmap.org/{z}/{x}/{y}.png&zmax=19&zmin=0", "OpenStreetMap", "wms"
    )
    add("Basemap", [osm])

    extent = districts.extent()
    extent.scale(1.05)
    project.viewSettings().setDefaultViewExtent(QgsReferencedRectangle(extent, CRS))
    out = OUT / "green_space.qgz"
    ok = project.write(str(out))
    print(f"{'Wrote' if ok else 'FAILED to write'} {out}")
    project.clear()  # release layers before QGIS shuts down
    return ok


def main() -> int:
    app = QgsApplication([], False)
    app.initQgis()
    ok = build(QgsProject.instance())
    app.exitQgis()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
