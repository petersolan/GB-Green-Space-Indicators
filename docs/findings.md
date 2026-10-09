# Green space in Devon: findings in brief

*For decision makers and non-specialists. Reference year 2024; methods and caveats in the
[README](../README.md) and the [feasibility note](feasibility.md).*

![Residents within 300 m of public green space, and summer greenness, by neighbourhood](images/indicators_map.png)

## What we measured

1. **Access:** the share of residents who live within 300 m (about a five-minute walk) of a
   public park, playing field, play space, allotment or sports ground of at least half a
   hectare. This is the World Health Organization's suggested benchmark for urban green space.
2. **Greenness:** how green each neighbourhood looks from space in summer, from Sentinel-2
   satellite imagery (the NDVI vegetation index, and the share of land that is vegetated).

Both are reported for the ten Devon local authorities and their 729 neighbourhoods (Lower layer
Super Output Areas, about 1,600 residents each).

## Headline findings

- **59% of Devon's 1.2 million residents** live within 300 m of a qualifying public green
  space; **about 500,000 do not.**
- **The cities do best:** Plymouth 73%, Exeter 70%, Torbay 66%. The rural districts are lowest:
  Torridge and West Devon 44%, South Hams 47%.
- **137 neighbourhoods, home to about 227,000 people, are below 25%**, and in 11 nobody lives
  within 300 m. Four of those are in the cities (two in Plymouth, one each in Exeter and
  Torbay), where the nearest qualifying space is 500 to 850 m away for the typical resident;
  the other seven are rural.
- **Greener places do not have better access.** Across neighbourhoods, the two measures move in
  opposite directions (correlation −0.44). Rural Devon is the greenest from space (90% or more
  vegetated) but has the fewest public parks; the cities are greyer but better served.

| District | Residents | Within 300 m | Typical distance to nearest site | Summer NDVI | Vegetated |
|---|---|---|---|---|---|
| Plymouth | 264,713 | 72.6% | 189 m | 0.57 | 58% |
| Exeter | 130,712 | 69.7% | 201 m | 0.61 | 65% |
| Torbay | 139,314 | 66.1% | 219 m | 0.66 | 71% |
| East Devon | 150,827 | 52.0% | 284 m | 0.75 | 89% |
| Mid Devon | 82,834 | 51.9% | 285 m | 0.77 | 90% |
| Teignbridge | 134,793 | 51.6% | 288 m | 0.79 | 92% |
| North Devon | 98,616 | 51.1% | 291 m | 0.78 | 93% |
| South Hams | 88,625 | 46.8% | 325 m | 0.79 | 91% |
| West Devon | 57,090 | 43.8% | 348 m | 0.77 | 94% |
| Torridge | 68,108 | 43.6% | 356 m | 0.76 | 94% |

*Typical distance: the median for residents. NDVI ranges from −1 to 1; dense, healthy vegetation is above about 0.6.*

## How to read this

- **Access counts formal public green space only.** Countryside reached by public footpaths,
  open-access land, beaches and private gardens isn't included, so rural scores understate the
  green space rural residents actually use. For rural areas, the measure says more about
  *parks and playing fields* than about *nature*.
- **Distances are straight lines** to the edge of a site. Real walking routes are longer, so the
  true share within a five-minute walk is lower, especially where rivers, railways or main roads
  cut through.
- **Greenness is one summer** (eight clear days, June to August 2024). Cloud left 13
  neighbourhoods with less than 80% clear coverage; the published data includes each
  area's clear coverage (NDVI_CLEAR_PCT), so those values can be read with care.

## What could follow

- **Target the four urban neighbourhoods with no access** (Plymouth 013A and 003E, Exeter
  015F, Torbay 013A) for new or opened-up spaces, for example school fields with community
  access.
- **Measure walking distance on the path network** and add site entrances (OS Open Greenspace
  access points) to sharpen the urban results.
- **Add a rural measure** of access to the countryside (public rights of way, open-access land),
  so rural areas are judged on the green space that matters to them.
- **Repeat yearly**: the pipeline reruns in about two minutes, and the outputs are published in
  standard statistical (SDMX) and metadata (ISO 19115, DCAT-AP) formats, so they can feed an
  indicator portal or a national catalogue without rework.
