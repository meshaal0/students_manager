import os
import django
import sys
from datetime import timedelta, date
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler, OneHotEncoder
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, confusion_matrix
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
import joblib

# Add the project root to the Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'school_management.settings') # Replace 'school_management' with your project's name
django.setup()

from students.models import Students, Attendance, Payment, Basics # noqa E402

# --- Configuration ---
CHURN_DEFINITION_NO_ATTENDANCE_DAYS = 30
MODEL_FILENAME = 'churn_model.joblib'
FEATURE_LIST_NUMERIC = [
    'days_since_last_attendance', 
    'attendance_rate_last_30_days',
    'consecutive_absences_current_month',
    'total_absences_current_month',
    'payment_history_ratio', # Calculated as months_paid / months_enrolled
]
FEATURE_LIST_CATEGORICAL = [
    'payment_status_current_month', # 0 for unpaid, 1 for paid
    'free_trial_used_and_not_converted' # Boolean -> 0 or 1
]


# --- 1. Churn Definition ---
def define_churn(student, today):
    """
    Defines if a student has churned.
    Churned if:
    - No attendance in the last CHURN_DEFINITION_NO_ATTENDANCE_DAYS days.
    - No payment for the current month.
    - Must have had some activity before this period (e.g., first attendance > CHURN_DEFINITION_NO_ATTENDANCE_DAYS ago)
    """
    last_30_days_start = today - timedelta(days=CHURN_DEFINITION_NO_ATTENDANCE_DAYS)
    current_month_start = today.replace(day=1)

    # Check for any attendance in the last 30 days
    recent_attendance = Attendance.objects.filter(
        student=student,
        attendance_date__gte=last_30_days_start,
        is_present=True # Or is_absent=False, depending on model
    ).exists()

    # Check for payment in the current month
    current_month_payment = Payment.objects.filter(
        student=student,
        month__year=current_month_start.year, # Assuming 'month' is a DateField like 'YYYY-MM-01'
        month__month=current_month_start.month
    ).exists()
    
    # Ensure student was active before the churn period
    first_attendance = Attendance.objects.filter(student=student, is_present=True).order_by('attendance_date').first()
    if not first_attendance or first_attendance.attendance_date >= last_30_days_start :
        return False # Not considered churn if they are new or became inactive before our observation window

    if not recent_attendance and not current_month_payment:
        return True
    return False

# --- 2. Feature Engineering Functions ---
def get_days_since_last_attendance(student, today):
    last_attendance = Attendance.objects.filter(student=student, is_present=True).order_by('-attendance_date').first()
    if last_attendance:
        return (today - last_attendance.attendance_date).days
    return 365 # A large number if no attendance ever

def get_attendance_rate_last_30_days(student, today):
    start_date = today - timedelta(days=30)
    # School days in last 30 days - approximation: count distinct days with any attendance record
    # This is a simplification. A more robust system would have a calendar of school days.
    school_days_in_period = Attendance.objects.filter(
        attendance_date__gte=start_date, 
        attendance_date__lte=today
    ).values('attendance_date').distinct().count()
    
    if school_days_in_period == 0:
        return 0 # Avoid division by zero; or could be 100 if student also had no attendance (no expectation)

    present_days = Attendance.objects.filter(
        student=student, 
        attendance_date__gte=start_date, 
        attendance_date__lte=today, 
        is_present=True
    ).count()
    
    return (present_days / school_days_in_period) * 100 if school_days_in_period > 0 else 0


