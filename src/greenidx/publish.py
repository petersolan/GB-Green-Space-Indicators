"""Publish: the indicators as statistics, with their structure and metadata.

From the gold tables this writes a small publication (to gold/publication in
the lake, and to ./publication for the repository):

  indicators.csv           tidy table: area, indicator, year, value, unit, names
  indicators_lsoa.parquet  LSOA polygons with all indicators (GeoParquet)
  indicators.sdmx.csv      SDMX-CSV 2.0 data for the dataflow DF_GREEN_SPACE
  indicators.dsd.xml       SDMX-ML 2.1 structures: codelists (areas, with each
                           LSOA's district as its parent; indicators; units),
                           concepts, the data structure definition and dataflow
  metadata.iso19139.xml    ISO 19115 metadata, ISO 19139 XML encoding (the
                           encoding INSPIRE and the UK GEMINI profile use)
  metadata.dcat-ap.jsonld  DCAT-AP 3 catalogue record (dataset + distributions)
  metadata.dc.xml          Dublin Core (OAI-DC) record

All three metadata records come from metadata/record.yml. The DCAT-AP record
is validated against the official DCAT-AP 3 SHACL shapes, and the SDMX data is
checked against its own codelists, before anything is written.
"""

from __future__ import annotations

import io
import json
import logging
from datetime import date
from pathlib import Path

import geopandas as gpd
import httpx
import pandas as pd
import pyshacl
import sdmx
import yaml
from deltalake.exceptions import TableNotFoundError
from pygeometa.schemas.iso19139 import ISO19139OutputSchema
from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.namespace import DCAT, DCTERMS, FOAF, RDF, RDFS, SKOS, XSD
from sdmx.message import StructureMessage
from sdmx.model import common
from sdmx.model import v21 as sdmx21

from greenidx import lake
from greenidx.config import ROOT, Settings

log = logging.getLogger(__name__)
PUBLICATION = ROOT / "publication"
RECORD = ROOT / "metadata" / "record.yml"
AGENCY = "PSOLAN"  # maintenance agency id for the SDMX structures
BASE_URL = "https://github.com/petersolan/GB-Green-Space-Indicators/raw/main/publication"
DCAT_AP_SHACL = (
    "https://raw.githubusercontent.com/SEMICeu/DCAT-AP/master/releases/3.0.0/shacl/dcat-ap-SHACL.ttl"
)
VCARD = Namespace("http://www.w3.org/2006/vcard/ns#")
ADMS = Namespace("http://www.w3.org/ns/adms#")
EU_THEME = "http://publications.europa.eu/resource/authority/data-theme/ENVI"
EU_FREQ = "http://publications.europa.eu/resource/authority/frequency/ANNUAL"
EU_LANG = "http://publications.europa.eu/resource/authority/language/ENG"

# id: (name, unit id, source table, column)
INDICATORS = {
    "GSA_300M": (
        "Residents within 300 m of public green space of at least 0.5 ha",
        "PC",
        "access_area",
        "share_within_300m_pct",
    ),
    "NDVI_MEAN": ("Mean summer NDVI from Sentinel-2", "NDVI", "ndvi_area", "mean_ndvi"),
    "NDVI_VEG_PCT": ("Area with summer NDVI above 0.5", "PC", "ndvi_area", "vegetated_pct"),
    # Quality of the two NDVI indicators: read them with care where this is low
    "NDVI_CLEAR_PCT": ("Area with a cloud-free summer observation", "PC", "ndvi_area", "clear_coverage_pct"),
}
UNITS = {"PC": "Percent", "NDVI": "Normalised difference vegetation index (-1 to 1)"}


# --- the indicator table --------------------------------------------------------


def indicator_table(settings: Settings) -> pd.DataFrame:
    """One row per area, indicator and year, from the gold tables."""
    frames = []
    for ind, (name, unit, table, column) in INDICATORS.items():
        try:
            df = lake.read_delta("gold", table)
        except TableNotFoundError:  # a stage that hasn't run yet just isn't published
            log.warning("gold/%s missing: %s not published", table, ind)
            continue
        frames.append(
            pd.DataFrame(
                {
                    "area_type": df["area_type"],
                    "area_code": df["area_code"],
                    "area_name": df["area_name"],
                    "parent_code": df["parent_code"],
                    "indicator": ind,
                    "indicator_name": name,
                    "year": settings.reference_year,
                    "value": df[column].round(4),
                    "unit": unit,
                }
            )
        )
    table = pd.concat(frames, ignore_index=True).dropna(subset=["value"])
    return table.sort_values(["indicator", "area_type", "area_code"]).reset_index(drop=True)


