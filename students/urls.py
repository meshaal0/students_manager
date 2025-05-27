from django.urls import path
from . import views
urlpatterns = [
     path('', views.home_view, name='home'),
    # path('', ),
    path('print-barcode/<int:student_id>/', views.print_barcode, name='print_barcode'),
    path('download-barcodes/', views.download_barcodes_pdf, name='download_barcodes'),
    path('attendance/', views.barcode_attendance_view, name='barcode_attendance'),
    path('mark-absentees/', views.mark_absentees_view, name='mark_absentees'),
    # path('dashboard/', views.daily_dashboard_view, name='daily_dashboard'), # Added
    # path('historical-insights/', views.historical_insights_view, name='historical_insights'), # Added
    # path('broadcast/', views.broadcast_message_view, name='broadcast_message'),
    path('income/', views.income_report_view, name='income_report'),
]
