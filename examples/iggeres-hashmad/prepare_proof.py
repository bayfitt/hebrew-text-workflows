#!/usr/bin/env python3
"""Convert the private Iggeres HaShmad pilot to a public-renderer input."""
import argparse
import hashlib
import json
from pathlib import Path
import re

SCHEMA = "bca35bddc3e4c8046698f9b85da9529a048f5be098a5c94ffcfd55c5104856cf"
ENGINE = "hebrew-transliteration@2.11.0"

def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def words(text):
    return re.sub(r"[^\u05d0-\u05ea\s]", "", text).split()

def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--reviewed", type=Path, required=True)
    cli.add_argument("--romanized", type=Path, required=True)
    cli.add_argument("--out", type=Path, required=True)
    a = cli.parse_args()
    doc = json.loads(a.reviewed.read_text(encoding="utf-8"))
    rows = doc["rows"]
    ids = [row["id"] for row in rows]
    if [row["n"] for row in rows] != list(range(1, 51)) or len(set(ids)) != 50:
        cli.error("expected 50 unique source-ordered rows")
    records = [json.loads(line) for line in a.romanized.read_text(encoding="utf-8").splitlines() if line.strip()]
    if [record["id"] for record in records] != [doc["title"]["id"], *ids]:
        cli.error("transliteration IDs or order do not match reviewed rows")
    passages = []
    for row, roman in zip(rows, records[1:]):
        if (
            sha(row["source"]) != row["source_sha256"]
            or words(row["working"]) != words(row["he"])
            or roman["vocalized_text"] != row["he"]
            or roman["transliteration_input_sha256"] != sha(row["transliteration_reading"])
            or roman["transliteration_schema_sha256"] != SCHEMA
            or roman["transliteration_engine"] != ENGINE
            or roman["transliteration_flags"]
            or not row["en"].strip()
            or not roman["transliteration"].strip()
        ):
            cli.error(f"review check failed: {row['id']}")
        passage = {"id": row["id"], "he": row["he"], "roman": roman["transliteration"], "en": row["en"]}
        if row["notes"]:
            passage["note"] = " ".join(f"[{note['id']}] {note['text']} ({note['label']}: {note['url']})" for note in row["notes"])
        passages.append(passage)
    snapshot = {
        "schema_version": 1,
        "title": doc["title"]["en"],
        "passages": passages,
        "chapters": [{"first_id": ids[0], "label": doc["body_title"]}],
        "publication_notice": ["Private 50-passage reading proof. Unresolved readings are marked in the review ledger."],
    }
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

if __name__ == "__main__":
    main()
