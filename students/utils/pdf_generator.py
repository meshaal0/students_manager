from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from .barcode_utils import generate_barcode_image
from io import BytesIO
from django.conf import settings
from ..models import Students
import os

def generate_barcodes_pdf():
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    students = Students.objects.all()
    x, y = 50, height - 100

    for student in students:
        # توليد الصورة في media/barcodes/
        full_path = generate_barcode_image(student.barcode)

        # رسم الاسم والباركود في الـ PDF
        c.drawString(x, y, f"{student.name} - {student.barcode}")
        c.drawImage(full_path, x, y - 50, width=200, height=50)

        y -= 120
        
        if y < 100:
            c.showPage()
            y = height - 100

    c.save()
    buffer.seek(0)
    return buffer
