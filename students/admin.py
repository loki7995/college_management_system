from django.contrib import admin

from accounts.admin_support import AuditedModelAdmin

from .models import Student, StudentDocument


class StudentDocumentInline(admin.TabularInline):
    model = StudentDocument
    extra = 0
    fields = ('title', 'file', 'uploaded_by', 'uploaded_at')
    readonly_fields = ('uploaded_at',)


@admin.register(Student)
class StudentAdmin(AuditedModelAdmin, admin.ModelAdmin):
    list_display = ('roll_number', 'full_name', 'email', 'department', 'academic_year', 'is_active')
    list_filter = ('department', 'academic_year', 'is_active')
    search_fields = ('roll_number', 'full_name', 'email')
    ordering = ('full_name',)
    list_per_page = 50
    inlines = (StudentDocumentInline,)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user_profile__user')


@admin.register(StudentDocument)
class StudentDocumentAdmin(AuditedModelAdmin, admin.ModelAdmin):
    list_display = ('title', 'student', 'uploaded_by', 'uploaded_at')
    search_fields = ('title', 'student__roll_number', 'student__full_name')
    list_select_related = ('student', 'uploaded_by')
    readonly_fields = ('uploaded_at',)
