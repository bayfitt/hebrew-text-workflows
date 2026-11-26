#!/bin/sh
set -eu
cd "$(dirname "$0")"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
for mode in fixed adaptive; do
  python3 build.py --input example.json --out "$tmp/$mode" --mode "$mode"
  pdf="$tmp/$mode/book.pdf"
  pdfinfo "$pdf" | grep -Eq '^Pages: +3$'
  pdfinfo "$pdf" | grep -Eq '^Page size: +1008 x 612 pts'
  pdftotext -layout -f 2 -l 2 "$pdf" "$tmp/left"
  pdftotext -layout -f 3 -l 3 "$pdf" "$tmp/right"
  grep -q 'Tomorrow morning' "$tmp/left"
  ! grep -q 'Notes to this spread' "$tmp/left"
  grep -q 'Note from the left page' "$tmp/right"
  grep -q 'Note from the right page' "$tmp/right"
  ! grep -E 'Missing character:|Overfull' "$tmp/$mode/book.log"
done
printf 'PASS: both render modes, Legal geometry, page ordering and right-side spread notes\n'
