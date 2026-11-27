# Book mode: one process, private content

GitHub versions the procedure, review rules, and tooling. The private Google Sheet
is the authority for book content. Keep private manifests, Sheets IDs, source files,
translations, caches, notes and exports out of the checkout. The CLI processes
normalized local checkpoints; it does not call Google, make editorial decisions,
or render a PDF/EPUB. A connector or authorized operator must actually perform
the Sheets operations. Do not create verification inputs by copying the planned
upload: capture them independently from the Sheet.

Run each command as `python3 scripts/book_workflow.py <stage> ...`, using
private paths. Pass JSON arrays or JSONL for row data.

1. **Source.** Capture `source_ref` (unique edition/section/range, independent
   of spreadsheet position), `source_text`, and `source_kind` (`typed` or
   `ocr`; the latter requires `ocr_evidence`). If available, preserve the
   earlier English in `editorial_english`, never in the Google translation
   column. `pin-source --source SOURCE` computes the snapshot hash; place it
   in a private JSON manifest alongside `book_id`, `source_edition`, and
   `source_revision`. Run `plan --manifest MANIFEST --source SOURCE --output PLAN`.
   An unchanged reference keeps its stable ID when rows move; any source edit
   invalidates later checkpoints through the source hash.
2. **Native Google Translate.** In a staging tab with headers on row 1, write
   ID in A, exact Hebrew in B, and the planned native Google formula in C.
   Use formula-capable input for C, not text. Wait for calculation; the
   connector must read the formula (e.g. Sheets `userEnteredValue.formulaValue`)
   and the corresponding effective value. Normalize each result to
   `{id,source_sha256,source_text,formula,value,error}`; put Sheets
   `effectiveValue.errorValue` in `error` when present. Then paste values
   only in a separate frozen range/tab and **read back** the frozen cell:
   `{id,source_sha256,source_text,formula:null,value}`. No formula in the
   frozen cell. Do not fill missing Google data with editorial English.
3. **English review.** Read the Hebrew in context; fix wrong meanings before
   higher-order style, preserve the author's argumentative pace, and record
   the editorial rationale separately. Supply decisions with
   `{id,source_sha256,google_sha256,english,english_note}`; the Google hash
   is SHA-256 of its exact UTF-8 value. Run
   `english --input PLAN --live LIVE --frozen FROZEN --edits EDITS --output ENGLISH`.
4. **Contextual niqqud.** After the English checkpoint, read the Hebrew
   independently, consult the chosen English to cross-check readings, and
   supply `{id,source_sha256,english_sha256,vocalized_text,niqqud_note}`.
   Optional editorial abbreviation work goes in `expanded_text` and
   `expansion_note` with supported existing `vocalization_flags` and
   `reading_edits`. Preserve original Hebrew separately. Run
   `niqqud-audit --input ENGLISH --drafts DRAFTS --output AUDIT`.
   For each reported occurrence, retain audit identity fields and add
   `sense` and `reason`. Then run
   `niqqud --input ENGLISH --drafts DRAFTS --decisions DECISIONS --output POINTED`.
   Its built-in targeted rule handles שם, not all Hebrew ambiguities;
   the editorial checkpoint remains responsible for all other vowels.
5. **Deterministic transliteration.** Run
   `transliterate --input POINTED --cache PRIVATE_CACHE --output TRANSLITERATED`.
   Uses the repository’s pinned Charles Loder engine/schema, no LLM.
   Run `sheet-rows --input TRANSLITERATED --output UPLOAD`; this blocks
   unresolved transliteration flags. Proofread the output against Hebrew.
6. **Sheet authority and exports.** Upload the rows to the private master
   Sheet. Read them back in order, including pinned provenance and all
   editorial columns, normalizing empty cells to empty strings and
   `contextual_notes` from a JSON-encoded cell to an array. Re-export a fresh
   snapshot from the Sheet and validate it against the expected upload with
   `export-input --input UPLOAD --readback READBACK --output VERIFIED`. If
   editors change a row, repeat the relevant review stages and verification.
   Pass only VERIFIED to the PDF/EPUB formatter; renderers should not use
   a staging tab or an earlier local draft.

See `tests/test_book_workflow.py` for a runnable synthetic example with positive
and negative checkpoints. It does not make a live Sheets write or test Google’s
translation service.
