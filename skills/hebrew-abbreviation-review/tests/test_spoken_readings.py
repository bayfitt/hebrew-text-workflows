#!/usr/bin/env python3
"""Regression cases use independently authored short sentences."""
import importlib.util
from pathlib import Path
import unittest


PATH = Path(__file__).resolve().parents[1] / 'scripts' / 'apply_expansions.py'
SPEC = importlib.util.spec_from_file_location('spoken_readings', PATH)
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)
POLICY = 'spoken-usage-v1'
DICTIONARY = 'a' * 64


def decision(record, token, **changes):
    start = record['source_text'].index(token)
    item = {
        'occurrence_id': 'example-1',
        'id': record['id'],
        'source_passage_sha256': m.digest(record['source_text']),
        'start_char': start,
        'end_char': start + len(token),
        'raw_token': token,
        'decision': 'retain',
        'expansion': None,
        'reason': 'The sentence uses the familiar spoken name.',
        'evidence': 'Context reviewed for this independently authored example.',
        'reading_policy_version': POLICY,
        'dictionary_sha256': DICTIONARY,
    }
    item.update(changes)
    return item


def apply(record, decisions):
    return m.apply([record], decisions, policy_version=POLICY, dictionary_sha256=DICTIONARY)[0]


class SpokenReadings(unittest.TestCase):
    def test_retained_name_gets_vowels_and_clean_pronunciation(self):
        record = {'id': 'example', 'source_text': 'הרמב"ם', 'vocalized_text': 'הרמב"ם'}
        item = decision(record, 'הרמב"ם', spoken_reading='הָרַמְבַּ"ם', english_label='Rambam')
        out = apply(record, [item])
        self.assertEqual(out['source_text'], record['source_text'])
        self.assertEqual(out['vocalized_text'], record['vocalized_text'])
        self.assertEqual(out['expanded_source_text'], record['source_text'])
        self.assertEqual(out['expanded_vocalized_text'], 'הָרַמְבַּ"ם')
        self.assertEqual(out['transliteration_input'], 'הָרַמְבַּם')
        self.assertEqual(out['expansion_edits'], [])
        self.assertEqual(out['reading_edits'][0]['english_label'], 'Rambam')
        self.assertEqual(out['reading_normalizations'][0]['source_offset'], 4)

    def test_ordinary_outer_quotes_survive(self):
        record = {'id': 'example', 'source_text': '📚 "רמב״ם" ואחריו רש״י.',
                  'vocalized_text': '📚 "רמב״ם" וְאַחֲרָיו רש״י.'}
        first = decision(record, 'רמב״ם', spoken_reading='רַמְבַּ״ם')
        second = decision(record, 'רש״י', occurrence_id='example-2', spoken_reading='רַשִׁ״י')
        out = apply(record, [second, first])
        self.assertEqual(out['expanded_vocalized_text'], '📚 "רַמְבַּ״ם" וְאַחֲרָיו רַשִׁ״י.')
        self.assertEqual(out['transliteration_input'], '📚 "רַמְבַּם" וְאַחֲרָיו רַשִׁי.')
        self.assertEqual(len(out['reading_normalizations']), 2)

    def test_outer_quotes_inside_accepted_span_survive(self):
        record = {'id': 'example', 'source_text': '"רמב"ם"', 'vocalized_text': '"רמב"ם"'}
        item = decision(record, '"רמב"ם"', spoken_reading='"רַמְבַּ"ם"')
        out = apply(record, [item])
        self.assertEqual(out['transliteration_input'], '"רַמְבַּם"')
        self.assertEqual(len(out['reading_normalizations']), 1)
        self.assertEqual(out['reading_normalizations'][0]['source_offset'], 4)

    def test_prefixed_exterior_hebrew_quotes_and_comma_survive(self):
        record = {'id': 'example', 'source_text': 'ו״הרמב״ם״,', 'vocalized_text': 'ו״הרמב״ם״,'}
        item = decision(record, 'ו״הרמב״ם״,', spoken_reading='וְ״הָרַמְבַּ״ם״,')
        out = apply(record, [item])
        self.assertEqual(out['transliteration_input'], 'וְ״הָרַמְבַּם״,')
        self.assertEqual(len(out['reading_normalizations']), 1)

    def test_internal_quote_cluster_preserves_article_opening_quote(self):
        record = {'id': 'example', 'source_text': 'ה"רמב""ם"', 'vocalized_text': 'ה"רמב""ם"'}
        item = decision(record, 'ה"רמב""ם"', spoken_reading='הָ"רַמְבַּ""ם"')
        out = apply(record, [item])
        self.assertEqual(out['transliteration_input'], 'הָ"רַמְבַּם"')
        self.assertEqual(len(out['reading_normalizations']), 2)

    def test_shuruq_is_a_reviewed_vowel(self):
        record = {'id': 'example', 'source_text': 'שו״ת', 'vocalized_text': 'שו״ת'}
        item = decision(record, 'שו״ת', spoken_reading='שׁוּ״תּ')
        self.assertEqual(apply(record, [item])['transliteration_input'], 'שׁוּתּ')

    def test_consonant_dagesh_alone_is_not_a_vowel(self):
        record = {'id': 'example', 'source_text': 'ב״ח', 'vocalized_text': 'ב״ח'}
        item = decision(record, 'ב״ח', spoken_reading='בּ״ח')
        with self.assertRaises(ValueError):
            apply(record, [item])

    def test_plural_acronym_internal_marks_and_exterior_quotes(self):
        record = {'id': 'example', 'source_text': '"בשו״תים",', 'vocalized_text': '"בשו״תים",'}
        item = decision(record, '"בשו״תים",', spoken_reading='"בְּשׁוּ״תִּים",')
        out = apply(record, [item])
        self.assertEqual(out['transliteration_input'], '"בְּשׁוּתִּים",')
        self.assertEqual(len(out['reading_normalizations']), 1)

    def test_phrase_and_spoken_name_use_original_offsets(self):
        record = {'id': 'example', 'source_text': 'אע״פ שהרמב״ם כאן.',
                  'vocalized_text': 'אע״פ שהרמב״ם כָּאן.'}
        phrase = decision(record, 'אע״פ', decision='expand', expansion='אף על פי',
                          vocalized_expansion='אַף עַל פִּי')
        name = decision(record, 'שהרמב״ם', occurrence_id='example-2', spoken_reading='שֶׁהָרַמְבַּ״ם')
        out = apply(record, [phrase, name])
        self.assertEqual(out['expanded_source_text'], 'אף על פי שהרמב״ם כאן.')
        self.assertEqual(out['transliteration_input'], 'אַף עַל פִּי שֶׁהָרַמְבַּם כָּאן.')
        self.assertEqual(len(out['expansion_edits']), 1)
        self.assertEqual(len(out['reading_edits']), 2)

    def test_numeral_retention_does_not_remove_marks(self):
        record = {'id': 'example', 'source_text': 'סעיף ט״ז', 'vocalized_text': 'סְעִיף ט״ז'}
        out = apply(record, [decision(record, 'ט״ז', reason='The context gives a section number.')])
        self.assertEqual(out['transliteration_input'], 'סְעִיף ט״ז')
        self.assertEqual(out['reading_edits'], [])

    def test_same_written_form_can_be_spoken_name(self):
        record = {'id': 'example', 'source_text': 'הט״ז כתב.', 'vocalized_text': 'הט״ז כָּתַב.'}
        out = apply(record, [decision(record, 'הט״ז', spoken_reading='הַטַּ״ז', english_label='Taz')])
        self.assertEqual(out['transliteration_input'], 'הַטַּז כָּתַב.')

    def test_manual_reading_stays_visible(self):
        record = {'id': 'example', 'source_text': 'מהר״ש', 'vocalized_text': 'מהר״ש'}
        out = apply(record, [decision(record, 'מהר״ש', decision='manual',
                                     reason='The intended customary reading needs confirmation.')])
        self.assertEqual(out['transliteration_input'], 'מהר״ש')
        self.assertEqual(out['reading_status'], 'needs_attention')

    def test_spoken_reading_requires_same_letters_evidence_and_vowels(self):
        record = {'id': 'example', 'source_text': 'רמב״ם', 'vocalized_text': 'רמב״ם'}
        good = decision(record, 'רמב״ם', spoken_reading='רַמְבַּ״ם')
        for changes in [
            {'spoken_reading': 'רַבֵּנוּ מֹשֶׁה'},
            {'spoken_reading': 'רַמְבַּ"ם'},
            {'spoken_reading': 'רמב״ם'},
            {'evidence': ''},
            {'decision': 'manual'},
        ]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                apply(record, [dict(good, **changes)])

    def test_explicit_stale_and_missing_policy_rejected(self):
        record = {'id': 'example', 'source_text': 'רמב״ם', 'vocalized_text': 'רמב״ם'}
        good = decision(record, 'רמב״ם', spoken_reading='רַמְבַּ״ם')
        for field in ['reading_policy_version', 'dictionary_sha256']:
            for bad in [dict(good, **{field: 'old'}), {k: v for k, v in good.items() if k != field}]:
                with self.subTest(field=field, bad=bad), self.assertRaises(ValueError):
                    apply(record, [bad])

    def test_legacy_call_still_accepts_unversioned_decisions(self):
        record = {'id': 'example', 'source_text': 'אע״פ', 'vocalized_text': 'אע״פ'}
        item = decision(record, 'אע״פ', decision='expand', expansion='אף על פי')
        del item['reading_policy_version']
        del item['dictionary_sha256']
        self.assertEqual(m.apply([record], [item])[0]['expanded_source_text'], 'אף על פי')

    def test_overlapping_spoken_and_expanded_readings_rejected(self):
        record = {'id': 'example', 'source_text': 'הרמב״ם', 'vocalized_text': 'הרמב״ם'}
        first = decision(record, 'הרמב״ם', spoken_reading='הָרַמְבַּ״ם')
        second = decision(record, 'רמב״ם', occurrence_id='example-2', decision='expand', expansion='רמבם')
        with self.assertRaises(ValueError):
            apply(record, [first, second])

    def test_spoken_reading_is_blocked_for_held_handwriting(self):
        record = {'id': 'example', 'source_text': 'רמב״ם', 'vocalized_text': 'Review needed.', 'reading_held': True}
        item = decision(record, 'רמב״ם', spoken_reading='רַמְבַּ״ם')
        with self.assertRaises(ValueError):
            apply(record, [item])

    def test_silent_mater_outside_edit_preserved_with_offsets(self):
        source = '📚 חייב והרמב״ם כאן'
        record = {'id': 'example', 'source_text': source,
                  'vocalized_text': '📚 חַיָּיב וְהָרַמְבַּ״ם כָּאן',
                  'transliteration_input': '📚 חַיָּב וְהָרַמְבַּ״ם כָּאן',
                  'phonetic_normalization': [{'operation': 'omit_silent_spelling_letter',
                                             'source_offset': source.index('חייב') + 2,
                                             'source_length': 1, 'source_letter': 'י',
                                             'provenance': 'Reviewed synthetic annotation.'}]}
        item = decision(record, 'והרמב״ם', spoken_reading='וְהָרַמְבַּ״ם')
        out = apply(record, [item])
        self.assertEqual(out['transliteration_input'], '📚 חַיָּב וְהָרַמְבַּם כָּאן')
        self.assertEqual(out['reading_normalizations'][0]['source_offset'], source.index('חייב') + 2)
        self.assertEqual(out['reading_normalizations'][1]['operation'], 'omit_acronym_mark')

    def test_edit_supersedes_old_mater_annotation_inside_span(self):
        record = {'id': 'example', 'source_text': 'חו״מ', 'vocalized_text': 'חו״מ',
                  'transliteration_input': 'ח״מ',
                  'phonetic_normalization': [{'operation': 'omit_silent_spelling_letter',
                                             'source_offset': 1, 'source_length': 1, 'source_letter': 'ו'}]}
        item = decision(record, 'חו״מ', decision='expand', expansion='חושן משפט',
                        vocalized_expansion='חוֹשֶׁן מִשְׁפָּט')
        out = apply(record, [item])
        self.assertEqual(out['transliteration_input'], 'חוֹשֶׁן מִשְׁפָּט')
        self.assertEqual(out['reading_normalizations'], [])

    def test_unrecorded_letter_omission_rejected(self):
        record = {'id': 'example', 'source_text': 'חייב', 'vocalized_text': 'חַיָּיב',
                  'transliteration_input': 'חַיָּב'}
        with self.assertRaises(ValueError):
            apply(record, [])

    def test_stale_mater_offset_and_source_marks_rejected(self):
        for source, offset in [('חייב', 0), ('חַיָּיב', 2)]:
            record = {'id': 'example', 'source_text': source, 'vocalized_text': source,
                      'phonetic_normalization': [{'operation': 'omit_silent_spelling_letter',
                                                 'source_offset': offset, 'source_length': 1,
                                                 'source_letter': 'י'}]}
            with self.subTest(source=source), self.assertRaises(ValueError):
                apply(record, [])

    def test_explicit_phonetic_vowels_outside_edit_preserved(self):
        record = {'id': 'example', 'source_text': 'אב רמב״ם', 'vocalized_text': 'אָב רמב״ם',
                  'transliteration_input': 'אַב רמב״ם'}
        out = apply(record, [decision(record, 'רמב״ם', spoken_reading='רַמְבַּ״ם')])
        self.assertEqual(out['expanded_vocalized_text'], 'אָב רַמְבַּ״ם')
        self.assertEqual(out['transliteration_input'], 'אַב רַמְבַּם')

    def test_retry_on_derived_record_is_idempotent(self):
        record = {'id': 'example', 'source_text': 'רמב״ם כאן', 'vocalized_text': 'רמב״ם כָּאן'}
        item = decision(record, 'רמב״ם', spoken_reading='רַמְבַּ״ם')
        first = apply(record, [item])
        self.assertEqual(apply(first, [item]), first)

    def test_printed_niqqud_and_unicode_offsets_are_preserved(self):
        record = {'id': 'example', 'source_text': '📚 אָב רמב״ם', 'vocalized_text': '📚 אָב רמב״ם'}
        item = decision(record, 'רמב״ם', spoken_reading='רַמְבַּ״ם')
        out = apply(record, [item])
        self.assertEqual(out['source_text'], '📚 אָב רמב״ם')
        quote = record['source_text'].index('״')
        self.assertEqual(out['reading_normalizations'][0]['source_offset'], quote)

    def test_changed_versioned_reading_invalidates_old_transliteration(self):
        record = {'id': 'example', 'source_text': 'רמב״ם', 'vocalized_text': 'רמב״ם',
                  'transliteration_input': 'רמב״ם', 'transliteration': 'old candidate',
                  'transliteration_status': 'draft', 'transliteration_input_sha256': 'old'}
        out = apply(record, [decision(record, 'רמב״ם', spoken_reading='רַמְבַּ״ם')])
        self.assertEqual(out['transliteration'], '')
        self.assertEqual(out['transliteration_status'], 'pending')
        self.assertIsNone(out['transliteration_input_sha256'])
        self.assertEqual(record['transliteration'], 'old candidate')


if __name__ == '__main__':
    unittest.main()
