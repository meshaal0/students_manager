<<<<<<< HEAD
from import_export import resources, fields
from import_export.widgets import DateWidget
from .models import Students, Attendance, Payment

class StudentsResource(resources.ModelResource):
    # Existing customization from the file
    last_reset_month = fields.Field(
        column_name='آخر إعادة تعيين',
        attribute='last_reset_month',
        widget=DateWidget(format='%Y-%m-%d'),
        readonly=True # Usually good for display/export, but can be an issue for import if not handled
=======
# students/resources.py

from import_export import resources, fields
from import_export.widgets import DateWidget
from .models import Students

class StudentsResource(resources.ModelResource):
    # مثال على تخصيص حقل التاريخ لو اردت تضمين "last_reset_month"
    last_reset_month = fields.Field(
        column_name='آخر إعادة تعيين',
        attribute='last_reset_month',
        widget=DateWidget(format='%Y-%m-%d')
>>>>>>> feat/student-data-insights
    )

    class Meta:
        model = Students
<<<<<<< HEAD
=======
        # الحقول التي تريد تصديرها/استيرادها
>>>>>>> feat/student-data-insights
        fields = (
            'id',
            'name',
            'father_phone',
            'barcode',
            'free_tries',
<<<<<<< HEAD
            'last_reset_month', # This is the custom field instance
            # Add other model fields you want to manage via import/export
            'date_joined', 'group', 'timing', 'days', 'course', 
            'start_date', 'end_date', 'total_fee', 'registration_fee', 
            'monthly_fee', 'qualification', 'description', 'is_active',
            'father_name', 'date_of_birth', 'cnic_number', 'address', 'admission_date'
        )
        export_order = (
            'id',
            'name',
            'father_name',
            'date_of_birth',
            'cnic_number',
            'address',
            'father_phone',
            'barcode',
            'group', 
            'timing', 
            'days', 
            'course', 
            'start_date', 
            'end_date', 
            'total_fee', 
            'registration_fee', 
            'monthly_fee',
            'admission_date',
            'qualification', 
            'description', 
            'free_tries',
            'last_reset_month',
            'date_joined',
            'is_active'
        )
        skip_unchanged = True
        report_skipped = True
        import_id_fields = ('id',)
        # To handle the custom 'last_reset_month' field during import if it's not directly writable
        # or if you want to control its import behavior, you might need custom logic in before_import_row, etc.
        # For now, assuming it's mainly for export or that the DateWidget handles imports appropriately if the field is writable.

class AttendanceResource(resources.ModelResource):
    class Meta:
        model = Attendance
        fields = ('id', 'student', 'attendance_date', 'timestamp', 'is_present', 'is_absent') # Explicitly list fields
        # Foreign key 'student' will be represented by its ID by default.
        # If you want to use student's barcode or name for import/export,
        # you'd use a widget like:
        # student_barcode = fields.Field(
        #     column_name='student_barcode',
        #     attribute='student',
        #     widget=ForeignKeyWidget(Students, 'barcode')
        # )

class PaymentResource(resources.ModelResource):
    class Meta:
        model = Payment
        fields = ('id', 'student', 'month', 'paid_on', 'amount') # Explicitly list fields, assuming 'amount' exists
        # Similar to AttendanceResource, 'student' FK is handled by ID.
=======
            'last_reset_month',
        )
        # يحدد ترتيب الأعمدة عند التصدير
        export_order = (
            'id',
            'name',
            'father_phone',
            'barcode',
            'free_tries',
            'last_reset_month',
        )
        # لتخطي السجلات غير المعدّلة وإظهارها في التقرير
        skip_unchanged = True
        report_skipped = True
        # يستخدم الحقل 'id' كمفتاح للتعريف عند الاستيراد
        import_id_fields = ('id',)
>>>>>>> feat/student-data-insights
