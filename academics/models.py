from decimal import Decimal
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone

from .grading import calculate_outcome, marks_rules


def generate_receipt_number():
    return uuid.uuid4().hex.upper()


def maximum_validator(setting_name, message):
    return [
        MinValueValidator(Decimal('0'), message='Marks cannot be negative.'),
        MaxValueValidator(
            Decimal(str(marks_rules()[setting_name])),
            message=message,
        ),
    ]


class ExaminationMark(models.Model):
    class Result(models.TextChoices):
        PASS = 'PASS', 'Pass'
        FAIL = 'FAIL', 'Fail'

    student = models.ForeignKey(
        'students.Student',
        on_delete=models.PROTECT,
        related_name='examination_marks',
    )
    subject_code = models.CharField(max_length=20)
    subject_name = models.CharField(max_length=120)
    semester = models.PositiveSmallIntegerField(
        choices=[(number, f'Semester {number}') for number in range(1, 13)],
    )
    internal_marks = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        validators=maximum_validator('internal_max', 'Internal marks cannot exceed the configured maximum.'),
    )
    external_marks = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        validators=maximum_validator('external_max', 'External marks cannot exceed the configured maximum.'),
    )
    total_marks = models.DecimalField(max_digits=6, decimal_places=2, editable=False, blank=True)
    percentage = models.DecimalField(max_digits=5, decimal_places=2, editable=False, blank=True)
    grade = models.CharField(max_length=2, editable=False, blank=True)
    result = models.CharField(max_length=4, choices=Result.choices, editable=False, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at', 'student__roll_number', 'subject_code']
        constraints = [
            models.UniqueConstraint(
                fields=['student', 'subject_code', 'semester'],
                name='unique_student_subject_semester_mark',
                violation_error_message='Marks already exist for this student, subject code, and semester.',
            ),
            models.CheckConstraint(
                condition=models.Q(internal_marks__gte=0)
                & models.Q(external_marks__gte=0),
                name='marks_must_be_nonnegative',
            ),
        ]

    def clean(self):
        super().clean()
        rules = marks_rules()
        errors = {}
        if self.internal_marks is not None:
            if self.internal_marks < 0:
                errors['internal_marks'] = 'Internal marks cannot be negative.'
            elif self.internal_marks > Decimal(str(rules['internal_max'])):
                errors['internal_marks'] = (
                    f'Internal marks cannot exceed {rules["internal_max"]}.'
                )
        if self.external_marks is not None:
            if self.external_marks < 0:
                errors['external_marks'] = 'External marks cannot be negative.'
            elif self.external_marks > Decimal(str(rules['external_max'])):
                errors['external_marks'] = (
                    f'External marks cannot exceed {rules["external_max"]}.'
                )
        if self.semester is not None and self.semester not in range(1, 13):
            errors['semester'] = 'Choose a semester from 1 to 12.'
        if errors:
            raise ValidationError(errors)

        if self.internal_marks is not None and self.external_marks is not None:
            outcome = calculate_outcome(self.internal_marks, self.external_marks)
            self.total_marks = outcome['total_marks']
            self.percentage = outcome['percentage']
            self.grade = outcome['grade']
            self.result = outcome['result']

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.student} · {self.subject_code} · Semester {self.semester}'


class Semester(models.Model):
    academic_year = models.CharField(max_length=20, db_index=True)
    number = models.PositiveSmallIntegerField(
        choices=[(number, f'Semester {number}') for number in range(1, 13)]
    )
    starts_on = models.DateField()
    ends_on = models.DateField()
    is_active = models.BooleanField(default=False)

    class Meta:
        ordering = ['-academic_year', 'number']
        constraints = [
            models.UniqueConstraint(
                fields=['academic_year', 'number'],
                name='unique_academic_year_semester',
            ),
            models.CheckConstraint(
                condition=Q(ends_on__gte=models.F('starts_on')),
                name='semester_end_on_or_after_start',
            ),
        ]

    def clean(self):
        super().clean()
        if self.starts_on and self.ends_on and self.ends_on < self.starts_on:
            raise ValidationError({'ends_on': 'Semester end date must be on or after its start date.'})

    def __str__(self):
        return f'{self.academic_year} · Semester {self.number}'


class Course(models.Model):
    code = models.CharField(max_length=20, unique=True, db_index=True)
    name = models.CharField(max_length=120)
    department = models.CharField(max_length=100, db_index=True)
    credits = models.PositiveSmallIntegerField(default=3)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ['department', 'code']
        indexes = [models.Index(fields=['department', 'is_active'])]

    def clean(self):
        super().clean()
        self.code = self.code.strip().upper()
        self.name = ' '.join(self.name.split())
        self.department = ' '.join(self.department.split())
        if not self.department:
            raise ValidationError({'department': 'Enter a department for this course.'})

    def __str__(self):
        return f'{self.code} — {self.name}'


