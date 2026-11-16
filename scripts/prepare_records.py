#!/usr/bin/env python3
"""Split long source records losslessly into stable printable passage units."""
import argparse
import re
import unicodedata

from workflow_io import digest, read_records, separate_output, write_records


def split_text(text, limit):
    parts = []
    start = 0
    while start < len(text):
        end = min(start + limit, len(text))
        if end < len(text):
            boundaries = list(re.finditer(r'\s+', text[start:end]))
            if boundaries:
                end = start + boundaries[-1].end()
            while end < len(text) and unicodedata.combining(text[end]):
                end += 1
        parts.append((start, end, text[start:end]))
        start = end
    return parts or [(0, 0, '')]


def prepare(records, limit=350):
    if limit < 20:
        raise ValueError('Passage character limit must be at least 20')
    output = []
    for record in records:
        source = record.get('source_text', record.get('text'))
        if not isinstance(source, str):
            raise ValueError('Expected source_text or text')
        parts = split_text(source, limit) if not record.get('reading_held') else [(0, len(source), source)]
        for index, (start, end, part) in enumerate(parts, 1):
            row = dict(record, source_text=part)
            if len(parts) > 1:
                row.update(id=f"{record['id']}:part-{index:03}", parent_id=record['id'],
                           parent_source_sha256=digest(source), parent_source_span=[start, end],
                           part_index=index, part_count=len(parts))
                # Derived readings belong to their original complete source.
                for field in ['vocalized_text', 'transliteration_input', 'transliteration',
                              'expanded_source_text', 'expanded_vocalized_text']:
                    row.pop(field, None)
            output.append(row)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--max-source-chars', type=int, default=350)
    args = parser.parse_args()
    separate_output(args.output, args.input)
    output = prepare(read_records(args.input), args.max_source_chars)
    write_records(args.output, output)
    print(f'Prepared {len(output)} passage units')


if __name__ == '__main__':
    main()
