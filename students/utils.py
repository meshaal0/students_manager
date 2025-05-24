from django.utils import timezone
from .models import Students, Attendance, Payment, Basics
from datetime import date, timedelta # timedelta added
from django.db.models import Count, Sum, Avg, F, ExpressionWrapper, fields # Added
from django.db.models.functions import TruncMonth, TruncWeek, TruncDay # Added
import calendar # Added

def get_daily_attendance_summary(target_date=None):
    """
    Calculates the attendance summary for a given date.

    Args:
        target_date (datetime.date, optional): The date for which to calculate the summary.
                                             Defaults to the current local date if None.

    Returns:
        dict: A dictionary containing:
            - 'date' (datetime.date): The date of the summary.
            - 'present_count' (int): Count of students marked as present.
            - 'absent_count' (int): Count of students marked as absent (is_absent=True).
            - 'present_students' (list[Students]): List of Student objects who were present.
            - 'absent_students' (list[Students]): List of Student objects who were marked absent.
            - 'unmarked_students_count' (int): Count of students with no attendance record for the day.
            - 'unmarked_students' (list[Students]): List of Student objects with no record for the day.
    """
    if target_date is None:
        target_date = timezone.localdate()  # Default to today if no date is specified

    # Query for students marked as present (is_absent=False) on the target_date
    present_attendance_records = Attendance.objects.filter(
        attendance_date=target_date,
        is_absent=False
    )
    present_students = [record.student for record in present_attendance_records]
    
    # Query for students marked as absent (is_absent=True) on the target_date
    absent_attendance_records = Attendance.objects.filter(
        attendance_date=target_date,
        is_absent=True
    )
    absent_students = [record.student for record in absent_attendance_records]

    # Identify all students who have any attendance record (present or absent) on the target_date
    students_with_record_today_ids = Attendance.objects.filter(
        attendance_date=target_date
    ).values_list('student_id', flat=True)
    
    # Retrieve all students in the system.
    # Consider adding an 'is_active' flag to the Students model for more precise filtering in large systems.
    all_students = Students.objects.all()

    # Determine unmarked students: those who are in `all_students` but not in `students_with_record_today_ids`
    unmarked_students = [
        student for student in all_students 
        if student.id not in students_with_record_today_ids
    ]

    return {
        'date': target_date,
        'present_count': present_attendance_records.count(),
        'absent_count': absent_attendance_records.count(),
        'present_students': present_students,
        'absent_students': absent_students,
        'unmarked_students_count': len(unmarked_students),
        'unmarked_students': unmarked_students,
    }

def get_absent_students_today():
    """
    Determines students considered "absent" for reporting purposes on the current day.
    This includes students explicitly marked as absent (`is_absent=True`)
    AND students who have no attendance record at all for the day.

    Returns:
        list[Students]: A list of unique Student objects considered absent for the current day.
    """
    today = timezone.localdate()
    summary = get_daily_attendance_summary(today)  # Leverage the daily summary function

    # Combine students explicitly marked absent and those who were not marked at all.
    # Using a set ensures uniqueness if a student somehow ended up in both lists (though unlikely with current logic).
    absent_for_report = list(set(summary['absent_students'] + summary['unmarked_students']))
    
    return absent_for_report


def get_student_remaining_free_tries(student):
    """
    Retrieves the number of remaining free attendance tries for a given student.

    Args:
        student (Students): The Student object to check.

    Returns:
        int: The number of free tries remaining for the student.

    Raises:
        ValueError: If the input `student` is not an instance of the Students model.
    """
    if not isinstance(student, Students):
        raise ValueError("Input `student` must be a Students model instance.")
    return student.free_tries


def get_students_paid_current_month():
    """
    Retrieves a queryset of students who have made a payment for the current calendar month.

    The "current calendar month" is determined by the server's local date at the time of execution.
    A student is considered "paid" if they have at least one Payment record where the `month`
    field matches the first day of the current month.

    Returns:
        QuerySet[Students]: A queryset of distinct Student objects who have paid this month.
    """
    # Determine the first day of the current month
    current_month_start = date(timezone.localdate().year, timezone.localdate().month, 1)
    
    # Query for students who have a related Payment record for this month_start
    paid_students = Students.objects.filter(
        payments__month=current_month_start  # Assumes 'payments' is the related_name from Student to Payment
    ).distinct()  # Ensure each student appears only once, even if multiple payments exist (though constrained by model)
    return paid_students


