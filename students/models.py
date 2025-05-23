from django.db import models
import random
from django.utils import timezone
from datetime import date

# Create your models here.

class Basics(models.Model):
    last_time = models.TimeField(verbose_name='آخر وقت')
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
        return f"{self.last_time} – {self.month_price}"
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
    def __str__(self):
        return f"{self.student.name} – {self.attendance_date}"
    class Meta:
        verbose_name = "حضور"
        verbose_name_plural = 'الحضور'
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