# Hebrew text workflows

Reusable workflows for Hebrew OCR review, niqqud, spoken roshei tevot, Charles Loder transliteration, English name review and printable Google Sheets.

The reading pass follows customary spoken usage. Familiar names include Rambam, Rashi, Taz, Shach and Chazal. Phrase abbreviations receive contextual readings, including שו״ע as שולחן ערוך. The agent chooses supported pronunciations and flags doubtful readings. The pronunciation decision happens during vocalization, before transliteration.

## Run the offline example

Use Python 3.11 or newer and Node.js 18 or newer. The example sentences and English snapshots were independently authored for this repository.

```sh
python3 scripts/run_demo.py --config examples/project.json
python3 -m unittest discover -s tests -v
python3 scripts/vocalize_test.py
node scripts/transliterate_test.mjs
python3 scripts/check_public_tree.py
```

The demo writes a reviewed JSONL file, OCR comparison candidates, native Sheets request plans and a blank Legal template under the ignored work directory. It uses zero provider requests and zero native Sheet writes. The example configuration identifies each input explicitly.

## Process a document

Put source documents and generated material under the ignored inputs and work directories. Input JSONL records require unique stable `id` values and `source_text`. Keep the original input and each stage's output as separate files. A supplied digital transcription can enter at the passage-preparation step.

Copy examples/document.json to a local project configuration and set its document paths, page range and layout. The stage runner resolves paths relative to that configuration. Each stage is explicit, including provider calls and review inputs.

```sh
python3 scripts/run_workflow.py --config examples/document.json --stage local-ocr --dry-run
python3 scripts/run_workflow.py --config examples/document.json --stage local-ocr
```

The other stage names are google-ocr, compare, prepare, vocalize, readings, transliterate, template, sheets and english. Save image-checked canonical text before prepare, reviewed occurrence decisions before readings, native destination metadata before sheets and current English review snapshots before english. The direct commands below expose each stage independently.

For a scanned PDF, local OCR uses Poppler and Tesseract with Hebrew language data. Two-up page layouts also require Pillow. Configure `--layout single` or `--layout two_up` for the supplied PDF. Source page numbers and bounding boxes are retained in the record metadata.

```sh
python3 scripts/ocr_pdf.py --pdf inputs/document.pdf --out work/local-ocr
python3 scripts/google_vision_ocr.py --pdf inputs/document.pdf --out work/google-ocr
python3 scripts/compare_ocr.py --primary work/local-ocr/records.jsonl --secondary work/google-ocr/records.jsonl --output work/ocr-comparison.jsonl
```

Google Vision uses an API key from `GOOGLE_VISION_API_KEY` or existing Google Application Default Credentials through gcloud. The helper computes the supplied PDF's hash and page count. Successful pages are cached independently and verified on resume. Credentials remain in local configuration.

Review OCR differences against the page images and save corrected literal records to work/canonical.jsonl. Keep engine output and source evidence available locally. OCR agreement provides a review cue. Source images establish the transcription.

```sh
python3 scripts/prepare_records.py --input work/canonical.jsonl --output work/passages.jsonl
python3 scripts/vocalize_batch.py --input work/passages.jsonl --field source_text --output work/vocalized.jsonl
```

Passage preparation splits long records at whitespace while preserving exact source spans and stable parent linkage. Its default limit is 350 source characters. Choose a smaller limit when print preview shows long translated rows. Perform passage preparation before reviewing occurrence offsets.

