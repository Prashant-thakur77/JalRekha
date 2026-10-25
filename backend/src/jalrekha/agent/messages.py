"""Short, plain alert texts in English, Hindi, Nepali, Maithili and Bhojpuri.

Every number in a message is filled from tool outputs (measurement, Kalman
rate, graph ETA); nothing is free text from a model. Templates are kept short
enough that Devanagari (UCS-2) messages fit in two SMS segments.
Maithili and Bhojpuri templates are marked ``needs_native_review``.
"""

from __future__ import annotations

import math
import re

GSM7 = set(
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà"
)
GSM7_EXT = set("^{}\\[~]|€")

NEEDS_REVIEW = {"mai", "bho"}

# Devanagari place and river names (Nepali spelling in Nepal, Hindi spelling in India).
DEVA = {
    "Koshi / Kosi": {"en": "Koshi", "ne": "कोशी", "hi": "कोसी", "mai": "कोसी", "bho": "कोसी"},
    "Gandaki / Narayani / Gandak": {"en": "Narayani/Gandak", "ne": "नारायणी", "hi": "गंडक", "mai": "गंडक", "bho": "गंडक"},
    "Karnali / Ghaghara": {"en": "Karnali/Ghaghara", "ne": "कर्णाली", "hi": "घाघरा", "mai": "घाघरा", "bho": "घाघरा"},
    "Bagmati": {"ne": "बागमती", "hi": "बागमती", "mai": "बागमती", "bho": "बागमती"},
    "Chatara": "चतरा",
    "Koshi Barrage (Bhimnagar)": "कोशी ब्यारेज",
    "Birpur": "बीरपुर",
    "Basua": "बसुआ",
    "Baltara": "बलतारा",
    "Devghat (Narayani)": "देवघाट",
    "Gandak Barrage (Valmikinagar)": "वाल्मीकिनगर",
    "Chatia": "चटिया",
    "Dumariaghat": "डुमरियाघाट",
    "Chisapani (Karnali)": "चिसापानी",
    "Girijapur Barrage": "गिरिजापुर",
    "Elgin Bridge": "एल्गिन ब्रिज",
    "Karmaiya (Bagmati)": "कर्मैया",
    "Dheng Bridge": "ढेंग",
    "Benibad": "बेनीबाद",
    "Nepal": {"ne": "नेपाल", "hi": "नेपाल", "mai": "नेपाल", "bho": "नेपाल"},
    "India": {"ne": "भारत", "hi": "भारत", "mai": "भारत", "bho": "भारत"},
    "NP": {"en": "Nepal", "ne": "नेपाल", "hi": "नेपाल", "mai": "नेपाल", "bho": "नेपाल"},
    "IN": {"en": "India", "ne": "भारत", "hi": "भारत", "mai": "भारत", "bho": "भारत"},
}

