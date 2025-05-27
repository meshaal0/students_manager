import os, re, time, threading, logging, json
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from urllib.parse import quote

# إعداد سجل للأخطاء
logging.basicConfig(
    filename=os.path.abspath("./whatsapp_service.log"),
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)

PROFILE_DIR = os.path.abspath("./whatsapp_profile")
FAILED_NUMBERS_FILE = os.path.abspath("./failed_whatsapp_numbers.json")
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

def log_failed_number(phone, student_name=None, error_type="unknown", error_message=""):
    """
    يسجل الأرقام الفاشلة في ملف JSON مع معلومات الطالب
    """
    try:
        # قراءة البيانات الموجودة أو إنشاء قائمة فارغة
        if os.path.exists(FAILED_NUMBERS_FILE):
            with open(FAILED_NUMBERS_FILE, 'r', encoding='utf-8') as f:
                failed_data = json.load(f)
        else:
            failed_data = []
        
        # إعداد بيانات الخطأ الجديد
        failure_record = {
            "timestamp": datetime.now().isoformat(),
            "phone": phone,
            "student_name": student_name,
            "error_type": error_type,
            "error_message": error_message,
            "attempts": 1
        }
        
        # البحث عن الرقم في السجلات الموجودة
        existing_record = None
        for record in failed_data:
            if record["phone"] == phone:
                existing_record = record
                break
        
        if existing_record:
            # تحديث السجل الموجود
            existing_record["attempts"] += 1
            existing_record["last_attempt"] = datetime.now().isoformat()
            existing_record["latest_error"] = error_message
        else:
            # إضافة سجل جديد
            failed_data.append(failure_record)
        
        # حفظ البيانات المحدثة
        with open(FAILED_NUMBERS_FILE, 'w', encoding='utf-8') as f:
            json.dump(failed_data, f, ensure_ascii=False, indent=2)
        
        logging.info(f"📝 تم تسجيل الرقم الفاشل: {phone} للطالب: {student_name}")
        
    except Exception as e:
        logging.error(f"خطأ في تسجيل الرقم الفاشل: {e}")

def check_whatsapp_errors(driver):
    """
    يتحقق من رسائل الخطأ الشائعة في WhatsApp Web
    """
    error_selectors = [
        # "Phone number shared via url is invalid"
        "div[data-testid='alert-phone-number-invalid']",
        # "Couldn't send message"
        "div[data-testid='alert-msg-failed']",
        # General error messages
        "div[role='alert']",
        # Invalid number popup
        "div[data-animate-modal-popup='true']",
        # Message failed to send
        "span[data-icon='msg-time']",
    ]
    
    for selector in error_selectors:
        try:
            error_element = driver.find_element(By.CSS_SELECTOR, selector)
            if error_element and error_element.is_displayed():
                error_text = error_element.text
                return True, error_text
        except NoSuchElementException:
            continue
    
    # التحقق من النص المحدد لرسائل الخطأ
    try:
        page_text = driver.page_source.lower()
        error_keywords = [
            "phone number shared via url is invalid",
            "couldn't send message",
            "message failed to send",
            "invalid phone number",
            "number does not exist on whatsapp"
        ]
        
        for keyword in error_keywords:
            if keyword in page_text:
                return True, keyword
                
    except Exception:
        pass
    
    return False, ""

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

