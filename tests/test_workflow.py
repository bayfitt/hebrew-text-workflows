import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
import xml.etree.ElementTree as ET
import zipfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import apply_readings
import build_sheets
import compare_ocr
import check_public_tree
import prepare_records
import review_english_names
import run_workflow
import vision_records
import workflow_io


def fixture(name):
    return [json.loads(line) for line in (ROOT / 'fixtures' / name).read_text().splitlines() if line.strip()]


class EnglishReviewTests(unittest.TestCase):
    def setUp(self):
        self.records = fixture('records.jsonl')
        self.decisions = fixture('english-name-decisions.jsonl')
        self.records[0]['reading_edits'] = [dict(fixture('reading-decisions.jsonl')[0])]

    def test_name_only_change_preserves_source_and_surrounding_english(self):
        before = copy.deepcopy(self.records)
        reviewed, archive = review_english_names.apply(self.records, self.decisions)
        self.assertEqual(reviewed[0]['english_override'], 'Rambam adds a short explanation.')
        self.assertEqual(self.records, before)
        self.assertEqual(reviewed[0]['source_text'], before[0]['source_text'])
        self.assertEqual(archive, [])

    def test_changed_machine_snapshot_rejected(self):
        self.records[0]['google_translate'] += ' '
        with self.assertRaisesRegex(ValueError, 'snapshot changed'):
            review_english_names.apply(self.records, self.decisions)

    def test_unlinked_name_or_wrong_label_rejected(self):
        self.decisions[0]['source_occurrence_id'] = 'unknown'
        with self.assertRaisesRegex(ValueError, 'source-linked name'):
            review_english_names.apply(self.records, self.decisions)
        self.decisions = fixture('english-name-decisions.jsonl')
        self.decisions[0]['replacement'] = 'Another author'
        with self.assertRaisesRegex(ValueError, 'reviewed name label'):
            review_english_names.apply(self.records, self.decisions)

    def test_existing_override_archived_and_concurrent_change_rejected(self):
        self.records[0]['english_override'] = self.records[0]['google_translate']
        reviewed, archive = review_english_names.apply(self.records, self.decisions)
        self.assertEqual(len(archive), 1)
        live = copy.deepcopy(self.records)
        live[0]['source_row_index'] = 17
        requests = review_english_names.plan_updates(reviewed, live, 3)
        self.assertEqual(requests[0]['updateCells']['start'], {'sheetId': 3, 'rowIndex': 17, 'columnIndex': 10})
        self.assertEqual(requests[0]['updateCells']['fields'], 'userEnteredValue')
        live[0]['english_override'] = 'An intervening edit'
        with self.assertRaisesRegex(ValueError, 'reviewed English changed'):
            review_english_names.plan_updates(reviewed, live, 3)

    def test_multiple_edits_same_passage_and_overlap_rejection(self):
        first = self.records[0]
        first['google_translate'] = 'Maimonides and Maimonides.'
        self.decisions[0]['english_input_sha256'] = workflow_io.digest(first['google_translate'])
        second = dict(self.decisions[0], start_char=15, end_char=25)
        reviewed, _ = review_english_names.apply(self.records, [self.decisions[0], second])
        self.assertEqual(reviewed[0]['english_override'], 'Rambam and Rambam.')
        with self.assertRaisesRegex(ValueError, 'Overlapping'):
            review_english_names.apply(self.records, [self.decisions[0], self.decisions[0]])


