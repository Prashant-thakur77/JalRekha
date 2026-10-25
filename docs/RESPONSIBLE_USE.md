# Responsible use

NadiSaathi points cameras at rivers in places where people live, and it drafts messages that can make families leave their homes. This page lists what the system does to keep that safe, and what a deploying authority must still do.

## What the system will not do

- It does not send any public message by itself. SMS, voice, CAP alerts, cross-border notices, all-clears, road status and relief dispatch all wait for a named person with the operator PIN. The approval stores who decided, when, and any edit next to the original text.
- It does not identify or track people. Faces and number plates are blurred with OpenCV YuNet detectors before a frame is stored or shown. The measurement only reads the gauge strip.
- It does not turn "unknown" into "safe". A frame that fails the quality gate cannot lower an alert level, and three uncertain readings in a row are sent to a person.
- It does not let a language model overrule the measurement. A vision model is asked only when the estimators disagree; its reply is parsed as three numbers and nothing else, and if it contradicts a confident reading, the reading stands and a person is asked.
- It does not replace official warnings. Every CAP file carries the note "Pilot decision-support draft; complements and never replaces official DHM/CWC/IMD/NDMA warnings."

The one autonomous public action is the local siren at the camera site, and only when the river is above the danger level, the image quality is good and the estimators agree. The guard also rate-limits it to six activations per hour per zone. This mirrors how community sirens are used today and keeps working when the cloud is unreachable.

## Data kept, and for how long

| Data | Kept | Where | Notes |
|---|---|---|---|
| Camera frames | redacted copies only | instance disk (`/var/lib/nadisaathi/uploads`) | removed with the instance; the S3 bucket has a 30-day lifecycle rule ready for a `frames/` prefix, not used yet |
| Stage readings, traces | the event and its review | SQLite on the instance | numbers, decisions, no personal data |
| Volunteer relief requests | text, need, people count, location rounded to about 100 m | SQLite | no names and no phone numbers are stored |
| Voice reports | the audio and its transcript | edge box / instance | shown to a person with the transcript; delete after review |
| Approvals | who approved, when, edits | SQLite, S3 `cap/` for CAP files | the audit trail of public messages |

SMS in the pilot goes only to verified test numbers. A real deployment uses the authority's own lists and its registered sender (TRAI DLT in India; the telecom operators' bulk SMS route in Nepal), and the lists never enter this system.

## Consent and signage

Every camera site needs the landowner's or the local body's written permission and a visible sign. Suggested sign text:

- English: "This camera measures the river level for flood warnings. It does not record people: faces and number plates are blurred automatically. Run by [municipality / district authority]. Contact: [phone]."
- हिन्दी: "यह कैमरा बाढ़ चेतावनी के लिए नदी का जलस्तर मापता है। यह लोगों को रिकॉर्ड नहीं करता: चेहरे और नंबर प्लेट अपने-आप धुंधले हो जाते हैं। संचालक: [नगर पालिका / ज़िला प्राधिकरण]। संपर्क: [फ़ोन]।"
- नेपाली: "यो क्यामेराले बाढी चेतावनीका लागि नदीको सतह नाप्छ। यसले मानिसको रेकर्ड गर्दैन: अनुहार र नम्बर प्लेट आफैँ धमिलो हुन्छन्। सञ्चालक: [नगरपालिका / जिल्ला प्राधिकरण]। सम्पर्क: [फोन]।"

The relief request form shows a consent note in English, Hindi and Nepali: their text and an approximate location are shared with the ward or district relief team, nothing else is kept, and they can ask the team to delete it.

## When things fail

| Failure | Behaviour |
|---|---|
| Camera moved or gauge out of view | readings are not used; the site is marked degraded; automatic actions there stop; a recalibration request goes to a person |
| Bad weather, night, glare | the frame cannot raise or lower an alert; the agent takes longer bursts and asks a gauge reader for a photo |
| Estimators disagree, no second opinion | the reading is held; after three in a row a person is asked |
| Cloud or Bedrock unavailable | rule fallback; the edge siren rule still works offline |
| Nobody approves a drafted alert | Step Functions re-notifies the operators every 15 minutes, up to three times |
| Wrong PIN attempts | five in ten minutes lock that client out for ten minutes |
| Spoofed camera | frame uploads need the camera key |

## Known limits that affect safety

Face and plate redaction recall has not been measured on our own data. In the public demo, frames, traces and approvals are readable without a PIN (the demo holds synthetic scenes and no personal data); a real deployment should put read access behind operator login too.

The real-camera evaluation covers two US sites; there is no Nepal or India footage yet. Travel times are estimates except one reported value. With official warning levels that are not consistent along a river, upstream warnings may give no extra lead time (see `docs/REPORT.md` section 6.3). Maithili and Bhojpuri message templates need review by native speakers before any public use. Model cards: `docs/MODEL_CARDS.md`.
