from django.utils import timezone
from .models import Students, Attendance, Payment, Basics
from datetime import date, timedelta # timedelta added
from django.db.models import Count, Sum, Avg, F, ExpressionWrapper, fields # Added
from django.db.models.functions import TruncMonth, TruncWeek, TruncDay # Added
import calendar # Added
from dateutil.relativedelta import relativedelta # Added for term payments

def has_active_payment(student, check_date):
    """
    Checks if a student has an active payment (monthly or term) covering the check_date.
    """
    if not isinstance(student, Students):
        raise ValueError("Input `student` must be a Students model instance.")
    if not isinstance(check_date, date):
        raise ValueError("Input `check_date` must be a date instance.")

    current_month_start = date(check_date.year, check_date.month, 1)

    # 1. Check for an active monthly payment for the current month
    if Payment.objects.filter(
        student=student,
        payment_type='monthly',
        month=current_month_start
    ).exists():
        return True

    # 2. Check for an active term payment covering the check_date
    term_payments = Payment.objects.filter(student=student, payment_type='term')
    for term_payment in term_payments:
        if term_payment.term_duration_months is None or term_payment.term_duration_months <= 0:
            continue # Skip invalid term payments

        term_start_date = term_payment.month # This is the first day of the start month
        # Calculate the end date of the term.
        # The term covers all days up to, but not including, the first day of the month *after* the term ends.
        # For example, a 3-month term starting Jan 1st (2023-01-01) ends March 31st.
        # The next payment would be due April 1st. So, term_end_date should be April 1st (2023-04-01).
        term_end_date = term_start_date + relativedelta(months=term_payment.term_duration_months)

        # Check if the check_date is within the term period [term_start_date, term_end_date)
        if term_start_date <= check_date < term_end_date:
            return True

    return False