def get_students_with_overdue_payments():
    """
    Identifies students who are considered to have overdue payments for the current calendar month.

    A student is primarily considered to have an overdue payment if they do NOT have
    a `Payment` record for the current calendar month (first day of the current month).
    The `last_reset_month` field on the `Students` model provides historical context
    but is not the primary driver for this function's "overdue" status for the *current* month.
    This function aims to find students who owe payment for the current accounting period.

    Returns:
        QuerySet[Students]: A queryset of Student objects who have not paid for the current month.
    """
    current_month_start = date(timezone.localdate().year, timezone.localdate().month, 1)
    
    # Get IDs of students who HAVE made a payment for the current month
    paid_this_month_student_ids = Payment.objects.filter(
        month=current_month_start
    ).values_list('student_id', flat=True)

    # Students are considered overdue if their ID is NOT in the list of those who paid this month.
    # This directly answers "who has not yet paid for the current month?"
    overdue_students = Students.objects.exclude(
        id__in=paid_this_month_student_ids
    )
    
    # Note on `last_reset_month`:
    # The `Students.last_reset_month` field is updated when `process_student_payment` runs.
    # While `last_reset_month < current_month_start` is a strong indicator a student might be overdue,
    # the absence of a `Payment` record for `current_month_start` is the definitive criterion here
    # for determining if they owe for *this specific month*.
    # This function does not need to explicitly check `last_reset_month` because if a payment
    # was processed correctly, `last_reset_month` would be updated, AND a `Payment` record would exist,
    # thereby excluding them from `overdue_students`.

    return overdue_students


def process_student_payment(student, payment_month=None):
    """
    Processes a payment for a given student.

    This function creates a `Payment` record for the specified `student` and `payment_month`.
    If the payment is successfully recorded (i.e., a new `Payment` object is created),
    it updates the student's `last_reset_month` to the `payment_month` and resets
    their `free_tries` based on the `Basics` settings.

    Args:
        student (Students): The Student object for whom the payment is being processed.
        payment_month (datetime.date, optional): The first day of the month for which
            the payment is being made. Defaults to the first day of the current local month.

    Returns:
        Payment: The created or existing Payment object if successful.
        None: If `Basics` settings are not found (which are needed for `free_tries`).

    Raises:
        ValueError: If `student` is not a `Students` instance or `payment_month` is invalid.
    """
    if not isinstance(student, Students):
        raise ValueError("Input `student` must be a Students model instance.")

    # Retrieve system-wide settings (like default free_tries)
    try:
        basics = Basics.objects.first() # Assuming a single Basics record
        if not basics:
            # Critical configuration missing, cannot reliably reset free_tries.
            # Depending on policy, could raise an error or log this.
            return None 
    except Basics.DoesNotExist:
        # Same as above: critical configuration missing.
        return None

    # Determine the target payment month (ensure it's the first day of that month)
    if payment_month is None:
        current_local_date = timezone.localdate()
        payment_month = date(current_local_date.year, current_local_date.month, 1)
    elif isinstance(payment_month, date):
        # Normalize to the first day of the provided month
        payment_month = date(payment_month.year, payment_month.month, 1)
    else:
        raise ValueError("`payment_month` must be a datetime.date object or None.")

    # Attempt to create or retrieve the payment record.
    # `get_or_create` ensures idempotency for payments for the same student and month.
    payment_record, created = Payment.objects.get_or_create(
        student=student,
        month=payment_month,
        # `defaults` are used only if a new record is created.
        # `paid_on` is auto_now_add=True in model, so it's set on creation.
        # Explicitly setting it here in defaults is more for clarity if model changes.
        defaults={'paid_on': timezone.now()} 
    )

    if created:
        # If a new payment record was actually created (not just retrieved)
        student.last_reset_month = payment_month
        student.free_tries = basics.free_tries  # Reset free_tries based on system settings
        student.save(update_fields=['last_reset_month', 'free_tries'])
    
    return payment_record


