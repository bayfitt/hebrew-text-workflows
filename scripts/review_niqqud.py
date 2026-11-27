#!/usr/bin/env python3
"""Review contextual readings of שם before downstream transliteration."""
import argparse
import json
import re
from pathlib import Path

from workflow_io import digest, read_records, separate_output, write_json, write_records

POLICY = 'contextual-shm-v1'
HEBREW = re.compile(r'(?:[\u05d0-\u05ea][\u0591-\u05bd\u05bf\u05c1\u05c2\u05c4\u05c5\u05c7]*)+')
MARKS = re.compile(r'[\u0591-\u05bd\u05bf\u05c1\u05c2\u05c4\u05c5\u05c7]')
READINGS = {'there': ('\u05c1', '\u05b8'), 'name': ('\u05c1', '\u05b5'),
            'set': ('\u05c2', '\u05b8')}
EDITABLE = set('\u05b0\u05b1\u05b2\u05b3\u05b4\u05b5\u05b6\u05b7\u05b8\u05b9\u05ba\u05bb\u05c1\u05c2\u05c7')
VOWELS = EDITABLE - set('\u05c1\u05c2')
COMMON_PREFIX = re.compile(r'(?:ו?ש?[בכלמה]?)שם\Z')


def plain(text):
    return MARKS.sub('', text)


def candidates(text):
    return [m for m in HEBREW.finditer(text) if COMMON_PREFIX.fullmatch(plain(m.group()))]


def split_shin(token):
    prefix, tail = token.rsplit('ש', 1)
    marks, mem = tail.split('ם', 1)
    return prefix, marks, mem


def set_reading(token, sense, pinned):
    prefix, old, mem = split_shin(token)
    dot, vowel = READINGS[sense]
    source_marks = split_shin(pinned)[1]
    if any(mark in EDITABLE and mark not in (dot, vowel) for mark in source_marks):
        raise ValueError('Decision would change original input pointing; verify the source edition')
    # Keep relative order of all surviving code points. Do not NFC/NFD the text.
    desired = [vowel, dot]
    for mark in desired[:]:
        if mark in old:
            desired.remove(mark)
    kept = set()
    parts = []
    for mark in old:
        if mark not in EDITABLE:
            parts.append(mark)
        elif mark in (dot, vowel) and mark not in kept:
            parts.append(mark)
            kept.add(mark)
        elif mark in VOWELS and vowel in desired:
            parts.append(vowel)
            desired.remove(vowel)
        elif mark in '\u05c1\u05c2' and dot in desired:
            parts.append(dot)
            desired.remove(dot)
    # Match conventional combining order for entirely new marks.
    for mark in desired:
        if mark == vowel:
            pos = next((i for i, present in enumerate(parts) if present in '\u05c1\u05c2'), len(parts))
            parts.insert(pos, mark)
        else:
            parts.append(mark)
    return prefix + 'ש' + ''.join(parts) + 'ם' + mem


def review(records, decisions, source_field, require_resolved=False):
    indexed = {}
    for d in decisions:
        key = (d['id'], d['occurrence'])
        if key in indexed:
            raise ValueError(f'Duplicate decision: {key}')
        indexed[key] = d
    output, report = [], []
    for row in records:
        text, source = row['vocalized_text'], row[source_field]
        original, found = candidates(source), candidates(text)
        if (original or found) and plain(text) != plain(source):
            raise ValueError(f"Source and draft consonants differ: {row['id']}")
        changes = []
        unresolved = 0
        for i, match in enumerate(found, 1):
            token = match.group()
            item = {'id': row['id'], 'occurrence': i, 'token': token, 'draft_sha256': digest(text),
                    'source_sha256': digest(source)}
            d = indexed.pop((row['id'], i), None)
            if d is None or d.get('sense') == 'uncertain':
                unresolved += 1
            if d is not None:
                if any(d.get(k) != v for k, v in item.items()):
                    raise ValueError(f'Stale or mismatched occurrence: {item}')
                if d.get('sense') not in {*READINGS, 'uncertain'} or not isinstance(d.get('reason'), str) or not d['reason'].strip():
                    raise ValueError('Provide a documented contextual decision or mark uncertain')
                if d['sense'] != 'uncertain':
                    changes.append((match.start(), match.end(), set_reading(token, d['sense'], original[i-1].group())))
            source_match = original[i-1]
            # Dicta reports offsets in its source (unvocalized) coordinate space.
            provider_warnings = [f['code'] for f in row.get('vocalization_flags', [])
                                 if f.get('code') == 'provider_low_confidence'
                                 and f.get('offset') == source_match.start()]
            report.append({**item, 'span': [match.start(), match.end()], 'context': source,
                           'source_span': [source_match.start(), source_match.end()],
                           'provider_warnings': provider_warnings,
                           'sense': d['sense'] if d else 'unreviewed',
                           'reason': d['reason'] if d else None})
        checked = text
        for start, end, replacement in reversed(changes):
            checked = checked[:start] + replacement + checked[end:]
        new = {**row, 'vocalized_text': checked}
        if checked != text and 'transliteration_input' in new:
            reading = row['transliteration_input']
            if reading == text:
                new['transliteration_input'] = checked
            else:
                # A separate phonetic layer may differ (abbreviations, etc.). Without
                # an aligned span map, never modify that layer based on offsets in this one.
                raise ValueError(f"Review divergent transliteration input separately: {row['id']}")
        new['niqqud_context_review'] = {'policy': POLICY, 'reviewed_sha256': digest(checked),
                                         'candidate_count': len(found), 'unresolved': unresolved}
        output.append(new)
    if indexed:
        raise ValueError(f'Unused decisions: {list(indexed)}')
    if require_resolved and any(row['niqqud_context_review']['unresolved'] for row in output):
        raise ValueError('Unresolved contextual niqqud; review queue before continuing')
    return output, report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input', required=True)
    ap.add_argument('--source-field', default='source_text')
    ap.add_argument('--decisions', help='JSONL occurrence decisions using the audit report identity fields')
    ap.add_argument('--report', required=True)
    ap.add_argument('--output', help='Separate reviewed JSONL; omit to create a report only')
    ap.add_argument('--require-resolved', action='store_true')
    args = ap.parse_args()
    paths = [args.input, args.decisions] if args.decisions else [args.input]
    separate_output(args.report, *paths)
    if args.output:
        separate_output(args.output, *paths, args.report)
    decisions = [json.loads(line) for line in Path(args.decisions).read_text().splitlines() if line.strip()] if args.decisions else []
    rows, audit = review(read_records(args.input), decisions, args.source_field)
    write_json(args.report, audit)
    if args.require_resolved and any(row['niqqud_context_review']['unresolved'] for row in rows):
        ap.error('Unresolved contextual niqqud; review the report before continuing')
    if args.output:
        write_records(args.output, rows)


if __name__ == '__main__':
    main()