# --- SDMX -----------------------------------------------------------------------


def _codelist(id_: str, name: str, codes: dict[str, str], agency: common.Agency) -> common.Codelist:
    cl = common.Codelist(id=id_, name={"en": name}, maintainer=agency, version="1.0", is_final=True)
    for code, label in codes.items():
        cl.append(common.Code(id=code, name={"en": label}))
    return cl


def sdmx_publication(table: pd.DataFrame) -> tuple[bytes, str]:
    """SDMX-ML 2.1 structure message and SDMX-CSV 2.0 data for the indicator table."""
    agency = common.Agency(id=AGENCY, name={"en": "Peter S (portfolio)"})
    areas = table.drop_duplicates("area_code").set_index("area_code")
    cl_area = _codelist(
        "CL_AREA_DEVON", "Devon districts (LAD) and LSOAs 2021", areas["area_name"].to_dict(), agency
    )
    # Statistical-geospatial hierarchy: each LSOA's parent is its district
    for code, parent in areas["parent_code"].dropna().items():
        cl_area.get(code).parent = cl_area.get(parent)
    cl_ind = _codelist(
        "CL_INDICATOR_GREEN", "Green space indicators", {k: v[0] for k, v in INDICATORS.items()}, agency
    )
    cl_unit = _codelist("CL_UNIT_GREEN", "Units", UNITS, agency)

    concepts = common.ConceptScheme(
        id="CS_GREEN_SPACE", name={"en": "Green space concepts"}, maintainer=agency, version="1.0"
    )
    for cid, label in (
        ("REF_AREA", "Reference area"),
        ("INDICATOR", "Indicator"),
        ("TIME_PERIOD", "Time period"),
        ("OBS_VALUE", "Observation value"),
        ("UNIT_MEASURE", "Unit of measure"),
    ):
        concepts.append(common.Concept(id=cid, name={"en": label}))

    def rep(cl):
        return common.Representation(enumerated=cl)

    dsd = sdmx21.DataStructureDefinition(
        id="DSD_GREEN_SPACE", name={"en": "Green space indicators"}, maintainer=agency, version="1.0"
    )
    dsd.dimensions.getdefault(
        "REF_AREA", concept_identity=concepts.get("REF_AREA"), local_representation=rep(cl_area)
    )
    dsd.dimensions.getdefault(
        "INDICATOR", concept_identity=concepts.get("INDICATOR"), local_representation=rep(cl_ind)
    )
    dsd.dimensions.getdefault(
        "TIME_PERIOD", cls=common.TimeDimension, concept_identity=concepts.get("TIME_PERIOD")
    )
    measure = dsd.measures.getdefault("OBS_VALUE", concept_identity=concepts.get("OBS_VALUE"))
    unit_attr = dsd.attributes.getdefault(
        "UNIT_MEASURE",
        concept_identity=concepts.get("UNIT_MEASURE"),
        local_representation=rep(cl_unit),
        related_to=sdmx21.PrimaryMeasureRelationship(),
    )
    flow = sdmx21.DataflowDefinition(
        id="DF_GREEN_SPACE",
        name={"en": "Green space access and greenness, Devon"},
        maintainer=agency,
        version="1.0",
        structure=dsd,
    )

    structures = StructureMessage()
    for obj in (cl_area, cl_ind, cl_unit, concepts, dsd, flow):
        structures.add(obj)
    structure_xml = sdmx.to_xml(structures, pretty_print=True)

    ds = sdmx21.StructureSpecificDataSet(structured_by=dsd, described_by=flow)
    for row in table.itertuples():
        key = dsd.make_key(
            common.Key, {"REF_AREA": row.area_code, "INDICATOR": row.indicator, "TIME_PERIOD": str(row.year)}
        )
        ds.obs.append(
            sdmx21.Observation(
                dimension=key,
                value=float(row.value),
                value_for=measure,
                attached_attribute={
                    "UNIT_MEASURE": common.AttributeValue(value=row.unit, value_for=unit_attr)
                },
            )
        )
    # As a DataFrame: the default string return is aligned for display, not CSV
    data_csv = sdmx.to_csv(ds, attributes="o", rtype=pd.DataFrame).to_csv(index=False)
    check_sdmx(structure_xml, data_csv)
    return structure_xml, data_csv


