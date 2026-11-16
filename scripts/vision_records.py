"""Convert retained Vision paragraph annotations to source-linked draft records."""
import json
from pathlib import Path


def box_points(box, width, height):
    if box.get('normalizedVertices'):
        return [(p.get('x', 0) * width, p.get('y', 0) * height) for p in box['normalizedVertices']]
    return [(p.get('x', 0), p.get('y', 0)) for p in box.get('vertices', [])]


def records_from_cache(cache, source_hash, pages, layout='single'):
    records = []
    for number in pages:
        entry = json.loads((Path(cache) / f'{number:03}.json').read_text())
        if entry.get('status') != 'success' or entry['source_sha256'] != source_hash:
            raise ValueError('OCR cache belongs to another source or an incomplete response')
        annotation = entry['response'].get('fullTextAnnotation', {})
        paragraph_index = 0
        for page in annotation.get('pages', []):
            width, height = page.get('width', 0), page.get('height', 0)
            for block in page.get('blocks', []):
                for paragraph in block.get('paragraphs', []):
                    text = ' '.join(''.join(symbol.get('text', '') for symbol in word.get('symbols', []))
                                    for word in paragraph.get('words', []))
                    if not text:
                        continue
                    paragraph_index += 1
                    points = box_points(paragraph.get('boundingBox', {}), width, height)
                    side = 'single'
                    if layout == 'two_up':
                        side = 'unknown' if not points else ('right' if sum(p[0] for p in points) / len(points) >= width / 2 else 'left')
                    bbox = [min(p[0] for p in points), min(p[1] for p in points),
                            max(p[0] for p in points), max(p[1] for p in points)] if points else None
                    records.append({'id': f'{source_hash[:12]}-p{number:04}-{side}-vision-{paragraph_index:04}',
                                    'source_text': text, 'ocr_provider': 'Google Cloud Vision',
                                    'source': {'pdf_page': number, 'side': side, 'bbox': bbox,
                                               'source_sha256': source_hash},
                                    'ocr_confidence': paragraph.get('confidence'),
                                    'needs_review': ['machine_ocr_draft'] + (['page_side_unknown'] if side == 'unknown' else [])})
        if not paragraph_index:
            records.append({'id': f'{source_hash[:12]}-p{number:04}-vision-empty',
                            'source_text': annotation.get('text', ''), 'ocr_provider': 'Google Cloud Vision',
                            'source': {'pdf_page': number, 'side': 'single', 'source_sha256': source_hash},
                            'needs_review': ['no_paragraph_geometry']})
    return records
