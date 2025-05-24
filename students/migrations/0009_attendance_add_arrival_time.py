from django.db import migrations, models

class Migration(migrations.Migration):

    dependencies = [
        ('students', '0008_new_message_models'), # تأكد من اسم الترحيل السابق
    ]

    operations = [
        migrations.AddField(
            model_name='attendance',
            name='arrival_time',
            field=models.TimeField(blank=True, help_text='يسجل وقت مسح الباركود للحضور', null=True, verbose_name='وقت الوصول الفعلي'),
        ),
    ]