def get_consecutive_absences_current_month(student, today):
    current_month_start = today.replace(day=1)
    absences = Attendance.objects.filter(
        student=student, 
        attendance_date__gte=current_month_start,
        attendance_date__lte=today, # up to today
        is_absent=True
    ).order_by('-attendance_date')

    consecutive_count = 0
    # Iterate backwards from today (or last absence date)
    # This is a simplified version. True consecutive count needs to check day by day.
    # For instance, if today is the 5th, and absent on 5th, 4th, but present on 3rd, it's 2.
    # A more accurate way:
    # Get all attendance for student this month. Iterate day by day from today backwards.
    # For now, we count consecutive from the most RECENT absence streak.
    
    # Simplified: count consecutive absences leading up to 'today' or the last recorded absence day
    # This might not be fully accurate if attendance isn't marked daily for all students.
    # Let's count from today backwards.
    current_day_check = today
    while current_day_check >= current_month_start:
        is_absent_on_day = Attendance.objects.filter(
            student=student, 
            attendance_date=current_day_check, 
            is_absent=True
        ).exists()
        is_present_on_day = Attendance.objects.filter(
            student=student, 
            attendance_date=current_day_check, 
            is_present=True
        ).exists()

        if is_absent_on_day:
            consecutive_count += 1
        elif is_present_on_day: # If present, the streak is broken
            break 
        # If neither (no record), we might assume school wasn't open or data missing.
        # For simplicity, if no record, assume not absent for consecutive counting from today.
        # This means streak breaks if a day has no record.
        elif not is_absent_on_day and not is_present_on_day:
             # If we want to count only based on marked absences, and ignore days with no marks:
             # This means if student was absent Mon, Tue, no record Wed, absent Thu, Fri -> this func would give 2 (Thu,Fri)
             # This depends on how strictly 'consecutive' should be interpreted with missing data.
             # For now, let's assume a non-record day breaks the consecutive chain from 'today'.
            break


        if current_day_check == current_month_start: # Stop at the beginning of the month
            break
        current_day_check -= timedelta(days=1)
        
    return consecutive_count


def get_total_absences_current_month(student, today):
    current_month_start = today.replace(day=1)
    return Attendance.objects.filter(
        student=student, 
        attendance_date__gte=current_month_start, 
        attendance_date__lte=today,
        is_absent=True
    ).count()


def get_payment_status_current_month(student, today):
    current_month_start = today.replace(day=1)
    return 1 if Payment.objects.filter(
        student=student, 
        month__year=current_month_start.year,
        month__month=current_month_start.month
    ).exists() else 0


def get_payment_history_ratio(student, today):
    first_record_date = None
    first_attendance = Attendance.objects.filter(student=student).order_by('attendance_date').first()
    first_payment = Payment.objects.filter(student=student).order_by('month').first()

    if first_attendance:
        first_record_date = first_attendance.attendance_date
    if first_payment:
        payment_start_date = first_payment.month # Assuming month is 'YYYY-MM-01'
        if first_record_date is None or payment_start_date < first_record_date:
            first_record_date = payment_start_date
            
    if not first_record_date:
        return 0 # No history

    # Calculate months enrolled (approximate)
    months_enrolled = (today.year - first_record_date.year) * 12 + (today.month - first_record_date.month) + 1
    if months_enrolled <= 0: months_enrolled = 1 # At least one month

    # Count unique months paid
    paid_months_count = Payment.objects.filter(student=student).values('month').distinct().count()
    
    return paid_months_count / months_enrolled if months_enrolled > 0 else 0


def get_free_trial_used_and_not_converted(student, today):
    # Student used free trials if free_tries is 0 (or less than initial if that's tracked)
    # And no payment for the current month (or month immediately after trial ended if that's better)
    basics = Basics.objects.first()
    initial_free_tries = basics.free_tries if basics else 3 # Fallback

    used_free_tries = student.free_tries < initial_free_tries # More robust: check if free_tries ever decreased
    
    # For simplicity: if free_tries is 0 and no current month payment
    if student.free_tries == 0:
        if not get_payment_status_current_month(student, today):
            return 1 # True: Used trials and not paid this month
    return 0 # False


# --- 3. Load Data and Create Dataset ---
def create_dataset():
    today = date.today()
    students = Students.objects.filter(is_active=True) # Consider only active students for churn prediction
    
    features_list = []
    churn_labels = []

    print(f"Processing {students.count()} students...")
    for student in students:
        # Define churn label
        is_churned = define_churn(student, today)
        
        # Calculate features
        student_features = {
            'days_since_last_attendance': get_days_since_last_attendance(student, today),
            'attendance_rate_last_30_days': get_attendance_rate_last_30_days(student, today),
            'consecutive_absences_current_month': get_consecutive_absences_current_month(student, today),
            'total_absences_current_month': get_total_absences_current_month(student, today),
            'payment_status_current_month': get_payment_status_current_month(student, today),
            'payment_history_ratio': get_payment_history_ratio(student, today),
            'free_trial_used_and_not_converted': get_free_trial_used_and_not_converted(student, today),
            # Add other features here
        }
        features_list.append(student_features)
        churn_labels.append(1 if is_churned else 0)

    df = pd.DataFrame(features_list)
    df['churn'] = churn_labels
    
    print(f"Dataset created with {len(df)} records.")
    print(f"Churn distribution:\n{df['churn'].value_counts(normalize=True)}")
    
    return df

