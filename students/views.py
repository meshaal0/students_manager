from django.shortcuts import render,redirect
from django.http import FileResponse
from .utils.pdf_generator import generate_barcodes_pdf
from django.shortcuts import get_object_or_404
from django.http import HttpResponse
from .models import Students,Attendance,Payment,Basics
from .utils.barcode_utils import generate_barcode_image
from .utils.whatsapp_queue import queue_whatsapp_message, log_failed_delivery
import os
from django.db import transaction
from django.conf import settings
from .util import has_active_payment # Import the new helper function
from django.contrib import messages
from django.utils import timezone
import threading
from datetime import date, datetime,timedelta
from .util import (
    get_daily_attendance_summary, get_students_with_overdue_payments, has_active_payment, # Added has_active_payment
    get_attendance_trends, get_revenue_trends,
    get_monthly_attendance_rate, get_student_payment_history
)
import logging

# Setup for WhatsApp delivery issue logging
whatsapp_issue_logger = logging.getLogger('whatsapp_issues')
whatsapp_issue_logger.setLevel(logging.INFO)
# Prevent propagation to root logger if not desired
# whatsapp_issue_logger.propagate = False 

# Check if handlers are already added to avoid duplication in dev server reloads
if not whatsapp_issue_logger.handlers:
    issue_file_handler = logging.FileHandler('whatsapp_delivery_issues.log', encoding='utf-8')
    issue_formatter = logging.Formatter('%(asctime)s - %(levelname)s - Student ID: %(student_id)s (Name: %(student_name)s) - Message Type: %(message_type)s - Reason: %(reason)s')
    issue_file_handler.setFormatter(issue_formatter)
    whatsapp_issue_logger.addHandler(issue_file_handler)


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


# Helper to send or log failure


# Helper to queue or log failures without altering message content
def send_or_log(student_obj, text_message, message_type_str):
    """
    Helper to queue WhatsApp message or log failure if phone/WhatsApp is disabled.
    Uses the student object directly.
    """
    phone = student_obj.father_phone or '' # Ensure phone is a string
    ctx = {
        'student_id': student_obj.id,
        'student_name': student_obj.name,
        'message_type': message_type_str,
        'reason': '' # Default reason
    }
    if phone and student_obj.has_whatsapp:
        queue_whatsapp_message(phone, text_message, **ctx)
    else:
        detailed_reason = ''
        if not phone: # Check for empty string ''
            detailed_reason = 'Missing phone number'
        elif not student_obj.has_whatsapp:
            detailed_reason = 'WhatsApp disabled for student'
        else:
            # This case should ideally not be reached if the outer if is "phone and student_obj.has_whatsapp"
            # It implies phone is true-ish but not whatsapp, or vice-versa, already covered.
            # However, as a safeguard:
            detailed_reason = 'Messaging condition not met (unspecified reason)'
        
        # Update ctx for logging if the queue_whatsapp_message in celery also logs based on reason
        ctx['reason'] = detailed_reason 
        log_failed_delivery(phone, message_type_str, detailed_reason, 'View-level skip (send_or_log)')
        # Note: We are NOT calling queue_whatsapp_message here in the else block.

# def barcode_attendance_view(request):
#     today = timezone.localdate()
#     context = {'now': today}

#     if request.method == 'POST':
#         basics = Basics.objects.first()
#         if not basics:
#             messages.error(request, "خطأ: إعدادات الأسعار الأساسية غير موجودة. يرجى مراجعة مسؤول النظام.")
#             return redirect('barcode_attendance')

#         action  = request.POST.get('action', 'scan')
#         barcode = request.POST.get('barcode', '').strip()

#         try:
#             student = Students.objects.get(barcode=barcode)
#         except Students.DoesNotExist:
#             messages.error(request, "❌ هذا الباركود غير صالح. الرجاء المحاولة مرة أخرى.")
#             return redirect('barcode_attendance')

#         # Check if attendance already recorded for today
#         if Attendance.objects.filter(student=student, attendance_date=today).exists():
#             messages.warning(request, f"⚠️ حضور {student.name} اليوم مسجّل مسبقاً.")
#             return redirect('barcode_attendance')

#         # Use the new helper function to check for active payment
#         paid = has_active_payment(student, today)

#         if action == 'scan':
#             try:
#                 basics = Basics.objects.first()
#                 late_arrival_time = basics.late_arrival_time
#             except:
#                 late_arrival_time = None

#             if late_arrival_time:
#                 current_time = timezone.localtime().time()
#                 if current_time > late_arrival_time:
#                     lateness_message = (
#                         f"👋 *مرحباً ولي أمر الطالب {student.name}،*\n\n"
#                         f"تم تسجيل حضور ابنكم/ابنتكم اليوم الساعة {current_time.strftime('%H:%M')}\.\n"
#                         "نأمل الالتزام بالحضور...\n\n"
#                         "مع تحيات،\n*م. عبدالله عمر* 😎"
#                     )
#                     send_or_log(student, lateness_message, 'Lateness Alert')

#             if paid:
#                 Attendance.objects.create(student=student, attendance_date=today, arrival_time=timezone.localtime().time())
#                 messages.success(request, f"✅ تم تسجيل حضور {student.name} بنجاح.")
#                 attendance_text = (
#                     f"👋 *مرحباً ولي أمر الطالب {student.name}،*\n\n"
#                     f"📌 *تم تسجيل الحضور بنجاح.*\n"
#                     f"🗓️ التاريخ: `{today.strftime('%Y-%m-%d')}`\n"
#                     f"⏰ الوقت: `{timezone.localtime().strftime('%H:%M')}`\n\n"
#                     "📚 نتمنى له يوماً موفقاً!\n\n"
#                     "مع تحيات،\n*م. عبدالله عمر* 😎"
#                 )
#                 send_or_log(student, attendance_text, 'Attendance')
#                 return redirect('barcode_attendance')
#             else: # Not paid
#                 # basics is already fetched and checked at the beginning of POST handling
#                 context.update({
#                     'pending_student': student,
#                     'barcode': barcode,
#                     'month_price': basics.month_price, # No need for 'if basics else 0' due to earlier check
#                     'term_price': basics.term_price,
#                     'default_term_duration': basics.default_term_duration_months,
#                 })
#                 if student.free_tries > 0:
#                     messages.warning(request, f"❗ لديك {student.free_tries} فرصة مجانية قبل الدفع.")
#                 else:
#                     messages.warning(request, "⚠️ انتهت فرصك المجانية لهذا الشهر، الرجاء الدفع.")

#         elif action == 'free':
#             if student.free_tries > 0:
#                 student.free_tries -= 1
#                 student.save()
#                 Attendance.objects.create(student=student, attendance_date=today, arrival_time=timezone.localtime().time())
#                 messages.success(request, f"✅ حضور مجانيّ. تبقى لديك {student.free_tries} {'فرصة' if student.free_tries==1 else 'فرص'}.")

#                 free_text = (
#                     f"👋 *مرحباً ولي أمر الطالب {student.name}،*\n\n"
#                     f"✅ سجلنا حضور اليوم كفرصة مجانية.\n"
#                     f"📌 تبقى {student.free_tries} {'فرصة' if student.free_tries==1 else 'فرص'} لهذا الشهر.\n\n"
#                     "🎯 ننصح بسداد الاشتراك لضمان استمرار الحضور دون حدود.\n\n"
#                     "– م. عبدالله عمر"
#                 )
#                 send_or_log(student, free_text, 'FreeTry')
#             else:
#                 messages.error(request, "❌ لا توجد فرص مجانية متبقية، الرجاء الدفع.")
#             return redirect('barcode_attendance')

#         elif action == 'pay':
#             payment_option = request.POST.get('payment_option', 'monthly') # 'monthly' or 'termly'
#             # basics is already fetched and checked
#             month_start = date(today.year, today.month, 1) # Payment month start

#             payment_params = {
#                 'student': student,
#                 'month': month_start, # Start month of the payment period
#             }
            
