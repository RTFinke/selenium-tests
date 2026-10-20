"""Extract the supplied Siz3r PDFs and generate an auditable Polish report."""
from __future__ import annotations

import csv
import hashlib
import json
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
SOURCE = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(r"C:\Users\suici\Downloads\Siz3rSizesComparisons")
sys.path.insert(0, str(ROOT / ".tmp-pdf-tools"))
sys.stdout.reconfigure(encoding="utf-8")
import pymupdf
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

PEOPLE = ["BB", "JB", "PF", "RF"]
MEASUREMENTS = [
    "Wzrost", "Obwód szyi", "Szerokość ramion", "Obwód klatki piersiowej",
    "Obwód biustu", "Obwód pod biustem", "Długość ramienia", "Obwód ramienia",
    "Obwód nadgarstka", "Długość tułowia", "Długość przodu", "Długość pleców",
    "Długość pleców do bioder", "Obwód talii", "Obwód bioder", "Wysokość stanu",
    "Obwód uda", "Długość nogawki po wewnętrznej", "Obwód kolana", "Obwód łydki",
    "Obwód kostki",
]
ROW_PATTERN = re.compile(
    r"\s*([^\d]+?)\s+(brak|\d+(?:,\d+)?)\s+(brak|\d+(?:,\d+)?)"
    r"\s+([+-]?\d+(?:,\d+)?|-)\s*(.*)"
)


def number(value):
    return float(value.replace(",", "."))


