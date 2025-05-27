# students/utils/failed_numbers_manager.py

import os
import json
import csv
from datetime import datetime
from django.conf import settings
from django.http import JsonResponse, HttpResponse
from ..models import Students

FAILED_NUMBERS_FILE = os.path.abspath("./failed_whatsapp_numbers.json")

def get_failed_numbers_summary():
    """
    يعيد ملخص شامل للأرقام الفاشلة مع معلومات الطلاب
    """
    try:
        if not os.path.exists(FAILED_NUMBERS_FILE):
            return {
                'total_failed': 0,
                'failed_records': [],
                'summary_by_error': {},
                'students_with_issues': []
            }
        
        with open(FAILED_NUMBERS_FILE, 'r', encoding='utf-8') as f:
            failed_data = json.load(f)
        
        # إحصائيات الأخطاء
        error_summary = {}
        students_with_issues = []
        
        for record in failed_data:
            error_type = record.get('error_type', 'unknown')
            if error_type in error_summary:
                error_summary[error_type] += 1
            else:
                error_summary[error_type] = 1
            
            # محاولة جلب معلومات الطالب من قاعدة البيانات
            if record.get('student_name'):
                try:
                    student = Students.objects.get(name=record['student_name'])
                    student_info = {
                        'id': student.id,
                        'name': student.name,
                        'phone': record['phone'],
                        'barcode': student.barcode,
                        'error_type': error_type,
                        'attempts': record.get('attempts', 1),
                        'last_attempt': record.get('last_attempt', record.get('timestamp')),
                        'error_message': record.get('error_message', '')
                    }
                    students_with_issues.append(student_info)
                except Students.DoesNotExist:
                    # الطالب لم يعد موجوداً في قاعدة البيانات
                    student_info = {
                        'id': None,
                        'name': record['student_name'],
                        'phone': record['phone'],
                        'barcode': 'غير متوفر',
                        'error_type': error_type,
                        'attempts': record.get('attempts', 1),
                        'last_attempt': record.get('last_attempt', record.get('timestamp')),
                        'error_message': record.get('error_message', ''),
                        'note': 'الطالب لم يعد موجوداً في النظام'
                    }
                    students_with_issues.append(student_info)
        
        return {
            'total_failed': len(failed_data),
            'failed_records': failed_data,
            'summary_by_error': error_summary,
            'students_with_issues': students_with_issues
        }
        
    except Exception as e:
        return {
            'error': f"خطأ في قراءة البيانات: {str(e)}",
            'total_failed': 0,
            'failed_records': [],
            'summary_by_error': {},
            'students_with_issues': []
        }

def export_failed_numbers_to_csv():
    """
    يصدر الأرقام الفاشلة إلى ملف CSV
    """
    summary = get_failed_numbers_summary()
    
    if summary['total_failed'] == 0:
        return None
    
    # إنشاء ملف CSV
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"failed_whatsapp_numbers_{timestamp}.csv"
    filepath = os.path.join(settings.MEDIA_ROOT, filename)
    
    # التأكد من وجود المجلد
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    
    try:
        with open(filepath, 'w', newline='', encoding='utf-8-sig') as csvfile:
            fieldnames = [
                'اسم الطالب', 'رقم الهاتف', 'الباركود', 'نوع الخطأ', 
                'رسالة الخطأ', 'عدد المحاولات', 'آخر محاولة', 'ملاحظات'
            ]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            
            writer.writeheader()
            for student in summary['students_with_issues']:
                writer.writerow({
                    'اسم الطالب': student['name'],
                    'رقم الهاتف': student['phone'],
                    'الباركود': student.get('barcode', 'غير متوفر'),
                    'نوع الخطأ': student['error_type'],
                    'رسالة الخطأ': student.get('error_message', ''),
                    'عدد المحاولات': student.get('attempts', 1),
                    'آخر محاولة': student.get('last_attempt', ''),
                    'ملاحظات': student.get('note', '')
                })
        
        return filepath
        
    except Exception as e:
        print(f"خطأ في إنشاء ملف CSV: {e}")
        return None

def fix_student_phone_number(student_id, new_phone):
    """
    يحدث رقم هاتف طالب ويزيل سجله من الأرقام الفاشلة
    """
    try:
        student = Students.objects.get(id=student_id)
        old_phone = student.father_phone
        student.father_phone = new_phone
        student.save()
        
        # إزالة السجل من الأرقام الفاشلة
        remove_failed_number_record(old_phone, student.name)
        
        return True, f"تم تحديث رقم هاتف {student.name} من {old_phone} إلى {new_phone}"
        
    except Students.DoesNotExist:
        return False, "الطالب غير موجود"
    except Exception as e:
        return False, f"خطأ في التحديث: {str(e)}"

def remove_failed_number_record(phone, student_name=None):
    """
    يزيل سجل رقم فاشل من الملف
    """
    try:
        if not os.path.exists(FAILED_NUMBERS_FILE):
            return True
        
        with open(FAILED_NUMBERS_FILE, 'r', encoding='utf-8') as f:
            failed_data = json.load(f)
        
        # فلترة البيانات لإزالة السجل المطلوب
        if student_name:
            failed_data = [
                record for record in failed_data 
                if not (record.get('phone') == phone and record.get('student_name') == student_name)
            ]
        else:
            failed_data = [
                record for record in failed_data 
                if record.get('phone') != phone
            ]
        
        # حفظ البيانات المحدثة
        with open(FAILED_NUMBERS_FILE, 'w', encoding='utf-8') as f:
            json.dump(failed_data, f, ensure_ascii=False, indent=2)
        
        return True
        
    except Exception as e:
        print(f"خطأ في إزالة السجل: {e}")
        return False

def clear_all_failed_records():
    """
    يمسح جميع سجلات الأرقام الفاشلة
    """
    try:
        if os.path.exists(FAILED_NUMBERS_FILE):
            os.remove(FAILED_NUMBERS_FILE)
        return True
    except Exception as e:
        print(f"خطأ في مسح السجلات: {e}")
        return False

def get_error_type_description(error_type):
    """
    يعيد وصف مفهوم لنوع الخطأ
    """
    descriptions = {
        'invalid_format': 'صيغة الرقم غير صالحة',
        'whatsapp_error': 'خطأ من واتساب (الرقم غير موجود أو غير نشط)',
        'send_failed': 'فشل في الإرسال',
        'no_send_button': 'الرقم غير موجود على واتساب',
        'selenium_error': 'خطأ تقني في المتصفح',
        'retry_failed': 'فشل في إعادة المحاولة',
        'final_check_failed': 'فشل في التحقق النهائي',
        'unknown': 'خطأ غير محدد'
    }
    return descriptions.get(error_type, error_type)