class CourseEnrollment(models.Model):
    student = models.ForeignKey(
        'students.Student',
        on_delete=models.PROTECT,
        related_name='course_enrollments',
    )
    course = models.ForeignKey(
        Course,
        on_delete=models.PROTECT,
        related_name='enrollments',
    )
    semester = models.ForeignKey(
        Semester,
        on_delete=models.PROTECT,
        related_name='enrollments',
    )
    enrolled_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['course__code', 'student__roll_number']
        constraints = [
            models.UniqueConstraint(
                fields=['student', 'course', 'semester'],
                name='unique_student_course_semester',
            ),
        ]
        indexes = [
            models.Index(fields=['student', 'semester']),
            models.Index(fields=['course', 'semester']),
        ]

    def clean(self):
        super().clean()
        if self.student_id and self.course_id and (
            self.student.department.casefold() != self.course.department.casefold()
        ):
            raise ValidationError(
                {'course': 'A student can only enroll in a course from their department.'}
            )

    def __str__(self):
        return f'{self.student.roll_number} · {self.course.code} · {self.semester}'


class ClassSession(models.Model):
    course = models.ForeignKey(
        Course,
        on_delete=models.PROTECT,
        related_name='class_sessions',
    )
    semester = models.ForeignKey(
        Semester,
        on_delete=models.PROTECT,
        related_name='class_sessions',
    )
    faculty = models.ForeignKey(
        'accounts.UserProfile',
        on_delete=models.PROTECT,
        related_name='class_sessions',
    )
    room = models.CharField(max_length=60, db_index=True)
    starts_at = models.DateTimeField(db_index=True)
    ends_at = models.DateTimeField()

    class Meta:
        ordering = ['starts_at', 'room']
        indexes = [models.Index(fields=['room', 'starts_at', 'ends_at'])]

    def clean(self):
        super().clean()
        errors = {}
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            errors['ends_at'] = 'Class end time must be after its start time.'
        if self.course_id and self.faculty_id:
            if self.faculty.role not in ('FACULTY', 'HOD'):
                errors['faculty'] = 'Assign a faculty or department head account to this class.'
            elif self.faculty.department.casefold() != self.course.department.casefold():
                errors['faculty'] = 'The faculty member must belong to the course department.'
        if self.starts_at and self.ends_at and self.ends_at > self.starts_at:
            conflicts = ClassSession.objects.filter(
                starts_at__lt=self.ends_at,
                ends_at__gt=self.starts_at,
            )
            if self.pk:
                conflicts = conflicts.exclude(pk=self.pk)
            if self.room.strip() and conflicts.filter(room__iexact=self.room.strip()).exists():
                errors['room'] = 'This room is already booked during the selected time.'
            if self.faculty_id and conflicts.filter(faculty_id=self.faculty_id).exists():
                errors['faculty'] = 'This faculty member already has a class during the selected time.'
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f'{self.course.code} · {self.starts_at:%Y-%m-%d %H:%M}'


class AttendanceRecord(models.Model):
    class Status(models.TextChoices):
        PRESENT = 'PRESENT', 'Present'
        ABSENT = 'ABSENT', 'Absent'
        EXCUSED = 'EXCUSED', 'Excused'

    session = models.ForeignKey(
        ClassSession,
        on_delete=models.CASCADE,
        related_name='attendance_records',
    )
    student = models.ForeignKey(
        'students.Student',
        on_delete=models.PROTECT,
        related_name='attendance_records',
    )
    status = models.CharField(
        max_length=8,
        choices=Status.choices,
        default=Status.PRESENT,
        db_index=True,
    )
    marked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='marked_attendance',
    )
    marked_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['student__roll_number']
        constraints = [
            models.UniqueConstraint(
                fields=['session', 'student'],
                name='unique_student_session_attendance',
            ),
        ]
        indexes = [
            models.Index(fields=['student', 'status']),
            models.Index(fields=['session', 'status']),
        ]

    def clean(self):
        super().clean()
        if self.session_id and self.student_id:
            if self.session.course.department.casefold() != self.student.department.casefold():
                raise ValidationError(
                    {'student': 'Attendance can only be recorded for students in the course department.'}
                )
            enrolled = CourseEnrollment.objects.filter(
                student_id=self.student_id,
                course_id=self.session.course_id,
                semester_id=self.session.semester_id,
            ).exists()
            if not enrolled:
                raise ValidationError(
                    {'student': 'The student must be enrolled in this course and semester.'}
                )

    def __str__(self):
        return f'{self.student.roll_number} · {self.session.course.code} · {self.get_status_display()}'


