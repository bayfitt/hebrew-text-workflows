# Rebuild a trilingual Legal print proof

The versioned JSON snapshot is the input, not the PDF or generated TeX. Export your reviewed Sheet to a private snapshot and retain the date, source edition/revision, snapshot hash and license/attribution separately with your project. Keep source text and published translations within the rights you have. This renderer never calls Sheets or edits it.

## Debian 13 reference build

```sh
sudo apt-get install --no-install-recommends texlive-luatex texlive-latex-recommended texlive-lang-other fonts-noto-core fonts-liberation poppler-utils
sh typeset/smoke-test.sh
python3 typeset/build.py --input typeset/example.json --out work/typeset-example
```

Reference environment: Debian 13.8 (amd64); LuaHBTeX 1.18.0; packages and versions are recorded in `debian-13.lock`. Use a Debian snapshot matching that package set for archival reproduction. Keep the resolved font files' SHA-256 and print supplier profile alongside a release. Updated packages may change line breaking; rebuild and proof again after upgrades. PDF bytes can differ because of build metadata.

Noto Sans Hebrew and its punctuation fallback (Noto Sans) are supplied under the SIL Open Font License by Debian's fonts-noto-core. The small synthetic example builds with upright Liberation Serif (also OFL). If you own a properly licensed Times New Roman installation, install its font files for the account running LuaLaTeX, run `fc-cache -f`, and invoke the renderer with `--require-tnr`. Verify the generated cover and PDF font list with `pdffonts`. Times New Roman is proprietary, is not bundled, and a copy is not implied by this project. Check your font's embedding permissions before distributing the PDF.

## Version 1 input

The JSON object has a `title`, `schema_version: 1`, a `passages` array with unique stable `id` strings plus `he` (pointed), `roman`, `en`, and optional `note`, and a `chapters` array. Each chapter has a display `label` and a `first_id` pointing to a passage. The first map entry must match the first passage; entries and passages must already be in verified edition order. Use an edition-specific source-check step to detect missing/inserted passages and to distinguish real chapter headings from segment continuations or appendix subheadings. This tool does not infer hierarchy or validate a source edition for you. Model stand-alone appendices as map entries; nested headings are not yet rendered by this version. Text fields are plain Unicode, not TeX.

## What the build does

Body columns are physically Hebrew on the left (text reads RTL), romanization in the center, English on the right. Landscape US Legal is 14 × 8.5 in. The title/contents page is page 1; spreads are physical even-left/odd-right and notes from both pages appear on the odd page. Spread notes are custom numbered apparatus, not native individual-page footnotes. Widths are selected from a bounded set using TeX's measured heights, consistent gutters and a visual-jitter penalty. `--mode fixed` gives a comparison with the same sizes and source. The generated PDF, page layout JSON and logs go under the specified output directory. Never edit generated TeX or PDF to change source text.

The allocator keeps each passage rectangular and intact; if one cannot fit, manually identify matching subparagraph boundaries in all three columns, retain parent/child IDs, and rerun. An empty last right-side body can be intentional; it still carries any notes from the left page. This is for proofs, not printer-approved PDF/X. Print representative pages duplex at 100% to check binding, margins, outside folios, niqqud, punctuation direction, notes and density. Reflow-test any text or font change. This version is an excerpt-oriented tool; benchmark and proof a full edition before production.