def check_sdmx(structure_xml: bytes, data_csv: str) -> None:
    """Parse the structures back and check every coded value in the data against them."""
    msg = sdmx.read_sdmx(io.BytesIO(structure_xml))
    data = pd.read_csv(io.StringIO(data_csv), dtype=str)
    for column, codelist in (
        ("REF_AREA", "CL_AREA_DEVON"),
        ("INDICATOR", "CL_INDICATOR_GREEN"),
        ("UNIT_MEASURE", "CL_UNIT_GREEN"),
    ):
        valid = {c.id for c in msg.codelist[codelist]}
        bad = set(data[column]) - valid
        if bad:
            raise ValueError(f"SDMX {column} values not in {codelist}: {sorted(bad)[:5]}")
    keys = data[["REF_AREA", "INDICATOR", "TIME_PERIOD"]]
    if keys.duplicated().any():
        raise ValueError("SDMX data has duplicate series keys")


# --- metadata -------------------------------------------------------------------


def load_record(bbox_wgs84: list[float]) -> dict:
    text = RECORD.read_text(encoding="utf-8")
    text = (
        text.replace('"{datestamp}"', date.today().isoformat())
        .replace('"{bbox_wgs84}"', json.dumps([round(v, 4) for v in bbox_wgs84]))
        .replace("{base_url}", BASE_URL)
    )
    return yaml.safe_load(text)


def iso19139(mcf: dict) -> str:
    return ISO19139OutputSchema().write(mcf)


def dublin_core(mcf: dict) -> str:
    """OAI-DC record: the fifteen Dublin Core elements that apply."""
    ident = mcf["identification"]
    begin, end = (ident["extents"]["temporal"][0][k] for k in ("begin", "end"))
    bbox = ident["extents"]["spatial"][0]["bbox"]
    elements = [
        ("title", ident["title"]["en"]),
        ("creator", mcf["contact"]["pointOfContact"]["organization"]),
        ("subject", "; ".join(ident["keywords"]["default"]["keywords"]["en"])),
        ("description", " ".join(ident["abstract"]["en"].split())),
        ("publisher", mcf["contact"]["publisher"]["organization"]),
        ("date", mcf["metadata"]["datestamp"]),
        ("type", "Dataset"),
        ("format", "text/csv"),
        ("identifier", mcf["metadata"]["identifier"]),
        ("source", mcf["metadata"]["dataseturi"]),
        ("language", "en"),
        ("coverage", f"Devon, United Kingdom; {begin}/{end}; WGS84 bbox {bbox}"),
        ("rights", ident["license"]["url"]),
    ]
    from xml.sax.saxutils import escape

    body = "\n".join(f"  <dc:{k}>{escape(str(v))}</dc:{k}>" for k, v in elements)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<oai_dc:dc xmlns:oai_dc="http://www.openarchives.org/OAI/2.0/oai_dc/"\n'
        '           xmlns:dc="http://purl.org/dc/elements/1.1/"\n'
        '           xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"\n'
        '           xsi:schemaLocation="http://www.openarchives.org/OAI/2.0/oai_dc/ '
        'http://www.openarchives.org/OAI/2.0/oai_dc.xsd">\n' + body + "\n</oai_dc:dc>\n"
    )


def _typed(g: Graph, node: URIRef, cls: URIRef) -> URIRef:
    """Declare a linked resource's class. DCAT-AP's shapes check the class of each
    value, and a validator doesn't fetch external vocabularies, so state it."""
    g.add((node, RDF.type, cls))
    return node


