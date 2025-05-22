
import os
from io import BytesIO
import arabic_reshaper
from bidi.algorithm import get_display
from django.conf import settings
from reportlab.lib.pagesizes import A6
from reportlab.lib.units import mm
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, Image, SimpleDocTemplate, Spacer
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Table, TableStyle

import barcode
from barcode.writer import ImageWriter
from PIL import Image as PILImage

# 1) سجّل الخط العربي (مسار الخط لديك)
pdfmetrics.registerFont(TTFont('Tajawal', 'static/fonts/Tajawal-Black.ttf'))

# 2) إعداد الأنماط
styles = getSampleStyleSheet()
arabic_style = ParagraphStyle(
    'Arabic',
    parent=styles['Normal'],
    fontName='Tajawal',
    fontSize=14,
    leading=18,
    rightIndent=0,
    alignment=2,   # 2 = right‑align
)

def reshape(text):
    reshaped = arabic_reshaper.reshape(text)
    return get_display(reshaped)

def generate_student_card_pdf(student):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A6,
                            rightMargin=10*mm, leftMargin=10*mm,
                            topMargin=10*mm, bottomMargin=10*mm)

    width, height = A6

    # ——— إعداد اللوجو
    logo_path = os.path.join(settings.BASE_DIR, 'static', 'logo.jpg')
    if os.path.exists(logo_path):
        logo = Image(logo_path, width=20*mm, height=20*mm)  # حجم صغير
    else:
        logo = Spacer(1, 20*mm)

    # ——— إعداد اسم الطالب
    name_para = Paragraph(reshape(student.name), arabic_style)

    # نجمع اللوجو والاسم في عمود واحد
    right_column = [logo, Spacer(1, 2*mm), name_para]

    # ——— إعداد الباركود كما في كودك الأصلي
    CODE128 = barcode.get_barcode_class('code128')
    bc_io = BytesIO()
    CODE128(student.barcode, writer=ImageWriter()).write(
        bc_io, {"module_height": 10.0, "font_size": 8}
    )
    bc_io.seek(0)
    bc_pil = PILImage.open(bc_io)
    tmp_bc = BytesIO()
    bc_pil.save(tmp_bc, format='PNG')
    tmp_bc.seek(0)
    # نجعل عرض الباركود تقريباً 60% من عرض الكارت
    bc_width = (width - 20*mm) * 0.6
    bc_height = bc_width * bc_pil.height / bc_pil.width
    bc_flow = Image(tmp_bc, width=bc_width, height=bc_height)

    # ——— نبني الجدول ثنائي الأعمدة
    data = [[right_column, bc_flow]]
    table = Table(
        data,
        colWidths=[(width - 20*mm) * 0.4, (width - 20*mm) * 0.6],
        hAlign='CENTER'
    )
    table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ALIGN',  (0, 0), (0, 0), 'RIGHT'),   # اللوجو والاسم يمين
        ('ALIGN',  (1, 0), (1, 0), 'LEFT'),    # الباركود يسار
        ('INNERGRID', (0,0), (-1,-1), 0, None),
        ('BOX',       (0,0), (-1,-1), 0, None),
    ]))

    # ——— نبني المستند
    story = [table, Spacer(1, 5*mm)]
    # اسم المؤسسة أسفل الكارت
    org_para = Paragraph(reshape("مؤسسة التعليم الحديث"), arabic_style)
    story.append(org_para)

    doc.build(story)
    buffer.seek(0)
    return buffer

# def generate_student_card_pdf(student):
#     """
#     يولّد PDF بحجم A6 يحتوي على:
#     • شعار
#     • اسم الطالب (عربي صحيح)
#     • باركود
#     • اسم المؤسسة
#     """
#     buffer = BytesIO()
#     doc = SimpleDocTemplate(buffer, pagesize=A6,
#                             rightMargin=10*mm, leftMargin=10*mm,
#                             topMargin=10*mm, bottomMargin=10*mm)

#     story = []
#     width, height = A6

#     # شعار المؤسسة
#     logo_path = os.path.join(settings.BASE_DIR, 'static', 'logo.jpg')
#     if os.path.exists(logo_path):
#         # استخدم Flowable Image
#         img = Image(logo_path, width=25*mm, height=25*mm)
#         story.append(img)
#     story.append(Spacer(1, 5*mm))

#     # اسم الطالب
#     name_para = Paragraph(reshape(student.name), arabic_style)
#     story.append(name_para)
#     story.append(Spacer(1, 5*mm))

#     # باركود: نحول أولاً إلى صورة ثم نحفظها مؤقتًا ونستخدم Flowable Image
#     CODE128 = barcode.get_barcode_class('code128')
#     bc_io = BytesIO()
#     CODE128(student.barcode, writer=ImageWriter()).write(
#         bc_io, {"module_height": 10.0, "font_size": 8}
#     )
#     bc_io.seek(0)
#     bc_pil = PILImage.open(bc_io)
#     # احفظ مؤقتًا صورة الباركود
#     tmp_bc = BytesIO()
#     bc_pil.save(tmp_bc, format='PNG')
#     tmp_bc.seek(0)
#     bc_flow = Image(tmp_bc, width=width-20*mm, height=(width-20*mm) * bc_pil.height/bc_pil.width)
#     story.append(bc_flow)
#     story.append(Spacer(1, 5*mm))

#     # اسم المؤسسة أسفل الكارت
#     org_para = Paragraph(reshape("مؤسسة التعليم الحديث"), arabic_style)
#     story.append(org_para)

#     # نبني المستند
#     doc.build(story)
#     buffer.seek(0)
    return buffer