class FeeInvoice(models.Model):
    class FeeType(models.TextChoices):
        TUITION = 'TUITION', 'Tuition'
        EXAMINATION = 'EXAMINATION', 'Examination'
        HOSTEL = 'HOSTEL', 'Hostel'
        OTHER = 'OTHER', 'Other'

    receipt_number = models.CharField(
        max_length=36,
        unique=True,
        default=generate_receipt_number,
        editable=False,
    )
    student = models.ForeignKey(
        'students.Student',
        on_delete=models.PROTECT,
        related_name='fee_invoices',
    )
    fee_type = models.CharField(max_length=16, choices=FeeType.choices, db_index=True)
    academic_year = models.CharField(max_length=20, db_index=True)
    amount_due = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
    )
    due_date = models.DateField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['due_date', 'student__roll_number']
        indexes = [models.Index(fields=['student', 'due_date'])]
        permissions = [
            ('manage_fee_records', 'Can create and update college fee records'),
        ]

    @property
    def amount_paid(self):
        prefetched = getattr(self, '_prefetched_objects_cache', {})
        if 'payments' in prefetched:
            return sum((payment.amount for payment in prefetched['payments']), Decimal('0.00'))
        return self.payments.aggregate(total=models.Sum('amount'))['total'] or Decimal('0.00')

    @property
    def balance(self):
        return max(self.amount_due - self.amount_paid, Decimal('0.00'))

    @property
    def status(self):
        if self.balance == 0:
            return 'PAID'
        if self.amount_paid:
            return 'PARTIAL'
        if self.due_date < timezone.localdate():
            return 'OVERDUE'
        return 'PENDING'

    def clean(self):
        super().clean()
        if self.amount_due is not None and self.amount_due <= 0:
            raise ValidationError({'amount_due': 'Invoice amount must be greater than zero.'})

    def __str__(self):
        return f'{self.receipt_number} · {self.student.roll_number}'


class FeePayment(models.Model):
    invoice = models.ForeignKey(
        FeeInvoice,
        on_delete=models.PROTECT,
        related_name='payments',
    )
    reference = models.CharField(max_length=80, unique=True)
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
    )
    paid_at = models.DateTimeField(default=timezone.now, db_index=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='recorded_fee_payments',
    )

    class Meta:
        ordering = ['-paid_at']
        permissions = [
            ('record_fee_payments', 'Can record college fee payments'),
        ]

    def clean(self):
        super().clean()
        if self.amount is None or self.amount <= 0:
            raise ValidationError({'amount': 'Payment amount must be greater than zero.'})
        if self.invoice_id:
            paid = self.invoice.amount_paid
            if self.pk:
                old_amount = FeePayment.objects.filter(pk=self.pk).values_list('amount', flat=True).first()
                if old_amount is not None:
                    paid -= old_amount
            if paid + self.amount > self.invoice.amount_due:
                raise ValidationError({'amount': 'Payment cannot exceed the outstanding invoice balance.'})

    def __str__(self):
        return f'{self.reference} · {self.amount}'


class CampusEvent(models.Model):
    class Kind(models.TextChoices):
        EXAM = 'EXAM', 'Examination'
        EVENT = 'EVENT', 'Campus event'

    title = models.CharField(max_length=160)
    kind = models.CharField(max_length=8, choices=Kind.choices, db_index=True)
    description = models.TextField(blank=True)
    starts_at = models.DateTimeField(db_index=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    department = models.CharField(max_length=100, blank=True, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_campus_events',
    )

    class Meta:
        ordering = ['starts_at']

    def clean(self):
        super().clean()
        if self.starts_at and self.ends_at and self.ends_at < self.starts_at:
            raise ValidationError({'ends_at': 'Event end must be on or after its start.'})

    def __str__(self):
        return self.title


class Announcement(models.Model):
    title = models.CharField(max_length=160)
    body = models.TextField()
    department = models.CharField(max_length=100, blank=True, db_index=True)
    academic_year = models.CharField(max_length=20, blank=True, db_index=True)
    student = models.ForeignKey(
        'students.Student',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='announcements',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_announcements',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    send_email = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at']

    def clean(self):
        super().clean()
        if self.student_id and self.department and (
            self.student.department.casefold() != self.department.casefold()
        ):
            raise ValidationError(
                {'department': 'An individual announcement’s department must match the selected student.'}
            )
        if self.student_id and self.academic_year and (
            self.student.academic_year != self.academic_year
        ):
            raise ValidationError(
                {'academic_year': 'An individual announcement’s academic year must match the selected student.'}
            )

    def __str__(self):
        return self.title
