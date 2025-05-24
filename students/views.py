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
<<<<<<< HEAD
from datetime import date
from datetime import timedelta
from django.db.models import Count, F, ExpressionWrapper, fields # Added for performance dashboard
from django.utils import timezone as django_timezone # Renamed to avoid conflict with today = timezone.localdate()
from .utils.risk_assessment_utils import get_student_risk_assessment # Added for risk assessment
from .utils.whatsapp_queue import send_low_recent_attendance_warning, send_high_risk_alert # Moved from here
=======
from datetime import date, datetime # Added datetime
from .utils import (
    get_daily_attendance_summary, get_students_with_overdue_payments, # Kept existing ones
    get_attendance_trends, get_revenue_trends,
    get_monthly_attendance_rate, get_student_payment_history
)
from .models import Students # To populate student selection

>>>>>>> feat/student-data-insights

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
<<<<<<< HEAD
=======
    threading.Thread(
        target=queue_whatsapp_message,
        args=(student.father_phone, text),
        daemon=True
    ).start()

>>>>>>> feat/student-data-insights
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
<<<<<<< HEAD
    
    LOW_ATTENDANCE_THRESHOLD_PERCENT = 50.0
    LOW_ATTENDANCE_PERIOD_DAYS = 10 # Check over last 10 school days

    for student in absentees:
        # إذا لم نسجل للطالب شيئاً اليوم (حضور أو غياب)
        if Attendance.objects.filter(student=student, attendance_date=today).exists():
            continue

        # 1. ضع علامة غياب
        current_absence_record = Attendance.objects.create(
=======

    for student in absentees:
        # إذا لم نسجل للطالب شيئاً اليوم
        if Attendance.objects.filter(student=student, attendance_date=today).exists():
            continue

        # ضع علامة غياب
        Attendance.objects.create(
>>>>>>> feat/student-data-insights
            student=student,
            attendance_date=today,
            is_absent=True
        )

<<<<<<< HEAD
        # 2. حساب الأيام المتتابعة للغياب (الموجودة سابقاً)
=======
        # حساب الأيام المتتابعة للغياب
>>>>>>> feat/student-data-insights
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

<<<<<<< HEAD
        # بناء الرسالة المناسبة للغياب (الموجودة سابقاً)
        text_consecutive_absence = get_absence_message(student, today, consecutive_days, total_absences)
        
        # أرسل رسالة الغياب المتتالي أولاً
        if text_consecutive_absence: # Only send if a message was generated
            threading.Thread(
                target=queue_whatsapp_message,
                args=(student.father_phone, text_consecutive_absence),
                daemon=True
            ).start()

        # --- NEW: Notification for Consistently Low Attendance ---
        # Only check if it's not the first absence this month to avoid immediate double alert
        # total_absences includes the one just recorded
        sent_low_attendance_warning = False
        if total_absences > 1: # Student has been absent before this month
            # Calculate attendance rate over the last LOW_ATTENDANCE_PERIOD_DAYS school days
            start_date_period = today - timedelta(days=LOW_ATTENDANCE_PERIOD_DAYS * 2) # Approx window to find X school days
            
            # Find actual school days in this period (days with any attendance record)
            # Querying all attendance records in a wide window and then processing in Python
            # can be inefficient. Better to get distinct dates from DB.
            
            # Get the dates of the last X school days before 'today'
            recent_school_days_dates = list(Attendance.objects.filter(
                attendance_date__lt=today # Exclude today as we just marked them absent
            ).order_by('-attendance_date').values_list('attendance_date', flat=True).distinct())[:LOW_ATTENDANCE_PERIOD_DAYS]

            if len(recent_school_days_dates) == LOW_ATTENDANCE_PERIOD_DAYS: # Ensure we have enough data
                # Filter these dates to be within a reasonable actual timeframe (e.g. last 30 calendar days)
                # This is to avoid using very old "school days" if school was closed for a long time.
                # For simplicity here, we use the X distinct school days found.
                # The period starts from the oldest of these X school days.
                period_start_date_for_calc = recent_school_days_dates[-1]

                present_count_period = Attendance.objects.filter(
                    student=student,
                    attendance_date__gte=period_start_date_for_calc,
                    attendance_date__lt=today, # Up to yesterday
                    is_present=True
                ).count()
                
                # Number of school days in this specific student's calculation period
                # is LOW_ATTENDANCE_PERIOD_DAYS because we fetched that many distinct dates.
                actual_school_days_in_student_period = len(recent_school_days_dates)

                if actual_school_days_in_student_period > 0:
                    recent_attendance_rate = (present_count_period / actual_school_days_in_student_period) * 100
                    if recent_attendance_rate < LOW_ATTENDANCE_THRESHOLD_PERCENT:
                        send_low_recent_attendance_warning(student.name, student.father_phone, recent_attendance_rate, actual_school_days_in_student_period)
                        sent_low_attendance_warning = True # Flag that this was sent

        # --- NEW: Notification for High Dropout Risk ---
        # Get risk assessment.
        # Avoid sending if a low attendance warning was just sent, as high risk might be due to that.
        # This logic can be refined: e.g. send if risk is high for *other* reasons.
        if not sent_low_attendance_warning: # Only proceed if low attendance warning wasn't sent
            risk_level, risk_reasons = get_student_risk_assessment(student) # Assume this function is up-to-date
            if risk_level == 'High':
                # Check if the primary reason for high risk is *already* covered by consecutive absence or low attendance.
                # For simplicity here, we just send the high risk alert if not sent_low_attendance_warning.
                # A more advanced check: if 'low attendance' is the *only* reason for high risk, and warning sent, skip.
                send_high_risk_alert(student.name, student.father_phone, risk_reasons)

    messages.success(request, "✅ تم تسجيل غياب اليوم وإرسال الإشعارات المخصصة (إذا لزم الأمر).")
=======
        # بناء الرسالة المناسبة
        text = get_absence_message(student, today, consecutive_days, total_absences)

        # أرسل الرسالة في Thread منفصل
        threading.Thread(
            target=queue_whatsapp_message,
            args=(student.father_phone, text),
            daemon=True
        ).start()

    messages.success(request, "✅ تم تسجيل غياب اليوم وإرسال إشعارات مخصصة لأولياء الأمور.")
>>>>>>> feat/student-data-insights
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


<<<<<<< HEAD
def performance_dashboard_view(request):
    today = django_timezone.localdate()
    current_month = today.month
    current_year = today.year

    # Fetch all students
    all_students = Students.objects.all()
    total_students_count = all_students.count()

    # Attendance Analysis
    # Overall attendance rate for the current month
    overall_attendance_qs = Attendance.objects.filter(
        attendance_date__month=current_month,
        attendance_date__year=current_year,
        is_absent=False # Count only presence
    )
    
    # To calculate overall rate: (Total present records / (Total students * School days so far))
    # School days so far in the month (approximate, assuming school open every weekday)
    # A more robust way would be to have a calendar of school days.
    # For now, let's count distinct days where any attendance was recorded for any student this month.
    distinct_school_days_count = Attendance.objects.filter(
        attendance_date__month=current_month,
        attendance_date__year=current_year
    ).values('attendance_date').distinct().count()

    if total_students_count > 0 and distinct_school_days_count > 0:
        total_possible_student_days = total_students_count * distinct_school_days_count
        present_count_overall = overall_attendance_qs.count()
        overall_attendance_rate = (present_count_overall / total_possible_student_days) * 100 if total_possible_student_days > 0 else 0
    else:
        overall_attendance_rate = 0


    student_attendance_data = []
    low_attendance_students_list = []
    
    # Days in the current month where attendance *could* have been marked.
    # Using distinct_school_days_count if available, otherwise today.day as a fallback.
    # This means if no attendance was marked at all, individual rates will be 0.
    effective_school_days_for_month = distinct_school_days_count if distinct_school_days_count > 0 else today.day

    students_at_risk = [] # For students with Medium or High risk

    for student in all_students:
        # Attendance rate calculation
        student_present_count = Attendance.objects.filter(
            student=student,
            attendance_date__month=current_month,
            attendance_date__year=current_year,
            is_present=True 
        ).count()
        
        if effective_school_days_for_month > 0:
            rate = (student_present_count / effective_school_days_for_month) * 100
        else:
            rate = 0
        
        # Risk assessment
        risk_level, risk_reasons = get_student_risk_assessment(student)
        
        student_attendance_data.append({
            'name': student.name, 
            'rate': round(rate, 2),
            'risk_level': risk_level,
            'risk_reasons': risk_reasons
        })
        
        if rate < 70: 
            low_attendance_students_list.append(student)
        
        if risk_level == 'High' or risk_level == 'Medium':
            students_at_risk.append({
                'student': student,
                'risk_level': risk_level,
                'risk_reasons': risk_reasons
            })


    # Payment Analysis
    payments_current_month = Payment.objects.filter(
        month__month=current_month, # Assuming 'month' field in Payment is a DateField representing start of month
        month__year=current_year
    )
    paid_students_current_month_ids = payments_current_month.values_list('student_id', flat=True).distinct()
    
    paid_count = len(paid_students_current_month_ids)
    unpaid_count = total_students_count - paid_count
    payment_summary = {'paid': paid_count, 'unpaid': unpaid_count}

    student_payment_data = []
    for student in all_students:
        status = 'Paid' if student.id in paid_students_current_month_ids else 'Unpaid'
        student_payment_data.append({'name': student.name, 'status': status})

    # Free Trials Analysis
    basics_info = Basics.objects.first() 
    default_free_tries = basics_info.free_tries if basics_info else INITIAL_FREE_TRIES # Use constant if Basics not set

    students_on_free_trial_count = 0
    # Students are on free trial if they have free_tries > 0 AND have not paid for the current month.
    for student in all_students:
        # Check if student has free tries remaining AND is not in the list of students who paid this month
        if student.free_tries > 0 and student.id not in paid_students_current_month_ids:
            students_on_free_trial_count += 1
            
    # Conversion Rate: Percentage of students who have paid at least once.
    # This is a general "ever paid" conversion rate.
    students_paid_at_least_once_count = Students.objects.filter(payment__isnull=False).distinct().count()
    
    if total_students_count > 0:
        paid_once_conversion_rate = (students_paid_at_least_once_count / total_students_count) * 100
    else:
        paid_once_conversion_rate = 0
        
    # More specific conversion: Students who used free trials (e.g., last_reset_month is set) and then paid.
    # This requires `last_reset_month` to be reliably set when free trials are given/reset.
    # For now, we use the simpler "paid at least once" metric.
    # If `last_reset_month` is available and used consistently:
    # students_who_had_trials = Students.objects.filter(last_reset_month__isnull=False)
    # converted_after_trial = students_who_had_trials.filter(payment__payment_date__gte=F('last_reset_month')).distinct().count()
    # conversion_rate_after_trial = (converted_after_trial / students_who_had_trials.count() * 100) if students_who_had_trials.count() > 0 else 0
    # For this iteration, `paid_once_conversion_rate` will be used as 'free_trial_conversion_rate'.


    context = {
        'overall_attendance_rate': round(overall_attendance_rate, 2),
        'low_attendance_students': low_attendance_students_list,
        'payment_summary': payment_summary,
        'students_on_free_trial': students_on_free_trial_count,
        'free_trial_conversion_rate': round(paid_once_conversion_rate, 2), 
        'student_attendance_data': student_attendance_data, # Now includes risk info
        'student_payment_data': student_payment_data,
        'students_at_risk': students_at_risk, # Added for template
        'current_month_year': today.strftime("%B %Y"),
        'total_students': total_students_count,
        'default_free_tries': default_free_tries,
        'distinct_school_days_count': distinct_school_days_count, # For transparency in template
    }
    return render(request, 'performance_dashboard.html', context)
=======
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
>>>>>>> feat/student-data-insights