TEMPLATES: dict[str, dict[str, str]] = {
    # Downstream (often cross-border) warning driven by the upstream camera.
    "downstream": {
        "en": "FLOOD WARNING {river}: rising fast upstream at {up} ({up_country}), {rate} m/h. May reach {place} in {eta_min}-{eta_max} h. Move people, animals, papers to high ground. {sender}",
        "hi": "बाढ़ चेतावनी: {up} ({up_country}) में {river} तेज़ी से बढ़ रही, {rate} मी/घं। {place} में {eta_min}-{eta_max} घंटे में पहुँच सकती है। ऊँची जगह जाएँ। {sender}",
        "ne": "बाढी चेतावनी: {up} ({up_country}) मा {river} छिटो बढ्दै, {rate} मि/घ। {place} मा {eta_min}-{eta_max} घण्टामा पुग्न सक्छ। अग्लो ठाउँमा जानुहोस्। {sender}",
        "mai": "बाढ़ि चेतावनी: {up} ({up_country}) मे {river} तेजी सँ बढ़ि रहल, {rate} मी/घं। {place} मे {eta_min}-{eta_max} घंटा मे पहुँचि सकैए। ऊँच जगह जाउ। {sender}",
        "bho": "बाढ़ चेतावनी: {up} ({up_country}) में {river} तेजी से बढ़त बा, {rate} मी/घं। {place} में {eta_min}-{eta_max} घंटा में पहुँच सकेला। ऊँच जगह जाईं। {sender}",
    },
    # Local warning for the communities at the camera site.
    "local_rise": {
        "en": "FLOOD WARNING {river} at {place}: {stage} m, rising {rate} m/h. May cross warning level {warning} m in ~{cross_min} min. Keep away from the river, be ready to move. {sender}",
        "hi": "बाढ़ चेतावनी {place}: {river} {stage} मी, {rate} मी/घं से बढ़ रही। ~{cross_min} मिनट में चेतावनी स्तर {warning} मी पार। नदी से दूर रहें। {sender}",
        "ne": "बाढी चेतावनी {place}: {river} {stage} मि, {rate} मि/घ ले बढ्दै। ~{cross_min} मिनेटमा चेतावनी तह {warning} मि नाघ्न सक्छ। नदीबाट टाढा रहनुहोस्। {sender}",
        "mai": "बाढ़ि चेतावनी {place}: {river} {stage} मी, {rate} मी/घं सँ बढ़ि रहल। ~{cross_min} मिनट मे चेतावनी स्तर {warning} मी पार। नदी सँ दूर रहू। {sender}",
        "bho": "बाढ़ चेतावनी {place}: {river} {stage} मी, {rate} मी/घं से बढ़त बा। ~{cross_min} मिनट में चेतावनी स्तर {warning} मी पार। नदी से दूर रहीं। {sender}",
    },
    # Local warning once the water is already above the warning level and still rising.
    "local_above": {
        "en": "FLOOD WARNING {river} at {place}: {stage} m, above warning level {warning} m, rising {rate} m/h. Danger level {danger} m. Be ready to move now. {sender}",
        "hi": "बाढ़ चेतावनी {place}: {river} {stage} मी, चेतावनी स्तर {warning} मी से ऊपर, {rate} मी/घं से बढ़ रही। तुरंत तैयार रहें। {sender}",
        "ne": "बाढी चेतावनी {place}: {river} {stage} मि, चेतावनी तह {warning} मि माथि, {rate} मि/घ ले बढ्दै। सर्न तयार रहनुहोस्। {sender}",
        "mai": "बाढ़ि चेतावनी {place}: {river} {stage} मी, चेतावनी स्तर {warning} मी सँ ऊपर, {rate} मी/घं सँ बढ़ि रहल। तैयार रहू। {sender}",
        "bho": "बाढ़ चेतावनी {place}: {river} {stage} मी, चेतावनी स्तर {warning} मी से ऊपर, {rate} मी/घं से बढ़त बा। तैयार रहीं। {sender}",
    },
    "danger": {
        "en": "DANGER {river} at {place}: {stage} m, above danger level {danger} m. Leave low ground NOW. Go to {shelter}. {sender}",
        "hi": "खतरा {place}: {river} {stage} मी, खतरे के स्तर {danger} मी से ऊपर। निचला इलाका तुरंत छोड़ें। {shelter} जाएँ। {sender}",
        "ne": "खतरा {place}: {river} {stage} मि, खतराको तह {danger} मि भन्दा माथि। तुरुन्तै होचो ठाउँ छोड्नुहोस्। {shelter} जानुहोस्। {sender}",
        "mai": "खतरा {place}: {river} {stage} मी, खतराक स्तर {danger} मी सँ ऊपर। निचला जगह तुरंत छोड़ू। {shelter} जाउ। {sender}",
        "bho": "खतरा {place}: {river} {stage} मी, खतरा के स्तर {danger} मी से ऊपर। निचला जगह तुरंत छोड़ीं। {shelter} जाईं। {sender}",
    },
    "all_clear": {
        "en": "UPDATE {river} at {place}: water falling ({stage} m, {rate} m/h). Stay alert. Do not cross flooded roads. {sender}",
        "hi": "सूचना {place}: {river} का पानी घट रहा है ({stage} मी, {rate} मी/घं)। सतर्क रहें, पानी भरी सड़क पार न करें। {sender}",
        "ne": "सूचना {place}: {river} को पानी घट्दैछ ({stage} मि, {rate} मि/घ)। सतर्क रहनुहोस्, डुबेको बाटो नकाट्नुहोस्। {sender}",
        "mai": "सूचना {place}: {river} क पानि घटि रहल अछि ({stage} मी, {rate} मी/घं)। सतर्क रहू, पानि भरल सड़क पार नहि करू। {sender}",
        "bho": "सूचना {place}: {river} के पानी घटत बा ({stage} मी, {rate} मी/घं)। सतर्क रहीं, पानी भरल सड़क पार मत करीं। {sender}",
    },
}

