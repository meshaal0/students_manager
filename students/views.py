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
    get_monthly_attendance_rate, get_student_payment_history,
    process_message_template, get_default_template_context # استيراد الدوال الجديدة
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
    # دالة عرض لمعالجة حضور الطلاب باستخدام الباركود.
    # تعرض الصفحة الرئيسية للحضور وتتعامل مع طلبات POST لتسجيل الحضور.
    context = {} # سياق القالب
    student_for_custom_message = None # سيتم استخدام هذا لتمرير الطالب إلى السياق إذا لزم الأمر
    today = timezone.localdate() # الحصول على تاريخ اليوم الحالي
    context['now'] = today

    if request.method == 'POST': # إذا كان الطلب من نوع POST (تم إرسال بيانات)
        action  = request.POST.get('action', 'scan') # الحصول على نوع الإجراء (مسح، استخدام فرصة، دفع، إرسال رسالة مخصصة)
        
        if action == 'send_custom_message':
            custom_message_content = request.POST.get('custom_message_content', '').strip()
            target_barcode = request.POST.get('target_barcode')
            manual_target_barcode = request.POST.get('manual_target_barcode', '').strip()
            student_to_message = None

            if target_barcode:
                try:
                    student_to_message = Students.objects.get(barcode=target_barcode)
                except Students.DoesNotExist:
                    messages.error(request, f"❌ لم يتم العثور على طالب بالباركود المحدد (المخفي): {target_barcode}")
            elif manual_target_barcode:
                try:
                    student_to_message = Students.objects.get(barcode=manual_target_barcode)
                except Students.DoesNotExist:
                    messages.error(request, f"❌ لم يتم العثور على طالب بالباركود اليدوي: {manual_target_barcode}")
            else:
                messages.error(request, "❌ لم يتم تحديد باركود الطالب لإرسال الرسالة المخصصة.")

            if student_to_message and custom_message_content:
                # إنشاء السياق للمتغيرات
                template_context = get_default_template_context(student_to_message)
                # يمكنك إضافة متغيرات أخرى خاصة بهذه الرسالة إذا أردت
                # template_context['custom_var'] = 'قيمة مخصصة'

                processed_message = process_message_template(custom_message_content, template_context)
                
                # تم إزالة الأسطر التالية لأن get_default_template_context و process_message_template يعالجانها:
                # today_str = timezone.localdate().strftime('%Y-%m-%d')
                # processed_message = processed_message.replace('{student_name}', student_to_message.name)
                # processed_message = processed_message.replace('{barcode}', student_to_message.barcode)
                # processed_message = processed_message.replace('{date}', today_str)
                # يمكنك إضافة المزيد من المتغيرات مثل {father_phone} إذا أردت

                queue_whatsapp_message(student_to_message.father_phone, processed_message)
                messages.success(request, f"✅ تم إرسال الرسالة المخصصة بنجاح إلى ولي أمر الطالب {student_to_message.name}.")
            elif not custom_message_content:
                messages.error(request, "❌ لا يمكن إرسال رسالة فارغة.")
            
            return redirect('barcode_attendance')

        # ==== معالجة الإجراءات الأخرى (scan, free, pay) ====
        barcode = request.POST.get('barcode', '').strip() # الحصول على الباركود المدخل لإجراءات الحضور

        # جلب الطالب أو رسالة خطأ
        # محاولة العثور على طالب بالباركود المدخل
        try:
            student = Students.objects.get(barcode=barcode)
        except Students.DoesNotExist:
            messages.error(request, "❌ هذا الباركود غير صالح. الرجاء المحاولة مرة أخرى.")
            return redirect('barcode_attendance')
        
        student_for_custom_message = student # اجعل الطالب الحالي هو الهدف الافتراضي للرسالة المخصصة

        # منع التكرار اليومي
        # التحقق مما إذا كان الطالب قد سجل حضوره بالفعل اليوم
        if Attendance.objects.filter(student=student, attendance_date=today).exists():
            messages.warning(request, f"⚠️ حضور {student.name} اليوم مسجّل مسبقاً.")
            # حتى لو مسجل مسبقًا، قد نرغب في إرسال رسالة مخصصة له
            context['pending_student'] = student # لتعبئة النموذج بالبيانات الصحيحة
            if student_for_custom_message:
                 context['pending_student_for_message'] = student_for_custom_message
            return render(request, 'attendance.html', context)


        # تحقق الدفع الحالي
        # تحديد أول يوم في الشهر الحالي للتحقق من حالة الدفع
        month_start = date(today.year, today.month, 1)
        # التحقق مما إذا كان الطالب قد دفع اشتراك الشهر الحالي
        paid = Payment.objects.filter(student=student, month=month_start).exists()

        # ==== القسم 1: مسح الباركود العادي (Scan) ====
        # هذا القسم يعالج حالة مسح الباركود العادية حيث يكون الطالب قد دفع الاشتراك.
        if action == 'scan':
            if paid: # إذا كان الطالب قد دفع
                # مدفوع
                Attendance.objects.create(student=student, attendance_date=today) # إنشاء سجل حضور جديد
                # احصل على سجل الحضور الذي تم إنشاؤه للتو لتسجيل وقت الوصول
                attendance_record = Attendance.objects.get(student=student, attendance_date=today, is_absent=False)
                # تسجيل وقت الوصول الفعلي للطالب (وقت مسح الباركود)
                attendance_record.arrival_time = timezone.localtime().time()
                attendance_record.save(update_fields=['arrival_time']) # حفظ التغيير في حقل arrival_time فقط

                # التحقق من التأخير وإرسال رسالة إذا لزم الأمر
                try:
                    basics = Basics.objects.first() # جلب الإعدادات الأساسية (يفترض وجود سجل واحد)
                    # إذا كان هناك آخر وقت مسموح به للحضور مسجل، ووقت وصول الطالب بعد هذا الوقت
                    if basics and basics.last_time and attendance_record.arrival_time > basics.last_time:
                        # إرسال رسالة تنبيه بالتأخير
                        _send_late_arrival_whatsapp_message(student, attendance_record.arrival_time, basics.last_time)
                except Basics.DoesNotExist:
                    pass # تجاهل الخطأ إذا لم يتم العثور على سجل الإعدادات الأساسية (يمكن تسجيل خطأ هنا إذا لزم الأمر)
                messages.success(request, f"✅ تم تسجيل حضور {student.name} بنجاح.")
                _send_whatsapp_attendance(student, today) # إرسال رسالة تأكيد الحضور العادية
                return redirect('barcode_attendance')
            else:
                # غير مدفوع: عرض دفع وخيارات الفرص المتبقية
                # إذا لم يكن الطالب قد دفع، يتم عرض خيارات استخدام فرصة مجانية أو الدفع
                student_for_custom_message = student #  لتمريره للسياق
                context.update({
                    'pending_student': student, # الطالب الذي ينتظر قرارًا
                    'barcode': barcode, # الباركود الخاص به لتسهيل الإجراء التالي
                })
                if student.free_tries > 0: # إذا كان لدى الطالب فرص مجانية متبقية
                    messages.warning(
                        request,
                        f"❗ لديك {student.free_tries} {'فرصة' if student.free_tries==1 else 'فرص'} مجانية قبل الدفع."
                    )
                else: # إذا لم يكن لديه فرص مجانية
                    messages.warning(
                        request,
                        "⚠️ انتهت فرصك المجانية لهذا الشهر، الرجاء الدفع."
                    )

        # ==== القسم 2: استخدام فرصة مجانية (Use Free Try) ====
        # هذا القسم يعالج حالة اختيار الطالب استخدام إحدى فرصه المجانية المتبقية.
        elif action == 'free':
            if student.free_tries > 0: # التأكد مرة أخرى من وجود فرص مجانية
                # خصم فرصة وتسجيل حضور
                student.free_tries -= 1 # خصم فرصة واحدة
                student.save() # حفظ التغييرات في سجل الطالب
                Attendance.objects.create(student=student, attendance_date=today) # إنشاء سجل حضور
                # احصل على سجل الحضور الذي تم إنشاؤه للتو لتسجيل وقت الوصول
                attendance_record = Attendance.objects.get(student=student, attendance_date=today, is_absent=False)
                # تسجيل وقت الوصول الفعلي للطالب
                attendance_record.arrival_time = timezone.localtime().time()
                attendance_record.save(update_fields=['arrival_time'])

                # التحقق من التأخير وإرسال رسالة إذا لزم الأمر (نفس منطق القسم الأول)
                try:
                    basics = Basics.objects.first()
                    if basics and basics.last_time and attendance_record.arrival_time > basics.last_time:
                        _send_late_arrival_whatsapp_message(student, attendance_record.arrival_time, basics.last_time)
                except Basics.DoesNotExist:
                    pass
                messages.success(
                    request,
                    f"✅ حضور مجانيّ. تبقى لديك {student.free_tries} {'فرصة' if student.free_tries==1 else 'فرص'}."
                )

                text = (
                    f"👋 *مرحباً بولي أمر الطالب/ـة {student.name}،*\n\n"
                    f"👍 تم تسجيل حضور ابنكم/ابنتكم اليوم كفرصة مجانية.\n"
                    f"Remaining free tries: {student.free_tries} {'فرصة متبقية' if student.free_tries == 1 else 'فرص متبقية'} لهذا الشهر.\n\n" # Changed to English for "Remaining free tries" for better universal understanding if needed, but kept Arabic for "فرص"
                    f"💡 لتفادي أي انقطاع، ننصح بتسوية الاشتراك الشهري في أقرب وقت مناسب.\n\n"
                    f"مع خالص تحياتنا،\n*إدارة مركزنا التعليمي*"
                )
                # إرسال رسالة تأكيد استخدام الفرصة المجانية عبر WhatsApp في thread منفصل
                threading.Thread(
                    target=queue_whatsapp_message,
                    args=(student.father_phone, text),
                    daemon=True
                ).start()
            else: # إذا لم تكن هناك فرص مجانية متبقية
                messages.error(request, "❌ لا توجد فرص مجانية متبقية، الرجاء الدفع.")
            return redirect('barcode_attendance') # إعادة توجيه إلى صفحة الحضور

        # ==== القسم 3: الدفع وتسجيل الحضور (Pay and Attend) ====
        # هذا القسم يعالج حالة قيام الطالب بدفع الاشتراك وتسجيل الحضور فورًا.
        elif action == 'pay': # لا تنسى أن barcode قد تم تعريفه سابقاً إذا لم يكن action هو send_custom_message
            # إنشاء سجل دفع جديد أو جلب السجل الموجود إذا كان الطالب قد دفع بالفعل لهذا الشهر
            payment, created = Payment.objects.get_or_create(
                student=student,
                month=month_start
            )
            # إعادة تعيين الفرص المجانية للطالب فور الدفع
            student.free_tries = INITIAL_FREE_TRIES # استخدام القيمة المبدئية للفرص المجانية
            student.last_reset_month = today.replace(day=1) # تحديث تاريخ آخر شهر تم فيه إعادة تعيين الفرص
            student.save() # حفظ التغييرات في سجل الطالب

            # تسجيل حضور اليوم
            Attendance.objects.create(student=student, attendance_date=today) # إنشاء سجل حضور
            # احصل على سجل الحضور الذي تم إنشاؤه للتو لتسجيل وقت الوصول
            attendance_record = Attendance.objects.get(student=student, attendance_date=today, is_absent=False)
            # تسجيل وقت الوصول الفعلي للطالب
            attendance_record.arrival_time = timezone.localtime().time()
            attendance_record.save(update_fields=['arrival_time'])

            # التحقق من التأخير وإرسال رسالة إذا لزم الأمر (نفس منطق القسم الأول)
            try:
                basics = Basics.objects.first()
                if basics and basics.last_time and attendance_record.arrival_time > basics.last_time:
                    _send_late_arrival_whatsapp_message(student, attendance_record.arrival_time, basics.last_time)
            except Basics.DoesNotExist:
                pass
            pay_amount = Basics.objects.get(id=1).month_price # جلب سعر الشهر من الإعدادات الأساسية
            # رسالة تأكيد الدفع
            dp_msg = (
                f"✅ شكراً جزيلاً! تم استلام اشتراك شهر {payment.month:%B %Y} لابنكم/ابنتكم {student.name} بمبلغ {pay_amount} جنيه مصري."
                if created else
                f"ℹ️ دفعتكم لشهر {payment.month:%B %Y} لابنكم/ابنتكم {student.name} مسجلة لدينا مسبقاً."
            )
            at_msg = f"✅ تم تسجيل حضور {student.name} اليوم {today:%Y-%m-%d}."

            _send_whatsapp_combined(student, dp_msg, at_msg)
            messages.success(request, dp_msg)
            messages.success(request, at_msg)
            return redirect('barcode_attendance')

    # إذا كان هناك طالب معلق (pending_student)، مرره إلى السياق للاستخدام في نموذج الرسالة المخصصة
    # هذا الشرط للتأكد من أن pending_student موجود في context قبل محاولة الوصول إليه
    # pending_student يتم تعيينه أعلاه عندما يكون الطالب غير مدفوع أو عندما يكون الحضور مسجل مسبقًا
    if 'pending_student' in context: 
        student_for_custom_message = context['pending_student']
    
    if student_for_custom_message: 
         context['pending_student_for_message'] = student_for_custom_message

    return render(request, 'attendance.html', context) # عرض صفحة الحضور مع السياق المحدث