class DictionaryValidationTests(unittest.TestCase):
    dictionary = {'policy_version': 'test-v1', 'entries': [
        {'written_form': 'רמב״ם', 'decision': 'retain', 'spoken_reading': 'רַמְבַּ״ם', 'english_label': 'Rambam'},
        {'written_form': 'ט״ז', 'decision': 'retain', 'spoken_reading': 'טַ״ז', 'english_label': 'Taz'},
        {'written_form': 'מהר״ל', 'decision': 'retain', 'spoken_reading': 'מַהַרַ״ל', 'english_label': 'Maharal'},
        {'written_form': 'שו״ע', 'decision': 'expand', 'expansion': 'שולחן ערוך', 'english_label': 'Shulchan Aruch'},
        {'written_form': 'ע״ש', 'decision': 'expand', 'expansion': 'עיין שם'}]}

    def test_dictionary_validates_prefixed_spoken_form(self):
        apply_readings.validate_dictionary_decisions(fixture('reading-decisions.jsonl'), self.dictionary)

    def test_stamped_full_name_proposal_cannot_bypass_dictionary(self):
        decision = dict(fixture('reading-decisions.jsonl')[0], decision='expand',
                        expansion='משה בן מימון', reading_policy_version='test-v1', dictionary_sha256='stamped')
        with self.assertRaisesRegex(ValueError, 'familiar spoken acronym'):
            apply_readings.validate_dictionary_decisions([decision], self.dictionary)

    def test_exterior_punctuation_cannot_bypass_dictionary(self):
        for raw in ['הרמב"ם,', '"הרמב"ם"', '(והרמב״ם)', 'הרמב""ם,']:
            decision = {'raw_token': raw, 'decision': 'expand', 'expansion': 'משה בן מימון'}
            with self.assertRaisesRegex(ValueError, 'familiar spoken acronym'):
                apply_readings.validate_dictionary_decisions([decision], self.dictionary)
        for raw, spoken in [('הרמב"ם,', 'הָרַמְבַּ"ם,'), ('"הרמב"ם"', '"הָרַמְבַּ"ם"')]:
            apply_readings.validate_dictionary_decisions([{'raw_token': raw, 'decision': 'retain',
                'spoken_reading': spoken, 'english_label': 'Rambam'}], self.dictionary)

    def test_title_expansion_and_contextual_alternative_validated(self):
        title = {'raw_token': '(בשו"ע)', 'decision': 'expand', 'expansion': '(בשולחן ערוך)', 'english_label': 'Shulchan Aruch'}
        apply_readings.validate_dictionary_decisions([title], self.dictionary)
        title['expansion'] = 'Some full author name'
        with self.assertRaisesRegex(ValueError, 'Phrase expansion differs'):
            apply_readings.validate_dictionary_decisions([title], self.dictionary)
        alternative = {'raw_token': 'ע"ש', 'decision': 'expand', 'expansion': 'על שם'}
        with self.assertRaisesRegex(ValueError, 'Phrase expansion differs'):
            apply_readings.validate_dictionary_decisions([alternative], self.dictionary)
        alternative.update(contextual_alternative='Naming construction in this sentence.',
                           reason='Naming construction', evidence='Complete reviewed synthetic sentence')
        apply_readings.validate_dictionary_decisions([alternative], self.dictionary)

    def test_wrong_pronunciation_and_name_label_rejected(self):
        decision = dict(fixture('reading-decisions.jsonl')[0], spoken_reading='הָרַמְבוּ"ם')
        with self.assertRaisesRegex(ValueError, 'selected dictionary profile'):
            apply_readings.validate_dictionary_decisions([decision], self.dictionary)
        decision = dict(fixture('reading-decisions.jsonl')[0], english_label='Maimonides')
        with self.assertRaisesRegex(ValueError, 'selected dictionary label'):
            apply_readings.validate_dictionary_decisions([decision], self.dictionary)

    def test_article_dagesh_is_allowed_only_in_first_stem_letter(self):
        for raw, spoken in [('המהר"ל', 'הַמַּהַרַ"ל'), ('במהר״ל', 'בַּמַּהַרַ״ל')]:
            decision = {'raw_token': raw, 'decision': 'retain', 'spoken_reading': spoken, 'english_label': 'Maharal'}
            apply_readings.validate_dictionary_decisions([decision], self.dictionary)
        bad = {'raw_token': 'מהר"ל', 'decision': 'retain', 'spoken_reading': 'מַּהַרַ"ל', 'english_label': 'Maharal'}
        with self.assertRaisesRegex(ValueError, 'selected dictionary profile'):
            apply_readings.validate_dictionary_decisions([bad], self.dictionary)

    def test_number_homograph_and_manual_hold_supported(self):
        number = {'raw_token': 'ט"ז', 'decision': 'expand', 'expansion': 'שישה עשר', 'usage': 'number'}
        apply_readings.validate_dictionary_decisions([number], self.dictionary)
        apply_readings.validate_dictionary_decisions([{'raw_token': 'ט"ז', 'decision': 'manual'}], self.dictionary)
        bad = {'raw_token': 'רמב"ם', 'decision': 'expand', 'expansion': 'משה בן מימון', 'usage': 'reference'}
        with self.assertRaisesRegex(ValueError, 'reviewed number phrase'):
            apply_readings.validate_dictionary_decisions([bad], self.dictionary)


