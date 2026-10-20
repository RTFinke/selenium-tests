"""Create the finished, print-ready SIZ3R stationery and AIO questionnaire.

Uses the user's original PNG unchanged, embedded fonts and native PDF text.
Answer spaces are genuinely empty: no labels, borders, lines or form fields.
"""

from pathlib import Path
import shutil
import sys

from PIL import Image
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Paragraph
from reportlab.lib.utils import ImageReader
from xml.sax.saxutils import escape

OUT = Path(__file__).resolve().parent / "pdf-final"
OUT.mkdir(parents=True, exist_ok=True)
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / ".tmp-pdf-tools"))
import pymupdf as fitz

LOGO_ORIGINAL = Path(r"C:\Users\suici\Downloads\logoSiz3r.png")
LOGO = OUT / "assets" / "logoSiz3r.png"
LOGO.parent.mkdir(exist_ok=True)
shutil.copyfile(LOGO_ORIGINAL, LOGO)
assert LOGO.read_bytes() == LOGO_ORIGINAL.read_bytes()

pdfmetrics.registerFont(TTFont("Siz3rText", r"C:\Windows\Fonts\segoeui.ttf"))
pdfmetrics.registerFont(TTFont("Siz3rMedium", r"C:\Windows\Fonts\seguisb.ttf"))
pdfmetrics.registerFontFamily("Siz3rText", normal="Siz3rText", bold="Siz3rMedium")

PAGE_W, PAGE_H = A4
MM = 72 / 25.4
LEFT = 23 * MM
RIGHT = PAGE_W - LEFT
WIDTH = RIGHT - LEFT
GUTTER = 27
TEXT_X = LEFT + GUTTER
TEXT_W = RIGHT - TEXT_X
GREEN = colors.HexColor("#00D278")
INK = colors.HexColor("#17211D")
BODY = colors.HexColor("#35413B")
MUTED = colors.HexColor("#69766F")
RULE = colors.HexColor("#DDE5E0")

STYLES = {
    "title": ParagraphStyle("Title", fontName="Siz3rMedium", fontSize=21, leading=27, textColor=INK),
    "heading": ParagraphStyle("Heading", fontName="Siz3rMedium", fontSize=12.4, leading=17, textColor=INK),
    "question": ParagraphStyle("Question", fontName="Siz3rText", fontSize=10.8, leading=15.2, textColor=BODY),
    "body": ParagraphStyle("Body", fontName="Siz3rText", fontSize=10.5, leading=15.3, textColor=BODY),
    "name": ParagraphStyle("Name", fontName="Siz3rMedium", fontSize=11.2, leading=16, textColor=INK),
    "meta": ParagraphStyle("Meta", fontName="Siz3rText", fontSize=9.5, leading=14, textColor=MUTED),
    "label": ParagraphStyle("Label", fontName="Siz3rMedium", fontSize=8, leading=12, textColor=MUTED),
}

QUESTIONS = [
    ("Integracja z AtomStore i kwestie techniczne", [
        "Czy posiadają Państwo gotowy moduł / integrację z silnikiem AtomStore (np. w oparciu o API / widget JS)?",
        "Jak wdrożenie Państwa rozwiązania wpływa na wydajność i czas ładowania karty produktu?",
    ]),
    ("Wymagania dotyczące materiałów produktowych", [
        "Jakich materiałów potrzebują Państwo z naszej strony do digitalizacji asortymentu? Czy wystarczą standardowe zdjęcia produktowe, czy wymagane są specjalne sesje lub pliki 3D?",
    ]),
    ("Specyfika asortymentu BHP", [
        "Jak Państwa algorytmy radzą sobie ze specyficznym asortymentem (ciężkie kurtki robocze, obuwie bezpieczne, rękawice, elementy odblaskowe)?",
        "Czy AI zachowuje wierne odwzorowanie faktury materiału i detali ubrań?",
    ]),
    ("Ścieżka użytkownika (UX) i RODO", [
        "Czy klient końcowy do skorzystania z przymierzalni w naszym sklepie musi zakładać konto w Państwa zewnętrznym serwisie, czy przymiarka może odbywać się bezrejestracyjnie?",
        "Jak z formalnego punktu widzenia rozwiązana jest kwestia przetwarzania wizerunku użytkownika i zgód RODO (kto jest administratorem danych przesyłanych zdjęć)?",
    ]),
    ("Funkcjonalność (Wizualizacja vs. Dobór rozmiaru)", [
        "Czy narzędzie oferuje jedynie wizualizację wyglądu ubrania na sylwetce, czy sugeruje również konkretny rozmiar (np. M, L, XL) na podstawie wprowadzonych wymiarów klienta?",
    ]),
    ("Model biznesowy i koszty", [
        "Jak wygląda struktura cennika? Interesuje nas koszt przygotowania 1 produktu (digitalizacja), ewentualna opłata za wdrożenie techniczne oraz model bieżących rozliczeń (abonament / opłata za pojedyncze wygenerowane przymierzenie / inne).",
    ]),
    ("Próbka / Pilotaż", [
        "Czy istnieje możliwość bezpłatnego przetestowania narzędzia i przygotowania próbki wizualizacji na podstawie 2–3 przesłanych przez nas produktów?",
    ]),
]

