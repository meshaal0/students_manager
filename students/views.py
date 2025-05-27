from django.shortcuts import render,redirect
from django.http import FileResponse
from .utils.pdf_generator import generate_barcodes_pdf
from django.shortcuts import get_object_or_404
from django.http import HttpResponse
from .models import Students,Attendance,Payment,Basics
from .utils.barcode_utils import generate_barcode_image
from .utils.whatsapp_queue import queue_whatsapp_message
import os
from django.conf import settings
from django.contrib import messages
from django.utils import timezone
import threading
from datetime import date
from datetime import timedelta
import logging

logger = logging.getLogger(__name__)

# INITIAL_FREE_TRIES = 3 # Removed as free_tries will be fetched from Basics model

# def print_student_card(request, student_id):
#     student = get_object_or_404(Students, id=student_id)
#     pdf_io = generate_student_card_pdf(student)
#     return FileResponse(
#         pdf_io, as_attachment=True,
#         filename=f"{student.barcode}_card.pdf",
#         content_type="application/pdf"
#     )

def print_barcode(request, student_id):
    student = get_object_or_404(Students, id=student_id)
    full_path = os.path.join(settings.MEDIA_ROOT, 'barcodes', f"{student.barcode}.png")

    # إذا لم يكن الباركود موجوداً، نقوم بتوليده
    if not os.path.exists(full_path):
        generate_barcode_image(student.barcode)

    if os.path.exists(full_path):
        return FileResponse(open(full_path, "rb"), content_type="image/png")
    else:
        return HttpResponse("فشل في توليد الباركود", status=404)
    
def download_barcodes_pdf(request):
    pdf = generate_barcodes_pdf()
    return FileResponse(pdf, as_attachment=True, filename='barcodes.pdf')

# Helper function for 'scan' action
def _handle_scan_action(request, student, today, paid_for_month, barcode_value, context, basics_settings):
    if paid_for_month:
        Attendance.objects.create(student=student, attendance_date=today)
        messages.success(request, f"✅ تم تسجيل حضور {student.name} بنجاح.")
        _send_whatsapp_attendance(student, today)
        return redirect('barcode_attendance')
    else:
        # Not paid: show options for payment or free tries
        context.update({
            'pending_student': student,
            'barcode': barcode_value, # Use the passed barcode_value
        })
        if student.free_tries > 0:
            messages.warning(
                request,
                f"❗ لديك {student.free_tries} {'فرصة' if student.free_tries==1 else 'فرص'} مجانية قبل الدفع."
            )
        else:
            messages.warning(
                request,
                "⚠️ انتهت فرصك المجانية لهذا الشهر، الرجاء الدفع."
            )
        # This path needs to render the template, not redirect, to show the context
        return render(request, 'attendance.html', context) 

# Helper function for 'free' action
def _handle_free_action(request, student, today, basics_settings):
    if student.free_tries > 0:
        student.free_tries -= 1
        student.save()
        Attendance.objects.create(student=student, attendance_date=today)
        messages.success(
            request,
            f"✅ حضور مجانيّ. تبقى لديك {student.free_tries} {'فرصة' if student.free_tries==1 else 'فرص'}."
        )
        text = (
            f"👋 *مرحباً ولي أمر الطالب {student.name}،*\n\n"
            f"✅ سجلنا حضور اليوم كفرصة مجانية.\n"
            f"📌 تبقى {student.free_tries} {'فرصة' if student.free_tries==1 else 'فرص'} لهذا الشهر.\n\n"
            f"🎯 ننصح بسداد الاشتراك لضمان استمرار الحضور دون حدود.\n\n"
            f"– م. عبدالله عمر"
        )
        logger.info(f"Attempting to queue WhatsApp message to {student.father_phone} for student {student.name} (type: free_action)")
        try:
            thread = threading.Thread(
                target=queue_whatsapp_message,
                args=(student.father_phone, text),
                daemon=True
            )
            thread.start()
        except Exception as e:
            logger.error(f"Failed to start WhatsApp thread for student {student.name} (phone: {student.father_phone}, type: free_action): {e}")
    else:
        messages.error(request, "❌ لا توجد فرص مجانية متبقية، الرجاء الدفع.")
    return redirect('barcode_attendance')

