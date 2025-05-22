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
