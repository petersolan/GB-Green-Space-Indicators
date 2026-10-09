"""The data lake: bronze (as received), silver (cleaned) and gold (indicators).

One interface over three backends, chosen by LAKE_BACKEND in the environment:
  local    a folder (default: ./lake), for quick runs and tests
  azurite  the Azure Storage emulator in Docker (docker compose up -d azurite)
  azure    a real storage account (AZURE_STORAGE_ACCOUNT_NAME + key or connection string)

Vector layers are GeoParquet; tables are Delta (ACID writes, schema enforcement
and time travel on plain Parquet files), the format Azure Databricks, Fabric
and Synapse read natively.
"""

from __future__ import annotations

import os
from functools import cache

import fsspec
import geopandas as gpd
import pandas as pd
from deltalake import DeltaTable, write_deltalake

from greenidx.config import ROOT

LAYERS = ("bronze", "silver", "gold")
# Azurite's account and key are public, fixed values documented by Microsoft
AZURITE = {
    "account_name": "devstoreaccount1",
    "account_key": "Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==",
}


@cache
def backend() -> str:
    name = os.environ.get("LAKE_BACKEND", "local")
    if name not in ("local", "azurite", "azure"):
        raise ValueError(f"LAKE_BACKEND must be local, azurite or azure, not {name!r}")
    return name


def container() -> str:
    return os.environ.get("LAKE_CONTAINER", "lake")


def _azure_options() -> dict[str, str]:
    """Credentials for fsspec (adlfs) and Delta (delta-rs), from the environment."""
    if backend() == "azurite":
        return {**AZURITE, "use_emulator": "true"}
    if conn := os.environ.get("AZURE_STORAGE_CONNECTION_STRING"):
        return {"connection_string": conn}
    return {
        "account_name": os.environ["AZURE_STORAGE_ACCOUNT_NAME"],
        "account_key": os.environ["AZURE_STORAGE_ACCOUNT_KEY"],
    }


def root() -> str:
    if backend() == "local":
        return str(ROOT / os.environ.get("LAKE_DIR", "lake")).replace("\\", "/")
    return f"az://{container()}"


def uri(layer: str, name: str) -> str:
    if layer not in LAYERS:
        raise ValueError(f"Unknown lake layer {layer!r}")
    return f"{root()}/{layer}/{name}"


@cache
def filesystem() -> fsspec.AbstractFileSystem:
    if backend() == "local":
        return fsspec.filesystem("file", auto_mkdir=True)
    opts = _azure_options()
    if backend() == "azurite":
        # adlfs takes the emulator as a connection string
        opts = {
            "connection_string": (
                "DefaultEndpointsProtocol=http;AccountName={account_name};AccountKey={account_key};"
                "BlobEndpoint=http://127.0.0.1:10000/{account_name};".format(**AZURITE)
            )
        }
    return fsspec.filesystem("abfs", **opts)


def ensure_container() -> None:
    """Create the blob container on first use (Delta writes don't create it)."""
    if backend() != "local" and not filesystem().exists(container()):
        filesystem().mkdir(container())


def delta_options() -> dict[str, str] | None:
    if backend() == "local":
        return None
    opts = _azure_options()
    if backend() == "azurite":
        return {
            "azure_storage_account_name": opts["account_name"],
            "azure_storage_account_key": opts["account_key"],
            "azure_storage_use_emulator": "true",
        }
    if "connection_string" in opts:
        return {"azure_storage_connection_string": opts["connection_string"]}
    return {
        "azure_storage_account_name": opts["account_name"],
        "azure_storage_account_key": opts["account_key"],
    }


def write_geoparquet(gdf: gpd.GeoDataFrame, layer: str, name: str) -> str:
    """Write a GeoParquet file (with bounding-box covering for fast spatial filters)."""
    path = uri(layer, f"{name}.parquet")
    ensure_container()
    with filesystem().open(path, "wb") as f:
        gdf.to_parquet(f, index=False, write_covering_bbox=True)
    return path


def read_geoparquet(layer: str, name: str, **kwargs) -> gpd.GeoDataFrame:
    with filesystem().open(uri(layer, f"{name}.parquet"), "rb") as f:
        return gpd.read_parquet(f, **kwargs)


def write_delta(df: pd.DataFrame, layer: str, name: str, mode: str = "overwrite") -> str:
    path = uri(layer, name)
    ensure_container()
    write_deltalake(
        path,
        df,
        mode=mode,
        schema_mode="overwrite" if mode == "overwrite" else None,
        storage_options=delta_options(),
    )
    return path


def read_delta(layer: str, name: str, version: int | None = None) -> pd.DataFrame:
    return DeltaTable(uri(layer, name), version=version, storage_options=delta_options()).to_pandas()


def write_bytes(data: bytes, layer: str, name: str) -> str:
    path = uri(layer, name)
    ensure_container()
    with filesystem().open(path, "wb") as f:
        f.write(data)
    return path


def read_bytes(layer: str, name: str) -> bytes:
    with filesystem().open(uri(layer, name), "rb") as f:
        return f.read()


def listing() -> list[str]:
    """Every file under the lake root, relative to it."""
    fs, base = filesystem(), root()
    prefix = base.removeprefix("az://")
    return sorted(p.removeprefix(prefix).lstrip("/") for p in fs.find(prefix))
