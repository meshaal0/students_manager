from celery import shared_task

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_whatsapp_task(self, phone, message):
    try:
        import pywhatkit
        # تأخير لتحميل WhatsApp Web
        pywhatkit.sendwhatmsg_instantly(phone, message, wait_time=20, tab_close=True)
    except Exception as exc:
        # إعادة المحاولة تلقائياً
        raise self.retry(exc=exc)