#             created = False
#             if payment_option == 'termly':
#                 term_duration = basics.default_term_duration_months if basics else 3
#                 payment_params.update({
#                     'payment_type': 'term',
#                     'term_duration_months': term_duration,
#                 })
#                 pay_amount = basics.term_price if basics else 0
#                 # Check if a similar term payment already exists for this start month
#                 payment, created = Payment.objects.get_or_create(
#                     student=student,
#                     month=month_start,
#                     payment_type='term',
#                     defaults=payment_params # only used if created
#                 )
#                 if not created and payment.term_duration_months != term_duration : # if exists but duration different, update
#                     payment.term_duration_months = term_duration
#                     payment.paid_on = timezone.now() # Re-stamp paid_on
#                     payment.save()
#                     # 'created' is effectively true for message purposes if we updated duration
#                     # Or, adjust dp_msg to handle "updated" scenario. For now, treat as new if duration changed.

#                 dp_msg = (
#                     f"✅ تم استلام اشتراك فصل يبدأ من {payment.month:%B %Y} لمدة {payment.term_duration_months} أشهر. بمبلغ {pay_amount}."
#                     if created or (payment.term_duration_months == term_duration and not created) # Re-evaluate this logic for message accuracy
#                     else f"ℹ️ دفعة الفصل التي تبدأ من {payment.month:%B %Y} مسجلة مسبقاً."
#                 )

#             else: # Monthly payment
#                 payment_params.update({
#                     'payment_type': 'monthly',
#                     'term_duration_months': None,
#                 })
#                 pay_amount = basics.month_price if basics else 0
#                 payment, created = Payment.objects.get_or_create(
#                     student=student,
#                     month=month_start,
#                     payment_type='monthly', # Ensure we are checking for monthly payment if one exists
#                     defaults=payment_params
#                 )
#                 dp_msg = (
#                     f"✅ تم استلام اشتراك شهر {payment.month:%B %Y}. بمبلغ {pay_amount}."
#                     if created else
#                     f"ℹ️ دفعتك لشهر {payment.month:%B %Y} مسجلّة مسبقاً."
#                 )

#             if created : # Only reset tries and last_reset_month if a new payment record was genuinely created or significantly updated
#                 student.free_tries = basics.free_tries # No need for 'if basics'
#                 student.last_reset_month = month_start # Reset to start of current payment period
#                 student.save()

#             Attendance.objects.create(student=student, attendance_date=today, arrival_time=timezone.localtime().time())
#             at_msg = f"✅ تم تسجيل حضور {student.name} اليوم {today:%Y-%m-%d}."

#             combined_text = (
#                 f"👋 *مرحباً ولي أمر الطالب {student.name}،*\n\n"
#                 f"{dp_msg}\n"
#                 f"{at_msg}\n\n"
#                 "📚 شكراً لتعاونكم!\n\n"
#                 "مع تحيات،\n*م. عبدالله عمر* 😎"
#             )
#             send_or_log(student, combined_text, 'PaymentAttendance')
#             messages.success(request, dp_msg)
#             messages.success(request, at_msg)
#             return redirect('barcode_attendance')

#     return render(request, 'attendance.html', context)

# def barcode_attendance_view(request):
#     """
#     View to handle barcode attendance scanning, free tries, or payment+attendance.
#     - GET: يعرض صفحة المسح فقط.
#     - POST: يعتمد على action في الفورم: 'scan', 'free', أو 'pay'.
#     """
#     today = timezone.localdate()
#     context = {'now': today}

#     # جلب إعدادات النظام مرة واحدة
#     basics = Basics.objects.first()
#     if request.method == 'POST':
#         if not basics:
#             messages.error(request, "خطأ: إعدادات النظام الأساسية غير موجودة. تواصل مع مسؤول النظام.")
#             return redirect('barcode_attendance')

#         # قراءة بيانات الفورم
#         action = request.POST.get('action', 'scan')
#         barcode = request.POST.get('barcode', '').strip()

#         if not barcode:
#             messages.error(request, "❌ الرجاء إدخال الباركود.")
#             return redirect('barcode_attendance')

#         # جلب الطالب بواسطة الباركود مع التعامل مع عدم وجوده
#         try:
#             student = Students.objects.get(barcode=barcode)
#         except Students.DoesNotExist:
#             messages.error(request, "❌ هذا الباركود غير صالح. الرجاء المحاولة مرة أخرى.")
#             return redirect('barcode_attendance')

#         # تحقق سريع: هل سجل حضور اليوم مسبقًا؟
#         if Attendance.objects.filter(student=student, attendance_date=today).exists():
#             messages.warning(request, f"⚠️ حضور {student.name} اليوم مسجّل مسبقاً.")
#             return redirect('barcode_attendance')

#         # التحقق من الدفع النشط (شهري أو فصلي)
#         paid = has_active_payment(student, today)

#         # مسح scan: تسجيل حضور عادي (مع تحقق التأخير)
#         if action == 'scan':
#             # تحقق وقت التأخير مرة واحدة: 
#             late_arrival_time = getattr(basics, 'late_arrival_time', None)
#             if late_arrival_time:
#                 current_time = timezone.localtime().time()
#                 if current_time > late_arrival_time:
#                     # رسالة تأخير
#                     lateness_message = (
#                         f"👋 *مرحباً ولي أمر الطالب {student.name}،*\n\n"
#                         f"تم تسجيل حضور ابنكم/ابنتكم اليوم الساعة {current_time.strftime('%H:%M')}.\n"
#                         "نأمل الالتزام بالحضور بوقت مبكر.\n\n"
#                         "مع تحيات،\n*م. عبدالله عمر* 😎"
#                     )
#                     send_or_log(student, lateness_message, 'Lateness Alert')

#             if paid:
#                 # تسجيل الحضور
#                 Attendance.objects.create(
#                     student=student,
#                     attendance_date=today,
#                     arrival_time=timezone.localtime().time()
#                 )
#                 messages.success(request, f"✅ تم تسجيل حضور {student.name} بنجاح.")
#                 attendance_text = (
#                     f"👋 *مرحباً ولي أمر الطالب {student.name}،*\n\n"
#                     f"📌 *تم تسجيل الحضور بنجاح.*\n"
#                     f"🗓️ التاريخ: `{today.strftime('%Y-%m-%d')}`\n"
#                     f"⏰ الوقت: `{timezone.localtime().strftime('%H:%M')}`\n\n"
#                     "📚 نتمنى له يوماً موفقاً!\n\n"
#                     "مع تحيات،\n*م. عبدالله عمر* 😎"
#                 )
#                 send_or_log(student, attendance_text, 'Attendance')
#                 return redirect('barcode_attendance')
#             else:
#                 # في حالة عدم الدفع: نجهز السياق لإظهار خيارات الدفع أو استخدام الفرصة المجانية
#                 context.update({
#                     'pending_student': student,
#                     'barcode': barcode,
#                     'month_price': basics.month_price,
#                     'term_price': basics.term_price,
#                     'default_term_duration': basics.default_term_duration_months,
#                 })
#                 if student.free_tries > 0:
#                     messages.warning(request, f"❗ لديك {student.free_tries} {'فرصة' if student.free_tries == 1 else 'فرص'} مجانية قبل الدفع.")
#                 else:
#                     messages.warning(request, "⚠️ انتهت فرصك المجانية لهذا الشهر، الرجاء الدفع.")
#                 # لا نعيد توجيه (redirect) هنا حتى يتم عرض خيارات الدفع/الفرصة في القالب.
        
#         # استخدام فرصة مجانية
#         elif action == 'free':
#             if student.free_tries > 0:
#                 student.free_tries -= 1
#                 student.save(update_fields=['free_tries'])
#                 Attendance.objects.create(
#                     student=student,
#                     attendance_date=today,
#                     arrival_time=timezone.localtime().time()
#                 )
#                 messages.success(request, f"✅ حضور مجانيّ: تبقى لديك {student.free_tries} {'فرصة' if student.free_tries == 1 else 'فرص'}.")
#                 free_text = (
#                     f"👋 *مرحباً ولي أمر الطالب {student.name}،*\n\n"
#                     f"✅ سجلنا حضور اليوم كفرصة مجانية.\n"
#                     f"📌 تبقى {student.free_tries} {'فرصة' if student.free_tries == 1 else 'فرص'} لهذا الشهر.\n\n"
#                     "🎯 ننصح بسداد الاشتراك لضمان استمرار الحضور دون حدود.\n\n"
#                     "– م. عبدالله عمر"
#                 )
#                 send_or_log(student, free_text, 'FreeTry')
#             else:
#                 messages.error(request, "❌ لا توجد فرص مجانية متبقية، الرجاء الدفع.")
#             return redirect('barcode_attendance')