def _dataset(g: Graph, dataset: URIRef, mcf: dict, publisher: URIRef) -> None:
    """Mandatory and recommended dataset properties."""
    ident, meta = mcf["identification"], mcf["metadata"]
    g.add((dataset, RDF.type, DCAT.Dataset))
    g.add((dataset, DCTERMS.identifier, Literal(meta["identifier"])))
    g.add((dataset, DCTERMS.title, Literal(ident["title"]["en"], lang="en")))
    g.add((dataset, DCTERMS.description, Literal(" ".join(ident["abstract"]["en"].split()), lang="en")))
    g.add((dataset, DCTERMS.publisher, publisher))
    g.add((dataset, DCTERMS.issued, Literal(meta["datestamp"], datatype=XSD.date)))
    # Controlled vocabularies of the EU Publications Office
    g.add((dataset, DCTERMS.language, _typed(g, URIRef(EU_LANG), DCTERMS.LinguisticSystem)))
    g.add((dataset, DCAT.theme, _typed(g, URIRef(EU_THEME), SKOS.Concept)))
    g.add((URIRef(EU_THEME), SKOS.prefLabel, Literal("Environment", lang="en")))
    g.add((dataset, DCTERMS.accrualPeriodicity, _typed(g, URIRef(EU_FREQ), DCTERMS.Frequency)))
    for kw in ident["keywords"]["default"]["keywords"]["en"]:
        g.add((dataset, DCAT.keyword, Literal(kw, lang="en")))
    g.add((dataset, DCAT.landingPage, _typed(g, URIRef(meta["dataseturi"]), FOAF.Document)))

    contact = BNode()
    g.add((dataset, DCAT.contactPoint, contact))
    g.add((contact, RDF.type, VCARD.Kind))
    g.add((contact, RDF.type, VCARD.Organization))
    g.add((contact, VCARD.fn, Literal(mcf["contact"]["pointOfContact"]["organization"])))
    g.add((contact, VCARD.hasEmail, URIRef(f"mailto:{mcf['contact']['pointOfContact']['email']}")))


def _coverage(g: Graph, dataset: URIRef, mcf: dict) -> None:
    """Spatial and temporal coverage, and lineage."""
    ident = mcf["identification"]
    west, south, east, north = ident["extents"]["spatial"][0]["bbox"]
    place = BNode()
    g.add((dataset, DCTERMS.spatial, place))
    g.add((place, RDF.type, DCTERMS.Location))
    wkt = f"POLYGON(({west} {south},{east} {south},{east} {north},{west} {north},{west} {south}))"
    g.add(
        (place, DCAT.bbox, Literal(wkt, datatype=URIRef("http://www.opengis.net/ont/geosparql#wktLiteral")))
    )
    period = BNode()
    temporal = ident["extents"]["temporal"][0]
    g.add((dataset, DCTERMS.temporal, period))
    g.add((period, RDF.type, DCTERMS.PeriodOfTime))
    g.add((period, DCAT.startDate, Literal(str(temporal["begin"]), datatype=XSD.date)))
    g.add((period, DCAT.endDate, Literal(str(temporal["end"]), datatype=XSD.date)))
    lineage = BNode()
    g.add((dataset, DCTERMS.provenance, lineage))
    g.add((lineage, RDF.type, DCTERMS.ProvenanceStatement))
    statement = " ".join(mcf["dataquality"]["lineage"]["statement"].split())
    g.add((lineage, RDFS.label, Literal(statement, lang="en")))


def _distributions(g: Graph, dataset: URIRef, mcf: dict) -> None:
    base = mcf["metadata"]["dataseturi"]
    licence = _typed(g, URIRef(mcf["identification"]["license"]["url"]), DCTERMS.LicenseDocument)
    for key, d in mcf["distribution"].items():
        dist = URIRef(f"{base}#distribution-{key}")
        g.add((dataset, DCAT.distribution, dist))
        g.add((dist, RDF.type, DCAT.Distribution))
        g.add((dist, DCTERMS.title, Literal(d["name"]["en"], lang="en")))
        g.add((dist, DCTERMS.description, Literal(d["description"]["en"], lang="en")))
        url = _typed(g, URIRef(d["url"]), RDFS.Resource)
        g.add((dist, DCAT.accessURL, url))
        g.add((dist, DCAT.downloadURL, url))
        media = URIRef(f"https://www.iana.org/assignments/media-types/{d['type']}")
        g.add((dist, DCAT.mediaType, _typed(g, media, DCTERMS.MediaType)))
        g.add((dist, DCTERMS.license, licence))
        if key == "sdmx_csv":
            standard = _typed(g, URIRef("https://sdmx.org/?page_id=5008"), DCTERMS.Standard)
            g.add((dist, DCTERMS.conformsTo, standard))
            g.add((standard, DCTERMS.title, Literal("SDMX-CSV 2.0", lang="en")))


