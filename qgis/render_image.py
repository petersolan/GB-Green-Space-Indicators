r"""Render docs/images/addresses_exeter.png from outputs/green_space.qgz (no window).

    "C:\Program Files\QGIS 3.44.13\bin\python-qgis-ltr.bat" qgis\render_image.py

Central Exeter at street scale: every address green (within 300 m of public
green space of at least 0.5 ha) or red (beyond), over OpenStreetMap.
"""

import sys
from pathlib import Path

from PIL import Image
from qgis.core import QgsApplication, QgsMapRendererParallelJob, QgsMapSettings, QgsProject, QgsRectangle
from qgis.PyQt.QtCore import QSize
from qgis.PyQt.QtGui import QColor

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "images" / "addresses_exeter.png"
EXTENT = QgsRectangle(291000, 91800, 294000, 94050)  # central Exeter


def draw() -> None:
    project = QgsProject.instance()
    project.read(str(ROOT / "outputs" / "green_space.qgz"))
    settings = QgsMapSettings()
    settings.setLayers([n.layer() for n in project.layerTreeRoot().findLayers() if n.isVisible()])
    settings.setDestinationCrs(project.crs())
    settings.setExtent(EXTENT)
    settings.setOutputSize(QSize(1150, 860))
    settings.setBackgroundColor(QColor("white"))
    job = QgsMapRendererParallelJob(settings)
    job.start()
    job.waitForFinished()
    job.renderedImage().save(str(OUT), "png")
    Image.open(OUT).convert("RGB").quantize(256, Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE).save(
        OUT, optimize=True
    )
    project.clear()  # release layers before QGIS shuts down
    print(f"Wrote {OUT} ({OUT.stat().st_size / 1e3:.0f} kB)")


def main() -> int:
    app = QgsApplication([], False)
    app.initQgis()
    draw()
    app.exitQgis()
    return 0


if __name__ == "__main__":
    sys.exit(main())
