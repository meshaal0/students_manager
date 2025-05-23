from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from datetime import date, timedelta
from django.core.management import call_command
from io import StringIO
from unittest.mock import patch, call # call is for checking multiple calls with specific arguments

from .models import Students, Attendance, Payment, Basics
from .utils.risk_assessment_utils import get_student_risk_assessment
# from .utils.whatsapp_queue import send_low_recent_attendance_warning, send_high_risk_alert # For mocking later

# --- Test Data Setup ---
class BaseTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.basics = Basics.objects.create(
            last_time=timezone.now().time(),
            month_price=100,
            free_tries=3,
            # logo will not be created as it requires an actual file
        )

        cls.student1 = Students.objects.create(
            name="Student One",
            father_phone="1111111111",
            free_tries=3 # Starts with full free tries
        )
        cls.student2 = Students.objects.create(
            name="Student Two",
            father_phone="2222222222",
            free_tries=0 # Used up free tries
        )
        cls.student3 = Students.objects.create(
            name="Student Three (Low Attendance)",
            father_phone="3333333333",
            free_tries=3
        )
        cls.student4 = Students.objects.create(
            name="Student Four (High Risk)",
            father_phone="4444444444",
            free_tries=0 # For high risk due to free_tries=0 and unpaid
        )

        cls.today = timezone.localdate()
        cls.yesterday = cls.today - timedelta(days=1)
        cls.two_weeks_ago = cls.today - timedelta(weeks=2)
        cls.one_month_ago = cls.today - timedelta(days=30)
        cls.current_month_start = cls.today.replace(day=1)

        # Attendance for Student 1 (Good attendance, paid)
        Attendance.objects.create(student=cls.student1, attendance_date=cls.today, is_absent=False)
        for i in range(1, 5): # Present for a few days this month
             Attendance.objects.create(student=cls.student1, attendance_date=cls.current_month_start + timedelta(days=i), is_absent=False)
        Payment.objects.create(student=cls.student1, month=cls.current_month_start)


        # Attendance for Student 2 (Poor attendance, unpaid, used free tries)
        Attendance.objects.create(student=cls.student2, attendance_date=cls.one_month_ago, is_absent=False) # Last seen a month ago
        # No payment for student2 this month

        # Attendance for Student 3 (Low Attendance setup)
        # To simulate low attendance for notification test: 10 school days, make 8 absent, 2 present
        # Let's assume school was open for the last 10 days (excluding today for mark_absentees test)
        for i in range(1, 11): # Last 10 days before today
            day = cls.today - timedelta(days=i)
            if i <= 2: # Present for 2 days
                Attendance.objects.create(student=cls.student3, attendance_date=day, is_absent=False)
            else: # Absent for 8 days
                Attendance.objects.create(student=cls.student3, attendance_date=day, is_absent=True)
        
        # Student 4 is for high risk (free_tries=0, unpaid current month) - no attendance needed for this specific risk factor


