# students/admin.py
from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse, NoReverseMatch
from import_export.admin import ImportExportModelAdmin
from .models import Students, Attendance, Payment,Basics
from .resources import StudentsResource
from django.utils import timezone # استورد timezone
from django.contrib import messages # استورد messages
from import_export.formats import base_formats

@admin.register(Students)
class StudentsAdmin(ImportExportModelAdmin):
    resource_class = StudentsResource
    search_fields = ('name', 'barcode','father_phone')
    list_display = (
        'name',
        'father_phone',
        'branch',
        'barcode',
        'print_barcode_link',
        'print_card',
    )
    formats = (base_formats.XLSX,)
    list_filter = ('branch',)  # Added branch to list_filter

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
@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('student', 'month', 'paid_on', 'payment_type', 'term_duration_months')
    list_filter = ('payment_type', 'month')
    search_fields = ('student__name', 'student__barcode')
    fieldsets = (
        (None, {
            'fields': ('student', 'month', 'payment_type', 'term_duration_months')
        }),
        ('معلومات الدفع (للقراءة فقط)', {
            'fields': ('paid_on',),
            'classes': ('collapse',),
        }),
    )
    readonly_fields = ('paid_on',)

@admin.register(Basics)
class BasicsAdmin(admin.ModelAdmin):
    list_display = ('month_price', 'term_price', 'default_term_duration_months', 'late_arrival_time', 'free_tries')
    fieldsets = (
        ('التسعير والمدد', {
            'fields': ('month_price', 'term_price', 'default_term_duration_months')
        }),
        ('إعدادات إضافية', {
            'fields': ('late_arrival_time', 'free_tries', 'logo')
        }),
    )
