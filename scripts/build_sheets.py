#!/usr/bin/env python3
"""Prepare bounded native Google Sheets writes and a Legal landscape template."""
import argparse
import json
import math
import re
import textwrap
import unicodedata
from pathlib import Path
from xml.sax.saxutils import escape
import zipfile

from workflow_io import read_records, write_json


TITLES = ['Book', 'Hebrew Review', 'Source & Review', 'Schema']
SOURCE_HEADERS = ['Record ID', 'Volume', 'Printed page', 'PDF page', 'Side', 'Kind',
                  'Corrected literal OCR', 'Vocalized source', 'Transliteration',
                  'Google Translate', 'Reviewed English', 'Displayed English', 'OCR confidence',
                  'Review status', 'Review flags', 'Source link', 'Reading source', 'Spoken Hebrew',
                  'Reading review', 'Source baseline', 'Vocalization baseline', 'Reading policy', 'Dictionary hash']
BOOK_HEADERS = [['עברית', 'Transliteration', 'English'],
                ['טקסט עברי', 'Hebrew reading', 'English reading'],
                ['ניקוד לבדיקה', 'Pronunciation draft', 'Translation draft']]
REVIEW_HEADERS = [['Literal OCR (hidden)', 'עברית מנוקדת — מקור', 'עברית לקריאה — ראשי תיבות', 'Review and source'],
                  ['מקור', 'ניקוד המקור', 'הקריאה המקובלת', 'Hebrew reading review'],
                  ['Literal source', 'Vocalization draft', 'Spoken reading draft', 'Uncertain readings stay flagged']]


def cell(value, formula=False):
    text = '' if value is None else str(value)
    return {'userEnteredValue': {('formulaValue' if formula else 'stringValue'): text}}


def without_marks(text):
    return ''.join(char for char in text if not (0x591 <= ord(char) <= 0x5C7 and unicodedata.category(char).startswith('M')))


def height(values, font_size=12):
    lines = []
    for value in values:
        text = without_marks(str(value))
        width = 52 if re.search('[א-ת]', text) else 60
        width = math.floor(width * 12 / font_size)
        lines.append(sum(max(1, len(textwrap.wrap(line, width, replace_whitespace=False)))
                         for line in text.split('\n')))
    line_height_pixels = font_size * 96 / 72 * 1.4
    return max(40, math.ceil(max(lines, default=1) * line_height_pixels + 8))


def review_text(record):
    manual = record.get('reading_status') in ['manual', 'needs_attention'] or record.get('expansion_review', {}).get('manual', 0)
    status = 'Reading review required' if manual else 'Reviewed spoken forms with draft niqqud'
    flags = record.get('reading_flags', [])
    descriptions = [flag if isinstance(flag, str) else flag.get('code', '') for flag in flags]
    return ' | '.join([status, record['id'], *descriptions])