# Helper function for 'pay' action
def _handle_pay_action(request, student, today, month_start, basics_settings):
    payment, created = Payment.objects.get_or_create(
        student=student,
        month=month_start
    )
    # Reset free tries using basics_settings
    student.free_tries = basics_settings.free_tries 
    student.last_reset_month = today.replace(day=1)
    student.save()

    Attendance.objects.create(student=student, attendance_date=today)
    
    # Use month_price from basics_settings
    month_price_value = basics_settings.month_price 
    dp_msg = (
        f"✅ تم استلام اشتراك شهر {payment.month:%B %Y}. بمبلغ {month_price_value} فقط لا غير"
        if created else
        f"ℹ️ دفعتك لشهر {payment.month:%B %Y} مسجلّة مسبقاً."
    )
    at_msg = f"✅ تم تسجيل حضور {student.name} اليوم {today:%Y-%m-%d}."

    # _send_whatsapp_combined handles its own logging for queueing
    _send_whatsapp_combined(student, dp_msg, at_msg)
    messages.success(request, dp_msg)
    messages.success(request, at_msg)
    return redirect('barcode_attendance')


def barcode_attendance_view(request):
    context = {}
    today = timezone.localdate()
    context['now'] = today # For displaying current month in template if needed

    basics_settings = Basics.objects.first()
    if basics_settings is None:
        messages.error(request, "Error: Basic settings not configured. Please contact admin.")
        return redirect('barcode_attendance')

    if request.method == 'POST':
        action  = request.POST.get('action', 'scan')
        barcode = request.POST.get('barcode', '').strip()

        try:
            student = Students.objects.get(barcode=barcode)
        except Students.DoesNotExist:
            messages.error(request, "❌ هذا الباركود غير صالح. الرجاء المحاولة مرة أخرى.")
            return redirect('barcode_attendance')

        if Attendance.objects.filter(student=student, attendance_date=today).exists():
            messages.warning(request, f"⚠️ حضور {student.name} اليوم مسجّل مسبقاً.")
            return redirect('barcode_attendance')

        month_start = date(today.year, today.month, 1)
        paid_for_month = Payment.objects.filter(student=student, month=month_start).exists()

        if action == 'scan':
            return _handle_scan_action(request, student, today, paid_for_month, barcode, context, basics_settings)
        elif action == 'free':
            return _handle_free_action(request, student, today, basics_settings)
        elif action == 'pay':
            return _handle_pay_action(request, student, today, month_start, basics_settings)
        else:
            # Should not happen if action is always one of the above
            messages.error(request, "Action غير معروف.")
            return redirect('barcode_attendance')

    return render(request, 'attendance.html', context)


def _send_whatsapp_attendance(student, today):
    date_str = today.strftime('%Y-%m-%d')
    time_str = timezone.localtime().strftime('%H:%M')
    text = (
        f"👋 *مرحباً ولي أمر الطالب {student.name}،*\n\n"
        f"📌 *تم تسجيل الحضور بنجاح.*\n"
        f"🗓️ التاريخ: `{date_str}`\n"
        f"⏰ الوقت: `{time_str}`\n\n"
        f"📚 نتمنى له يوماً موفقاً!\n\n"
        f"مع تحيات،\n*م. عبدالله عمر* 😎"
    )
    logger.info(f"Attempting to queue WhatsApp message to {student.father_phone} for student {student.name} (type: attendance_confirmation)")
    try:
        thread = threading.Thread(
            target=queue_whatsapp_message,
            args=(student.father_phone, text),
            daemon=True
        )
        thread.start()
    except Exception as e:
        logger.error(f"Failed to start WhatsApp thread for student {student.name} (phone: {student.father_phone}, type: attendance_confirmation): {e}")

def _send_whatsapp_combined(student, dp_msg, at_msg):
    text = (
        f"👋 *مرحباً ولي أمر الطالب {student.name}،*\n\n"
        f"{dp_msg}\n"
        f"{at_msg}\n\n"
        f"📚 شكراً لتعاونكم!\n\n"
        f"مع تحيات،\n*م. عبدالله عمر* 😎"
    )
    logger.info(f"Attempting to queue WhatsApp message to {student.father_phone} for student {student.name} (type: payment_confirmation_and_attendance)")
    try:
        thread = threading.Thread(
            target=queue_whatsapp_message,
            args=(student.father_phone, text),
            daemon=True
        )
        thread.start()
    except Exception as e:
        logger.error(f"Failed to start WhatsApp thread for student {student.name} (phone: {student.father_phone}, type: payment_confirmation_and_attendance): {e}")


