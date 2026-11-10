"""Build the fictional conditions and previous proposals in data/demo/.

The catalog (data/demo/catalog.json) is the public conservation price list.
Everything written here is invented for the course project: condition
wording, clients ("לקוח דמו NN"), addresses ("עיר לדוגמה"), projects,
quantities and the prices quoted in each proposal (drawn around the catalog
price). A fixed seed makes every run produce the same files.

Field names follow the app's tables (proposals, proposal_line_items,
proposal_selected_conditions, proposal_payment_milestones) so the same data
can later become the demo app's backup file.

Usage:
    python scripts/build_demo_data.py
"""

from __future__ import annotations

import json
import random
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "data" / "demo"
SEED = 29102026
PROPOSAL_COUNT = 30
VAT_RATE = 18.0

# --- Conditions (fictional wording) -------------------------------------
# `key` lets the review rules refer to a condition without matching its text.
CONDITIONS = [
    ("payment", "התשלום לפי אבני הדרך המפורטות בהצעה, תוך 30 יום מהגשת חשבון."),
    ("scaffolding_included", "פיגום והקמתו כלולים במחיר ההצעה."),
    ("scaffolding_excluded", "פיגום אינו כלול במחיר ההצעה, ויתומחר בנפרד לפי הצורך."),
    ("schedule", "משך העבודה תלוי בחגים, במזג האוויר ובזמני הייבוש של חומרי הסיד."),
    ("permits", "קבלת היתרים ואישור מחלקת השימור באחריות המזמין, אלא אם נכתב אחרת."),
    ("utilities", "המזמין יספק נקודת חשמל ומים בקרבת האתר ללא תשלום."),
    ("hidden_defects", "ליקויים נסתרים שיתגלו במהלך העבודה (למשל ברזל חלוד או אבן סדוקה מאחורי הטיח) יתומחרו בנפרד ויבוצעו רק באישור המזמין."),
    ("changes", "שינויים ותוספות יבוצעו רק לאחר אישור בכתב, לפי מחירי ההצעה או לפי מחיר שיוסכם."),
    ("measurement", "הכמויות בהצעה משוערות. החיוב לפי מדידה בפועל בגמר העבודה."),
    ("waste", "פינוי הפסולת מהעבודה לאתר מורשה כלול במחיר."),
    ("warranty", "אחריות לעבודה לשנתיים מיום המסירה, למעט נזק משימוש לא סביר או מגורם חיצוני."),
    ("access", "המזמין יאפשר גישה רציפה לאתר ולחזיתות במשך כל תקופת העבודה."),
    ("samples", "לפני הביצוע תוכן דוגמת טיח וגוון לאישור המזמין ומחלקת השימור."),
    ("insurance", "לקבלן ביטוח צד ג' וביטוח חבות מעבידים בתוקף לכל תקופת העבודה."),
    ("site_ready", "מועד תחילת העבודה ייקבע רק אחרי שהאתר יהיה פנוי ומוכן לביצוע."),
    ("waste_excluded", "פינוי הפסולת מהעבודה אינו כלול במחיר ויתומחר בנפרד, אלא אם צוין אחרת."),
]
# Validity and VAT were dropped on 31.10.2026 (the app's PDF shows both); the
# data files were edited directly then, so a rerun reshuffles the proposals.
# site_ready was added on 31.10.2026 the same way (the owner raised the
# topic; fictional wording, not his), and waste_excluded the same day (user).
ALWAYS = ["payment", "schedule", "changes", "measurement"]

