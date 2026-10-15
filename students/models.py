from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone


phone_validator = RegexValidator(
    regex=r'^[0-9+().\-\s]{7,25}$',
    message='Enter a phone number with 7–25 digits or standard phone symbols.',
)


class Student(models.Model):
    roll_number = models.CharField(
        'Roll number',
        max_length=30,
        unique=True,
        error_messages={'unique': 'A student with this roll number already exists.'},
    )
    full_name = models.CharField('Full name', max_length=150)
    email = models.EmailField(
        unique=True,
        error_messages={'unique': 'A student with this email address already exists.'},
    )
    phone_number = models.CharField(
        'Phone number',
        max_length=25,
        blank=True,
        validators=[phone_validator],
    )
    department = models.CharField(max_length=100, db_index=True)
    academic_year = models.CharField(
        'Academic year',
        max_length=20,
        db_index=True,
        help_text='For example, 2026-2027.',
    )
    is_active = models.BooleanField('Active', default=True, db_index=True)
    date_of_birth = models.DateField('Date of birth', null=True, blank=True)
    address = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['full_name', 'roll_number']

    def clean(self):
        super().clean()
        if self.date_of_birth and self.date_of_birth > timezone.localdate():
            raise ValidationError({'date_of_birth': 'Date of birth cannot be in the future.'})

    def __str__(self):
        return f'{self.full_name} ({self.roll_number})'


def validate_student_document(upload):
    import os

    extension = os.path.splitext(upload.name)[1].lower()
    if extension not in {'.pdf', '.jpg', '.jpeg', '.png'}:
        raise ValidationError('Upload a PDF, JPG, or PNG file.')
    if upload.size > 5 * 1024 * 1024:
        raise ValidationError('Documents must be 5 MB or smaller.')

    header = upload.read(16)
    upload.seek(0)
    valid_signatures = {
        '.pdf': header.startswith(b'%PDF-'),
        '.jpg': header.startswith(b'\xff\xd8\xff'),
        '.jpeg': header.startswith(b'\xff\xd8\xff'),
        '.png': header.startswith(b'\x89PNG\r\n\x1a\n'),
    }
    if not valid_signatures[extension]:
        raise ValidationError('The file content does not match its extension.')


class StudentDocument(models.Model):
    student = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        related_name='documents',
    )
    title = models.CharField(max_length=120)
    file = models.FileField(
        upload_to='student-documents/%Y/%m/',
        validators=[validate_student_document],
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='uploaded_student_documents',
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-uploaded_at', 'title']

    def __str__(self):
        return f'{self.student.roll_number} — {self.title}'