The vocalizer retains original characters and existing marks, adds compatible draft niqqud and records source-preserving phonetic metadata. Its optional live rabbinic service is Dicta NakdanPro. Provider failures retain flagged source text and support a cached retry. [Dicta tools](https://dicta.org.il/tools)

## Review spoken forms

Install the skill directory at your Codex skills location or invoke its instructions from this checkout. The agent reviews complete source contexts and the pronunciation profile. The dictionary supplies reviewed familiar forms and evidence. Each applied decision must bind to the current source hash and exact occurrence span.

The decision contract supports phrase expansion, retained familiar acronyms with `spoken_reading`, optional `english_label` and explicit manual review. The helper records the reading policy and dictionary hash. A changed policy invalidates prior policy-bound decisions. Its pronunciation input omits abbreviation marks only in reviewed spoken-acronym spans. Ordinary quotation punctuation and recorded silent-letter behavior are preserved. Literal or numeric homographs use an explicit `usage` value. A phrase meaning that differs from the profile requires a documented `contextual_alternative`, reason and evidence.

Prepare work/reading-decisions.jsonl using the review agent. Every production decision includes the selected dictionary's exact hash and reading policy version. The dictionary-bound entrypoint validates the selected spoken form and English label before applying the occurrence. Its output feeds Charles through `transliteration_input`.

```sh
python3 scripts/apply_readings.py --records work/vocalized.jsonl --decisions work/reading-decisions.jsonl --dictionary profiles/spoken-readings.json --output work/readings.jsonl
```

```sh
node scripts/transliterate_batch.mjs --input work/readings.jsonl --output work/transliterated.jsonl --schema profiles/charles-schema.json
```

The supplied profile contains the configured pronunciation mappings and cleanup rules. A project can supply its own profile through `--schema`. Charles Loder's bundled engine is version 2.11.0. Engine, wrapper, schema, reading policy and dictionary identifiers participate in reproducible output and cache checks.

## Create the printable Google Sheet

Create a blank Legal landscape template, then import it into Google Drive as a native Google Sheet.

```sh
python3 scripts/build_sheets.py --out work/sheets --template-only
```

Read the imported Sheet's native metadata and save it locally to work/sheet-metadata.json. It must identify the Book, Hebrew Review, Source & Review and Schema tabs. Native sheet IDs come from that destination metadata. The fixture metadata contains demonstration IDs.

Generate requests with the current reading policy and dictionary hash from the reading output.

```sh
python3 scripts/build_sheets.py --input work/transliterated.jsonl --metadata work/sheet-metadata.json --out work/sheets --policy-version spoken-usage-v1 --dictionary-hash HASH_FROM_READING_OUTPUT
```

Review layout.json and the bounded body batches before applying them through an authorized Sheets connector or API. Layout applies before body batches. Source and reading formulas include source, vocalization, policy and dictionary validity guards. Repeated batches write the same exact cells.

The Book tab prints Hebrew, transliteration and English. Hebrew Review has hidden literal OCR in A, vocalized source in B, spoken Hebrew in C and review information in D. Both visible tabs use three 403-pixel columns. The blank template supplies US Legal landscape page settings at 14 × 8.5 inches with fit-to-width printing. Native request payloads supply content and formatting.

Open native print preview after applying requests. Verify Legal paper, landscape orientation, three visible columns, Hebrew shaping, review flags, the longest rows and table passages. The print-checks report identifies oversized rows requiring shorter source passage units. Read the written cells back and compare them with the prepared requests, including effective formula results.

## Review English name labels

The hidden source tab uses a native `GOOGLETRANSLATE` formula per passage. Reviewed English overrides occupy K and displayed English selects K or the machine result. Export a bounded current snapshot with source text, current machine English, current override and accepted `reading_edits`.

Prepare source-linked English name decisions with exact English spans. The helper checks source and English hashes and requires each replacement to match an accepted reading's English label. It archives superseded overrides and can prepare K-only updates against a fresh live snapshot.

```sh
python3 scripts/review_english_names.py --input work/english-snapshot.jsonl --decisions work/english-name-decisions.jsonl --output work/english-reviewed.jsonl --archive work/english-overrides-archive.json
```

Add `--live work/fresh-live-snapshot.jsonl --source-sheet-id NATIVE_ID --payload work/english-updates.json` to prepare native writes. Use the zero-based `source_row_index` for subsets whose source row differs from list position. Before writing, the helper rechecks the source, reviewed override and active English snapshot. Surrounding translated wording is retained exactly.

## Public release

Public files comprise workflow code, generic profiles, review instructions and independently authored fixtures. Document scans, OCR, translations, review decisions, source evidence, Sheet links and working exports belong in private working storage.

Before publication, run the public-tree check. An optional local `--private-records` input checks for long overlapping Hebrew sequences while keeping the comparison input outside the repository. After the initial commit, `--history` checks every reachable source blob as well.

This workflow code uses the MIT license. Charles Loder's copyright and MIT notice are retained in scripts/transliterate_LICENSE.md. [MIT license](https://opensource.org/license/mit)
