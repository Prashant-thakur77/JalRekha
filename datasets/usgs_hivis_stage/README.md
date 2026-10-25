# USGS HIVIS river-camera stage dataset (6 sites, 524 labelled images)

This is a small held-out evaluation set for the JalRekha waterline/stage estimator. It pairs real webcam images from fixed USGS stream-gauge cameras with the gauge height the gauge recorded at the same time. Every site's window brackets a storm hydrograph, so stage changes a lot within each site (from 1.5 m to 6.8 m of change).

To rebuild it (Python 3.10, stdlib + httpx, about 34 MB):

```
python scripts/fetch_stage_dataset.py --out datasets/usgs_hivis_stage
# options: --variant overlay (full-res 2688x1520, about 600 KB/img), --tolerance-min, --max-per-site, --day-start, --day-end
```

Existing images are skipped, so the script can be re-run after an interruption.

## Contents

| file | what |
|---|---|
| `images/<site_id>/*.jpg` | HIVIS `720/` variant: 720x405 (Hancock is portrait, 405x720), with the USGS text banner (site name + local time) burned into the top-left |
| `labels.csv` | one row per image (columns below) |
| `sites.csv` | camera metadata from the HIVIS NIMS API (description, lat/lng, tz, links) |
| `gauge/<nwis_site>_00065.csv` | the full raw instantaneous gauge-height series for each window ±1 day (`timestamp_utc, stage_ft, stage_m, qualifiers`) |
| `summary.json` | per-site counts from the fetch run (listed / dropped-night / dropped-no-match / kept) |

`labels.csv` columns: `site_id, image_path, timestamp_utc, stage_m, stage_ft, gauge_site, match_gap_min, source_url, gauge_timestamp_utc, qualifiers, local_time`

- `timestamp_utc` is the image capture time, parsed from the S3 key (`<camId>___YYYY-MM-DDTHH-MM-SSZ.jpg`, which is UTC). It matches the local time printed in the banner.
- `stage_ft` is the NWIS parameter 00065 (gauge height) as published, in feet above the **local gauge datum**. `stage_m = stage_ft * 0.3048`. These values are not elevations and can't be compared across sites. Dallas, for example, has a datum offset that puts its normal stage near 70 ft.
- `qualifiers` is the NWIS approval code: `P` = provisional (subject to revision), `A` = approved.
- `image_path` is relative to this directory.

## Sites

| site_id | NWIS gauge | images | stage range (ft) | stage range (m) | window (UTC) | what's in view |
|---|---|---|---|---|---|---|
| NY_East_Branch_Delaware_River_at_Hancock_Staff | 01421500 | 88 | 9.26 – 18.08 | 2.822 – 5.511 | 2026-07-26 – 08-02 | close-up of a large staff gauge (13–20 ft marks), submerged at peak |
| NY_Genesee_River_at_Avon_Staff_Gage | 04228500 | 88 | 14.45 – 24.47 | 4.404 – 7.458 | 2026-09-01 – 09-08 | staff gauge on a stone bridge abutment, plus the river bank |
| NY_Owasco_Inlet_below_Aurora_Street_at_Moravia_Staff | 04235299 | 75 | 3.63 – 8.68 | 1.106 – 2.646 | 2026-08-31 – 09-07 | inclined staff plates + a staff post mid-channel, debris during the flood |
| IL_Vermilion_River_near_Danville | 03339000 | 97 | 2.55 – 24.99 | 0.777 – 7.617 | 2026-08-12 – 08-20 | wide river view, riprap bank + truss bridge (no staff; waterline on the bank) |
| IN_White_River_at_Michigan_Street_at_Indianapolis | 03352953 | 88 | 8.70 – 18.36 | 2.652 – 5.596 | 2026-08-12 – 08-19 | wide river view from the gauge house; gauge pole occludes the right edge |
| TX_White_Rk_Ck_at_Greenville_Ave_Dallas | 08057200 | 88 | 69.90 – 87.32 | 21.305 – 26.615 | 2026-09-28 – 10-05 | urban creek from a bridge; flash flood on 10-01 (+16 ft in about 4 h, in daylight) |

Total: **524 images, 34 MB**. Three sites have a staff gauge in view. The other three need the waterline read against the bank or other structures.