ANSWER_REGIONS = []


def paragraph(canvas, text, top, style="body", x=LEFT, width=WIDTH):
    value = Paragraph(escape(text), STYLES[style])
    _, height = value.wrap(width, PAGE_H)
    value.drawOn(canvas, x, PAGE_H - top - height)
    return top + height


def header_footer(canvas, page_number=None, total=None):
    canvas.saveState()
    logo_width = 42 * MM
    with Image.open(LOGO) as image:
        logo_height = logo_width * image.height / image.width
    logo_top = 20 * MM
    canvas.drawImage(ImageReader(str(LOGO)), LEFT, PAGE_H - logo_top - logo_height,
                     width=logo_width, height=logo_height, mask="auto")
    canvas.setFillColor(INK)
    canvas.setFont("Siz3rMedium", 9)
    canvas.drawRightString(RIGHT, PAGE_H - logo_top - 10, "siz3r.com")
    canvas.setFillColor(MUTED)
    canvas.setFont("Siz3rText", 8.8)
    canvas.drawRightString(RIGHT, PAGE_H - logo_top - 24, "office@siz3r.com")
    canvas.linkURL("https://siz3r.com", (RIGHT-60, PAGE_H-logo_top-14, RIGHT, PAGE_H-logo_top), relative=0, thickness=0)
    canvas.linkURL("mailto:office@siz3r.com", (RIGHT-90, PAGE_H-logo_top-28, RIGHT, PAGE_H-logo_top-16), relative=0, thickness=0)

    separator_top = 105
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.5)
    canvas.line(LEFT, PAGE_H - separator_top, RIGHT, PAGE_H - separator_top)
    canvas.setStrokeColor(GREEN)
    canvas.setLineWidth(1.4)
    canvas.line(LEFT, PAGE_H - separator_top, LEFT + 32, PAGE_H - separator_top)

    footer_y = 77
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.45)
    canvas.line(LEFT, footer_y, RIGHT, footer_y)
    canvas.setFillColor(MUTED)
    canvas.setFont("Siz3rMedium", 7.8)
    canvas.drawString(LEFT, footer_y - 17, "Siz3r Sp. z o.o.")
    name_width = pdfmetrics.stringWidth("Siz3r Sp. z o.o.", "Siz3rMedium", 7.8)
    canvas.setFont("Siz3rText", 7.8)
    canvas.drawString(LEFT + name_width + 9, footer_y - 17, "ul. Stanisławowska 47 · 54-611 Wrocław")
    canvas.setFont("Siz3rText", 7.3)
    canvas.drawString(LEFT, footer_y - 29, "NIP: 894-313-42-44   ·   KRS: 0000754380   ·   REGON: 381639043")
    canvas.drawString(LEFT, footer_y - 41, "Kapitał zakładowy: 5 000 zł")
    if page_number is not None:
        canvas.setFont("Siz3rMedium", 8)
        canvas.drawRightString(RIGHT, footer_y - 17, f"{page_number} / {total}")
    canvas.restoreState()


def section(canvas, number, top, spaces, page_number):
    title, questions = QUESTIONS[number - 1]
    canvas.setFillColor(GREEN)
    canvas.setFont("Siz3rMedium", 10.5)
    canvas.drawString(LEFT, PAGE_H - top - 12.7, f"{number:02d}")
    top = paragraph(canvas, title, top, "heading", x=TEXT_X, width=TEXT_W) + 11
    for index, (question, space) in enumerate(zip(questions, spaces)):
        top = paragraph(canvas, question, top, "question", x=TEXT_X, width=TEXT_W)
        answer_top = top + 8
        answer_bottom = answer_top + space
        ANSWER_REGIONS.append((page_number, (TEXT_X, answer_top, RIGHT, answer_bottom), number, index))
        top = answer_bottom + 8
    return top


