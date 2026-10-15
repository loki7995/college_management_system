from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class UserProfile(models.Model):
    class Role(models.TextChoices):
        ADMIN = 'ADMIN', 'Administrator'
        REGISTRAR = 'REGISTRAR', 'Registrar / Academic Admin'
        HOD = 'HOD', 'Head of Department'
        FINANCE = 'FINANCE', 'Finance / Accounts Officer'
        FACULTY = 'FACULTY', 'Faculty'
        STUDENT = 'STUDENT', 'Student'

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='role_profile',
    )
    role = models.CharField(max_length=10, choices=Role.choices)
    department = models.CharField(max_length=100, blank=True)
    student = models.OneToOneField(
        'students.Student',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='user_profile',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['user__username']

    def clean(self):
        super().clean()
        self.department = self.department.strip()
        errors = {}
        if self.role in (self.Role.FACULTY, self.Role.HOD):
            if not self.department:
                errors['department'] = 'Select the staff member’s department.'
            if self.student_id:
                errors['student'] = 'Staff profiles cannot be linked to a student record.'
        elif self.role == self.Role.STUDENT:
            if not self.student_id:
                errors['student'] = 'Link the student account to its student record.'
            if self.department:
                errors['department'] = 'Student department is taken from the linked student record.'
        elif self.role == self.Role.ADMIN:
            if self.student_id:
                errors['student'] = 'Administrator profiles cannot be linked to a student record.'
            if self.department:
                errors['department'] = 'Administrator profiles do not have a department scope.'
        elif self.role in (self.Role.REGISTRAR, self.Role.FINANCE):
            if self.student_id:
                errors['student'] = 'Staff profiles cannot be linked to a student record.'
            if self.department:
                errors['department'] = 'This role has college-wide access and no department scope.'
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.user.get_username()} — {self.get_role_display()}'


class AuditEntry(models.Model):
    class Action(models.TextChoices):
        CREATE = 'CREATE', 'Create'
        UPDATE = 'UPDATE', 'Update'
        DELETE = 'DELETE', 'Delete'

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_entries',
    )
    action = models.CharField(max_length=8, choices=Action.choices, db_index=True)
    object_type = models.CharField(max_length=120, db_index=True)
    object_id = models.CharField(max_length=80, db_index=True)
    object_repr = models.CharField(max_length=255)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    before = models.JSONField(null=True, blank=True)
    after = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['object_type', 'object_id', '-created_at'])]

    def __str__(self):
        return f'{self.get_action_display()} {self.object_type} {self.object_id}'


class LoginAttempt(models.Model):
    identifier_hash = models.CharField(max_length=64)
    ip_address = models.GenericIPAddressField()
    failures = models.PositiveSmallIntegerField(default=0)
    window_started_at = models.DateTimeField()
    locked_until = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['identifier_hash', 'ip_address'],
                name='unique_login_attempt_identifier_ip',
            ),
        ]
        indexes = [models.Index(fields=['locked_until', 'updated_at'])]
