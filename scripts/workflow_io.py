"""Shared local record and checkpoint operations."""
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path


def digest(value):
    data = value.encode('utf-8') if isinstance(value, str) else value
    return hashlib.sha256(data).hexdigest()


def read_records(path):
    text = Path(path).read_text(encoding='utf-8')
    if not text.strip():
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = [json.loads(line) for line in text.splitlines() if line.strip()]
    if isinstance(parsed, dict):
        parsed = parsed.get('records', [parsed])
    if not isinstance(parsed, list):
        raise ValueError('Expected a record list or JSON Lines')
    ids = [record.get('id') for record in parsed]
    if any(not isinstance(value, str) or not value for value in ids):
        raise ValueError('Each record needs a nonempty string id')
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate record id')
    return parsed


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f'.{os.getpid()}.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.chmod(0o600)
    temporary.replace(path)


def write_records(path, records):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f'.{os.getpid()}.tmp')
    temporary.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in records), encoding='utf-8')
    temporary.chmod(0o600)
    temporary.replace(path)


def separate_output(output, *inputs):
    if Path(output).resolve() in {Path(value).resolve() for value in inputs}:
        raise ValueError('Use a separate output path')


def pdf_page_count(path):
    result = subprocess.run(['pdfinfo', str(path)], capture_output=True, text=True,
                            timeout=30, env={**os.environ, 'LC_ALL': 'C'})
    match = re.search(r'^Pages:\s+(\d+)', result.stdout, re.MULTILINE)
    if result.returncode or not match:
        raise RuntimeError('pdfinfo could not read the supplied PDF page count')
    return int(match.group(1))


def parse_pages(value, page_count):
    if value in (None, '', 'all'):
        return list(range(1, page_count + 1))
    pages = []
    for part in value.split(','):
        if '-' in part:
            first, last = map(int, part.split('-', 1))
            if first > last:
                raise ValueError('Page ranges must be ascending')
            pages.extend(range(first, last + 1))
        else:
            pages.append(int(part))
    if not pages or any(page < 1 or page > page_count for page in pages):
        raise ValueError('Requested page is outside the supplied PDF')
    return sorted(set(pages))
