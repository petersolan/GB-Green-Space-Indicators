# Feasibility, options and risks

*For project sponsors and technical leads deciding how to produce green space indicators
routinely. It sets out what was tested, the options at each decision point, the risks, and a
recommendation. Results and methods are in the [README](../README.md); plain-language findings
in [findings.md](findings.md).*

## The question

Can a small team produce neighbourhood-level green space indicators every year, from open data,
on a cloud platform, published to the standards a statistics office and a data catalogue
expect, without building heavy infrastructure?

**Short answer: yes.** This prototype runs end to end in about two minutes for Devon (1.2
million residents, 729 neighbourhoods) on a laptop, against either local storage or Azure Blob
Storage, with no paid services. Scaling to England and Wales is a matter of data volume, not
design, with the caveats below.

## Decisions and options

### 1. Where the data lives

| Option | For | Against |
|---|---|---|
| **Data lake on object storage (chosen)**: GeoParquet and Delta tables on Azure Blob Storage | Cheap (pennies per month here), scales without servers, readable by Databricks, Fabric, Synapse, DuckDB and pandas; Delta gives atomic writes and history (time travel) | Spatial queries need an engine on top (DuckDB, Spark); no live editing |
| Spatial database (PostGIS) | Mature spatial SQL and indexing, multi-user editing, serves maps directly (GeoServer) | A server to run and patch; weaker as a long-term archive and for analytics at scale |
| Managed analytics platform (Databricks, Fabric) | Notebooks, scheduling, governance in one place | Licence and compute cost; platform lock-in for a small workload |

**Recommendation:** keep the lake as the system of record, and add PostGIS or a map service
only where people need interactive maps or editing. The lake layout (bronze, silver, gold)
already matches what Databricks and Fabric expect, so moving onto either later needs no rework.

### 2. Satellite processing

| Option | For | Against |
|---|---|---|
| **Read in place from a cloud catalogue (chosen)**: Sentinel-2 from Microsoft Planetary Computer via STAC, processed lazily with Xarray | No bulk downloads; only the area's pixels are read; reproducible from the catalogue query | Depends on an external free service and its terms; network speed matters |
| Download scenes, process locally | Full control, works offline | Gigabytes per run; storage and housekeeping |
| Pre-made products (e.g. ESA WorldCover, Dynamic World) | No processing | Fixed definitions and dates; less control over method and year |

**Recommendation:** in-place reading, with the clearest days chosen per run. For national
scale, run the same code on Azure compute in the same region as the catalogue (Planetary
Computer is hosted in Azure West Europe), so data never leaves the data centre.

### 3. How access is measured

| Option | For | Against |
|---|---|---|
| **Straight-line distance to site edge (chosen)** | Simple, fast, transparent; the usual first-pass method | Overstates access where rivers, railways and main roads block routes |
| Walking distance on a path network | Closer to real experience | Needs a path network (OS MasterMap Highways or OSM paths), entrances, and routing: more data and compute |
| Distance to site entrances (OS Open Greenspace access points) | Fixes the large-park problem (an edge 300 m away may have no gate) | Entrance data is incomplete in places |

**Recommendation:** publish the straight-line indicator now, clearly labelled, and pilot
network distance with entrances in the cities, where it changes results most.

### 4. Green space source

| Option | For | Against |
|---|---|---|
| **OS Open Zoomstack green space (chosen)** | Open (OGL), national, consistent types | Generalised; no entrances; typed for mapping, not for access |
| OS Open Greenspace | Open, includes access points | Similar coverage; needs an extra download |
| OS MasterMap Greenspace | Most detailed (includes private and amenity green space) | Licensed; public-sector access via the PSGA, not open |
| OpenStreetMap | Rich local detail (footpaths, gates) | Uneven completeness, which biases comparisons between areas |

## Standards and interoperability

- **Statistics:** observations are published as **SDMX-CSV 2.0**, described by an SDMX-ML 2.1
  data structure definition. The area codelist records each neighbourhood's district as its
  parent, so the geography hierarchy travels with the data. This is the format
  Eurostat, the OECD and national statistics offices exchange indicators in.
- **Metadata:** one source record produces **ISO 19115** (ISO 19139 XML, the encoding used by
  INSPIRE and the UK GEMINI profile), a **DCAT-AP 3** catalogue record that passes the official
  SHACL validation, and **Dublin Core**. They can't drift apart, because none is edited by hand.
- **Geography:** ONS codes (GSS) for areas, British National Grid for all geometry; outputs in
  GeoParquet, readable by QGIS, ArcGIS Pro, GDAL and every major analytics engine.

## Risks and dependencies

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| A free service changes terms or goes down (Planetary Computer, ONS geography API) | Medium | Run fails | Bronze layer keeps what was fetched; alternative catalogue (AWS Earth Search) uses the same STAC interface |
| Source definitions change (green space types, boundary vintages) | Medium | Year-on-year breaks | Versioned silver rules; Delta history; boundary vintage recorded in metadata |
| Indicator misread (rural "low access") | High | Wrong policy conclusions | Plain-language caveats published with the data; add a rural countryside-access measure |
| Cloud cover leaves gaps in greenness | Medium | Unreliable NDVI for some areas | Coverage published as its own indicator (NDVI_CLEAR_PCT); widen the date window where low |
| Population model error at address level | Low | Small errors in shares | Inputs are census totals; errors average out at neighbourhood level |
| Cost overrun on cloud | Low | Budget | Storage is pennies; compute only when running; no always-on services |

## Effort to take it to production

| Step | Effort |
|---|---|
| Run on a real Azure storage account, credentials in Key Vault, scheduled yearly (Azure Functions or a pipeline job) | 2–3 days |
| National coverage (England and Wales): same code, run per region on Azure compute | 3–5 days |
| Network walking distance and entrances for cities | 1–2 weeks |
| Rural countryside-access indicator (rights of way, open-access land) | 1 week |
| Publish to a catalogue (CKAN, data.gov.uk) and an SDMX registry | 2–3 days |

## Recommendation

Proceed. Adopt the lake design and the published standards as they are; label the access
indicator as straight-line and urban-focused until the network version exists; and add the
rural measure before the indicators are used to compare urban and rural areas.
