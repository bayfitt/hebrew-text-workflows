#!/usr/bin/env python3
"""Check the public source tree and optional history for private payloads."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import unicodedata


ROOT = Path(__file__).resolve().parents[1]
DIRECTORIES = {'scripts', 'tests', 'skills', 'profiles', 'fixtures', 'examples'}
ROOT_FILES = {'README.md', 'LICENSE', '.gitignore'}
EXTENSIONS = {'.py', '.mjs', '.gs', '.md', '.json', '.jsonl', '.yaml', '.yml', '.txt'}
PATTERNS = [re.compile(rb'AIza[0-9A-Za-z_-]{30,}'),
            re.compile(rb'sk-(?:proj-)?[0-9A-Za-z_-]{24,}'),
            re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
            re.compile(rb'"refresh_token"\s*:\s*"[^"\n]{12,}"'),
            re.compile(rb'docs\.google\.com/spreadsheets/d/[0-9A-Za-z_-]{25,}')]


def hebrew_words(text):
    text = re.sub(r'\\u(05[0-9A-Fa-f]{2})', lambda match: chr(int(match[1], 16)), text)
    text = unicodedata.normalize('NFKC', text)
    text = ''.join(char for char in text if not (0x591 <= ord(char) <= 0x5C7 and unicodedata.category(char).startswith('M')))
    return re.findall('[א-ת]+', text)


def source_paths():
    for path in ROOT.rglob('*'):
        relative = path.relative_to(ROOT)
        if any(part in {'.git', 'work', 'private', 'inputs', 'outputs', '__pycache__', 'node_modules'} for part in relative.parts):
            continue
        if path.is_file() or path.is_symlink():
            yield relative, path


def check_blob(name, data, private_windows):
    relative = Path(name)
    if relative.parts[0] not in DIRECTORIES and name not in ROOT_FILES:
        raise ValueError(f'Unapproved public path {name}')
    if name not in ROOT_FILES and relative.suffix not in EXTENSIONS:
        raise ValueError(f'Unapproved public file type {name}')
    if len(data) > 5_000_000:
        raise ValueError(f'Unexpected large public source file {name}')
    if any(pattern.search(data) for pattern in PATTERNS):
        raise ValueError(f'Credential or private Sheet link pattern in {name}')
    text = data.decode('utf-8')
    words = hebrew_words(text)
    if private_windows and any(tuple(words[index:index + 12]) in private_windows for index in range(max(0, len(words) - 11))):
        raise ValueError(f'Private text overlap in {name}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--private-records', help='Optional local JSONL reference outside the public tree')
    parser.add_argument('--history', action='store_true')
    args = parser.parse_args()
    private_windows = set()
    if args.private_records:
        reference = Path(args.private_records).resolve()
        if ROOT in reference.parents:
            raise ValueError('Private comparison input belongs outside the public repository')
        for line in reference.read_text().splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            words = hebrew_words(record.get('source_text', ''))
            private_windows.update(tuple(words[index:index + 12]) for index in range(max(0, len(words) - 11)))
    count = 0
    for relative, path in source_paths():
        if path.is_symlink():
            raise ValueError(f'Public symlink requires an explicit source copy {relative}')
        check_blob(str(relative), path.read_bytes(), private_windows)
        count += 1
    blobs = 0
    if args.history:
        entries = subprocess.check_output(['git', 'rev-list', '--objects', '--all'], cwd=ROOT, text=True).splitlines()
        for entry in entries:
            parts = entry.split(' ', 1)
            if len(parts) != 2:
                continue
            object_id, name = parts
            kind = subprocess.check_output(['git', 'cat-file', '-t', object_id], cwd=ROOT, text=True).strip()
            if kind != 'blob':
                continue
            data = subprocess.check_output(['git', 'cat-file', 'blob', object_id], cwd=ROOT)
            check_blob(name, data, private_windows)
            blobs += 1
    print(json.dumps({'public_source_files_checked': count, 'history_blobs_checked': blobs,
                      'private_text_reference_used': bool(args.private_records), 'status': 'pass'}))


if __name__ == '__main__':
    main()