# --- 4. Data Preprocessing and Model Training ---
def train_model(df):
    if df.empty or 'churn' not in df.columns or len(df.columns) == 1:
        print("DataFrame is empty or lacks features/target. Skipping training.")
        return None, None

    X = df.drop('churn', axis=1)
    y = df['churn']

    if X.empty:
        print("Feature set X is empty. Skipping training.")
        return None, None
        
    # Identify numeric and categorical features from the dataframe columns
    # This is safer if some features ended up not being calculated or added
    actual_numeric_features = [col for col in FEATURE_LIST_NUMERIC if col in X.columns]
    actual_categorical_features = [col for col in FEATURE_LIST_CATEGORICAL if col in X.columns]

    # Preprocessing pipelines
    numeric_transformer = Pipeline(steps=[
        ('imputer', SimpleImputer(strategy='median')), # Fill missing numeric values with median
        ('scaler', StandardScaler())
    ])

    categorical_transformer = Pipeline(steps=[
        ('imputer', SimpleImputer(strategy='most_frequent')), # Fill missing categorical values with most frequent
        ('onehot', OneHotEncoder(handle_unknown='ignore')) # Convert categorical to numeric
    ])

    # Create a column transformer
    preprocessor = ColumnTransformer(
        transformers=[
            ('num', numeric_transformer, actual_numeric_features),
            ('cat', categorical_transformer, actual_categorical_features)
        ], 
        remainder='passthrough' # Keep other columns (if any) - though ideally all are handled
    )

    # Full pipeline with preprocessing and model
    model_pipeline = Pipeline(steps=[
        ('preprocessor', preprocessor),
        ('classifier', LogisticRegression(solver='liblinear', random_state=42, class_weight='balanced')) # class_weight for imbalanced data
    ])

    # Split data
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y if sum(y) > 1 else None)

    if X_train.empty:
        print("X_train is empty after split. Cannot train model.")
        return None, None

    # Train the model
    model_pipeline.fit(X_train, y_train)
    
    # --- 5. Model Evaluation ---
    y_pred_test = model_pipeline.predict(X_test)
    
    print("\nModel Evaluation on Test Set:")
    print(f"Accuracy: {accuracy_score(y_test, y_pred_test):.4f}")
    print(f"Precision: {precision_score(y_test, y_pred_test, zero_division=0):.4f}")
    print(f"Recall: {recall_score(y_test, y_pred_test, zero_division=0):.4f}")
    print(f"F1-score: {f1_score(y_test, y_pred_test, zero_division=0):.4f}")
    print("Confusion Matrix:\n", confusion_matrix(y_test, y_pred_test))
    
    return model_pipeline, (X_test, y_test)


# --- Main Execution ---
if __name__ == '__main__':
    print("Starting churn model training script...")
    dataset_df = create_dataset()
    
    if dataset_df.empty or dataset_df.shape[0] < 10: # Minimum samples to train
        print("Not enough data to train a meaningful model.")
    else:
        trained_model, eval_data = train_model(dataset_df)
        
        if trained_model:
            # --- 6. Save the Model ---
            model_path = os.path.join(os.path.dirname(__file__), MODEL_FILENAME)
            try:
                joblib.dump(trained_model, model_path)
                print(f"\nTrained model saved to {model_path}")
            except Exception as e:
                print(f"Error saving model: {e}")
        else:
            print("Model training failed or was skipped.")
    print("\nChurn model training script finished.")

# Example usage (if you want to run this script directly):
# Ensure your Django project is in PYTHONPATH
# cd to the directory containing this script
# python train_churn_model.py
```
