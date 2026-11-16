#!/usr/bin/env python3
"""Apply reviewed spoken readings to derived Hebrew and Charles input."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re


MARK = re.compile(r'[\u0591-\u05bd\u05bf\u05c1-\u05c2\u05c4-\u05c5\u05c7]')
VOWEL = re.compile(r'[\u05b0-\u05bb\u05c7]')
HEBREW = re.compile(r'[א-ת]')
ACRONYM_MARKS = frozenset('״׳"\'‘’“”')


def strip_marks(text):
    return MARK.sub('', text)


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def jsonl(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def letter_units(text):
    """Group each base character with its following Hebrew marks."""
    leading = ''
    units = []
    for offset, character in enumerate(text):
        if MARK.fullmatch(character):
            if units:
                units[-1]['text'] += character
            else:
                leading += character
        else:
            units.append({'character': character, 'text': character, 'offset': offset})
    return leading, units


def decision_versions(decisions, field, expected):
    versions = {item[field] for item in decisions if item.get(field) is not None}
    if len(versions) > 1:
        raise ValueError('Mixed decision versions for ' + field)
    if expected is not None:
        if any(item.get(field) != expected for item in decisions):
            raise ValueError('Stale or missing decision version for ' + field)
        return expected
    return next(iter(versions), None)


def acronym_mark_positions(units):
    """Find the rightmost internal cluster, including before an acronym suffix."""
    for right in reversed(range(1, len(units))):
        if not HEBREW.fullmatch(units[right]['character']):
            continue
        start = right
        while start > 0 and units[start - 1]['character'] in ACRONYM_MARKS:
            start -= 1
        if 0 < start < right and HEBREW.fullmatch(units[start - 1]['character']):
            return set(range(start, right))
    return set()


def validate_decisions(records, decisions, policy_version, dictionary_sha256):
    by_id = {record['id']: record for record in records}
    if len(by_id) != len(records):
        raise ValueError('Duplicate passage IDs')
    policy_version = decision_versions(decisions, 'reading_policy_version', policy_version)
    dictionary_sha256 = decision_versions(decisions, 'dictionary_sha256', dictionary_sha256)
    occurrences = set()
    grouped = defaultdict(list)
    for decision in decisions:
        occurrence = decision['occurrence_id']
        if occurrence in occurrences:
            raise ValueError('Duplicate occurrence: ' + occurrence)
        occurrences.add(occurrence)
        identity = decision['id']
        if identity not in by_id:
            raise ValueError('Unknown passage: ' + identity)
        source = by_id[identity]['source_text']
        start, end = decision['start_char'], decision['end_char']
        if decision['source_passage_sha256'] != digest(source):
            raise ValueError('Stale source: ' + identity)
        if not 0 <= start < end <= len(source) or source[start:end] != decision['raw_token']:
            raise ValueError('Wrong literal span: ' + occurrence)
        if MARK.fullmatch(source[start]) or (end < len(source) and MARK.fullmatch(source[end])):
            raise ValueError('Partial Hebrew mark cluster: ' + occurrence)
        action = decision['decision']
        if action not in ['expand', 'retain', 'manual']:
            raise ValueError('Unknown decision: ' + occurrence)
        if not decision.get('reason'):
            raise ValueError('Missing contextual reason: ' + occurrence)
        spoken = decision.get('spoken_reading')
        if spoken is not None:
            if action != 'retain' or not isinstance(spoken, str) or not spoken.strip():
                raise ValueError('Spoken reading requires a retained token: ' + occurrence)
            if strip_marks(spoken) != strip_marks(decision['raw_token']):
                raise ValueError('Spoken reading changes literal characters: ' + occurrence)
            _, spoken_units = letter_units(spoken)
            has_shuruq = any(unit['character'] == 'ו' and '\u05bc' in unit['text']
                             for unit in spoken_units)
            if not VOWEL.search(spoken) and not has_shuruq:
                raise ValueError('Spoken reading needs reviewed vowels: ' + occurrence)
            if not decision.get('evidence'):
                raise ValueError('Missing spoken-reading evidence: ' + occurrence)
        if action == 'expand':
            expansion = decision.get('expansion')
            if not isinstance(expansion, str) or not expansion.strip() or strip_marks(expansion) != expansion:
                raise ValueError('Expansion must be nonempty and unpointed: ' + occurrence)
            if not decision.get('evidence'):
                raise ValueError('Missing expansion evidence: ' + occurrence)
            vocalized = decision.get('vocalized_expansion')
            if vocalized is not None and strip_marks(vocalized) != expansion:
                raise ValueError('Expanded vocalization changes letters: ' + occurrence)
        elif decision.get('expansion') is not None:
            raise ValueError('Unaccepted expansion provided: ' + occurrence)
        if decision.get('english_label') is not None and (
                not isinstance(decision['english_label'], str) or not decision['english_label'].strip()):
            raise ValueError('English label must be nonempty text: ' + occurrence)
        grouped[identity].append(decision)
    return grouped, policy_version, dictionary_sha256


def baseline_phonetics(record, source_units, reading, reading_units):
    """Align a supplied phonetic input using its exact omission provenance."""
    by_offset = {unit['offset']: index for index, unit in enumerate(source_units)}
    omitted = {}
    for normalization in record.get('phonetic_normalization', []):
        offset = normalization.get('source_offset')
        if (normalization.get('operation') != 'omit_silent_spelling_letter'
                or type(offset) is not int or offset not in by_offset
                or normalization.get('source_length') != 1):
            raise ValueError('Unsupported phonetic normalization: ' + record['id'])
        index = by_offset[offset]
        character = source_units[index]['character']
        if (character not in 'וי' or source_units[index]['text'] != character
                or normalization.get('source_letter') != character or index in omitted):
            raise ValueError('Stale or duplicate phonetic normalization: ' + record['id'])
        omitted[index] = dict(normalization)

    supplied = record.get('source_transliteration_input', record.get('transliteration_input'))
    if not supplied:
        leading, _ = letter_units(reading)
        supplied = leading + ''.join(unit['text'] for index, unit in enumerate(reading_units)
                                     if index not in omitted)
    leading, phonetic_units = letter_units(supplied)
    expected = ''.join(unit['character'] for index, unit in enumerate(source_units) if index not in omitted)
    if strip_marks(supplied) != expected:
        raise ValueError('Unrecorded phonetic character change: ' + record['id'])
    phonetics = []
    cursor = iter(phonetic_units)
    for index in range(len(source_units)):
        phonetics.append('' if index in omitted else next(cursor)['text'])
    return supplied, leading, phonetics, omitted


def render_readings(record, accepted):
    source = record['source_text']
    reading = record.get('vocalized_text') or source
    if strip_marks(reading) != strip_marks(source):
        raise ValueError('Reading/source alignment differs: ' + record['id'])
    _, source_units = letter_units(source)
    reading_leading, reading_units = letter_units(reading)
    baseline, phonetic_leading, phonetics, omitted = baseline_phonetics(
        record, source_units, reading, reading_units)
    display_parts = [reading_leading]
    phonetic_parts = [phonetic_leading]
    display_size = len(reading_leading)
    phonetic_size = len(phonetic_leading)
    normalizations = []
    cursor = 0

    for decision in accepted + [None]:
        left = len(source_units) if decision is None else len(strip_marks(source[:decision['start_char']]))
        for index in range(cursor, left):
            display = reading_units[index]['text']
            if index in omitted:
                normalizations.append({**omitted[index], 'reading_offset': display_size,
                                       'transliteration_input_offset': phonetic_size})
            display_parts.append(display)
            phonetic_parts.append(phonetics[index])
            display_size += len(display)
            phonetic_size += len(phonetics[index])
        if decision is None:
            break
        right = len(strip_marks(source[:decision['end_char']]))
        if decision['decision'] == 'expand':
            replacement = decision.get('vocalized_expansion') or decision['expansion']
            phonetic_replacement = replacement
        else:
            replacement = decision['spoken_reading']
            leading, units = letter_units(replacement)
            acronym_marks = acronym_mark_positions(units)
            pieces = [leading]
            local_size = len(leading)
            for index, unit in enumerate(units):
                if index in acronym_marks:
                    if len(unit['text']) != 1:
                        raise ValueError('Spoken acronym mark carries vowels: ' + decision['occurrence_id'])
                    normalizations.append({
                        'rule_id': 'spoken-acronym-marks-v1',
                        'operation': 'omit_acronym_mark',
                        'source_offset': source_units[left + index]['offset'],
                        'source_length': 1,
                        'source_character': unit['character'],
                        'reading_offset': display_size + unit['offset'],
                        'transliteration_input_offset': phonetic_size + local_size,
                        'occurrence_id': decision['occurrence_id'],
                        'provenance': decision['evidence'],
                        'applies_to': 'transliteration_input_only',
                    })
                else:
                    pieces.append(unit['text'])
                    local_size += len(unit['text'])
            phonetic_replacement = ''.join(pieces)
        display_parts.append(replacement)
        phonetic_parts.append(phonetic_replacement)
        display_size += len(replacement)
        phonetic_size += len(phonetic_replacement)
        cursor = right

    expanded_source = source
    for decision in reversed(accepted):
        if decision['decision'] == 'expand':
            start, end = decision['start_char'], decision['end_char']
            expanded_source = expanded_source[:start] + decision['expansion'] + expanded_source[end:]
    expanded_reading = ''.join(display_parts)
    if strip_marks(expanded_reading) != strip_marks(expanded_source):
        raise ValueError('Output layers differ: ' + record['id'])
    return expanded_source, expanded_reading, ''.join(phonetic_parts), normalizations, baseline


def apply(records, decisions, *, policy_version=None, dictionary_sha256=None):
    grouped, policy_version, dictionary_sha256 = validate_decisions(
        records, decisions, policy_version, dictionary_sha256)
    output = []
    for original in records:
        record = dict(original)
        source = original['source_text']
        reading = original.get('vocalized_text') or source
        decisions_here = grouped[original['id']]
        accepted = sorted((decision for decision in decisions_here
                           if decision['decision'] == 'expand' or decision.get('spoken_reading') is not None),
                          key=lambda decision: decision['start_char'])
        previous_end = 0
        for decision in accepted:
            if decision['start_char'] < previous_end:
                raise ValueError('Overlapping readings: ' + original['id'])
            previous_end = decision['end_char']
        if original.get('reading_held'):
            if accepted:
                raise ValueError('Cannot apply a reading to held handwriting: ' + original['id'])
            expanded_source, expanded_reading = source, reading
            baseline = original.get('source_transliteration_input', original.get('transliteration_input')) or reading
            phonetic, normalizations = baseline, []
            status = 'held'
        else:
            expanded_source, expanded_reading, phonetic, normalizations, baseline = render_readings(record, accepted)
            needs_attention = any(decision['decision'] == 'manual' for decision in decisions_here)
            needs_attention |= any(decision['decision'] == 'expand' and not decision.get('vocalized_expansion')
                                   for decision in accepted)
            status = 'needs_attention' if needs_attention else 'draft'
        expansions = [decision for decision in accepted if decision['decision'] == 'expand']
        record.update(
            expanded_source_text=expanded_source,
            expanded_vocalized_text=expanded_reading,
            expansion_edits=expansions,
            reading_edits=accepted,
            reading_policy_version=policy_version,
            dictionary_sha256=dictionary_sha256,
            reading_status=status,
            source_transliteration_input=baseline,
            transliteration_input=phonetic,
            reading_normalizations=normalizations,
            expansion_review=dict(Counter(decision['decision'] for decision in decisions_here)),
            expansion_source_sha256=digest(source),
            expanded_source_sha256=digest(expanded_source),
        )
        previous_input = original.get('transliteration_input', reading)
        if policy_version is not None and phonetic != previous_input and original.get('transliteration'):
            record['transliteration'] = ''
            record['transliteration_status'] = 'pending'
            record['transliteration_input_sha256'] = None
        assert record['source_text'] == original['source_text']
        assert record.get('vocalized_text') == original.get('vocalized_text')
        output.append(record)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--records', required=True)
    parser.add_argument('--decisions', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--policy-version')
    parser.add_argument('--dictionary-sha256')
    args = parser.parse_args()
    if Path(args.output).resolve() in [Path(args.records).resolve(), Path(args.decisions).resolve()]:
        parser.error('Use a separate output path')
    records, decisions = jsonl(args.records), jsonl(args.decisions)
    output = apply(records, decisions, policy_version=args.policy_version, dictionary_sha256=args.dictionary_sha256)
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(''.join(json.dumps(record, ensure_ascii=False) + '\n' for record in output))
    temporary.chmod(0o600)
    temporary.replace(path)
    print(json.dumps({
        'passages': len(output),
        'decisions': dict(Counter(decision['decision'] for decision in decisions)),
        'passages_with_expansions': sum(bool(record['expansion_edits']) for record in output),
        'passages_with_reviewed_readings': sum(bool(record['reading_edits']) for record in output),
        'literal_and_vocalized_inputs_preserved': True,
        'reading_policy_version': output[0]['reading_policy_version'] if output else args.policy_version,
    }))


if __name__ == '__main__':
    main()