# دالة مساعدة لإرسال رسالة WhatsApp عند تسجيل الحضور العادي
def _send_whatsapp_attendance(student, today):
    # student: كائن الطالب الذي تم تسجيل حضوره
    # today: تاريخ اليوم
    date_str = today.strftime('%Y-%m-%d') # تنسيق التاريخ
    time_str = timezone.localtime().strftime('%H:%M') # تنسيق الوقت الحالي
    text = (
        f"👋 *مرحباً بولي أمر الطالب/ـة {student.name}،*\n\n"
        f"✅ تم تسجيل حضور ابنكم/ابنتكم اليوم بنجاح.\n"
        f"🗓️ التاريخ: {date_str}\n"
        f"⏰ الوقت: {time_str}\n\n"
        f"📚 نتمنى له/لها يوماً دراسياً موفقاً ومثمراً!\n\n"
        f"مع خالص تحياتنا،\n*إدارة مركزنا التعليمي*"
    )
    # إرسال الرسالة في thread منفصل لتجنب تعطيل عملية الحضور الرئيسية
    threading.Thread(
        target=queue_whatsapp_message, # الدالة الهدف للإرسال (تضيف الرسالة إلى طابور)
        args=(student.father_phone, text), # الوسائط المطلوبة للدالة (رقم الهاتف والنص)
        daemon=True # يجعل الـ thread يعمل في الخلفية
    ).start()