#         # الدفع وتسجيل الحضور
#         elif action == 'pay':
#             payment_option = request.POST.get('payment_option', 'monthly')
#             month_start = date(today.year, today.month, 1)

#             # نستخدم transaction.atomic لضمان الاتساق: الدفع + تسجيل الحضور يتمان معًا أو لا شيء
#             with transaction.atomic():
#                 created = False
#                 dp_msg = ""
#                 # بناء باراميترات الدفع المشتركة
#                 if payment_option == 'termly':
#                     term_duration = basics.default_term_duration_months or 1
#                     pay_amount = basics.term_price
#                     payment, created = Payment.objects.get_or_create(
#                         student=student,
#                         month=month_start,
#                         payment_type='term',
#                         defaults={
#                             'term_duration_months': term_duration,
#                             'paid_on': timezone.now()
#                         }
#                     )
#                     # إذا وجدنا سجل سابق ومدة الدفع مختلفة، نحدّثه
#                     if not created and payment.term_duration_months != term_duration:
#                         payment.term_duration_months = term_duration
#                         payment.paid_on = timezone.now()
#                         payment.save(update_fields=['term_duration_months', 'paid_on'])
#                         created = True  # نعتبره كإنشاء جديد لغرض الرسالة
#                     # صياغة رسالة دقيقة
#                     if created:
#                         dp_msg = (
#                             f"✅ تم استلام اشتراك فصل يبدأ من {payment.month:%B %Y} لمدة {payment.term_duration_months} أشهر بمبلغ {pay_amount}."
#                         )
#                     else:
#                         dp_msg = f"ℹ️ اشتراك الفصل الحالي ({payment.month:%B %Y}) مسجل مسبقاً بنفس المدة."
#                 else:
#                     # دفع شهري
#                     pay_amount = basics.month_price
#                     payment, created = Payment.objects.get_or_create(
#                         student=student,
#                         month=month_start,
#                         payment_type='monthly',
#                         defaults={'term_duration_months': None, 'paid_on': timezone.now()}
#                     )
#                     if created:
#                         dp_msg = f"✅ تم استلام اشتراك شهر {payment.month:%B %Y} بمبلغ {pay_amount}."
#                     else:
#                         dp_msg = f"ℹ️ دفعك لشهر {payment.month:%B %Y} مسجل مسبقاً."

#                 # إذا تم إنشاء سجل جديد أو تحديث (اعتبرناه إنشاء جديد أعلاه)، نعيد تعيين الفرص
#                 if created:
#                     student.free_tries = basics.free_tries
#                     student.last_reset_month = month_start
#                     student.save(update_fields=['free_tries', 'last_reset_month'])

#                 # تسجيل الحضور بعد الدفع
#                 Attendance.objects.create(
#                     student=student,
#                     attendance_date=today,
#                     arrival_time=timezone.localtime().time()
#                 )
#                 at_msg = f"✅ تم تسجيل حضور {student.name} اليوم {today:%Y-%m-%d}."
#                 combined_text = (
#                     f"👋 *مرحباً ولي أمر الطالب {student.name}،*\n\n"
#                     f"{dp_msg}\n"
#                     f"{at_msg}\n\n"
#                     "📚 شكراً لتعاونكم!\n\n"
#                     "مع تحيات،\n*م. عبدالله عمر* 😎"
#                 )
#                 send_or_log(student, combined_text, 'PaymentAttendance')
#                 messages.success(request, dp_msg)
#                 messages.success(request, at_msg)
#             return redirect('barcode_attendance')

#         else:
#             # action غير معروف
#             messages.error(request, "إجراء غير مدعوم.")
#             return redirect('barcode_attendance')

#     # في حالة GET أو عند الحاجة لإعادة عرض الصفحة بعد 'scan' غير مدفوع
#     return render(request, 'attendance.html', context)

# def get_absence_message(student, today, consecutive_days, total_absences):
#     """
#     يُعيد رسالة مُخصصة بناءً على:
#     - consecutive_days: عدد الأيام المتتابعة للغياب حتى اليوم
#     - total_absences: إجمالي عدد أيام الغياب في الشهر الحالي
#     """
#     date_str = today.strftime("%Y-%m-%d")
#     # Using a more neutral and informative emoji for the header
#     base_header = f"📋 *متابعة حضور الطالب {student.name}*\n\n"
#     signature = "\n\nنتمنى لكم يوماً طيباً،\n*م. عبدالله عمر وفريق العمل* 👨‍🏫" # Slightly warmer signature

#     # أول غياب للطالب في الشهر
#     if total_absences == 1 and consecutive_days == 1:
#         return (
#             base_header +
#             f" لاحظنا غياب ابنك/ابنتك اليوم ({date_str}).\n" # Softer phrasing
#             "🗓️ نأمل إبلاغنا سبب الغياب لنتمكن من تقديم الدعم إذا لزم الأمر.\n" # More supportive
#             "📞 لا تترددوا في التواصل معنا لمناقشة أي تفاصيل." +
#             signature
#         )

#     # غياب متتابع يومين
#     if consecutive_days == 2:
#         return (
#             base_header +
#             f"⚠️ لاحظنا غياب ابنك/ابنتك لليوم الثاني على التوالي ({date_str}).\n" # Consistent emoji and phrasing
#             "📝 نأمل تزويدنا بسبب الغياب لمتابعة تقدمه الدراسي وضمان عدم تأثره.\n" # Focus on progress
#             "💬 يرجى التواصل معنا إذا كانت هناك ظروف خاصة تتطلب المساعدة." +
#             signature
#         )

#     # غياب متتابع 3 أيام أو أكثر
#     if consecutive_days >= 3:
#         return (
#             base_header +
#             f"🚨 غياب متكرر: نلاحظ أن ابنك/ابنتك غائب منذ {consecutive_days} أيام، حتى تاريخ اليوم ({date_str}).\n" # Clear and direct
#             "🧑‍🏫 نود التأكيد على أهمية الحضور المنتظم، ونطلب منكم التواصل معنا لمناقشة الوضع.\n"
#             "🤝 إذا كانت هناك أي تحديات تواجه الطالب، فنحن هنا لتقديم الدعم والعمل سوياً لإيجاد حلول مناسبة.\n" +
#             "إن كان هناك أي مشاكل أو شكوى، الرجاء إبلاغنا ونعد بأننا سنعمل على حلها والمساعدة إن شاء الله."+ # Retained this important part
#             signature
#         )

#     # غياب متقطع (ليس متتابعاً مع اليوم السابق)
#     if consecutive_days == 1 and total_absences > 1:
#         return (
#             base_header +
#             f" لاحظنا تكرار غياب ابنك/ابنتك اليوم ({date_str}) بعد غيابه سابقاً هذا الشهر.\n" # Clearer phrasing
#             "📈 نرجو متابعة انتظام الحضور ودعم الطالب للالتزام.\n"
#             "💬 إذا احتجتم لأي مساعدة أو استشارة بخصوص انتظام الحضور، فنحن هنا لتقديم الدعم." + # Added offer for help
#             signature
#         )

#     # حالات عامة أخرى (احتياط - should ideally not be reached if logic is correct)
#     return (
#         base_header +
#         f" تم تسجيل غياب ابنك/ابنتك اليوم ({date_str}).\n" # More neutral than "لم يتم تسجيل حضور"
#         "📞 يرجى التواصل معنا إذا كان هناك أي استفسار أو لتوضيح سبب الغياب." +
#         signature
#     )

# def mark_absentees_view(request):
#     """
#     يسجل غياب جميع الطلاب الذين لم يحضروا اليوم،
#     ويرسل إشعار WhatsApp لأولياء أمورهم مع رسالة مخصصة لكل حالة.
#     """
#     if request.method != 'POST':
#         return redirect('barcode_attendance')

