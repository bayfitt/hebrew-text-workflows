#!/usr/bin/env python3
"""Compare OCR variants while preserving each provider's literal text."""
import argparse
from collections import defaultdict
import difflib
import unicodedata

from workflow_io import digest, read_records, separate_output, write_records


QUOTE_MAP = str.maketrans({'״': '"', '“': '"', '”': '"', '׳': "'", '’': "'", '‘': "'"})


def normalized(text):
    return ''.join(char for char in unicodedata.normalize('NFC', text).translate(QUOTE_MAP)
                   if not (0x591 <= ord(char) <= 0x5C7 and unicodedata.category(char).startswith('M')))


def groups(records):
    output = defaultdict(list)
    for record in records:
        source = record.get('source', {})
        page = source.get('pdf_page', record.get('pdf_page'))
        key = (page, source.get('side', record.get('side', 'single'))) if page is not None else (record['id'], '')
        output[key].append(record)
    return output


def compare(primary, secondary):
    left, right = groups(primary), groups(secondary)
    output = []
    for index, key in enumerate(dict.fromkeys([*left, *right]), 1):
        a = '\n'.join(row.get('source_text', row.get('text', '')) for row in left[key])
        b = '\n'.join(row.get('source_text', row.get('text', '')) for row in right[key])
        changes = [{'operation': op, 'primary_span': [i, j], 'secondary_span': [k, l],
                    'primary_text': a[i:j], 'secondary_text': b[k:l]}
                   for op, i, j, k, l in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes()
                   if op != 'equal']
        output.append({'id': f'comparison-{index:06}', 'source_group': list(key),
                       'primary_ids': [row['id'] for row in left[key]],
                       'secondary_ids': [row['id'] for row in right[key]],
                       'primary_text': a, 'secondary_text': b,
                       'primary_sha256': digest(a), 'secondary_sha256': digest(b),
                       'normalized_equal': normalized(a) == normalized(b),
                       'differences': changes,
                       'review_status': 'source image review required' if changes else 'OCR engines agree'})
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--primary', required=True)
    parser.add_argument('--secondary', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    separate_output(args.output, args.primary, args.secondary)
    output = compare(read_records(args.primary), read_records(args.secondary))
    write_records(args.output, output)
    print(f'Compared {len(output)} page or record groups')


if __name__ == '__main__':
    main()
