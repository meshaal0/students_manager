# Generated by Django 5.2.1 on 2025-05-27 17:51

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('students', '0011_rename_ate_arrival_time_basics_late_arrival_time'),
    ]

    operations = [
        migrations.AddField(
            model_name='students',
            name='has_whatsapp',
            field=models.BooleanField(default=True, verbose_name='لديه واتس اب'),
        ),
    ]
