"""The lake round trip, the SDMX publication and the metadata records."""

import io
import socket
import xml.dom.minidom

import geopandas as gpd
import pandas as pd
import pytest
import sdmx
from shapely.geometry import Point

from greenidx import lake, publish


def _table() -> pd.DataFrame:
    rows = [("LAD", "E07000041", "Exeter", None), ("LSOA", "E01020001", "Exeter 001A", "E07000041")]
    return pd.DataFrame(
        [
            dict(
                area_type=t,
                area_code=c,
                area_name=n,
                parent_code=p,
                indicator=ind,
                indicator_name=publish.INDICATORS[ind][0],
                year=2024,
                value=v,
                unit=publish.INDICATORS[ind][1],
            )
            for t, c, n, p in rows
            for ind, v in (("GSA_300M", 55.5), ("NDVI_MEAN", 0.61))
        ]
    )


def test_lake_round_trip():
    gdf = gpd.GeoDataFrame({"a": [1]}, geometry=[Point(1, 2)], crs="EPSG:27700")
    lake.write_geoparquet(gdf, "silver", "points")
    assert lake.read_geoparquet("silver", "points").geometry.iloc[0].equals(Point(1, 2))
    lake.write_delta(pd.DataFrame({"x": [1, 2]}), "gold", "t")
    lake.write_delta(pd.DataFrame({"x": [3]}), "gold", "t")
    assert lake.read_delta("gold", "t")["x"].tolist() == [3]
    assert lake.read_delta("gold", "t", version=0)["x"].tolist() == [1, 2]  # Delta time travel
    with pytest.raises(ValueError):
        lake.uri("platinum", "x")


def test_sdmx_structures_and_data():
    structure_xml, data_csv = publish.sdmx_publication(_table())
    msg = sdmx.read_sdmx(io.BytesIO(structure_xml))
    areas = msg.codelist["CL_AREA_DEVON"]
    assert areas.get("E01020001").parent.id == "E07000041"  # LSOA -> district hierarchy
    assert {d.id for d in msg.structure["DSD_GREEN_SPACE"].dimensions} == {
        "REF_AREA",
        "INDICATOR",
        "TIME_PERIOD",
    }
    data = pd.read_csv(io.StringIO(data_csv))
    assert list(data.columns[:3]) == ["STRUCTURE", "STRUCTURE_ID", "ACTION"]  # SDMX-CSV 2.0
    assert len(data) == 4
    assert set(data["UNIT_MEASURE"]) == {"PC", "NDVI"}


def test_sdmx_check_rejects_unknown_codes():
    structure_xml, data_csv = publish.sdmx_publication(_table())
    with pytest.raises(ValueError, match="REF_AREA"):
        publish.check_sdmx(structure_xml, data_csv.replace("E01020001", "E01999999"))


def test_metadata_records_are_consistent():
    mcf = publish.load_record([-4.68, 50.2, -2.88, 51.25])
    iso = publish.iso19139(mcf)
    xml.dom.minidom.parseString(iso)
    assert "Green space access and summer greenness" in iso
    dc = publish.dublin_core(mcf)
    xml.dom.minidom.parseString(dc)
    assert "<dc:title>Green space access" in dc
    graph = publish.dcat_ap(mcf)
    titles = {str(o) for o in graph.objects(None, publish.DCTERMS.title)}
    assert mcf["identification"]["title"]["en"] in titles


def _online(host: str) -> bool:
    try:
        socket.create_connection((host, 443), timeout=3).close()
        return True
    except OSError:
        return False


@pytest.mark.network
@pytest.mark.skipif(not _online("raw.githubusercontent.com"), reason="offline")
def test_dcat_ap_conforms_to_official_shapes():
    publish.validate_dcat_ap(publish.dcat_ap(publish.load_record([-4.68, 50.2, -2.88, 51.25])))


def _azurite_up() -> bool:
    try:
        socket.create_connection(("127.0.0.1", 10000), timeout=1).close()
        return True
    except OSError:
        return False


@pytest.mark.skipif(not _azurite_up(), reason="Azurite not running (docker compose up -d azurite)")
def test_lake_azurite(monkeypatch):
    monkeypatch.setenv("LAKE_BACKEND", "azurite")
    monkeypatch.setenv("LAKE_CONTAINER", "test-lake")
    lake.backend.cache_clear()
    lake.filesystem.cache_clear()
    if lake.filesystem().exists("test-lake"):
        lake.filesystem().rm("test-lake", recursive=True)
    # A Delta write into a fresh account must create the container itself
    lake.write_delta(pd.DataFrame({"x": [1]}), "gold", "azure_check")
    assert lake.read_delta("gold", "azure_check")["x"].tolist() == [1]
    assert lake.root() == "az://test-lake"


def test_env_file_fills_gaps_but_never_overrides(tmp_path, monkeypatch):
    from greenidx.__main__ import load_env

    (tmp_path / ".env").write_text('# comment\nLAKE_CONTAINER="from-file"\nLAKE_BACKEND=azure\n')
    monkeypatch.delenv("LAKE_CONTAINER", raising=False)
    monkeypatch.setenv("LAKE_BACKEND", "local")  # already set: must win
    load_env(tmp_path / ".env")
    import os

    assert os.environ["LAKE_CONTAINER"] == "from-file"
    assert os.environ["LAKE_BACKEND"] == "local"
    monkeypatch.delenv("LAKE_CONTAINER")


def test_delta_options_from_connection_string(monkeypatch):
    monkeypatch.setenv("LAKE_BACKEND", "azure")
    monkeypatch.setenv(
        "AZURE_STORAGE_CONNECTION_STRING",
        "DefaultEndpointsProtocol=https;AccountName=greenidx1;AccountKey=abc==;EndpointSuffix=core.windows.net",
    )
    lake.backend.cache_clear()
    assert lake.delta_options() == {
        "azure_storage_account_name": "greenidx1",
        "azure_storage_account_key": "abc==",
    }
