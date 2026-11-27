import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from review_niqqud import candidates, plain, review, set_reading


class ContextReview(unittest.TestCase):
    def row(self, src, draft):
        return {'id': 'r', 'source_text': src, 'vocalized_text': draft, 'other': 'keep'}

    def decisions(self, row, *senses):
        _, audit = review([row], [], 'source_text')
        self.assertEqual(len(audit), len(senses))
        return [dict(a, sense=s, reason='Complete clause examined') for a, s in zip(audit, senses)]

    def test_regression_name_and_other_senses(self):
        row = self.row('קרא לו שם. היה שם. שם אותו. אין רושם.',
                       'קרא לו שָׁם. היה שֵׁם. שָׁם אותו. אין רושם.')
        rules = self.decisions(row, 'name', 'there', 'set')
        checked, _ = review([row], rules, 'source_text', True)
        self.assertEqual(checked[0]['vocalized_text'], 'קרא לו שֵׁם. היה שָׁם. שָׂם אותו. אין רושם.')
        self.assertEqual(plain(checked[0]['vocalized_text']), row['source_text'])
        self.assertEqual(checked[0]['other'], 'keep')

    def test_exact_wars_of_the_lord_reading(self):
        row = self.row('וקראתי שם הספר מלחמות השם',
                       'וְקָרָאתִי שָׁם הַסֵּפֶר מִלְחֲמוֹת הַשֵּׁם')
        row['id'] = 'MH-SEF-01-005'
        row['vocalization_flags'] = [
            {'code': 'provider_low_confidence', 'offset': 7, 'blocking': False, 'token': 'שם'}]
        _, queue = review([row], [], 'source_text')
        self.assertEqual(queue[0]['provider_warnings'], ['provider_low_confidence'])
        self.assertEqual(queue[1]['provider_warnings'], [])
        with self.assertRaisesRegex(ValueError, 'Unresolved'):
            review([row], [], 'source_text', True)
        rules = self.decisions(row, 'name', 'name')
        [checked], _ = review([row], rules, 'source_text', True)
        self.assertEqual(checked['vocalized_text'],
                         'וְקָרָאתִי שֵׁם הַסֵּפֶר מִלְחֲמוֹת הַשֵּׁם')

    def test_no_global_change_or_substrings(self):
        row = self.row('שָׁם נשמה שמש ש״ם', 'שָׁם נשמה שמש ש״ם')
        checked, audit = review([row], self.decisions(row, 'uncertain'), 'source_text')
        self.assertEqual(checked[0]['vocalized_text'], row['vocalized_text'])
        self.assertEqual(len(audit), 1)
        with self.assertRaisesRegex(ValueError, 'Unresolved'):
            review([row], [], 'source_text', True)

    def test_preserves_noncanonical_order_and_protected_marks(self):
        raw = 'מִשׁ\u0591ָ\u05bdם\u05c4'
        self.assertEqual(set_reading(raw, 'name', 'מש\u0591ם'), 'מִשׁ\u0591ֵ\u05bdם\u05c4')
        self.assertEqual(set_reading('שָׁם', 'there', 'שָׁם'), 'שָׁם')
        with self.assertRaisesRegex(ValueError, 'original'):
            set_reading('שָׁם', 'name', 'שָׁם')
        self.assertEqual(len(candidates('השם משם ובשם ששם ובכּלל')), 4)

    def test_stale_decision_and_deleted_target_fail(self):
        row = self.row('שם', 'שָׁם')
        [decision] = self.decisions(row, 'name')
        with self.assertRaisesRegex(ValueError, 'Stale'):
            review([self.row('שם', 'שָׁם')], [decision], 'source_text')
        with self.assertRaisesRegex(ValueError, 'consonants'):
            review([self.row('שם', 'שן')], [], 'source_text')

    def test_does_not_leave_stale_phonetic_input(self):
        row = dict(self.row('שם', 'שָׁם'), transliteration_input='שָׁם')
        rules = self.decisions(row, 'name')
        [checked], _ = review([row], rules, 'source_text')
        self.assertEqual(checked['transliteration_input'], 'שֵׁם')
        row['transliteration_input'] += '!'
        with self.assertRaisesRegex(ValueError, 'divergent'):
            review([row], rules, 'source_text')
