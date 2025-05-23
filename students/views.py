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
from datetime import date, datetime # Added datetime
from .utils import (
    get_daily_attendance_summary, get_students_with_overdue_payments, # Kept existing ones
    get_attendance_trends, get_revenue_trends,
    get_monthly_attendance_rate, get_student_payment_history
)
from .models import Students # To populate student selection


INITIAL_FREE_TRIES = 3

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


def barcode_attendance_view(request):
    context = {}
    today = timezone.localdate()
    context['now'] = today

    if request.method == 'POST':
        action  = request.POST.get('action', 'scan')
        barcode = request.POST.get('barcode', '').strip()

        # جلب الطالب أو رسالة خطأ
        try:
            student = Students.objects.get(barcode=barcode)
        except Students.DoesNotExist:
            messages.error(request, "❌ هذا الباركود غير صالح. الرجاء المحاولة مرة أخرى.")
            return redirect('barcode_attendance')

        # منع التكرار اليومي
        if Attendance.objects.filter(student=student, attendance_date=today).exists():
            messages.warning(request, f"⚠️ حضور {student.name} اليوم مسجّل مسبقاً.")
            return redirect('barcode_attendance')

        # تحقق الدفع الحالي
        month_start = date(today.year, today.month, 1)
        paid = Payment.objects.filter(student=student, month=month_start).exists()

        # ==== مسح scan ====
        if action == 'scan':
            if paid:
                # مدفوع
                Attendance.objects.create(student=student, attendance_date=today)
                messages.success(request, f"✅ تم تسجيل حضور {student.name} بنجاح.")
                _send_whatsapp_attendance(student, today)
                return redirect('barcode_attendance')
            else:
                # غير مدفوع: عرض دفع وخيارات الفرص المتبقية
                context.update({
                    'pending_student': student,
                    'barcode': barcode,
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

        # ==== استخدام فرصة مجانية ====
        elif action == 'free':
            if student.free_tries > 0:
                # خصم فرصة وتسجيل حضور
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
                threading.Thread(
                    target=queue_whatsapp_message,
                    args=(student.father_phone, text),
                    daemon=True
                ).start()
            else:
                messages.error(request, "❌ لا توجد فرص مجانية متبقية، الرجاء الدفع.")
            return redirect('barcode_attendance')

        # ==== الدفع + تسجيل حضور ====
        elif action == 'pay':
            payment, created = Payment.objects.get_or_create(
                student=student,
                month=month_start
            )
            # إعادة تعيين الفرص فور الدفع
            student.free_tries = INITIAL_FREE_TRIES
            student.last_reset_month = today.replace(day=1)
            student.save()

            # تسجيل حضور اليوم
            Attendance.objects.create(student=student, attendance_date=today)
            pay_amount = Basics.objects.get(id=1)
            dp_msg = (
                f"✅ تم استلام اشتراك شهر {payment.month:%B %Y}. بمبلغ {pay_amount} فقط لا غير"
                if created else
                f"ℹ️ دفعتك لشهر {payment.month:%B %Y} مسجلّة مسبقاً."
            )
            at_msg = f"✅ تم تسجيل حضور {student.name} اليوم {today:%Y-%m-%d}."

            _send_whatsapp_combined(student, dp_msg, at_msg)
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
    threading.Thread(
        target=queue_whatsapp_message,
        args=(student.father_phone, text),
        daemon=True
    ).start()

def _send_whatsapp_combined(student, dp_msg, at_msg):
    text = (
        f"👋 *مرحباً ولي أمر الطالب {student.name}،*\n\n"
        f"{dp_msg}\n"
        f"{at_msg}\n\n"
        f"📚 شكراً لتعاونكم!\n\n"
        f"مع تحيات،\n*م. عبدالله عمر* 😎"
    )
    threading.Thread(
        target=queue_whatsapp_message,
        args=(student.father_phone, text),
        daemon=True
    ).start()


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
        threading.Thread(
            target=queue_whatsapp_message,
            args=(student.father_phone, text),
            daemon=True
        ).start()

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
                context['monthly_attendance_rate'] = get_monthly_attendance_rate(selected_student, year, month)
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
