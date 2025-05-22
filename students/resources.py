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
    )

    class Meta:
        model = Students
        # الحقول التي تريد تصديرها/استيرادها
        fields = (
            'id',
            'name',
            'father_phone',
            'barcode',
            'free_tries',
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