def get_absence_message(student, today, consecutive_days, total_absences):
    """
    يُعيد رسالة مُخصصة بناءً على:
    - consecutive_days: عدد الأيام المتتابعة للغياب حتى اليوم
    - total_absences: إجمالي عدد أيام الغياب في الشهر الحالي
    """
    date_str = today.strftime("%Y-%m-%d")
    base_header = f"📢 *تنبيه ولي أمر الطالب {student.name}*\n\n"
    signature = "\n\nمع تحيات،\n*م. عبدالله عمر*"

    # أول غياب للطالب في الشهر
    if total_absences == 1 and consecutive_days == 1:
        return (
            base_header +
            f"❌ تم تسجيل أول غياب لابنك/ابنتك اليوم ({date_str}).\n"
            "📌 نرجو اطلاعنا على سبب الغياب وتزويدنا بإفادة إذا لزم الأمر." +
            signature
        )

    # غياب متتابع يومين
    if consecutive_days == 2:
        return (
            base_header +
            f"⚠️ تم تسجيل غياب ابنك/ابنتك لليوم الثاني على التوالي ({date_str}).\n"
            "📌 نرجو تزويدنا بمبرر الغياب لمساعدتنا في متابعة حالته الدراسية." +
            signature
        )

    # غياب متتابع 3 أيام أو أكثر
    if consecutive_days >= 3:
        return (
            base_header +
            f"🚨 غياب متتابع: ابنك/ابنتك غائب منذ {consecutive_days} أيام حتى ({date_str}).\n"
            "📌 نطلب منكم التواصل عاجلاً لتوضيح الوضع وتفادي التأثير السلبي على المستوى الدراسي.\n" +
            "ان كان هناك اي مشاكل او شكوى الرجاء ابلاغنا ونعد باننا سنعمل على حلها والمساعدة ان شاء الله"+
            signature
        )

    # غياب متقطع (ليس متتابعاً مع اليوم السابق)
    if consecutive_days == 1 and total_absences > 1:
        return (
            base_header +
            f"❌ تم تسجيل غياب ابنك/ابنتك اليوم ({date_str}) مرة أخرى بعد غيابه سابقاً.\n"
            "📌 نرجو متابعة انتظام الحضور ودعم الطالب للعودة إلى المدرسة بانتظام." +
            signature
        )

    # حالات عامة أخرى (احتياط)
    return (
        base_header +
        f"❌ لم يتم تسجيل حضور ابنك/ابنتك اليوم ({date_str}).\n"
        "📌 الرجاء التواصل معنا إذا كان هناك أي استفسار." +
        signature
    )

def mark_absentees_view(request):
    """
    يسجل غياب جميع الطلاب الذين لم يحضروا اليوم،
    ويرسل إشعار WhatsApp لأولياء أمورهم مع رسالة مخصصة لكل حالة.
    """
    if request.method != 'POST':
        return redirect('barcode_attendance')

    today = timezone.localdate()
    # بداية الشهر لحساب إجمالي الغيابات
    month_start = today.replace(day=1)

    # جميع الطلاب
    all_students = Students.objects.all()
    # الطلاب الذين حضروا اليوم
    attended_ids = Attendance.objects.filter(
        attendance_date=today,
        is_absent=False
    ).values_list('student_id', flat=True)
    # الطلاب الغائبون اليوم
    absentees = all_students.exclude(id__in=attended_ids)

    for student in absentees:
        # إذا لم نسجل للطالب شيئاً اليوم
        if Attendance.objects.filter(student=student, attendance_date=today).exists():
            continue

        # ضع علامة غياب
        Attendance.objects.create(
            student=student,
            attendance_date=today,
            is_absent=True
        )

        # حساب الأيام المتتابعة للغياب
        consecutive_days = 1
        yesterday = today - timedelta(days=1)
        # تحقق من الغياب أمس
        if Attendance.objects.filter(student=student, attendance_date=yesterday, is_absent=True).exists():
            consecutive_days += 1
            # غياب اليوم قبل أمس
            day_before = today - timedelta(days=2)
            if Attendance.objects.filter(student=student, attendance_date=day_before, is_absent=True).exists():
                consecutive_days += 1

        # حساب إجمالي الغيابات منذ بداية الشهر
        total_absences = Attendance.objects.filter(
            student=student,
            attendance_date__gte=month_start,
            is_absent=True
        ).count()

        # بناء الرسالة المناسبة
        text = get_absence_message(student, today, consecutive_days, total_absences)

        # أرسل الرسالة في Thread منفصل
        logger.info(f"Attempting to queue WhatsApp message to {student.father_phone} for student {student.name} (type: absentee_notification)")
        try:
            thread = threading.Thread(
                target=queue_whatsapp_message,
                args=(student.father_phone, text),
                daemon=True
            )
            thread.start()
        except Exception as e:
            logger.error(f"Failed to start WhatsApp thread for student {student.name} (phone: {student.father_phone}, type: absentee_notification): {e}")

    messages.success(request, "✅ تم تسجيل غياب اليوم وإرسال إشعارات مخصصة لأولياء الأمور.")
    return redirect('barcode_attendance')