def dcat_ap(mcf: dict) -> Graph:
    """DCAT-AP 3 catalogue with the dataset and its distributions."""
    g = Graph()
    for prefix, ns in (("dcat", DCAT), ("dct", DCTERMS), ("foaf", FOAF), ("vcard", VCARD), ("adms", ADMS)):
        g.bind(prefix, ns)
    base = mcf["metadata"]["dataseturi"]
    catalog, dataset = URIRef(f"{base}#catalog"), URIRef(f"{base}#dataset")
    publisher = _typed(g, URIRef(mcf["contact"]["publisher"]["url"]), FOAF.Agent)
    g.add((publisher, FOAF.name, Literal(mcf["contact"]["publisher"]["organization"], lang="en")))

    g.add((catalog, RDF.type, DCAT.Catalog))
    g.add((catalog, DCTERMS.title, Literal("Green space indicators catalogue", lang="en")))
    g.add(
        (
            catalog,
            DCTERMS.description,
            Literal("Indicators published by the GB-Green-Space-Indicators project.", lang="en"),
        )
    )
    g.add((catalog, DCTERMS.publisher, publisher))
    g.add((catalog, DCAT.dataset, dataset))
    _dataset(g, dataset, mcf, publisher)
    _coverage(g, dataset, mcf)
    _distributions(g, dataset, mcf)
    return g


def validate_dcat_ap(graph: Graph) -> None:
    """Validate against the official DCAT-AP 3 SHACL shapes (violations fail the run)."""
    shapes = Graph().parse(
        data=httpx.get(DCAT_AP_SHACL, timeout=60, follow_redirects=True).text, format="turtle"
    )
    conforms, _, text = pyshacl.validate(graph, shacl_graph=shapes, inference="none", allow_warnings=True)
    if not conforms:
        raise ValueError(f"DCAT-AP record does not conform:\n{text[:3000]}")
    log.info("DCAT-AP record conforms to the DCAT-AP 3.0.0 SHACL shapes")


# --- run ------------------------------------------------------------------------


def run(settings: Settings | None = None) -> dict[str, str]:
    settings = settings or Settings()
    table = indicator_table(settings)
    areas = lake.read_geoparquet("silver", "areas")
    wide = table.pivot_table(index="area_code", columns="indicator", values="value").reset_index()
    lsoa = areas[areas["area_type"] == "LSOA"].merge(wide, on="area_code", how="left")
    lsoa = gpd.GeoDataFrame(lsoa, geometry="geometry", crs=areas.crs)

    structure_xml, data_csv = sdmx_publication(table)
    lad = areas[areas["area_type"] == "LAD"]
    mcf = load_record(list(lad.to_crs("EPSG:4326").total_bounds))
    dcat = dcat_ap(mcf)
    validate_dcat_ap(dcat)

    files: dict[str, bytes] = {
        "indicators.csv": table.to_csv(index=False).encode(),
        "indicators.sdmx.csv": data_csv.encode(),
        "indicators.dsd.xml": structure_xml,
        "metadata.iso19139.xml": iso19139(mcf).encode(),
        "metadata.dcat-ap.jsonld": dcat.serialize(format="json-ld", indent=2).encode(),
        "metadata.dc.xml": dublin_core(mcf).encode(),
    }
    buf = io.BytesIO()
    lsoa.to_parquet(buf, index=False, write_covering_bbox=True)
    files["indicators_lsoa.parquet"] = buf.getvalue()

    PUBLICATION.mkdir(exist_ok=True)
    written = {}
    for name, data in files.items():
        (PUBLICATION / name).write_bytes(data)
        written[name] = lake.write_bytes(data, "gold", f"publication/{name}")
    lake.write_delta(table, "gold", "indicators")
    log.info(
        "Published %s observations (%s areas, %s indicators) to %s and the lake",
        f"{len(table):,}",
        table["area_code"].nunique(),
        table["indicator"].nunique(),
        Path(PUBLICATION).relative_to(ROOT),
    )
    return written
