#!/usr/bin/env python3
"""Book checkpoints: plan, verify Google English, review niqqud, gate exports."""
import argparse
import json
import re
import subprocess
import tempfile
from pathlib import Path

from review_niqqud import plain, review
from workflow_io import digest, read_records, separate_output, write_json, write_records

HERE = Path(__file__).resolve().parent
FORMULA_ERRORS = {'#ERROR!', '#REF!', '#VALUE!', '#N/A', '#NAME?', '#NUM!', '#NULL!', '#DIV/0!'}


def pin(value):
    return digest(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def nonblank(value):
    return isinstance(value, str) and bool(value.strip())


def unindexed(path):
    """Read source or per-occurrence decisions without requiring one id per row."""
    text = Path(path).read_text(encoding='utf-8')
    try:
        rows = json.loads(text)
    except json.JSONDecodeError:
        rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    if isinstance(rows, dict):
        rows = rows.get('records', [rows])
    require(isinstance(rows, list) and all(isinstance(row, dict) for row in rows), 'Expected records')
    return rows


def plan(manifest, source):
    require(re.fullmatch(r'[a-z0-9][a-z0-9-]*', manifest['book_id']), 'Invalid book ID')
    require(nonblank(manifest.get('source_edition')) and nonblank(manifest.get('source_revision')),
            'Pin source edition and revision')
    mode = manifest.get('translation_mode', 'source-first')
    require(mode in {'source-first', 'google-comparison'}, 'Invalid translation mode')
    require(source and manifest['source_sha256'] == pin(source), 'Source snapshot pin mismatch or empty source')
    records = []
    refs = set()
    for index, row in enumerate(source, 2):
        ref, text = row['source_ref'], row['source_text']
        require(nonblank(ref) and ref not in refs and nonblank(text), 'Missing source text or duplicate source reference')
        require(row.get('source_kind') in {'typed', 'ocr'}, 'Declare typed/OCR provenance on every row')
        require(row['source_kind'] != 'ocr' or nonblank(row.get('ocr_evidence')),
                'OCR rows need an image/page reference or audit artifact')
        refs.add(ref)
        records.append({**{key: row[key] for key in ('source_ref', 'source_text', 'source_kind',
                                              'ocr_evidence', 'editorial_english') if key in row},
                        'id': manifest['book_id'] + '-' + pin(ref)[:24],
                        'source_sha256': digest(text), 'source_edition': manifest['source_edition'],
                        'source_revision': manifest['source_revision'], 'sheet_row': index,
                        'translation_mode': mode})
        if mode == 'google-comparison':
            records[-1]['google_formula'] = f'=GOOGLETRANSLATE(B{index},"he","en")'
    return records


def align(rows, observed, label):
    require(len(rows) == len(observed), f'{label}: row count mismatch')
    for row, actual in zip(rows, observed):
        require(actual['id'] == row['id'] and actual['source_sha256'] == row['source_sha256'],
                f'{label}: row identity or source pin mismatch: {row["id"]}')
        yield row, actual


def english(rows, edits):
    require(rows, 'Empty English checkpoint')
    output = []
    for row, decision in align(rows, edits, 'English review'):
        require(nonblank(decision.get('english')) and nonblank(decision.get('english_note')),
                'English decision missing')
        output.append({**row, 'english': decision['english'], 'english_note': decision['english_note']})
    return output


def compare_google(rows, live, frozen, notes):
    require(rows and all(row.get('translation_mode') == 'google-comparison' for row in rows),
            'Google evidence is accepted only in explicit google-comparison mode')
    output = []
    for (row, a), (_, b), (_, decision) in zip(
            align(rows, live, 'live formula'), align(rows, frozen, 'frozen value'),
            align(rows, notes, 'comparison notes'), strict=True):
        require(a.get('source_text') == b.get('source_text') == row['source_text'],
                'Formula or frozen readback Hebrew differs')
        value = a.get('value')
        require(a.get('formula') == row['google_formula'] and a.get('error') is None and nonblank(value)
                and value not in FORMULA_ERRORS and not value.lstrip().startswith('=')
                and value.strip().casefold() not in {'loading...', 'loading…'}, 'Missing successful live Google formula/value')
        require(b.get('formula') is None and b.get('value') == value, 'Frozen Google cell differs or is still a formula')
        comparison_note = decision.get('google_comparison_note')
        require(nonblank(row.get('english')) and nonblank(row.get('english_note'))
                and decision.get('english_sha256') == digest(row['english'])
                and decision.get('google_sha256') == digest(value) and nonblank(comparison_note),
                'Independent English or comparison evidence missing or stale')
        output.append({**row, 'google_translate': value, 'google_comparison_note': comparison_note})
    return output


def point(rows, drafts, decisions, require_resolved):
    inputs = []
    for row, draft in align(rows, drafts, 'niqqud review'):
        text = draft.get('vocalized_text')
        require(draft.get('english_sha256') == digest(row['english']) and nonblank(text)
                and nonblank(draft.get('niqqud_note')), 'Niqqud review missing or stale English pin')
        expanded = draft.get('expanded_text', row['source_text'])
        require(nonblank(expanded) and plain(text) == plain(expanded), 'Pointing changed expanded Hebrew consonants')
        require(expanded == row['source_text'] or nonblank(draft.get('expansion_note')),
                'Editorial expansion needs a note')
        inputs.append({**row, 'expanded_text': expanded, 'vocalized_text': text,
                       'vocalization_flags': draft.get('vocalization_flags', []),
                       'reading_edits': draft.get('reading_edits', []),
                       'expansion_note': draft.get('expansion_note', ''),
                       'niqqud_note': draft['niqqud_note']})
    reviewed, audit = review(inputs, decisions, 'expanded_text', require_resolved)
    for row in reviewed:
        row['contextual_notes'] = [a['reason'] for a in audit if a['id'] == row['id'] and a['reason']]
    return reviewed, audit


def sheet_rows(rows):
    fields = ('id', 'source_sha256', 'source_ref', 'source_edition', 'source_revision',
              'source_text', 'source_kind', 'ocr_evidence',
              'translation_mode', 'google_translate', 'google_comparison_note', 'editorial_english', 'english', 'english_note', 'expanded_text',
              'expansion_note', 'vocalized_text', 'niqqud_note', 'contextual_notes', 'transliteration',
              'transliteration_engine', 'transliteration_schema_sha256',
              'transliteration_library_sha256', 'transliteration_wrapper_sha256')
    for row in rows:
        require(row.get('translation_mode') != 'google-comparison' or
                (nonblank(row.get('google_translate')) and nonblank(row.get('google_comparison_note'))),
                'Google comparison mode requires a verified comparison before upload')
        require(row.get('transliteration_status') == 'draft' and nonblank(row.get('transliteration'))
                and not row.get('transliteration_flags')
                and row.get('transliteration_input_sha256') == digest(row['vocalized_text']),
                f'Blocked, flagged or stale deterministic transliteration: {row["id"]}')
    return [{field: row.get(field, '') for field in fields} for row in rows]


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    stages = cli.add_subparsers(dest='stage', required=True)
    for name, flags in {
        'pin-source': ('source',),
        'plan': ('manifest', 'source', 'output'),
        'english': ('input', 'edits', 'output'),
        'compare-google': ('input', 'live', 'frozen', 'notes', 'output'),
        'niqqud-audit': ('input', 'drafts', 'output'),
        'niqqud': ('input', 'drafts', 'decisions', 'output'),
        'transliterate': ('input', 'cache', 'output'),
        'sheet-rows': ('input', 'output'),
        'export-input': ('input', 'readback', 'output'),
    }.items():
        stage = stages.add_parser(name)
        for flag in flags:
            stage.add_argument('--' + flag, required=True)
    a = cli.parse_args()
    try:
        if hasattr(a, 'output'):
            separate_output(a.output, *(v for k, v in vars(a).items() if v is not None and k not in {'output', 'stage', 'cache'}))
        if a.stage == 'pin-source':
            print(pin(unindexed(a.source)))
        elif a.stage == 'plan':
            write_records(a.output, plan(json.loads(Path(a.manifest).read_text()), unindexed(a.source)))
        elif a.stage == 'english':
            write_records(a.output, english(read_records(a.input), read_records(a.edits)))
        elif a.stage == 'compare-google':
            write_records(a.output, compare_google(*(read_records(getattr(a, k))
                                                      for k in ('input', 'live', 'frozen', 'notes'))))
        elif a.stage.startswith('niqqud'):
            final = a.stage == 'niqqud'
            rows, audit = point(read_records(a.input), read_records(a.drafts),
                                unindexed(a.decisions) if final else [], final)
            (write_records if final else write_json)(a.output, rows if final else audit)
        elif a.stage == 'transliterate':
            with tempfile.TemporaryDirectory() as directory:
                result = Path(directory) / 'transliterated.jsonl'
                subprocess.run(['node', str(HERE / 'transliterate_batch.mjs'), '--input', a.input,
                                '--output', str(result), '--cache', a.cache, '--field', 'vocalized_text',
                                '--require-context-review'], check=True)
                rows = read_records(result)
                require(rows, 'Empty transliteration')
                write_records(a.output, rows)
        elif a.stage == 'sheet-rows':
            rows = read_records(a.input)
            require(rows, 'Empty sheet upload')
            write_records(a.output, sheet_rows(rows))
        elif a.stage == 'export-input':
            expected = read_records(a.input)
            actual = read_records(a.readback)
            require(expected and actual == expected, 'Private Sheet readback differs; do not render PDF/EPUB')
            write_records(a.output, actual)
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as exc:
        cli.error(str(exc))


if __name__ == '__main__':
    main()
