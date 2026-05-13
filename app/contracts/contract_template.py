"""Генерация PDF договора фрахтования."""
from datetime import datetime
from pathlib import Path
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import registerFontFamily
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
EXECUTOR = {"name": "ИП Шин Сергей Тимофеевич", "inn": "621200217989", "car": "GAC M8", "car_type": "M1", "plate": "В412УМ62"}
def _register_fonts() -> tuple[str, str]:
    try:
        pdfmetrics.registerFont(TTFont("DejaVu", "DejaVuSans.ttf")); pdfmetrics.registerFont(TTFont("DejaVu-Bold", "DejaVuSans-Bold.ttf")); registerFontFamily("DejaVu", normal="DejaVu", bold="DejaVu-Bold"); return "DejaVu", "DejaVu-Bold"
    except Exception:
        return "Helvetica", "Helvetica-Bold"
def generate_contract_pdf(
    order: dict,
    output_dir: Path,
    signed: bool = True,
    filename: str | None = None
) -> str:
    normal_font, bold_font = _register_fonts(); output_dir.mkdir(parents=True, exist_ok=True);
    pdf_name = filename or f"contract_{order['booking_id']}.pdf"
    filename = output_dir / pdf_name
    doc = SimpleDocTemplate(str(filename), pagesize=A4, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
    styles = getSampleStyleSheet(); styles.add(ParagraphStyle(name="TitleCenter", fontName=bold_font, fontSize=13, alignment=TA_CENTER, spaceAfter=12)); styles.add(ParagraphStyle(name="Justify", fontName=normal_font, fontSize=11, alignment=TA_JUSTIFY, leading=15, spaceAfter=10)); styles.add(ParagraphStyle(name="Section", fontName=bold_font, fontSize=11, spaceBefore=15, spaceAfter=8))
    story = [Paragraph(f"Договор фрахтования № {order['booking_id']}", styles['TitleCenter']), Paragraph("транспортного средства для перевозки пассажиров", styles['TitleCenter']), Paragraph(f"{EXECUTOR['name']}, ИНН {EXECUTOR['inn']}, именуемый в дальнейшем Фрахтовщик, и {order['name']}, именуемый в дальнейшем Фрахтователь, заключили настоящий договор о нижеследующем:", styles['Justify']), Paragraph(f"1.1. Фрахтовщик обязуется за плату в размере <b>{order['price']}</b> рублей предоставить Фрахтователю всю вместимость транспортного средства для перевозки пассажиров и багажа.", styles['Justify']), Paragraph(f"<b>1.4. Срок выполнения перевозки:</b> {order['date']}.", styles['Justify']), Paragraph("1.5. Транспортное средство:", styles['Section']), Paragraph(f"Марка и модель: {EXECUTOR['car']}<br/>Тип ТС: {EXECUTOR['car_type']}<br/>Государственный номер: {EXECUTOR['plate']}", styles['Justify']), Spacer(1, 20), Paragraph("Реквизиты и подписи сторон", styles['TitleCenter'])]
    sign_time = datetime.now().strftime("%d.%m.%Y %H:%M") if signed else ""; left_party = f"<b>{EXECUTOR['name']}</b><br/><b>ИНН:</b> {EXECUTOR['inn']}"; right_party = f"<b>ФИО:</b> {order['name']}<br/><b>Телефон</b>: {order['phone']}"
    if signed:
        s = f"<br/><br/>Подписано простой электронной подписью {sign_time} в соответствии с Федеральным законом от 06.04.2011 № 63-ФЗ «Об электронной подписи»"; left_party += s; right_party += s
    table = Table([[Paragraph("<b>Фрахтовщик</b>", styles['Justify']), Paragraph("<b>Фрахтователь</b>", styles['Justify'])], [Paragraph(left_party, styles['Justify']), Paragraph(right_party, styles['Justify'])]], colWidths=[250, 250])
    table.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.5, colors.black), ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.black), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke)])); story.append(table); doc.build(story)
    return str(filename)
