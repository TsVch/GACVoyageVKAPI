"""Генерация PDF согласия на обработку персональных данных."""
from datetime import datetime
from pathlib import Path
import uuid
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

def _register_fonts() -> tuple[str, str]:
    try:
        pdfmetrics.registerFont(TTFont("DejaVu", "DejaVuSans.ttf"))
        pdfmetrics.registerFont(TTFont("DejaVu-Bold", "DejaVuSans-Bold.ttf"))
        return "DejaVu", "DejaVu-Bold"
    except Exception:
        return "Helvetica", "Helvetica-Bold"

def generate_consent_pdf(name: str, phone: str, output_dir: Path, preview: bool = False) -> str:
    normal_font, bold_font = _register_fonts()
    output_dir.mkdir(parents=True, exist_ok=True)
    if preview:
        filename = output_dir / "temp_consent.pdf"; full_name = "[ваше ФИО будет указано после ввода]"; phone_display = "[ваш телефон будет указан после ввода]"; date_display = "[дата]"; time_display = "[время]"
    else:
        filename = output_dir / f"consent_{uuid.uuid4()}.pdf"; full_name = name; phone_display = phone; date_display = datetime.now().strftime("%d.%m.%Y"); time_display = datetime.now().strftime("%H:%M")
    doc = SimpleDocTemplate(str(filename), pagesize=A4, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="TitleCenter", fontName=bold_font, fontSize=13, alignment=TA_CENTER, spaceAfter=12))
    styles.add(ParagraphStyle(name="Justify", fontName=normal_font, fontSize=11, alignment=TA_JUSTIFY, leading=15, spaceAfter=10))
    styles.add(ParagraphStyle(name="Section", fontName=bold_font, fontSize=11, spaceBefore=15, spaceAfter=8))
    story = [Paragraph("СОГЛАСИЕ", styles["TitleCenter"]), Paragraph("на обработку персональных данных", styles["TitleCenter"])]
    story.append(Paragraph(f"Я, {full_name}, (далее — Субъект персональных данных), в соответствии с Федеральным законом от 27.07.2006 № 152-ФЗ «О персональных данных», свободно, своей волей и в своем интересе даю согласие индивидуальному предпринимателю Шин Сергею Тимофеевичу (ИНН 621200217989), (далее — Оператор) на обработку своих персональных данных на следующих условиях:", styles["Justify"]))
    story += [Paragraph("1. ПЕРСОНАЛЬНЫЕ ДАННЫЕ", styles["Section"]), Paragraph("Настоящее согласие дается на обработку следующих персональных данных:", styles["Justify"]), Paragraph("— Фамилия, имя, отчество<br/>— Номер телефона", styles["Justify"]), Paragraph("2. ЦЕЛИ ОБРАБОТКИ", styles["Section"]), Paragraph("Обработка персональных данных осуществляется в целях:", styles["Justify"]), Paragraph("— Заключения и исполнения договора фрахтования<br/>— Оказания услуг по перевозке пассажиров<br/>— Связи с клиентом", styles["Justify"]), Paragraph("3. СПОСОБЫ ОБРАБОТКИ", styles["Section"]), Paragraph("Оператор осуществляет обработку персональных данных следующими способами:", styles["Justify"]), Paragraph("— Сбор, запись, систематизация, накопление, хранение<br/>— Использование, передача<br/>— Обезличивание, удаление, уничтожение", styles["Justify"]), Paragraph("4. СРОК ДЕЙСТВИЯ", styles["Section"]), Paragraph("Настоящее согласие действует с момента его подписания и до момента его отзыва субъектом персональных данных.", styles["Justify"]), Spacer(1, 20), Paragraph("Подпись субъекта персональных данных", styles["Section"]), Paragraph(f"<b>ФИО:</b> {full_name}<br/><b>Телефон:</b> {phone_display}<br/><b>Дата и время:</b> {date_display} {time_display}", styles["Justify"])]
    if not preview:
        story += [Spacer(1, 12), Paragraph("Подписано простой электронной подписью в соответствии с Федеральным законом от 06.04.2011 № 63-ФЗ «Об электронной подписи».", styles["Justify"])]
    doc.build(story)
    return str(filename)
