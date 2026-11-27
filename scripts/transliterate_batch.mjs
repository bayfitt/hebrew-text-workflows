#!/usr/bin/env node
/** Deterministic configured Hebrew transliteration.
 * Charles Loder hebrew-transliteration 2.11.0 is MIT licensed.
 * See transliterate_LICENSE.md for its attribution.
 */
import { readFileSync, writeFileSync, renameSync, mkdirSync, existsSync } from 'node:fs';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { dirname, resolve, join } from 'node:path';
import { createHash } from 'node:crypto';
import vm from 'node:vm';

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, '..');
export const sha256 = value => createHash('sha256').update(value).digest('hex');

export function readRecords(path) {
  const raw = readFileSync(path, 'utf8');
  const trimmed = raw.trim();
  if (!trimmed) return [];
  if (trimmed.startsWith('[')) return JSON.parse(trimmed);
  try {
    const parsed = JSON.parse(trimmed);
    if (Array.isArray(parsed.records)) return parsed.records;
    if (parsed && typeof parsed === 'object' && ('id' in parsed || 'segment_id' in parsed)) return [parsed];
  } catch {}
  return raw.split(/\r?\n/).filter(line => line.trim()).map((line, index) => {
    try { return JSON.parse(line); }
    catch (error) { throw new Error(`Invalid JSON on line ${index + 1}: ${error.message}`); }
  });
}

export function loadEngine(schemaFile, assetDirectory = HERE) {
  const exported = JSON.parse(readFileSync(schemaFile, 'utf8'));
  const rows = Array.isArray(exported) ? exported : (exported.rows ?? exported.values);
  if (!Array.isArray(rows) || rows.length < 91) throw new Error('Schema must contain A1:D100 as {rows:[...]}, {values:[...]}, or a matrix.');
  const schemaRows = rows.slice(2, 72).map(row => (row ?? []).slice(0, 3));
  const cleanupRows = rows.slice(76, 86).map(row => (row ?? []).slice(0, 2));
  const removeApostrophe = rows[89]?.[1];
  const vowels = rows[90]?.[1];
  const settings = { schemaRows, cleanupRows, removeApostrophe, vowels };
  const library = readFileSync(join(assetDirectory, 'transliterate_charles_library.gs'), 'utf8');
  const wrapper = readFileSync(join(assetDirectory, 'transliterate_sheets_wrapper.gs'), 'utf8');
  const context = vm.createContext({});
  vm.runInContext(library, context, { timeout: 5000, filename: 'CharlesHebrew.gs' });
  vm.runInContext(wrapper, context, { timeout: 5000, filename: 'Code.gs' });
  // The original wrapper parses typed rows and performs all house cleanup.
  // Do not normalize, simplify, or replace any of the author's symbols here.
  const run = text => context.CHARLES_TRANSLITERATE(text, schemaRows, cleanupRows, removeApostrophe, vowels);
  // Validate schema parsing even for an empty book.
  run('');
  return {
    run,
    schema_sha256: sha256(JSON.stringify(settings)),
    library_sha256: sha256(library),
    wrapper_sha256: sha256(wrapper),
    schema_source: exported.source ?? schemaFile,
    schema_range: exported.range ?? 'Schema!A1:D100',
    version: 'hebrew-transliteration@2.11.0',
  };
}

function atomicJson(path, value) {
  mkdirSync(dirname(path), { recursive: true });
  const temporary = `${path}.${process.pid}.tmp`;
  writeFileSync(temporary, `${JSON.stringify(value)}\n`, { mode: 0o600 });
  renameSync(temporary, path);
}

function parseArgs(argv) {
  const args = { field: null, schema: join(ROOT, 'profiles/charles-schema.json'), cache: join(ROOT, 'work/transliteration/cache/charles') };
  for (let i = 0; i < argv.length; i++) {
    const key = argv[i];
    if (key === '--require-context-review') { args.requireContextReview = true; continue; }
    if (key === '--help' || key === '-h') { args.help = true; continue; }
    if (!['--input', '--output', '--schema', '--field', '--cache', '--limit'].includes(key) || !argv[i + 1]) throw new Error(`Unknown or missing argument: ${key}`);
    args[key.slice(2)] = argv[++i];
  }
  return args;
}

