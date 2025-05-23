# students/admin.py
from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse, NoReverseMatch

from import_export.admin import ImportExportModelAdmin
from .models import Students, Attendance, Payment, Basics
from .resources import StudentsResource, AttendanceResource, PaymentResource # Ensure all are imported

@admin.register(Students)
class StudentsAdmin(ImportExportModelAdmin):
    resource_class = StudentsResource
    list_display = (
        'name',
        'father_phone',
        'barcode',
        'free_tries',
        'last_reset_month',
        'print_barcode_link', 
    )
    search_fields = ('name', 'barcode', 'father_phone')
    list_filter = ('last_reset_month', 'free_tries') # Only existing fields
    readonly_fields = ('last_reset_month', 'barcode') # Barcode is auto-generated

    def print_barcode_link(self, obj):
        try:
            url = reverse('print_barcode', args=[obj.id])
            return format_html('<a href="{}" target="_blank">باركود</a>', url)
        except NoReverseMatch:
            return "-"
    print_barcode_link.short_description = 'طباعة باركود'

@admin.register(Attendance)
class AttendanceAdmin(ImportExportModelAdmin):
    resource_class = AttendanceResource
    list_display = ('student', 'attendance_date', 'timestamp', 'is_absent') # Corrected: no is_present
    list_filter = ('attendance_date', 'is_absent', 'student__name') # Corrected: student__name for filtering by student
    search_fields = ('student__name', 'student__barcode') 
    date_hierarchy = 'attendance_date'

@admin.register(Payment)
class PaymentAdmin(ImportExportModelAdmin):
    resource_class = PaymentResource
    list_display = ('student', 'month', 'paid_on') # Corrected: no amount
    list_filter = ('month', 'student__name') # Corrected: student__name for filtering by student
    search_fields = ('student__name', 'student__barcode')
    date_hierarchy = 'paid_on'

if not admin.site.is_registered(Basics):
    @admin.register(Basics)
    class BasicsAdmin(admin.ModelAdmin): 
        list_display = ('id','last_time', 'month_price', 'free_tries', 'logo')
