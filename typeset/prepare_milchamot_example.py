#!/usr/bin/env python3
"""Prepare an attributed proof from the public, pinned Hebrew reading edition."""
import argparse
import hashlib
import json
from pathlib import Path

REVISION = "97b2b1085bfe01091b9c00115955bd32231812c7"
SHA256 = "c0b4a5b073af97841c43bbc369504ab444e748ba011e8ef3644cc222cbda9770"
NOTICE = [
    "Rabbi Yiḥya Qappach, Milchamot Hashem. Reading edition: Ben Fitterman and contributors.",
    "Digital text: Hebrew Wikisource contributors, via the Sefaria Hebrew version titled ויקיטקסט.",
    "https://github.com/bayfitt/milchamot-hashem at " + REVISION,
    "Original and adapted reading excerpt: CC BY-SA 4.0, https://creativecommons.org/licenses/by-sa/4.0/.",
    "Changes for this example: selected passages and typesetting only, with an English-column notice. No English translation supplied.",
]

p = argparse.ArgumentParser(description=__doc__)
p.add_argument("--from-reading-edition", type=Path, required=True)
p.add_argument("--out", type=Path, required=True)
a = p.parse_args()
raw = a.from_reading_edition.read_bytes()
if hashlib.sha256(raw).hexdigest() != SHA256:
    p.error("reading-hebrew.jsonl does not match pinned public revision " + REVISION)
records = [json.loads(line) for line in raw.splitlines()]
rows = [
    {"id": entry["id"], "he": entry["vocalized_hebrew"],
     "roman": entry["transliteration"], "en": "English translation not supplied." if i == 0 else ""}
    for i, entry in enumerate(records[:4])
]
data = {
    "schema_version": 1,
    "title": "Milchamot Hashem",
    "chapters": [{"label": "Author's preface (public excerpt)", "first_id": rows[0]["id"], "footer_label": "Author’s Preface"}],
    "passages": rows,
    "publication_notice": NOTICE,
}
a.out.parent.mkdir(parents=True, exist_ok=True)
a.out.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
