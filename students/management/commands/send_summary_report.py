import datetime
from django.utils import timezone
from django.core.management.base import BaseCommand, CommandError
from students.models import Students, Attendance, Payment, Basics
from students.utils.risk_assessment_utils import get_student_risk_assessment # Assuming path is correct
from django.db.models import Count

class Command(BaseCommand):
    help = 'Generates a summary report of student activity and performance for the current month.'

    def handle(self, *args, **options):
        today = timezone.localdate()
        current_month = today.month
        current_year = today.year
        
        # For month name
        month_name = today.strftime("%B")

        self.stdout.write(self.style.SUCCESS(f"--- Monthly Summary Report - {month_name}, {current_year} ---"))

        # --- Fetch Data ---
        all_students = Students.objects.filter(is_active=True) # Consider active students
        total_students_count = all_students.count()
        
        if total_students_count == 0:
            self.stdout.write(self.style.WARNING("No active students found. Report generation aborted."))
            return

        # Attendance data for current month
        attendances_current_month = Attendance.objects.filter(
            attendance_date__year=current_year,
            attendance_date__month=current_month
        )

        # Payment data for current month
        # Assuming Payment model has a 'month' field (DateField, e.g., YYYY-MM-01)
        current_month_start_date = today.replace(day=1)
        payments_current_month = Payment.objects.filter(
            month__year=current_year,
            month__month=current_month
        )

        # --- Calculate Key Metrics ---

        # 1. Overall Attendance Rate
        present_count_overall = attendances_current_month.filter(is_present=True).count()
        # Calculate distinct school days in the month
        distinct_school_days_count = attendances_current_month.values('attendance_date').distinct().count()

        overall_attendance_rate = 0
        if total_students_count > 0 and distinct_school_days_count > 0:
            total_possible_student_days = total_students_count * distinct_school_days_count
            if total_possible_student_days > 0:
                overall_attendance_rate = (present_count_overall / total_possible_student_days) * 100
        
        self.stdout.write(f"\n--- Attendance ---")
        self.stdout.write(f"Overall Attendance Rate: {overall_attendance_rate:.2f}%")
        self.stdout.write(f"(Based on {present_count_overall} present records over {distinct_school_days_count} school days for {total_students_count} students)")


        # 2. Payment Status
        paid_students_ids_current_month = payments_current_month.values_list('student_id', flat=True).distinct()
        paid_count_current_month = len(paid_students_ids_current_month)
        unpaid_count_current_month = total_students_count - paid_count_current_month

        self.stdout.write(f"\n--- Payments (Current Month: {month_name}) ---")
        self.stdout.write(f"Students Paid: {paid_count_current_month}")
        self.stdout.write(f"Students Unpaid: {unpaid_count_current_month}")

        # 3. Students on Free Trials
        # Assumes student.free_tries > 0 and student is not in paid_students_ids_current_month
        students_on_free_trial_count = 0
        for student in all_students:
            if student.free_tries > 0 and student.id not in paid_students_ids_current_month:
                students_on_free_trial_count += 1
        
        basics_info = Basics.objects.first()
        default_free_tries = basics_info.free_tries if basics_info else "N/A (Basics not set)"

        self.stdout.write(f"\n--- Free Trials ---")
        self.stdout.write(f"Students Currently on Free Trial: {students_on_free_trial_count}")
        self.stdout.write(f"(Default free tries per new student: {default_free_tries})")


        # 4. Students at Risk
        medium_risk_count = 0
        high_risk_count = 0
        high_risk_student_names = []

        for student in all_students:
            risk_level, risk_reasons = get_student_risk_assessment(student)
            if risk_level == 'High':
                high_risk_count += 1
                high_risk_student_names.append(f"{student.name} (Reasons: {', '.join(risk_reasons)})")
            elif risk_level == 'Medium':
                medium_risk_count += 1
        
        self.stdout.write(f"\n--- Student Risk Assessment ---")
        self.stdout.write(f"Students at Medium Risk: {medium_risk_count}")
        self.stdout.write(f"Students at High Risk: {high_risk_count}")

        if high_risk_student_names:
            self.stdout.write(self.style.WARNING("High Risk Students:"))
            for name_reason in high_risk_student_names:
                self.stdout.write(self.style.WARNING(f"- {name_reason}"))
        
        self.stdout.write(self.style.SUCCESS("\n--- Report Generation Complete ---"))

# To run this command:
# python manage.py send_summary_report
```
