from .models import AuditEntry


def capture_fields(instance):
    return {
        field.name: str(getattr(instance, field.attname))
        for field in instance._meta.concrete_fields
        if field.name not in {'password'}
    }


def record_change(request, instance, action, before=None):
    user = request.user if request.user.is_authenticated else None
    AuditEntry.objects.create(
        actor=user,
        action=action,
        object_type=instance._meta.label,
        object_id=str(instance.pk),
        object_repr=str(instance)[:255],
        ip_address=request.META.get('REMOTE_ADDR'),
        before=before,
        after=None if action == AuditEntry.Action.DELETE else capture_fields(instance),
    )
