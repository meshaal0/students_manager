# init_whatsapp_session.py
import os
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.desired_capabilities import DesiredCapabilities

print('here')
# PROFILE_DIR = os.path.abspath("./whatsapp_profile")
# os.makedirs(PROFILE_DIR, exist_ok=True)
print('here2')
os.environ['WDM_SSL_VERIFY'] = '0'  # disable SSL verification :contentReference[oaicite:2]{index=2}

# 2) (Optional) Force fresh download if you suspect cache corruption
os.environ['WDM_CACHE_VALID_RANGE'] = '0'

options = Options()
# options.add_argument(f"--user-data-dir={PROFILE_DIR}")
options.add_argument("--start-maximized")
print('options')

caps = DesiredCapabilities.CHROME.copy()
caps['acceptInsecureCerts'] = True 

# driver_path = ChromeDriverManager().install()
# service     = Service(driver_path)
driver      = webdriver.Chrome( options=options)
# لا تستخدم headless هنا إطلاقًا
driver.get("https://web.whatsapp.com/")
print("✅ تم فتح واتساب ويب. امسح QR من الموبايل.")

input("📱 اضغط Enter بعد تسجيل الدخول في WhatsApp Web...")
driver.quit()