#     today = timezone.localdate()
#     # بداية الشهر لحساب إجمالي الغيابات
#     month_start = today.replace(day=1)

#     # جميع الطلاب
#     all_students = Students.objects.all()
#     # الطلاب الذين حضروا اليوم
#     attended_ids = Attendance.objects.filter(
#         attendance_date=today,
#         is_absent=False
#     ).values_list('student_id', flat=True)
#     # الطلاب الغائبون اليوم
#     absentees = all_students.exclude(id__in=attended_ids)

#     for student in absentees:
#         # إذا لم نسجل للطالب شيئاً اليوم
#         if Attendance.objects.filter(student=student, attendance_date=today).exists():
#             continue

#         # ضع علامة غياب
#         Attendance.objects.create(
#             student=student,
#             attendance_date=today,
#             is_absent=True
#         )

#         # حساب الأيام المتتابعة للغياب
#         consecutive_days = 1
#         yesterday = today - timedelta(days=1)
#         # تحقق من الغياب أمس
#         if Attendance.objects.filter(student=student, attendance_date=yesterday, is_absent=True).exists():
#             consecutive_days += 1
#             # غياب اليوم قبل أمس
#             day_before = today - timedelta(days=2)
#             if Attendance.objects.filter(student=student, attendance_date=day_before, is_absent=True).exists():
#                 consecutive_days += 1

#         # حساب إجمالي الغيابات منذ بداية الشهر
#         total_absences = Attendance.objects.filter(
#             student=student,
#             attendance_date__gte=month_start,
#             is_absent=True
#         ).count()

#         # بناء الرسالة المناسبة
#         text = get_absence_message(student, today, consecutive_days, total_absences)

#         # أرسل الرسالة باستخدام send_or_log
#         send_or_log(student, text, 'Absence Alert')

#     messages.success(request, "✅ تم تسجيل غياب اليوم وإرسال إشعارات مخصصة لأولياء الأمور.")
#     return redirect('barcode_attendance')











# def barcode_attendance_view(request):
#     """
#     View to handle barcode attendance scanning, free tries, أو payment+attendance.
#     - GET: يعرض صفحة المسح فقط.
#     - POST: يعتمد على action في الفورم: 'scan', 'free', أو 'pay'.
#     """
#     today = timezone.localdate()
#     context = {'now': today}

#     # جلب إعدادات النظام مرة واحدة
#     basics = Basics.objects.first()
#     if request.method == 'POST':
#         if not basics:
#             messages.error(request, "خطأ: إعدادات النظام الأساسية غير موجودة. تواصل مع مسؤول النظام.")
#             return redirect('barcode_attendance')

#         # قراءة بيانات الفورم
#         action = request.POST.get('action', 'scan')
#         barcode = request.POST.get('barcode', '').strip()

#         if not barcode:
#             messages.error(request, "❌ الرجاء إدخال الباركود.")
#             return redirect('barcode_attendance')

#         # جلب الطالب بواسطة الباركود مع التعامل مع عدم وجوده
#         try:
#             student = Students.objects.get(barcode=barcode)
#         except Students.DoesNotExist:
#             messages.error(request, "❌ هذا الباركود غير صالح. الرجاء المحاولة مرة أخرى.")
#             return redirect('barcode_attendance')

#         # تحقق سريع: هل سجل حضور اليوم مسبقًا؟
#         if Attendance.objects.filter(student=student, attendance_date=today).exists():
#             messages.warning(request, f"⚠️ حضور {student.name} اليوم مسجّل مسبقاً.")
#             return redirect('barcode_attendance')

#         # التحقق من الدفع النشط (شهري أو فصلي)
#         paid = has_active_payment(student, today)

#         # مسح scan: تسجيل حضور عادي (مع تحقق التأخير)
#         if action == 'scan':
#             # تحقق وقت التأخير مرة واحدة:
#             late_arrival_time = getattr(basics, 'late_arrival_time', None)
#             current_time = timezone.localtime().time()
#             if late_arrival_time and current_time > late_arrival_time:
#                 # رسالة تأخير
#                 lateness_message = (
#                     f"👋 أهلاً ولي أمر الطالب {student.name}،\n\n"
#                     f"سجلنا وصول ابنكم/ابنتكم الساعة {current_time.strftime('%H:%M')} اليوم. لاحظنا التأخير، ونقدّر تعاونكم في الحضور أبكر عشان يبدأ اليوم الدراسي بنشاط.\n\n"
#                     "لو في ظروف خاصة بتمنع الوصول أبكر، ياريت تبلغونا مسبقاً لنساعد بتنظيم الجدول.\n\n"
#                     "مع تحيات فريق الإدارة والتعليم 💡"
#                 )
#                 send_or_log(student, lateness_message, 'Lateness Alert')

#             if paid:
#                 # تسجيل الحضور
#                 Attendance.objects.create(
#                     student=student,
#                     attendance_date=today,
#                     arrival_time=timezone.localtime().time()
#                 )
#                 messages.success(request, f"✅ تم تسجيل حضور {student.name} بنجاح.")
#                 attendance_text = (
#                     f"👋 مرحباً ولي أمر الطالب {student.name}،\n\n"
#                     f"📌 تم تسجيل حضور ابنكم/ابنتكم بنجاح اليوم.\n"
#                     f"🗓️ التاريخ: `{today.strftime('%Y-%m-%d')}`\n"
#                     f"⏰ الوقت: `{timezone.localtime().strftime('%H:%M')}`\n\n"
#                     "نتمنى له/لها يوماً دراسياً ناجحاً ومثمرًا!📚\n\n"
#                     "لو في أي ملاحظات أو استفسارات، تواصلوا معنا.\n"
#                     "مع تحيات فريق الإدارة والتعليم 😊"
#                 )
#                 send_or_log(student, attendance_text, 'Attendance')
#                 return redirect('barcode_attendance')
#             else:
#                 # في حالة عدم الدفع: نجهز السياق لإظهار خيارات الدفع أو استخدام الفرصة المجانية
#                 context.update({
#                     'pending_student': student,
#                     'barcode': barcode,
#                     'month_price': basics.month_price,
#                     'term_price': basics.term_price,
#                     'default_term_duration': basics.default_term_duration_months,
#                 })
#                 if student.free_tries > 0:
#                     messages.warning(request, f"❗ لديك {student.free_tries} {'فرصة' if student.free_tries == 1 else 'فرص'} مجانية قبل الدفع. يفضل تجديد الاشتراك لضمان حضور مستمر.")
#                 else:
#                     messages.warning(request, "⚠️ انتهت فرصك المجانية لهذا الشهر، الرجاء الدفع للاستمرار بدون انقطاع.")
#                 # لا نعيد توجيه هنا حتى يتم عرض خيارات الدفع/الفرصة في القالب.

#         # استخدام فرصة مجانية
#         elif action == 'free':
#             if student.free_tries > 0:
#                 student.free_tries -= 1
#                 student.save(update_fields=['free_tries'])
#                 Attendance.objects.create(
#                     student=student,
#                     attendance_date=today,
#                     arrival_time=timezone.localtime().time()
#                 )
#                 messages.success(request, f"✅ حضور مجاني: تبقى لديك {student.free_tries} {'فرصة' if student.free_tries == 1 else 'فرص'}. لتجربة النظام، لكن ننصح بالتجديد للديمومة.")
#                 free_text = (
#                     f"👋 أهلاً ولي أمر الطالب {student.name}،\n\n"
#                     f"سجلنا حضور اليوم كفرصة مجانية، وتبقى {student.free_tries} {'فرصة' if student.free_tries == 1 else 'فرص'} لهذا الشهر.\n\n"
#                     "يا ريت لو حابب تستمر بدون قيود، جدد الاشتراك عشان يضمن حضور ابنك/ابنتك بانتظام.\n\n"
#                     "مع تحيات فريق الإدارة والتعليم 🚀"
#                 )
#                 send_or_log(student, free_text, 'FreeTry')
#             else:
#                 messages.error(request, "❌ لا توجد فرص مجانية متبقية، الرجاء الدفع.")
#             return redirect('barcode_attendance')

