# Generated by Django 5.2.1 on 2025-05-27 12:14

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('students', '0010_remove_basics_last_time_basics_ate_arrival_time'),
    ]

    operations = [
        migrations.RenameField(
            model_name='basics',
            old_name='ate_arrival_time',
            new_name='late_arrival_time',
        ),
    ]
