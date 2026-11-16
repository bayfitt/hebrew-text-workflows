# Reviewed reading decisions

Input records are JSON Lines with a unique `id`, literal `source_text` and optional `vocalized_text`. An existing `transliteration_input` may carry documented silent-matres omissions in `phonetic_normalization`.

Each occurrence uses Python Unicode code-point offsets with an exclusive end. The helper checks the source hash, literal token, complete Hebrew mark clusters and overlapping accepted edits.

## Familiar spoken acronym

Use `retain` with reviewed vowels in `spoken_reading`. Its unpointed characters must exactly match `raw_token`, including its quote glyphs and prefixes.

```json
{
  "occurrence_id": "sample-1:name-1",
  "id": "sample-1",
  "source_passage_sha256": "SHA-256 of UTF-8 source_text",
  "start_char": 0,
  "end_char": 5,
  "raw_token": "רמב״ם",
  "decision": "retain",
  "expansion": null,
  "spoken_reading": "רַמְבַּ״ם",
  "english_label": "Rambam",
  "reason": "The sentence uses the familiar spoken name.",
  "evidence": "Local context and the configured reading profile.",
  "reading_policy_version": "spoken-usage-v1",
  "dictionary_sha256": "SHA-256 of the selected dictionary file"
}
```

This yields displayed Hebrew `רַמְבַּ״ם` and Charles input `רַמְבַּם`. The existing pronunciation schema determines the Latin result.

## Phrase expansion and held forms

Use `expand` with a nonempty unpointed `expansion`, contextual `reason` and `evidence`. A supplied `vocalized_expansion` must have the same unpointed characters as the expansion. For example, אע״פ can expand to אף על פי with אַף עַל פִּי as its reviewed vocalization.

Use `retain` with a null expansion for a literal quotation, numeral or other retained token. Use `manual` with a null expansion and a concrete reason for an unresolved reading. Both retain their source spelling. A held handwriting notice uses `reading_held: true` on its input record.

When a policy version and dictionary hash are requested, every decision carries those exact values. This also applies to literal and manual decisions. Legacy callers can omit the policy arguments and use the original decision format.

## Application

Optional provider proposals can be collected through this skill's `scripts/propose_expansions.py`. The contextual review supplies accepted readings and versions before application.

Run the dictionary-bound front end from the workflow repository root. It computes the dictionary hash, checks the policy and validates recognized forms before invoking this skill's helper. A full-name expansion for a familiar acronym is rejected by that validation.

```bash
python3 scripts/apply_readings.py \
  --records records.jsonl \
  --decisions decisions.jsonl \
  --dictionary profiles/spoken-readings.json \
  --output reviewed.jsonl
```

The lower-level importable interface is `apply(records, decisions, *, policy_version=None, dictionary_sha256=None)`. Its version and span checks supplement the dictionary validation performed by the front end. Legacy callers can still invoke `scripts/apply_expansions.py` directly with their validated unversioned decisions.

Output includes the original fields and these derived fields.

- `expanded_source_text` and `expanded_vocalized_text` retain the existing helper interface.
- `expansion_edits` contains phrase expansions. `reading_edits` includes these and retained acronyms with reviewed spoken vowels.
- `transliteration_input` is the pronunciation input for Charles. `source_transliteration_input` preserves its baseline so a retry on a derived record is repeatable.
- `reading_normalizations` records source and output offsets for inherited outside-span matres omissions and accepted internal spoken-acronym mark omissions. Exterior quotation marks survive even when they occur inside the accepted source span.
- `reading_policy_version`, `dictionary_sha256` and `reading_status` record the applied review. Status is `draft`, `needs_attention` or `held`.

The helper preserves literal source and source vocalization. It rejects unrecorded base-character changes in a supplied phonetic input. A replacement supersedes previous phonetic annotations inside its exact accepted span.

Run Charles on the resulting `transliteration_input`. A changed versioned pronunciation clears an inherited Latin candidate and marks it `pending` until that step completes.

Run the regression checks from the skill directory.

```bash
python3 -m unittest discover -s tests -v
```
