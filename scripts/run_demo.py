#!/usr/bin/env python3
"""Run independently authored fixtures through the offline reviewed pipeline."""
import argparse
import json
from pathlib import Path
import subprocess

from build_sheets import build, write_template
from apply_readings import apply as apply_readings
from compare_ocr import compare
from review_english_names import apply as apply_english
from workflow_io import digest, read_records, write_json, write_records


ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default=str(ROOT / 'examples/project.json'))
    args = parser.parse_args()
    config_path = Path(args.config).resolve()
    config = json.loads(config_path.read_text())
    def path(key):
        return (config_path.parent / config[key]).resolve()
    out = path('output')
    if out == ROOT or ROOT not in out.parents or out.relative_to(ROOT).parts[0] != 'work':
        raise ValueError('The offline example output belongs under the ignored work directory')
    records = read_records(path('input'))
    secondary = read_records(path('comparison'))
    write_records(out / 'ocr-comparison.jsonl', compare(records, secondary))
    dictionary_hash = digest(path('dictionary').read_bytes())
    dictionary = json.loads(path('dictionary').read_text())
    policy = dictionary['policy_version']
    decisions = [json.loads(line) for line in path('decisions').read_text().splitlines() if line.strip()]
    decisions = [dict(row, reading_policy_version=policy, dictionary_sha256=dictionary_hash) for row in decisions]
    readings = apply_readings(records, decisions, dictionary, dictionary_hash)
    write_records(out / 'readings.jsonl', readings)
    subprocess.run(['node', str(ROOT / 'scripts/transliterate_batch.mjs'),
                    '--input', str(out / 'readings.jsonl'), '--output', str(out / 'transliterated.jsonl'),
                    '--schema', str(path('schema')), '--cache', str(out / 'cache/charles')], check=True)
    transliterated = read_records(out / 'transliterated.jsonl')
    english = [json.loads(line) for line in path('english_decisions').read_text().splitlines() if line.strip()]
    reviewed, archived = apply_english(transliterated, english)
    write_records(out / 'reviewed.jsonl', reviewed)
    write_json(out / 'archived-english-overrides.json', archived)
    metadata = json.loads(path('sheet_metadata').read_text())
    ids = {sheet['properties']['title']: sheet['properties']['sheetId'] for sheet in metadata['sheets']}
    payload = build(reviewed, ids, policy, dictionary_hash)
    write_json(out / 'sheets/layout.json', payload['layout'])
    for index, batch in enumerate(payload['batches']):
        write_json(out / 'sheets/body' / f'{index:04}.json', batch)
    write_template(out / 'sheets/legal-landscape-template.xlsx')
    summary = {'records': len(reviewed), 'policy': policy, 'dictionary_sha256': dictionary_hash,
               'reading_edits': sum(len(row.get('reading_edits', [])) for row in reviewed),
               'english_name_edits': sum(len(row['english_review_edits']) for row in reviewed),
               'source_preserved': all(a['source_text'] == b['source_text'] for a, b in zip(records, reviewed, strict=True)),
               'provider_calls': 0, 'native_writes': 0, 'oversized_rows': payload['oversized_rows']}
    write_json(out / 'summary.json', summary)
    assert summary['source_preserved'] and not summary['oversized_rows']
    print(json.dumps(summary))


if __name__ == '__main__':
    main()
