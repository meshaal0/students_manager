from django.shortcuts import render,redirect
from django.http import FileResponse
from .utils.pdf_generator import generate_barcodes_pdf
from django.shortcuts import get_object_or_404
from django.http import HttpResponse
from .models import Students,Attendance,Payment,Basics
from .utils.barcode_utils import generate_barcode_image
from .utils.whatsapp_queue import queue_whatsapp_message,log_failed_delivery
import os
from django.conf import settings
from django.contrib import messages
from django.utils import timezone
import threading
from datetime import date, datetime,timedelta
from .util import (
    get_daily_attendance_summary, get_students_with_overdue_payments, # Kept existing ones
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

INITIAL_FREE_TRIES = 3

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
def send_or_log(student, text, message_type):
    phone = student.father_phone or ''
    ctx = {
        'student_id': student.id,
        'student_name': student.name,
        'message_type': message_type,
        'reason': ''
    }
    queue_whatsapp_message(phone, text, **ctx)
    if not phone or not student.has_whatsapp:
        reason = 'Missing phone or WhatsApp disabled'
        log_failed_delivery(phone, message_type, reason, 'View-level skip')

# def send_or_log(student, text, message_type):
#     phone = student.father_phone or ''
#     ctx = {
#         'student_id': student.id,
#         'student_name': student.name,
#         'message_type': message_type,
#         'reason': ''
#     }
#     if phone and student.has_whatsapp:
#         queue_whatsapp_message(phone, text, **ctx)
#     else:
#         reason = 'Missing phone or WhatsApp disabled'
#         log_failed_delivery(phone, message_type, reason, 'View-level skip')
#         ctx['reason'] = reason
#         queue_whatsapp_message(phone, text, **ctx)

def barcode_attendance_view(request):
    today = timezone.localdate()
    context = {'now': today}

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
        paid = Payment.objects.filter(student=student, month=month_start).exists()

        if action == 'scan':
            try:
                basics = Basics.objects.first()
                late_arrival_time = basics.late_arrival_time
            except:
                late_arrival_time = None

            if late_arrival_time:
                current_time = timezone.localtime().time()
                if current_time > late_arrival_time:
                    lateness_message = (
                        f"👋 *مرحباً ولي أمر الطالب {student.name}،*\n\n"
                        f"تم تسجيل حضور ابنكم/ابنتكم اليوم الساعة {current_time.strftime('%H:%M')}\.\n"
                        "نأمل الالتزام بالحضور...\n\n"
                        "مع تحيات،\n*م. عبدالله عمر* 😎"
                    )
                    phone = student.father_phone or ''
                    reason = '' if student.father_phone and student.has_whatsapp else 'No WhatsApp or Missing phone'
                    send_or_log(phone, lateness_message, student.id, student.name, 'Lateness Alert', reason)

            if paid:
                Attendance.objects.create(student=student, attendance_date=today)
                messages.success(request, f"✅ تم تسجيل حضور {student.name} بنجاح.")
                attendance_text = (
                    f"👋 *مرحباً ولي أمر الطالب {student.name}،*\n\n"
                    f"📌 *تم تسجيل الحضور بنجاح.*\n"
                    f"🗓️ التاريخ: `{today.strftime('%Y-%m-%d')}`\n"
                    f"⏰ الوقت: `{timezone.localtime().strftime('%H:%M')}`\n\n"
                    "📚 نتمنى له يوماً موفقاً!\n\n"
                    "مع تحيات،\n*م. عبدالله عمر* 😎"
                )
                phone = student.father_phone or ''
                reason = '' if student.father_phone and student.has_whatsapp else 'No WhatsApp or Missing phone'
                send_or_log(phone, attendance_text, student.id, student.name, 'Attendance', reason)
                return redirect('barcode_attendance')
            else:
                context.update({'pending_student': student, 'barcode': barcode})
                if student.free_tries > 0:
                    messages.warning(request, f"❗ لديك {student.free_tries} فرصة مجانية قبل الدفع.")
                else:
                    messages.warning(request, "⚠️ انتهت فرصك المجانية لهذا الشهر، الرجاء الدفع.")

        elif action == 'free':
            if student.free_tries > 0:
                student.free_tries -= 1
                student.save()
                Attendance.objects.create(student=student, attendance_date=today)
                messages.success(request, f"✅ حضور مجانيّ. تبقى لديك {student.free_tries} {'فرصة' if student.free_tries==1 else 'فرص'}.")

                free_text = (
                    f"👋 *مرحباً ولي أمر الطالب {student.name}،*\n\n"
                    f"✅ سجلنا حضور اليوم كفرصة مجانية.\n"
                    f"📌 تبقى {student.free_tries} {'فرصة' if student.free_tries==1 else 'فرص'} لهذا الشهر.\n\n"
                    "🎯 ننصح بسداد الاشتراك لضمان استمرار الحضور دون حدود.\n\n"
                    "– م. عبدالله عمر"
                )
                phone = student.father_phone or ''
                reason = '' if student.father_phone and student.has_whatsapp else 'No WhatsApp or Missing phone'
                send_or_log(phone, free_text, student.id, student.name, 'FreeTry', reason)
            else:
                messages.error(request, "❌ لا توجد فرص مجانية متبقية، الرجاء الدفع.")
            return redirect('barcode_attendance')

        elif action == 'pay':
            payment, created = Payment.objects.get_or_create(student=student, month=month_start)
            student.free_tries = INITIAL_FREE_TRIES
            student.last_reset_month = today.replace(day=1)
            student.save()

            Attendance.objects.create(student=student, attendance_date=today)
            basics = Basics.objects.first()
            pay_amount = basics.month_price if basics else 0
            dp_msg = (
                f"✅ تم استلام اشتراك شهر {payment.month:%B %Y}. بمبلغ {pay_amount} فقط لا غير"
                if created else
                f"ℹ️ دفعتك لشهر {payment.month:%B %Y} مسجلّة مسبقاً."
            )
            at_msg = f"✅ تم تسجيل حضور {student.name} اليوم {today:%Y-%m-%d}."

            combined_text = (
                f"👋 *مرحباً ولي أمر الطالب {student.name}،*\n\n"
                f"{dp_msg}\n"
                f"{at_msg}\n\n"
                "📚 شكراً لتعاونكم!\n\n"
                "مع تحيات،\n*م. عبدالله عمر* 😎"
            )
            phone = student.father_phone or ''
            reason = '' if student.father_phone and student.has_whatsapp else 'No WhatsApp or Missing phone'
            send_or_log(phone, combined_text, student.id, student.name, 'PaymentAttendance', reason)
            messages.success(request, dp_msg)
            messages.success(request, at_msg)
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
    if student.father_phone and student.has_whatsapp:
        queue_whatsapp_message(
            student.father_phone,
            text,
            student_id=student.id,
            student_name=student.name,
            message_type='Lateness Alert',
            reason=''
        )
    else:
        # الكود الذي يسجّل أسباب عدم الإرسال
        queue_whatsapp_message(
            student.father_phone or 'None',
            text,
            student_id=student.id,
            student_name=student.name,
            message_type='Lateness Alert',
            reason='No WhatsApp or Missing phone'
        )
    ctx = {
    'student_id': student.id,
    'student_name': student.name,
    'message_type': 'Attendance',
    'reason': ''
        }
    if student.father_phone and student.has_whatsapp:
        queue_whatsapp_message(student.father_phone, text, **ctx)
    else:
        reason = 'No WhatsApp or Missing phone'
        # سجّل الفشل مباشرةً في الـ CSV
        log_failed_delivery(student.father_phone or '', 'Attendance', reason, 'View-level skip')
        # ما زلنا نمرّر ليتضح في اللوج العادي
        ctx['reason'] = reason
        queue_whatsapp_message(student.father_phone or '', text, **ctx)

def _send_whatsapp_combined(student, dp_msg, at_msg):
    text = (
        f"👋 *مرحباً ولي أمر الطالب {student.name}،*\n\n"
        f"{dp_msg}\n"
        f"{at_msg}\n\n"
        f"📚 شكراً لتعاونكم!\n\n"
        f"مع تحيات،\n*م. عبدالله عمر* 😎"
    )
    if student.father_phone and student.has_whatsapp:
        queue_whatsapp_message(
        student.father_phone,
        text,
        student_id=student.id,
        student_name=student.name,
        message_type='Lateness Alert',
        reason=''
        )
    else:
        # الكود الذي يسجّل أسباب عدم الإرسال
        queue_whatsapp_message(
            student.father_phone or 'None',
            text,
            student_id=student.id,
            student_name=student.name,
            message_type='Lateness Alert',
            reason='No WhatsApp or Missing phone'
        )
    ctx = {
    'student_id': student.id,
    'student_name': student.name,
    'message_type': 'Attendance',
    'reason': ''
        }
    if student.father_phone and student.has_whatsapp:
        queue_whatsapp_message(student.father_phone, text, **ctx)
    else:
        reason = 'No WhatsApp or Missing phone'
        # سجّل الفشل مباشرةً في الـ CSV
        log_failed_delivery(student.father_phone or '', 'Attendance', reason, 'View-level skip')
        # ما زلنا نمرّر ليتضح في اللوج العادي
        ctx['reason'] = reason
        queue_whatsapp_message(student.father_phone or '', text, **ctx)


def get_absence_message(student, today, consecutive_days, total_absences):
    """
    يُعيد رسالة مُخصصة بناءً على:
    - consecutive_days: عدد الأيام المتتابعة للغياب حتى اليوم
    - total_absences: إجمالي عدد أيام الغياب في الشهر الحالي
    """
    date_str = today.strftime("%Y-%m-%d")
    # Using a more neutral and informative emoji for the header
    base_header = f"📋 *متابعة حضور الطالب {student.name}*\n\n"
    signature = "\n\nنتمنى لكم يوماً طيباً،\n*م. عبدالله عمر وفريق العمل* 👨‍🏫" # Slightly warmer signature

    # أول غياب للطالب في الشهر
    if total_absences == 1 and consecutive_days == 1:
        return (
            base_header +
            f" لاحظنا غياب ابنك/ابنتك اليوم ({date_str}).\n" # Softer phrasing
            "🗓️ نأمل إبلاغنا سبب الغياب لنتمكن من تقديم الدعم إذا لزم الأمر.\n" # More supportive
            "📞 لا تترددوا في التواصل معنا لمناقشة أي تفاصيل." +
            signature
        )

    # غياب متتابع يومين
    if consecutive_days == 2:
        return (
            base_header +
            f"⚠️ لاحظنا غياب ابنك/ابنتك لليوم الثاني على التوالي ({date_str}).\n" # Consistent emoji and phrasing
            "📝 نأمل تزويدنا بسبب الغياب لمتابعة تقدمه الدراسي وضمان عدم تأثره.\n" # Focus on progress
            "💬 يرجى التواصل معنا إذا كانت هناك ظروف خاصة تتطلب المساعدة." +
            signature
        )

    # غياب متتابع 3 أيام أو أكثر
    if consecutive_days >= 3:
        return (
            base_header +
            f"🚨 غياب متكرر: نلاحظ أن ابنك/ابنتك غائب منذ {consecutive_days} أيام، حتى تاريخ اليوم ({date_str}).\n" # Clear and direct
            "🧑‍🏫 نود التأكيد على أهمية الحضور المنتظم، ونطلب منكم التواصل معنا لمناقشة الوضع.\n"
            "🤝 إذا كانت هناك أي تحديات تواجه الطالب، فنحن هنا لتقديم الدعم والعمل سوياً لإيجاد حلول مناسبة.\n" +
            "إن كان هناك أي مشاكل أو شكوى، الرجاء إبلاغنا ونعد بأننا سنعمل على حلها والمساعدة إن شاء الله."+ # Retained this important part
            signature
        )

    # غياب متقطع (ليس متتابعاً مع اليوم السابق)
    if consecutive_days == 1 and total_absences > 1:
        return (
            base_header +
            f" لاحظنا تكرار غياب ابنك/ابنتك اليوم ({date_str}) بعد غيابه سابقاً هذا الشهر.\n" # Clearer phrasing
            "📈 نرجو متابعة انتظام الحضور ودعم الطالب للالتزام.\n"
            "💬 إذا احتجتم لأي مساعدة أو استشارة بخصوص انتظام الحضور، فنحن هنا لتقديم الدعم." + # Added offer for help
            signature
        )

    # حالات عامة أخرى (احتياط - should ideally not be reached if logic is correct)
    return (
        base_header +
        f" تم تسجيل غياب ابنك/ابنتك اليوم ({date_str}).\n" # More neutral than "لم يتم تسجيل حضور"
        "📞 يرجى التواصل معنا إذا كان هناك أي استفسار أو لتوضيح سبب الغياب." +
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
        if student.father_phone and student.has_whatsapp:
            queue_whatsapp_message(
            student.father_phone,
            text,
            student_id=student.id,
            student_name=student.name,
            message_type='Lateness Alert',
            reason=''
        )
    else:
        # الكود الذي يسجّل أسباب عدم الإرسال
        queue_whatsapp_message(
            student.father_phone or 'None',
            text,
            student_id=student.id,
            student_name=student.name,
            message_type='Lateness Alert',
            reason='No WhatsApp or Missing phone'
        )

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
        'current_year': timezone.localdate().year
    }
    
    report_type = request.GET.get('report_type')
    student_id = request.GET.get('student_id')
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')
    year_str = request.GET.get('year')
    month_str = request.GET.get('month')

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
        context['attendance_trends'] = get_attendance_trends(start_date_obj, end_date_obj, period='day')
        context['attendance_trends_weekly'] = get_attendance_trends(start_date_obj, end_date_obj, period='week')
        context['attendance_trends_monthly'] = get_attendance_trends(start_date_obj, end_date_obj, period='month')
    
    elif report_type == 'revenue_trends':
        # Fetch monthly and yearly revenue trends for the selected date range.
        context['revenue_trends_monthly'] = get_revenue_trends(start_date_obj, end_date_obj, period='month')
        context['revenue_trends_yearly'] = get_revenue_trends(start_date_obj, end_date_obj, period='year')

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
            phone = student.father_phone or ''
            reason = '' if phone and student.has_whatsapp else 'No WhatsApp or Missing phone'
            if phone:
                personalized_content = message_content.replace('{student_name}', student.name)
                full_message = broadcast_header + personalized_content + broadcast_signature
                # Use send_or_log to queue and log failures
                send_or_log(
                    phone,
                    full_message,
                    student.id,
                    student.name,
                    'Broadcast Message',
                    reason
                )
                send_count += 1
            else:
                # Log missing phone case
                log_failed_delivery(phone, 'Broadcast Message', reason, '')

        if send_count > 0:
            messages.success(request, f"✅ تم إرسال الرسالة إلى {send_count} ولي أمر بنجاح.")
        else:
            messages.warning(request, "⚠️ لم يتم إرسال الرسالة لأي ولي أمر (قد لا يكون هناك أرقام هواتف مسجلة).")
        return redirect('broadcast_message')

    return render(request, 'broadcast_message.html')


# def broadcast_message_view(request):
#     if request.method == 'POST':
#         message_content = request.POST.get('message', '').strip()
#         if not message_content:
#             messages.error(request, "❌ لا يمكن إرسال رسالة فارغة.")
#             return redirect('broadcast_message')

#         all_students = Students.objects.all()
#         if not all_students:
#             messages.warning(request, "⚠️ لا يوجد طلاب مسجلين لإرسال الرسالة إليهم.")
#             return redirect('broadcast_message')

#         # Define standard header and signature
#         broadcast_header = "📢 *رسالة عامة من الإدارة:*\n\n"
#         broadcast_signature = "\n\nمع تحيات،\n*م. عبدالله عمر وفريق العمل* 👨‍🏫"
        
#         send_count = 0
#         for student in all_students:
#             if student.father_phone:
#                 # Personalize the message content
#                 personalized_content = message_content.replace('{student_name}', student.name)
#                 # Combine with header and signature
#                 full_message_for_student = broadcast_header + personalized_content + broadcast_signature
                
#                 threading.Thread(
#                     target=queue_whatsapp_message,
#                     args=(student.father_phone, full_message_for_student),
#                     daemon=True
#                 ).start()
#                 send_count += 1
#             else:
#                 reason = 'Missing father_phone' if not student.father_phone else 'has_whatsapp is False'
#                 log_extra = {'student_id': student.id, 'student_name': student.name, 'message_type': 'Broadcast Message', 'reason': reason}
#                 whatsapp_issue_logger.info("WhatsApp not sent.", extra=log_extra)
        
#         if send_count > 0:
#             messages.success(request, f"✅ تم إرسال الرسالة إلى {send_count} ولي أمر بنجاح.")
#         else:
#             messages.warning(request, "⚠️ لم يتم إرسال الرسالة لأي ولي أمر (قد لا يكون هناك أرقام هواتف مسجلة).")
#         return redirect('broadcast_message')
    
#     return render(request, 'broadcast_message.html')

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