def get_daily_attendance_summary(target_date=None, branch_id=None):
    """
    Calculates the attendance summary for a given date, optionally filtered by branch.

    Args:
        target_date (datetime.date, optional): The date for which to calculate the summary.
                                             Defaults to the current local date if None.
        branch_id (str, optional): The ID of the branch to filter by.

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
        target_date = timezone.localdate()

    # Base queryset for Attendance, filtered by date
    attendance_base_qs = Attendance.objects.filter(attendance_date=target_date)

    # Base queryset for Students
    students_qs = Students.objects.all()
    if branch_id:
        students_qs = students_qs.filter(branch=branch_id)
        attendance_base_qs = attendance_base_qs.filter(student__branch=branch_id)

    # Present students
    present_attendance_records = attendance_base_qs.filter(is_absent=False)
    present_students = [record.student for record in present_attendance_records]
    
    # Absent students
    absent_attendance_records = attendance_base_qs.filter(is_absent=True)
    absent_students = [record.student for record in absent_attendance_records]

    # IDs of students with any attendance record today (respecting branch filter if applied)
    students_with_record_today_ids = attendance_base_qs.values_list('student_id', flat=True)
    
    # Unmarked students (from the potentially branch-filtered list of all students)
    unmarked_students = [
        student for student in students_qs
        if student.id not in students_with_record_today_ids
    ]

    return {
        'date': target_date,
        'present_count': len(present_students), # Count from the list of students to ensure branch consistency
        'absent_count': len(absent_students),   # Count from the list of students
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

    A student is primarily considered to have an overdue payment if they do not have an
    active payment (monthly or term-based) covering the current date.
    Optionally filters by branch.

    Args:
        branch_id (str, optional): The ID of the branch to filter by.

    Returns:
        list[Students]: A list of Student objects who do not have an active payment for today.
    """
    today = timezone.localdate()
    students_query = Students.objects.all()
    if branch_id:
        students_query = students_query.filter(branch=branch_id)
    
    overdue_students_list = []
    for student in students_query: # Iterate over potentially filtered students
        if not has_active_payment(student, today):
            overdue_students_list.append(student)

    return overdue_students_list


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
        return None


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
    grouped by a specified period (day, week, or month) within a given date range,
    optionally filtered by branch.

    Args:
        start_date (datetime.date): The beginning of the date range (inclusive).
        end_date (datetime.date): The end of the date range (inclusive).
        period (str, optional): The period to group by. Can be 'day', 'week', or 'month'.
                                Defaults to 'day'.
        branch_id (str, optional): The ID of the branch to filter by.


    Returns:
        list[dict]: A list of dictionaries, where each dictionary represents a period
                    and contains:
                    - 'period_start' (datetime.date): The start date of the period.
                    - 'present_count' (int): The number of students marked present in that period.
                    The list is ordered by `period_start`.

    Raises:
        ValueError: If `period` is not one of 'day', 'week', 'month'.
    """
    # Base queryset for Attendance
    queryset = Attendance.objects.filter(
        attendance_date__gte=start_date,
        attendance_date__lte=end_date,
        is_absent=False  # Consider only students marked as present
    )

    if branch_id:
        queryset = queryset.filter(student__branch=branch_id)

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


def get_revenue_trends(start_date, end_date, period='month', branch_id=None):
    """
    Calculates total estimated revenue from payments, grouped by a specified period (month or year)
    within a given date range, optionally filtered by branch.

    Important Assumption:
    This function currently estimates revenue based on the *current* prices (`month_price`, `term_price`)
    stored in the `Basics` model. This is a simplification. For accurate historical
    revenue tracking, the actual price paid should be stored with each `Payment` record,
    and this function should sum those actual amounts.

    Args:
        start_date (datetime.date): The beginning of the date range for payments (inclusive, based on Payment.month).
        end_date (datetime.date): The end of the date range for payments (inclusive, based on Payment.month).
        period (str, optional): The period to group revenue by. Can be 'month' or 'year'.
                                Defaults to 'month'.
        branch_id (str, optional): The ID of the branch to filter by.

    Returns:
        list[dict]: A list of dictionaries, where each dictionary represents a period
                    and contains:
                    - 'period_start' (datetime.date): The start date of the period
                                                     (first day of month or first day of year).
                    - 'total_revenue' (Decimal/float): The estimated total revenue for that period.
                    Returns an empty list if `Basics` settings are not found.
    """
    try:
        basics = Basics.objects.first()
        if not basics: # Check if basics object itself is None
            return [] 
        # current_month_price will be determined based on payment_type later
    except Basics.DoesNotExist:
        return []

    # Base queryset for Payments
    queryset = Payment.objects.filter(month__gte=start_date, month__lte=end_date)
    if branch_id:
        queryset = queryset.filter(student__branch=branch_id)

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
    # This logic needs to sum actual payment amounts based on type (monthly/term)
    # instead of just counting payments and multiplying by a single price.
    
    revenue_trends_data = []

    # Annotate with period_group first
    payments_by_period = queryset.annotate(
        period_group=trunc_function
    ).values(
        'period_group', 'payment_type' # Also get payment_type to determine price
    ).annotate(
        num_payments=Count('id')
    ).order_by('period_group')

    # Aggregate revenue, considering payment_type
    aggregated_revenue = {} # Key: period_group, Value: total_revenue

    for entry in payments_by_period:
        period_group = entry['period_group']
        payment_type = entry['payment_type']
        num_payments = entry['num_payments']

        price = 0
        if payment_type == 'monthly' and basics.month_price is not None:
            price = basics.month_price
        elif payment_type == 'term' and basics.term_price is not None:
            # For term, the price is for the whole term.
            # If a term payment falls into this period_group (month/year), we count its full price.
            # This assumes 'month' on Payment is the start of the term.
            price = basics.term_price
            # This might overcount if a term spans multiple 'period_group's and we only group by start month.
            # A more accurate approach would be to prorate or allocate revenue if term price should be spread.
            # For now, if payment.month (term start) is in this period_group, count full term_price.
            
        revenue_for_entry = num_payments * price

        current_total = aggregated_revenue.get(period_group, 0)
        aggregated_revenue[period_group] = current_total + revenue_for_entry

    # Format for output
    if period == 'year':
        yearly_aggregated_revenue = {}
        for period_group, total_revenue in aggregated_revenue.items():
            year_of_payment = period_group.year
            current_year_total = yearly_aggregated_revenue.get(year_of_payment, 0)
            yearly_aggregated_revenue[year_of_payment] = current_year_total + total_revenue
        
        for year_val, total_revenue in sorted(yearly_aggregated_revenue.items()):
            revenue_trends_data.append({
                'period_start': date(year_val, 1, 1),
                'total_revenue': total_revenue
            })
    else: # For 'month' period
        for period_group, total_revenue in sorted(aggregated_revenue.items()):
            revenue_trends_data.append({
                'period_start': period_group,
                'total_revenue': total_revenue
            })
            
    return revenue_trends_data

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