def make_letterhead():
    target = OUT / "Siz3r_Papier_firmowy.pdf"
    canvas = Canvas(str(target), pagesize=A4, pageCompression=1)
    canvas.setTitle("Siz3r — papier firmowy")
    canvas.setAuthor("Siz3r")
    canvas.setSubject("Papier firmowy A4 z pustym obszarem na treść")
    header_footer(canvas)
    canvas.showPage()
    canvas.save()
    return target


def make_aio():
    target = OUT / "Siz3r_AIO_Pytania_i_odpowiedzi.pdf"
    canvas = Canvas(str(target), pagesize=A4, pageCompression=1)
    canvas.setTitle("Siz3r — odpowiedź na zapytanie sklep.aio.com.pl")
    canvas.setAuthor("Siz3r")
    canvas.setSubject("Pytania klienta z pustym miejscem na odpowiedzi")

    header_footer(canvas, 1, 3)
    top = paragraph(canvas, "ADRESAT", 133, "label") + 5
    top = paragraph(canvas, "Bartłomiej Fitas", top, "name")
    top = paragraph(canvas, "Kierownik działu e-commerce", top, "meta")
    top = paragraph(canvas, "sklep.aio.com.pl", top, "meta") + 27
    top = paragraph(canvas, "Wirtualna przymierzalnia", top, "title") + 7
    top = paragraph(canvas, "Odpowiedź na zapytanie · sklep.aio.com.pl", top, "meta") + 21
    top = paragraph(canvas, "Szanowny Panie Bartłomieju,", top) + 8
    top = paragraph(canvas, "dziękujemy za zainteresowanie rozwiązaniem Siz3r. Poniżej przedstawiamy odpowiedzi na pytania dotyczące wdrożenia wirtualnej przymierzalni w Państwa sklepie.", top) + 25
    top = section(canvas, 1, top, [55, 55], 1) + 9
    top = section(canvas, 2, top, [65], 1)
    assert top < PAGE_H - 93, f"Page 1 content exceeds footer clearance: {top}"
    canvas.showPage()

    header_footer(canvas, 2, 3)
    top = paragraph(canvas, "ODPOWIEDŹ NA ZAPYTANIE · SKLEP.AIO.COM.PL", 133, "label") + 30
    top = section(canvas, 3, top, [80, 80], 2) + 18
    top = section(canvas, 4, top, [80, 80], 2)
    assert top < PAGE_H - 93, f"Page 2 content exceeds footer clearance: {top}"
    canvas.showPage()

    header_footer(canvas, 3, 3)
    top = paragraph(canvas, "ODPOWIEDŹ NA ZAPYTANIE · SKLEP.AIO.COM.PL", 133, "label") + 30
    top = section(canvas, 5, top, [65], 3) + 13
    top = section(canvas, 6, top, [78], 3) + 13
    top = section(canvas, 7, top, [65], 3) + 13
    top = paragraph(canvas, "Z poważaniem,", top, "body", x=TEXT_X, width=TEXT_W)
    assert top + 35 < PAGE_H - 93, f"Page 3 signature has insufficient room: {top}"
    canvas.showPage()
    canvas.save()
    return target


def verify_and_render(target, aio=False):
    with fitz.open(target) as pdf:
        assert len(pdf) == (3 if aio else 1)
        all_text = "\n".join(page.get_text() for page in pdf)
        assert "[" not in all_text and "]" not in all_text
        assert "Wpisz" not in all_text
        assert all("office@siz3r.com" in page.get_text() for page in pdf)
        assert all("Siz3r Sp. z o.o." in page.get_text() for page in pdf)
        for page in pdf:
            assert abs(page.rect.width - PAGE_W) < 0.1
            assert abs(page.rect.height - PAGE_H) < 0.1
            assert len(page.get_images()) >= 1
        if aio:
            normalize = lambda text: " ".join(text.split())
            normalized_text = normalize(all_text)
            for title, questions in QUESTIONS:
                assert normalize(title) in normalized_text
                for question in questions:
                    assert normalize(question) in normalized_text, question
            assert len(ANSWER_REGIONS) == 10
            for page_number, bounds, _, _ in ANSWER_REGIONS:
                rect = fitz.Rect(bounds)
                assert not pdf[page_number - 1].get_textbox(rect).strip(), bounds
        for index, page in enumerate(pdf):
            page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5)).save(OUT / f"{target.stem}_strona_{index+1}.png")
        print(f"OK: {target.name}; {len(pdf)} pages; original logo, embedded fonts, text and blank answer spaces verified.")


if __name__ == "__main__":
    verify_and_render(make_letterhead())
    verify_and_render(make_aio(), aio=True)
