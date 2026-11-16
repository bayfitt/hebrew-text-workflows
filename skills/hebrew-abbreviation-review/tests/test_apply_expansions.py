#!/usr/bin/env python3
"""Safety checks for Hebrew offsets, retained niqqud, and stale source guards."""
import importlib.util
from pathlib import Path
import unittest

PATH = Path(__file__).resolve().parents[1] / 'scripts' / 'apply_expansions.py'
spec = importlib.util.spec_from_file_location('expansions', PATH)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def decision(record, token, expansion, **changes):
    start = record['source_text'].index(token)
    item = dict(occurrence_id='o1', id=record['id'],
                source_passage_sha256=m.digest(record['source_text']),
                start_char=start, end_char=start + len(token), raw_token=token,
                decision='expand', expansion=expansion,
                reason='The passage uses the standard phrase.', evidence='Exact local context.')
    item.update(changes)
    return item


class ExpansionSafety(unittest.TestCase):
    def test_python_unicode_offsets_preserve_surrounding_marks(self):
        r = dict(id='p1', source_text='📖 אָמַר אע״פ כן.', vocalized_text='📖 אָמַר אע״פ כֵּן.')
        d = decision(r, 'אע״פ', 'אף על פי', vocalized_expansion='אַף עַל פִּי')
        out = m.apply([r], [d])[0]
        self.assertEqual(out['source_text'], r['source_text'])
        self.assertEqual(out['vocalized_text'], r['vocalized_text'])
        self.assertEqual(out['expanded_source_text'], '📖 אָמַר אף על פי כן.')
        self.assertEqual(out['expanded_vocalized_text'], '📖 אָמַר אַף עַל פִּי כֵּן.')

    def test_two_edits_keep_offsets_from_original(self):
        r = dict(id='p2', source_text='אע״פ,מ״מ.', vocalized_text='אע״פ,מ״מ.')
        a = decision(r, 'אע״פ', 'אף על פי')
        b = decision(r, 'מ״מ', 'מכל מקום', occurrence_id='o2')
        self.assertEqual(m.apply([r], [b, a])[0]['expanded_source_text'], 'אף על פי,מכל מקום.')

    def test_stale_and_wrong_span_rejected(self):
        r = dict(id='p3', source_text='אע״פ', vocalized_text='אע״פ')
        d = decision(r, 'אע״פ', 'אף על פי')
        for changes in [dict(source_passage_sha256='wrong'), dict(raw_token='מ״מ')]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                m.apply([r], [dict(d, **changes)])

    def test_overlap_rejected(self):
        r = dict(id='p4', source_text='אע״פ', vocalized_text='אע״פ')
        a = decision(r, 'אע״פ', 'אף על פי')
        b = decision(r, 'ע״פ', 'על פי', occurrence_id='o2')
        with self.assertRaises(ValueError):
            m.apply([r], [a, b])

    def test_incompatible_vocalization_rejected(self):
        r = dict(id='p5', source_text='אע״פ', vocalized_text='אע״פ')
        d = decision(r, 'אע״פ', 'אף על פי', vocalized_expansion='אַף עַל פִּיו')
        with self.assertRaises(ValueError):
            m.apply([r], [d])

    def test_reading_notice_preserved_and_expansion_blocked(self):
        r = dict(id='p6', source_text='אע״פ', vocalized_text='Handwriting: review needed.', reading_held=True)
        self.assertEqual(m.apply([r], [])[0]['expanded_vocalized_text'], r['vocalized_text'])
        with self.assertRaises(ValueError):
            m.apply([r], [decision(r, 'אע״פ', 'אף על פי')])

    def test_partial_mark_cluster_and_misaligned_reading_rejected(self):
        r = dict(id='p7', source_text='ר׳ַ', vocalized_text='ר׳ַ')
        with self.assertRaises(ValueError):
            m.apply([r], [decision(r, 'ר׳', 'רבי')])
        with self.assertRaises(ValueError):
            m.apply([dict(id='p8', source_text='אב', vocalized_text='אָבג')], [])


if __name__ == '__main__':
    unittest.main()
