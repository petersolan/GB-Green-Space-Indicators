"""Command line: python -m greenidx <stage> [<stage> ...]

Stages run in the order given; `all` runs the full pipeline:
  bronze     fetch and filter the sources into the lake
  silver     clean, validate and conform
  access     green space access indicator (gold)
  ndvi       Sentinel-2 summer greenness indicator (gold)
  publish    indicator table, SDMX, ISO 19115 / DCAT-AP / Dublin Core metadata
  ls         list the lake's contents
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

STAGES = ["bronze", "silver", "access", "ndvi", "publish"]


def load_env(path: Path) -> None:
    """Read KEY=value lines from .env into the environment (existing values win)."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"'))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="greenidx", description=__doc__.splitlines()[0])
    parser.add_argument("stages", nargs="+", choices=[*STAGES, "all", "ls"])
    args = parser.parse_args(argv)
    load_env(Path.cwd() / ".env")
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S"
    )
    log = logging.getLogger("greenidx")
    # One line per HTTP request is noise
    for noisy in ("httpx", "azure"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    from greenidx import lake

    stages = STAGES if "all" in args.stages else args.stages
    log.info("Lake: %s (%s)", lake.root(), lake.backend())
    for stage in stages:
        if stage == "ls":
            print("\n".join(lake.listing()))
            continue
        started = time.perf_counter()
        module = {"access": "gold_access", "ndvi": "gold_ndvi"}.get(stage, stage)
        written = __import__(f"greenidx.{module}", fromlist=["run"]).run()
        log.info("%s done in %.1f s: %s", stage, time.perf_counter() - started, ", ".join(written))
    return 0


if __name__ == "__main__":
    sys.exit(main())
