import hashlib
import hmac
import logging
import smtplib
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_not_required
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.conf import settings
from django.contrib.auth.views import LoginView, PasswordResetView
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.core.mail.message import BadHeaderError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.cache import never_cache

from academics.models import Course, FeeInvoice
from students.models import Student

from .audit import capture_fields, record_change
from .forms import FacultyAccountForm, StudentAccountForm
from .models import LoginAttempt, UserProfile
from .permissions import get_user_role, roles_required, visible_students


ROLE_PORTALS = {
    'admin': (
        UserProfile.Role.ADMIN,
        UserProfile.Role.REGISTRAR,
        UserProfile.Role.HOD,
        UserProfile.Role.FINANCE,
    ),
    'student': (UserProfile.Role.STUDENT,),
    'faculty': (UserProfile.Role.FACULTY,),
}

ROLE_LABELS = {
    'admin': 'Admin',
    UserProfile.Role.STUDENT: 'Student',
    UserProfile.Role.FACULTY: 'Faculty',
}

logger = logging.getLogger(__name__)


@login_not_required
def portal_home(request):
    if request.user.is_authenticated:
        if get_user_role(request.user) is not None:
            return redirect('students:dashboard')
        messages.error(
            request,
            'Your account does not have a valid college role. Contact an administrator.',
        )
    return render(request, 'accounts/portal_home.html')


@method_decorator(sensitive_post_parameters(), name='dispatch')
@method_decorator(never_cache, name='dispatch')
@method_decorator(login_not_required, name='dispatch')
class PortalLoginView(LoginView):
    template_name = 'accounts/login.html'
    redirect_authenticated_user = False
    portal = None

    def dispatch(self, request, *args, **kwargs):
        self.expected_role = ROLE_PORTALS.get(self.portal)
        if self.expected_role is None:
            self.expected_role = ()
        if request.user.is_authenticated:
            role = get_user_role(request.user)
            if role is not None:
                if self.expected_role and role not in self.expected_role:
                    messages.info(
                        request,
                        'You are already signed in with a different college role. You have been returned to your dashboard.',
                    )
                return redirect('students:dashboard')
            messages.error(
                request,
                'Your signed-in account has no valid college role. Contact an administrator or sign out.',
            )
            return redirect('accounts:portal_home')
        return super().dispatch(request, *args, **kwargs)

    def _login_attempt_key(self):
        username = self.request.POST.get('username', '').strip().casefold()
        ip_address = self.request.META.get('REMOTE_ADDR', '')
        if not username or not ip_address:
            return None
        identifier_hash = hmac.new(
            str(settings.SECRET_KEY).encode(),
            username.encode(),
            hashlib.sha256,
        ).hexdigest()
        return identifier_hash, ip_address

    def post(self, request, *args, **kwargs):
        self.rate_limited = False
        key = self._login_attempt_key()
        if key:
            attempt = LoginAttempt.objects.filter(
                identifier_hash=key[0],
                ip_address=key[1],
                locked_until__gt=timezone.now(),
            ).first()
            if attempt:
                self.rate_limited = True
                form = self.get_form()
                form.add_error(
                    None,
                    'Too many unsuccessful login attempts. Try again after the temporary lock expires.',
                )
                return self.form_invalid(form)
        return super().post(request, *args, **kwargs)

    def _record_failed_login(self):
        key = self._login_attempt_key()
        if not key:
            return
        now = timezone.now()
        with transaction.atomic():
            attempt, _ = LoginAttempt.objects.select_for_update().get_or_create(
                identifier_hash=key[0],
                ip_address=key[1],
                defaults={
                    'failures': 0,
                    'window_started_at': now,
                },
            )
            if attempt.window_started_at < now - timedelta(minutes=15):
                attempt.failures = 0
                attempt.window_started_at = now
                attempt.locked_until = None
            attempt.failures += 1
            if attempt.failures >= 5:
                attempt.locked_until = now + timedelta(minutes=15)
            attempt.save(
                update_fields=[
                    'failures',
                    'window_started_at',
                    'locked_until',
                    'updated_at',
                ]
            )

    def form_valid(self, form):
        actual_role = get_user_role(form.get_user())
        if actual_role is None:
            form.add_error(
                None,
                'This account is not configured for the college portal. Contact an administrator.',
            )
            return self.form_invalid(form)
        if self.expected_role and actual_role not in self.expected_role:
            form.add_error(
                None,
                f'This account is not authorized for the {ROLE_LABELS[self.portal]} portal. Choose the correct portal or contact an administrator.',
            )
            return self.form_invalid(form)
        key = self._login_attempt_key()
        if key:
            LoginAttempt.objects.filter(
                identifier_hash=key[0],
                ip_address=key[1],
            ).delete()
        return super().form_valid(form)

    def form_invalid(self, form):
        if not getattr(self, 'rate_limited', False) and form.get_user() is None:
            self._record_failed_login()
        return super().form_invalid(form)

    def get_success_url(self):
        return reverse('students:dashboard')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['portal'] = self.portal
        context['portal_label'] = ROLE_LABELS.get(self.portal)
        context['portal_home_url'] = reverse('accounts:portal_home')
        return context


