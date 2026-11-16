#!/usr/bin/env python3
"""Cached, source-preserving draft niqqud through Dicta's rabbinic Nakdan.

No generated fallback vowels, abbreviation expansion, spelling correction, or
translation occurs here. Every output still requires contextual proofreading.
The public endpoint and request shape come from NakdanPro's current client:
https://nakdanpro.dicta.org.il/js/app.a9570778.js (accessed 2026-11-15).
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
ENDPOINT = 'https://nakdan-u2-1a.loadbalancer.dicta.org.il/api'
MARK_RE = re.compile(r'[\u0591-\u05bd\u05bf\u05c1-\u05c2\u05c4-\u05c5\u05c7]')
HEBREW_RE = re.compile(r'[\u05d0-\u05ea]')
VOWELS = set(chr(n) for n in range(0x05B0, 0x05BC)) | {'\u05c7'}
ADDABLE = VOWELS | {'\u05bc', '\u05bf', '\u05c1', '\u05c2'}
QUOTE_MAP = str.maketrans({'׳': "'", '״': '"', '’': "'", '‘': "'", '“': '"', '”': '"'})
ACRONYM_RE = re.compile(r'[א-ת][א-ת\u0591-\u05c7]*[״"׳\x27][א-ת\u0591-\u05c7]*')
NAME_RE = re.compile(r'(?<![א-ת])(?:רבי|הרבי|רב|הרב|רבנו|רבינו|רבן|הגאון)\s+([א-ת][א-ת\u0591-\u05c7״"׳\x27]*)')
MATER_RULE = 'dicta-matres-v1'
MATER_RULE_SOURCE = 'https://nakdanpro.dicta.org.il/js/app.a9570778.js'


def digest(value: str | bytes) -> str:
    return hashlib.sha256(value.encode('utf-8') if isinstance(value, str) else value).hexdigest()


def strip_marks(value: str) -> str:
    return MARK_RE.sub('', value)


def same_base(source: str, candidate: str) -> bool:
    return strip_marks(source).translate(QUOTE_MAP) == strip_marks(candidate).translate(QUOTE_MAP)


def letter_units(value: str) -> tuple[str, list[dict]]:
    leading = ''
    units: list[dict] = []
    for offset, char in enumerate(value):
        if MARK_RE.fullmatch(char):
            if units:
                units[-1]['marks'] += char
            else:
                leading += char
        else:
            units.append({'char': char, 'marks': '', 'offset': offset})
    return leading, units


def overlay_marks(source: str, candidate: str) -> tuple[str, list[dict], int]:
    """Add only compatible missing marks; original characters remain in order."""
    flags: list[dict] = []
    # A vertical bar in a Nakdan word option marks its prefix boundary.
    candidate = candidate.replace('|', '')
    if not same_base(source, candidate):
        return source, [{'code': 'candidate_consonant_difference', 'offset': 0,
                         'candidate': candidate, 'blocking': True}], 0
    leading, source_units = letter_units(source)
    _, candidate_units = letter_units(candidate)
    result = [leading]
    added = 0
    for original, predicted in zip(source_units, candidate_units):
        marks = original['marks']
        candidate_marks = set(predicted['marks']) & ADDABLE
        # U+05BD in this service also marks matres lectionis. Never add that
        # service metadata as an editorial meteg. Source meteg is preserved.
        if not HEBREW_RE.fullmatch(original['char']):
            result.append(original['char'] + marks)
            continue
        existing = set(marks)
        groups = [VOWELS, {'\u05c1', '\u05c2'}, {'\u05bc', '\u05bf'}]
        allowed = set(candidate_marks)
        for group in groups:
            current, proposed = existing & group, candidate_marks & group
            if current:
                allowed -= group
                if proposed and current != proposed:
                    flags.append({'code': 'existing_mark_conflict', 'offset': original['offset'],
                                  'source_marks': ''.join(sorted(current)),
                                  'provider_marks': ''.join(sorted(proposed)), 'blocking': False})
        # An added shureq dot would contradict an existing holam on vav, and
        # adding holam would contradict an already pointed vowel shureq.
        if original['char'] == 'ו':
            if existing & {'\u05b9', '\u05ba'} and '\u05bc' in allowed:
                allowed.discard('\u05bc')
                flags.append({'code': 'existing_mark_conflict', 'offset': original['offset'],
                              'detail': 'Source holam conflicts with predicted shureq.', 'blocking': False})
            if '\u05bc' in existing and not (existing & VOWELS) and allowed & {'\u05b9', '\u05ba'}:
                allowed -= {'\u05b9', '\u05ba'}
                flags.append({'code': 'existing_mark_conflict', 'offset': original['offset'],
                              'detail': 'Source shureq conflicts with predicted holam.', 'blocking': False})
        extra = ''.join(dict.fromkeys(char for char in predicted['marks'] if char in allowed - existing))
        added += len(extra)
        result.append(original['char'] + marks + extra)
    output = ''.join(result)
    if strip_marks(output) != strip_marks(source):
        raise AssertionError('Overlay changed a source consonant, space, or punctuation mark.')
    # Existing marks occur in exactly the original order on the same character.
    _, final_units = letter_units(output)
    if len(final_units) != len(source_units) or any(
        a['char'] != b['char'] or not b['marks'].startswith(a['marks'])
        for a, b in zip(source_units, final_units)
    ):
        raise AssertionError('Overlay changed an original mark.')
    return output, flags, added


def option_text(option) -> str:
    if isinstance(option, str):
        return option
    if isinstance(option, list) and option:
        return str(option[0])
    if isinstance(option, dict):
        return str(option.get('w', option.get('nikud', '')))
    return ''


def phonetic_reading(source: str, displayed: str, provider_option: str,
                     provider_rank: int = 1) -> tuple[str, list[dict], list[dict]]:
    """Omit only explicitly annotated silent spelling letters from reading.

    Dicta's official client exports its haser reading by dropping the character
    immediately followed by U+05BD. Our displayed text keeps the original
    letters. We carry those annotations separately and apply the documented
    reading operation only to a distinct Charles input. Genuine original
    meteg is not evidence that a source letter is silent.
    """
    raw = provider_option.replace('|', '')
    if not same_base(source, raw) or not same_base(source, displayed):
        return displayed, [], [{'code': 'phonetic_alignment_error', 'offset': 0, 'blocking': True}]
    leading, original_units = letter_units(source)
    _, display_units = letter_units(displayed)
    _, provider_units = letter_units(raw)
    omissions: set[int] = set()
    normalizations, flags = [], []
    for index, (original, predicted) in enumerate(zip(original_units, provider_units)):
        if '\u05bd' not in predicted['marks']:
            continue
        if '\u05bd' in original['marks']:
            flags.append({'code': 'source_meteg_not_interpreted_as_mater', 'offset': original['offset'],
                          'detail': 'Original meteg is preserved; its meaning is not inferred from provider metadata.',
                          'blocking': False})
            continue
        # Only the unpointed yod/vav metadata actually observed in this API is
        # accepted automatically. Existing marks and other letter annotations
        # need review rather than a guessed deletion.
        if (original['char'] not in 'וי' or original['marks']
                or set(predicted['marks']) != {'\u05bd'}):
            flags.append({'code': 'ambiguous_mater_annotation', 'offset': original['offset'],
                          'source_letter': original['char'], 'provider_option': provider_option,
                          'detail': 'No automatic reading deletion: original marks, unsupported letter, or conflicting provider marks.',
                          'blocking': True})
            continue
        omissions.add(index)
        normalizations.append({'rule_id': MATER_RULE, 'operation': 'omit_silent_spelling_letter',
                               'source_offset': original['offset'], 'source_length': 1,
                               'source_letter': original['char'], 'provider_marker': 'U+05BD',
                               'provider_option': provider_option, 'provider_option_rank': provider_rank,
                               'provenance': MATER_RULE_SOURCE,
                               'applies_to': 'transliteration_input_only', 'proofreading_status': 'pending'})
    reading = leading + ''.join(unit['char'] + unit['marks'] for index, unit in enumerate(display_units)
                                if index not in omissions)
    removed_offsets = {item['source_offset'] for item in normalizations}
    expected = ''.join(char for offset, char in enumerate(source)
                       if offset not in removed_offsets and not MARK_RE.fullmatch(char))
    if strip_marks(reading) != expected:
        raise AssertionError('Phonetic input changed more than the recorded metadata-marked letters.')
    return reading, normalizations, flags


def render_response(source: str, response) -> list[dict]:
    data = response.get('data') if isinstance(response, dict) else response
    if not isinstance(data, list):
        raise ValueError('Nakdan response has no ordered token list.')
    originals = [str(token.get('str', token.get('word', ''))) for token in data]
    if ''.join(originals) != source:
        raise ValueError('Provider tokenization does not reproduce the exact submitted text.')
    rendered: list[dict] = []
    offset = 0
    for token, original in zip(data, originals):
        item = token.get('nakdan', token)
        flags: list[dict] = []
        output, reading, added = original, original, 0
        normalizations: list[dict] = []
        if not token.get('sep', item.get('sep', False)) and HEBREW_RE.search(original):
            options = item.get('options', [])
            selected = selected_raw = None
            rank = None
            for index, option in enumerate(options):
                candidate = option_text(option).replace('|', '')
                if same_base(original, candidate):
                    selected, rank = candidate, index
                    selected_raw = option_text(option)
                    break
            if selected is None:
                flags.append({'code': 'no_source_preserving_candidate', 'offset': 0,
                              'candidate': option_text(options[0]) if options else '', 'blocking': True})
            else:
                output, mark_flags, added = overlay_marks(original, selected)
                flags.extend(mark_flags)
                reading, normalizations, reading_flags = phonetic_reading(original, output, selected_raw, rank + 1)
                flags.extend(reading_flags)
                if rank:
                    flags.append({'code': 'lower_rank_source_preserving_candidate', 'offset': 0,
                                  'provider_rank': rank + 1, 'blocking': False})
            if item.get('fconfident') is False:
                flags.append({'code': 'provider_low_confidence', 'offset': 0, 'blocking': False})
            if item.get('fnotfromwl'):
                flags.append({'code': 'provider_unknown_word', 'offset': 0, 'blocking': False})
            if not any(char in VOWELS for char in output):
                flags.append({'code': 'word_without_vowels', 'offset': 0, 'blocking': True})
        rendered.append({'start': offset, 'end': offset + len(original), 'source': original,
                         'output': output, 'transliteration_input': reading,
                         'phonetic_normalization': normalizations, 'flags': flags, 'added': added})
        offset += len(original)
    return rendered


def extract_span(tokens: list[dict], start: int, end: int, source: str) -> dict:
    pieces, readings, flags, normalizations, added = [], [], [], [], 0
    for token in tokens:
        low, high = max(start, token['start']), min(end, token['end'])
        if low >= high:
            continue
        if low == token['start'] and high == token['end']:
            pieces.append(token['output'])
            readings.append(token.get('transliteration_input', token['output']))
            added += token['added']
            normalizations.extend({**item, 'source_offset': token['start'] - start + item['source_offset']}
                                  for item in token.get('phonetic_normalization', []))
            flags.extend({**flag, 'offset': token['start'] - start + flag['offset'],
                          'token': token['source']} for flag in token['flags'])
        elif token['output'] == token['source']:
            pieces.append(token['source'][low - token['start']:high - token['start']])
            readings.append(token['source'][low - token['start']:high - token['start']])
        else:
            raise ValueError('A provider word crosses a source record boundary.')
    output = ''.join(pieces)
    if strip_marks(output) != strip_marks(source):
        raise ValueError('Extracted output changes a source consonant, space, or punctuation mark.')
    for match in ACRONYM_RE.finditer(source):
        flags.append({'code': 'acronym_or_abbreviation_reading', 'offset': match.start(),
                      'token': match.group(), 'blocking': False})
    # Recognition is deliberately conservative; this is a review cue, not an
    # exhaustive named-entity detector or a determination of pronunciation.
    unpointed = []
    source_offsets = []
    for offset, char in enumerate(source):
        if not MARK_RE.fullmatch(char):
            unpointed.append(char)
            source_offsets.append(offset)
    for match in NAME_RE.finditer(''.join(unpointed)):
        low = source_offsets[match.start(1)]
        high = source_offsets[match.end(1) - 1] + 1
        while high < len(source) and MARK_RE.fullmatch(source[high]):
            high += 1
        flags.append({'code': 'possible_proper_name', 'offset': low,
                      'token': source[low:high], 'blocking': False})
    reading = ''.join(readings)
    omissions = {item['source_offset'] for item in normalizations}
    expected = ''.join(char for offset, char in enumerate(source)
                       if offset not in omissions and not MARK_RE.fullmatch(char))
    if strip_marks(reading) != expected:
        raise ValueError('Phonetic input changes an unrecorded source character.')
    return {'text': output, 'transliteration_input': reading,
            'phonetic_normalization': normalizations, 'flags': flags, 'added': added}


def split_source(text: str, limit: int) -> list[tuple[int, str]]:
    parts = []
    start = 0
    while start < len(text):
        end = min(start + limit, len(text))
        if end < len(text):
            whitespace = list(re.finditer(r'\s+', text[start:end]))
            if whitespace:
                end = start + whitespace[-1].end()
            else:
                raise ValueError('One source token exceeds the request character limit.')
        parts.append((start, text[start:end]))
        start = end
    return parts or [(0, '')]


def request_groups(records: list[dict], field: str, limit: int):
    group, length = [], 0
    for index, record in enumerate(records):
        text = record[field]
        for part_index, (source_start, part) in enumerate(split_source(text, limit)):
            separator = 2 if group else 0
            if group and length + separator + len(part) > limit:
                yield group
                group, length, separator = [], 0, 0
            start = length + separator
            group.append({'record_index': index, 'part': part_index, 'source_start': source_start,
                          'start': start, 'end': start + len(part), 'text': part})
            length = start + len(part)
    if group:
        yield group


class NakdanClient:
    def __init__(self, args):
        self.args = args
        self.cache = Path(args.cache)
        self.last_request = 0.0
        self.calls, self.cache_hits = 0, 0

    def get(self, source: str) -> tuple[dict, str]:
        payload = {'task': 'nakdan', 'data': source, 'genre': self.args.genre,
                   'addmorph': True, 'keepmetagim': True, 'keepqq': True,
                   'matchpartial': True, 'nodageshdefmem': False, 'patachma': False,
                   'useTokenization': True}
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
        key = digest(self.args.endpoint.encode() + b'\n' + encoded)
        path = self.cache / f'{key}.json.gz'
        if path.exists():
            with gzip.open(path, 'rt', encoding='utf8') as handle:
                cached = json.load(handle)
            self.cache_hits += 1
            return cached['response'], key
        for attempt in range(self.args.retries):
            delay = self.args.delay - (time.monotonic() - self.last_request)
            if delay > 0:
                time.sleep(delay)
            request = Request(self.args.endpoint, data=encoded, method='POST', headers={
                'Content-Type': 'application/json', 'Accept': 'application/json',
                'User-Agent': 'SourceFaithfulVocalization/1.0'})
            try:
                self.last_request = time.monotonic()
                with urlopen(request, timeout=self.args.timeout) as result:
                    response = json.load(result)
                self.calls += 1
                # Validate the public service's response contract before caching.
                if not isinstance(response, dict) or not isinstance(response.get('data'), list):
                    raise ValueError('Unexpected Nakdan response; refusing to invent niqqud.')
                self.cache.mkdir(parents=True, exist_ok=True)
                temporary = path.with_suffix(f'.{id(self)}.tmp')
                with gzip.open(temporary, 'wt', encoding='utf8') as handle:
                    json.dump({'endpoint': self.args.endpoint, 'genre': self.args.genre,
                               'request_sha256': key, 'fetched_at': datetime.now(timezone.utc).isoformat(),
                               'response': response}, handle, ensure_ascii=False)
                temporary.replace(path)
                return response, key
            except HTTPError as error:
                if error.code not in (429, 500, 502, 503, 504) or attempt + 1 == self.args.retries:
                    raise
                retry_after = error.headers.get('Retry-After', '')
                time.sleep(min(30, max(2 ** (attempt + 1), float(retry_after) if retry_after.isdigit() else 0)))
            except (URLError, TimeoutError, ConnectionError):
                if attempt + 1 == self.args.retries:
                    raise
                time.sleep(min(15, 2 ** (attempt + 1)))
        raise RuntimeError('Request retry limit reached.')


def read_records(path: Path) -> list[dict]:
    raw = path.read_text(encoding='utf8')
    if not raw.strip():
        return []
    if raw.lstrip().startswith('['):
        return json.loads(raw)
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed['records'] if 'records' in parsed else [parsed]
    except json.JSONDecodeError:
        pass
    return [json.loads(line) for line in raw.splitlines() if line.strip()]


def write_records(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f'.{time.time_ns()}.tmp')
    with temporary.open('w', encoding='utf8') as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + '\n')
    temporary.replace(path)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--field', default='text')
    parser.add_argument('--cache', default=str(ROOT / 'work/transliteration/cache/nakdan'))
    parser.add_argument('--endpoint', default=ENDPOINT)
    parser.add_argument('--genre', default='rabbinic', choices=['rabbinic', 'modern', 'medievalpoetry'])
    parser.add_argument('--batch-chars', default=4500, type=int)
    parser.add_argument('--delay', default=1.0, type=float)
    parser.add_argument('--timeout', default=45.0, type=float)
    parser.add_argument('--retries', default=3, type=int)
    parser.add_argument('--limit', type=int)
    parser.add_argument('--max-service-errors', default=3, type=int)
    args = parser.parse_args(argv)
    if args.input.resolve() == args.output.resolve():
        parser.error('Input and output must be separate files.')
    if not 100 <= args.batch_chars <= 9000:
        parser.error('--batch-chars must be between 100 and 9000.')
    records = read_records(args.input)
    if args.limit is not None:
        records = records[:args.limit]
    seen = set()
    for record in records:
        identity = record.get('id', record.get('segment_id'))
        if identity is None or identity == '' or str(identity) in seen:
            parser.error('Every record needs a unique stable id or segment_id.')
        seen.add(str(identity))
        if not isinstance(record.get(args.field), str):
            parser.error(f'{identity}: missing string field {args.field!r}')
    client = NakdanClient(args)
    outputs = [{**record, 'source_text': record[args.field], 'vocalized_text': '',
                'transliteration_input': '', 'phonetic_normalization': [],
                'phonetic_normalization_rule': MATER_RULE, 'phonetic_normalization_status': 'draft',
                'vocalization_status': 'draft', 'needs_proofreading': True,
                'proofreading_status': 'pending', 'vocalization_flags': [],
                'vocalization_provenance': 'machine_generated_nakdan_rabbinic_draft',
                'vocalization_engine': 'Dicta NakdanPro public service',
                'vocalization_genre': args.genre,
                'source_sha256': digest(record[args.field]), 'input_marks_preserved': True,
                'consonants_preserved': True, 'added_marks_count': 0,
                'vocalization_request_keys': []} for record in records]
    failures = 0
    groups = list(request_groups(records, args.field, args.batch_chars))
    for group_index, group in enumerate(groups):
        submitted = '\n\n'.join(part['text'] for part in group)
        failure, key = None, None
        try:
            if failures >= args.max_service_errors:
                raise RuntimeError('Service failures exceeded limit; pending passages need a resume.')
            if HEBREW_RE.search(submitted):
                response, key = client.get(submitted)
                tokens = render_response(submitted, response)
            else:
                tokens = [{'start': 0, 'end': len(submitted), 'source': submitted,
                           'output': submitted, 'flags': [], 'added': 0}]
        except (HTTPError, URLError, TimeoutError, ConnectionError, ValueError, RuntimeError) as error:
            failure = f'{type(error).__name__}: {error}'
            failures += 1
        for part in group:
            out = outputs[part['record_index']]
            if failure:
                extracted = {'text': part['text'], 'added': 0, 'flags': [
                    {'code': 'vocalization_service_error', 'offset': 0, 'detail': failure, 'blocking': True}]}
            else:
                try:
                    extracted = extract_span(tokens, part['start'], part['end'], part['text'])
                except ValueError as error:
                    extracted = {'text': part['text'], 'added': 0, 'flags': [
                        {'code': 'provider_alignment_error', 'offset': 0, 'detail': str(error), 'blocking': True}]}
            out['vocalized_text'] += extracted['text']
            out['transliteration_input'] += extracted.get('transliteration_input', extracted['text'])
            out['phonetic_normalization'].extend({**item, 'source_offset': item['source_offset'] + part['source_start'],
                                                  'vocalization_request_key': key}
                                                 for item in extracted.get('phonetic_normalization', []))
            out['added_marks_count'] += extracted['added']
            out['vocalization_flags'].extend({**flag, 'offset': flag['offset'] + part['source_start']}
                                            for flag in extracted['flags'])
            if key:
                out['vocalization_request_keys'].append(key)
            if failure:
                out['vocalization_status'] = 'blocked'
                out['phonetic_normalization_status'] = 'blocked'
            elif any(flag['blocking'] for flag in extracted['flags']) and out['vocalization_status'] != 'blocked':
                out['vocalization_status'] = 'needs_attention'
            if any(flag['code'] in ('ambiguous_mater_annotation', 'phonetic_alignment_error') for flag in extracted['flags']):
                out['phonetic_normalization_status'] = 'blocked'
        print(json.dumps({'group': group_index + 1, 'groups': len(groups), 'calls': client.calls,
                          'cache_hits': client.cache_hits, 'service_failures': failures,
                          'last_ids': [records[p['record_index']].get('id', records[p['record_index']].get('segment_id')) for p in group],
                          'error': failure}, ensure_ascii=False), file=sys.stderr, flush=True)
    for out in outputs:
        if strip_marks(out['vocalized_text']) != strip_marks(out['source_text']):
            raise AssertionError(f"Source preservation failed for {out.get('id')}")
        omissions = {item['source_offset'] for item in out['phonetic_normalization']}
        expected = ''.join(char for offset, char in enumerate(out['source_text'])
                           if offset not in omissions and not MARK_RE.fullmatch(char))
        if strip_marks(out['transliteration_input']) != expected:
            raise AssertionError(f"Unrecorded phonetic source change for {out.get('id')}")
    write_records(args.output, outputs)
    summary = {'records': len(outputs), 'groups': len(groups), 'service_calls': client.calls,
               'cache_hits': client.cache_hits, 'service_failures': failures,
               'statuses': dict(Counter(out['vocalization_status'] for out in outputs)),
               'flag_counts': dict(Counter(flag['code'] for out in outputs for flag in out['vocalization_flags'])),
               'phonetic_normalizations': sum(len(out['phonetic_normalization']) for out in outputs),
               'output': str(args.output), 'review_status': 'draft, contextual proofreading pending'}
    args.output.with_suffix(args.output.suffix + '.summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(summary, ensure_ascii=False), file=sys.stderr)
    return 1 if any(out['vocalization_status'] == 'blocked' for out in outputs) else 0


if __name__ == '__main__':
    raise SystemExit(main())
