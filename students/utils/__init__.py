# This file makes the 'utils' directory a Python package.

# Import functions from utils.py to make them accessible
# via the 'students.utils' namespace.
from .barcode_utils import generate_barcode_image
from .pdf_generator import generate_barcodes_pdf
from .whatsapp import send_whatsapp_message_immediately
from .whatsapp_queue import queue_whatsapp_message
from .whatsapp_Sel import send_whatsapp_message
from .utils import (
    get_daily_attendance_summary,
    get_absent_students_today,
    get_student_remaining_free_tries,
    get_students_paid_current_month,
    get_students_with_overdue_payments,
    process_student_payment,
    get_monthly_attendance_rate,
    get_attendance_trends,
    get_student_payment_history,
    get_revenue_trends,
    process_message_template, # تصدير الدالة الجديدة
    get_default_template_context, # تصدير الدالة الجديدة
)


# Optionally, define __all__ to specify what is exported
# when 'from students.utils import *' is used.
__all__ = [
    'generate_barcode_image',
    'generate_barcodes_pdf',
    'send_whatsapp_message_immediately',
    'queue_whatsapp_message',
    'send_whatsapp_message',
    'get_daily_attendance_summary',
    'get_absent_students_today',
    'get_student_remaining_free_tries',
    'get_students_paid_current_month',
    'get_students_with_overdue_payments',
    'process_student_payment',
    'get_monthly_attendance_rate',
    'get_attendance_trends',
    'get_student_payment_history',
    'get_revenue_trends',
    'process_message_template', # إضافة الدالة الجديدة إلى __all__
    'get_default_template_context', # إضافة الدالة الجديدة إلى __all__
]
