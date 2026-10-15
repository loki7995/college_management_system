from django.contrib import admin

from accounts.admin_support import AuditedModelAdmin

from .models import (
    Announcement,
    AttendanceRecord,
    CampusEvent,
    ClassSession,
    Course,
    CourseEnrollment,
    ExaminationMark,
    FeeInvoice,
    FeePayment,
    Semester,
)

@admin.register(ExaminationMark)
class ExaminationMarkAdmin(AuditedModelAdmin, admin.ModelAdmin):
    list_display = (
        'student',
        'subject_code',
        'subject_name',
        'semester',
        'internal_marks',
        'external_marks',
        'total_marks',
        'grade',
        'result',
    )
    list_filter = ('semester', 'result')
    search_fields = (
        'student__roll_number',
        'student__full_name',
        'subject_code',
        'subject_name',
    )
    ordering = ('-created_at',)
    readonly_fields = ('total_marks', 'percentage', 'grade', 'result', 'created_at', 'updated_at')
    list_per_page = 50
    list_select_related = ('student',)

@admin.register(Semester)
class SemesterAdmin(AuditedModelAdmin, admin.ModelAdmin):
    list_display = ('academic_year', 'number', 'starts_on', 'ends_on', 'is_active')
    list_filter = ('academic_year', 'is_active')
    ordering = ('-academic_year', 'number')


@admin.register(Course)
class CourseAdmin(AuditedModelAdmin, admin.ModelAdmin):
    list_display = ('code', 'name', 'department', 'credits', 'is_active')
    list_filter = ('department', 'is_active')
    search_fields = ('code', 'name', 'department')
    ordering = ('department', 'code')


@admin.register(CourseEnrollment)
class CourseEnrollmentAdmin(AuditedModelAdmin, admin.ModelAdmin):
    list_display = ('student', 'course', 'semester', 'enrolled_at')
    list_filter = ('course__department', 'semester__academic_year', 'semester__number')
    search_fields = ('student__roll_number', 'student__full_name', 'course__code', 'course__name')
    list_select_related = ('student', 'course', 'semester')


@admin.register(ClassSession)
class ClassSessionAdmin(AuditedModelAdmin, admin.ModelAdmin):
    list_display = ('course', 'faculty', 'room', 'starts_at', 'ends_at')
    list_filter = ('course__department', 'semester', 'starts_at')
    search_fields = ('course__code', 'course__name', 'room', 'faculty__user__username')
    list_select_related = ('course', 'semester', 'faculty__user')


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(AuditedModelAdmin, admin.ModelAdmin):
    list_display = ('session', 'student', 'status', 'marked_by', 'marked_at')
    list_filter = ('status', 'session__course__department', 'session__semester')
    search_fields = ('student__roll_number', 'student__full_name', 'session__course__code')
    list_select_related = ('session__course', 'student', 'marked_by')


@admin.register(FeeInvoice)
class FeeInvoiceAdmin(AuditedModelAdmin, admin.ModelAdmin):
    list_display = ('receipt_number', 'student', 'fee_type', 'amount_due', 'amount_paid', 'balance', 'status', 'due_date')
    list_filter = ('fee_type', 'academic_year', 'due_date')
    search_fields = ('receipt_number', 'student__roll_number', 'student__full_name')
    list_select_related = ('student',)
    readonly_fields = ('receipt_number', 'created_at')
    list_per_page = 50

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('student').prefetch_related('payments')


@admin.register(FeePayment)
class FeePaymentAdmin(AuditedModelAdmin, admin.ModelAdmin):
    list_display = ('reference', 'invoice', 'amount', 'paid_at', 'recorded_by')
    search_fields = ('reference', 'invoice__receipt_number', 'invoice__student__roll_number')
    list_filter = ('paid_at',)
    list_select_related = ('invoice__student', 'recorded_by')


@admin.register(CampusEvent)
class CampusEventAdmin(AuditedModelAdmin, admin.ModelAdmin):
    list_display = ('title', 'kind', 'starts_at', 'ends_at', 'department')
    list_filter = ('kind', 'department', 'starts_at')
    search_fields = ('title', 'description', 'department')


@admin.register(Announcement)
class AnnouncementAdmin(AuditedModelAdmin, admin.ModelAdmin):
    list_display = ('title', 'department', 'academic_year', 'student', 'send_email', 'created_at')
    list_filter = ('department', 'academic_year', 'send_email', 'created_at')
    search_fields = ('title', 'body', 'student__roll_number', 'student__full_name')
    list_select_related = ('student', 'created_by')
