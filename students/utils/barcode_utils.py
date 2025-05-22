import os
import barcode
from barcode.writer import ImageWriter
from django.conf import settings

def generate_barcode_image(barcode_number):
    barcode_folder = os.path.join(settings.MEDIA_ROOT, 'barcodes')
    os.makedirs(barcode_folder, exist_ok=True)

    filepath = os.path.join(barcode_folder, f"{barcode_number}")
    code128 = barcode.get('code128', barcode_number, writer=ImageWriter())
    full_path = code128.save(filepath)  # يحفظ كـ .png تلقائيًا
    return full_path  