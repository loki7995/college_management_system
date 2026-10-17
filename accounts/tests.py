from decimal import Decimal
import re
from unittest.mock import patch
from urllib.parse import urlsplit

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse

from academics.models import ExaminationMark
from students.models import Student

from .models import UserProfile


class AuthenticationWorkflowTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            username='accounts-admin',
            email='accounts-admin@example.edu',
            password='Admin-test-password-932!',
        )

    def test_anonymous_users_are_redirected_to_login(self):
        response = self.client.get(reverse('students:dashboard'))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.url,
            f'{reverse("accounts:portal_home")}?next={reverse("students:dashboard")}',
        )

    def test_login_and_post_logout(self):
        response = self.client.post(
            reverse('accounts:login'),
            {
                'username': self.admin.get_username(),
                'password': 'Admin-test-password-932!',
            },
        )
        self.assertRedirects(response, reverse('students:dashboard'))
        self.assertEqual(self.client.get(reverse('students:dashboard')).status_code, 200)

        logout_response = self.client.post(reverse('accounts:logout'))
        self.assertRedirects(logout_response, reverse('accounts:portal_home'))
        protected_response = self.client.get(reverse('students:dashboard'))
        self.assertEqual(protected_response.status_code, 302)
        self.assertTrue(
            protected_response.url.startswith(reverse('accounts:portal_home'))
        )

    def test_superuser_login_routes_to_administrator_dashboard_without_profile(self):
        self.assertFalse(
            UserProfile.objects.filter(user=self.admin).exists()
        )
        response = self.client.post(
            reverse('accounts:login'),
            {
                'username': self.admin.get_username(),
                'password': 'Admin-test-password-932!',
            },
        )
        self.assertRedirects(response, reverse('students:dashboard'))
        dashboard = self.client.get(response.url)
        self.assertEqual(dashboard.status_code, 200)
        self.assertTemplateUsed(dashboard, 'students/dashboard.html')
        self.assertEqual(dashboard.context['current_user_role'], UserProfile.Role.ADMIN)
        self.assertContains(dashboard, 'Admin panel')

    def test_superuser_role_takes_precedence_over_student_profile(self):
        student = Student.objects.create(
            roll_number='ADMIN-ROLE-OVERRIDE',
            full_name='Linked Student',
            email='linked-student@example.edu',
            department='Engineering',
            academic_year='2026-2027',
        )
        UserProfile.objects.create(
            user=self.admin,
            role=UserProfile.Role.STUDENT,
            student=student,
        )
        self.client.force_login(self.admin)
        response = self.client.get(reverse('students:dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'students/dashboard.html')
        self.assertEqual(response.context['current_user_role'], UserProfile.Role.ADMIN)

    def test_password_change_updates_the_authenticated_users_password(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse('accounts:password_change'),
            {
                'old_password': 'Admin-test-password-932!',
                'new_password1': 'A-new-test-password-583!',
                'new_password2': 'A-new-test-password-583!',
            },
        )
        self.assertRedirects(response, reverse('accounts:password_change_done'))
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.check_password('A-new-test-password-583!'))

    def test_authenticated_user_without_a_provisioned_role_is_denied(self):
        user = get_user_model().objects.create_user(
            username='no-role',
            password='No-role-test-password-183!',
        )
        self.client.force_login(user)
        response = self.client.get(reverse('students:dashboard'))
        self.assertEqual(response.status_code, 403)

    def test_authenticated_user_with_invalid_profile_role_is_denied(self):
        user = get_user_model().objects.create_user(
            username='invalid-role',
            password='Invalid-role-test-password-384!',
        )
        profile = UserProfile.objects.create(
            user=user,
            role=UserProfile.Role.FACULTY,
            department='Engineering',
        )
        UserProfile.objects.filter(pk=profile.pk).update(role='INVALID')
        self.client.force_login(user)
        response = self.client.get(reverse('students:dashboard'))
        self.assertEqual(response.status_code, 403)

    def test_staff_flag_without_explicit_admin_role_does_not_grant_admin_access(self):
        user = get_user_model().objects.create_user(
            username='staff-without-role',
            password='Staff-without-role-test-password-268!',
            is_staff=True,
        )
        self.client.force_login(user)
        response = self.client.get(reverse('students:dashboard'))
        self.assertEqual(response.status_code, 403)


class RoleAccessTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser(
            username='role-admin',
            email='role-admin@example.edu',
            password='Role-admin-test-password-314!',
        )
        self.faculty = User.objects.create_user(
            username='engineering-faculty',
            password='Faculty-test-password-271!',
        )
        self.student_user = User.objects.create_user(
            username='linked-student',
            password='Student-test-password-615!',
        )
        self.own_student = self.make_student(
            'ROLE-OWN-01',
            'Own Student',
            'own.student@example.edu',
            'Engineering',
        )
        self.other_student = self.make_student(
            'ROLE-OTHER-01',
            'Other Student',
            'other.student@example.edu',
            'Science',
        )
        UserProfile.objects.create(
            user=self.faculty,
            role=UserProfile.Role.FACULTY,
            department='Engineering',
        )
        UserProfile.objects.create(
            user=self.student_user,
            role=UserProfile.Role.STUDENT,
            student=self.own_student,
        )
        self.own_mark = self.make_mark(self.own_student, 'EN101', 'Engineering Basics')
        self.other_mark = self.make_mark(self.other_student, 'SC101', 'Science Basics')

    def make_student(self, roll, name, email, department):
        return Student.objects.create(
            roll_number=roll,
            full_name=name,
            email=email,
            department=department,
            academic_year='2026-2027',
        )

    def make_mark(self, student, code, name):
        return ExaminationMark.objects.create(
            student=student,
            subject_code=code,
            subject_name=name,
            semester=1,
            internal_marks=Decimal('20'),
            external_marks=Decimal('60'),
        )

    def test_faculty_can_only_see_and_record_in_their_department(self):
        self.client.force_login(self.faculty)
        students_response = self.client.get(reverse('students:list'))
        self.assertContains(students_response, self.own_student.full_name)
        self.assertNotContains(students_response, self.other_student.full_name)
        self.assertEqual(
            self.client.get(
                reverse('students:detail', args=[self.other_student.pk])
            ).status_code,
            404,
        )

        marks_response = self.client.get(reverse('academics:list'))
        self.assertContains(marks_response, self.own_mark.subject_name)
        self.assertNotContains(marks_response, self.other_mark.subject_name)
        self.assertEqual(
            self.client.get(
                reverse('academics:detail', args=[self.other_mark.pk])
            ).status_code,
            404,
        )
        form_response = self.client.get(reverse('academics:create'))
        student_choices = form_response.context['form'].fields['student'].queryset
        self.assertQuerySetEqual(
            student_choices.order_by('pk'),
            [self.own_student],
        )

        response = self.client.post(
            reverse('academics:create'),
            {
                'student': self.other_student.pk,
                'subject_code': 'SC102',
                'subject_name': 'Not in scope',
                'semester': 2,
                'internal_marks': '20',
                'external_marks': '60',
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            ExaminationMark.objects.filter(subject_code='SC102').count(),
            0,
        )
        self.assertEqual(
            self.client.get(
                reverse('students:update', args=[self.own_student.pk])
            ).status_code,
            403,
        )
        update_response = self.client.post(
            reverse('academics:update', args=[self.own_mark.pk]),
            {
                'student': self.own_student.pk,
                'subject_code': 'EN101',
                'subject_name': 'Engineering Basics',
                'semester': 1,
                'internal_marks': '25',
                'external_marks': '60',
            },
        )
        self.assertRedirects(
            update_response,
            reverse('academics:detail', args=[self.own_mark.pk]),
        )
        self.own_mark.refresh_from_db()
        self.assertEqual(self.own_mark.total_marks, Decimal('85'))
        self.assertEqual(
            self.client.get(
                reverse('academics:delete', args=[self.own_mark.pk])
            ).status_code,
            403,
        )

    def test_student_can_only_view_their_own_profile_and_results(self):
        self.client.force_login(self.student_user)
        dashboard_response = self.client.get(reverse('students:dashboard'))
        self.assertEqual(dashboard_response.status_code, 200)
        self.assertContains(dashboard_response, self.own_student.full_name)
        self.assertNotContains(dashboard_response, self.other_student.full_name)

        own_profile = self.client.get(
            reverse('students:detail', args=[self.own_student.pk])
        )
        self.assertEqual(own_profile.status_code, 200)
        self.assertEqual(
            self.client.get(
                reverse('students:detail', args=[self.other_student.pk])
            ).status_code,
            404,
        )
        marks_response = self.client.get(reverse('academics:list'))
        self.assertContains(marks_response, self.own_mark.subject_name)
        self.assertNotContains(marks_response, self.other_mark.subject_name)
        self.assertEqual(
            self.client.get(
                reverse('academics:detail', args=[self.other_mark.pk])
            ).status_code,
            404,
        )
        self.assertEqual(self.client.get(reverse('students:list')).status_code, 403)
        self.assertEqual(self.client.get(reverse('academics:create')).status_code, 403)
        self.assertEqual(
            self.client.get(
                reverse('academics:update', args=[self.own_mark.pk])
            ).status_code,
            403,
        )

    def test_faculty_login_routes_to_department_dashboard(self):
        response = self.client.post(
            reverse('accounts:login'),
            {
                'username': self.faculty.get_username(),
                'password': 'Faculty-test-password-271!',
            },
        )
        self.assertRedirects(response, reverse('students:dashboard'))
        dashboard = self.client.get(response.url)
        self.assertEqual(dashboard.status_code, 200)
        self.assertTemplateUsed(dashboard, 'students/dashboard.html')
        self.assertEqual(
            dashboard.context['current_user_role'],
            UserProfile.Role.FACULTY,
        )
        self.assertContains(dashboard, 'DEPARTMENT OVERVIEW')
        self.assertEqual(dashboard.context['student_count'], 1)

    def test_student_login_routes_to_own_student_dashboard(self):
        response = self.client.post(
            reverse('accounts:login'),
            {
                'username': self.student_user.get_username(),
                'password': 'Student-test-password-615!',
            },
        )
        self.assertRedirects(response, reverse('students:dashboard'))
        dashboard = self.client.get(response.url)
        self.assertEqual(dashboard.status_code, 200)
        self.assertTemplateUsed(dashboard, 'students/student_dashboard.html')
        self.assertEqual(
            dashboard.context['current_user_role'],
            UserProfile.Role.STUDENT,
        )
        self.assertContains(dashboard, self.own_student.full_name)
        self.assertNotContains(dashboard, self.other_student.full_name)


class PortalAndAccountManagementTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser(
            username='portal-admin',
            email='portal-admin@example.edu',
            password='Portal-admin-test-password-481!',
        )
        self.faculty = User.objects.create_user(
            username='engineering-faculty',
            email='portal-faculty@example.edu',
            password='Faculty-test-password-271!',
        )
        self.faculty_profile = UserProfile.objects.create(
            user=self.faculty,
            role=UserProfile.Role.FACULTY,
            department='Engineering',
        )
        self.student = Student.objects.create(
            roll_number='ROLE-OWN-01',
            full_name='Own Student',
            email='portal.student@example.edu',
            department='Engineering',
            academic_year='2026-2027',
        )
        self.own_student = self.student
        self.other_student = Student.objects.create(
            roll_number='ROLE-OTHER-01',
            full_name='Other Student',
            email='other.student@example.edu',
            department='Science',
            academic_year='2026-2027',
        )
        self.student_user = User.objects.create_user(
            username='linked-student',
            email=self.student.email,
            password='Student-test-password-615!',
        )
        UserProfile.objects.create(
            user=self.student_user,
            role=UserProfile.Role.STUDENT,
            student=self.student,
        )
        self.unlinked_student = Student.objects.create(
            roll_number='ROLE-UNLINKED-01',
            full_name='Unlinked Student',
            email='unlinked.student@example.edu',
            department='Science',
            academic_year='2026-2027',
        )
        self.own_mark = self.make_mark(
            self.own_student,
            'EN101',
            'Engineering Basics',
        )
        self.other_mark = self.make_mark(
            self.other_student,
            'SC101',
            'Science Basics',
        )

    def make_mark(self, student, code, name):
        return ExaminationMark.objects.create(
            student=student,
            subject_code=code,
            subject_name=name,
            semester=1,
            internal_marks=Decimal('20'),
            external_marks=Decimal('60'),
        )

    def test_portal_landing_offers_all_three_role_choices(self):
        response = self.client.get(reverse('accounts:portal_home'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'accounts/portal_home.html')
        for label, url_name in (
            ('Login as Admin', 'accounts:admin_login'),
            ('Login as Student', 'accounts:student_login'),
            ('Login as Faculty', 'accounts:faculty_login'),
        ):
            self.assertContains(response, label)
            self.assertContains(response, reverse(url_name))

    def test_each_role_can_sign_in_through_its_own_portal(self):
        cases = (
            ('accounts:admin_login', self.admin, 'Portal-admin-test-password-481!'),
            ('accounts:faculty_login', self.faculty, 'Faculty-test-password-271!'),
            ('accounts:student_login', self.student_user, 'Student-test-password-615!'),
        )
        for portal, user, password in cases:
            with self.subTest(portal=portal):
                response = self.client.post(
                    reverse(portal),
                    {'username': user.get_username(), 'password': password},
                )
                self.assertRedirects(response, reverse('students:dashboard'))
                dashboard = self.client.get(response.url)
                self.assertEqual(dashboard.status_code, 200)
                self.client.post(reverse('accounts:logout'))

    def test_portal_rejects_credentials_for_a_different_role(self):
        response = self.client.post(
            reverse('accounts:admin_login'),
            {
                'username': self.faculty.get_username(),
                'password': 'Faculty-test-password-271!',
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'not authorized for the Admin portal')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_portal_rejects_an_account_without_a_valid_role(self):
        unassigned = get_user_model().objects.create_user(
            username='portal-unassigned',
            password='Portal-unassigned-test-password-129!',
        )
        response = self.client.post(
            reverse('accounts:student_login'),
            {
                'username': unassigned.get_username(),
                'password': 'Portal-unassigned-test-password-129!',
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'not configured for the college portal')
        self.assertNotIn('_auth_user_id', self.client.session)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_admin_can_create_search_and_deactivate_faculty_account(self):
        mail.outbox.clear()
        self.client.force_login(self.admin)
        create_url = reverse('accounts:faculty_create')
        response = self.client.post(
            create_url,
            {
                'username': 'new-faculty',
                'first_name': 'New',
                'last_name': 'Faculty',
                'email': 'new.faculty@example.edu',
                'department': 'Computer Science and Engineering (CSE)',
                'is_active': 'on',
            },
        )
        profile = UserProfile.objects.get(user__username='new-faculty')
        self.assertRedirects(
            response,
            reverse('accounts:faculty_detail', args=[profile.pk]),
            fetch_redirect_response=False,
        )
        self.assertEqual(profile.role, UserProfile.Role.FACULTY)
        self.assertEqual(profile.department, 'Computer Science and Engineering (CSE)')
        self.assertFalse(profile.user.is_staff)
        self.assertFalse(profile.user.is_superuser)
        self.assertFalse(profile.user.has_usable_password())
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(profile.user.email, mail.outbox[0].to)
        setup_url = re.search(r'https?://\S+', mail.outbox[0].body).group(0)
        self.assertIn('password/reset/confirm/', setup_url)
        self.assertNotContains(
            self.client.get(reverse('accounts:faculty_detail', args=[profile.pk])),
            'password/reset/confirm/',
        )
        listing = self.client.get(
            reverse('accounts:faculty_list'),
            {
                'q': 'new-faculty',
                'department': 'Computer Science and Engineering (CSE)',
                'status': 'active',
            },
        )
        self.assertContains(listing, 'new-faculty')
        self.assertEqual(listing.context['page_obj'].paginator.count, 1)
        accounts = self.client.get(
            reverse('accounts:user_list'),
            {'q': 'new-faculty', 'role': UserProfile.Role.FACULTY},
        )
        self.assertContains(accounts, 'new-faculty')
        self.assertEqual(accounts.context['page_obj'].paginator.count, 1)
        deactivate_url = reverse(
            'accounts:faculty_status',
            args=[profile.pk, 'deactivate'],
        )
        self.assertEqual(self.client.get(deactivate_url).status_code, 200)
        response = self.client.post(deactivate_url)
        self.assertRedirects(
            response,
            reverse('accounts:faculty_detail', args=[profile.pk]),
        )
        profile.user.refresh_from_db()
        self.assertFalse(profile.user.is_active)

    def test_faculty_creation_rejects_unlisted_department_values(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse('accounts:faculty_create'),
            {
                'username': 'invalid-department-faculty',
                'email': 'invalid.department@example.edu',
                'department': 'Unlisted Department',
                'is_active': 'on',
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('department', response.context['form'].errors)
        self.assertFalse(
            get_user_model().objects.filter(
                username='invalid-department-faculty'
            ).exists()
        )

    def test_admin_can_edit_existing_faculty_profile(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse('accounts:faculty_update', args=[self.faculty_profile.pk]),
            {
                'username': self.faculty.get_username(),
                'first_name': 'Updated',
                'last_name': 'Faculty',
                'email': 'updated.faculty@example.edu',
                'department': 'Electronics and Communication Engineering (ECE)',
                'is_active': 'on',
            },
        )
        self.assertRedirects(
            response,
            reverse('accounts:faculty_detail', args=[self.faculty_profile.pk]),
        )
        self.faculty.refresh_from_db()
        self.faculty_profile.refresh_from_db()
        self.assertEqual(self.faculty.first_name, 'Updated')
        self.assertEqual(
            self.faculty_profile.department,
            'Electronics and Communication Engineering (ECE)',
        )

    def test_admin_can_create_a_student_from_the_existing_student_form(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse('students:create'),
            {
                'roll_number': 'ADMIN-ADDED-01',
                'full_name': 'Admin Added Student',
                'email': 'admin.added@example.edu',
                'department': 'Information Technology (IT)',
                'academic_year': '2026-2027',
            },
        )
        student = Student.objects.get(roll_number='ADMIN-ADDED-01')
        self.assertRedirects(
            response,
            reverse('students:detail', args=[student.pk]),
        )
        self.assertEqual(student.full_name, 'Admin Added Student')
        self.assertFalse(UserProfile.objects.filter(student=student).exists())

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_admin_can_create_student_login_and_use_one_time_password_link(self):
        mail.outbox.clear()
        self.client.force_login(self.admin)
        create_url = reverse(
            'accounts:student_account_create',
            args=[self.unlinked_student.pk],
        )
        response = self.client.post(
            create_url,
            {'username': self.unlinked_student.roll_number},
        )
        self.assertRedirects(
            response,
            reverse('students:detail', args=[self.unlinked_student.pk]),
            fetch_redirect_response=False,
        )
        profile = UserProfile.objects.get(student=self.unlinked_student)
        user = profile.user
        self.assertEqual(profile.role, UserProfile.Role.STUDENT)
        self.assertEqual(user.email, self.unlinked_student.email)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.has_usable_password())

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.unlinked_student.email, mail.outbox[0].to)
        setup_url = re.search(r'https?://\S+', mail.outbox[0].body).group(0)
        setup_path = urlsplit(setup_url).path
        setup_response = self.client.get(setup_path, follow=True)
        self.assertEqual(setup_response.status_code, 200)
        self.assertTrue(setup_response.context['validlink'])
        setup_form_path = urlsplit(setup_response.redirect_chain[-1][0]).path
        new_password = 'Student-new-secure-password-384!'
        response = self.client.post(
            setup_form_path,
            {'new_password1': new_password, 'new_password2': new_password},
        )
        self.assertRedirects(
            response,
            reverse('accounts:password_reset_complete'),
        )
        user.refresh_from_db()
        self.assertTrue(user.check_password(new_password))
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.is_staff)
        self.assertFalse(self.client.get(setup_form_path).context['validlink'])

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_student_account_is_not_created_when_setup_email_delivery_fails(self):
        self.client.force_login(self.admin)
        with patch('accounts.views.send_mail', side_effect=OSError):
            response = self.client.post(
                reverse(
                    'accounts:student_account_create',
                    args=[self.unlinked_student.pk],
                ),
                {'username': self.unlinked_student.roll_number},
            )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'was not created because account setup')
        self.assertFalse(
            UserProfile.objects.filter(student=self.unlinked_student).exists()
        )

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_forgot_password_is_generic_and_completes_single_use_reset(self):
        mail.outbox.clear()
        response = self.client.post(
            reverse('accounts:password_reset'),
            {'email': self.admin.email},
        )
        self.assertRedirects(response, reverse('accounts:password_reset_done'))
        self.assertEqual(len(mail.outbox), 1)

        reset_url = re.search(r'https?://\S+', mail.outbox[0].body).group(0)
        reset_page = self.client.get(urlsplit(reset_url).path, follow=True)
        self.assertTrue(reset_page.context['validlink'])
        reset_form_path = urlsplit(reset_page.redirect_chain[-1][0]).path
        new_password = 'Admin-reset-new-password-628!'
        response = self.client.post(
            reset_form_path,
            {'new_password1': new_password, 'new_password2': new_password},
        )
        self.assertRedirects(
            response,
            reverse('accounts:password_reset_complete'),
        )
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.check_password(new_password))
        self.assertFalse(
            self.client.get(urlsplit(reset_url).path, follow=True)
            .context['validlink']
        )

        mail.outbox.clear()
        response = self.client.post(
            reverse('accounts:password_reset'),
            {'email': 'unknown.person@example.edu'},
        )
        self.assertRedirects(response, reverse('accounts:password_reset_done'))
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_forgot_password_requests_are_throttled(self):
        mail.outbox.clear()
        for _ in range(6):
            response = self.client.post(
                reverse('accounts:password_reset'),
                {'email': self.admin.email},
            )
            self.assertRedirects(
                response,
                reverse('accounts:password_reset_done'),
            )
        self.assertEqual(len(mail.outbox), 5)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_forgot_password_rejects_malformed_email_without_sending(self):
        mail.outbox.clear()
        response = self.client.post(
            reverse('accounts:password_reset'),
            {'email': 'not-an-email'},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('email', response.context['form'].errors)
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(
        EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
        PASSWORD_RESET_TIMEOUT=-1,
    )
    def test_expired_password_reset_link_is_not_accepted(self):
        mail.outbox.clear()
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse('accounts:password_reset'),
            {'email': self.admin.email},
        )
        self.assertRedirects(response, reverse('accounts:password_reset_done'))
        reset_url = re.search(r'https?://\S+', mail.outbox[-1].body).group(0)
        reset_page = self.client.get(urlsplit(reset_url).path, follow=True)
        self.assertFalse(reset_page.context['validlink'])

    def test_faculty_cannot_access_administrator_account_management(self):
        self.client.force_login(self.faculty)
        urls = (
            reverse('accounts:faculty_list'),
            reverse('accounts:faculty_create'),
            reverse('accounts:user_list'),
            reverse(
                'accounts:student_account_create',
                args=[self.student.pk],
            ),
        )
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)

    def test_student_accounts_prevent_physical_student_deletion(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse('admin:index')).status_code, 200)
        response = self.client.get(
            reverse('students:delete', args=[self.own_student.pk])
        )
        self.assertContains(response, 'Deactivate student')
        response = self.client.post(
            reverse('students:delete', args=[self.own_student.pk])
        )
        self.assertRedirects(
            response,
            reverse('students:detail', args=[self.own_student.pk]),
        )
        self.own_student.refresh_from_db()
        self.assertFalse(self.own_student.is_active)
        self.assertTrue(
            UserProfile.objects.filter(student=self.own_student).exists()
        )

    def test_provisioned_administrator_has_cross_department_access(self):
        administrator = get_user_model().objects.create_user(
            username='provisioned-admin',
            password='Provisioned-admin-test-password-431!',
            is_staff=True,
        )
        UserProfile.objects.create(
            user=administrator,
            role=UserProfile.Role.ADMIN,
        )
        self.client.force_login(administrator)
        students_response = self.client.get(reverse('students:list'))
        self.assertContains(students_response, self.own_student.full_name)
        self.assertContains(students_response, self.other_student.full_name)
        marks_response = self.client.get(reverse('academics:list'))
        self.assertContains(marks_response, self.own_mark.subject_name)
        self.assertContains(marks_response, self.other_mark.subject_name)
        self.assertEqual(self.client.get(reverse('students:create')).status_code, 200)
        self.assertEqual(self.client.get(reverse('academics:create')).status_code, 200)
        self.assertEqual(self.client.get(reverse('admin:index')).status_code, 200)

    def test_faculty_dashboard_counts_only_assigned_department(self):
        self.faculty.is_staff = True
        self.faculty.save(update_fields=['is_staff'])
        self.client.force_login(self.faculty)
        response = self.client.get(reverse('students:dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['student_count'], 1)
        self.assertEqual(response.context['marks_count'], 1)
        self.assertNotContains(response, self.other_student.full_name)
        self.assertContains(response, 'DEPARTMENT OVERVIEW')
        self.assertEqual(self.client.get(reverse('admin:index')).status_code, 403)

    def test_faculty_profile_requires_a_department(self):
        invalid_user = get_user_model().objects.create_user(username='invalid-faculty')
        profile = UserProfile(
            user=invalid_user,
            role=UserProfile.Role.FACULTY,
        )
        with self.assertRaises(ValidationError) as error:
            profile.full_clean()
        self.assertIn('department', error.exception.message_dict)

    def test_ordinary_user_with_admin_profile_does_not_receive_admin_access(self):
        ordinary_user = get_user_model().objects.create_user(
            username='non-superuser-admin-role',
            password='Ordinary-user-test-password-726!',
        )
        UserProfile.objects.create(
            user=ordinary_user,
            role=UserProfile.Role.ADMIN,
        )
        self.client.force_login(ordinary_user)
        self.assertEqual(
            self.client.get(reverse('students:dashboard')).status_code,
            403,
        )