def build(records, sheet_ids, policy_version, dictionary_hash, batch_size=50):
    if set(sheet_ids) != set(TITLES) or len(set(sheet_ids.values())) != len(TITLES):
        raise ValueError('Provide distinct native sheet IDs for the four named tabs')
    if not 1 <= batch_size <= 150:
        raise ValueError('Batch size must be between 1 and 150')
    layout = []
    source_id = sheet_ids['Source & Review']
    book_id = sheet_ids['Book']
    review_id = sheet_ids['Hebrew Review']
    schema_id = sheet_ids['Schema']
    for title, columns, rows, hidden in [('Book', 3, len(records) + 3, False),
                                         ('Hebrew Review', 4, len(records) + 3, False),
                                         ('Source & Review', 23, len(records) + 1, True),
                                         ('Schema', 2, 20, True)]:
        layout.append({'updateSheetProperties': {
            'properties': {'sheetId': sheet_ids[title], 'hidden': hidden,
                           'gridProperties': {'rowCount': max(rows, 20), 'columnCount': columns,
                                              'frozenRowCount': 1, 'hideGridlines': True}},
            'fields': 'hidden,gridProperties'}})
    for title in ['Book', 'Hebrew Review']:
        sid = sheet_ids[title]
        columns = 3 if title == 'Book' else 4
        layout.extend([
            {'updateDimensionProperties': {'range': {'sheetId': sid, 'dimension': 'COLUMNS',
                                                     'startIndex': 0, 'endIndex': columns},
                                           'properties': {'pixelSize': 403}, 'fields': 'pixelSize'}},
            {'repeatCell': {'range': {'sheetId': sid}, 'cell': {'userEnteredFormat': {
                'textFormat': {'fontFamily': 'Times New Roman', 'fontSize': 12},
                'verticalAlignment': 'TOP', 'wrapStrategy': 'WRAP'}}, 'fields': 'userEnteredFormat'}},
            {'updateCells': {'start': {'sheetId': sid, 'rowIndex': 0, 'columnIndex': 0},
                             'rows': [{'values': [cell(value) for value in row]} for row in
                                      (BOOK_HEADERS if title == 'Book' else REVIEW_HEADERS)],
                             'fields': 'userEnteredValue'}},
            {'repeatCell': {'range': {'sheetId': sid, 'startRowIndex': 0, 'endRowIndex': 1},
                            'cell': {'userEnteredFormat': {'backgroundColor': {'red': .75, 'green': .88, 'blue': .82},
                                                          'textFormat': {'bold': True}}},
                            'fields': 'userEnteredFormat.backgroundColor,userEnteredFormat.textFormat.bold'}}])
    layout.append({'updateDimensionProperties': {
        'range': {'sheetId': review_id, 'dimension': 'COLUMNS', 'startIndex': 0, 'endIndex': 1},
        'properties': {'hiddenByUser': True}, 'fields': 'hiddenByUser'}})
    layout.append({'updateCells': {'start': {'sheetId': source_id, 'rowIndex': 0, 'columnIndex': 0},
                                   'rows': [{'values': [cell(value) for value in SOURCE_HEADERS]}],
                                   'fields': 'userEnteredValue'}})
    layout.append({'updateCells': {'start': {'sheetId': schema_id, 'rowIndex': 0, 'columnIndex': 0},
                                   'rows': [{'values': [cell('Reading policy'), cell(policy_version)]},
                                            {'values': [cell('Dictionary SHA-256'), cell(dictionary_hash)]}],
                                   'fields': 'userEnteredValue'}})
    batches, oversized = [], []
    for offset in range(0, len(records), batch_size):
        sources, books, reviews, sizes = [], [], [], []
        for index, record in enumerate(records[offset:offset + batch_size], offset):
            sr, vr = index + 2, index + 4
            source = record['source_text']
            pointed = record.get('vocalized_text') or source
            reading_source = record.get('expanded_source_text', source)
            reading = record.get('expanded_vocalized_text', pointed)
            info = review_text(record)
            meta = record.get('source', {})
            values = [record['id'], record.get('volume', ''), record.get('printed_page', ''),
                      meta.get('pdf_page', ''), meta.get('side', ''), record.get('kind', 'body'),
                      source, pointed, record.get('transliteration', ''),
                      f'=IF(G{sr}="","",GOOGLETRANSLATE(G{sr},"he","en"))',
                      record.get('english_override', ''), f'=IF(K{sr}<>"",K{sr},J{sr})',
                      record.get('ocr_confidence', ''), info, '', record.get('source_url', ''),
                      reading_source, reading, info, source, pointed,
                      record.get('reading_policy_version', ''), record.get('dictionary_sha256', '')]
            sources.append({'values': [cell(value, formula=col in [9, 11]) for col, value in enumerate(values)]})
            guard = (f'AND(EXACT(\'Source & Review\'!G{sr},\'Source & Review\'!T{sr}),'
                     f'EXACT(\'Source & Review\'!H{sr},\'Source & Review\'!U{sr}),'
                     f'EXACT(\'Source & Review\'!V{sr},Schema!B1),'
                     f'EXACT(\'Source & Review\'!W{sr},Schema!B2))')
            books.append({'values': [cell(f"='Source & Review'!H{sr}", True),
                                     cell(f'=IF({guard},\'Source & Review\'!I{sr},"[reading review pending]")', True),
                                     cell(f"='Source & Review'!L{sr}", True)]})
            reviews.append({'values': [cell(f"='Source & Review'!G{sr}", True),
                                       cell(f"='Source & Review'!H{sr}", True),
                                       cell(f'=IF({guard},\'Source & Review\'!R{sr},B{vr})', True),
                                       cell(f'=IF({guard},\'Source & Review\'!S{sr},"Source or reading policy changed. Recheck this row.")', True)]})
            font = 10 if record.get('kind') == 'footnotes' else 12
            for view_row in [books[-1], reviews[-1]]:
                for view_cell in view_row['values']:
                    view_cell['userEnteredFormat'] = {'textFormat': {'fontSize': font}}
            displayed_english = record.get('english_override') or record.get('google_translate') or record.get('english_text', '')
            for sid, values in [(book_id, [pointed, record.get('transliteration', ''), displayed_english]),
                                (review_id, [pointed, reading, info])]:
                pixels = height(values, font)
                sizes.append({'updateDimensionProperties': {
                    'range': {'sheetId': sid, 'dimension': 'ROWS', 'startIndex': index + 3, 'endIndex': index + 4},
                    'properties': {'pixelSize': pixels}, 'fields': 'pixelSize'}})
                if pixels > 650:
                    oversized.append({'id': record['id'], 'sheet_id': sid, 'required_pixels': pixels})
        requests = []
        for sid, row_index, rows in [(source_id, offset + 1, sources),
                                     (book_id, offset + 3, books), (review_id, offset + 3, reviews)]:
            fields = 'userEnteredValue' if sid == source_id else 'userEnteredValue,userEnteredFormat.textFormat.fontSize'
            requests.append({'updateCells': {'start': {'sheetId': sid, 'rowIndex': row_index, 'columnIndex': 0},
                                             'rows': rows, 'fields': fields}})
        batches.append({'requests': requests + sizes})
    return {'layout': {'requests': layout}, 'batches': batches, 'oversized_rows': oversized,
            'print_profile': {'paper': 'Legal', 'width_inches': 14, 'height_inches': 8.5,
                              'orientation': 'landscape', 'fit_to_width': 1, 'visible_columns': 3}}


