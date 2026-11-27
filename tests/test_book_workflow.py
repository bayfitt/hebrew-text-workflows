import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

from book_workflow import digest, pin
from workflow_io import read_records


@pytest.mark.parametrize('google', [False, True])
def test_synthetic_book_cli(tmp_path, google):
    def put(name, obj):
        path = tmp_path / name
        path.write_text(json.dumps(obj, ensure_ascii=False))
        return path

    def run(stage, *, fails=False, **args):
        command = [sys.executable, str(ROOT / 'scripts/book_workflow.py'), stage]
        for key, value in args.items():
            command.extend(('--' + key, str(value)))
        proc = subprocess.run(command, capture_output=True, text=True)
        assert bool(proc.returncode) == fails, proc.stderr
        return proc.stdout

    source_rows = [{'source_ref': 'Synthetic 1:1', 'source_kind': 'typed',
                    'source_text': 'שם שם', 'editorial_english': 'An older draft'}]
    source = put('source.json', source_rows)
    assert run('pin-source', source=source).strip() == pin(source_rows)
    manifest = put('manifest.json', {'book_id': 'synthetic', 'source_edition': 'fixture',
                                    'source_revision': 'r1', 'source_sha256': pin(source_rows),
                                    **({'translation_mode': 'google-comparison'} if google else {})})
    plan = tmp_path / 'plan.jsonl'
    run('plan', manifest=manifest, source=source, output=plan)
    row, = read_records(plan)
    key = {k: row[k] for k in ('id','source_sha256')}
    engine_out = 'There name'
    observed = {**key, 'source_text': row['source_text'], 'value': engine_out}
    edits = put('edits.json', [{**key, 'english': 'There, a name.', 'english_note': 'Retain both senses.'}])
    en = tmp_path / 'en.jsonl'
    run('english', input=plan, edits=edits, output=en)
    assert 'google_translate' not in read_records(en)[0]
    if google:
        live = put('live.json', [{**observed, 'formula': row['google_formula']}])
        frozen = put('frozen.json', [observed])
        notes = put('notes.json', [{**key, 'google_sha256': digest(engine_out),
                                  'english_sha256': digest('There, a name.'),
                                  'google_comparison_note': 'Punctuation changed.',
                                  'english': 'Attempted overwrite'}])
        compared = tmp_path / 'compared.jsonl'
        run('compare-google', input=en, live=live, frozen=live, notes=notes, output=compared, fails=True)
        run('compare-google', input=en, live=live, frozen=frozen, notes=notes, output=compared)
        en = compared
    else:
        assert 'google_formula' not in row
        empty = put('no-readback.json', [])
        run('compare-google', input=en, live=empty, frozen=empty, notes=empty,
            output=tmp_path / 'not-compared.jsonl', fails=True)
    drafts = put('drafts.json', [{**key, 'vocalized_text': 'שָׁם שָׁם', 'niqqud_note': 'Check homographs.',
                                  'english_sha256': digest('There, a name.')}])
    audit = tmp_path / 'audit.json'
    pointing = tmp_path / 'pointing.jsonl'
    run('niqqud-audit', input=en, drafts=drafts, output=audit)
    candidates = json.loads(audit.read_text())
    decisions = put('decisions.json', [{**item, 'sense': sense, 'reason': reason}
                    for item, sense, reason in zip(candidates, ['there', 'name'], ['Locative.', 'Noun.'])])
    run('niqqud', input=en, drafts=drafts, decisions=put('empty.json', []), output=pointing, fails=True)
    run('niqqud', input=en, drafts=drafts, decisions=decisions, output=pointing)
    assert read_records(pointing)[0]['vocalized_text'] == 'שָׁם שֵׁם'
    trans = tmp_path / 'trans.jsonl'
    run('transliterate', input=en, cache=tmp_path/'cache', output=trans, fails=True)
    run('transliterate', input=pointing, cache=tmp_path/'cache', output=trans)
    rows = tmp_path / 'rows.jsonl'
    run('sheet-rows', input=trans, output=rows)
    canonical, = read_records(rows)
    assert canonical['editorial_english'] == 'An older draft'
    assert canonical['google_translate'] == ('There name' if google else '')
    assert canonical['english'] == 'There, a name.'
    assert canonical['contextual_notes'] == ['Locative.', 'Noun.']
    assert canonical['transliteration']
    rendered = tmp_path / 'export.jsonl'
    run('export-input', input=rows, readback=put('drift.json', [{**canonical, 'english': 'drift'}]),
        output=rendered, fails=True)
    assert not rendered.exists()
    run('export-input', input=rows, readback=put('readback.json', [canonical]), output=rendered)
    assert read_records(rendered) == [canonical]
