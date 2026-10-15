from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin

from .admin_support import AuditedModelAdmin
from .audit import capture_fields
from .models import AuditEntry, UserProfile


@admin.register(UserProfile)
class UserProfileAdmin(AuditedModelAdmin, admin.ModelAdmin):
    list_display = ('user', 'role', 'department', 'student')
    list_filter = ('role', 'department')
    search_fields = ('user__username', 'user__email', 'student__roll_number', 'student__full_name')
    autocomplete_fields = ('user', 'student')
    ordering = ('user__username',)

    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


@admin.register(AuditEntry)
class AuditEntryAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'actor', 'action', 'object_type', 'object_id', 'ip_address')
    list_filter = ('action', 'object_type', 'created_at')
    search_fields = ('object_repr', 'object_id', 'actor__username', 'ip_address')
    list_select_related = ('actor',)
    readonly_fields = (
        'actor',
        'action',
        'object_type',
        'object_id',
        'object_repr',
        'ip_address',
        'before',
        'after',
        'created_at',
    )
    ordering = ('-created_at',)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser and request.method in ('GET', 'HEAD', 'OPTIONS')

    def has_delete_permission(self, request, obj=None):
        return False


class AuditedUserAdmin(AuditedModelAdmin, UserAdmin):
    def save_model(self, request, obj, form, change):
        request._audit_user_before = self._snapshot(obj) if change else None
        request._audit_user_created = not change
        UserAdmin.save_model(self, request, obj, form, change)

    def save_related(self, request, form, formsets, change):
        UserAdmin.save_related(self, request, form, formsets, change)
        user = form.instance
        before = request._audit_user_before
        after = self._snapshot(user)
        AuditEntry.objects.create(
            actor=request.user,
            action=(
                AuditEntry.Action.UPDATE
                if change
                else AuditEntry.Action.CREATE
            ),
            object_type=user._meta.label,
            object_id=str(user.pk),
            object_repr=str(user)[:255],
            ip_address=request.META.get('REMOTE_ADDR'),
            before=before,
            after=after,
        )

    @staticmethod
    def _snapshot(user):
        values = capture_fields(user)
        values['groups'] = list(user.groups.order_by('name').values_list('name', flat=True))
        values['user_permissions'] = list(
            user.user_permissions.order_by('codename').values_list('codename', flat=True)
        )
        return values


admin.site.unregister(get_user_model())
admin.site.register(get_user_model(), AuditedUserAdmin)
