from django import forms

class BarcodeAttendanceForm(forms.Form):
    ACTION_CHOICES = [
        ('scan', 'Scan'),
        ('free', 'Free'),
        ('pay', 'Pay'),
        ('send_custom_message', 'Send Custom Message'),
    ]
    barcode = forms.CharField(max_length=5, min_length=5)
    action = forms.ChoiceField(choices=ACTION_CHOICES)
    payment_option = forms.ChoiceField(
        choices=[('monthly', 'شهري'), ('termly', 'فصلي')],
        required=False
    )
    custom_message_content = forms.CharField(widget=forms.Textarea, required=False)
    manual_target_barcode = forms.CharField(max_length=5, min_length=5, required=False)

    def clean(self):
        cleaned = super().clean()
        action = cleaned.get('action')
        if action == 'pay':
            if not cleaned.get('payment_option'):
                raise forms.ValidationError("يجب اختيار نوع الاشتراك.")
        if action == 'send_custom_message':
            content = cleaned.get('custom_message_content')
            if not content:
                raise forms.ValidationError("محتوى الرسالة مطلوب.")
            barcode = cleaned.get('manual_target_barcode') or cleaned.get('barcode')
            if not barcode:
                raise forms.ValidationError("الباركود مطلوب لإرسال الرسالة.")
        return cleaned