def column_name(index):
    result = ''
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def write_template(path):
    """Write a blank native-import template with OOXML Legal page settings."""
    main_ns = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    rel_ns = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
    files = {}
    overrides = ''.join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(1, 5))
    files['[Content_Types].xml'] = ('<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>' + overrides + '</Types>')
    files['_rels/.rels'] = ('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'<Relationship Id="rId1" Type="{rel_ns}/officeDocument" Target="xl/workbook.xml"/></Relationships>')
    sheets = ''.join(f'<sheet name="{escape(title)}" sheetId="{i}" state="{"hidden" if i > 2 else "visible"}" r:id="rId{i}"/>' for i, title in enumerate(TITLES, 1))
    names = ''.join(f'<definedName name="_xlnm.Print_Titles" localSheetId="{i}">\'{escape(title)}\'!$1:$1</definedName>' for i, title in enumerate(TITLES[:2]))
    files['xl/workbook.xml'] = f'<workbook xmlns="{main_ns}" xmlns:r="{rel_ns}"><sheets>{sheets}</sheets><definedNames>{names}</definedNames></workbook>'
    relationships = ''.join(f'<Relationship Id="rId{i}" Type="{rel_ns}/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1, 5))
    files['xl/_rels/workbook.xml.rels'] = ('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + relationships + f'<Relationship Id="rId5" Type="{rel_ns}/styles" Target="styles.xml"/></Relationships>')
    files['xl/styles.xml'] = (f'<styleSheet xmlns="{main_ns}"><fonts count="1"><font><sz val="12"/><name val="Times New Roman"/></font></fonts>'
        '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
        '<borders count="1"><border/></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf></cellXfs>'
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>')
    for index, title in enumerate(TITLES, 1):
        rows = BOOK_HEADERS if index == 1 else REVIEW_HEADERS if index == 2 else [SOURCE_HEADERS] if index == 3 else [['Reading policy', ''], ['Dictionary SHA-256', '']]
        data = ''
        for row_index, values in enumerate(rows, 1):
            cells = ''.join(f'<c r="{column_name(col)}{row_index}" t="inlineStr"><is><t xml:space="preserve">{escape(str(value))}</t></is></c>' for col, value in enumerate(values, 1))
            data += f'<row r="{row_index}" ht="30" customHeight="1">{cells}</row>'
        columns = '<col min="1" max="3" width="50.5" customWidth="1"/>'
        if index == 2:
            columns = '<col min="1" max="1" width="50.5" customWidth="1" hidden="1"/><col min="2" max="4" width="50.5" customWidth="1"/>'
        files[f'xl/worksheets/sheet{index}.xml'] = (
            f'<worksheet xmlns="{main_ns}"><sheetPr><pageSetUpPr fitToPage="1"/></sheetPr>'
            '<sheetViews><sheetView workbookViewId="0" showGridLines="0"><pane ySplit="1" topLeftCell="A2" state="frozen"/></sheetView></sheetViews>'
            f'<sheetFormatPr defaultRowHeight="30"/><cols>{columns}</cols><sheetData>{data}</sheetData>'
            '<pageMargins left="0.5" right="0.5" top="0.5" bottom="0.5" header="0.2" footer="0.2"/>'
            '<pageSetup paperSize="5" orientation="landscape" fitToWidth="1" fitToHeight="0"/></worksheet>')
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, xml in files.items():
            archive.writestr(name, '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' + xml)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input')
    parser.add_argument('--metadata')
    parser.add_argument('--out', required=True)
    parser.add_argument('--policy-version', default='spoken-usage-v1')
    parser.add_argument('--dictionary-hash', default='')
    parser.add_argument('--template-only', action='store_true')
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    write_template(out / 'legal-landscape-template.xlsx')
    if args.template_only:
        return
    if not args.input or not args.metadata:
        parser.error('Payloads require --input and --metadata from the destination Sheet')
    metadata = json.loads(Path(args.metadata).read_text())
    ids = {sheet['properties']['title']: sheet['properties']['sheetId'] for sheet in metadata['sheets']
           if sheet['properties']['title'] in TITLES}
    result = build(read_records(args.input), ids, args.policy_version, args.dictionary_hash)
    write_json(out / 'layout.json', result['layout'])
    for index, batch in enumerate(result['batches']):
        write_json(out / 'body' / f'{index:04}.json', batch)
    write_json(out / 'print-checks.json', {key: result[key] for key in ['oversized_rows', 'print_profile']})
    print(json.dumps({'batches': len(result['batches']), 'oversized_rows': len(result['oversized_rows'])}))


if __name__ == '__main__':
    main()