# --- Work types ---------------------------------------------------------
# items: (code or [alternative codes], probability, min qty, max qty).
# Codes are written without the shared "01." prefix.
WORK_TYPES = {
    "facade_plaster": {
        "exterior": True,
        "projects": ["שיקום חזיתות טיח — מבנה מגורים משנות ה-30",
                     "חידוש טיח וצבע בחזית הרחוב",
                     "שיקום מעטפת מבנה לשימור — טיח סיד"],
        "background": "המבנה מוגדר לשימור. הטיח בחזיתות מתנתק ומתפורר במקומות רבים, ויש סדקים וצמחייה.",
        "conditions": ["scaffolding", "access", "samples", "hidden_defects", "permits"],
        "items": [
            ("09.001.0040", 0.7, 50, 400),
            (["09.001.0100", "09.001.0110", "09.001.0060"], 0.8, 80, 600),
            ("09.001.0270", 0.6, 20, 200),
            ("09.001.0194", 0.4, 20, 150),
            ("09.001.0030", 0.4, 80, 600),
            (["09.001.0222", "09.001.0250"], 0.4, 10, 80),
            (["09.001.0228", "09.001.0230"], 0.5, 10, 60),
            (["11.001.0010", "11.001.0030", "11.001.0070"], 0.8, 80, 600),
            ("24.009.0010", 0.3, 10, 80),
            ("29.001.0900", 0.6, 1, 1),
            ("29.001.0100", 0.4, 1, 6),
            ("29.001.0200", 0.3, 1, 1),
            ("11.002.0034", 0.4, 10, 60),
        ],
    },
    "facade_stone": {
        "exterior": True,
        "projects": ["שיקום חזית אבן כורכר", "ניקוי וכיחול חזית אבן", "שיקום קירות אבן במבנה היסטורי"],
        "background": "קירות האבן מלוכלכים, הכיחול שחוק, וחלק מהאבנים רופפות או חסרות.",
        "conditions": ["scaffolding", "access", "hidden_defects", "permits"],
        "items": [
            ("14.001.0060", 0.95, 40, 350),
            ("14.001.0070", 0.6, 3, 30),
            ("14.001.0080", 0.4, 5, 40),
            (["14.001.0086", "14.001.0085"], 0.4, 10, 80),
            ("14.001.0130", 0.3, 2, 12),
            ("14.001.0036", 0.3, 20, 150),
            ("14.001.0160", 0.3, 5, 40),
            ("09.001.0040", 0.5, 40, 300),
            ("29.001.0900", 0.4, 1, 1),
        ],
    },
    "balconies_concrete": {
        "exterior": True,
        "projects": ["שיקום מרפסות ובטון חשוף", "תיקוני בטון במרפסות ובמעקות", "שיקום מעקות פריקסט ומרפסות"],
        "background": "בתחתית המרפסות ובשוליהן הבטון מתקלף וברזל הזיון חשוף וחלוד.",
        "conditions": ["scaffolding", "hidden_defects", "access"],
        "items": [
            ("02.001.0180", 0.85, 10, 120),
            ("02.001.0190", 0.6, 3, 40),
            ("02.001.0200", 0.3, 10, 120),
            ("03.001.0010", 0.4, 5, 40),
            ("03.001.0120", 0.4, 5, 40),
            ("10.001.0124", 0.4, 5, 40),
            (["06.002.0260", "06.002.0270"], 0.5, 5, 60),
            ("11.002.0034", 0.5, 5, 60),
            ("05.004.0020", 0.3, 2, 12),
        ],
    },
    "roof_waterproofing": {
        "exterior": False,
        "projects": ["איטום גג שטוח", "החלפת איטום גג ומרזבים", "איטום גג ומעקות"],
        "background": "יש נזילות לדירות העליונות. האיטום בגג ישן וסדוק, והמרזבים סתומים.",
        "conditions": ["access", "warranty", "hidden_defects"],
        "items": [
            (["24.005.0040", "24.005.0010", "24.005.0030"], 0.7, 60, 400),
            (["05.003.0008", "05.003.0003", "05.003.0040"], 0.95, 60, 400),
            (["05.003.0010", "05.003.0020"], 0.6, 20, 120),
            ("05.003.0030", 0.5, 20, 120),
            ("05.004.0020", 0.5, 2, 15),
            ("05.001.0050", 0.4, 6, 40),
            ("05.001.0060", 0.3, 1, 4),
            ("24.005.0050", 0.6, 60, 400),
            ("02.004.0020", 0.3, 20, 120),
        ],
    },
    "wood_windows": {
        "exterior": False,
        "projects": ["שיקום חלונות ותריסי עץ", "שיקום נגרות מקורית בחזית", "שיקום תריסים ערביים וחלונות"],
        "background": "החלונות והתריסים המקוריים מעץ. חלק מהכנפות רקובות, הרפפות שבורות והפרזול חסר.",
        "conditions": ["access", "samples"],
        "items": [
            (["06.001.0370", "06.001.0380", "06.001.0390"], 0.9, 2, 16),
            (["06.001.0420", "06.001.0430", "06.001.0440"], 0.6, 2, 16),
            ("06.001.0190", 0.4, 1, 8),
            ("06.004.0060", 0.5, 4, 30),
            ("11.002.0011", 0.6, 5, 40),
            ("11.002.0012", 0.4, 5, 40),
            ("06.001.0010", 0.2, 1, 3),
            ("24.006.0030", 0.2, 1, 3),
        ],
    },
    "railings_grilles": {
        "exterior": True,
        "projects": ["שיקום מעקות וסורגים", "שיקום מסגרות ברזל מקוריות", "שיקום מעקות מרפסות ושער כניסה"],
        "background": "המעקות והסורגים המקוריים חלודים, חלק מהעוגנים רופפים, ויש חלקי עיטור חסרים.",
        "conditions": ["scaffolding", "access"],
        "items": [
            (["06.002.0260", "06.002.0270", "06.002.0290"], 0.9, 5, 70),
            ("06.002.0300", 0.5, 2, 16),
            ("06.002.0250", 0.3, 5, 40),
            ("11.002.0034", 0.6, 5, 70),
            ("11.002.0035", 0.4, 2, 20),
            ("06.002.0320", 0.3, 1, 2),
            ("06.002.0090", 0.15, 1, 4),
        ],
    },
    "tile_roof": {
        "exterior": True,
        "projects": ["שיקום גג רעפים", "פירוק והרכבה מחדש של גג רעפים", "שיקום גג רעפים וארגזי רוח"],
        "background": "גג הרעפים המקורי דולף, חלק מהרעפים שבורים וקורות העץ נפגעו מרטיבות.",
        "conditions": ["scaffolding", "hidden_defects", "access"],
        "items": [
            ("20.002.0010", 0.8, 40, 250),
            ("20.001.0020", 0.4, 1, 6),
            ("20.001.0040", 0.5, 10, 60),
            ("20.002.0050", 0.5, 5, 40),
            ("20.002.0120", 0.4, 40, 250),
            ("20.002.0130", 0.4, 40, 250),
            ("20.002.0170", 0.4, 40, 250),
            (["05.001.0050", "05.001.0055"], 0.5, 10, 50),
            ("20.002.0045", 0.25, 10, 80),
        ],
    },
    "stairwell": {
        "exterior": False,
        "projects": ["שיקום חדר מדרגות ולובי", "חידוש חדר מדרגות לשימור", "שיקום טראצו וטיח בחדר המדרגות"],
        "background": "חדר המדרגות המקורי: מדרגות טראצו שחוקות, טיח פנים מתקלף ומעקה עץ פגוע.",
        "conditions": ["samples", "utilities"],
        "items": [
            ("10.001.0090", 0.8, 10, 60),
            ("10.001.0100", 0.6, 5, 40),
            ("10.001.0110", 0.4, 10, 60),
            ("09.001.0025", 0.5, 30, 200),
            ("11.001.0010", 0.8, 50, 300),
            ("08.001.0040", 0.4, 3, 12),
            ("06.001.0350", 0.3, 10, 50),
            ("06.001.0520", 0.3, 1, 2),
            ("06.002.0280", 0.4, 10, 50),
            ("24.001.0060", 0.2, 1, 1),
        ],
    },
    "rising_damp": {
        "exterior": False,
        "projects": ["טיפול בלחות עולה במסד המבנה", "שיקום מסד ומניעת רטיבות", "טיפול ברטיבות בקירות קומת הקרקע"],
        "background": "בתחתית הקירות יש רטיבות עולה: הטיח מתפורר, ויש כתמי מלח עד גובה של כמטר.",
        "conditions": ["hidden_defects", "warranty"],
        "items": [
            (["05.001.0010", "14.001.0210"], 0.9, 10, 80),
            ("05.001.0030", 0.5, 10, 80),
            ("09.001.0207", 0.7, 10, 90),
            ("24.009.0010", 0.6, 10, 90),
            ("05.001.0140", 0.3, 10, 60),
            (["05.001.0110", "05.001.0120"], 0.4, 10, 80),
        ],
    },
    "ornaments": {
        "exterior": True,
        "projects": ["שיקום עיטורים וקרניזים בחזית", "שחזור פרטי טיח מעוטרים", "שיקום מסגרות חלונות ועיטורים"],
        "background": "בחזית יש קרניזים, מסגרות מעוטרות סביב החלונות ופילסטרים. חלקם סדוקים וחלקם חסרים.",
        "conditions": ["scaffolding", "samples", "permits"],
        "items": [
            (["09.001.0215", "09.001.0210"], 0.5, 5, 40),
            ("09.001.0225", 0.4, 5, 40),
            ("09.001.0260", 0.5, 5, 50),
            ("09.001.0280", 0.4, 5, 40),
            ("09.001.0330", 0.3, 1, 6),
            ("09.001.0340", 0.4, 1, 8),
            ("03.001.0010", 0.3, 5, 30),
        ],
    },
}
EXTRAS = [  # generic lines added now and then to any proposal
    ("60.001.0010", 0.25, 8, 64),
    ("24.040.0010", 0.2, 2, 15),
]