## How the labels were matched

1. For each camera, every image key in the window was listed straight from the public S3 bucket (`ListObjectsV2` with prefix `720/<camId>/<camId>___<date>`).
2. Images were kept only if the local hour, in the camera's `tz` from the HIVIS API, was in [08:00, 19:00). This removes night/IR frames.
3. Each image was paired with the **nearest-in-time** NWIS instantaneous gauge-height reading (15-min data from `https://waterservices.usgs.gov/nwis/iv/?parameterCd=00065`) and kept only if the gap was **≤ 10 minutes**. The cameras fire on the quarter-hour, so the actual gaps are all **< 0.7 min** (see `match_gap_min`). Only 1 image in the whole set was dropped for having no gauge reading.
4. If more than 120 images passed for a site, it was thinned evenly in time to 120. No site reached the cap.

The raw gauge CSVs are included, so you can interpolate instead of taking the nearest reading.

## Sources

- Images: USGS HIVIS (Hydrologic Imagery Visualization and Information System), https://apps.usgs.gov/hivis/ . Per-camera pages are `https://apps.usgs.gov/hivis/camera/<site_id>`. Camera metadata comes from `https://api.waterdata.usgs.gov/nims/v0/cameras?camId=<site_id>`, and the images from the public bucket `https://usgs-nims-images.s3.amazonaws.com/720/<site_id>/` (per-image URL in `source_url`).
- Gauge height: USGS National Water Information System (NWIS) instantaneous values service, https://waterservices.usgs.gov/nwis/iv/ , parameter 00065. The site pages are linked in `sites.csv` (`https://waterdata.usgs.gov/monitoring-location/USGS-<site>/`).

## Licence and citation

USGS-authored or USGS-produced data and information, including HIVIS imagery and NWIS data, are in the **U.S. public domain**. See the USGS "Copyrights and Credits" policy: https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits . No permission is needed. USGS asks for an acknowledgement such as "Credit: U.S. Geological Survey".

Suggested citation:

> U.S. Geological Survey, 2026, Hydrologic Imagery Visualization and Information System (HIVIS) webcam imagery, https://apps.usgs.gov/hivis/, accessed 2026-10-25; and U.S. Geological Survey, 2026, National Water Information System data available on the World Wide Web (USGS Water Data for the Nation), https://waterdata.usgs.gov/, accessed 2026-10-25.

NWIS disclaimer: provisional data (`P`) are subject to revision. See https://waterdata.usgs.gov/provisional-data-statement/ .

## Caveats

- **Stage is relative to each gauge's own datum.** Evaluate per site, using either relative stage (rank/correlation, change from a reference frame) or a per-site calibration fitted on a few frames. Don't compare absolute metres across sites.
- **Rises often happen overnight.** Night frames are excluded, so for Hancock (9.4 → 17.4 ft), Vermilion (3.5 → 15.0 ft) and Moravia (4.1 → 8.7 ft) the steep part of the rise falls between the last evening frame and the first morning frame. Avon rises partly overnight and partly in daylight. Each site still covers the peak and the full recession. The Dallas flash flood (70.9 → 87.3 ft between 08:00 and 12:00 local) and the Indianapolis rise are captured in daylight.
- **Camera moves and reframing** (seen on contact sheets):
  - Moravia: framing changes noticeably during and after the 09-03 flood (debris, slight pan/zoom).
  - Vermilion: occasional view shifts (e.g. 2026-08-18 08:00 local).
  - Dallas: the view differs between 09-28 – 09-30 and 10-01 onward.
  - Avon: shows some small zoom/framing differences.

  Fixed pixel ROIs may need per-frame registration.
- **Lighting:** strong sun glare and specular water (Dallas, Vermilion, Indianapolis), hard bridge shadows across the Avon staff, and raindrops on the lens on some Indianapolis frames.
- **Burned-in text banner** in the top-left of every frame (and a USGS logo top-right). Mask those areas if your estimator looks at edges there.
- The 720px images are downscaled copies. Use `--variant overlay` for full resolution if you need to read staff graduations. That is about 600 KB per image, roughly 320 MB for this set.
- Almost all labels are provisional (`P`). Only Avon is approved (`A`).