#         # الدفع وتسجيل الحضور
#         elif action == 'pay':
#             payment_option = request.POST.get('payment_option', 'monthly')
#             month_start = date(today.year, today.month, 1)

#             # نستخدم transaction.atomic لضمان الاتساق: الدفع + تسجيل الحضور
#             with transaction.atomic():
#                 created = False
#                 dp_msg = ""
#                 # بناء باراميترات الدفع المشتركة
#                 if payment_option == 'termly':
#                     term_duration = basics.default_term_duration_months or 1
#                     pay_amount = basics.term_price
#                     payment, created = Payment.objects.get_or_create(
#                         student=student,
#                         month=month_start,
#                         payment_type='term',
#                         defaults={
#                             'term_duration_months': term_duration,
#                             'paid_on': timezone.now()
#                         }
#                     )
#                     if not created and payment.term_duration_months != term_duration:
#                         payment.term_duration_months = term_duration
#                         payment.paid_on = timezone.now()
#                         payment.save(update_fields=['term_duration_months', 'paid_on'])
#                         created = True
#                     if created:
#                         dp_msg = (
#                             f"✅ تم استلام اشتراك فصل يبدأ {payment.month.strftime('%B %Y')} لمدة {payment.term_duration_months} أشهر بقيمة {pay_amount}ج."
#                         )
#                     else:
#                         dp_msg = f"ℹ️ اشتراك الفصل الحالي ({payment.month.strftime('%B %Y')}) مسجل مسبقاً بنفس المدة."
#                 else:
#                     pay_amount = basics.month_price
#                     payment, created = Payment.objects.get_or_create(
#                         student=student,
#                         month=month_start,
#                         payment_type='monthly',
#                         defaults={'term_duration_months': None, 'paid_on': timezone.now()}
#                     )
#                     if created:
#                         dp_msg = f"✅ تم استلام اشتراك شهر {payment.month.strftime('%B %Y')} بقيمة {pay_amount}ج."
#                     else:
#                         dp_msg = f"ℹ️ اشتراك شهر {payment.month.strftime('%B %Y')} مسجل مسبقاً."

#                 # إعادة ضبط الفرص إذا جديد
#                 if created:
#                     student.free_tries = basics.free_tries
#                     student.last_reset_month = month_start
#                     student.save(update_fields=['free_tries', 'last_reset_month'])

#                 # تسجيل الحضور بعد الدفع
#                 Attendance.objects.create(
#                     student=student,
#                     attendance_date=today,
#                     arrival_time=timezone.localtime().time()
#                 )
#                 at_msg = f"✅ تم تسجيل حضور {student.name} اليوم {today.strftime('%Y-%m-%d')} بعد الدفع."
#                 combined_text = (
#                     f"👋 أهلاً ولي أمر الطالب {student.name}،\n\n"
#                     f"{dp_msg}\n{at_msg}\n\n"
#                     "شكراً لتعاونكم وثقتكم بنا! إذا في أي استفسار بخصوص الاشتراك، تواصلوا معانا.\n"
#                     "مع تحيات فريق الإدارة والتعليم 👍"
#                 )
#                 send_or_log(student, combined_text, 'PaymentAttendance')
#                 messages.success(request, dp_msg)
#                 messages.success(request, at_msg)
#             return redirect('barcode_attendance')

#         else:
#             messages.error(request, "إجراء غير مدعوم.")
#             return redirect('barcode_attendance')

#     # في حالة GET أو إعادة عرض الصفحة بعد 'scan' غير مدفوع
#     return render(request, 'attendance.html', context)


# def get_absence_message(student, today, consecutive_days, total_absences, paid):
#     """
#     يُعيد رسالة مُخصصة بناءً على:
#     - consecutive_days: عدد الأيام المتتابعة للغياب حتى اليوم
#     - total_absences: إجمالي عدد أيام الغياب في الشهر الحالي
#     - paid: حالة الدفع الحالية (True إذا الاشتراك نشط)
#     """
#     date_str = today.strftime("%Y-%m-%d")
#     base_header = f"📋 متابعة حضور ابنك {student.name}\n\n"
#     signature = "\n\nنتمنى دوام التوفيق لابنك/بنتك،\nفريق الإدارة والتعليم 💼"

#     # إضافة تذكير بالدفع إن لم يكن فعالاً
#     payment_reminder = ""
#     if not paid:
#         payment_reminder = (
#             "\n\n⚠️ لاحظنا أن الاشتراك غير مفعّل، لضمان استمرار حضور ابنك/ابنتك بانتظام، يرجى تجديد الاشتراك في أقرب وقت."
#         )

#     # أول غياب للطالب في الشهر
#     if total_absences == 1 and consecutive_days == 1:
#         return (
#             base_header +
#             f"احنا لاحظنا غياب ابنك/ابنتك اليوم ({date_str}).\n"
#             "يا ريت تبلغونا بسبب الغياب لو في ظرف طارئ، عشان نقدر نساند ابنك.\n"
#             + payment_reminder + signature
#         )

#     # غياب متتابع يومين
#     if consecutive_days == 2:
#         return (
#             base_header +
#             f"⚠️ غياب لليوم الثاني على التوالي ({date_str}).\n"
#             "مهم نعرف السبب عشان نساعد في تدارك أي نقص دراسي.\n"
#             + payment_reminder + signature
#         )

#     # غياب متتابع 3 أيام أو أكثر
#     if consecutive_days >= 3:
#         return (
#             base_header +
#             f"🚨 غياب متكرر: ابنك/ابنتك غائب منذ {consecutive_days} أيام حتى ({date_str}).\n"
#             "يهمنا التواصل معكم فوراً لمناقشة الوضع وتقديم أي دعم أو حل مناسب.\n"
#             + payment_reminder + signature
#         )

#     # غياب متقطع (ليس متتابعاً مع اليوم السابق)
#     if consecutive_days == 1 and total_absences > 1:
#         return (
#             base_header +
#             f"لاحظنا تكرار الغياب اليوم ({date_str}) بعد غيبه سابقاً هذا الشهر.\n"
#             "يرجى متابعة انتظام الحضور ودعم ابنك/ابنتك للالتزام.\n"
#             + payment_reminder + signature
#         )

#     # حالات عامة أخرى
#     return (
#         base_header +
#         f"تم تسجيل غياب ابنك/ابنتك اليوم ({date_str}).\n"
#         "لو في أي استفسار أو ظرف خاص، تواصلوا معانا.\n"
#         + payment_reminder + signature
#     )


# def mark_absentees_view(request):
#     """
#     يسجل غياب جميع الطلاب الذين لم يحضروا اليوم، ويرسل إشعار WhatsApp لأولياء أمورهم مع رسالة مخصصة لكل حالة.
#     """
#     if request.method != 'POST':
#         return redirect('barcode_attendance')

#     today = timezone.localdate()
#     now_time = timezone.localtime().time()
#     month_start = today.replace(day=1)

#     # جلب جميع الطلاب والحاضرين اليوم
#     all_students = Students.objects.all()
#     attended_ids = Attendance.objects.filter(
#         attendance_date=today,
#         is_absent=False
#     ).values_list('student_id', flat=True)
#     absentees = all_students.exclude(id__in=attended_ids)

#     for student in absentees:
#         # إذا لم نسجل للطالب شيئاً اليوم
#         if Attendance.objects.filter(student=student, attendance_date=today).exists():
#             continue

#         # علامة غياب
#         Attendance.objects.create(
#             student=student,
#             attendance_date=today,
#             is_absent=True
#         )

#         # حساب الأيام المتتابعة للغياب
#         consecutive_days = 1
#         yesterday = today - timedelta(days=1)
#         if Attendance.objects.filter(student=student, attendance_date=yesterday, is_absent=True).exists():
#             consecutive_days += 1
#             day_before = today - timedelta(days=2)
#             if Attendance.objects.filter(student=student, attendance_date=day_before, is_absent=True).exists():
#                 consecutive_days += 1

#         # حساب إجمالي الغيابات منذ بداية الشهر
#         total_absences = Attendance.objects.filter(
#             student=student,
#             attendance_date__gte=month_start,
#             is_absent=True
#         ).count()