def send_whatsapp_message(phone, message, student_name=None):
    """
    يرسل رسالة عبر الجلسة الدائمة مع تتبع محسن للأخطاء:
    - يتنقل للمحادثة.
    - ينتظر زر الإرسال ثم ينقره.
    - يتحقق من رسائل الخطأ ويسجلها.
    - يعيد بدء الجلسة إذا تعطّلت.
    """
    if not is_valid_phone(phone):
        logging.error(f"🚫 رقم غير صالح: {phone}")
        log_failed_number(phone, student_name, "invalid_format", "صيغة الرقم غير صالحة")
        return False
        
    driver = get_driver()
    if not driver:
        logging.error("🚨 لا توجد جلسة جاهزة للرسائل.")
        return False

    to = format_phone(phone)
    encoded_message = quote(message, safe='')  # ترميز الرسالة لتكون صالحة في URL
    url = f"https://web.whatsapp.com/send?phone={to}&text={encoded_message}"

    try:
        driver.get(url)
        
        # انتظار قصير للتحقق من وجود خطأ فوري
        time.sleep(3)
        
        # التحقق من رسائل الخطأ قبل محاولة الإرسال
        has_error, error_message = check_whatsapp_errors(driver)
        if has_error:
            logging.warning(f"⚠️ خطأ في الرقم {to}: {error_message}")
            log_failed_number(phone, student_name, "whatsapp_error", error_message)
            return False
        
        # محاولة العثور على زر الإرسال
        try:
            send_btn = WebDriverWait(driver, 20).until(
                EC.element_to_be_clickable((By.XPATH, "//span[@data-icon='send']/parent::button"))
            )
            send_btn.click()
            
            # انتظار قصير بعد الإرسال للتحقق من النجاح
            time.sleep(2)
            
            # التحقق من رسائل الخطأ بعد الإرسال
            has_error_after, error_after = check_whatsapp_errors(driver)
            if has_error_after:
                logging.warning(f"⚠️ فشل الإرسال إلى {to}: {error_after}")
                log_failed_number(phone, student_name, "send_failed", error_after)
                return False
            
            logging.info(f"📩 أرسلنا رسالة إلى {to} في {datetime.now().strftime('%H:%M:%S')}")
            return True
            
        except TimeoutException:
            # لم يتم العثور على زر الإرسال - قد يكون الرقم غير صالح
            logging.warning(f"⚠️ لم يتم العثور على زر الإرسال للرقم {to}")
            log_failed_number(phone, student_name, "no_send_button", "لم يتم العثور على زر الإرسال - الرقم قد يكون غير موجود على واتساب")
            return False

    except Exception as e:
        logging.warning(f"⚠️ تعطل الإرسال إلى {to}: {e} — المحاولة بإعادة تشغيل الجلسة")
        log_failed_number(phone, student_name, "selenium_error", str(e))
        
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
            print('try resend')
            driver.get(url)
            time.sleep(3)
            
            # التحقق من الأخطاء مرة أخرى
            has_error, error_message = check_whatsapp_errors(driver)
            if has_error:
                logging.warning(f"⚠️ خطأ في المحاولة الثانية للرقم {to}: {error_message}")
                log_failed_number(phone, student_name, "retry_failed", error_message)
                return False
            
            send_btn = WebDriverWait(driver, 20).until(
                EC.element_to_be_clickable((By.XPATH, "//span[@data-icon='send']/parent::button"))
            )
            send_btn.click()
            
            time.sleep(2)
            
            # التحقق النهائي من الأخطاء
            has_error_final, error_final = check_whatsapp_errors(driver)
            if has_error_final:
                log_failed_number(phone, student_name, "final_check_failed", error_final)
                return False
                
            logging.info(f"🔁 resending successful {to}")
            return True
            
        except Exception as e2:
            logging.error(f"❌ we couldn't resend the message {to}: {e2}")
            log_failed_number(phone, student_name, "retry_failed", str(e2))
            return False

def get_failed_numbers_report():
    """
    يعيد تقرير بالأرقام الفاشلة
    """
    try:
        if not os.path.exists(FAILED_NUMBERS_FILE):
            return []
        
        with open(FAILED_NUMBERS_FILE, 'r', encoding='utf-8') as f:
            failed_data = json.load(f)
        
        return failed_data
        
    except Exception as e:
        logging.error(f"خطأ في قراءة تقرير الأرقام الفاشلة: {e}")
        return []

def clear_failed_numbers_log():
    """
    يمسح سجل الأرقام الفاشلة
    """
    try:
        if os.path.exists(FAILED_NUMBERS_FILE):
            os.remove(FAILED_NUMBERS_FILE)
            logging.info("تم مسح سجل الأرقام الفاشلة")
            return True
    except Exception as e:
        logging.error(f"خطأ في مسح سجل الأرقام الفاشلة: {e}")
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
