# India and India–Nepal flood photos

Twenty real photographs of floods, flooded roads, bridges, relief work and rivers
in India and along the India–Nepal border (Bihar, Assam, Kerala, Uttar Pradesh,
Uttarakhand, Punjab, Tamil Nadu and Nepal's Koshi Province). NadiSaathi uses them
in two ways:

- **Web UI imagery.** Hero and story images on the frontend. They are chosen to be
  respectful: no dead bodies and no close-ups of people in distress.
- **Real-data test for the road/bridge photo check.** Nine photos (kinds
  `flooded-road` and `bridge`) show water over a road, street, underpass or bridge.
  Most also include an object of roughly known height (hand pump, kerb, car,
  autorickshaw or motorcycle wheel, compound wall, bus). `has_reference_object`
  and `reference_object` in `credits.json` record which object it is.

Every photo comes from Wikimedia Commons and is public domain, CC0, CC BY or
CC BY-SA. Each one must be credited as shown in the table below. That credit is
a licence requirement for the photos.

## Layout

| Path | Contents |
|---|---|
| `datasets/india_flood_photos/originals/<id>.<ext>` | Original files, byte-identical to Commons (SHA-1 checked) |
| `frontend/public/images/india/<id>-1600.webp` | Web copy, longest side 1600 px, WebP quality 78, no EXIF |
| `frontend/public/images/india/<id>-800.webp` | Web copy, longest side 800 px, same settings |
| `frontend/public/images/india/credits.json` | One record per photo: title, place, date, kind, English and Hindi alt text, author, licence, licence URL, Commons page, original URL, SHA-1, reference object |
| `docs/PHOTO_CREDITS.md` | The credits table, for the app's credits page |

The web copies total about 5.3 MB (20 × 2 files).

Kinds in the set: 6 `flood-scene`, 7 `flooded-road`, 2 `bridge`, 2 `relief`, 3 `river`.

Licences in the set: 1 public domain, 1 CC0, 4 CC BY 2.0, 2 CC BY 3.0, 1 CC BY 4.0,
1 CC BY-SA 2.0, 2 CC BY-SA 3.0, 8 CC BY-SA 4.0.

## How it was collected (October 2026)

All queries went to `https://commons.wikimedia.org/w/api.php` with a descriptive
User-Agent that includes a contact URL.

1. **Category listing.** For each category below, the API listed the files and their
   licence metadata in one call:

   ```
   action=query&generator=categorymembers&gcmtitle=Category:<name>&gcmtype=file&gcmlimit=200
     &prop=imageinfo&iiprop=url|extmetadata|size|mime
     &iiextmetadatafilter=LicenseShortName|LicenseUrl|Artist|DateTimeOriginal|ImageDescription|Categories|Restrictions
   ```

   Categories searched: Floods in India, Floods in Bihar, 2008 Kosi floods,
   Flooded roads in India, Floods in Assam, Floods in India by state or territory,
   Floods in Uttar Pradesh, Flood damage in India, Flood level signs in India,
   2018 Kerala floods (and its Kochi, Kottayam and Angamaly subcategories),
   Floods in Kerala, 2019 Kerala floods, Operation Madad (2018),
   2013 North India floods, Operation Rahat, Floods in Uttarakhand,
   Floods in West Bengal, Floods in Nepal, Flood damage in Nepal,
   2017 floods in India, 2019 Bihar floods, 2024 Bihar floods, Kosi River,
   Koshi Barrage.

2. **Full-text search** in the File namespace, same `prop=imageinfo` parameters:

   ```
   action=query&generator=search&gsrnamespace=6&gsrlimit=50&gsrsearch=<query>
   ```

   Queries: `flooded road Bihar`, `flood Patna street`, `waterlogged road India`,
   `flood Guwahati road`, `Bihar flood 2019`, `flooded street India flickr`,
   `Kosi flood`, `Assam flood boat`, `DFID flood India`, `Supaul flood`,
   `Darbhanga flood`, `Muzaffarpur flood`, `Gorakhpur flood`, `Dhemaji flood`,
   `Majuli flood`, `Brahmaputra flood`, `Uttarakhand flood 2013 road`,
   `Kedarnath flood`, `Chennai flood 2015`, `Mumbai flood street`,
   `Kosi river Bihar`, `embankment Bihar river`, `Gandak river flood`,
   `Ganga flood Patna`, `Bagmati river Bihar`, `flood India causeway`,
   `submerged bridge India`, `Srinagar flood 2014`.

3. **Licence filter.** A file was kept only if `extmetadata.LicenseShortName` was
   `Public domain`, `CC0`, `CC BY 2.0/2.5/3.0/4.0` or `CC BY-SA 2.0/3.0/4.0`.
   Everything else was dropped, including GODL-India (many Government of India
   flood photos on Commons carry it), NC, ND and unlicensed files. Files with
   unclear authorship were also dropped, for example where the uploader credits a
   different photographer in the description, or where the author is only
   "assumed".

4. **Visual review.** About 60 candidates of at least 1500 px were reviewed as
   contact sheets. They were rejected for blur, heavy watermarks, maps or satellite
   images, or identifiable people in distress (for example a child being carried
   during a rescue). PD, CC0 and CC BY files were preferred over CC BY-SA when the
   content was comparable.

5. **Download and web copies.** Originals were downloaded from the `url` field of
   `imageinfo` and checked against the Commons SHA-1. The web copies were made
   with Pillow: EXIF orientation applied, converted to RGB, fitted into a
   1600 px and an 800 px box with Lanczos, and saved as WebP at quality 78 with
   no metadata.

## Reproducing

```bash
python scripts/fetch_india_flood_photos.py                         # originals, SHA-1 verified
cd backend && uv run python ../scripts/fetch_india_flood_photos.py --web   # also rebuild the webp copies
```

The script reads `frontend/public/images/india/credits.json`. It skips files that
are already present and verified, and waits between downloads.

## Notes and caveats

- Dates, places and authors come from each file's Commons page. The NDRF rescue
  photo is dated 2008-07-17 on Commons, which is about a month before the Kosi
  embankment breach of 18 August 2008. The date is reproduced as recorded.
- "Reference object" heights are approximate. Wheel and kerb heights vary by
  vehicle and street, so use them for an order-of-magnitude check only, not for
  calibrated depth.
- The Chennai street photos and the Kochi police-vehicle photo show heavy monsoon
  waterlogging in a city, not river flooding. They are included because they
  clearly show water depth against vehicles and kerbs.
- Resized copies of CC BY-SA photos stay under the same CC BY-SA licence.

## Credits

Photos are listed with their authors and licences as required. Each title links
to the file's Commons page, which holds the full licence text and history.

| # | Photo | Place | Date | Kind | Author | Licence | Source |
|---|---|---|---|---|---|---|---|
| 1 | Flooded farmland in northern Bihar during the 2008 Kosi flood (`bihar-kosi-flood-2008`) | Northern Bihar, Kosi basin, Bihar, India | 2008-09-09 | flood-scene | Manoj nav (English Wikipedia) | [CC BY 3.0](https://creativecommons.org/licenses/by/3.0) | [File:Flooded Bihar.JPG](https://commons.wikimedia.org/wiki/File:Flooded_Bihar.JPG) |
| 2 | Flooded village on the Brahmaputra plains (`assam-goalpara-flood-2010`) | Goalpara district, Assam, India | 2010-09-01 | flood-scene | PP Yoonus | [Public domain](https://commons.wikimedia.org/wiki/Template:PD-self) | [File:Brahmaputra Plains in Goalpara District of Assam 857.jpg](https://commons.wikimedia.org/wiki/File:Brahmaputra_Plains_in_Goalpara_District_of_Assam_857.jpg) |
| 3 | Assam flood, September 2015 (`assam-flood-2015`) | Assam, India | 2015-09-04 | flood-scene | Pradip Nemane | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0) | [File:Assam flood in 2015.jpg](https://commons.wikimedia.org/wiki/File:Assam_flood_in_2015.jpg) |
| 4 | Flood-affected home at Tipomia village (`assam-jorhat-tipomia-2026`) | Tipomia village, near Gaurisagar (Jorhat area), Assam, India | 2026-08-01 | flood-scene | Nskjnv | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0) | [File:Flood Affected home at Tipomia Village.jpg](https://commons.wikimedia.org/wiki/File:Flood_Affected_home_at_Tipomia_Village.jpg) |
| 5 | Monsoon flooding near PG Chowk, Triyuga (`nepal-triyuga-2019`) | Triyuga Municipality, Udayapur District, Koshi Province, Nepal | 2019-09-18 | flood-scene | Rmfenner | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0) | [File:Monsoonal flooding near PG Chowk, Triyuga, Nepal 2019 1913.jpg](https://commons.wikimedia.org/wiki/File:Monsoonal_flooding_near_PG_Chowk,_Triyuga,_Nepal_2019_1913.jpg) |
| 6 | A bench in the flooded Ganga at Prayagraj (`prayagraj-ganga-bench-2011`) | Ganga riverfront, Prayagraj (Allahabad), Uttar Pradesh, India | 2011-09-09 | flood-scene | Barry Pousman | [CC BY 2.0](https://creativecommons.org/licenses/by/2.0) | [File:Chilling on a bench in the flooded Ganges (6130950760).jpg](https://commons.wikimedia.org/wiki/File:Chilling_on_a_bench_in_the_flooded_Ganges_(6130950760).jpg) |
| 7 | Flooded road in Amritsar (`amritsar-flooded-road-2013`) | Amritsar, Punjab, India | 2013-07-05 | flooded-road | Nitin Chandra | [CC0](https://creativecommons.org/publicdomain/zero/1.0/deed.en) | [File:Flooded road in Amritsar, July 2013.jpg](https://commons.wikimedia.org/wiki/File:Flooded_road_in_Amritsar,_July_2013.jpg) |
| 8 | Hand pump in a flooded Chennai street (`chennai-handpump-street-2008`) | Chennai, Tamil Nadu, India | 2008-10-22 | flooded-road | McKay Savage | [CC BY 2.0](https://creativecommons.org/licenses/by/2.0) | [File:India - Chennai - Monsoon - 05 (3058218683).jpg](https://commons.wikimedia.org/wiki/File:India_-_Chennai_-_Monsoon_-_05_(3058218683).jpg) |
| 9 | Autorickshaw on a flooded Chennai street (`chennai-autorickshaw-street-2008`) | Chennai, Tamil Nadu, India | 2008-10-22 | flooded-road | McKay Savage | [CC BY 2.0](https://creativecommons.org/licenses/by/2.0) | [File:India - Chennai - Monsoon - 03 (3058213357).jpg](https://commons.wikimedia.org/wiki/File:India_-_Chennai_-_Monsoon_-_03_(3058213357).jpg) |
| 10 | Motorcycle parked in a flooded Chennai street (`chennai-motorcycle-street-2008`) | Chennai, Tamil Nadu, India | 2008-10-22 | flooded-road | McKay Savage | [CC BY 2.0](https://creativecommons.org/licenses/by/2.0) | [File:India - Chennai - Monsoon - 02 (3059047958).jpg](https://commons.wikimedia.org/wiki/File:India_-_Chennai_-_Monsoon_-_02_(3059047958).jpg) |
| 11 | Police vehicle driving through monsoon waterlogging in Kochi (`kerala-police-suv-2010`) | Kochi, Ernakulam district, Kerala, India | 2010-06-12 | flooded-road | Liji Jinaraj | [CC BY-SA 2.0](https://creativecommons.org/licenses/by-sa/2.0) | [File:Kerala police 4x4 driving through a monsoon.jpg](https://commons.wikimedia.org/wiki/File:Kerala_police_4x4_driving_through_a_monsoon.jpg) |
| 12 | State Highway 32 under water at Pala (`kerala-pala-sh32-2018`) | Pala, Kottayam district, Kerala, India | 2018-08-17 | flooded-road | Praveenp | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0) | [File:Pala during 2018 Kerala floods 01.jpg](https://commons.wikimedia.org/wiki/File:Pala_during_2018_Kerala_floods_01.jpg) |
| 13 | Flooded roadside gate on the Thrissur–Irinjalakuda route (`kerala-thrissur-flooded-gate-2018`) | Ettumuna, Thrissur–Irinjalakuda road, Kerala, India | 2018-09-11 | flooded-road | Smibinozone | [CC BY 3.0](https://creativecommons.org/licenses/by/3.0) | [File:Kerala flood 2018.jpg](https://commons.wikimedia.org/wiki/File:Kerala_flood_2018.jpg) |
| 14 | Bus caught in a flooded railway underpass, Mathura (`mathura-underpass-bus-2016`) | Mathura, Uttar Pradesh, India | 2016-07-17 | bridge | Vadaykeviv | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0) | [File:Flood in Mathura, Uttar Pradesh.jpg](https://commons.wikimedia.org/wiki/File:Flood_in_Mathura,_Uttar_Pradesh.jpg) |
| 15 | Damaged bridge over a swollen river, Uttarkashi (`uttarkashi-bridge-2013`) | Uttarkashi district, Uttarakhand, India | 2013-06-17 | bridge | sumit (Commons user Aadhyantindia) | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0) | [File:Uttarkashi flood 2013.jpg](https://commons.wikimedia.org/wiki/File:Uttarkashi_flood_2013.jpg) |
| 16 | NDRF rescue boat during the Kosi flood (`bihar-ndrf-rescue-2008`) | Kosi flood area, Bihar, India | 2008-07-17 | relief | Kumarrakajee | [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0) | [File:NDRF in Bihar Flood.jpg](https://commons.wikimedia.org/wiki/File:NDRF_in_Bihar_Flood.jpg) |
| 17 | Fishing boats sent from Kollam for rescue work in Chengannur (`kerala-rescue-boats-2018`) | Vady, Kollam, Kerala, India | 2018-08-17 | relief | Kannan Shanmugam, Shanmugam studio, Kollam | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0) | [File:Boats from Vady Kollam transported to chenganoor flood rescue2.jpg](https://commons.wikimedia.org/wiki/File:Boats_from_Vady_Kollam_transported_to_chenganoor_flood_rescue2.jpg) |
| 18 | Koshi Barrage at golden hour (`koshi-barrage-sunset-2015`) | Koshi Barrage, near the India–Nepal border, Koshi Province, Nepal | 2015-01-16 | river | Khan Anas333 | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0) | [File:Koshi barrage golden hour.jpg](https://commons.wikimedia.org/wiki/File:Koshi_barrage_golden_hour.jpg) |
| 19 | Koshi Barrage looking south (`koshi-barrage-2018`) | Koshi Barrage, near the India–Nepal border, Koshi Province, Nepal | 2018-11-24 | river | Innocentbunny | [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0) | [File:Kosi Barrage looking south.jpg](https://commons.wikimedia.org/wiki/File:Kosi_Barrage_looking_south.jpg) |
| 20 | Riverbank erosion at Semra during the 2015 flood (`ghazipur-semra-erosion-2015`) | Semra, Ghazipur district, Uttar Pradesh, India | 2015-08-08 | river | कलमकार (Kalamkar) | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0) | [File:Semra in flood.jpg](https://commons.wikimedia.org/wiki/File:Semra_in_flood.jpg) |