#         # تحقق حالة الدفع الحالية
#         paid = has_active_payment(student, today)
#         # بناء الرسالة المناسبة
#         text = get_absence_message(student, today, consecutive_days, total_absences, paid)

#         # أرسل الرسالة باستخدام send_or_log
#         send_or_log(student, text, 'Absence Alert')

#     messages.success(request, "✅ تم تسجيل غياب اليوم وإرسال إشعارات مخصصة لأولياء الأمور.")
#     return redirect('barcode_attendance')



def barcode_attendance_view(request):
    today = timezone.localdate()
    current_time = timezone.localtime().time()
    context = {'now': today}
    basics = Basics.objects.first()
    if request.method == 'POST':
        if not basics:
            # لا توجد إعدادات النظام
            messages.error(request, "خطأ: إعدادات النظام الأساسية غير موجودة. تواصل مع مسؤول النظام.")
            return redirect('barcode_attendance')

        action = request.POST.get('action', 'scan')
        barcode = request.POST.get('barcode', '').strip()
        if not barcode:
            messages.error(request, "❌ الرجاء إدخال الباركود.")
            return redirect('barcode_attendance')
        try:
            student = Students.objects.get(barcode=barcode)
        except Students.DoesNotExist:
            messages.error(request, "❌ هذا الباركود غير صالح. الرجاء المحاولة مرة أخرى.")
            return redirect('barcode_attendance')

        # إذا مسجل حضور اليوم مسبقاً
        if Attendance.objects.filter(student=student, attendance_date=today).exists():
            # نضع اسم الطالب بين نجمتين لظهور bold في الواجهة إن رغبنا: *اسم*
            messages.warning(request, f"⚠️ حضور *{student.name}* اليوم مسجل مسبقاً.")
            return redirect('barcode_attendance')

        paid = has_active_payment(student, today)
        # تحديد هل المتأخر بعد الوقت المحدد؟
        late_time = getattr(basics, 'late_arrival_time', None)
        is_late = bool(late_time and current_time > late_time)

        if action == 'scan':
            if paid:
                # تسجيل حضور مدفوع (أو اشتراك ساري)
                Attendance.objects.create(
                    student=student,
                    attendance_date=today,
                    arrival_time=current_time
                )
                # بناء رسالة موحدة: تأخير + تأكيد الحضور
                # تنسيق اسم الطالب بالـ*bold* مباشرة
                # pronoun: نفترض "ابنك/ابنتك"، أو عدّل الصيغة لو أضفت حقل gender
                pronoun = getattr(student, 'pronoun', 'ابنك/ابنتك')
                # بداية التحية مع تنسيق الاسم بين نجمتين
                header = f"👋 أهلاً ولي أمر *{student.name}*،\n\n"
                body = ""
                if is_late:
                    # قسم التأخير
                    body += (
                        f"سجلنا وصول {pronoun} الساعة *{current_time.strftime('%H:%M')}* اليوم، ولاحظنا تأخرًا عن الموعد المعتاد.\n"
                        "نقدّر تعاونكم في الحضور أبكر كي يبدأ اليوم الدراسي بنشاط.\n"
                        "إذا كان هناك ظرف خاص يمنع الوصول في الموعد، يُرجى إفادتنا مسبقًا لنساعد في التنسيق.\n\n"
                    )
                # قسم التأكيد العام
                body += (
                    "📌 تم تسجيل حضور " + pronoun + " بنجاح اليوم.\n"
                    f"🗓️ التاريخ: *{today.strftime('%Y-%m-%d')}*\n"
                    f"⏰ الوقت: *{current_time.strftime('%H:%M')}*\n\n"
                    "نتمنى له/لها يومًا دراسيًا ناجحًا ومثمرًا! 📚\n"
                    "إذا كان لديكم أي ملاحظات أو استفسارات، تواصلوا معنا.\n"
                )
                # التوقيع
                footer = "\n\nمع تحيات *فريق الإدارة والتعليم* 👍"
                message_text = header + body + footer
                send_or_log(student, message_text, 'Attendance')
                messages.success(request, f"✅ تم تسجيل حضور *{student.name}* بنجاح.")
                return redirect('barcode_attendance')
            else:
                # غير مدفوع: عرض خيارات الدفع أو الفرصة المجانية
                context.update({
                    'pending_student': student,
                    'barcode': barcode,
                    'month_price': basics.month_price,
                    'term_price': basics.term_price,
                    'default_term_duration': basics.default_term_duration_months,
                    'is_late': is_late,
                })
                if student.free_tries > 0:
                    warn = f"❗ لديك {student.free_tries} {'فرصة' if student.free_tries == 1 else 'فرص'} مجانية"
                    if is_late:
                        warn += " (تم تسجيل وصول متأخر اليوم)"
                    messages.warning(request, warn + ". يفضل تجديد الاشتراك لضمان حضور مستمر.")
                else:
                    messages.warning(request, "⚠️ انتهت فرصك المجانية لهذا الشهر، الرجاء الدفع للاستمرار بدون انقطاع.")
                # لا ترسل رسالة هنا، يتم الإرسال في فرع 'free' أو 'pay'
        elif action == 'free':
            if student.free_tries > 0:
                # إعادة حساب التأخير في نفس الطلب
                Attendance.objects.create(
                    student=student,
                    attendance_date=today,
                    arrival_time=current_time
                )
                student.free_tries -= 1
                student.save(update_fields=['free_tries'])
                pronoun = getattr(student, 'pronoun', 'ابنك/ابنتك')
                header = f"👋 أهلاً ولي أمر *{student.name}*،\n\n"
                body = ""
                if is_late:
                    body += (
                        f"سجلنا وصول {pronoun} الساعة *{current_time.strftime('%H:%M')}* اليوم، ولاحظنا تأخرًا عن الموعد المعتاد.\n"
                        "نقدّر تعاونكم في الحضور أبكر كي يبدأ اليوم الدراسي بنشاط.\n"
                        "إذا كان هناك ظرف خاص يمنع الوصول في الموعد، يُرجى إفادتنا مسبقًا لنساعد في التنسيق.\n\n"
                    )
                body += (
                    f"📌 تم تسجيل حضور اليوم كفرصة مجانية، وتبقى لديك *{student.free_tries}* "
                    f"{'فرصة' if student.free_tries == 1 else 'فرص'} لهذا الشهر.\n\n"
                    "ننصح بتجديد الاشتراك لضمان حضور منتظم دون قيود.\n"
                )
                footer = "\n\nمع تحيات *فريق الإدارة والتعليم* 🚀"
                message_text = header + body + footer
                send_or_log(student, message_text, 'FreeTry')
                messages.success(request, f"✅ حضور مجاني: تبقى لديك {student.free_tries} {'فرصة' if student.free_tries == 1 else 'فرص'}.")
            else:
                messages.error(request, "❌ لا توجد فرص مجانية متبقية، الرجاء الدفع.")
            return redirect('barcode_attendance')
        elif action == 'pay':
            payment_option = request.POST.get('payment_option', 'monthly')
            month_start = date(today.year, today.month, 1)
            with transaction.atomic():
                created = False
                dp_msg = ""
                if payment_option == 'termly':
                    term_duration = basics.default_term_duration_months or 1
                    pay_amount = basics.term_price
                    payment, created = Payment.objects.get_or_create(
                        student=student,
                        month=month_start,
                        payment_type='term',
                        defaults={
                            'term_duration_months': term_duration,
                            'paid_on': timezone.now()
                        }
                    )
                    if not created and payment.term_duration_months != term_duration:
                        payment.term_duration_months = term_duration
                        payment.paid_on = timezone.now()
                        payment.save(update_fields=['term_duration_months', 'paid_on'])
                        created = True
                    if created:
                        dp_msg = f"✅ تم استلام اشتراك فصل يبدأ {month_start.strftime('%B %Y')} لمدة {term_duration} أشهر بقيمة {pay_amount}ج."
                    else:
                        dp_msg = f"ℹ️ اشتراك الفصل الحالي ({month_start.strftime('%B %Y')}) مسجل مسبقاً بنفس المدة."
                else:
                    pay_amount = basics.month_price
                    payment, created = Payment.objects.get_or_create(
                        student=student,
                        month=month_start,
                        payment_type='monthly',
                        defaults={'term_duration_months': None, 'paid_on': timezone.now()}
                    )
                    if created:
                        dp_msg = f"✅ تم استلام اشتراك شهر {month_start.strftime('%B %Y')} بقيمة {pay_amount}ج."
                    else:
                        dp_msg = f"ℹ️ اشتراك شهر {month_start.strftime('%B %Y')} مسجل مسبقاً."
                if created:
                    student.free_tries = basics.free_tries
                    student.last_reset_month = month_start
                    student.save(update_fields=['free_tries', 'last_reset_month'])
                # تسجيل الحضور بعد الدفع
                Attendance.objects.create(
                    student=student,
                    attendance_date=today,
                    arrival_time=current_time
                )
                # بناء رسالة تتضمن التأخير إن وجد + نص الدفع + تأكيد الحضور
                pronoun = getattr(student, 'pronoun', 'ابنك/ابنتك')
                header = f"👋 أهلاً ولي أمر *{student.name}*،\n\n"
                body = ""
                if is_late:
                    body += (
                        f"سجلنا وصول {pronoun} الساعة *{current_time.strftime('%H:%M')}* اليوم، ولاحظنا تأخرًا عن الموعد المعتاد.\n"
                        "نقدّر تعاونكم في الحضور أبكر كي يبدأ اليوم الدراسي بنشاط.\n"
                        "إذا كان هناك ظرف خاص يمنع الوصول في الموعد، يُرجى إفادتنا مسبقًا لنساعد في التنسيق.\n\n"
                    )
                body += dp_msg + "\n\n"
                body += (
                    f"✅ تم تسجيل حضور {pronoun} اليوم.\n"
                    f"🗓️ التاريخ: *{today.strftime('%Y-%m-%d')}*\n"
                    f"⏰ الوقت: *{current_time.strftime('%H:%M')}*\n\n"
                    "شكرًا لتعاونكم وثقتكم بنا! إذا كان لديكم أي استفسار بخصوص الاشتراك، تواصلوا معنا.\n"
                )
                footer = "\n\nمع تحيات *فريق الإدارة والتعليم* 👍"
                message_text = header + body + footer
                send_or_log(student, message_text, 'PaymentAttendance')
                messages.success(request, dp_msg)
                messages.success(request, f"✅ تم تسجيل حضور *{student.name}* اليوم بعد الدفع.")
            return redirect('barcode_attendance')
        else:
            messages.error(request, "إجراء غير مدعوم.")
            return redirect('barcode_attendance')
    # GET أو إعادة عرض القالب
    return render(request, 'attendance.html', context)


