# Iggeres HaShmad: 50-row pilot workflow

This example adapts the existing trilingual renderer to a private review snapshot. It includes no book text, English draft, raw scans, private links, or rendered proof.

The witness is the medieval Hebrew translation in Abraham Geiger's *Moses ben Maimon: Studien* (Breslau, 1850), [HebrewBooks facsimile 26811](https://hebrewbooks.org/26811). In this scan, the letter is PDF pages 3–13, with printed folios 1a–6a. The pilot begins at the first line of the letter proper on PDF page 3 and ends at the Hanukkah example on PDF page 6, folio 2b, body line 30. The lost Judeo-Arabic original is not supplied by this witness. Do not substitute a modern Hebrew or English edition without revisiting attribution and rights.

Keep the scan, source-aligned review data, and renderer outputs in ignored local directories. The two inputs below are the private, reviewed 50-row JSON and the corresponding output of the pinned transliteration step. Prepare English and niqqud independently, reconcile against the Hebrew, and regenerate transliteration after a pointing change. Preserve unresolved variants and source citations separately from the reading text.

```sh
python3 examples/iggeres-hashmad/prepare_proof.py \
  --reviewed inputs/iggeres-hashmad/first50.json \
  --romanized inputs/iggeres-hashmad/transliterated.jsonl \
  --out work/iggeres-hashmad/renderer-input.json
python3 typeset/build.py \
  --input work/iggeres-hashmad/renderer-input.json \
  --out work/iggeres-hashmad/proof
```

This uses the shared US Legal three-column renderer and is not a byte-identical reproduction of the private proof. Visually check the longest Hebrew rows, the facing-page notes, and the unresolved review flags before any release.
