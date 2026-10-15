from django.core.exceptions import PermissionDenied
from django.utils.deprecation import MiddlewareMixin

from .models import UserProfile
from .permissions import get_user_role


class AdminRoleMiddleware(MiddlewareMixin):
    def process_view(self, request, view_func, view_args, view_kwargs):
        match = getattr(request, 'resolver_match', None)
        if (
            match is not None
            and match.namespace == 'admin'
            and match.url_name != 'login'
            and get_user_role(request.user) != UserProfile.Role.ADMIN
        ):
            raise PermissionDenied
        return None
