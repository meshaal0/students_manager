# students/admin.py
from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse, NoReverseMatch

# استيراد الكلاس الجديد
from import_export.admin import ImportExportModelAdmin
from .models import Students, Attendance, Payment,Basics
from .resources import StudentsResource

@admin.register(Students)
class StudentsAdmin(ImportExportModelAdmin):
    resource_class = StudentsResource

    list_display = (
        'name',
        'father_phone',
        'barcode',
        'print_barcode_link',
        'print_card',
    )

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

# # admin.py
# from django.contrib import admin
# from django.utils.html import format_html
# from django.urls import reverse, NoReverseMatch
# from .models import Students, Attendance, Payment

# class StudentsAdmin(admin.ModelAdmin):
#     list_display = (
#         'name',
#         'father_phone',
#         'barcode',
#         'print_barcode_link',
#         'print_card',
#     )

#     def print_barcode_link(self, obj):
#         try:
#             url = reverse('print_barcode', args=[obj.id])
#             return format_html('<a href="{}" target="_blank">باركود</a>', url)
#         except NoReverseMatch:
#             return "غير متاح"
#     print_barcode_link.short_description = 'طباعة باركود'

#     # students/admin.py
#     def print_card(self, obj):
#         url = reverse('print_student_card', args=[obj.id])
#         return format_html('<a href="{}" target="_blank">PDF كارت</a>', url)
    
#     print_card.short_description = 'طباعة كرنيه'

# admin.site.register(Students, StudentsAdmin)
# admin.site.register(Attendance)
# admin.site.register(Payment)
