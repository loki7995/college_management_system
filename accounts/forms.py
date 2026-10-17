from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Q

from students.departments import DEPARTMENT_CHOICES, department_choices

from .models import UserProfile


class FacultyAccountForm(forms.Form):
    username = forms.CharField(
        max_length=150,
        help_text='Used by the faculty member to sign in.',
    )
    first_name = forms.CharField(max_length=150, required=False)
    last_name = forms.CharField(max_length=150, required=False)
    email = forms.EmailField()
    department = forms.ChoiceField(
        choices=DEPARTMENT_CHOICES,
        error_messages={'required': 'Select the faculty member’s department.'},
    )
    is_active = forms.BooleanField(required=False, initial=True)

    def __init__(self, *args, profile=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.profile = profile
        self.fields['department'].choices = department_choices(
            profile.department if profile is not None else ''
        )
        if profile is not None:
            self.initial.update(
                {
                    'username': profile.user.get_username(),
                    'first_name': profile.user.first_name,
                    'last_name': profile.user.last_name,
                    'email': profile.user.email,
                    'department': profile.department,
                    'is_active': profile.user.is_active,
                }
            )
            self.fields['username'].disabled = True

    def clean_username(self):
        username = self.cleaned_data['username'].strip()
        users = get_user_model().objects.filter(username__iexact=username)
        if self.profile is not None:
            users = users.exclude(pk=self.profile.user_id)
        if users.exists():
            raise forms.ValidationError('An account with this username already exists.')
        return username

    def clean_email(self):
        email = self.cleaned_data['email'].strip()
        users = get_user_model().objects.filter(email__iexact=email)
        if self.profile is not None:
            users = users.exclude(pk=self.profile.user_id)
        if users.exists():
            raise forms.ValidationError('An account with this email address already exists.')
        return email

    def clean_department(self):
        return self.cleaned_data['department']

    def save(self):
        if self.profile is None:
            raise ValueError('Use create_account() to create a faculty profile.')
        user = self.profile.user
        user.first_name = self.cleaned_data['first_name'].strip()
        user.last_name = self.cleaned_data['last_name'].strip()
        user.email = self.cleaned_data['email']
        user.is_active = self.cleaned_data['is_active']
        user.save(
            update_fields=[
                'first_name',
                'last_name',
                'email',
                'is_active',
            ]
        )
        self.profile.department = self.cleaned_data['department']
        self.profile.save(update_fields=['department', 'updated_at'])
        return self.profile

    def create_account(self):
        if self.profile is not None:
            raise ValueError('This form is already editing an existing faculty profile.')
        if not self.is_valid():
            raise ValueError('Cannot create an account from an invalid form.')
        user_model = get_user_model()
        user = user_model(
            username=self.cleaned_data['username'],
            first_name=self.cleaned_data['first_name'].strip(),
            last_name=self.cleaned_data['last_name'].strip(),
            email=self.cleaned_data['email'],
            is_active=self.cleaned_data['is_active'],
            is_staff=False,
            is_superuser=False,
        )
        user.set_password(None)
        user.save()
        return UserProfile.objects.create(
            user=user,
            role=UserProfile.Role.FACULTY,
            department=self.cleaned_data['department'],
        )


class StudentAccountForm(forms.Form):
    username = forms.CharField(
        max_length=150,
        help_text='Defaults to the student roll number; you can change it.',
    )
    email = forms.EmailField(disabled=True)

    def __init__(self, *args, student, **kwargs):
        super().__init__(*args, **kwargs)
        self.student = student
        self.fields['email'].initial = student.email
        self.fields['username'].initial = student.roll_number

    def clean_username(self):
        username = self.cleaned_data['username'].strip()
        if get_user_model().objects.filter(username__iexact=username).exists():
            raise forms.ValidationError('An account with this username already exists.')
        return username

    def clean(self):
        cleaned_data = super().clean()
        if hasattr(self.student, 'user_profile'):
            raise forms.ValidationError(
                'This student is already linked to a login account.'
            )
        email_users = get_user_model().objects.filter(
            Q(email__iexact=self.student.email)
        )
        if email_users.exists():
            self.add_error(
                None,
                'A login account already uses this student email address. Review User Accounts before proceeding.',
            )
        return cleaned_data

    def create_account(self):
        if not self.is_valid():
            raise ValueError('Cannot create an account from an invalid form.')
        user_model = get_user_model()
        user = user_model(
            username=self.cleaned_data['username'],
            first_name=self.student.full_name,
            email=self.student.email,
            is_active=self.student.is_active,
            is_staff=False,
            is_superuser=False,
        )
        user.set_password(None)
        user.save()
        return UserProfile.objects.create(
            user=user,
            role=UserProfile.Role.STUDENT,
            student=self.student,
        )
