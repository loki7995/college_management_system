from .audit import capture_fields, record_change
from .models import AuditEntry


class AuditedModelAdmin:
    def save_model(self, request, obj, form, change):
        before = None
        if change:
            previous = type(obj).objects.get(pk=obj.pk)
            before = capture_fields(previous)
        super().save_model(request, obj, form, change)
        action = AuditEntry.Action.UPDATE if change else AuditEntry.Action.CREATE
        record_change(request, obj, action, before)

    def delete_model(self, request, obj):
        before = capture_fields(obj)
        record_change(request, obj, AuditEntry.Action.DELETE, before)
        super().delete_model(request, obj)
