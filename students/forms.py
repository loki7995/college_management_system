from django import forms
from django.utils import timezone

from .models import Student, StudentDocument


class StudentForm(forms.ModelForm):
    class Meta:
        model = Student
        fields = [
            'roll_number',
            'full_name',
            'email',
            'phone_number',
            'department',
            'academic_year',
            'date_of_birth',
            'address',
        ]
        error_messages = {
            'roll_number': {'required': 'Enter the student’s roll number.'},
            'full_name': {'required': 'Enter the student’s full name.'},
            'email': {
                'required': 'Enter an email address.',
                'invalid': 'Enter a valid email address.',
            },
            'department': {'required': 'Enter the student’s department.'},
            'academic_year': {'required': 'Enter the academic year.'},
        }
        widgets = {
            'roll_number': forms.TextInput(attrs={'placeholder': 'e.g. STU-2026-001'}),
            'full_name': forms.TextInput(attrs={'placeholder': 'e.g. Alex Morgan'}),
            'email': forms.EmailInput(attrs={'placeholder': 'name@college.edu'}),
            'phone_number': forms.TextInput(attrs={'placeholder': '+1 555 010 0200'}),
            'department': forms.TextInput(attrs={'placeholder': 'e.g. Computer Science'}),
            'academic_year': forms.TextInput(attrs={'placeholder': 'e.g. 2026-2027'}),
            'date_of_birth': forms.DateInput(attrs={'type': 'date'}),
            'address': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Street, city, postal code'}),
        }

    def clean_roll_number(self):
        return self.cleaned_data['roll_number'].strip()

    def clean_full_name(self):
        full_name = ' '.join(self.cleaned_data['full_name'].split())
        if not full_name:
            raise forms.ValidationError('Enter the student’s full name.')
        return full_name

    def clean_email(self):
        return self.cleaned_data['email'].strip().lower()

    def clean_department(self):
        return self.cleaned_data['department'].strip()

    def clean_academic_year(self):
        return self.cleaned_data['academic_year'].strip()

    def clean_date_of_birth(self):
        date_of_birth = self.cleaned_data.get('date_of_birth')
        if date_of_birth and date_of_birth > timezone.localdate():
            raise forms.ValidationError('Date of birth cannot be in the future.')
        return date_of_birth


class StudentDocumentForm(forms.ModelForm):
    class Meta:
        model = StudentDocument
        fields = ('title', 'file')
        widgets = {'title': forms.TextInput(attrs={'placeholder': 'Document description'})}