# دالة مساعدة لإرسال رسالة WhatsApp مجمعة (تأكيد الدفع + تأكيد الحضور)
def _send_whatsapp_combined(student, dp_msg, at_msg):
    # student: كائن الطالب
    # dp_msg: رسالة تأكيد الدفع (تم إنشاؤها في barcode_attendance_view)
    # at_msg: رسالة تأكيد الحضور (تم إنشاؤها في barcode_attendance_view)
    text = (
        f"👋 *مرحباً بولي أمر الطالب/ـة {student.name}،*\n\n"
        f"{dp_msg}\n"
        f"{at_msg}\n\n"
        f"🤝 نشكركم على حسن تعاونكم وثقتكم.\n\n"
        f"مع خالص تحياتنا،\n*إدارة مركزنا التعليمي*"
    )
    # إرسال الرسالة في thread منفصل
    threading.Thread(
        target=queue_whatsapp_message,
        args=(student.father_phone, text),
        daemon=True
    ).start()

# دالة مساعدة لإرسال رسالة WhatsApp عند وصول الطالب متأخراً
def _send_late_arrival_whatsapp_message(student, actual_arrival_time, allowed_latest_time):
    # student: كائن الطالب المتأخر
    # actual_arrival_time: وقت وصول الطالب الفعلي
    # allowed_latest_time: آخر وقت مسموح به للحضور
    time_format = "%I:%M %p" # تنسيق الوقت لعرضه بصيغة AM/PM (مثال: 03:30 PM)
    actual_time_str = actual_arrival_time.strftime(time_format) # وقت الوصول الفعلي بصيغة نصية
    allowed_time_str = allowed_latest_time.strftime(time_format) # آخر وقت مسموح به بصيغة نصية

    text = (
        f"👋 *مرحباً بولي أمر الطالب/ـة {student.name}،*\n\n"
        f"⏱️ نود إعلامكم بأن ابنكم/ابنتكم قد وصل/وصلت متأخراً/متأخرة اليوم.\n"
        f"⏰ وقت الوصول الفعلي: *{actual_time_str}*\n"
        f"🕒 آخر وقت مسموح به للحضور: *{allowed_time_str}*\n\n"
        f" حرصاً على انضباط المواعيد وتحقيق أقصى استفادة، نرجو التأكيد على أهمية الحضور في الوقت المحدد.\n\n"
        f"مع خالص تحياتنا،\n*إدارة مركزنا التعليمي*"
    )
    # إرسال الرسالة في thread منفصل
    threading.Thread(
        target=queue_whatsapp_message,
        args=(student.father_phone, text),
        daemon=True
    ).start()