def _consume_password_reset_limit(identifier, ip_address, maximum_attempts):
    identifier_hash = hmac.new(
        str(settings.SECRET_KEY).encode(),
        f'password-reset:{identifier}'.encode(),
        hashlib.sha256,
    ).hexdigest()
    now = timezone.now()
    with transaction.atomic():
        attempt, _ = LoginAttempt.objects.select_for_update().get_or_create(
            identifier_hash=identifier_hash,
            ip_address=ip_address,
            defaults={'failures': 0, 'window_started_at': now},
        )
        if attempt.locked_until and attempt.locked_until > now:
            return False
        if attempt.window_started_at < now - timedelta(minutes=15):
            attempt.failures = 0
            attempt.window_started_at = now
            attempt.locked_until = None
        attempt.failures += 1
        if attempt.failures >= maximum_attempts:
            attempt.locked_until = now + timedelta(minutes=15)
        attempt.save(
            update_fields=[
                'failures',
                'window_started_at',
                'locked_until',
                'updated_at',
            ]
        )
        return attempt.failures <= maximum_attempts


class ThrottledPasswordResetView(PasswordResetView):
    template_name = 'accounts/password_reset_form.html'
    email_template_name = 'accounts/password_reset_email.txt'
    subject_template_name = 'accounts/password_reset_subject.txt'
    success_url = reverse_lazy('accounts:password_reset_done')

    def post(self, request, *args, **kwargs):
        form = self.get_form()
        if form.is_valid():
            email = form.cleaned_data['email'].strip().casefold()
            ip_address = request.META.get('REMOTE_ADDR') or '0.0.0.0'
            email_allowed = _consume_password_reset_limit(
                f'email:{email}',
                ip_address,
                maximum_attempts=5,
            )
            ip_allowed = _consume_password_reset_limit(
                'all-addresses',
                ip_address,
                maximum_attempts=20,
            )
            if not (email_allowed and ip_allowed):
                return redirect(self.get_success_url())
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        try:
            return super().form_valid(form)
        except (BadHeaderError, OSError, smtplib.SMTPException, ValueError):
            logger.error('Password-reset email delivery failed.')
            return redirect(self.get_success_url())


def permission_denied(request, exception=None):
    return render(request, 'accounts/403.html', status=403)


@roles_required(*UserProfile.Role.values)
def command_search(request):
    query = request.GET.get('q', '').strip()[:100]
    role = get_user_role(request.user)
    students = []
    faculty = []
    courses = []
    invoices = []
    if len(query) >= 2:
        if role != UserProfile.Role.FINANCE:
            students = list(
                visible_students(request.user)
                .filter(
                    Q(roll_number__icontains=query)
                    | Q(full_name__icontains=query)
                    | Q(email__icontains=query)
                )
                .order_by('roll_number')[:5]
            )
        if role in (
            UserProfile.Role.ADMIN,
            UserProfile.Role.REGISTRAR,
            UserProfile.Role.HOD,
        ):
            faculty_query = UserProfile.objects.filter(
                role__in=(UserProfile.Role.FACULTY, UserProfile.Role.HOD)
            ).select_related('user')
            if role == UserProfile.Role.HOD:
                faculty_query = faculty_query.filter(
                    department=request.user.role_profile.department
                )
            faculty = list(
                faculty_query.filter(
                    Q(user__username__icontains=query)
                    | Q(user__first_name__icontains=query)
                    | Q(user__last_name__icontains=query)
                    | Q(user__email__icontains=query)
                ).order_by('user__username')[:5]
            )
        if role in (
            UserProfile.Role.ADMIN,
            UserProfile.Role.REGISTRAR,
            UserProfile.Role.HOD,
            UserProfile.Role.FACULTY,
            UserProfile.Role.STUDENT,
        ):
            courses_query = Course.objects.filter(is_active=True)
            if role in (UserProfile.Role.HOD, UserProfile.Role.FACULTY):
                courses_query = courses_query.filter(
                    department=request.user.role_profile.department
                )
            elif role == UserProfile.Role.STUDENT:
                courses_query = courses_query.filter(
                    enrollments__student_id=request.user.role_profile.student_id
                )
            courses = list(
                courses_query.filter(
                    Q(code__icontains=query)
                    | Q(name__icontains=query)
                    | Q(department__icontains=query)
                ).distinct().order_by('code')[:5]
            )
        if role in (
            UserProfile.Role.ADMIN,
            UserProfile.Role.REGISTRAR,
            UserProfile.Role.FINANCE,
        ):
            invoice_query = FeeInvoice.objects.select_related('student')
        elif role == UserProfile.Role.STUDENT:
            invoice_query = FeeInvoice.objects.filter(
                student_id=request.user.role_profile.student_id
            ).select_related('student')
        else:
            invoice_query = FeeInvoice.objects.none()
        invoices = list(
            invoice_query.filter(
                Q(receipt_number__icontains=query)
                | Q(student__roll_number__icontains=query)
                | Q(student__full_name__icontains=query)
                | Q(student__email__icontains=query)
            ).order_by('-created_at')[:5]
        )
    return render(
        request,
        'accounts/_command_results.html',
        {
            'query': query,
            'students': students,
            'faculty': faculty,
            'courses': courses,
            'invoices': invoices,
        },
    )


