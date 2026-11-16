#!/usr/bin/env python3
"""Resumable local PDF OCR with retained images, TSV and exact draft paragraphs."""
import argparse
import csv
import io
import json
import os
from pathlib import Path
import subprocess

from workflow_io import digest, parse_pages, pdf_page_count, write_json, write_records


def paragraphs(tsv, page, side, source_hash, image):
    words = [row for row in csv.DictReader(io.StringIO(tsv), delimiter='\t', quoting=csv.QUOTE_NONE)
             if row.get('level') == '5' and row.get('text', '').strip()]
    groups = {}
    for word in words:
        groups.setdefault((int(word['block_num']), int(word['par_num'])), []).append(word)
    records = []
    ordered = sorted(groups.values(), key=lambda group: min(int(word['top']) for word in group))
    for index, group in enumerate(ordered, 1):
        lines = {}
        for word in group:
            lines.setdefault(int(word['line_num']), []).append(word['text'])
        text = ' '.join(' '.join(lines[line]) for line in sorted(lines))
        left = min(int(word['left']) for word in group)
        top = min(int(word['top']) for word in group)
        right = max(int(word['left']) + int(word['width']) for word in group)
        bottom = max(int(word['top']) + int(word['height']) for word in group)
        confidence = sum(float(word['conf']) for word in group) / len(group)
        records.append({'id': f'{source_hash[:12]}-p{page:04}-{side}-p{index:04}',
                        'source_text': text, 'ocr_provider': 'Tesseract',
                        'source': {'pdf_page': page, 'side': side, 'bbox': [left, top, right, bottom],
                                   'source_sha256': source_hash, 'image': str(image)},
                        'ocr_confidence': round(confidence, 2), 'needs_review': ['machine_ocr_draft']})
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pdf', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--pages', default='all')
    parser.add_argument('--layout', choices=['single', 'two_up'], default='single')
    parser.add_argument('--language', default='heb')
    parser.add_argument('--dpi', type=int, default=300)
    parser.add_argument('--tesseract', default='tesseract')
    args = parser.parse_args()
    source_hash = digest(Path(args.pdf).read_bytes())
    pages = parse_pages(args.pages, pdf_page_count(args.pdf))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    version = subprocess.check_output([args.tesseract, '--version'], text=True).splitlines()[0]
    identity = {'source_sha256': source_hash, 'layout': args.layout, 'language': args.language,
                'dpi': args.dpi, 'engine': version}
    cache_key = digest(json.dumps(identity, sort_keys=True))
    all_records = []
    for page in pages:
        folder = out / cache_key[:16] / f'page-{page:04}'
        checkpoint = folder / 'page.json'
        if checkpoint.exists():
            cached = json.loads(checkpoint.read_text())
            if cached['identity'] != identity:
                raise ValueError('OCR checkpoint configuration changed')
            all_records.extend(cached['records'])
            continue
        folder.mkdir(parents=True, exist_ok=True)
        stem = folder / 'page'
        subprocess.run(['pdftoppm', '-f', str(page), '-l', str(page), '-singlefile', '-png',
                        '-r', str(args.dpi), args.pdf, str(stem)], check=True,
                       capture_output=True, timeout=180)
        image = stem.with_suffix('.png')
        images = [('single', image)]
        if args.layout == 'two_up':
            from PIL import Image
            with Image.open(image) as spread:
                midpoint = spread.width // 2
                images = []
                for side, bounds in [('right', (midpoint, 0, spread.width, spread.height)),
                                     ('left', (0, 0, midpoint, spread.height))]:
                    target = folder / f'{side}.png'
                    spread.crop(bounds).save(target)
                    images.append((side, target))
        records = []
        for side, target in images:
            result = subprocess.run([args.tesseract, str(target), 'stdout', '-l', args.language,
                                     '--psm', '3', 'tsv'], capture_output=True, text=True,
                                    timeout=180, env={**os.environ, 'OMP_THREAD_LIMIT': '1'})
            if result.returncode:
                raise RuntimeError('Tesseract failed. Check the configured language data.')
            (folder / f'{side}.tsv').write_text(result.stdout)
            records.extend(paragraphs(result.stdout, page, side, source_hash, target))
        write_json(checkpoint, {'identity': identity, 'records': records})
        all_records.extend(records)
    write_records(out / 'records.jsonl', all_records)
    print(json.dumps({'pages': len(pages), 'records': len(all_records), 'source_sha256': source_hash}))


if __name__ == '__main__':
    main()