export async function main(argv = process.argv.slice(2)) {
  const args = parseArgs(argv);
  if (args.help || !args.input || !args.output) {
    console.error('Usage: node scripts/transliterate_batch.mjs --input vocalized.jsonl --output transliterated.jsonl [--schema profiles/charles-schema.json] [--field vocalized_text] [--limit N]');
    return args.help ? 0 : 2;
  }
  if (resolve(args.input) === resolve(args.output)) throw new Error('Input and output must be separate files.');
  const engine = loadEngine(args.schema);
  let records = readRecords(args.input);
  if (args.limit) records = records.slice(0, Number(args.limit));
  const seen = new Set();
  for (const record of records) {
    const id = record.id ?? record.segment_id;
    if (id == null || id === '') throw new Error('Every record needs a stable id or segment_id.');
    if (seen.has(String(id))) throw new Error(`Duplicate record ID: ${id}`);
    seen.add(String(id));
  }
  const results = [];
  let errors = 0, cached = 0;
  for (const record of records) {
    const inputField = args.field ?? (typeof record.transliteration_input === 'string' ? 'transliteration_input' : 'vocalized_text');
    const text = record[inputField];
    const review = record.niqqud_context_review;
    if (args.requireContextReview && (
      review?.policy !== 'contextual-shm-v1' || review.unresolved !== 0 ||
      typeof text !== 'string' || review.reviewed_sha256 !== sha256(text)
    )) throw new Error(`Missing, unresolved or stale niqqud context review: ${record.id}`);
    let result;
    if (typeof text !== 'string') {
      result = { transliteration: '', transliteration_status: 'error', transliteration_error: `Missing string field: ${inputField}` };
    } else if (['error', 'blocked'].includes(record.vocalization_status) || record.phonetic_normalization_status === 'blocked') {
      result = { transliteration: '', transliteration_status: 'blocked', transliteration_error: 'Vocalization or phonetic metadata needs correction before transliteration.' };
    } else {
      const key = sha256(JSON.stringify([engine.version, engine.library_sha256, engine.wrapper_sha256, engine.schema_sha256, text, record.reading_policy_version ?? null, record.dictionary_sha256 ?? null]));
      const cacheFile = join(args.cache, `${key}.json`);
      if (existsSync(cacheFile)) {
        result = JSON.parse(readFileSync(cacheFile, 'utf8'));
        cached++;
      } else {
        try {
          const transliteration = engine.run(text);
          if (typeof transliteration !== 'string') throw new Error('The original wrapper returned a non-string value.');
          const flags = [];
          if (/[\u05d0-\u05ea]/u.test(transliteration)) flags.push('untransliterated_hebrew');
          if (/%%%|\$\$\$|\^\^\^/u.test(transliteration)) flags.push('unresolved_schema_marker');
          result = { transliteration, transliteration_status: flags.length ? 'needs_attention' : 'draft', transliteration_flags: flags };
          atomicJson(cacheFile, result);
        } catch (error) {
          result = { transliteration: '', transliteration_status: 'error', transliteration_error: error.message };
        }
      }
    }
    if (result.transliteration_status === 'error' || result.transliteration_status === 'blocked') errors++;
    const acceptedReadings = record.reading_edits ?? [];
    const unresolvedAcronym = (record.vocalization_flags ?? []).some(flag => {
      if (flag.code !== 'acronym_or_abbreviation_reading') return false;
      return !acceptedReadings.some(edit =>
        Number.isInteger(flag.offset) && edit.start_char <= flag.offset && flag.offset < edit.end_char);
    });
    const readingFlags = unresolvedAcronym ? ['unresolved_acronym_or_abbreviation_reading'] : [];
    const outputFlags = [...new Set([...(result.transliteration_flags ?? []), ...readingFlags])];
    results.push({
      ...record, ...result,
      transliteration_flags: outputFlags,
      transliteration_status: result.transliteration_status === 'draft' && outputFlags.length ? 'needs_attention' : result.transliteration_status,
      transliteration_input_field: inputField,
      transliteration_input_sha256: typeof text === 'string' ? sha256(text) : null,
      needs_proofreading: true,
      proofreading_status: record.proofreading_status ?? 'pending',
      transliteration_engine: engine.version,
      transliteration_schema_sha256: engine.schema_sha256,
      transliteration_library_sha256: engine.library_sha256,
      transliteration_wrapper_sha256: engine.wrapper_sha256,
    });
    if (results.length % 100 === 0) console.error(JSON.stringify({ progress: results.length, total: records.length, errors, cached }));
  }
  mkdirSync(dirname(resolve(args.output)), { recursive: true });
  const temporary = `${args.output}.${process.pid}.tmp`;
  writeFileSync(temporary, results.map(record => JSON.stringify(record)).join('\n') + (results.length ? '\n' : ''), { mode: 0o600 });
  renameSync(temporary, args.output);
  console.error(JSON.stringify({ records: results.length, errors, cached, output: args.output, schema_sha256: engine.schema_sha256 }));
  return errors ? 1 : 0;
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  main().then(code => { process.exitCode = code; }).catch(error => { console.error(error.stack ?? String(error)); process.exitCode = 2; });
}
