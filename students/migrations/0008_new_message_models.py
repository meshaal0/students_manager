from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):

    dependencies = [
        ('students', '0007_basics_free_tries'),
    ]

    operations = [
        migrations.CreateModel(
            name='NotificationCategory',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255, unique=True, verbose_name='اسم فئة الإشعار')),
            ],
            options={
                'verbose_name': 'فئة إشعار',
                'verbose_name_plural': 'فئات الإشعارات',
            },
        ),
        migrations.CreateModel(
            name='BroadcastMessage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=255, verbose_name='العنوان')),
                ('content', models.TextField(verbose_name='المحتوى')),
                ('send_to_all', models.BooleanField(default=True, verbose_name='إرسال للجميع')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='وقت الإنشاء')),
                ('sent_at', models.DateTimeField(blank=True, null=True, verbose_name='وقت الإرسال')),
                ('category', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='students.notificationcategory', verbose_name='الفئة')),
            ],
            options={
                'verbose_name': 'رسالة عامة',
                'verbose_name_plural': 'الرسائل العامة',
                'ordering': ['-created_at'],
            },
        ),
    ]