def get_monthly_attendance_rate(student, year, month):
    """
    Calculates the attendance rate for a specific student for a given calendar month and year.

    The rate is defined as:
    (Number of days student was marked present) / (Total number of days student was marked either present or absent) * 100.
    Days for which the student has no `Attendance` record in the specified month are excluded from the calculation.

    Args:
        student (Students): The Student object for whom to calculate the rate.
        year (int): The calendar year.
        month (int): The calendar month (1-12).

    Returns:
        float: The attendance rate as a percentage (e.g., 75.0 for 75%).
               Returns 0.0 if the student has no attendance records (neither present nor absent)
               for the specified month.

    Raises:
        ValueError: If `student` is not a `Students` instance.
    """
    if not isinstance(student, Students):
        raise ValueError("Input `student` must be a Students model instance.")

    # Determine the start and end dates of the specified month
    try:
        num_days_in_month = calendar.monthrange(year, month)[1]
        start_date_month = date(year, month, 1)
        end_date_month = date(year, month, num_days_in_month)
    except calendar.IllegalMonthError: # Handle invalid month numbers
        # Or raise a more specific error, or return a specific value like None
        return 0.0 


    # Retrieve all attendance records for the student within the specified month
    attendance_records_in_month = Attendance.objects.filter(
        student=student,
        attendance_date__gte=start_date_month,
        attendance_date__lte=end_date_month
    )

    # Count days marked present
    days_present_count = attendance_records_in_month.filter(is_absent=False).count()
    # Count total days with any mark (present or absent)
    total_marked_days_count = attendance_records_in_month.count()

    if total_marked_days_count == 0:
        # No attendance records for this student in this month.
        return 0.0
    
    # Calculate rate
    rate = (days_present_count / total_marked_days_count) * 100
    return rate


def get_attendance_trends(start_date, end_date, period='day'):
    """
    Calculates overall attendance trends (count of present students)
    grouped by a specified period (day, week, or month) within a given date range.

    Args:
        start_date (datetime.date): The beginning of the date range (inclusive).
        end_date (datetime.date): The end of the date range (inclusive).
        period (str, optional): The period to group by. Can be 'day', 'week', or 'month'.
                                Defaults to 'day'.

    Returns:
        list[dict]: A list of dictionaries, where each dictionary represents a period
                    and contains:
                    - 'period_start' (datetime.date): The start date of the period.
                    - 'present_count' (int): The number of students marked present in that period.
                    The list is ordered by `period_start`.

    Raises:
        ValueError: If `period` is not one of 'day', 'week', or 'month'.
    """
    # Filter for attendance records of present students within the date range
    queryset = Attendance.objects.filter(
        attendance_date__gte=start_date,
        attendance_date__lte=end_date,
        is_absent=False  # Consider only students marked as present
    )

    # Determine the truncation function based on the specified period
    if period == 'day':
        trunc_function = TruncDay('attendance_date')
    elif period == 'week':
        trunc_function = TruncWeek('attendance_date') # Note: Week start depends on DB settings (e.g., Sunday or Monday)
    elif period == 'month':
        trunc_function = TruncMonth('attendance_date')
    else:
        raise ValueError("Invalid `period`. Choose from 'day', 'week', 'month'.")

    # Annotate the queryset to group by the chosen period and count present students
    trends = queryset.annotate(
        period_start=trunc_function  # Create a new field 'period_start' with the truncated date
    ).values(
        'period_start'  # Group by this truncated date
    ).annotate(
        present_count=Count('id')  # Count the number of attendance records (i.e., present students) in each group
    ).order_by(
        'period_start'  # Order the results chronologically
    )

    return list(trends)  # Convert the QuerySet of dictionaries to a list


def get_student_payment_history(student):
    """
    Retrieves the payment history for a specific student.

    Args:
        student (Students): The Student object for whom to retrieve payment history.

    Returns:
        QuerySet[Payment]: A queryset of Payment objects related to the student,
                           ordered by the payment month in descending order (most recent first).

    Raises:
        ValueError: If `student` is not a `Students` instance.
    """
    if not isinstance(student, Students):
        raise ValueError("Input `student` must be a Students model instance.")
    
    # Access payments using the related_name 'payments' from Students model to Payment model
    return student.payments.all().order_by('-month')


