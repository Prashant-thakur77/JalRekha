# USGS river-gauge pairs for the lead-time evaluation

Upstream/downstream pairs of USGS stream gauges on the same main stem, used by
`eval/run_leadtime.py` to measure how much earlier a downstream community is
warned when the alert rule also watches the upstream gauge.

These are **U.S. rivers**. Public multi-year gauge series for the Nepal/India
rivers the system targets are not available, so this measures the mechanism on
real U.S. data. It does not measure performance in Nepal or India.

- **Source:** USGS National Water Information System (NWIS), instantaneous values,
  parameter `00065` (gauge height), USGS NWIS instantaneous values, https://waterservices.usgs.gov/nwis/iv/
- **Flood categories (optional):** NOAA NWPS gauge API, https://api.water.noaa.gov/nwps/v1/gauges/<usgs id> (flood categories, ft)
- **Licence:** U.S. public domain. Credit: U.S. Geological Survey.
- **Fetched:** 2026-10-25T11:09:14+00:00 (UTC)
- **Period:** 2021-01-01 to 2026-10-01 (TRAIN to 2023-12-31, TEST after)
- **Rebuild:** `cd backend && uv run python ../eval/fetch_hydro_pairs.py` (raw NWIS JSON is cached under `~/.cache/nadisaathi/usgs_nwis_iv/`)

## Files

| file | content |
|---|---|
| `sites/<site>.csv.gz` | gzipped CSV, `timestamp_utc,stage_m,qualifiers`, 15-min UTC grid |
| `pairs.json` | pairs, site names/coordinates, coverage checks, NWS categories and datum check |

`stage_m` = NWIS gauge height in feet x 0.3048, above the **local gauge datum**;
values are not elevations and cannot be compared between sites. Qualifiers are
the NWIS codes (`A` approved, `P` provisional, `e` estimated, ...). Missing
15-min slots are simply absent (ice, equipment, gaps).

A site is used only if at least 80% of the hours have at least
one reading in both TRAIN and TEST (some gauges report every 30 min; those slots
in between are absent, not interpolated). A pair is dropped if either site fails.

## Pairs

| pair | river | upstream | downstream | straight-line km | used |
|---|---|---|---|---|---|
| delaware_callicoon_montague | Delaware River | 01427510 DELAWARE RIVER AT CALLICOON NY | 01438500 Delaware River at Montague NJ | 54.3 | yes |
| delaware_montague_trenton | Delaware River | 01438500 Delaware River at Montague NJ | 01463500 Delaware River at Trenton NJ | 120.9 | yes |
| susquehanna_conklin_wilkesbarre | Susquehanna River | 01503000 SUSQUEHANNA RIVER AT CONKLIN NY | 01536500 Susquehanna River at Wilkes-Barre, PA | 87.5 | yes |
| susquehanna_wilkesbarre_harrisburg | Susquehanna River | 01536500 Susquehanna River at Wilkes-Barre, PA | 01570500 Susquehanna River at Harrisburg, PA | 139.4 | yes |
| potomac_hancock_pointofrocks | Potomac River | 01613000 POTOMAC RIVER AT HANCOCK, MD | 01638500 POTOMAC RIVER AT POINT OF ROCKS, MD | 72.0 | yes |
| potomac_pointofrocks_littlefalls | Potomac River | 01638500 POTOMAC RIVER AT POINT OF ROCKS, MD | 01646500 POTOMAC RIVER NEAR WASH, DC LITTLE FALLS PUMP STA | 50.8 | yes |
| juniata_huntingdon_newport | Juniata River | 01559000 Juniata River at Huntingdon, PA | 01567000 Juniata River at Newport, PA | 75.2 | yes |
| wabash_lafayette_terrehaute | Wabash River | 03335500 WABASH RIVER AT LAFAYETTE, IN | 03341500 WABASH RIVER AT TERRE HAUTE, IN | 115.3 | yes |

## Sites

`datum diff` = NWPS observed stage minus the USGS reading at the same time (ft);
near 0 means the NWS flood categories are on the USGS gauge datum.

| site | name | 15-min points | hourly coverage TRAIN | hourly coverage TEST | NWS action ft | NWS minor ft | datum diff ft |
|---|---|---|---|---|---|---|---|
| 01427510 | DELAWARE RIVER AT CALLICOON NY | 201005 | 0.996 | 0.998 | 9 | 12 | 0.0 |
| 01438500 | Delaware River at Montague NJ | 201538 | 1.000 | 1.000 | 23 | 25 | 0.0 |
| 01463500 | Delaware River at Trenton NJ | 201076 | 1.000 | 0.996 | 17 | 20 | 0.0 |
| 01503000 | SUSQUEHANNA RIVER AT CONKLIN NY | 201484 | 1.000 | 1.000 | 10 | 12 | 0.0 |
| 01536500 | Susquehanna River at Wilkes-Barre, PA | 201117 | 0.998 | 1.000 | 10 | 22 | 0.0 |
| 01559000 | Juniata River at Huntingdon, PA | 201549 | 1.000 | 1.000 | 9 | 12 | 0.0 |
| 01567000 | Juniata River at Newport, PA | 162352 | 0.995 | 1.000 | 17 | 22 | 0.0 |
| 01570500 | Susquehanna River at Harrisburg, PA | 100552 | 0.996 | 1.000 | 11 | 17 | 0.0 |
| 01613000 | POTOMAC RIVER AT HANCOCK, MD | 201070 | 1.000 | 0.996 | 21 | 25 | 0.0 |
| 01638500 | POTOMAC RIVER AT POINT OF ROCKS, MD | 200140 | 0.999 | 1.000 | 11 | 16 | 0.03 |
| 01646500 | POTOMAC RIVER NEAR WASH, DC LITTLE FALLS PUMP STA | 199799 | 0.998 | 0.991 | 5 | 10 | 0.0 |
| 03335500 | WABASH RIVER AT LAFAYETTE, IN | 200642 | 0.994 | 0.999 | 7 | 11 | 0.0 |
| 03341500 | WABASH RIVER AT TERRE HAUTE, IN | 193993 | 0.995 | 0.998 | 11.5 | 16.5 | 0.0 |