# --- Test Dashboard View ---
class DashboardViewTests(BaseTestCase):
    def test_dashboard_view_access(self):
        client = Client()
        response = client.get(reverse('performance_dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'performance_dashboard.html')

    def test_dashboard_context_data(self):
        client = Client()
        response = client.get(reverse('performance_dashboard'))
        self.assertEqual(response.status_code, 200)
        context = response.context

        # Expected: student1 paid, student2 unpaid, student3 unpaid, student4 unpaid
        self.assertEqual(context['payment_summary']['paid'], 1)
        self.assertEqual(context['payment_summary']['unpaid'], 3) 
        
        # Expected: student2 (free_tries=0, unpaid), student4 (free_tries=0, unpaid)
        # But student2 had attendance long ago, so might not be "on free trial" if logic implies active trial usage
        # Current dashboard logic: free_tries > 0 AND unpaid this month
        # Student1 paid. Student3 free_tries=3, unpaid. Student2 free_tries=0. Student4 free_tries=0.
        self.assertEqual(context['students_on_free_trial'], 1) # Student3

        # Student1: 5 present / (days_in_month_so_far or distinct_school_days)
        # Assuming distinct_school_days is at least 5 (from student1's attendance) + 10 (from student3)
        # student1_attendance_data = next((s for s in context['student_attendance_data'] if s['name'] == "Student One"), None)
        # self.assertIsNotNone(student1_attendance_data)
        # self.assertGreater(student1_attendance_data['rate'], 0) # Actual rate depends on distinct_school_days

        # Low attendance students (rate < 70%)
        # Student2 has very low rate. Student3 has 20% over last 10 days (dashboard calculates over month)
        # Student3 in current month: 2 present / (days_in_month_so_far or distinct_school_days)
        # Calculation of 'effective_school_days_for_month' in view is complex. Test existence.
        self.assertIn('low_attendance_students', context)


        # Students at Risk (using get_student_risk_assessment)
        # Student2: free_tries=0, unpaid, old attendance -> High risk
        # Student4: free_tries=0, unpaid -> High risk
        # Student3: low recent attendance -> Medium risk
        students_at_risk_names = [item['student'].name for item in context['students_at_risk']]
        self.assertIn("Student Two", students_at_risk_names)
        self.assertIn("Student Three (Low Attendance)", students_at_risk_names)
        self.assertIn("Student Four (High Risk)", students_at_risk_names)


# --- Test Utility Functions ---
class UtilsTests(BaseTestCase):
    def test_get_student_risk_assessment(self):
        # Student 1: Paid, good attendance (assumed by recent attendance) -> Low
        risk, reasons = get_student_risk_assessment(self.student1)
        self.assertEqual(risk, 'Low')

        # Student 2: free_tries=0, unpaid, no recent attendance -> High
        risk_s2, reasons_s2 = get_student_risk_assessment(self.student2)
        self.assertEqual(risk_s2, 'High')
        self.assertIn("Free trial exhausted and no payment this month.", reasons_s2)

        # Student 3: Low recent attendance (2/10 days present) -> Medium
        # Note: get_student_risk_assessment checks last 2 weeks. Our setup is last 10 days.
        # We need to ensure the data aligns with the 2-week window for a precise test here.
        # For now, let's manually add some absences for student3 in the last 2 weeks if not covered.
        # The setup already has student3 with 20% attendance in last 10 days.
        # If today is beginning of month, this might not trigger "absences this month" rule.
        risk_s3, reasons_s3 = get_student_risk_assessment(self.student3)
        self.assertEqual(risk_s3, 'Medium')
        self.assertTrue(any("Attendance in last 2 weeks" in reason for reason in reasons_s3))
        
        # Student 4: free_tries=0, unpaid -> High (even with no attendance data)
        risk_s4, reasons_s4 = get_student_risk_assessment(self.student4)
        self.assertEqual(risk_s4, 'High')
        self.assertIn("Free trial exhausted and no payment this month.", reasons_s4)

        # Student with multiple absences this month but otherwise okay
        student_many_absences = Students.objects.create(name="Absence Test", father_phone="555", free_tries=3)
        Payment.objects.create(student=student_many_absences, month=self.current_month_start) # Paid
        for i in range(5):
            Attendance.objects.create(student=student_many_absences, attendance_date=self.current_month_start + timedelta(days=i), is_absent=True)
        # Add one present day to avoid low attendance rule if school days are few
        Attendance.objects.create(student=student_many_absences, attendance_date=self.current_month_start + timedelta(days=5), is_absent=False)

        risk_ma, reasons_ma = get_student_risk_assessment(student_many_absences)
        self.assertEqual(risk_ma, 'Medium') # Should be medium due to 5 absences
        self.assertIn("5 absences this month.", reasons_ma)


# --- Test Management Command ---
class ManagementCommandsTests(BaseTestCase):
    def test_send_summary_report_command(self):
        # Add more specific data for the command if needed, e.g. more varied risk levels
        out = StringIO()
        call_command('send_summary_report', stdout=out)
        report_output = out.getvalue()

        self.assertIn(f"--- Monthly Summary Report - {self.today.strftime('%B')}, {self.today.year} ---", report_output)
        self.assertIn("Overall Attendance Rate:", report_output)
        self.assertIn("Students Paid: 1", report_output) # Student1
        self.assertIn("Students Unpaid: 3", report_output) # Student2, Student3, Student4
        self.assertIn("Students Currently on Free Trial: 1", report_output) # Student3
        self.assertIn("Students at Medium Risk:", report_output) # Student3
        self.assertIn("Students at High Risk:", report_output) # Student2, Student4
        self.assertIn("Student Two", report_output) # High risk student name
        self.assertIn("Student Four (High Risk)", report_output) # High risk student name


# --- Test Notification Logic ---
class NotificationLogicTests(BaseTestCase):
    # Patch the actual queueing functions in whatsapp_queue module
    @patch('students.utils.whatsapp_queue.send_low_recent_attendance_warning')
    @patch('students.utils.whatsapp_queue.send_high_risk_alert')
    def test_mark_absentees_notifications(self, mock_send_high_risk, mock_send_low_warning):
        client = Client()
        
        # --- Scenario 1: Low Recent Attendance for Student3 ---
        # Student3 is already set up with 2 present, 8 absent in last 10 days (excluding today)
        # Marking student3 absent today should trigger the low attendance warning.
        # Student3 has free_tries=3, so not high risk for free_trial reason.
        
        # Ensure student3 has more than 1 absence this month for the check `if total_absences > 1:`
        # The setup has 8 absences in the prior 10 days. If these fall in current month, it's fine.
        # Let's assume some of those 8 absences are in the current month.
        
        # Simulate POST request to mark_absentees. This view marks ALL un-attended students absent.
        # We need to ensure other students (student1) are marked present today to avoid them being marked absent.
        Attendance.objects.filter(student=self.student1, attendance_date=self.today).delete() # remove if any
        Attendance.objects.create(student=self.student1, attendance_date=self.today, is_absent=False) # Student1 is present

        # Student2 was last seen a month ago, will be marked absent.
        # Student4 has no attendance, will be marked absent.

        response = client.post(reverse('mark_absentees')) # This will mark student3, student2, student4 absent today
        self.assertEqual(response.status_code, 302) # Redirects

        # Check for Student3 low attendance warning
        # Student3's attendance over last 10 school days (before today) was 20% (2 present / 10 school days)
        # Expected call: send_low_recent_attendance_warning(student_name, father_phone, rate, period_days)
        # rate is 20.0, period_days is 10
        
        called_with_correct_args_for_s3 = False
        for single_call in mock_send_low_warning.call_args_list:
            args, kwargs = single_call
            # args[0] is student_name, args[1] is father_phone, args[2] is rate, args[3] is period_days
            if args[0] == self.student3.name and args[1] == self.student3.father_phone and round(args[2]) == 20 and args[3] == 10:
                called_with_correct_args_for_s3 = True
                break
        self.assertTrue(called_with_correct_args_for_s3, "Low attendance warning for Student3 not called with expected args.")


        # --- Scenario 2: High Risk for Student4 ---
        # Student4 is free_tries=0, unpaid. Marking absent today.
        # This should trigger high risk alert. Low attendance warning should not be sent for Student4
        # as their earlier attendance history isn't specifically crafted for that.
        
        # Check if high risk alert was called for Student4
        # Student4 has risk_assessment of 'High' due to free_tries=0 and no payment.
        # The low attendance warning for Student4 might or might not have been called depending on its actual attendance data.
        # The logic is `if not sent_low_attendance_warning: ... send_high_risk_alert`
        # So we need to ensure Student4 *didn't* trigger low attendance warning to robustly test high risk alert.
        # Student4 has no prior attendance, so its recent attendance rate would be 0 over 0 school days,
        # which the `if len(recent_school_days_dates) == LOW_ATTENDANCE_PERIOD_DAYS:` check would likely bypass.

        called_s4_high_risk = False
        for single_call in mock_send_high_risk.call_args_list:
            args, kwargs = single_call
            if args[0] == self.student4.name and args[1] == self.student4.father_phone:
                called_s4_high_risk = True
                break
        self.assertTrue(called_s4_high_risk, "High risk alert for Student4 not called.")

        # Student2 would also be marked absent and is high risk.
        called_s2_high_risk = False
        for single_call in mock_send_high_risk.call_args_list:
            args, kwargs = single_call
            if args[0] == self.student2.name and args[1] == self.student2.father_phone:
                called_s2_high_risk = True
                break
        self.assertTrue(called_s2_high_risk, "High risk alert for Student2 not called.")
```