def get_revenue_trends(start_date, end_date, period='month'):
    """
    Calculates total estimated revenue from payments, grouped by a specified period (month or year)
    within a given date range.

    Important Assumption:
    This function currently estimates revenue based on the *current* `month_price`
    stored in the `Basics` model. This is a simplification. For accurate historical
    revenue tracking, the actual price paid should be stored with each `Payment` record,
    and this function should sum those actual amounts.

    Args:
        start_date (datetime.date): The beginning of the date range for payments (inclusive, based on Payment.month).
        end_date (datetime.date): The end of the date range for payments (inclusive, based on Payment.month).
        period (str, optional): The period to group revenue by. Can be 'month' or 'year'.
                                Defaults to 'month'.

    Returns:
        list[dict]: A list of dictionaries, where each dictionary represents a period
                    and contains:
                    - 'period_start' (datetime.date): The start date of the period
                                                     (first day of month or first day of year).
                    - 'total_revenue' (Decimal/float): The estimated total revenue for that period.
                    Returns an empty list if `Basics` settings or `month_price` is not found.
    """
    # Retrieve the current standard month price from Basics.
    # This is a simplification; ideally, price_paid would be on Payment model.
    try:
        basics = Basics.objects.first()
        if not basics or basics.month_price is None:
            # If no price is set, revenue calculation is not possible.
            return [] 
        current_month_price = basics.month_price # Assuming month_price is a Decimal or float
    except Basics.DoesNotExist:
        # If Basics settings don't exist, cannot calculate revenue.
        return []

    # Filter payments within the specified date range (based on the 'month' field of Payment model)
    queryset = Payment.objects.filter(
        month__gte=start_date, 
        month__lte=end_date
    )

    # Determine truncation strategy based on the period
    if period == 'month':
        trunc_function = TruncMonth('month')
    elif period == 'year':
        # For year, we group by month first, then aggregate in Python.
        # Django's TruncYear isn't universally supported or might behave differently across DBs.
        # A common approach is to truncate to month, then process.
        trunc_function = TruncMonth('month') # Will be further processed for 'year'
    else:
        # Default to month or raise an error for invalid period
        # For now, defaulting to month for simplicity if period is invalid.
        trunc_function = TruncMonth('month')


    # Annotate queryset to group by the period and count payments
    # This count will then be multiplied by `current_month_price`.
    payment_counts_by_period = queryset.annotate(
        period_group=trunc_function  # Group by the truncated date (month or start of month for year)
    ).values(
        'period_group'  # Select the grouping period
    ).annotate(
        num_payments=Count('id')  # Count payments in each group
    ).order_by(
        'period_group'  # Order chronologically
    )
    
    # Process the grouped data to calculate revenue
    revenue_trends_data = []
    if period == 'year':
        yearly_aggregated_revenue = {} # {<year_int>: <total_revenue_for_year>}
        for entry in payment_counts_by_period:
            year_of_payment = entry['period_group'].year
            revenue_for_entry = entry['num_payments'] * current_month_price
            
            if year_of_payment not in yearly_aggregated_revenue:
                yearly_aggregated_revenue[year_of_payment] = 0
            yearly_aggregated_revenue[year_of_payment] += revenue_for_entry
        
        # Convert aggregated yearly data to the list format
        for year_val, total_revenue in sorted(yearly_aggregated_revenue.items()):
            revenue_trends_data.append({
                'period_start': date(year_val, 1, 1), # Represent year by its first day
                'total_revenue': total_revenue
            })
    else: # For 'month' period
        for entry in payment_counts_by_period:
            revenue_trends_data.append({
                'period_start': entry['period_group'], # This is already the first of the month
                'total_revenue': entry['num_payments'] * current_month_price
            })
            
    return revenue_trends_data

# students/utils.py
from django.utils import timezone # قد تحتاجها لمتغيرات التاريخ الافتراضية

def process_message_template(template_string, context_dict):
    '''
    يستبدل المتغيرات المعرفة بين أقواس معقوفة {} في نص القالب
    بالقيم المقابلة لها من القاموس السياقي.

    مثال:
    template = "مرحباً {student_name}, تاريخ اليوم هو {date}."
    context = {'student_name': 'علي', 'date': '2023-10-26'}
    process_message_template(template, context) 
    -> "مرحباً علي, تاريخ اليوم هو 2023-10-26."
    '''
    processed_string = template_string
    for key, value in context_dict.items():
        placeholder = "{" + str(key) + "}" # بناء المتغير النائب مثل {student_name}
        processed_string = processed_string.replace(placeholder, str(value))
    return processed_string

def get_default_template_context(student=None):
    '''
    يُرجع قاموسًا بالمتغيرات الافتراضية التي يمكن استخدامها في قوالب الرسائل.
    '''
    context = {
        'date': timezone.localdate().strftime('%Y-%m-%d'),
        'time': timezone.localtime().strftime('%I:%M %p'),
    }
    if student:
        context['student_name'] = student.name
        context['barcode'] = student.barcode
        context['father_phone'] = student.father_phone
        # يمكنك إضافة المزيد من حقول الطالب هنا إذا لزم الأمر
    return context
