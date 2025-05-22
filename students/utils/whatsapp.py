import pywhatkit
import pyautogui
import re
import time
from datetime import datetime, timedelta

def format_phone(raw_phone):
    digits = re.sub(r'\D', '', raw_phone)
    if digits.startswith('0'):
        digits = digits[1:]
    return f"+20{digits}"

def send_whatsapp_free(raw_phone, message):
    to = format_phone(raw_phone)

    # 1) حساب وقت الإرسال بعد دقيقة لتجنّب تأخيرات التحميل
    now = datetime.now()
    send_time = now + timedelta(minutes=1)
    if now.second > 50:
        send_time += timedelta(minutes=1)
    hour, minute = send_time.hour, send_time.minute

    # 2) فتح WhatsApp Web وكتابة الرسالة
    pywhatkit.sendwhatmsg(to, message, hour, minute, wait_time=10, tab_close=False)

    # 3) الانتظار حتى تُحمَّل الصفحة وحقل الرسالة
    #    (10s wait_time + 5s تحميل إضافي)
    time.sleep(15)

    # 4) الضغط على Enter لإرسال الرسالة
    pyautogui.press('enter')

    # 5) إغلاق التبويب التلقائي بعد الإرسال
    time.sleep(2)
    pyautogui.hotkey('ctrl', 'w')

    return send_time
# import pywhatkit
# import re
# from datetime import datetime, timedelta

# def format_phone(raw_phone):
#     digits = re.sub(r'\D', '', raw_phone)
#     if digits.startswith('0'):
#         digits = digits[1:]
#     return f"+20{digits}"


# def send_whatsapp_free(raw_phone, message):
#     to = format_phone(raw_phone)

#     # 1) حساب متى نرسل الرسالة
#     now = datetime.now()
#     # نريد الإرسال بعد دقيقة واحدة (لتفادي تأخيرات التحميل)
#     send_time = now + timedelta(minutes=1)

#     # إذا وصلت الثواني إلى أكثر من 50، نزود دقيقة إضافية
#     if now.second > 50:
#         send_time += timedelta(minutes=1)

#     hour = send_time.hour
#     minute = send_time.minute

#     # 2) نفّذ pywhatkit
#     # wait_time أقل ما يمكن (مثلاً 10 ثوانٍ) لتقليل وقت التحميل
#     pywhatkit.sendwhatmsg(to, message, hour, minute, wait_time=10, tab_close=True)

#     # 3) أرجع وقت الإرسال ليعلمه الـ view
#     return send_time

# def send_whatsapp_free(raw_phone, message):
#     to = format_phone(raw_phone)
    
#     # حساب الوقت بعد دقيقة واحدة من الآن
#     now = datetime.now() + timedelta(minutes=1)
#     hour = now.hour
#     minute = now.minute

#     # إرسال بعد دقيقة تلقائياً
#     pywhatkit.sendwhatmsg(to, message, hour, minute, wait_time=20, tab_close=True)
# def send_whatsapp_free(raw_phone, message):
#     to = format_phone(raw_phone)
    
#     # حساب الوقت بعد دقيقة واحدة من الآن
#     now = datetime.now() + timedelta(minutes=1)
#     hour = now.hour
#     minute = now.minute

#     # إرسال بعد دقيقة تلقائياً
#     pywhatkit.sendwhatmsg(to, message, hour, minute, wait_time=20, tab_close=True)
