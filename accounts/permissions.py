from functools import wraps

from django.core.exceptions import PermissionDenied
from django.db.models import QuerySet

from students.models import Student

from .models import UserProfile


def get_user_role(user):
    if not user.is_authenticated:
        return None
    if user.is_superuser:
        return UserProfile.Role.ADMIN
    try:
        role = user.role_profile.role
    except UserProfile.DoesNotExist:
        return None
    if role not in UserProfile.Role.values:
        return None
    if role == UserProfile.Role.ADMIN and not user.is_staff:
        return None
    if role in (UserProfile.Role.FACULTY, UserProfile.Role.HOD) and not user.role_profile.department.strip():
        return None
    if role == UserProfile.Role.STUDENT and user.role_profile.student_id is None:
        return None
    return role


def roles_required(*roles):
    def decorator(view_func):
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            if get_user_role(request.user) not in roles:
                raise PermissionDenied
            return view_func(request, *args, **kwargs)

        return wrapped

    return decorator


def visible_students(user) -> QuerySet:
    role = get_user_role(user)
    if role in (UserProfile.Role.ADMIN, UserProfile.Role.REGISTRAR):
        return Student.objects.all()
    if role in (UserProfile.Role.FACULTY, UserProfile.Role.HOD):
        return Student.objects.filter(department=user.role_profile.department)
    if role == UserProfile.Role.STUDENT:
        return Student.objects.filter(pk=user.role_profile.student_id)
    raise PermissionDenied


def visible_marks(user, queryset=None):
    from academics.models import ExaminationMark

    records = queryset if queryset is not None else ExaminationMark.objects.all()
    role = get_user_role(user)
    if role in (UserProfile.Role.ADMIN, UserProfile.Role.REGISTRAR):
        return records
    if role in (UserProfile.Role.FACULTY, UserProfile.Role.HOD):
        return records.filter(student__department=user.role_profile.department)
    if role == UserProfile.Role.STUDENT:
        return records.filter(student_id=user.role_profile.student_id)
    raise PermissionDenied


def writable_students(user):
    role = get_user_role(user)
    if role in (UserProfile.Role.ADMIN, UserProfile.Role.REGISTRAR):
        return Student.objects.filter(is_active=True)
    if role in (UserProfile.Role.FACULTY, UserProfile.Role.HOD):
        return Student.objects.filter(
            is_active=True,
            department=user.role_profile.department,
        )
    raise PermissionDenied


def can_manage_all(user):
    return get_user_role(user) in (UserProfile.Role.ADMIN, UserProfile.Role.REGISTRAR)
