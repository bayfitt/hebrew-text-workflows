#!/usr/bin/env python3
"""Apply reviewed, source-linked English name edits against exact snapshots."""
import argparse
from collections import defaultdict
from pathlib import Path

from workflow_io import digest, read_records, separate_output, write_json, write_records


def english_base(record):
    return record.get('english_override') or record.get('google_translate') or record.get('english_text', '')


def apply(records, decisions):
    by_id = {record['id']: record for record in records}
    if len(by_id) != len(records):
        raise ValueError('Duplicate record id')
    grouped = defaultdict(list)
    for decision in decisions:
        record = by_id.get(decision['id'])
        if record is None:
            raise ValueError('Unknown English review record')
        text = english_base(record)
        if decision['source_passage_sha256'] != digest(record['source_text']):
            raise ValueError('English review source changed')
        if decision['english_input_sha256'] != digest(text):
            raise ValueError('English snapshot changed')
        start, end = decision['start_char'], decision['end_char']
        if not 0 <= start < end <= len(text) or text[start:end] != decision['raw_text']:
            raise ValueError('English review span changed')
        source_decisions = {entry['occurrence_id']: entry for entry in record.get('reading_edits', [])}
        source_decision = source_decisions.get(decision['source_occurrence_id'])
        if source_decision is None or not source_decision.get('english_label'):
            raise ValueError('English edit requires an accepted source-linked name')
        if decision['replacement'] != source_decision['english_label']:
            raise ValueError('English replacement differs from the reviewed name label')
        if not decision.get('reason'):
            raise ValueError('English review needs a contextual reason')
        grouped[record['id']].append(decision)

    output, archives = [], []
    for original in records:
        record = dict(original)
        before = english_base(original)
        edits = sorted(grouped[record['id']], key=lambda entry: entry['start_char'])
        previous_end = 0
        for edit in edits:
            if edit['start_char'] < previous_end:
                raise ValueError('Overlapping English name edits')
            previous_end = edit['end_char']
        after = before
        for edit in reversed(edits):
            after = after[:edit['start_char']] + edit['replacement'] + after[edit['end_char']:]
        record['english_review_edits'] = edits
        if edits:
            record.update(english_input_sha256=digest(before),
                          english_override_before=original.get('english_override', ''),
                          google_translate_before=original.get('google_translate', ''),
                          english_override=after)
            if original.get('english_override') and after != original['english_override']:
                archives.append({'id': record['id'], 'source_passage_sha256': digest(record['source_text']),
                                 'previous_english_override': original['english_override'],
                                 'replacement_english_override': after})
        output.append(record)
    return output, archives


def plan_updates(reviewed, live, source_sheet_id):
    current = {record['id']: record for record in live}
    requests = []
    for index, record in enumerate(reviewed):
        if not record.get('english_review_edits'):
            continue
        snapshot = current[record['id']]
        if snapshot['source_text'] != record['source_text']:
            raise ValueError('Live source changed before English write')
        if snapshot.get('english_override', '') != record['english_override_before']:
            raise ValueError('Live reviewed English changed before write')
        if not record['english_override_before'] and snapshot.get('google_translate', '') != record['google_translate_before']:
            raise ValueError('Live machine English changed before write')
        row_index = snapshot.get('source_row_index', index + 1)
        requests.append({'updateCells': {
            'start': {'sheetId': source_sheet_id, 'rowIndex': row_index, 'columnIndex': 10},
            'rows': [{'values': [{'userEnteredValue': {'stringValue': record['english_override']}}]}],
            'fields': 'userEnteredValue'}})
    return requests


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True)
    parser.add_argument('--decisions', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--archive', required=True)
    parser.add_argument('--live')
    parser.add_argument('--source-sheet-id', type=int)
    parser.add_argument('--payload')
    args = parser.parse_args()
    separate_output(args.output, args.input, args.decisions)
    separate_output(args.archive, args.input, args.decisions, args.output)
    # Multiple decisions can belong to the same passage.
    import json
    decisions = [json.loads(line) for line in Path(args.decisions).read_text().splitlines() if line.strip()]
    output, archive = apply(read_records(args.input), decisions)
    if args.payload:
        if not args.live or args.source_sheet_id is None:
            parser.error('--payload requires --live and --source-sheet-id')
        requests = plan_updates(output, read_records(args.live), args.source_sheet_id)
        write_json(args.payload, {'requests': requests})
    write_records(args.output, output)
    write_json(args.archive, archive)
    print(json.dumps({'reviewed_records': sum(bool(row['english_review_edits']) for row in output),
                      'archived_overrides': len(archive)}))


if __name__ == '__main__':
    main()