def mark_absentees_view(request):
    if request.method != 'POST':
        return redirect('barcode_attendance')
    today = timezone.localdate()
    month_start = today.replace(day=1)
    all_students = Students.objects.all()
    attended_ids = Attendance.objects.filter(attendance_date=today, is_absent=False).values_list('student_id', flat=True)
    absentees = all_students.exclude(id__in=attended_ids)
    for student in absentees:
        # إذا سجلنا حضور أو غياب بالفعل اليوم، نتخطى
        if Attendance.objects.filter(student=student, attendance_date=today).exists():
            continue
        # تسجيل الغياب
        Attendance.objects.create(student=student, attendance_date=today, is_absent=True)
        # حساب الأيام المتتابعة للغياب
        consecutive_days = 1
        yesterday = today - timedelta(days=1)
        if Attendance.objects.filter(student=student, attendance_date=yesterday, is_absent=True).exists():
            consecutive_days += 1
            day_before = today - timedelta(days=2)
            if Attendance.objects.filter(student=student, attendance_date=day_before, is_absent=True).exists():
                consecutive_days += 1
        # إجمالي الغيابات منذ بداية الشهر
        total_absences = Attendance.objects.filter(
            student=student,
            attendance_date__gte=month_start,
            is_absent=True
        ).count()
        paid = has_active_payment(student, today)
        # بناء رسالة الغياب كما في الدالة السابقة لكن inline
        pronoun = getattr(student, 'pronoun', 'ابنك/ابنتك')
        header = f"📋 متابعة حضور *{student.name}*\n\n"
        date_str = today.strftime("%Y-%m-%d")
        body = ""
        if total_absences == 1 and consecutive_days == 1:
            body = (
                f"لاحظنا غياب {pronoun} اليوم (*{date_str}*).\n"
                "يرجى إعلامنا بالسبب إن كان ظرف طارئًا لنتمكن من المساعدة.\n"
            )
        elif consecutive_days == 2:
            body = (
                f"⚠️ غياب لليوم الثاني على التوالي (*{date_str}*).\n"
                "مهم معرفة السبب لتدارك أي نقص دراسي.\n"
            )
        elif consecutive_days >= 3:
            body = (
                f"🚨 غياب متكرر: {pronoun} غائب منذ *{consecutive_days}* أيام حتى (*{date_str}*).\n"
                "يهمنا التواصل معكم فورًا لمناقشة الوضع وتقديم الدعم المناسب.\n"
            )
        elif consecutive_days == 1 and total_absences > 1:
            body = (
                f"لاحظنا تكرار غياب {pronoun} اليوم (*{date_str}*) بعد غيابه سابقًا هذا الشهر.\n"
                "يرجى متابعة انتظام الحضور ودعم " + pronoun + " للالتزام.\n"
            )
        else:
            body = (
                f"تم تسجيل غياب {pronoun} اليوم (*{date_str}*).\n"
                "إذا كان هناك أي ظرف خاص أو استفسار، تواصلوا معنا.\n"
            )
        # تذكير الدفع إذا غير مفعل
        if not paid:
            body += "\n⚠️ لاحظنا أن الاشتراك غير مفعل، لضمان استمرار حضور " + pronoun + " بانتظام، يرجى تجديد الاشتراك في أقرب وقت.\n"
        footer = "\n\nنتمنى دوام التوفيق لـ" + pronoun + "،\nمع تحيات *فريق الإدارة والتعليم* 💼"
        message_text = header + body + footer
        send_or_log(student, message_text, 'Absence Alert')
    messages.success(request, "✅ تم تسجيل غياب اليوم وإرسال إشعارات مخصصة لأولياء الأمور.")
    return redirect('barcode_attendance')

# #################################################################################


def daily_dashboard_view(request):
    """
    Displays a daily dashboard with attendance summary and students with overdue payments.

    Retrieves data for the current day using utility functions:
    - `get_daily_attendance_summary`: For counts of present, absent, and unmarked students,
      and lists of these students.
    - `get_students_with_overdue_payments`: For a list of students who haven't paid
      for the current month.

    Args:
        request: HttpRequest object.

    Returns:
        HttpResponse object rendering the `students/daily_dashboard.html` template
        with the following context:
        - 'dashboard_date' (date): The current date for which the dashboard is displayed.
        - 'attendance_summary' (dict): Data from `get_daily_attendance_summary`.
        - 'overdue_payment_students' (QuerySet[Students]): Students with overdue payments.
        - 'page_title' (str): The title for the page ("لوحة المتابعة اليومية").
    """
    today = timezone.localdate()
    # Fetch daily attendance summary (present, absent, unmarked students)
    attendance_summary = get_daily_attendance_summary(today)
    # Fetch students who have not paid for the current month
    overdue_payment_students = get_students_with_overdue_payments()

    context = {
        'dashboard_date': today,
        'attendance_summary': attendance_summary,
        'overdue_payment_students': overdue_payment_students,
        'page_title': 'لوحة المتابعة اليومية' # Daily Dashboard
    }
    return render(request, 'students/daily_dashboard.html', context)