def extract():
    records, inventory = [], []
    for path in sorted(SOURCE.glob("*.pdf")):
        match = re.fullmatch(r"([A-Z]+)-(1photo|2photos)-(\d+)\.pdf", path.name)
        if not match:
            raise ValueError(f"Nieznany format nazwy pliku: {path.name}")
        person, photo_label, run = match.groups()
        photos = int(photo_label[0])
        file_records = []
        with pymupdf.open(path) as document:
            for page in document:
                for line in page.get_text(sort=True).splitlines():
                    row = ROW_PATTERN.fullmatch(line)
                    if not row:
                        continue
                    name, predicted, actual, printed_difference, extra = row.groups()
                    name = name.strip()
                    if name not in MEASUREMENTS:
                        raise ValueError(f"Nieznany wymiar: {path.name}: {name}")
                    predicted = None if predicted == "brak" else number(predicted)
                    actual = None if actual == "brak" else number(actual)
                    printed_difference = None if printed_difference == "-" else number(printed_difference)
                    difference = None if predicted is None or actual is None else predicted - actual
                    if difference != printed_difference:
                        raise ValueError(f"Niezgodna różnica w PDF: {path.name}: {name}")
                    # Two PDFs also contain previous results. They are not extra trials.
                    if extra:
                        previous, printed_change = extra.split()
                        change = None if predicted is None or previous == "brak" else predicted - number(previous)
                        expected_change = None if printed_change == "-" else number(printed_change)
                        if change != expected_change:
                            raise ValueError(f"Niezgodna zmiana w PDF: {path.name}: {name}")
                    file_records.append(dict(
                        file=path.name, person=person, photos=photos, run=int(run),
                        measurement=name, siz3r=predicted, actual=actual,
                        diff=difference, abs_diff=None if difference is None else abs(difference),
                        pdf_diff=printed_difference,
                    ))
            page_count = len(document)
        if [r["measurement"] for r in file_records] != MEASUREMENTS:
            raise ValueError(f"Niepełna lub powtórzona tabela: {path.name}")
        records.extend(file_records)
        inventory.append(dict(file=path.name, person=person, photos=photos, run=int(run),
                              rows=len(file_records), pages=page_count,
                              sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    if not records:
        raise ValueError("Brak plików źródłowych")
    # Verify that actual values and missingness agree across a person's repeated trials.
    actuals = defaultdict(set)
    for record in records:
        actuals[record["person"], record["measurement"]].add(record["actual"])
    if any(len(values) != 1 for values in actuals.values()):
        raise ValueError("Pomiary rzeczywiste różnią się między próbami tej samej osoby")
    return records, inventory


def completeness(record):
    if record["siz3r"] is None and record["actual"] is None:
        return "Brak obu wartości"
    if record["siz3r"] is None:
        return "Brak Siz3r"
    if record["actual"] is None:
        return "Brak rzeczywistego"
    return "OK"


def stats(records):
    valid = [r for r in records if completeness(r) == "OK"]
    return dict(n=len(valid), mae=statistics.mean(r["abs_diff"] for r in valid) if valid else None,
                bias=statistics.mean(r["diff"] for r in valid) if valid else None)


def fmt(value, signed=False):
    if value is None:
        return "—"
    return (f"{value:+.2f}" if signed and value != 0 else f"{value:.2f}").replace(".", ",")


def winner(first, second):
    if first is None or second is None:
        return "Brak danych"
    return "2 zdjęcia" if second < first else "1 zdjęcie" if first < second else "Tak samo"


def effect(change):
    if change is None:
        return "Brak danych"
    if change == 0:
        return "Bez zmiany"
    return f"{fmt(abs(change))} cm {'lepiej' if change < 0 else 'gorzej'}"


def used_measurements(first, second):
    return f"{first['n'] + second['n']} ({first['n']} + {second['n']})"


def write_csv(filename, headers, rows):
    with (OUT / filename).open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream, delimiter=";")
        writer.writerow(headers)
        for row in rows:
            writer.writerow([fmt(v) if isinstance(v, float) else "" if v is None else v for v in row])


# Small native OOXML writer: numeric cells, formulas with cached results, styles and filters.
NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
ET.register_namespace("", NS)
ET.register_namespace("r", REL)


def element(name, attributes=None, parent=None, text=None):
    node = ET.Element(f"{{{NS}}}{name}", attributes or {}) if parent is None else ET.SubElement(parent, f"{{{NS}}}{name}", attributes or {})
    if text is not None:
        node.text = str(text)
    return node


def colname(n):
    result = ""
    while n:
        n, rem = divmod(n - 1, 26)
        result = chr(65 + rem) + result
    return result


def cell(value=None, style=0, formula=None):
    return dict(value=value, style=style, formula=formula)


def sheet(name, rows, widths, header=1, merges=(), conditional=()):
    return dict(name=name, rows=rows, widths=widths, header=header,
                merges=merges, conditional=conditional)


def write_xlsx(sheets):
    styles = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="{NS}">
<numFmts count="4"><numFmt numFmtId="164" formatCode="0.00"/>
<numFmt numFmtId="165" formatCode="+0.00;-0.00;0.00"/>
<numFmt numFmtId="166" formatCode="0.##"/>
<numFmt numFmtId="167" formatCode="0.00&quot; cm gorzej&quot;;0.00&quot; cm lepiej&quot;;&quot;Bez zmiany&quot;"/></numFmts>
<fonts count="5">
<font><sz val="11"/><color rgb="FF203D4D"/><name val="Calibri"/></font>
<font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font>
<font><b/><sz val="20"/><color rgb="FF203D4D"/><name val="Calibri"/></font>
<font><sz val="10"/><color rgb="FF536773"/><name val="Calibri"/></font>
<font><b/><sz val="11"/><color rgb="FF203D4D"/><name val="Calibri"/></font>
</fonts><fills count="5">
<fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FF203D4D"/><bgColor indexed="64"/></patternFill></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FFEAF1F5"/><bgColor indexed="64"/></patternFill></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FFFFF3D6"/><bgColor indexed="64"/></patternFill></fill>
</fills><borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="13">
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"><alignment vertical="center"/></xf>
<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="center" wrapText="1"/></xf>
<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"><alignment horizontal="center" vertical="center"/></xf>
<xf numFmtId="165" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"><alignment horizontal="center" vertical="center"/></xf>
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"><alignment horizontal="center" vertical="center"/></xf>
<xf numFmtId="0" fontId="2" fillId="0" borderId="0" xfId="0"><alignment vertical="center"/></xf>
<xf numFmtId="0" fontId="3" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="center" wrapText="1"/></xf>
<xf numFmtId="164" fontId="4" fillId="3" borderId="0" xfId="0" applyNumberFormat="1"><alignment horizontal="center" vertical="center"/></xf>
<xf numFmtId="0" fontId="4" fillId="3" borderId="0" xfId="0"><alignment vertical="center"/></xf>
<xf numFmtId="166" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"><alignment horizontal="center" vertical="center"/></xf>
<xf numFmtId="0" fontId="0" fillId="4" borderId="0" xfId="0"><alignment vertical="center"/></xf>
<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf>
<xf numFmtId="167" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"><alignment horizontal="center" vertical="center"/></xf>
</cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
<dxfs count="2"><dxf><font><color rgb="FF197047"/></font><fill><patternFill patternType="solid"><fgColor rgb="FFE2F3E9"/></patternFill></fill></dxf>
<dxf><font><color rgb="FFA33333"/></font><fill><patternFill patternType="solid"><fgColor rgb="FFFCE7E7"/></patternFill></fill></dxf></dxfs>
</styleSheet>'''
    workbook = element("workbook")
    book_views = element("bookViews", parent=workbook)
    element("workbookView", {"activeTab": "0"}, book_views)
    sheet_nodes = element("sheets", parent=workbook)
    element("calcPr", {"calcId": "191029", "fullCalcOnLoad": "1"}, workbook)
    relationships = []
    contents = [('<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'),
                ('<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>')]
    with ZipFile(OUT / "Siz3r_podsumowanie_wymiarow.xlsx", "w", ZIP_DEFLATED) as archive:
        archive.writestr("xl/styles.xml", styles)
        for index, spec in enumerate(sheets, 1):
            numeric_columns = set()
            for values in spec["rows"][spec["header"]:]:
                for column, item in enumerate(values, 1):
                    value = item["value"] if isinstance(item, dict) else item
                    if isinstance(value, (int, float)):
                        numeric_columns.add(column)
            element("sheet", {"name": spec["name"], "sheetId": str(index), f"{{{REL}}}id": f"rId{index}"}, sheet_nodes)
            relationships.append(f'<Relationship Id="rId{index}" Type="{REL}/worksheet" Target="worksheets/sheet{index}.xml"/>')
            contents.append(f'<Override PartName="/xl/worksheets/sheet{index}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>')
            node = element("worksheet")
            last_col = colname(len(spec["widths"]))
            element("dimension", {"ref": f"A1:{last_col}{len(spec['rows'])}"}, node)
            views = element("sheetViews", parent=node)
            view = element("sheetView", {"workbookViewId": "0", "showGridLines": "0"}, views)
            element("pane", {"ySplit": str(spec["header"]), "topLeftCell": f"A{spec['header'] + 1}", "activePane": "bottomLeft", "state": "frozen"}, view)
            element("sheetFormatPr", {"defaultRowHeight": "22"}, node)
            columns = element("cols", parent=node)
            for column, width in enumerate(spec["widths"], 1):
                element("col", {"min": str(column), "max": str(column), "width": str(width), "customWidth": "1"}, columns)
            data = element("sheetData", parent=node)
            for row_no, row_values in enumerate(spec["rows"], 1):
                row = element("row", {"r": str(row_no)}, data)
                if row_no == spec["header"]:
                    row.set("ht", "76"); row.set("customHeight", "1")
                elif row_values and isinstance(row_values[0], dict) and row_values[0]["style"] in [5, 6]:
                    row.set("ht", "32" if row_values[0]["style"] == 5 else "28"); row.set("customHeight", "1")
                for column, item in enumerate(row_values, 1):
                    item = item if isinstance(item, dict) else cell(item)
                    value, style_id, formula = item["value"], item["style"], item["formula"]
                    if row_no == spec["header"] and style_id == 1 and column in numeric_columns:
                        style_id = 11
                    elif isinstance(value, (int, float)) and style_id == 0:
                        style_id = 4
                    elif isinstance(value, (int, float)) and style_id == 8:
                        style_id = 7
                    if value is None and formula is None:
                        continue
                    entry = element("c", {"r": f"{colname(column)}{row_no}", "s": str(style_id)}, row)
                    if formula is not None:
                        if isinstance(value, str) or value is None:
                            entry.set("t", "str")
                        element("f", parent=entry, text=formula)
                        element("v", parent=entry, text="" if value is None else value)
                    elif isinstance(value, (int, float)):
                        element("v", parent=entry, text=value)
                    else:
                        entry.set("t", "inlineStr")
                        inline = element("is", parent=entry)
                        element("t", parent=inline, text=value)
            if spec["name"] != "Jak czytać":
                end = 28 if spec["name"] == "Podsumowanie" else len(spec["rows"])
                element("autoFilter", {"ref": f"A{spec['header']}:{last_col}{end}"}, node)
            if spec["merges"]:
                merges = element("mergeCells", {"count": str(len(spec["merges"]))}, node)
                for merged in spec["merges"]:
                    element("mergeCell", {"ref": merged}, merges)
            for reference in spec["conditional"]:
                formatting = element("conditionalFormatting", {"sqref": reference}, node)
                for priority, operator, dxf in [(1, "lessThan", 0), (2, "greaterThan", 1)]:
                    rule = element("cfRule", {"type": "cellIs", "dxfId": str(dxf), "priority": str(priority), "operator": operator}, formatting)
                    element("formula", parent=rule, text="0")
            element("pageMargins", {"left": "0.3", "right": "0.3", "top": "0.4", "bottom": "0.4", "header": "0.2", "footer": "0.2"}, node)
            element("pageSetup", {"paperSize": "9", "orientation": "landscape", "fitToWidth": "1", "fitToHeight": "0"}, node)
            archive.writestr(f"xl/worksheets/sheet{index}.xml", ET.tostring(node, encoding="utf-8", xml_declaration=True))
        relationships.append(f'<Relationship Id="rId{len(sheets) + 1}" Type="{REL}/styles" Target="styles.xml"/>')
        archive.writestr("xl/workbook.xml", ET.tostring(workbook, encoding="utf-8", xml_declaration=True))
        archive.writestr("xl/_rels/workbook.xml.rels", f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{"".join(relationships)}</Relationships>')
        archive.writestr("_rels/.rels", f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="{REL}/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        archive.writestr("[Content_Types].xml", f'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>{"".join(contents)}</Types>')


def make_workbook(records, inventory, summary, overall, person_dimensions, person_summary, trials):
    last = len(records) + 1
    source_name = "Dane źródłowe"
    reference = lambda col: f"'{source_name}'!${col}$2:${col}${last}"

    def count_formula(measurement_cell):
        common = f'{reference("E")},{measurement_cell},{reference("K")},"OK"'
        total = f"COUNTIFS({common})"
        first = f'COUNTIFS({common},{reference("D")},1)'
        second = f'COUNTIFS({common},{reference("D")},2)'
        return f'{total}&" ("&{first}&" + "&{second}&")"'

    raw_rows = [[cell(v, 1) for v in ["Plik", "Osoba", "Próba", "Liczba zdjęć", "Pomiar", "Siz3r [cm]", "Rzeczywisty [cm]", "Różnica [cm]", "Bezwzględna różnica [cm]", "Różnica w PDF [cm]", "Dostępność"]]]
    for row, record in enumerate(records, 2):
        status = completeness(record)
        raw_rows.append([record["file"], record["person"], cell(record["run"], 4), cell(record["photos"], 4), record["measurement"],
                         cell(record["siz3r"], 9), cell(record["actual"], 9),
                         cell(record["diff"], 3, f'IF(OR(F{row}="",G{row}=""),"",F{row}-G{row})'),
                         cell(record["abs_diff"], 2, f'IF(H{row}="","",ABS(H{row}))'),
                         cell(record["pdf_diff"], 3),
                         cell(status, 0 if status == "OK" else 10,
                              f'IF(AND(ISNUMBER(F{row}),ISNUMBER(G{row})),"OK",IF(AND(F{row}="",G{row}=""),"Brak obu wartości",IF(F{row}="","Brak Siz3r","Brak rzeczywistego")))')])
    summary_rows = [
        [cell("Siz3r — porównanie pomiarów ciała", 5)],
        [cell(f"{len(inventory)} plików • {len(PEOPLE)} osoby • 1 i 2 zdjęcia • wszystkie wartości w cm", 6)],
        [cell("Średnia pomyłka: o ile cm wynik odbiega od rzeczywistego pomiaru, niezależnie od tego, czy jest większy, czy mniejszy.", 6)],
        [cell("Zawyżenie / zaniżenie: + oznacza wynik za duży, − za mały. Zawyżenia i zaniżenia mogą się znosić w średniej.", 6)],
        [cell("Co daje 2. zdjęcie? „Lepiej” oznacza mniejszą średnią pomyłkę, a „gorzej” większą. Każda próba ma jednakową wagę.", 6)], [],
        [cell(v, 1) for v in ["Mierzony wymiar", "Średnio o ile Siz3r się myli [cm]\n1 zdjęcie", "Średnio o ile Siz3r się myli [cm]\n2 zdjęcia", "Co daje 2. zdjęcie?\nLepiej / gorzej", "Średnie zawyżenie lub zaniżenie [cm]\n1 zdjęcie", "Średnie zawyżenie lub zaniżenie [cm]\n2 zdjęcia", "Który wariant jest dokładniejszy?", "Łączna liczba użytych pomiarów\nrazem (1 zdjęcie + 2 zdjęcia)"]],
    ]
    summary_rows[6][-1]["style"] = 11
    for row_no, item in enumerate(summary, 8):
        name, first, second = item["measurement"], item["first"], item["second"]
        row = [name]
        for photos, group in [(1, first), (2, second)]:
            row.append(cell(group["mae"], 2, f'AVERAGEIFS({reference("I")},{reference("D")},{photos},{reference("E")},A{row_no})'))
        row.append(cell(item["change"], 12, f"C{row_no}-B{row_no}"))
        for photos, group in [(1, first), (2, second)]:
            row.append(cell(group["bias"], 3, f'AVERAGEIFS({reference("H")},{reference("D")},{photos},{reference("E")},A{row_no})'))
        row.append(cell(winner(first["mae"], second["mae"]), 0,
                        f'IF(B{row_no}<C{row_no},"1 zdjęcie",IF(C{row_no}<B{row_no},"2 zdjęcia","Tak samo"))'))
        row.append(cell(used_measurements(first, second), 4, count_formula(f"A{row_no}")))
        summary_rows.append(row)
    summary_rows += [[], [cell("Łącznie (dostępne pozycje)", 8),
                           cell(overall[1]["mae"], 7), cell(overall[2]["mae"], 7), cell(overall[2]["mae"] - overall[1]["mae"], 12),
                           cell(overall[1]["bias"], 7), cell(overall[2]["bias"], 7), cell(winner(overall[1]["mae"], overall[2]["mae"]), 8),
                           cell(used_measurements(overall[1], overall[2]), 4)],
                     [cell("Łączny wynik uśrednia 101 dostępnych pozycji na wariant; nie jest średnią z 21 średnich w tabeli.", 6)],
                     [cell("Licznik uwzględnia tylko kompletne pola: wynik Siz3r i pomiar rzeczywisty. 4 (2 + 2) oznacza po 2 użyte wyniki w każdym wariancie.", 6)]]
    person_dim_rows = [[cell(v, 1) for v in ["Osoba", "Mierzony wymiar", "Średnio o ile Siz3r się myli [cm]\n1 zdjęcie", "Średnio o ile Siz3r się myli [cm]\n2 zdjęcia", "Co daje 2. zdjęcie?\nLepiej / gorzej", "Średnie zawyżenie lub zaniżenie [cm]\n1 zdjęcie", "Średnie zawyżenie lub zaniżenie [cm]\n2 zdjęcia", "Łączna liczba użytych pomiarów\nrazem (1 zdjęcie + 2 zdjęcia)"]]]
    person_dim_rows[0][-1]["style"] = 11
    for item in person_dimensions:
        first, second = item["first"], item["second"]
        person_dim_rows.append([item["person"], item["measurement"],
                                cell(first["mae"], 2), cell(second["mae"], 2), cell(item["change"], 12), cell(first["bias"], 3), cell(second["bias"], 3),
                                cell(used_measurements(first, second), 4)])
    person_rows = [[cell(v, 1) for v in ["Osoba", "Liczba prób\n1 zdjęcie", "Liczba prób\n2 zdjęcia", "Średnio o ile Siz3r się myli [cm]\n1 zdjęcie", "Średnio o ile Siz3r się myli [cm]\n2 zdjęcia", "Co daje 2. zdjęcie?\nLepiej / gorzej"]]]
    for item in person_summary:
        person_rows.append([item["person"], item["runs"], item["runs"],
                            cell(item["first"]["mae"], 2), cell(item["second"]["mae"], 2), cell(item["change"], 12)])
    trial_headers = ["Plik", "Osoba", "Liczba zdjęć", "Numer próby", "Brakujące rzeczywiste pomiary", "Średnio o ile Siz3r się myli [cm]", "Średnie zawyżenie lub zaniżenie [cm]"]
    trial_rows = [[cell(v, 1) for v in trial_headers]]
    for item in trials:
        trial_rows.append([item["file"], item["person"], item["photos"], item["run"], len(MEASUREMENTS) - item["n"], cell(item["mae"], 2), cell(item["bias"], 3)])
    equal_rows = [[cell("Równa waga osób — wariant pomocniczy", 5)],
                  [cell("Najpierw średni błąd z prób jednej osoby, potem średnia z osób z dostępnym pomiarem. JB i PF nie mają większej wagi.", 6)],
                  [cell(v, 1) for v in ["Mierzony wymiar", "Liczba osób", "Średnio o ile Siz3r się myli [cm]\n1 zdjęcie", "Średnio o ile Siz3r się myli [cm]\n2 zdjęcia", "Co daje 2. zdjęcie?\nLepiej / gorzej", "Łączna liczba użytych pomiarów\nrazem (1 zdjęcie + 2 zdjęcia)"]]]
    equal_rows[2][-1]["style"] = 11
    for name in MEASUREMENTS:
        selected = [item for item in person_dimensions if item["measurement"] == name and item["first"]["mae"] is not None]
        first = statistics.mean(item["first"]["mae"] for item in selected)
        second = statistics.mean(item["second"]["mae"] for item in selected)
        counts = [sum(item[group]["n"] for item in selected) for group in ["first", "second"]]
        equal_rows.append([name, len(selected), cell(first, 2), cell(second, 2), cell(second - first, 12),
                           cell(used_measurements(dict(n=counts[0]), dict(n=counts[1])), 4)])
    notes = [
        "Jak czytać raport",
        "Cel: średnie różnice Siz3r względem pomiarów rzeczywistych, osobno dla jednego i dwóch zdjęć.",
        "Nazwa JB-1photo-1: osoba JB, jedno zdjęcie, pierwsza próba. PF-2photos-2: osoba PF, dwa zdjęcia, druga próba.",
        "Liczbę zdjęć i próbę odczytano z nazw plików. Tytuły PDF typu „zdjęcie 3” nie określają liczby zdjęć wejściowych.",
        "Z 12 PDF odczytano 252 pozycje: 202 z pomiarem rzeczywistym i 50 bez niego. Po 101 porównań na wariant.",
        "Średnio o ile Siz3r się myli: średnia odległość wyniku od rzeczywistego pomiaru. Zawsze 0 lub więcej; mniej oznacza dokładniej.",
        "Przykład: wynik za duży o 4 cm i za mały o 4 cm dają średnią pomyłkę 4 cm, lecz średnie zawyżenie / zaniżenie 0 cm.",
        "Średnie zawyżenie / zaniżenie: średnia z Siz3r minus rzeczywisty. Plus oznacza wynik za duży, minus za mały.",
        "Co daje 2. zdjęcie: „1,00 cm lepiej” oznacza pomyłkę mniejszą o 1 cm, „1,00 cm gorzej” większą o 1 cm.",
        "Excel przechowuje efekt jako liczbę: wynik dla 2 zdjęć minus wynik dla 1 zdjęcia. Format komórki dodaje słowo „lepiej” lub „gorzej”.",
        "Główna tabela nadaje każdej próbie tę samą wagę. BB i RF mają po jednej próbie na wariant; JB i PF po dwie.",
        "Zakładka „Równa waga osób” pokazuje dodatkowy wariant, w którym najpierw uśredniono próby każdej osoby.",
        "Brakujące rzeczywiste wartości nie zostały zastąpione zerami. Liczba porównań oznacza dostępne pomiary, a nie liczbę osób.",
        "Liczba pomiarów z pełnymi danymi: 4 (2 + 2) oznacza 4 kompletne pola, po 2 dla wariantu z 1 zdjęciem i z 2 zdjęciami.",
        "Pole jest użyte w średniej tylko wtedy, gdy zawiera obie wartości: Siz3r i pomiar rzeczywisty. Brak którejkolwiek wyklucza to pole.",
        "Zakładka „Kompletność pól” pokazuje dla każdego parametru i każdego pliku, czy dane zostały użyte, czy pominięte z powodu braku.",
        "Łączny wynik jest średnią po dostępnych pozycjach i zależy od zestawu wymiarów oraz braków danych.",
        "Klatka piersiowa i biust są osobnymi pozycjami, zgodnie z PDF. Wzrost uwzględniono; jest zgodny we wszystkich plikach.",
        "Kolumny „Poprzednie” i „Zmiana” w dwóch PDF nie zostały policzone jako dodatkowe próby.",
        "W źródłowych PDF przypisano rzeczywiste wartości do nazw wymiarów według kolejności wierszy. Raport zachowuje te przypisania.",
        "Raport opisuje dostarczone wyniki 4 osób. Powtórzenia tej samej osoby nie oznaczają dodatkowych niezależnych osób.",
        "Weryfikacja: wszystkie 202 różnice z PDF zgadzają się z ponownym odejmowaniem Siz3r − rzeczywisty.",
        "Weryfikacja: wartości rzeczywiste oraz braki są spójne między próbami tej samej osoby.",
        f"Folder źródłowy: {SOURCE}",
        "Wartości w Excelu zachowują pełną precyzję. PDF i CSV pokazują wyniki zaokrąglone do 2 miejsc.",
        "Źródłowe pliki pozostawiono bez zmian. Plik analiza.py umożliwia ponowne wygenerowanie raportu.",
    ]
    note_rows = [[cell(note, 5 if index == 0 else 6)] for index, note in enumerate(notes)]
    source_rows = [[cell(v, 1) for v in ["Plik", "Osoba", "Liczba zdjęć", "Próba", "Liczba wierszy", "Strony", "SHA-256"]]]
    source_rows += [[i["file"], i["person"], i["photos"], i["run"], i["rows"], i["pages"], i["sha256"]] for i in inventory]
    count_header = "Liczba pomiarów z pełnymi danymi\nrazem (1 zdjęcie + 2 zdjęcia)"
    for rows, header_row in [(summary_rows, 6), (person_dim_rows, 0), (equal_rows, 2)]:
        rows[header_row][-1]["value"] = count_header
    field_headers = ["Mierzony wymiar"] + [item["file"] for item in inventory] + [count_header]
    field_rows = [[cell(label, 1) for label in field_headers]]
    field_rows[0][-1]["style"] = 11
    indexed_records = {(r["file"], r["measurement"]): r for r in records}
    for item in summary:
        field_row = [item["measurement"]]
        for file in inventory:
            status = completeness(indexed_records[file["file"], item["measurement"]])
            field_row.append(cell("Użyty" if status == "OK" else status, 0 if status == "OK" else 10))
        field_row.append(cell(used_measurements(item["first"], item["second"]), 4))
        field_rows.append(field_row)
    write_xlsx([
        sheet("Podsumowanie", summary_rows, [42] + [27] * 5 + [24, 29], 7,
              [f"A{r}:H{r}" for r in [1, 2, 3, 4, 5, 31, 32]], ["D8:D28"]),
        sheet("Osoby", person_rows, [12] + [27] * 5, conditional=["F2:F5"]),
        sheet("Próby", trial_rows, [25, 12, 16, 12, 27, 27, 27]),
        sheet("Osoby i wymiary", person_dim_rows, [12, 42] + [27] * 5 + [29], conditional=["E2:E85"]),
        sheet("Równa waga osób", equal_rows, [42] + [24] * 4 + [29], 3, ["A1:F1", "A2:F2"], ["E4:E24"]),
        sheet(source_name, raw_rows, [24, 11, 10, 15, 42, 16, 20, 19, 26, 22, 25]),
        sheet("Jak czytać", note_rows, [150], merges=[]),
        sheet("Pliki źródłowe", source_rows, [25, 12, 17, 12, 20, 12, 72]),
        sheet("Kompletność pól", field_rows, [42] + [24] * len(inventory) + [29]),
    ])


def make_pdf(summary, overall, person_summary, trials):
    pdfmetrics.registerFont(TTFont("Arial", r"C:\Windows\Fonts\arial.ttf"))
    pdfmetrics.registerFont(TTFont("ArialBold", r"C:\Windows\Fonts\arialbd.ttf"))
    width, height = landscape(A4)
    doc = canvas.Canvas(str(OUT / "Siz3r_podsumowanie_wymiarow.pdf"), pagesize=(width, height))
    doc.setTitle("Siz3r — porównanie pomiarów: 1 i 2 zdjęcia")
    doc.setAuthor("Analiza dostarczonych plików Siz3r")
    ink, muted = colors.HexColor("#203D4D"), colors.HexColor("#526875")
    pale, green, red = colors.HexColor("#EFF4F7"), colors.HexColor("#197047"), colors.HexColor("#A33333")
    margin = 32
    padding = 10
    table_width = width - 2 * margin
    first_column_width = 235
    def column_widths(column_count):
        return [first_column_width] + [(table_width - first_column_width) / (column_count - 1)] * (column_count - 1)

    def text(x, y, value, size=9, bold=False, color=ink, right=False, centered=False):
        doc.setFillColor(color)
        doc.setFont("ArialBold" if bold else "Arial", size)
        draw = doc.drawCentredString if centered else doc.drawRightString if right else doc.drawString
        draw(x, y, str(value))

    def footer(page):
        doc.setStrokeColor(colors.HexColor("#D6E0E6"))
        doc.line(margin, 28, width - margin, 28)
        text(margin, 15, "Siz3r | 12 porównań PDF | BB, JB, PF, RF | Wszystkie różnice w cm", 8, color=muted)
        text(width - margin, 15, f"{page} / 2", 8, color=muted, right=True)

    def table(top, headings, data, widths, row_height=15, delta_column=None, font=8.5,
              groups=None, delta_values=None):
        assert len(headings) == len(widths) and all(len(row) == len(widths) for row in data)
        heading_height = 46 if groups else max(32, 12 + 10 * max(len(h.split("\n")) for h in headings))
        doc.setFillColor(ink)
        doc.rect(margin, top - heading_height, sum(widths), heading_height, fill=1, stroke=0)

        def header_label(label, x, column_width, label_top, label_height, left=False):
            lines = label.split("\n")
            baseline = label_top - label_height / 2 + (len(lines) - 1) * 5 - 2.8
            for index, line in enumerate(lines):
                assert pdfmetrics.stringWidth(line, "ArialBold", 8) <= column_width - 2 * padding, line
                text(x + padding if left else x + column_width / 2,
                     baseline - index * 10, line, 8, True, colors.white, centered=not left)

        x = margin
        if groups:
            column = 0
            doc.setStrokeColor(colors.HexColor("#58707D"))
            doc.setLineWidth(0.5)
            for label, count in groups:
                group_width = sum(widths[column:column + count])
                header_label(label, x, group_width, top, heading_height if count == 1 else 28, left=column == 0)
                if count > 1:
                    doc.line(x, top - 28, x + group_width, top - 28)
                    child_x = x
                    for child_column in range(column, column + count):
                        header_label(headings[child_column], child_x, widths[child_column], top - 28, 18)
                        child_x += widths[child_column]
                x += group_width
                column += count
                if column < len(widths):
                    doc.line(x, top, x, top - heading_height)
            assert column == len(widths)
        else:
            for column, (heading, column_width) in enumerate(zip(headings, widths)):
                header_label(heading, x, column_width, top, heading_height, left=column == 0)
                x += column_width
        y = top - heading_height
        for index, row in enumerate(data):
            if index % 2 == 0:
                doc.setFillColor(pale)
                doc.rect(margin, y - row_height, sum(widths), row_height, fill=1, stroke=0)
            x = margin
            for column, (value, column_width) in enumerate(zip(row, widths)):
                color = ink
                if column == delta_column:
                    numeric = delta_values[index] if delta_values is not None else float(str(value).replace(",", "."))
                    color = green if numeric < 0 else red if numeric > 0 else muted
                assert pdfmetrics.stringWidth(str(value), "Arial", font) <= column_width - 2 * padding
                text(x + padding if column == 0 else x + column_width / 2,
                     y - row_height / 2 - font * 0.35,
                     value, font, color=color, centered=column != 0)
                x += column_width
            y -= row_height
        return y

    text(margin, height - 38, "Siz3r — średnie różnice pomiarów", 20, True)
    text(margin, height - 56, "Porównanie 1 zdjęcia i 2 zdjęć | 4 osoby | po 6 prób na wariant", 10, color=muted)
    card_top = height - 69
    card_width = (width - 2 * margin - 20) / 3
    change = overall[2]["mae"] - overall[1]["mae"]
    for index, (label, value, note) in enumerate([
        ("1 ZDJĘCIE — ŚREDNIA POMYŁKA", fmt(overall[1]["mae"]) + " cm", "101 dostępnych porównań"),
        ("2 ZDJĘCIA — ŚREDNIA POMYŁKA", fmt(overall[2]["mae"]) + " cm", "101 dostępnych porównań"),
        ("EFEKT DODANIA 2. ZDJĘCIA", effect(change), "Większa średnia pomyłka w tych plikach"),
    ]):
        x = margin + index * (card_width + 10)
        doc.setFillColor(pale)
        doc.roundRect(x, card_top - 58, card_width, 58, 5, fill=1, stroke=0)
        text(x + padding, card_top - 13, label, 8, True, muted)
        text(x + padding, card_top - 35, value, 19, True, red if index == 2 else ink)
        text(x + padding, card_top - 49, note, 8, color=muted)
    text(margin, height - 140, "Średnia pomyłka: o ile cm wynik odbiega od rzeczywistego pomiaru, niezależnie od tego, czy jest większy, czy mniejszy.", 8.5)
    text(margin, height - 152, "Zawyżenie / zaniżenie: + oznacza wynik za duży, − za mały. Zawyżenia i zaniżenia mogą się znosić w średniej.", 8.5)
    text(margin, height - 164, "Licznik obejmuje tylko pola z obiema wartościami: Siz3r i rzeczywistą. 4 (2 + 2) = po 2 kompletne pola w każdym wariancie.", 8.5)
    table_rows = [[item["measurement"], fmt(item["first"]["mae"]), fmt(item["second"]["mae"]),
                   effect(item["change"]), fmt(item["first"]["bias"], True), fmt(item["second"]["bias"], True),
                   used_measurements(item["first"], item["second"])] for item in summary]
    bottom = table(height - 175,
                   ["Mierzony wymiar", "1 zdjęcie", "2 zdjęcia", "", "1 zdjęcie", "2 zdjęcia", ""],
                   table_rows, column_widths(7),
                   row_height=15, delta_column=3, font=8.6,
                   groups=[("Mierzony wymiar", 1), ("Średnio o ile Siz3r\nsię myli [cm]", 2),
                           ("Co daje\n2. zdjęcie?", 1), ("Średnie zawyżenie\nlub zaniżenie [cm]", 2),
                           ("Liczba pomiarów\nz pełnymi danymi", 1)],
                   delta_values=[item["change"] for item in summary])
    text(margin, bottom - 15, "2 zdjęcia: 7 wymiarów dokładniej, 8 mniej dokładnie, 6 bez zmiany. Braki pominięto; każda próba ma jednakową wagę.", 8.5)
    footer(1)
    doc.showPage()

    text(margin, height - 38, "Osoby, kolejne próby i sposób liczenia", 20, True)
    text(margin, height - 57, "Średnia pomyłka poniżej obejmuje dostępne pomiary danej osoby lub próby.", 10, color=muted)
    rows = [[item["person"], item["runs"], item["runs"],
             fmt(item["first"]["mae"]), fmt(item["second"]["mae"]), effect(item["change"])] for item in person_summary]
    bottom = table(height - 72,
                   ["Osoba", "Liczba prób\n1 zdjęcie", "Liczba prób\n2 zdjęcia", "Średnia\npomyłka [cm]\n1 zdjęcie", "Średnia\npomyłka [cm]\n2 zdjęcia", "Co daje\n2. zdjęcie?"],
                   rows, column_widths(6), row_height=15, delta_column=5,
                   delta_values=[item["change"] for item in person_summary])
    text(margin, bottom - 24, "Wyniki poszczególnych prób", 12, True)
    trial_rows = [[item["file"], item["person"], item["photos"], item["run"],
                   len(MEASUREMENTS) - item["n"], fmt(item["mae"]), fmt(item["bias"], True)] for item in trials]
    bottom = table(bottom - 40,
                   ["Plik", "Osoba", "Liczba\nzdjęć", "Numer\npróby", "Brakujące\nrzeczywiste\npomiary", "Średnia\npomyłka\n[cm]", "Zawyżenie /\nzaniżenie\n[cm]"],
                   trial_rows, column_widths(7), row_height=15)
    text(margin, bottom - 24, "Metoda i zakres", 12, True)
    notes = [
        "• Liczbę zdjęć i numer próby odczytano z nazw plików. Kolumn „Poprzednie” i „Zmiana” w PDF nie dodano jako prób.",
        "• Odczytano 252 pozycje: 202 z pomiarem rzeczywistym i 50 bez niego. Wszystkie dostępne różnice przeliczono i sprawdzono.",
        "• Główna tabela waży próby jednakowo. Excel zawiera także rozbicie na osoby i wymiary oraz wariant z równą wagą osób.",
        "• Łączny błąd jest średnią po dostępnych pozycjach. Klatkę i biust zachowano osobno; wzrost uwzględniono (wszędzie błąd 0).",
        "• PDF źródłowe przypisują wartości rzeczywiste do nazw według kolejności wierszy. W tym raporcie zachowano te przypisania.",
        "• Licznik sprawdza każde pole osobno. Pole bez wartości Siz3r lub pomiaru rzeczywistego jest pominięte w średniej i liczniku.",
    ]
    for index, note in enumerate(notes):
        text(margin, bottom - 40 - 12 * index, note, 8.5)
    footer(2)
    doc.save()


def main():
    records, inventory = extract()
    summary = []
    for name in MEASUREMENTS:
        first = stats([r for r in records if r["measurement"] == name and r["photos"] == 1])
        second = stats([r for r in records if r["measurement"] == name and r["photos"] == 2])
        summary.append(dict(measurement=name, first=first, second=second, change=second["mae"] - first["mae"]))
    overall = {photos: stats([r for r in records if r["photos"] == photos]) for photos in [1, 2]}
    person_dimensions, person_summary, trials = [], [], []
    for person in PEOPLE:
        groups = {photos: [r for r in records if r["person"] == person and r["photos"] == photos] for photos in [1, 2]}
        first, second = stats(groups[1]), stats(groups[2])
        run_counts = [len(set(r["run"] for r in groups[photos])) for photos in [1, 2]]
        if run_counts[0] != run_counts[1]:
            raise ValueError("Nierówna liczba prób między wariantami")
        person_summary.append(dict(person=person, runs=run_counts[0], first=first, second=second, change=second["mae"] - first["mae"]))
        for name in MEASUREMENTS:
            first = stats([r for r in groups[1] if r["measurement"] == name])
            second = stats([r for r in groups[2] if r["measurement"] == name])
            change = second["mae"] - first["mae"] if first["n"] and second["n"] else None
            person_dimensions.append(dict(person=person, measurement=name, first=first, second=second, change=change))
    for item in inventory:
        trials.append(dict(file=item["file"], person=item["person"], photos=item["photos"], run=item["run"],
                           **stats([r for r in records if r["file"] == item["file"]])))
    write_csv("Siz3r_srednie_roznice.csv",
              ["Mierzony wymiar", "Średnio o ile Siz3r się myli: 1 zdjęcie [cm]", "Średnio o ile Siz3r się myli: 2 zdjęcia [cm]", "Co daje 2. zdjęcie?", "Średnie zawyżenie lub zaniżenie: 1 zdjęcie [cm]", "Średnie zawyżenie lub zaniżenie: 2 zdjęcia [cm]", "Który wariant jest dokładniejszy?", "Liczba pomiarów z pełnymi danymi: razem (1 zdjęcie + 2 zdjęcia)"],
              [[i["measurement"], i["first"]["mae"], i["second"]["mae"], effect(i["change"]), i["first"]["bias"], i["second"]["bias"], winner(i["first"]["mae"], i["second"]["mae"]), used_measurements(i["first"], i["second"])] for i in summary])
    write_csv("Siz3r_dane_zrodlowe.csv", ["Plik", "Osoba", "Liczba zdjęć", "Próba", "Pomiar", "Siz3r [cm]", "Rzeczywisty [cm]", "Różnica [cm]", "Bezwzględna różnica [cm]"],
              [[r[k] for k in ["file", "person", "photos", "run", "measurement", "siz3r", "actual", "diff", "abs_diff"]] for r in records])
    make_workbook(records, inventory, summary, overall, person_dimensions, person_summary, trials)
    make_pdf(summary, overall, person_summary, trials)
    result = dict(records=records, files=inventory, summary=summary, overall=overall,
                  person_summary=person_summary, person_dimensions=person_dimensions, trials=trials)
    (OUT / "dane.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(dict(files=len(inventory), rows=len(records), valid=sum(completeness(r) == "OK" for r in records),
                          overall=overall, better=sum(i["change"] < 0 for i in summary), worse=sum(i["change"] > 0 for i in summary),
                          same=sum(i["change"] == 0 for i in summary)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