# دالة لتوليد رسالة الغياب المناسبة بناءً على حالة غياب الطالب
def get_absence_message(student, today, consecutive_days, total_absences):
    """
    يُعيد رسالة مُخصصة بناءً على:
    - student: كائن الطالب الغائب.
    - today: تاريخ اليوم الحالي.
    - consecutive_days: عدد الأيام المتتابعة للغياب حتى اليوم (بما في ذلك اليوم الحالي).
    - total_absences: إجمالي عدد أيام غياب الطالب في الشهر الحالي (بما في ذلك اليوم الحالي).
    """
    date_str = today.strftime("%Y-%m-%d") # تنسيق تاريخ اليوم
    base_header = f"📢 *إشعار بخصوص غياب الطالب/ـة {student.name}*\n\n" # بداية موحدة لجميع رسائل الغياب
    signature = "\n\nمع خالص تحياتنا،\n*إدارة مركزنا التعليمي*" # توقيع موحد

    # الحالة 1: أول غياب للطالب في الشهر
    # إذا كان إجمالي الغيابات هذا الشهر هو 1، وأيام الغياب المتتالية هي 1 (أي هذا هو أول يوم غياب).
    if total_absences == 1 and consecutive_days == 1:
        return (
            base_header +
            f"❌ تم تسجيل أول غياب لابنك/ابنتك اليوم ({date_str}).\n"
            "📌 نرجو اطلاعنا على سبب الغياب وتزويدنا بإفادة إذا لزم الأمر." +
            signature
        )

    # الحالة 2: غياب متتابع لمدة يومين
    # إذا كان الطالب غائباً لليوم الثاني على التوالي.
    if consecutive_days == 2:
        return (
            base_header +
            f"⚠️ تم تسجيل غياب ابنك/ابنتك لليوم الثاني على التوالي ({date_str}).\n"
            "📌 نرجو تزويدنا بمبرر الغياب لمساعدتنا في متابعة حالته الدراسية." +
            signature
        )

    # الحالة 3: غياب متتابع لمدة 3 أيام أو أكثر
    # إذا كان الطالب غائباً لثلاثة أيام متتالية أو أكثر.
    if consecutive_days >= 3:
        return (
            base_header +
            f"🚨 غياب متتابع: ابنك/ابنتك غائب منذ {consecutive_days} أيام حتى ({date_str}).\n"
            "📌 نطلب منكم التكرم بالتواصل معنا في أقرب فرصة لمناقشة الأمر وتقديم الدعم اللازم لابنكم/ابنتكم.\n" +
            "إن كانت هناك أي تحديات تواجهه/تواجهها، فنحن هنا للمساعدة والعمل سوياً لإيجاد الحلول المناسبة." +
            signature
        )

    # الحالة 4: غياب متقطع (ليس متتابعاً مع اليوم السابق ولكن هناك غيابات أخرى في الشهر)
    # إذا كان الغياب الحالي هو ليوم واحد فقط (consecutive_days == 1) ولكن إجمالي الغيابات في الشهر أكبر من 1.
    if consecutive_days == 1 and total_absences > 1:
        return (
            base_header +
            f"❌ تم تسجيل غياب ابنك/ابنتك اليوم ({date_str}) مرة أخرى بعد غيابه سابقاً.\n"
            "📌 نرجو متابعة انتظام الحضور ودعم الطالب للعودة إلى المدرسة بانتظام." +
            signature
        )

    # الحالة 5: حالات عامة أخرى (احتياطية، يجب ألا يتم الوصول إليها إذا كانت الشروط أعلاه تغطي كل الحالات)
    # رسالة غياب عامة إذا لم تتطابق أي من الحالات المخصصة أعلاه.
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