MILESTONES = [
    [("מקדמה עם החתימה על ההצעה", 30), ("עם השלמת מחצית מהעבודה", 40), ("עם מסירת העבודה", 30)],
    [("מקדמה", 20), ("לאחר השלמת עבודות ההכנה והתיקונים", 50), ("בגמר העבודה ופירוק הפיגום", 30)],
    [("מקדמה", 50), ("עם מסירת העבודה", 50)],
    [("מקדמה", 25), ("לאחר חודש עבודה", 25), ("לאחר חודשיים עבודה", 25), ("עם מסירת העבודה", 25)],
]
STREETS = ["הזית", "התאנה", "הגפן", "הרימון", "השקד", "האלה", "הדקל", "הברוש", "האורן", "הערבה"]
ORGS = [None, None, "נציגות הבית המשותף", "ועד הבית"]


def _quantity(rng: random.Random, unit: str, low: float, high: float) -> float:
    if unit == "קומפ":
        return 1
    if unit == "ש\"ע":
        return float(8 * rng.randint(max(1, int(low // 8)), max(1, int(high // 8))))
    if unit == "טון":
        return round(rng.uniform(0.2, 2.0), 1)
    if unit == "מ\"ק":
        return rng.randint(int(low * 2), int(high * 2)) / 2
    return float(rng.randint(int(low), int(high)))


def _pick_alternative(rng: random.Random, codes: list[str]) -> str:
    """The first alternative is the usual choice (70%), the rest share the remainder."""
    return codes[0] if rng.random() < 0.7 else rng.choice(codes[1:])


def _price(base: float, factor: float) -> float:
    price = base * factor
    return float(round(price / 5) * 5) if price >= 100 else float(round(price))


def build(catalog: list[dict]) -> tuple[list[dict], list[dict]]:
    rng = random.Random(SEED)
    by_code = {c["code"]: c for c in catalog}

    conditions = [
        {"id": f"cond-{key}", "key": key, "text": text, "sort_order": i, "is_active": True}
        for i, (key, text) in enumerate(CONDITIONS)
    ]

    types = list(WORK_TYPES)
    start, end = date(2025, 1, 6), date(2026, 9, 24)
    dates = sorted(start + timedelta(days=rng.randint(0, (end - start).days)) for _ in range(PROPOSAL_COUNT))

    proposals = []
    per_year: dict[int, int] = {}
    for n, issue in enumerate(dates, 1):
        main = types[(n - 1) % len(types)]
        chosen = [main]
        if rng.random() < 0.3:
            chosen.append(rng.choice([t for t in types if t != main]))

        factor = rng.uniform(0.9, 1.1)
        lines, seen = [], set()
        for wt in chosen:
            for codes, prob, low, high in WORK_TYPES[wt]["items"] + EXTRAS:
                if rng.random() > prob:
                    continue
                code = "01." + (_pick_alternative(rng, codes) if isinstance(codes, list) else codes)
                if code in seen:
                    continue
                seen.add(code)
                item = by_code[code]
                lines.append({
                    "catalog_item_id": item["id"],
                    "code": code,
                    "description": item["description"],
                    "unit": item["unit"],
                    "quantity": _quantity(rng, item["unit"], low, high),
                    "unit_price": _price(item["base_price"], factor * rng.uniform(0.95, 1.05)),
                    "discount_percent": 0.0,
                })
        lines.sort(key=lambda line: line["code"])

        keys = list(ALWAYS)
        exterior = any(WORK_TYPES[wt]["exterior"] for wt in chosen)
        for wt in chosen:
            for key in WORK_TYPES[wt]["conditions"]:
                if key == "scaffolding":
                    key = "scaffolding_included" if rng.random() < 0.6 else "scaffolding_excluded"
                    if any(k.startswith("scaffolding") for k in keys):
                        continue
                if key not in keys:
                    keys.append(key)
        for key, prob in (("warranty", 0.6), ("insurance", 0.5), ("utilities", 0.4), ("waste", 0.5)):
            if key not in keys and rng.random() < prob:
                keys.append(key)
        order = [c[0] for c in CONDITIONS]
        keys.sort(key=order.index)

        per_year[issue.year] = per_year.get(issue.year, 0) + 1
        main_info = WORK_TYPES[main]
        proposals.append({
            "id": f"demo-prop-{n:03d}",
            "proposal_number": f"D-{issue.year}-{per_year[issue.year]:03d}",
            "client_name": f"לקוח דמו {n:02d}",
            "org_name": rng.choice(ORGS),
            "project_name": rng.choice(main_info["projects"]),
            "project_address": f"רחוב {rng.choice(STREETS)} {rng.randint(2, 60)}, עיר לדוגמה",
            "background_text": main_info["background"],
            "work_types": chosen,
            "exterior_work": exterior,
            "validity_days": 30,
            "issue_date": issue.isoformat(),
            "status": "sent" if n <= PROPOSAL_COUNT - 4 else "issued",
            "vat_rate_applied": VAT_RATE,
            "line_items": lines,
            "condition_ids": [f"cond-{k}" for k in keys],
            "payment_milestones": [
                {"description": d, "percent": float(p)}
                for d, p in rng.choice(MILESTONES if len(lines) > 4 else MILESTONES[2:3])
            ],
        })
    return conditions, proposals


def _write(name: str, payload: dict) -> None:
    (DEMO / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def main() -> int:
    catalog = json.loads((DEMO / "catalog.json").read_text(encoding="utf-8"))["items"]
    conditions, proposals = build(catalog)
    note = "בדיוני, נכתב לפרויקט הקורס. אינו מבוסס על הצעות או תנאים אמיתיים."
    _write("conditions.json", {"note": note, "count": len(conditions), "items": conditions})
    _write("proposals.json", {"note": note, "count": len(proposals), "items": proposals})
    print(f"wrote {len(conditions)} conditions and {len(proposals)} proposals")
    return 0


if __name__ == "__main__":
    sys.exit(main())