def _account_setup_url(request, user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    path = reverse('accounts:password_reset_confirm', args=[uid, token])
    return request.build_absolute_uri(path)


class AccountEmailDeliveryError(Exception):
    pass


def _send_account_setup_email(request, user, role_label):
    setup_url = _account_setup_url(request, user)
    subject = f'Set up your {role_label} college portal account'
    body = (
        f'Hello {user.get_full_name() or user.get_username()},\n\n'
        'An account has been created for you in the college portal. '
        'Use the secure, single-use link below to choose your password:\n\n'
        f'{setup_url}\n\n'
        'This link expires after the configured password-reset period. '
        'If you were not expecting this message, contact your college administrator.'
    )
    try:
        sent_count = send_mail(
            subject,
            body,
            settings.DEFAULT_FROM_EMAIL,
            [user.email],
            fail_silently=False,
        )
    except (BadHeaderError, OSError, smtplib.SMTPException, ValueError) as error:
        logger.error('Account password-setup email delivery failed.')
        raise AccountEmailDeliveryError from error
    if sent_count != 1:
        logger.error('Account password-setup email was not accepted by the email backend.')
        raise AccountEmailDeliveryError


@roles_required(UserProfile.Role.ADMIN, UserProfile.Role.REGISTRAR)
def faculty_list(request):
    query = request.GET.get('q', '').strip()
    department = request.GET.get('department', '').strip()
    status = request.GET.get('status', '')
    profiles = UserProfile.objects.filter(
        role=UserProfile.Role.FACULTY
    ).select_related('user')
    if query:
        profiles = profiles.filter(
            Q(user__username__icontains=query)
            | Q(user__first_name__icontains=query)
            | Q(user__last_name__icontains=query)
            | Q(user__email__icontains=query)
            | Q(department__icontains=query)
        )
    departments = list(
        UserProfile.objects.filter(role=UserProfile.Role.FACULTY)
        .order_by('department')
        .values_list('department', flat=True)
        .distinct()
    )
    if department not in departments:
        department = ''
    if department:
        profiles = profiles.filter(department=department)
    if status in ('active', 'inactive'):
        profiles = profiles.filter(user__is_active=(status == 'active'))
    else:
        status = ''

    page_obj = Paginator(profiles.order_by('user__username'), 20).get_page(
        request.GET.get('page')
    )
    query_params = request.GET.copy()
    query_params.pop('page', None)
    return render(
        request,
        'accounts/faculty_list.html',
        {
            'page_obj': page_obj,
            'profiles': page_obj.object_list,
            'query': query,
            'departments': departments,
            'selected_department': department,
            'selected_status': status,
            'query_string': query_params.urlencode(),
        },
    )


@roles_required(UserProfile.Role.ADMIN, UserProfile.Role.REGISTRAR)
def faculty_create(request):
    form = FacultyAccountForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            with transaction.atomic():
                profile = form.create_account()
                record_change(request, profile.user, 'CREATE')
                record_change(request, profile, 'CREATE')
                _send_account_setup_email(request, profile.user, 'faculty')
        except (AccountEmailDeliveryError, IntegrityError, ValidationError):
            form.add_error(
                None,
                'The faculty account was not created because account setup could not be completed. Verify email delivery settings and try again.',
            )
        else:
            messages.success(
                request,
                'Faculty account created. A secure password-setup email was sent to the registered address.',
            )
            return redirect('accounts:faculty_detail', pk=profile.pk)
    return render(
        request,
        'accounts/faculty_form.html',
        {'form': form, 'page_title': 'Add faculty', 'submit_label': 'Create faculty account'},
    )


@roles_required(UserProfile.Role.ADMIN, UserProfile.Role.REGISTRAR)
def faculty_detail(request, pk):
    profile = get_object_or_404(
        UserProfile.objects.select_related('user'),
        pk=pk,
        role=UserProfile.Role.FACULTY,
    )
    return render(
        request,
        'accounts/faculty_detail.html',
        {'profile': profile},
    )


@roles_required(UserProfile.Role.ADMIN, UserProfile.Role.REGISTRAR)
def faculty_update(request, pk):
    profile = get_object_or_404(
        UserProfile.objects.select_related('user'),
        pk=pk,
        role=UserProfile.Role.FACULTY,
    )
    form = FacultyAccountForm(
        request.POST or None,
        profile=profile,
    )
    if request.method == 'POST' and form.is_valid():
        try:
            with transaction.atomic():
                user_before = capture_fields(profile.user)
                profile_before = capture_fields(profile)
                form.save()
                record_change(request, profile.user, 'UPDATE', user_before)
                record_change(request, profile, 'UPDATE', profile_before)
        except (IntegrityError, ValidationError):
            form.add_error(
                None,
                'The faculty account could not be updated. Check that the email is unique, then try again.',
            )
        else:
            messages.success(request, 'Faculty account details were updated.')
            return redirect('accounts:faculty_detail', pk=profile.pk)
    return render(
        request,
        'accounts/faculty_form.html',
        {
            'form': form,
            'profile': profile,
            'page_title': 'Edit faculty',
            'submit_label': 'Save changes',
        },
    )


@roles_required(UserProfile.Role.ADMIN, UserProfile.Role.REGISTRAR)
def faculty_status(request, pk, status):
    profile = get_object_or_404(
        UserProfile.objects.select_related('user'),
        pk=pk,
        role=UserProfile.Role.FACULTY,
    )
    if status not in ('activate', 'deactivate'):
        return redirect('accounts:faculty_detail', pk=profile.pk)
    active = status == 'activate'
    if request.method == 'POST':
        before = capture_fields(profile.user)
        profile.user.is_active = active
        profile.user.save(update_fields=['is_active'])
        record_change(request, profile.user, 'UPDATE', before)
        action = 'activated' if active else 'deactivated'
        messages.success(request, f'The faculty account was {action}.')
        return redirect('accounts:faculty_detail', pk=profile.pk)
    return render(
        request,
        'accounts/faculty_status_confirm.html',
        {'profile': profile, 'target_active': active},
    )


@roles_required(UserProfile.Role.ADMIN, UserProfile.Role.REGISTRAR)
def student_account_create(request, pk):
    student = get_object_or_404(Student, pk=pk)
    if hasattr(student, 'user_profile'):
        messages.info(request, 'This student already has a linked login account.')
        return redirect('students:detail', pk=student.pk)
    form = StudentAccountForm(request.POST or None, student=student)
    if request.method == 'POST' and form.is_valid():
        try:
            with transaction.atomic():
                profile = form.create_account()
                record_change(request, profile.user, 'CREATE')
                record_change(request, profile, 'CREATE')
                _send_account_setup_email(request, profile.user, 'student')
        except (AccountEmailDeliveryError, IntegrityError, ValidationError):
            form.add_error(
                None,
                'The student login was not created because account setup could not be completed. Verify email delivery settings and try again.',
            )
        else:
            messages.success(
                request,
                'Student login created. A secure password-setup email was sent to the registered address.',
            )
            return redirect('students:detail', pk=student.pk)
    return render(
        request,
        'accounts/student_account_form.html',
        {'form': form, 'student': student},
    )


@roles_required(UserProfile.Role.ADMIN)
def user_account_list(request):
    query = request.GET.get('q', '').strip()
    role_filter = request.GET.get('role', '')
    users = get_user_model().objects.all().order_by('username')
    if query:
        users = users.filter(
            Q(username__icontains=query)
            | Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(email__icontains=query)
        )
    if role_filter in UserProfile.Role.values:
        if role_filter == UserProfile.Role.ADMIN:
            users = users.filter(
                Q(is_superuser=True)
                | Q(role_profile__role=UserProfile.Role.ADMIN, is_staff=True)
            )
        else:
            users = users.filter(role_profile__role=role_filter)
    else:
        role_filter = ''
    page_obj = Paginator(users.select_related('role_profile'), 20).get_page(
        request.GET.get('page')
    )
    for user in page_obj.object_list:
        user.application_role = get_user_role(user)
    query_params = request.GET.copy()
    query_params.pop('page', None)
    return render(
        request,
        'accounts/user_list.html',
        {
            'page_obj': page_obj,
            'users': page_obj.object_list,
            'query': query,
            'selected_role': role_filter,
            'role_choices': UserProfile.Role.choices,
            'query_string': query_params.urlencode(),
        },
    )
