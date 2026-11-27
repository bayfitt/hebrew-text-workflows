#!/usr/bin/env python3
"""Run one explicit document workflow stage from a local project configuration."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

from workflow_io import digest


ROOT = Path(__file__).resolve().parents[1]
STAGES = ['local-ocr', 'google-ocr', 'compare', 'prepare', 'vocalize', 'niqqud-review', 'readings',
          'transliterate', 'template', 'sheets', 'english']


def stage_command(config, config_directory, stage):
    def path(key):
        return str((config_directory / config[key]).resolve())
    output = Path(path('output'))
    pdf = config.get('pdf', {})
    python = sys.executable
    script = lambda name: str(ROOT / 'scripts' / name)
    commands = {
        'compare': [python, script('compare_ocr.py'), '--primary', str(output / 'local-ocr/records.jsonl'),
                    '--secondary', str(output / 'google-ocr/records.jsonl'), '--output', str(output / 'ocr-comparison.jsonl')],
        'prepare': [python, script('prepare_records.py'), '--input', path('canonical_records'),
                    '--output', str(output / 'passages.jsonl'), '--max-source-chars', str(config.get('max_source_chars', 350))],
        'vocalize': [python, script('vocalize_batch.py'), '--input', str(output / 'passages.jsonl'),
                     '--field', 'source_text', '--output', str(output / 'vocalized.jsonl'), '--cache', str(output / 'cache/nakdan')],
        'readings': [python, script('apply_readings.py'), '--records', str(output / 'vocalized.jsonl'),
                     '--decisions', path('reading_decisions'), '--dictionary', path('dictionary'),
                     '--output', str(output / 'readings.jsonl')],
        'transliterate': ['node', script('transliterate_batch.mjs'), '--input', str(output / 'readings.jsonl'),
                          '--output', str(output / 'transliterated.jsonl'), '--schema', path('schema'),
                          '--cache', str(output / 'cache/charles')],
        'template': [python, script('build_sheets.py'), '--out', str(output / 'sheets'), '--template-only'],
        'english': [python, script('review_english_names.py'), '--input', path('english_snapshot'),
                     '--decisions', path('english_name_decisions'), '--output', str(output / 'english-reviewed.jsonl'),
                     '--archive', str(output / 'english-overrides-archive.json')],
    }
    if stage == 'niqqud-review' or (stage == 'readings' and config.get('niqqud_context_decisions')):
        command = [python, script('review_niqqud.py'), '--input', str(output / 'vocalized.jsonl'),
                   '--report', str(output / 'niqqud-context-report.json')]
        if stage == 'niqqud-review':
            return command
        reviewed = str(output / 'vocalized-context-reviewed.jsonl')
        command.extend(['--decisions', path('niqqud_context_decisions'), '--output', reviewed,
                        '--require-resolved'])
        reading_command = commands['readings']
        reading_command[reading_command.index('--records') + 1] = reviewed
        # Dispatcher runs the guard before the consumer, eliminating stale cached review reuse.
        return [command, reading_command]
    if stage in ['local-ocr', 'google-ocr']:
        command = [python, script('ocr_pdf.py' if stage == 'local-ocr' else 'google_vision_ocr.py'),
                   '--pdf', path('input_pdf'), '--pages', pdf.get('pages', 'all'),
                   '--layout', pdf.get('layout', 'single'), '--out', str(output / stage)]
        if stage == 'local-ocr':
            command.extend(['--language', pdf.get('language', 'heb')])
        return command
    if stage == 'sheets':
        dictionary_bytes = Path(path('dictionary')).read_bytes()
        dictionary = json.loads(dictionary_bytes)
        return [python, script('build_sheets.py'), '--input', str(output / 'transliterated.jsonl'),
                '--metadata', path('sheet_metadata'), '--out', str(output / 'sheets'),
                '--policy-version', dictionary['policy_version'], '--dictionary-hash', digest(dictionary_bytes)]
    return commands[stage]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--stage', required=True, choices=STAGES)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    config_path = Path(args.config).resolve()
    command = stage_command(json.loads(config_path.read_text()), config_path.parent, args.stage)
    if args.dry_run:
        print(json.dumps({'stage': args.stage, 'command': command}))
        return
    for step in command if isinstance(command[0], list) else [command]:
        subprocess.run(step, check=True)


if __name__ == '__main__':
    main()
