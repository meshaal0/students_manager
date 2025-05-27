from django.test import TestCase
from django.utils import timezone
from datetime import date, timedelta
from django.core.files.uploadedfile import SimpleUploadedFile # For dummy logo
from .models import Students, Attendance, Payment, Basics
from .utils import (
    get_daily_attendance_summary, process_student_payment,
    get_students_with_overdue_payments, get_monthly_attendance_rate,
    get_student_remaining_free_tries, get_students_paid_current_month,
    get_absent_students_today # Added this as it's in utils and good to test
)

# Create your tests here.
class StudentUtilsTests(TestCase):
    def setUp(self):
        # Create a dummy logo file for tests
        dummy_logo = SimpleUploadedFile(
            "dummy_logo.png", 
            b"file_content", # Some content for the file
            content_type="image/png"
        )
        # Create Basics record (required by process_student_payment and for free_tries)
        self.basics = Basics.objects.create(
            last_time=timezone.now().time(), 
            month_price=100, 
            free_tries=3,
            logo=dummy_logo
        )
        
        # Create some students
        self.student1 = Students.objects.create(name="طالب ١", father_phone="111", free_tries=self.basics.free_tries)
        self.student2 = Students.objects.create(name="طالب ٢", father_phone="222", free_tries=self.basics.free_tries)
        self.student3 = Students.objects.create(name="طالب ٣", father_phone="333", free_tries=0, last_reset_month=date(2023,1,1)) # Paid long ago
        self.student4 = Students.objects.create(name="طالب ٤", father_phone="444", free_tries=1) # Student with some tries

    def test_get_student_remaining_free_tries(self):
        self.assertEqual(get_student_remaining_free_tries(self.student1), self.basics.free_tries)
        self.assertEqual(get_student_remaining_free_tries(self.student3), 0)
        self.assertEqual(get_student_remaining_free_tries(self.student4), 1)

    def test_process_student_payment(self):
        payment_month = date(timezone.localdate().year, timezone.localdate().month, 1)
        
        payment_record = process_student_payment(self.student1)
        self.assertIsNotNone(payment_record)
        self.assertEqual(payment_record.student, self.student1)
        self.assertEqual(payment_record.month, payment_month)
        
        self.student1.refresh_from_db() # Reload student from DB
        self.assertEqual(self.student1.last_reset_month, payment_month)
        self.assertEqual(self.student1.free_tries, self.basics.free_tries) # Check if free_tries are reset
        
        # Test idempotency (paying again for same month)
        payment_record_again = process_student_payment(self.student1, payment_month)
        self.assertIsNotNone(payment_record_again)
        self.assertEqual(payment_record.id, payment_record_again.id) # Should be the same payment record
        self.assertEqual(Payment.objects.filter(student=self.student1, month=payment_month).count(), 1)

    def test_get_students_paid_current_month(self):
        # No one paid yet for current month
        self.assertQuerysetEqual(get_students_paid_current_month().order_by('name'), [])

        process_student_payment(self.student1)
        paid_students = get_students_paid_current_month()
        self.assertIn(self.student1, paid_students)
        self.assertNotIn(self.student2, paid_students)

    def test_get_students_with_overdue_payments(self):
        today = timezone.localdate()
        # current_month_start = date(today.year, today.month, 1) # Not directly used in assertions here

        # Initially, all students who haven't paid this month are overdue
        overdue = get_students_with_overdue_payments().order_by('name')
        expected_overdue = [self.student1, self.student2, self.student3, self.student4]
        self.assertQuerysetEqual(overdue, [repr(s) for s in expected_overdue], transform=repr, ordered=False)
        
        # Student1 pays
        process_student_payment(self.student1)
        overdue_after_s1_pays = get_students_with_overdue_payments().order_by('name')
        expected_overdue_after_s1_pays = [self.student2, self.student3, self.student4]
        self.assertQuerysetEqual(overdue_after_s1_pays, [repr(s) for s in expected_overdue_after_s1_pays], transform=repr, ordered=False)
        self.assertNotIn(self.student1, overdue_after_s1_pays)


    def test_get_daily_attendance_summary(self):
        today = timezone.localdate()
        Attendance.objects.create(student=self.student1, attendance_date=today, is_absent=False) # Present
        Attendance.objects.create(student=self.student2, attendance_date=today, is_absent=True)  # Absent
        # Student3 and Student4 have no record for today

        summary = get_daily_attendance_summary(today)
        self.assertEqual(summary['present_count'], 1)
        self.assertIn(self.student1, summary['present_students'])
        self.assertEqual(summary['absent_count'], 1)
        self.assertIn(self.student2, summary['absent_students'])
        self.assertEqual(summary['unmarked_students_count'], 2) 
        self.assertIn(self.student3, summary['unmarked_students'])
        self.assertIn(self.student4, summary['unmarked_students'])

    def test_get_monthly_attendance_rate(self):
        year = timezone.localdate().year
        month = timezone.localdate().month
        
        # Student1: 2 present, 1 absent. Rate = (2/3)*100
        Attendance.objects.create(student=self.student1, attendance_date=date(year, month, 1), is_absent=False)
        Attendance.objects.create(student=self.student1, attendance_date=date(year, month, 2), is_absent=False)
        Attendance.objects.create(student=self.student1, attendance_date=date(year, month, 3), is_absent=True)
        
        rate_s1 = get_monthly_attendance_rate(self.student1, year, month)
        self.assertAlmostEqual(rate_s1, (2/3) * 100, places=2)

        # Student2: 1 present, 0 absent. Rate = (1/1)*100
        Attendance.objects.create(student=self.student2, attendance_date=date(year, month, 1), is_absent=False)
        rate_s2 = get_monthly_attendance_rate(self.student2, year, month)
        self.assertAlmostEqual(rate_s2, 100.0, places=2)

        # Student3: No records for this month. Rate = 0.0
        rate_s3 = get_monthly_attendance_rate(self.student3, year, month)
        self.assertEqual(rate_s3, 0.0)

        # Student4: 1 absent. Rate = (0/1)*100 = 0.0
        Attendance.objects.create(student=self.student4, attendance_date=date(year, month, 5), is_absent=True)
        rate_s4 = get_monthly_attendance_rate(self.student4, year, month)
        self.assertEqual(rate_s4, 0.0)

    def test_get_absent_students_today(self):
        today = timezone.localdate()
        # Student1: Present
        Attendance.objects.create(student=self.student1, attendance_date=today, is_absent=False)
        # Student2: Marked as absent
        Attendance.objects.create(student=self.student2, attendance_date=today, is_absent=True)
        # Student3: No record (should be considered absent for this report)
        # Student4: No record (should be considered absent for this report)

        absent_today_list = get_absent_students_today()

        self.assertNotIn(self.student1, absent_today_list)
        self.assertIn(self.student2, absent_today_list)
        self.assertIn(self.student3, absent_today_list)
        self.assertIn(self.student4, absent_today_list)
        self.assertEqual(len(absent_today_list), 3)

    def test_process_student_payment_no_basics(self):
        """
        Test that process_student_payment handles missing Basics settings gracefully.
        """
        Basics.objects.all().delete() # Ensure no Basics record exists
        payment_record = process_student_payment(self.student1)
        self.assertIsNone(payment_record, "Payment processing should fail or return None if Basics settings are missing.")

