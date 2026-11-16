#!/usr/bin/env node
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, writeFileSync, readdirSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { resolve, dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadEngine, main } from './transliterate_batch.mjs';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const schema = join(root, 'profiles/charles-schema.json');
const engine = loadEngine(schema);
const samples = new Map([
  ['שָׁלוֹם', 'sholōm'],
  ['רַמְבַּם', 'rambam'],
  ['רַשִׁי', 'rashi'],
  ['טַז', 'ṭaz'],
  ['שַׁךְ', 'shach'],
]);
for (const [source, expected] of samples) {
  assert.equal(engine.run(source), expected);
  assert.equal(engine.run(source), engine.run(source));
  assert.equal(engine.run([[source]])[0][0], expected);
}
assert.equal(engine.run(''), '');
assert.equal(engine.run(null), '');
assert.deepEqual(JSON.parse(JSON.stringify(engine.run([['רַמְבַּם', ''], [null, 'רַשִׁי']]))), [['rambam', ''], ['', 'rashi']]);

const directory = mkdtempSync(join(tmpdir(), 'hebrew-workflow-test-'));
try {
  const input = join(directory, 'input.jsonl');
  const output = join(directory, 'output.jsonl');
  const cache = join(directory, 'cache');
  const record = { id: 'synthetic', source_text: 'רמב״ם', transliteration_input: 'רַמְבַּם',
    reading_policy_version: 'first', dictionary_sha256: 'one',
    reading_edits: [{ start_char: 0, end_char: 5 }],
    vocalization_flags: [{ code: 'acronym_or_abbreviation_reading', offset: 0 }] };
  writeFileSync(input, JSON.stringify(record));
  assert.equal(await main(['--input', input, '--output', output, '--schema', schema, '--cache', cache]), 0);
  const result = JSON.parse(readFileSync(output, 'utf8'));
  assert.equal(result.transliteration, 'rambam');
  assert.equal(result.transliteration_status, 'draft');
  assert.equal(result.transliteration_flags.includes('unresolved_acronym_or_abbreviation_reading'), false);
  record.reading_policy_version = 'second';
  writeFileSync(input, JSON.stringify(record));
  await main(['--input', input, '--output', output, '--schema', schema, '--cache', cache]);
  assert.equal(readdirSync(cache).length, 2);
  record.reading_edits = [];
  writeFileSync(input, JSON.stringify(record));
  await main(['--input', input, '--output', output, '--schema', schema, '--cache', cache]);
  assert.equal(JSON.parse(readFileSync(output, 'utf8')).transliteration_status, 'needs_attention');
} finally {
  rmSync(directory, { recursive: true, force: true });
}
console.log(JSON.stringify({ passed: true, scalar_array_samples: samples.size, reading_policy_cache_test: true }));
