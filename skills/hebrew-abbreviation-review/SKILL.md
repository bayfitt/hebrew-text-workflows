---
name: hebrew-abbreviation-review
description: Review Hebrew and Aramaic roshei tevot in context and prepare their customary spoken readings during vocalization, with familiar names, phrase expansions and pronunciation review flags.
---

# Spoken Hebrew abbreviation review

Resolve the reading a person would use aloud. Read the complete sentence, source location and adjoining reference before choosing a form.

## Reading policy

- Use familiar forms such as Rambam, Ramban, Rashi, Taz, Shach and Chazal. Supply their reviewed Hebrew vowels and the project's customary English label.
- Read phrase abbreviations and shortened titles according to usage. For example, אע״פ becomes אף על פי and שו״ע is read שולחן ערוך. Resolve ר״ת, ע״ש and similar forms from their sentence and citation.
- Select pronunciation variants using the configured reading profile and evidence. Give uncertain forms a concrete review reason and retain their literal spelling.
- Preserve attached articles, conjunctions and prepositions. Review their vowels in the complete phrase.
- Identify numerals, dates, quotations and footnote markers from context. A year such as ה׳תש״ע has a different function from a divine-name abbreviation. In an established divine-name context, the reading may use השם.
- Confirm bibliographic identity when it affects the reading. Retain source evidence about uncertain identities and pronunciation variants.

Check source images when letters or punctuation may be OCR errors. Table headers and cell boundaries can determine a citation's referent. Route source corrections through the project's source-review step and independently check reconstructed tables before using them as reading evidence.

Automated suggestions provide candidate meanings for contextual review. The accepted reading should follow customary usage in the project. Optional proposals can be collected from [Dicta's rabbinic abbreviation tool](https://abbreviation.dicta.org.il/).

## Vocalization pass

Keep literal source and source vocalization recoverable. Put the reviewed spoken reading in its derived field or review column. In a configured Hebrew review sheet, hidden A may hold literal OCR, B the vocalized source, C the spoken reading and D review information.

Resolve spoken acronyms during vocalization. Record exact source spans, reviewed vowels and the reading-policy version. For a retained acronym, `spoken_reading` has the source token's exact letters and punctuation with its reviewed vowels. Phrase replacements use `expansion` and optional `vocalized_expansion`.

The helper constructs Charles input from the reviewed reading and records omitted acronym marks. Source and displayed Hebrew keep their punctuation. Existing documented silent-matres adjustments remain available outside edited spans. Follow the project's configured pronunciation schema and validate necessary Charles wrapper or engine changes against surrounding text.

An English label such as Rambam identifies the source-linked acronym. Review the current machine or edited English in context before applying name-label changes. Preserve the original translation and exact comparison snapshot in the project's review records.

## Apply and verify

Use [the decision contract](references/decisions.md) and the workflow repository's `scripts/apply_readings.py` front end for dictionary-bound application. It validates familiar forms against the configured dictionary before invoking the exact-span helper. Exact hashes and Unicode spans bind each decision to its current source. Include policy and dictionary versions when applying a versioned review. Re-review decisions when their source context, policy or dictionary changes.

For an installed skill, locate the full workflow checkout through the active project's configuration or its configured tools directory. The checkout supplies the dictionary and validation front end. Resolve those paths against that checkout. Setup and the offline example are documented in the public workflow repository. [Hebrew text workflows](https://github.com/bayfitt/hebrew-text-workflows)

Inspect source preservation, accepted spans, derived pronunciation, visible flags and rendered Hebrew. Existing printed marks stay in the source layer. Doubtful pronunciation remains visible for follow-up. A permitted independent reviewer can check large batches against their passages and configured reading profile.
