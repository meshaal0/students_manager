from django.db import models
import random
from django.utils import timezone
from datetime import date

# Create your models here.

class Basics(models.Model):
    ate_arrival_time = models.TimeField(verbose_name='وقت اعتبار التأخير', null=True, blank=True)
    month_price = models.IntegerField(verbose_name='سعر الشهر')
    free_tries = models.PositiveSmallIntegerField(
        verbose_name='عدد الفرص المجانية',
        default=3,
        help_text='عدد الفرص المجانية المتاحة للطلاب'
    )
    logo = models.ImageField(
        verbose_name='شعار',
        upload_to='logo/',)
    def __str__(self):
        return f"{self.ate_arrival_time} – {self.month_price}"
    class Meta:
        verbose_name = "أساسيات"
        verbose_name_plural = 'الأساسيات'
        

class Students(models.Model):
    name = models.CharField(verbose_name='الاسم', max_length=100)
    father_phone = models.CharField(verbose_name='هاتف ولي الأمر', max_length=15)
    barcode = models.CharField(verbose_name='الباركود', max_length=5, unique=True, blank=True)
    free_tries = models.PositiveSmallIntegerField(
        'عدد الفرص المجانية المتبقية',default=3
    )
    last_reset_month = models.DateField(
        'آخر شهر إعادة تعيين',
        null=True, blank=True,
        help_text='يُحدَّث فقط عند الدفع'
    )

    def save(self, *args, **kwargs):
        if not self.barcode:
            # توليد رقم باركود عشوائي مكون من 5 أرقام
            while True:
                code = str(random.randint(10000, 99999))
                if not Students.objects.filter(barcode=code).exists():
                    self.barcode = code
                    break
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name
    class Meta:
        verbose_name = "طالب"
        verbose_name_plural = 'الطلاب'

class Attendance(models.Model):
    student = models.ForeignKey(Students, on_delete=models.CASCADE)
    timestamp = models.DateTimeField(auto_now_add=True)
    attendance_date = models.DateField(
        default=timezone.localdate,
        editable=False,        # اختياري: يمنع تعديل التاريخ يدويًا من الـ admin
    )
    is_absent = models.BooleanField('غياب', default=False)
    arrival_time = models.TimeField(verbose_name='وقت الوصول الفعلي', null=True, blank=True, help_text='يسجل وقت مسح الباركود للحضور') # وقت وصول الطالب الفعلي عند مسح الباركود
    def __str__(self):
        return f"{self.student.name} – {self.attendance_date}"
    class Meta:
        verbose_name = "حضور"
        verbose_name_plural = 'الحاضرون' # Changed for better clarity
        constraints = [
            models.UniqueConstraint(
                fields=['student', 'attendance_date'],
                name='unique_student_attendance_per_day'
            )
        ]


def first_day_of_current_month():
    """
    يُعيد التاريخ ‘YYYY-MM-01’ للشهر الحالي حسب الإعداد الزمني في Django.
    """
    today = timezone.localdate()
    return date(today.year, today.month, 1)

class Payment(models.Model):
    student = models.ForeignKey(
        'Students',on_delete=models.CASCADE,related_name='payments',verbose_name='الطالب'
    )
    # يصبح default تلقائيًا أوّلي الشهر الجاري
    month = models.DateField(
        default=first_day_of_current_month,verbose_name='شهر الدفع'
    )
    paid_on = models.DateTimeField(
        auto_now_add=True,verbose_name='تاريخ ووقت الدفع'
    )

    class Meta:
        # قيد فريد: طالب + أوّلي نفس الشهر
        constraints = [
            models.UniqueConstraint(
                fields=['student', 'month'],
                name='unique_payment_per_month'
            )
        ]
        ordering = ['-month']
        verbose_name = 'دفعة'
        verbose_name_plural = 'الدفعات'

    def __str__(self):
        # مثال: "أحمد – 2025-05"
        return f"{self.student.name} – {self.month:%Y-%m}"
class NotificationCategory(models.Model):
    name = models.CharField(max_length=255, unique=True, verbose_name="اسم فئة الإشعار") # اسم الفئة، يجب أن يكون فريداً
    def __str__(self):
        return self.name # التمثيل النصي للنموذج هو اسم الفئة

    class Meta:
        verbose_name = "فئة إشعار" # اسم مفرد للنموذج في واجهة المشرف
        verbose_name_plural = "فئات الإشعارات" # اسم الجمع للنموذج في واجهة المشرف

# نموذج BroadcastMessage لإدارة الرسائل العامة (الإشعارات)
# يستخدم لإرسال رسائل مجمعة للطلاب أو فئات معينة منهم
class BroadcastMessage(models.Model):
    category = models.ForeignKey( # حقل لربط الرسالة بفئة إشعار (اختياري)
        NotificationCategory,
        on_delete=models.SET_NULL, # إذا حُذفت الفئة، يبقى هذا الحقل فارغاً (null) بدلاً من حذف الرسالة
        null=True, # يسمح بأن يكون الحقل فارغاً في قاعدة البيانات
        blank=True, # يسمح بأن يكون الحقل فارغاً في النماذج (forms)
        verbose_name="الفئة" # الاسم المعروض في واجهة المشرف
    )
    title = models.CharField(max_length=255, verbose_name="العنوان") # عنوان الرسالة
    content = models.TextField(verbose_name="المحتوى") # محتوى الرسالة النصي
    send_to_all = models.BooleanField(default=True, verbose_name="إرسال للجميع") # علامة لتحديد ما إذا كانت الرسالة سترسل لجميع الطلاب
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="وقت الإنشاء") # تاريخ ووقت إنشاء الرسالة (يُضبط تلقائياً عند الإنشاء)
    sent_at = models.DateTimeField(null=True, blank=True, verbose_name="وقت الإرسال") # تاريخ ووقت إرسال الرسالة (يُضبط عند الإرسال الفعلي)

    def __str__(self):
        return self.title # التمثيل النصي للنموذج هو عنوان الرسالة

    class Meta:
        verbose_name = "رسالة عامة" # اسم مفرد للنموذج في واجهة المشرف
        verbose_name_plural = "الرسائل العامة" # اسم الجمع للنموذج في واجهة المشرف
        ordering = ['-created_at'] # ترتيب الرسائل في واجهة المشرف بحيث تظهر الأحدث أولاً
    # class Meta:
    #     constraints = [
    #         models.UniqueConstraint(
    #             fields=['student','attendance_date'],
    #             name='unique_student_per_day'
                    # abdallahoamrdnddnd djdnf fjnfrjnr
    #         )
    #     ]

    # def __str__(self):
    #     return f"{self.student.name} – {self.attendance_date}"