# Further tests for get_attendance_trends and get_revenue_trends could be added,
# but they are more complex due to date ranges and grouping.
# The current set covers the core individual student and daily summary utilities.

# Example test for view (very basic, just checks if it loads)
# More complex view testing would involve checking context, form submissions etc.
class ViewsTestCase(TestCase):
    def setUp(self):
        # Create a dummy logo file for tests
        dummy_logo = SimpleUploadedFile("dummy_logo.png", b"file_content", content_type="image/png")
        self.basics = Basics.objects.create(
            last_time=timezone.now().time(), 
            month_price=100, 
            free_tries=3,
            logo=dummy_logo
        )
        self.student = Students.objects.create(name="Test Student", father_phone="12345")

    def test_daily_dashboard_view_loads(self):
        response = self.client.get('/dashboard/') # Assuming '/dashboard/' is the URL for daily_dashboard_view
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "لوحة المتابعة اليومية")

    def test_historical_insights_view_loads(self):
        response = self.client.get('/historical-insights/') # Assuming '/historical-insights/' is the URL
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "التحليلات التاريخية")

    # Add more view tests:
    # - Test with GET parameters for historical_insights_view
    # - Test context data for both views
    # - If views have POST logic (not in this case for dashboard/insights), test that.
    
    # Note: The URLs for these views need to be correctly mapped in students/urls.py
    # and included in the project's main urls.py for self.client.get to work.
    # For this test, I'm assuming they are mapped at root like '/dashboard/'
    # If they are under a namespace like '/students/dashboard/', adjust the paths.
    # From previous tasks, they are:
    # path('dashboard/', views.daily_dashboard_view, name='daily_dashboard')
    # path('historical-insights/', views.historical_insights_view, name='historical_insights')
    # So, the paths used above are correct if students app urls are included at root level.
    # If students app is namespaced e.g. path('students/', include('students.urls')),
    # then paths would be '/students/dashboard/', etc.
    # For now, assuming root level inclusion for simplicity in test.
    # Django's test client will resolve them correctly if urls are set up.
    # Let's use reverse to be more robust.
    
    def test_daily_dashboard_view_loads_with_reverse(self):
        from django.urls import reverse
        url = reverse('daily_dashboard')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "لوحة المتابعة اليومية")

    def test_historical_insights_view_loads_with_reverse(self):
        from django.urls import reverse
        url = reverse('historical_insights')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "التحليلات التاريخية")