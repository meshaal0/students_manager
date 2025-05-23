import threading, queue, time
from .whatsapp_Sel import send_whatsapp_message

# قائمة انتظار للرسائل
message_queue = queue.Queue()

def message_worker():
    while True:
        phone, message = message_queue.get()
        try:
            print(f"📨 إرسال رسالة إلى {phone} …")
            success = send_whatsapp_message(phone, message)
            if success:
                print("✅ تم الإرسال.")
            else:
                print("❌ فشل الإرسال.")
        except Exception as e:
            print(f"🚨 خطأ في معالجة رسالة لـ {phone}: {e}")
        finally:
            message_queue.task_done()
            time.sleep(1)  # تأخير بسيط بين الرسائل

# تشغيل الخيط الدائم
worker_thread = threading.Thread(target=message_worker, daemon=True)
worker_thread.start()

def queue_whatsapp_message(phone, message):
    """أضف رسالة إلى قائمة الانتظار."""
    message_queue.put((phone, message))

def send_low_recent_attendance_warning(student_name, father_phone, rate, period_days):
    """
    Constructs and queues a message for consistently low attendance.
    """
    text = (
        f"👋 *مرحباً ولي أمر الطالب {student_name}،*\n\n"
        f" لاحظنا أن نسبة حضور {student_name} كانت {rate:.0f}% خلال آخر {period_days} يوم دراسي.\n"
        f"نرجو التواصل معنا لمناقشة أي تحديات قد تواجه {student_name} لضمان انتظامه في الحضور.\n\n"
        f"مع تحيات،\n*م. عبدالله عمر*"
    )
    queue_whatsapp_message(father_phone, text)

def send_high_risk_alert(student_name, father_phone, reasons):
    """
    Constructs and queues a message for students identified as high risk.
    'reasons' is currently not used in the message to keep it soft, but available for future enhancements.
    """
    # reason_summary = reasons[0] if reasons and isinstance(reasons, list) and reasons[0] else "مستوى الحضور والمشاركة"
    text = (
        f"👋 *مرحباً ولي أمر الطالب {student_name}،*\n\n"
        f"نود التواصل معكم لمناقشة مستوى مشاركة وحضور {student_name} في الفترة الأخيرة.\n"
        f"يرجى التواصل معنا في أقرب فرصة مناسبة لكم لنتعاون سوياً في دعمه.\n\n"
        f"مع تحيات،\n*م. عبدالله عمر*"
    )
    queue_whatsapp_message(father_phone, text)
