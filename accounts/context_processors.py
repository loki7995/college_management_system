from .models import UserProfile
from .permissions import get_user_role


def role_context(request):
    role = get_user_role(request.user)
    return {
        'current_user_role': role,
        'is_college_admin': role == UserProfile.Role.ADMIN,
        'is_academic_admin': role in (
            UserProfile.Role.ADMIN,
            UserProfile.Role.REGISTRAR,
        ),
        'is_finance_officer': role == UserProfile.Role.FINANCE,
        'is_hod': role == UserProfile.Role.HOD,
        'is_faculty': role in (UserProfile.Role.FACULTY, UserProfile.Role.HOD),
        'is_student': role == UserProfile.Role.STUDENT,
    }
