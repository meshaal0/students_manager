from django.utils import timezone
from datetime import timedelta, date
from students.models import Payment, Attendance, Basics # Assuming Basics model stores initial_free_tries

def get_student_risk_assessment(student):
    """
    Provides a simplified, rule-based risk assessment for a student.
    This is a placeholder and does not use a trained ML model.
    """
    today = timezone.localdate()
    risk = 'Low' # Default risk
    reasons = []

    # Rule 1: Free trial expired and no payment for the current month
    current_month_start = today.replace(day=1)
    paid_current_month = Payment.objects.filter(
        student=student,
        month__year=current_month_start.year,
        month__month=current_month_start.month
    ).exists()

    basics = Basics.objects.first() # Get default free tries
    initial_free_tries = basics.free_tries if basics else 3 # Fallback

    # Check if free tries were used up.
    # This condition assumes free_tries are decremented and 0 means all used.
    # If student.last_reset_month is available, a better check might be:
    # student.last_reset_month is not None AND student.free_tries == 0
    if student.free_tries == 0 and not paid_current_month:
        # To be more accurate, one might also check if the student was expected to pay this month
        # (e.g. their free trial period just ended).
        # For now, if free_tries is 0 and no payment this month, it's a high risk.
        risk = 'High'
        reasons.append("Free trial exhausted and no payment this month.")
        return risk, reasons # High risk overrides others for now

    # Rule 2: Low attendance in the last 2 weeks
    two_weeks_ago = today - timedelta(weeks=2)
    
    # Count distinct school days in the last 2 weeks
    # This counts days where *any* student had an attendance record.
    # A more robust approach might use a predefined school calendar.
    school_days_last_2_weeks = Attendance.objects.filter(
        attendance_date__gte=two_weeks_ago,
        attendance_date__lte=today
    ).values('attendance_date').distinct().count()

    if school_days_last_2_weeks > 0: # Avoid division by zero
        attended_days_last_2_weeks = Attendance.objects.filter(
            student=student,
            attendance_date__gte=two_weeks_ago,
            attendance_date__lte=today,
            is_present=True # Assuming is_present=True means attended
        ).count()
        
        attendance_rate_last_2_weeks = (attended_days_last_2_weeks / school_days_last_2_weeks) * 100
        
        if attendance_rate_last_2_weeks < 50:
            risk = 'Medium'
            reasons.append(f"Attendance in last 2 weeks is {attendance_rate_last_2_weeks:.1f}%.")
    elif student.date_joined.date() < two_weeks_ago : # Student is not new, but no school days recorded
        # If student is not new and no school activity was recorded at all in last 2 weeks, it's a concern.
        risk = 'Medium'
        reasons.append("No school attendance activity recorded in the last 2 weeks for any student, and student is not new.")


    # Rule 3: Multiple Absences this month (Example)
    absences_this_month = Attendance.objects.filter(
        student=student,
        attendance_date__month=today.month,
        attendance_date__year=today.year,
        is_absent=True
    ).count()

    if absences_this_month >= 5: # Example threshold
        if risk == 'Low': risk = 'Medium' # Elevate from Low to Medium
        reasons.append(f"{absences_this_month} absences this month.")
    elif absences_this_month >= 2 and risk == 'Low':
         reasons.append(f"{absences_this_month} absences this month.")


    if not reasons and risk == 'Low':
        reasons.append("Generally good standing based on current rules.")
        
    return risk, reasons
