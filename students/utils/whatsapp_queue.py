import os
import csv
import logging
import threading
import queue
import time
from datetime import datetime
from .whatsapp_Sel import send_whatsapp_message  # وحدّد هذا المسار بدقّة حسب مشروعك

# إعداد سجلّ الأخطاء
logger = logging.getLogger('whatsapp_issues')
logger.setLevel(logging.INFO)

# مسار ملف CSV لحفظ محاولات الإرسال الفاشلة
FAILED_CSV = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'failed_whatsapp_deliveries.csv'))
# التأكد من وجود الملف وكتابة العناوين إذا لم يكن موجودًا
if not os.path.exists(FAILED_CSV):
    os.makedirs(os.path.dirname(FAILED_CSV), exist_ok=True)
    with open(FAILED_CSV, mode='w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['timestamp', 'phone', 'message_type', 'reason', 'details'])

# دالة مساعدة لتسجيل الفشل في ملف CSV
def log_failed_delivery(phone, message_type, reason, details=""):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with open(FAILED_CSV, mode='a', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([timestamp, phone, message_type, reason, details])

# إذا أردت حقول إضافية دائماً
class ContextFilter(logging.Filter):
    def filter(self, record):
        for attr in ('student_id','student_name','message_type','reason'):
            if not hasattr(record, attr):
                setattr(record, attr, '-')
        return True

if not logger.handlers:
    fh = logging.FileHandler('whatsapp_delivery_issues.log', encoding='utf-8')
    fmt = '%(asctime)s - %(levelname)s - Student ID: %(student_id)s (Name: %(student_name)s) - Message Type: %(message_type)s - Reason: %(reason)s'
    fh.setFormatter(logging.Formatter(fmt))
    logger.addHandler(fh)
    logger.addFilter(ContextFilter())

# طابور الرسائل وخيط المعالجة
_message_queue = queue.Queue()

def queue_whatsapp_message(phone, text, **log_context):
    """أضف رسالة إلى الطابور باستخدام سياق تسجيل (student_id, message_type, …)."""
    _message_queue.put((phone, text, log_context))


def _worker():
    # استدعِ الدالة هنا لتفادي دوائر الاستيراد
    from .whatsapp_queue import send_whatsapp_message
    while True:
        phone, text, ctx = _message_queue.get()
        success = False
        try:
            if send_whatsapp_message(phone, text):
                success = True
            else:
                ctx.setdefault('reason', 'Unknown failure')
        except Exception as e:
            ctx.setdefault('reason', str(e))
        finally:
            if not success:
                # سجل في لوج
                logger.info("WhatsApp not sent.", extra=ctx)
                # سجل في CSV
                log_failed_delivery(
                    phone,
                    ctx.get('message_type', 'Unknown'),
                    ctx.get('reason', 'Unknown failure'),
                    ctx.get('details', '')
                )
            _message_queue.task_done()
            time.sleep(1)

# إطلاق الخيط عند استيراد الوحدة
threading.Thread(target=_worker, daemon=True).start()
