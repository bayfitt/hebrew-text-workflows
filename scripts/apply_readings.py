#!/usr/bin/env python3
"""Validate policy-bound spoken decisions and apply the exact-span reading pass."""
import argparse
import importlib.util
import json
from pathlib import Path
import re
import unicodedata

from workflow_io import digest, read_records, separate_output, write_records


ROOT = Path(__file__).resolve().parents[1]
MARK = re.compile(r'[\u0591-\u05bd\u05bf\u05c1-\u05c2\u05c4-\u05c5\u05c7]')
QUOTES = str.maketrans({'״': '"', '“': '"', '”': '"', '׳': "'", '’': "'", '‘': "'"})
NUMBER_WORDS = set('אחד אחת שני שניים שנים שתיים שתי שלוש שלושה ארבע ארבעה חמש חמישה חמשה שש שישה ששה שבע שבעה שמונה תשע תשעה עשר עשרה עשרים שלושים ארבעים חמישים ששים שישים שבעים שמונים תשעים מאה מאתיים מאות אלף אלפיים אלפים'.split())


def normalized(text):
    return unicodedata.normalize('NFC', text.translate(QUOTES))


def matched_entry(token, dictionary):
    plain = MARK.sub('', normalized(token))
    matches = []
    for entry in dictionary['entries']:
        written = MARK.sub('', normalized(entry['written_form']))
        pattern = ''.join('["\']+' if char in ['"', "'"] else re.escape(char) for char in written)
        for match in re.finditer(pattern, plain):
            before, after = plain[:match.start()], plain[match.end():]
            if (re.fullmatch('[^א-ת0-9]*[ובכלמשהד]*', before)
                    and not re.search('[א-ת0-9]', after)):
                matches.append((len(written), match.start(), match.end(), entry))
    return max(matches, key=lambda match: match[0])[1:] if matches else (0, 0, None)


def spoken_core(reading, start, end):
    positions = [index for index, char in enumerate(reading) if not MARK.fullmatch(char)] + [len(reading)]
    return reading[positions[start]:positions[end]]


def canonical_quotes(reading):
    return re.sub('["\']+', '"', normalized(reading))


def spoken_matches_profile(reading, start, end, expected):
    core = spoken_core(reading, start, end)
    normalized_core = canonical_quotes(core)
    allowed = {canonical_quotes(value) for value in expected}
    if normalized_core in allowed:
        return True
    positions = [index for index, char in enumerate(reading) if not MARK.fullmatch(char)] + [len(reading)]
    prefix = reading[:positions[start]]
    prefix_units = re.findall(r'[א-ת][\u0591-\u05c7]*', prefix)
    if not prefix_units:
        return False
    last_prefix = prefix_units[-1]
    article = last_prefix[0] == 'ה' or (last_prefix[0] in 'בכל' and any(mark in last_prefix for mark in ['\u05b7', '\u05b8']))
    first = re.match(r'^([א-ת])([\u0591-\u05c7]*)', normalized_core)
    if not article or first is None or '\u05bc' not in first[2]:
        return False
    ungeminated = first[1] + first[2].replace('\u05bc', '', 1) + normalized_core[first.end():]
    return ungeminated in allowed


def validate_dictionary_decisions(decisions, dictionary):
    for decision in decisions:
        start, end, entry = matched_entry(decision['raw_token'], dictionary)
        if entry is None or decision['decision'] == 'manual':
            continue
        if decision.get('usage') in ['number', 'quotation', 'reference']:
            if decision.get('spoken_reading') or decision.get('english_label'):
                raise ValueError('A literal or numeric usage cannot carry a name reading')
            if decision['decision'] == 'expand':
                words = MARK.sub('', decision.get('expansion', '')).split()
                numeric = words and all(word in NUMBER_WORDS or word.removeprefix('ו') in NUMBER_WORDS or word.isdecimal() for word in words)
                if decision['usage'] != 'number' or not numeric:
                    raise ValueError('A literal homograph expansion requires a reviewed number phrase')
            continue
        if entry['decision'] == 'retain' and entry.get('spoken_reading'):
            if decision['decision'] == 'expand':
                raise ValueError('A familiar spoken acronym requires a retained reading decision')
            if decision.get('spoken_reading'):
                expected = [entry['spoken_reading'], *entry.get('spoken_reading_variants', [])]
                if not spoken_matches_profile(decision['spoken_reading'], start, end, expected):
                    raise ValueError('Spoken reading differs from the selected dictionary profile')
                if decision.get('english_label') != entry.get('english_label'):
                    raise ValueError('English name differs from the selected dictionary label')
        elif entry['decision'] == 'expand' and decision['decision'] == 'expand':
            plain = MARK.sub('', normalized(decision['raw_token']))
            expected = plain[:start] + entry['expansion'] + plain[end:]
            contextual = decision.get('contextual_alternative')
            if contextual:
                if not isinstance(contextual, str) or not contextual.strip() or not decision.get('evidence') or not decision.get('reason'):
                    raise ValueError('A contextual dictionary alternative requires a reason and evidence')
            else:
                if canonical_quotes(decision['expansion']) != canonical_quotes(expected):
                    raise ValueError('Phrase expansion differs from the selected dictionary profile')
                if entry.get('english_label') and decision.get('english_label') != entry['english_label']:
                    raise ValueError('English title differs from the selected dictionary label')


def apply(records, decisions, dictionary, dictionary_hash):
    validate_dictionary_decisions(decisions, dictionary)
    spec = importlib.util.spec_from_file_location(
        'spoken_reading_engine', ROOT / 'skills/hebrew-abbreviation-review/scripts/apply_expansions.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.apply(records, decisions, policy_version=dictionary['policy_version'],
                        dictionary_sha256=dictionary_hash)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--records', required=True)
    parser.add_argument('--decisions', required=True)
    parser.add_argument('--dictionary', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    separate_output(args.output, args.records, args.decisions, args.dictionary)
    dictionary_bytes = Path(args.dictionary).read_bytes()
    dictionary = json.loads(dictionary_bytes)
    decisions = [json.loads(line) for line in Path(args.decisions).read_text().splitlines() if line.strip()]
    output = apply(read_records(args.records), decisions, dictionary, digest(dictionary_bytes))
    write_records(args.output, output)
    print(json.dumps({'records': len(output), 'reading_policy_version': dictionary['policy_version'],
                      'dictionary_sha256': digest(dictionary_bytes)}))


if __name__ == '__main__':
    main()