def historical_insights_view(request):
    """
    Provides a view for historical data analysis based on user-selected criteria.

    Supports various report types selected via GET parameters:
    - 'attendance_trends': Shows daily, weekly, and monthly attendance counts.
    - 'revenue_trends': Shows monthly and yearly estimated revenue.
    - 'student_attendance_rate': Calculates monthly attendance rate for a selected student.
    - 'student_payment_history': Lists payment history for a selected student.

    Accepts GET parameters for filtering:
    - 'report_type': The type of report to generate.
    - 'student_id': ID of the student for student-specific reports.
    - 'start_date', 'end_date': Date range for trend reports.
    - 'year', 'month': For student attendance rate report.

    Args:
        request: HttpRequest object.

    Returns:
        HttpResponse object rendering the `students/historical_insights.html` template
        with a context containing:
        - 'page_title' (str): Title of the page.
        - 'students' (QuerySet[Students]): All students for selection.
        - 'current_year' (int): Current year for form defaults.
        - 'start_date_val', 'end_date_val': Current values for date inputs.
        - 'selected_student_id', 'selected_year', 'selected_month', 'selected_report_type':
          Current selections for form fields.
        - Data specific to the report type (e.g., 'attendance_trends', 'revenue_trends_monthly',
          'monthly_attendance_rate', 'payment_history').
        - Error messages ('date_error', 'student_error', 'form_error') if applicable.
    """
    context = {
        'page_title': 'التحليلات التاريخية',  # Historical Insights
        'students': Students.objects.all().order_by('name'),  # For student selection dropdown
        'current_year': timezone.localdate().year,
        'branch_choices': Students.BRANCH_CHOICES, # Add branch choices
    }
    
    report_type = request.GET.get('report_type')
    student_id = request.GET.get('student_id')
    selected_branch = request.GET.get('branch') # Get selected branch
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')
    year_str = request.GET.get('year')
    month_str = request.GET.get('month')
    
    context['selected_branch'] = selected_branch # Add to context

    # Default date range for trends (e.g., last 30 days if not specified)
    default_end_date = timezone.localdate()
    default_start_date = default_end_date - timezone.timedelta(days=30) # Default to 30 days prior

    # Populate context with current form values or defaults
    context['start_date_val'] = start_date_str if start_date_str else default_start_date.isoformat()
    context['end_date_val'] = end_date_str if end_date_str else default_end_date.isoformat()
    context['selected_student_id'] = int(student_id) if student_id else None
    context['selected_year'] = int(year_str) if year_str else default_end_date.year
    context['selected_month'] = int(month_str) if month_str else default_end_date.month
    context['selected_report_type'] = report_type

    # Attempt to parse date strings from GET parameters; use defaults if parsing fails or not provided.
    try:
        start_date_obj = datetime.strptime(start_date_str, '%Y-%m-%d').date() if start_date_str else default_start_date
        end_date_obj = datetime.strptime(end_date_str, '%Y-%m-%d').date() if end_date_str else default_end_date
    except ValueError:
        # If date parsing fails, revert to defaults and set an error message.
        start_date_obj = default_start_date
        end_date_obj = default_end_date
        context['date_error'] = "صيغة التاريخ غير صحيحة. فضلا استخدم YYYY-MM-DD."

    # --- Generate report data based on report_type ---
    if report_type == 'attendance_trends':
        # Fetch daily, weekly, and monthly attendance trends for the selected date range.
        context['attendance_trends'] = get_attendance_trends(start_date_obj, end_date_obj, period='day', branch_id=selected_branch)
        context['attendance_trends_weekly'] = get_attendance_trends(start_date_obj, end_date_obj, period='week', branch_id=selected_branch)
        context['attendance_trends_monthly'] = get_attendance_trends(start_date_obj, end_date_obj, period='month', branch_id=selected_branch)
    
    elif report_type == 'revenue_trends':
        # Fetch monthly and yearly revenue trends for the selected date range.
        context['revenue_trends_monthly'] = get_revenue_trends(start_date_obj, end_date_obj, period='month', branch_id=selected_branch)
        context['revenue_trends_yearly'] = get_revenue_trends(start_date_obj, end_date_obj, period='year', branch_id=selected_branch)

    elif report_type and student_id: # Student-specific reports
        try:
            selected_student = Students.objects.get(id=student_id)
            context['selected_student'] = selected_student # Add selected student to context
            
            if report_type == 'student_attendance_rate':
                # Determine year and month for the report, defaulting to current year/month.
                year = int(year_str) if year_str else timezone.localdate().year
                month = int(month_str) if month_str else timezone.localdate().month
                
                monthly_rate = get_monthly_attendance_rate(selected_student, year, month)
                if monthly_rate is None:
                    context['form_error'] = "الشهر أو السنة المحددة غير صالحة."
                    # Ensure rate variables are not set or are cleared if error occurs
                    if 'monthly_attendance_rate' in context: del context['monthly_attendance_rate']
                    if 'rate_year' in context: del context['rate_year']
                    if 'rate_month' in context: del context['rate_month']
                else:
                    context['monthly_attendance_rate'] = monthly_rate
                    context['rate_year'] = year
                    context['rate_month'] = month
            
            elif report_type == 'student_payment_history':
                context['payment_history'] = get_student_payment_history(selected_student)
                
        except Students.DoesNotExist:
            context['student_error'] = "الطالب المحدد غير موجود."
        except ValueError: # Handles errors from int(year_str) or int(month_str)
            context['form_error'] = "سنة أو شهر غير صالح."
            # Optionally, clear potentially misleading partial data if year/month were bad
            if 'monthly_attendance_rate' in context: del context['monthly_attendance_rate']

    return render(request, 'students/historical_insights.html', context)


def broadcast_message_view(request):
    if request.method == 'POST':
        message_content = request.POST.get('message', '').strip()
        if not message_content:
            messages.error(request, "❌ لا يمكن إرسال رسالة فارغة.")
            return redirect('broadcast_message')

        all_students = Students.objects.all()
        if not all_students:
            messages.warning(request, "⚠️ لا يوجد طلاب مسجلين لإرسال الرسالة إليهم.")
            return redirect('broadcast_message')

        broadcast_header = "📢 *رسالة عامة من الإدارة:*\n\n"
        broadcast_signature = "\n\nمع تحيات،\n*م. عبدالله عمر وفريق العمل* 👨‍🏫"

        send_count = 0
        for student in all_students:
            personalized_content = message_content.replace('{student_name}', student.name)
            full_message = broadcast_header + personalized_content + broadcast_signature
            send_or_log(student, full_message, 'Broadcast Message')
            
            # To maintain an accurate count of messages *attempted* to be sent (i.e., phone and whatsapp enabled)
            if student.father_phone and student.has_whatsapp:
                send_count += 1

        if send_count > 0:
            messages.success(request, f"✅ تم إرسال الرسالة إلى {send_count} ولي أمر بنجاح.")
        else:
            messages.warning(request, "⚠️ لم يتم إرسال الرسالة لأي ولي أمر (قد لا يكون هناك أرقام هواتف مسجلة).")
        return redirect('broadcast_message')

    return render(request, 'broadcast_message.html')

def income_report_view(request):
    """
    يعرض تقرير الدخل بناءً على المدفوعات المسجلة.
    """
    payments = Payment.objects.all().order_by('-paid_on')
    month_payments= payments.filter(payment_type='monthly').order_by('-paid_on')
    term_payments= payments.filter(payment_type='term').order_by('-paid_on')
    
    try:
        basics = Basics.objects.get(id=1)
        month_price = basics.month_price
        term_price = basics.term_price
    except Basics.DoesNotExist:
        # Fallback or error handling if Basics instance is not found
        messages.error(request, "لم يتم تحديد سعر الشهر الأساسي. يرجى مراجعة الإعدادات.")
        month_price = 0 # Default to 0 if not set, to avoid further errors
        # Or redirect to an admin/setup page
        # return redirect('some_admin_setup_page')

    total_income_month = month_payments.count() * month_price
    total_income_term = term_payments.count() * term_price
    total_income = total_income_month+total_income_term
    
    now = timezone.now()
    month_year = now.strftime("%B %Y") # Example: "October 2023"
    # For Arabic month names, you might need a custom mapping or locale settings
    # For simplicity, using English month names as strftime default
    
    context = {
        'payments': payments,
        'month_payments':month_payments,
        'term_payments':term_payments,
        'month_price': month_price, # This is the price for EACH payment listed
        'term_price': term_price, # This is the price for EACH payment listed
        'total_income': total_income,
        'month_year': month_year,
    }
    
    return render(request, 'income.html', context)

def home_view(request):
    """
    Renders the home page.
    """
    return render(request, 'home.html')
