# students/admin.py
from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse, NoReverseMatch
from import_export.admin import ImportExportModelAdmin
from .models import Students, Attendance, Payment,Basics,NotificationCategory,BroadcastMessage
from .resources import StudentsResource
from django.utils import timezone # استورد timezone
from .utils.whatsapp_queue import queue_whatsapp_message # استورد queue_whatsapp_message
from django.contrib import messages # استورد messages
from import_export.formats import base_formats

@admin.register(Students)
class StudentsAdmin(ImportExportModelAdmin):
    resource_class = StudentsResource
    search_fields = ('name', 'barcode','father_phone')
    list_display = (
        'name',
        'father_phone',
        'barcode',
        'print_barcode_link',
        'print_card',
    )
    formats = (base_formats.XLSX,)

    def print_barcode_link(self, obj):
        try:
            url = reverse('print_barcode', args=[obj.id])
            return format_html('<a href="{}" target="_blank">باركود</a>', url)
        except NoReverseMatch:
            return "-"
    print_barcode_link.short_description = 'طباعة باركود'

    def print_card(self, obj):
        try:
            url = reverse('print_student_card', args=[obj.id])
            return format_html('<a href="{}" target="_blank">PDF كارت</a>', url)
        except NoReverseMatch:
            return "-"
    print_card.short_description = 'طباعة كرنيه'


# تسجيل بقية الموديلات كما كانت
admin.site.register(Attendance)
admin.site.register(Payment)
admin.site.register(Basics)
@admin.register(NotificationCategory)
class NotificationCategoryAdmin(admin.ModelAdmin):
    search_fields = ['name'] # يتيح البحث عن فئات الإشعارات باستخدام حقل الاسم

# واجهة المشرف لنموذج الرسائل العامة (الإشعارات)
@admin.register(BroadcastMessage)
class BroadcastMessageAdmin(admin.ModelAdmin):
    # الحقول التي ستظهر في قائمة الرسائل في واجهة المشرف
    list_display = ('title', 'category', 'send_to_all', 'created_at', 'sent_at', 'was_sent')
    # الفلاتر التي ستظهر في الشريط الجانبي لتصفية الرسائل
    list_filter = ('category', 'send_to_all', 'sent_at')
    # الحقول التي يمكن البحث من خلالها عن الرسائل
    search_fields = ('title', 'content')
    # الحقول التي ستكون للقراءة فقط (لا يمكن تعديلها مباشرة من واجهة المشرف)
    readonly_fields = ('sent_at',)

    # دالة مخصصة لعرض أيقونة تشير إلى ما إذا كانت الرسالة قد أُرسلت أم لا
    def was_sent(self, obj):
        # obj هو كائن BroadcastMessage الحالي
        if obj.sent_at: # إذا كان حقل sent_at يحتوي على تاريخ (أي تم الإرسال)
            return format_html('<img src="/static/admin/img/icon-yes.svg" alt="True">') # عرض أيقونة "نعم"
        return format_html('<img src="/static/admin/img/icon-no.svg" alt="False">') # عرض أيقونة "لا"
    was_sent.short_description = 'تم الإرسال' # النص الذي سيظهر كعنوان للعمود في واجهة المشرف

    # إجراء مخصص لإرسال الرسائل المحددة
    def send_selected_messages(self, request, queryset):
        # request: كائن HttpRequest الحالي
        # queryset: مجموعة الرسائل التي تم تحديدها من قبل المشرف
        for message in queryset: # المرور على كل رسالة محددة
            if message.send_to_all and not message.sent_at: # التحقق مما إذا كانت الرسالة مخصصة للإرسال للجميع ولم تُرسل بعد
                students_to_notify = Students.objects.all() # جلب جميع الطلاب
                for student in students_to_notify: # المرور على كل طالب
                    # التأكد من أن رقم هاتف ولي الأمر موجود قبل محاولة الإرسال
                    if student.father_phone:
                        queue_whatsapp_message(student.father_phone, message.content) # إضافة الرسالة إلى طابور الإرسال
                message.sent_at = timezone.now() # تحديث وقت إرسال الرسالة إلى الوقت الحالي
                message.save(update_fields=['sent_at']) # حفظ التغيير في حقل sent_at فقط
                # إعلام المشرف بنجاح عملية الإرسال لهذه الرسالة
                self.message_user(request, f"الرسالة '{message.title}' تم إرسالها إلى جميع الطلاب.")
            elif message.sent_at: # إذا كانت الرسالة قد أُرسلت مسبقًا
                # إعلام المشرف بأن الرسالة قد أُرسلت بالفعل
                self.message_user(request, f"الرسالة '{message.title}' قد تم إرسالها مسبقًا.", messages.WARNING)
            elif not message.send_to_all: # إذا لم تكن الرسالة مخصصة للإرسال للجميع
                # إعلام المشرف بأنه تم تجاهل الرسالة لأنها ليست للإرسال العام
                self.message_user(request, f"الرسالة '{message.title}' لم يتم تحديد 'إرسال للجميع' لها، لذا تم تجاهلها.", messages.INFO)

    send_selected_messages.short_description = "إرسال الرسائل المحددة إلى جميع الطلاب" # النص الذي سيظهر للإجراء في قائمة الإجراءات
    actions = [send_selected_messages] # إضافة الإجراء إلى قائمة الإجراءات المتاحة
    