# def mark_absentees_view(request):
#     """
#     يسجل غياب جميع الطلاب الذين لم يحضروا اليوم، ويرسل إشعار WhatsApp لأولياء أمورهم.
#     """
#     if request.method == 'POST':
#         today = timezone.localdate()
#         month_start = date(today.year, today.month, 1)

#         # 1) كل الطلاب
#         all_students = Students.objects.all()
#         # 2) الطلاب الذين سجلوا حضورًا (حقيقيًا) اليوم
#         attended_ids = Attendance.objects.filter(
#             attendance_date=today,
#             is_absent=False
#         ).values_list('student_id', flat=True)

#         # 3) الطلاب الغائبون
#         absentees = all_students.exclude(id__in=attended_ids)

#         for student in absentees:
#             # 4) تأكد أنّنا لم نسجل حضور أو غياب لهم اليوم سابقًا
#             if not Attendance.objects.filter(student=student, attendance_date=today).exists():
#                 # 5) سجّلهم كـغائب
#                 Attendance.objects.create(
#                     student=student,
#                     attendance_date=today,
#                     is_absent=True
#                 )
#                 # 6) أرسل رسالة غياب
#                 text = (
#                     f"📢 *تنبيه ولي أمر الطالب {student.name}*\n\n"
#                     f"❌ لم يتم تسجيل حضور ابنك/ابنتك اليوم `{today:%Y-%m-%d}`.\n"
#                     f"📌 الرجاء متابعة الأمر أو التواصل معنا في حال وجود مبرر.\n\n"
#                     f"مع تحيات،\n*م. عبدالله عمر*"
#                 )
#                 threading.Thread(
#                     target=queue_whatsapp_message,
#                     args=(student.father_phone, text),
#                     daemon=True
#                 ).start()

#         messages.success(request, "✅ يتم الان تسجيل غياب غير الحاضرين اليوم وإرسال الإشعارات.")
#         return redirect('barcode_attendance')

#     # إذا GET، ببساطة أعد توجيه لصفحة الحضور
#     return redirect('barcode_attendance')


def income_report_view(request):
    """
    يعرض تقرير الدخل بناءً على المدفوعات المسجلة.
    """
    payments = Payment.objects.all().order_by('-paid_on')
    
    try:
        basics = Basics.objects.get(id=1)
        month_price = basics.month_price
    except Basics.DoesNotExist:
        # Fallback or error handling if Basics instance is not found
        messages.error(request, "لم يتم تحديد سعر الشهر الأساسي. يرجى مراجعة الإعدادات.")
        month_price = 0 # Default to 0 if not set, to avoid further errors
        # Or redirect to an admin/setup page
        # return redirect('some_admin_setup_page')

    total_income = payments.count() * month_price
    
    now = timezone.now()
    month_year = now.strftime("%B %Y") # Example: "October 2023"
    # For Arabic month names, you might need a custom mapping or locale settings
    # For simplicity, using English month names as strftime default
    
    context = {
        'payments': payments,
        'month_price': month_price, # This is the price for EACH payment listed
        'total_income': total_income,
        'month_year': month_year,
    }
    
    return render(request, 'income.html', context)


def home_view(request):
    """
    Renders the home page.
    """
    return render(request, 'home.html')
