# في utils/message_templates.py مثلاً
from datetime import timedelta
import babel.dates
from django.utils import timezone

def format_date_ar(date_obj):
    # يفترض تثبيت Babel في المشروع
    return babel.dates.format_date(date_obj, format='yyyy-MM-dd', locale='ar')

def format_time(time_obj):
    return time_obj.strftime("%H:%M")

def attendance_message(student):
    today = timezone.localdate()
    now = timezone.localtime().time()
    date_str = format_date_ar(today)
    time_str = format_time(now)
    return (
        f"👋 *مرحباً ولي أمر الطالب {student.name}*،\n\n"
        f"*✅ تم تسجيل الحضور اليوم*\n"
        f"🗓️ التاريخ: `{date_str}`\n"
        f"⏰ الوقت: `{time_str}`\n\n"
        "نتمنى له يوماً موفقاً.\n"
        "مع تحيات،\n*م. عبدالله عمر*"
    )

def lateness_message(student):
    now = timezone.localtime().time()
    time_str = format_time(now)
    return (
        f"👋 *مرحباً ولي أمر الطالب {student.name}*،\n\n"
        f"⚠️ تم تسجيل حضور متأخر اليوم الساعة `{time_str}`.\n"
        "نرجو الالتزام بمواعيد الحضور.\n\n"
        "مع تحيات،\n*م. عبدالله عمر*"
    )

def payment_message(student, payment):
    # payment.month هو أول اليوم في الشهر/الفصل
    # استخدم Babel لجعل الشهر/السنة بالعربية:
    month_ar = babel.dates.format_date(payment.month, format='MMMM yyyy', locale='ar')
    if payment.payment_type == 'monthly':
        period_desc = f"شهر {month_ar}"
    else:
        # نفترض term_duration_months موجود
        # نحسب نهاية الفترة
        from dateutil.relativedelta import relativedelta
        end_date = payment.month + relativedelta(months=payment.term_duration_months) - timedelta(days=1)
        end_month_ar = babel.dates.format_date(end_date, format='MMMM yyyy', locale='ar')
        period_desc = f"فصل من {month_ar} إلى {end_month_ar}"
    amount_str = str(payment.amount) if hasattr(payment, 'amount') else "المبلغ المحدد"  # عدّل حسب الحقل الفعلي
    return (
        f"👋 *مرحباً ولي أمر الطالب {student.name}*،\n\n"
        f"*✅ تم استلام اشتراك {period_desc} بمبلغ {amount_str}.*\n"
        "شكراً لتعاونكم.\n\n"
        "مع تحيات،\n*م. عبدالله عمر*"
    )

def payment_and_attendance_message(student, payment):
    att_msg = attendance_message(student)
    pay_msg = payment_message(student, payment)
    # إزالة التحية المكررة؛ نأخذ التحية من pay_msg ثم فقرة attendance بدون التحية
    # نفصل: بعد pay_msg نجعل فقرة attendance مختصرة:
    today = timezone.localdate()
    time_str = format_time(timezone.localtime().time())
    date_str = format_date_ar(today)
    attend_part = f"*✅ تم تسجيل الحضور اليوم*\n🗓️ `{date_str}`   ⏰ `{time_str}`"
    # دمج:
    # نزيل آخر توقيع في pay_msg لتفادي التكرار، أو نجمع ثم نضيف توقيع واحد:
    header = f"👋 *مرحباً ولي أمر الطالب {student.name}*،\n\n"
    body = f"*✅ تم استلام الاشتراك* ثم\n{attend_part}\n\n"
    footer = "📚 نتمنى له يوماً موفقاً.\nمع تحيات،\n*م. عبدالله عمر*"
    return header + body + footer