SENDER = {"np": "-NadiSaathi", "in": "-NadiSaathi", "ar": "-JalRekha"}
DEFAULT_SHELTER = {"en": "the nearest shelter", "hi": "नज़दीकी आश्रय", "ne": "नजिकको आश्रयस्थल", "mai": "लगक आश्रय", "bho": "नजदीकी आश्रय"}


def localise(name: str, lang: str) -> str:
    v = DEVA.get(name)
    if v is None or lang == "en":
        if isinstance(v, dict) and lang in v:
            return v[lang]
        return name
    if isinstance(v, dict):
        return v.get(lang) or v.get("hi") or name
    return v


def _fmt(x: float | None, nd: int = 1) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "?"
    return f"{x:.{nd}f}"


def render(kind: str, lang: str, facts: dict) -> str:
    tpl = TEMPLATES[kind].get(lang) or TEMPLATES[kind]["en"]
    values = {
        "river": localise(facts.get("river", ""), lang),
        "place": localise(facts.get("place", ""), lang),
        "up": localise(facts.get("up", ""), lang),
        "up_country": localise(facts.get("up_country", ""), lang),
        "rate": _fmt(facts.get("rate_m_per_h"), 1),
        "stage": _fmt(facts.get("stage_m"), 2),
        "warning": _fmt(facts.get("warning_m"), 1),
        "danger": _fmt(facts.get("danger_m"), 1),
        "eta_min": _fmt(facts.get("eta_min_h"), 0),
        "eta_max": _fmt(facts.get("eta_max_h"), 0),
        "cross_min": str(int(round(facts["cross_min"]))) if facts.get("cross_min") is not None else "?",
        "shelter": facts.get("shelter") or DEFAULT_SHELTER.get(lang, DEFAULT_SHELTER["en"]),
        "sender": facts.get("sender", "-NadiSaathi"),
    }
    return re.sub(r"\s+", " ", tpl.format(**values)).strip()


def sms_segments(text: str) -> dict:
    """SMS encoding and segment count (GSM-7: 160/153 chars, UCS-2: 70/67)."""
    if all(c in GSM7 or c in GSM7_EXT for c in text):
        units = sum(2 if c in GSM7_EXT else 1 for c in text)
        single, multi, enc = 160, 153, "GSM-7"
    else:
        # UCS-2 counts UTF-16 code units
        units = len(text.encode("utf-16-le")) // 2
        single, multi, enc = 70, 67, "UCS-2"
    segments = 1 if units <= single else math.ceil(units / multi)
    return {"encoding": enc, "units": units, "segments": segments}


def build_messages(kind: str, langs: list[str], facts: dict) -> list[dict]:
    out = []
    for lang in langs:
        text = render(kind, lang, facts)
        seg = sms_segments(text)
        out.append(
            {
                "lang": lang,
                "text": text,
                "chars": len(text),
                "segments": seg["segments"],
                "encoding": seg["encoding"],
                "needs_native_review": lang in NEEDS_REVIEW,
            }
        )
    return out
