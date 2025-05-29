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

# Setup for WhatsApp delivery issue logging (for invalid numbers/no WhatsApp issues)
sel_whatsapp_issue_logger = logging.getLogger('sel_whatsapp_issues') 
sel_whatsapp_issue_logger.setLevel(logging.INFO)

if not sel_whatsapp_issue_logger.handlers:
    sel_issue_file_handler = logging.FileHandler('whatsapp_delivery_issues.log', encoding='utf-8')
    sel_issue_formatter = logging.Formatter('%(asctime)s - %(levelname)s - Phone: %(phone_number)s - Message Type: %(message_type)s - Reason: %(reason)s - Details: %(details)s')
    sel_issue_file_handler.setFormatter(sel_issue_formatter)
    sel_whatsapp_issue_logger.addHandler(sel_issue_file_handler)

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
        log_extra = {'phone_number': to, 'message_type': 'Selenium Send', 'reason': 'Initial send failed, possibly invalid number/no WhatsApp', 'details': str(e)}
        sel_whatsapp_issue_logger.warning("Initial WhatsApp send attempt failed.", extra=log_extra)
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
            log_extra_retry = {'phone_number': to, 'message_type': 'Selenium Send Retry', 'reason': 'Retry send failed, possibly invalid number/no WhatsApp', 'details': str(e2)}
            sel_whatsapp_issue_logger.error("Retry WhatsApp send attempt failed.", extra=log_extra_retry)
            logging.error(f"❌ we couldn`t resend the message {to}: {e2}")
            return False
# import os, re, time, threading, logging
# from datetime import datetime
# from selenium import webdriver
# from selenium.webdriver.chrome.options import Options
# from selenium.webdriver.chrome.service import Service
# from selenium.webdriver.common.by import By
# from selenium.webdriver.support.ui import WebDriverWait
# from selenium.webdriver.support import expected_conditions as EC
# # from webdriver_manager.chrome import ChromeDriverManager
# from urllib.parse import quote

# # إعداد سجل للأخطاء
# logging.basicConfig(
#     filename=os.path.abspath("./whatsapp_service.log"),
#     level=logging.INFO,
#     format='%(asctime)s %(levelname)s %(message)s'
# )

# PROFILE_DIR = os.path.abspath("./whatsapp_profile")
# os.makedirs(PROFILE_DIR, exist_ok=True)

# _driver = None
# _lock = threading.Lock()

# def is_valid_phone(phone):
#     """تحقق من صحة رقم الجوال الدولي (بصيغة واتساب)."""
#     digits = re.sub(r'\D', '', str(phone))
#     # يجب أن يكون الطول بين 10 و 15 رقم (حسب معايير واتساب)
#     return 10 <= len(digits) <= 15

# def format_phone(raw):
#     digits = re.sub(r'\D', '', raw)
#     if digits.startswith('0'):
#         digits = digits[1:]
#     return f"+20{digits}"

# def get_driver():
#     """إنشاء أو استرجاع الجلسة الدائمة لـ Chrome/Selenium."""
#     global _driver
#     with _lock:
#         if _driver is None:
#             print(_driver)
#             options = Options()
#             options.add_argument(f"--user-data-dir={PROFILE_DIR}")
#             options.add_argument("--start-maximized")
#             # أول مرة بدون headless حتى تسجل QR
#             try:
#                 _driver = webdriver.Chrome(
#                     # service=Service(ChromeDriverManager().install()),
#                     options=options
#                 )
#                 _driver.get("https://web.whatsapp.com/")
#                 logging.info("⌛ انتظر مسح QR في WhatsApp Web …")
#                 # ننتظر حتى يظهر مربع الكتابة في أي محادثة (يشير للدخول الناجح)
#                 WebDriverWait(_driver, 300).until(
#                     EC.presence_of_element_located((By.CSS_SELECTOR, "div[contenteditable='true']"))
#                 )
#                 logging.info("✅ جاهز لإرسال الرسائل.")
#             except Exception as e:
#                 logging.error(f"فشل إنشاء جلسة WhatsApp Web: {e}")
#                 if _driver:
#                     try: _driver.quit()
#                     except: pass
#                 _driver = None
#         return _driver

# def send_whatsapp_message(phone, message):
#     """
#     يرسل رسالة عبر الجلسة الدائمة:
#     - يتنقل للمحادثة.
#     - ينتظر زر الإرسال ثم ينقره.
#     - يعيد بدء الجلسة إذا تعطّلت.
#     """
#     if not is_valid_phone(phone):
#         logging.error(f"🚫 رقم غير صالح: {phone}")
#         return False
#     driver = get_driver()
#     if not driver:
#         logging.error("🚨 لا توجد جلسة جاهزة للرسائل.")
#         return False

#     to = format_phone(phone)
#     encoded_message = quote(message,safe='')  # ترميز الرسالة لتكون صالحة في URL
#     url = f"https://web.whatsapp.com/send?phone={to}&text={encoded_message}"


#     try:
#         driver.get(url)
#         send_btn = WebDriverWait(driver, 30).until(
#                 EC.element_to_be_clickable((By.XPATH, "//span[@data-icon='send']/parent::button"))
#             )
#         send_btn.click()
#         logging.info(f"📩 أرسلنا رسالة إلى {to} في {datetime.now().strftime('%H:%M:%S')}")
#         time.sleep(2)
#         return True

#     except Exception as e:
#         logging.warning(f"⚠️ تعطل الإرسال إلى {to}: {e} — المحاولة بإعادة تشغيل الجلسة")
#         # إعادة محاولة بإعادة إنشاء الجلسة
#         try:
#             with _lock:
#                 if _driver:
#                     _driver.quit()
#                 _driver = None
#         except:
#             pass
#         # محاولة ثانية
#         driver = get_driver()
#         if not driver:
#             return False
#         try:
#             print('try selm')
#             driver.get(url)
#             send_btn = WebDriverWait(driver, 30).until(
#                 EC.element_to_be_clickable((By.XPATH, "//span[@data-icon='send']/parent::button"))
#             )
#             send_btn.click()
#             logging.info(f"🔁 resending succesful {to}")
#             time.sleep(2)
#             return True
#         except Exception as e2:
#             logging.error(f"❌ we couldn`t resend the message {to}: {e2}")
#             return False
