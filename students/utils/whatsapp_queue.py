import threading, queue, time
from .whatsapp_Sel import send_whatsapp_message

# قائمة انتظار للرسائل
message_queue = queue.Queue()

def message_worker():
    while True:
        message_data = message_queue.get()
        
        # التحقق من نوع البيانات المستلمة
        if isinstance(message_data, tuple) and len(message_data) == 2:
            # الطريقة القديمة (phone, message)
            phone, message = message_data
            student_name = None
        elif isinstance(message_data, tuple) and len(message_data) == 3:
            # الطريقة الجديدة (phone, message, student_name)
            phone, message, student_name = message_data
        else:
            print(f"🚨 تنسيق بيانات غير صالح في قائمة الانتظار: {message_data}")
            message_queue.task_done()
            continue
        
        try:
            print(f"📨 إرسال رسالة إلى {phone} {'للطالب ' + student_name if student_name else ''} …")
            success = send_whatsapp_message(phone, message, student_name)
            if success:
                print(f"✅ تم الإرسال بنجاح {'للطالب ' + student_name if student_name else ''}.")
            else:
                print(f"❌ فشل الإرسال {'للطالب ' + student_name if student_name else ''}.")
        except Exception as e:
            print(f"🚨 خطأ في معالجة رسالة لـ {phone} {'للطالب ' + student_name if student_name else ''}: {e}")
        finally:
            message_queue.task_done()
            time.sleep(1)  # تأخير بسيط بين الرسائل

# تشغيل الخيط الدائم
worker_thread = threading.Thread(target=message_worker, daemon=True)
worker_thread.start()

def queue_whatsapp_message(phone, message, student_name=None):
    """
    أضف رسالة إلى قائمة الانتظار.
    
    Args:
        phone: رقم الهاتف
        message: نص الرسالة
        student_name: اسم الطالب (اختياري) - يساعد في التتبع والتسجيل
    """
    if student_name:
        message_queue.put((phone, message, student_name))
    else:
        message_queue.put((phone, message))

# دالة للتوافق مع الإصدارات السابقة
def queue_whatsapp_message_old(phone, message):
    """دالة للتوافق مع الطريقة القديمة"""
    queue_whatsapp_message(phone, message)
    
# import threading, queue, time
# from .whatsapp_Sel import send_whatsapp_message

# # قائمة انتظار للرسائل
# message_queue = queue.Queue()

# def message_worker():
#     while True:
#         phone, message = message_queue.get()
#         try:
#             print(f"📨 إرسال رسالة إلى {phone} …")
#             success = send_whatsapp_message(phone, message)
#             if success:
#                 print("✅ تم الإرسال.")
#             else:
#                 print("❌ فشل الإرسال.")
#         except Exception as e:
#             print(f"🚨 خطأ في معالجة رسالة لـ {phone}: {e}")
#         finally:
#             message_queue.task_done()
#             time.sleep(1)  # تأخير بسيط بين الرسائل

# # تشغيل الخيط الدائم
# worker_thread = threading.Thread(target=message_worker, daemon=True)
# worker_thread.start()

# def queue_whatsapp_message(phone, message):
#     """أضف رسالة إلى قائمة الانتظار."""
#     message_queue.put((phone, message))
