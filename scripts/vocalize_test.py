#!/usr/bin/env python3
"""Meaningful invariants; fixture niqqud is test data, never a fallback."""
import importlib.util
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location('vocalize_batch', Path(__file__).with_name('vocalize_batch.py'))
v = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(v)


class SourcePreservationTests(unittest.TestCase):
    def test_existing_marks_win_over_conflicting_prediction(self):
        source = 'שָׁלוֹם'
        output, flags, added = v.overlay_marks(source, 'שְׂלוּם')
        self.assertEqual(output, source)
        self.assertEqual(added, 0)
        self.assertEqual({x['code'] for x in flags}, {'existing_mark_conflict'})

    def test_adds_marks_without_changing_source_punctuation(self):
        source = 'הרמב״ם'
        output, _, _ = v.overlay_marks(source, 'הָ|רַמְבַּ"ם')
        self.assertEqual(output, 'הָרַמְבַּ״ם')
        self.assertEqual(v.strip_marks(output), source)

    def test_mater_metadata_is_not_added_as_meteg(self):
        output, _, _ = v.overlay_marks('פיקוח', 'פִּיֽקּוּחַ')
        self.assertEqual(output, 'פִּיקּוּחַ')
        self.assertNotIn('\u05bd', output)
        existing, _, _ = v.overlay_marks('פִּיֽקוח', 'פִּיקּוּחַ')
        self.assertIn('\u05bd', existing)

    def test_consonant_difference_has_no_fabricated_fallback(self):
        output, flags, added = v.overlay_marks('מלכים', 'מְלָכוֹת')
        self.assertEqual(output, 'מלכים')
        self.assertEqual(added, 0)
        self.assertTrue(flags[0]['blocking'])

    def test_cached_hayav_annotation_has_separate_classical_reading(self):
        # Exact chosen word option from the retained Nakdan rabbinic response.
        source, option = 'חייב', 'חַיָּיֽב'
        displayed, _, _ = v.overlay_marks(source, option)
        reading, changes, flags = v.phonetic_reading(source, displayed, option)
        self.assertEqual(displayed, 'חַיָּיב')
        self.assertEqual(v.strip_marks(displayed), source)
        self.assertEqual(reading, 'חַיָּב')
        self.assertEqual([(x['source_offset'], x['source_letter']) for x in changes], [(2, 'י')])
        self.assertEqual(changes[0]['provider_option'], option)
        self.assertEqual(flags, [])

    def test_no_silent_letter_is_inferred_without_provider_metadata(self):
        displayed = 'חַיָּיב'
        reading, changes, flags = v.phonetic_reading('חייב', displayed, displayed)
        self.assertEqual(reading, displayed)
        self.assertEqual(changes, [])
        self.assertEqual(flags, [])

    def test_original_meteg_is_never_treated_as_new_mater_metadata(self):
        source = 'פִּיֽקוח'
        displayed, _, _ = v.overlay_marks(source, 'פִּיֽקּוּחַ')
        reading, changes, flags = v.phonetic_reading(source, displayed, 'פִּיֽקּוּחַ')
        self.assertEqual(reading, displayed)
        self.assertEqual(changes, [])
        self.assertIn('source_meteg_not_interpreted_as_mater', {f['code'] for f in flags})

    def test_metadata_conflicting_with_original_marks_does_not_delete(self):
        source = 'חייְב'
        displayed, _, _ = v.overlay_marks(source, 'חַיָּיֽב')
        reading, changes, flags = v.phonetic_reading(source, displayed, 'חַיָּיֽב')
        self.assertEqual(reading, displayed)
        self.assertEqual(changes, [])
        self.assertTrue(flags[0]['blocking'])

    def test_phonetic_normalization_offsets_survive_record_slicing(self):
        source = 'שלום\n\nחייב לשלם'
        response = {'data': [
            {'str': 'שלום', 'nakdan': {'options': [{'w': 'שָׁלוֹם'}]}},
            {'str': '\n\n', 'sep': True, 'nakdan': {}},
            {'str': 'חייב', 'nakdan': {'options': [{'w': 'חַיָּיֽב'}]}},
            {'str': ' ', 'sep': True, 'nakdan': {}},
            {'str': 'לשלם', 'nakdan': {'options': [{'w': 'לְשַׁלֵּם'}]}}]}
        tokens = v.render_response(source, response)
        second = v.extract_span(tokens, 6, len(source), source[6:])
        self.assertEqual(second['text'], 'חַיָּיב לְשַׁלֵּם')
        self.assertEqual(second['transliteration_input'], 'חַיָּב לְשַׁלֵּם')
        self.assertEqual(second['phonetic_normalization'][0]['source_offset'], 2)

    def test_wrong_provider_tokenization_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'exact submitted text'):
            v.render_response('שלום  עולם', {'data': [{'str': 'שלום עולם'}]})

    def test_record_boundaries_and_whitespace_are_exact(self):
        source = '  אמר\n\nשלום!\n'
        response = {'data': [
            {'str': '  ', 'sep': True, 'nakdan': {}},
            {'str': 'אמר', 'nakdan': {'options': [{'w': 'אָמַר'}], 'fconfident': True}},
            {'str': '\n\n', 'sep': True, 'nakdan': {}},
            {'str': 'שלום', 'nakdan': {'options': [{'w': 'שָׁלוֹם'}], 'fconfident': True}},
            {'str': '!\n', 'sep': True, 'nakdan': {}}]}
        tokens = v.render_response(source, response)
        a = v.extract_span(tokens, 0, 5, source[:5])
        b = v.extract_span(tokens, 7, len(source), source[7:])
        self.assertEqual(a['text'], '  אָמַר')
        self.assertEqual(b['text'], 'שָׁלוֹם!\n')
        self.assertEqual(v.strip_marks(a['text']) + '\n\n' + v.strip_marks(b['text']), source)

    def test_pointed_name_and_acronym_are_flagged(self):
        source = 'אָמַר רַבִּי עקיבא על הרמב״ם'
        tokens = [{'start': 0, 'end': len(source), 'source': source,
                   'output': source, 'added': 0, 'flags': []}]
        out = v.extract_span(tokens, 0, len(source), source)
        codes = {x['code'] for x in out['flags']}
        self.assertIn('possible_proper_name', codes)
        self.assertIn('acronym_or_abbreviation_reading', codes)

    def test_splitting_and_grouping_never_changes_a_record(self):
        source = 'אמר ' * 70 + '\nשלום'
        parts = v.split_source(source, 100)
        self.assertEqual(''.join(text for _, text in parts), source)
        records = [{'id': 'a', 'text': source}, {'id': 'b', 'text': ' שלום '}]
        recovered = {0: '', 1: ''}
        for group in v.request_groups(records, 'text', 100):
            submitted = '\n\n'.join(part['text'] for part in group)
            self.assertLessEqual(len(submitted), 100)
            for part in group:
                self.assertEqual(submitted[part['start']:part['end']], part['text'])
                recovered[part['record_index']] += part['text']
        self.assertEqual(recovered, {0: source, 1: ' שלום '})


if __name__ == '__main__':
    unittest.main()
