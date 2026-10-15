from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db.models import Q

from accounts.models import UserProfile
from accounts.permissions import get_user_role, visible_students, writable_students
from students.models import Student

from .models import (
    Announcement,
    CampusEvent,
    ClassSession,
    Course,
    CourseEnrollment,
    FeeInvoice,
    FeePayment,
    Semester,
    ExaminationMark,
)


class ExaminationMarkForm(forms.ModelForm):
    class Meta:
        model = ExaminationMark
        fields = [
            'student',
            'subject_code',
            'subject_name',
            'semester',
            'internal_marks',
            'external_marks',
        ]
        error_messages = {
            'student': {'required': 'Select a student for this examination record.'},
            'subject_code': {'required': 'Enter the subject code.'},
            'subject_name': {'required': 'Enter the subject name.'},
            'semester': {'required': 'Select the semester.'},
            'internal_marks': {'required': 'Enter the internal examination marks.'},
            'external_marks': {'required': 'Enter the external examination marks.'},
        }
        widgets = {
            'student': forms.Select(),
            'subject_code': forms.TextInput(attrs={'placeholder': 'e.g. CS201'}),
            'subject_name': forms.TextInput(attrs={'placeholder': 'e.g. Data Structures'}),
            'semester': forms.Select(),
            'internal_marks': forms.NumberInput(attrs={'min': '0', 'step': '0.01'}),
            'external_marks': forms.NumberInput(attrs={'min': '0', 'step': '0.01'}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        rules = settings.ACADEMIC_MARKS_RULES
        students = writable_students(user) if user is not None else Student.objects.filter(is_active=True)
        if self.instance.pk:
            if user is not None:
                students = visible_students(user).filter(
                    Q(is_active=True) | Q(pk=self.instance.student_id)
                )
            else:
                students = Student.objects.filter(
                    Q(is_active=True) | Q(pk=self.instance.student_id)
                )
        self.fields['student'].queryset = students.order_by('roll_number')
        self.fields['student'].label_from_instance = (
            lambda student: (
                f'{student.roll_number} — {student.full_name}'
                f'{" (inactive)" if not student.is_active else ""}'
            )
        )
        self.fields['student'].empty_label = 'Choose a student…'
        self.fields['internal_marks'].widget.attrs['max'] = str(rules['internal_max'])
        self.fields['internal_marks'].help_text = f'Out of {rules["internal_max"]}.'
        self.fields['external_marks'].widget.attrs['max'] = str(rules['external_max'])
        self.fields['external_marks'].help_text = f'Out of {rules["external_max"]}.'
        self.fields['semester'].empty_label = 'Choose a semester…'

    def clean_subject_code(self):
        return self.cleaned_data['subject_code'].strip().upper()

    def clean_subject_name(self):
        return ' '.join(self.cleaned_data['subject_name'].split())

    def clean(self):
        cleaned_data = super().clean()
        student = cleaned_data.get('student')
        subject_code = cleaned_data.get('subject_code')
        semester = cleaned_data.get('semester')
        if student and subject_code and semester:
            duplicate = ExaminationMark.objects.filter(
                student=student,
                subject_code=subject_code,
                semester=semester,
            )
            if self.instance.pk:
                duplicate = duplicate.exclude(pk=self.instance.pk)
            if duplicate.exists():
                self.add_error(
                    None,
                    'Marks already exist for this student, subject code, and semester.',
                )
        return cleaned_data


class CourseForm(forms.ModelForm):
    class Meta:
        model = Course
        fields = ('code', 'name', 'department', 'credits', 'is_active')
        widgets = {
            'code': forms.TextInput(attrs={'placeholder': 'e.g. CS201'}),
            'name': forms.TextInput(attrs={'placeholder': 'Course name'}),
            'department': forms.TextInput(attrs={'placeholder': 'Department'}),
        }


class CourseEnrollmentForm(forms.ModelForm):
    class Meta:
        model = CourseEnrollment
        fields = ('student', 'semester')

    def __init__(self, *args, course, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.course = course
        self.fields['student'].queryset = visible_students(user).filter(
            is_active=True,
            department__iexact=course.department,
        ).order_by('roll_number')
        self.fields['semester'].queryset = Semester.objects.filter(
            is_active=True
        ).order_by('-academic_year', 'number')
        self.fields['student'].label_from_instance = (
            lambda student: f'{student.roll_number} — {student.full_name}'
        )

    def save(self, commit=True):
        enrollment = super().save(commit=False)
        enrollment.course = self.course
        if commit:
            enrollment.full_clean()
            enrollment.save()
        return enrollment


class SemesterForm(forms.ModelForm):
    class Meta:
        model = Semester
        fields = ('academic_year', 'number', 'starts_on', 'ends_on', 'is_active')
        widgets = {
            'starts_on': forms.DateInput(attrs={'type': 'date'}),
            'ends_on': forms.DateInput(attrs={'type': 'date'}),
        }


class ClassSessionForm(forms.ModelForm):
    class Meta:
        model = ClassSession
        fields = ('course', 'semester', 'faculty', 'room', 'starts_at', 'ends_at')
        widgets = {
            'starts_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
            'ends_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        role = get_user_role(user) if user is not None else None
        courses = Course.objects.filter(is_active=True)
        if role in (UserProfile.Role.HOD, UserProfile.Role.FACULTY):
            courses = courses.filter(department=user.role_profile.department)
        self.fields['course'].queryset = courses.order_by('code')
        self.fields['semester'].queryset = Semester.objects.filter(is_active=True).order_by(
            '-academic_year', 'number'
        )
        faculty_profiles = UserProfile.objects.filter(
            role__in=(UserProfile.Role.FACULTY, UserProfile.Role.HOD),
            user__is_active=True,
        ).select_related('user')
        if role in (UserProfile.Role.HOD, UserProfile.Role.FACULTY):
            faculty_profiles = faculty_profiles.filter(
                department=user.role_profile.department
            )
        self.fields['faculty'].queryset = faculty_profiles.order_by('user__username')
        self.fields['faculty'].label_from_instance = (
            lambda profile: f'{profile.user.get_full_name() or profile.user.get_username()} · {profile.department}'
        )

    def clean(self):
        cleaned = super().clean()
        user = self.user
        if user is not None:
            role = get_user_role(user)
            course = cleaned.get('course')
            faculty = cleaned.get('faculty')
            if role in (UserProfile.Role.HOD, UserProfile.Role.FACULTY):
                department = user.role_profile.department.casefold()
                if course and course.department.casefold() != department:
                    self.add_error('course', 'You can only schedule courses in your department.')
                if faculty and faculty.department.casefold() != department:
                    self.add_error('faculty', 'You can only assign faculty in your department.')
        return cleaned


class FeeInvoiceForm(forms.ModelForm):
    class Meta:
        model = FeeInvoice
        fields = ('student', 'fee_type', 'academic_year', 'amount_due', 'due_date')
        widgets = {'due_date': forms.DateInput(attrs={'type': 'date'})}

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if get_user_role(user) == UserProfile.Role.FINANCE:
            students = Student.objects.filter(is_active=True)
        else:
            students = visible_students(user).filter(is_active=True)
        self.fields['student'].queryset = students.order_by('roll_number')
        self.fields['student'].label_from_instance = (
            lambda student: f'{student.roll_number} — {student.full_name}'
        )


class FeePaymentForm(forms.ModelForm):
    class Meta:
        model = FeePayment
        fields = ('reference', 'amount')

    def __init__(self, *args, invoice, **kwargs):
        super().__init__(*args, **kwargs)
        self.invoice = invoice

    def clean_amount(self):
        amount = self.cleaned_data['amount']
        if amount > self.invoice.balance:
            raise ValidationError('Payment cannot exceed the outstanding invoice balance.')
        return amount


class CampusEventForm(forms.ModelForm):
    class Meta:
        model = CampusEvent
        fields = ('title', 'kind', 'description', 'starts_at', 'ends_at', 'department')
        widgets = {
            'starts_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
            'ends_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        }


class AnnouncementForm(forms.ModelForm):
    class Meta:
        model = Announcement
        fields = ('title', 'body', 'department', 'academic_year', 'student', 'send_email')
        widgets = {'body': forms.Textarea(attrs={'rows': 5})}

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['student'].required = False
        self.fields['student'].queryset = visible_students(user).order_by('roll_number')
        self.fields['student'].label_from_instance = (
            lambda student: f'{student.roll_number} — {student.full_name}'
        )
