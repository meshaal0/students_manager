import os, re, time, threading, logging
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
# from webdriver_manager.chrome import ChromeDriverManager
from urllib.parse import quote

# إعداد سجل للأخطاء
logging.basicConfig(
    filename=os.path.abspath("./whatsapp_service.log"),
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)

PROFILE_DIR = os.path.abspath("./whatsapp_profile")
os.makedirs(PROFILE_DIR, exist_ok=True)

_driver = None
_lock = threading.Lock()

def is_valid_phone(phone):
    """تحقق من صحة رقم الجوال الدولي (بصيغة واتساب)."""
    digits = re.sub(r'\D', '', str(phone))
    # يجب أن يكون الطول بين 10 و 15 رقم (حسب معايير واتساب)
    return 10 <= len(digits) <= 15

def format_phone(raw):
    digits = re.sub(r'\D', '', raw)
    if digits.startswith('0'):
        digits = digits[1:]
    return f"+20{digits}"

def get_driver():
    """إنشاء أو استرجاع الجلسة الدائمة لـ Chrome/Selenium."""
    global _driver
    with _lock:
        if _driver is None:
            print(_driver)
            options = Options()
            options.add_argument(f"--user-data-dir={PROFILE_DIR}")
            options.add_argument("--start-maximized")
            # أول مرة بدون headless حتى تسجل QR
            try:
                _driver = webdriver.Chrome(
                    # service=Service(ChromeDriverManager().install()),
                    options=options
                )
                _driver.get("https://web.whatsapp.com/")
                logging.info("⌛ انتظر مسح QR في WhatsApp Web …")
                # ننتظر حتى يظهر مربع الكتابة في أي محادثة (يشير للدخول الناجح)
                WebDriverWait(_driver, 300).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "div[contenteditable='true']"))
                )
                logging.info("✅ جاهز لإرسال الرسائل.")
            except Exception as e:
                logging.error(f"فشل إنشاء جلسة WhatsApp Web: {e}")
                if _driver:
                    try: _driver.quit()
                    except: pass
                _driver = None
        return _driver

def send_whatsapp_message(phone, message):
    """
    يرسل رسالة عبر الجلسة الدائمة:
    - يتنقل للمحادثة.
    - ينتظر زر الإرسال ثم ينقره.
    - يعيد بدء الجلسة إذا تعطّلت.
    """
    if not is_valid_phone(phone):
        logging.error(f"🚫 رقم غير صالح: {phone}")
        return False
    driver = get_driver()
    if not driver:
        logging.error("🚨 لا توجد جلسة جاهزة للرسائل.")
        return False

    to = format_phone(phone)
    encoded_message = quote(message,safe='')  # ترميز الرسالة لتكون صالحة في URL
    url = f"https://web.whatsapp.com/send?phone={to}&text={encoded_message}"


    try:
        driver.get(url)
        send_btn = WebDriverWait(driver, 30).until(
                EC.element_to_be_clickable((By.XPATH, "//span[@data-icon='send']/parent::button"))
            )
        send_btn.click()
        logging.info(f"📩 أرسلنا رسالة إلى {to} في {datetime.now().strftime('%H:%M:%S')}")
        time.sleep(2)
        return True

    except Exception as e:
        logging.warning(f"⚠️ تعطل الإرسال إلى {to}: {e} — المحاولة بإعادة تشغيل الجلسة")
        # إعادة محاولة بإعادة إنشاء الجلسة
        try:
            with _lock:
                if _driver:
                    _driver.quit()
                _driver = None
        except:
            pass
        # محاولة ثانية
        driver = get_driver()
        if not driver:
            return False
        try:
            print('try selm')
            driver.get(url)
            send_btn = WebDriverWait(driver, 30).until(
                EC.element_to_be_clickable((By.XPATH, "//span[@data-icon='send']/parent::button"))
            )
            send_btn.click()
            logging.info(f"🔁 resending succesful {to}")
            time.sleep(2)
            return True
        except Exception as e2:
            logging.error(f"❌ we couldn`t resend the message {to}: {e2}")
            return False

# # utils/whatsapp.py
# import os
# import re
# import time
# from datetime import datetime
# from selenium import webdriver
# from selenium.webdriver.chrome.options import Options
# from selenium.webdriver.chrome.service import Service
# from selenium.webdriver.common.by import By
# from selenium.webdriver.support.ui import WebDriverWait
# from selenium.webdriver.support import expected_conditions as EC
# from webdriver_manager.chrome import ChromeDriverManager

# # مسار مجلد الجلسة (نفس المسار بعد init_whatsapp_session)
# PROFILE_DIR = os.path.abspath("./whatsapp_profile")
# os.makedirs(PROFILE_DIR, exist_ok=True)

# def format_phone(raw_phone):
#     digits = re.sub(r'\D', '', raw_phone)
#     if digits.startswith('0'):
#         digits = digits[1:]
#     return f"+20{digits}"

# def send_whatsapp_free(raw_phone, message):
#     to = format_phone(raw_phone)

#     # 1) إعداد ChromeOptions
#     options = Options()
#     options.add_argument(f"--user-data-dir={PROFILE_DIR}")
#     options.add_argument("--start-maximized")
#     # لا تستخدم headless هنا

#     driver = None
#     try:
#         # 2) شغّل ChromeDriver المناسب تلقائيًا
#         service = Service(ChromeDriverManager().install())
#         driver = webdriver.Chrome(service=service, options=options)

#         # 3) افتح رابط المحادثة مع الرسالة مُضمّنة في الـ URL
#         url = f"https://web.whatsapp.com/send?phone={to}&text={message}"
#         driver.get(url)

#         # 4) انتظر ظهور زر الإرسال (button[data-testid="compose-btn-send"])
#         send_btn = WebDriverWait(driver, 30).until(
#             EC.element_to_be_clickable((By.XPATH, "//span[@data-icon='send']/parent::button"))
#         )
#         send_btn.click()


#         # 5) اضغط الزر لإرسال الرسالة
#         print("✅ DONE")

#         # 6) مهلة إضافية للتأكد من خروج الرسالة على الواجهة
#         time.sleep(5)

#         driver.quit()
#         return datetime.now()

#     except Exception as e:
#         print("❌ FAIL", e)
#         if driver:
#             try: driver.quit()
#             except: pass
#         return None