class SourceAndLayoutTests(unittest.TestCase):
    def test_row_height_converts_point_fonts_to_pixels(self):
        text = '\n'.join(['A short example line.'] * 5)
        self.assertGreaterEqual(build_sheets.height([text], 12), 120)

    def test_public_text_check_normalizes_niqqud_and_unicode_escapes(self):
        self.assertEqual(check_public_tree.hebrew_words('שָׁלוֹם לדוגמה'), ['שלום', 'לדוגמה'])
        encoded = json.dumps('שָׁלוֹם לדוגמה', ensure_ascii=True)
        self.assertEqual(check_public_tree.hebrew_words(encoded), ['שלום', 'לדוגמה'])

    def test_long_passages_split_losslessly_and_repeat_stably(self):
        source = 'שָׁלוֹם לדוגמה ' * 80
        records = [{'id': 'long-example', 'source_text': source, 'vocalized_text': source}]
        prepared = prepare_records.prepare(records, 100)
        self.assertEqual(''.join(row['source_text'] for row in prepared), source)
        self.assertEqual(prepared, prepare_records.prepare(records, 100))
        self.assertTrue(all(row['parent_source_sha256'] == workflow_io.digest(source) for row in prepared))
        self.assertTrue(all('vocalized_text' not in row for row in prepared))

    def test_ocr_comparison_preserves_provider_text_and_references(self):
        a, b = fixture('records.jsonl'), fixture('secondary-ocr.jsonl')
        original = copy.deepcopy(a)
        compared = compare_ocr.compare(a, b)
        self.assertEqual(a, original)
        self.assertEqual(compared[0]['primary_text'], a[0]['source_text'])
        self.assertEqual(compared[0]['primary_ids'], ['example-name'])
        self.assertTrue(compared[0]['differences'])
        self.assertEqual(compare_ocr.normalized('רַמְבַּ״ם'), compare_ocr.normalized('רמב"ם'))

    def test_vision_cache_checks_exact_source(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '001.json'
            path.write_text(json.dumps({'status': 'success', 'source_sha256': 'source-a',
                                       'response': {'fullTextAnnotation': {'text': ''}}}))
            with self.assertRaisesRegex(ValueError, 'another source'):
                vision_records.records_from_cache(directory, 'source-b', [1])

    def test_page_selection_follows_supplied_document(self):
        self.assertEqual(workflow_io.parse_pages('all', 3), [1, 2, 3])
        self.assertEqual(workflow_io.parse_pages('2-3,1', 3), [1, 2, 3])
        with self.assertRaises(ValueError):
            workflow_io.parse_pages('4', 3)

    def test_production_stage_uses_project_page_and_layout_settings(self):
        config = json.loads((ROOT / 'examples/document.json').read_text())
        config['pdf'].update(pages='2-4', layout='two_up')
        command = run_workflow.stage_command(config, ROOT / 'examples', 'local-ocr')
        self.assertEqual(command[command.index('--pages') + 1], '2-4')
        self.assertEqual(command[command.index('--layout') + 1], 'two_up')
        self.assertTrue(command[command.index('--pdf') + 1].endswith('/inputs/document.pdf'))

    def test_sheet_payload_keeps_translation_formulas_and_policy_guards(self):
        records = fixture('records.jsonl')
        for record in records:
            record.update(reading_policy_version='test', dictionary_sha256='hash')
        ids = dict(zip(build_sheets.TITLES, [1, 2, 3, 4]))
        result = build_sheets.build(records, ids, 'test', 'hash')
        source = result['batches'][0]['requests'][0]['updateCells']['rows'][0]['values']
        self.assertIn('GOOGLETRANSLATE(G2,"he","en")', source[9]['userEnteredValue']['formulaValue'])
        self.assertEqual(source[11]['userEnteredValue']['formulaValue'], '=IF(K2<>"",K2,J2)')
        guard = result['batches'][0]['requests'][2]['updateCells']['rows'][0]['values'][2]['userEnteredValue']['formulaValue']
        self.assertIn('Schema!B1', guard)
        self.assertIn('Schema!B2', guard)
        self.assertEqual(result['print_profile']['visible_columns'], 3)
        self.assertFalse(result['oversized_rows'])
        directions = [request['repeatCell'] for request in result['layout']['requests']
                      if 'repeatCell' in request and
                      'textDirection' in request['repeatCell']['cell'].get('userEnteredFormat', {})]
        self.assertTrue(any(item['range'] == {'sheetId': 1, 'startColumnIndex': 0, 'endColumnIndex': 1}
                            and item['cell']['userEnteredFormat']['textDirection'] == 'RIGHT_TO_LEFT'
                            for item in directions))
        self.assertTrue(any(item['range'] == {'sheetId': 2, 'startColumnIndex': 3, 'endColumnIndex': 4}
                            and item['cell']['userEnteredFormat']['horizontalAlignment'] == 'LEFT'
                            for item in directions))

    def test_blank_template_is_legal_landscape_with_hidden_literal_column(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'template.xlsx'
            build_sheets.write_template(path)
            ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
            with zipfile.ZipFile(path) as archive:
                for number in [1, 2]:
                    root = ET.fromstring(archive.read(f'xl/worksheets/sheet{number}.xml'))
                    setup = root.find('s:pageSetup', ns)
                    self.assertEqual(setup.attrib['paperSize'], '5')
                    self.assertEqual(setup.attrib['orientation'], 'landscape')
                root = ET.fromstring(archive.read('xl/worksheets/sheet2.xml'))
                self.assertEqual(root.find('s:cols/s:col', ns).attrib['hidden'], '1')


class ProviderRetryTests(unittest.TestCase):
    def test_rate_limit_retry_then_cached_result(self):
        spec = importlib.util.spec_from_file_location('vocalizer', ROOT / 'scripts/vocalize_batch.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as directory:
            client = module.NakdanClient(SimpleNamespace(cache=directory, genre='rabbinic',
                endpoint='https://example.invalid/api', retries=2, delay=0, timeout=1))
            response = unittest.mock.MagicMock()
            response.read.return_value = b'{"data": []}'
            response.__enter__.return_value = response
            error = HTTPError('https://example.invalid/api', 429, 'rate limit', {}, None)
            with patch.object(module, 'urlopen', side_effect=[error, response]) as request, patch.object(module.time, 'sleep'):
                first, key = client.get('שלום')
                second, same_key = client.get('שלום')
            self.assertEqual(first, second)
            self.assertEqual(key, same_key)
            self.assertEqual(request.call_count, 2)
            self.assertEqual(client.cache_hits, 1)


if __name__ == '__main__':
    unittest.main()
