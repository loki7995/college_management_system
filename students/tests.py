from datetime import date

from django.contrib.auth import get_user_model
from django.test.utils import CaptureQueriesContext
from django.test import TestCase
from django.urls import reverse
from django.db import connection

from academics.forms import ExaminationMarkForm
from academics.models import ExaminationMark
from .forms import StudentForm
from .models import Student


class StudentManagementTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_superuser(
            username='test-admin',
            email='test-admin@example.edu',
            password='Test-only-admin-password-482!',
        )
        self.client.force_login(user)

    def valid_data(self, **overrides):
        data = {
            'roll_number': 'STU-2026-001',
            'full_name': 'Jordan Lee',
            'email': 'jordan.lee@example.edu',
            'phone_number': '+1 555 010 0200',
            'department': 'Computer Science and Engineering (CSE)',
            'academic_year': '2026-2027',
            'date_of_birth': '2005-04-12',
            'address': '100 College Avenue',
        }
        data.update(overrides)
        return data

    def test_registration_saves_student_and_shows_detail(self):
        response = self.client.post(reverse('students:create'), self.valid_data())
        student = Student.objects.get(roll_number='STU-2026-001')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('students:detail', args=[student.pk]))
        self.assertEqual(student.email, 'jordan.lee@example.edu')
        self.assertEqual(student.date_of_birth, date(2005, 4, 12))
        self.assertIsNotNone(student.created_at)
        self.assertIsNotNone(student.updated_at)

    def test_required_and_unique_fields_have_clear_errors(self):
        Student.objects.create(
            roll_number='STU-2026-001',
            full_name='Existing Student',
            email='existing@example.edu',
            department='Science',
            academic_year='2026-2027',
        )
        missing_form = StudentForm({})
        self.assertFalse(missing_form.is_valid())
        self.assertIn('Enter the student’s roll number.', missing_form.errors['roll_number'])
        duplicate_form = StudentForm(self.valid_data(email='existing@example.edu'))
        self.assertFalse(duplicate_form.is_valid())
        self.assertIn('A student with this email address already exists.', duplicate_form.errors['email'])

    def test_future_birth_date_is_rejected(self):
        form = StudentForm(self.valid_data(date_of_birth='2999-01-01'))
        self.assertFalse(form.is_valid())
        self.assertIn('Date of birth cannot be in the future.', form.errors['date_of_birth'])

    def test_department_dropdown_accepts_only_standard_values_and_preserves_legacy_edit_values(self):
        form = StudentForm(self.valid_data(department='Unlisted Department'))
        self.assertFalse(form.is_valid())
        self.assertIn('department', form.errors)

        student = Student.objects.create(
            roll_number='STU-LEGACY-001',
            full_name='Legacy Department Student',
            email='legacy.department@example.edu',
            department='Computer Science',
            academic_year='2026-2027',
        )
        edit_form = StudentForm(
            self.valid_data(roll_number=student.roll_number, email=student.email),
            instance=student,
        )
        self.assertTrue(edit_form.is_valid(), edit_form.errors)
        self.assertIn(
            ('Computer Science', 'Computer Science (existing value)'),
            edit_form.fields['department'].choices,
        )

    def test_list_search_detail_edit_and_confirmed_delete(self):
        student = Student.objects.create(
            roll_number='STU-2026-001',
            full_name='Jordan Lee',
            email='jordan.lee@example.edu',
            department='Computer Science',
            academic_year='2026-2027',
        )
        response = self.client.get(reverse('students:list'), {'q': 'Jordan'})
        self.assertContains(response, 'Jordan Lee')
        self.assertEqual(
            self.client.get(reverse('students:detail', args=[student.pk])).status_code,
            200,
        )
        update_data = self.valid_data(full_name='Jordan Lee Updated')
        update_response = self.client.post(
            reverse('students:update', args=[student.pk]),
            update_data,
        )
        self.assertEqual(update_response.status_code, 302)
        student.refresh_from_db()
        self.assertEqual(student.full_name, 'Jordan Lee Updated')
        self.assertEqual(
            self.client.get(reverse('students:delete', args=[student.pk])).status_code,
            200,
        )
        self.assertTrue(Student.objects.filter(pk=student.pk).exists())
        delete_response = self.client.post(reverse('students:delete', args=[student.pk]))
        self.assertEqual(delete_response.status_code, 302)
        self.assertFalse(Student.objects.filter(pk=student.pk).exists())

    def test_student_directory_filters_and_preserves_pagination_parameters(self):
        for number in range(21):
            Student.objects.create(
                roll_number=f'STU-LIST-{number:03}',
                full_name=f'List Student {number:03}',
                email=f'list{number:03}@example.edu',
                department='Science' if number % 2 == 0 else 'Arts',
                academic_year='2026-2027' if number % 3 else '2025-2026',
                is_active=number != 20,
            )

        all_students = self.client.get(reverse('students:list'), {'status': 'all'})
        self.assertEqual(all_students.context['page_obj'].paginator.count, 21)
        self.assertEqual(all_students.context['page_obj'].paginator.num_pages, 2)
        next_page = self.client.get(
            reverse('students:list'),
            {'status': 'all', 'department': 'Arts', 'page': 2},
        )
        self.assertIn('status=all', next_page.context['query_string'])
        self.assertIn('department=Arts', next_page.context['query_string'])

        filtered = self.client.get(
            reverse('students:list'),
            {
                'department': 'Science',
                'academic_year': '2026-2027',
                'status': 'active',
            },
        )
        self.assertTrue(filtered.context['page_obj'].paginator.count > 0)
        self.assertTrue(all(student.is_active for student in filtered.context['students']))
        self.assertTrue(all(student.department == 'Science' for student in filtered.context['students']))
        self.assertTrue(all(student.academic_year == '2026-2027' for student in filtered.context['students']))

        inactive = self.client.get(reverse('students:list'), {'status': 'inactive'})
        self.assertEqual(inactive.context['page_obj'].paginator.count, 1)
        self.assertContains(inactive, 'Inactive')

    def test_student_with_marks_is_deactivated_and_academic_history_is_preserved(self):
        student = Student.objects.create(
            roll_number='STU-HISTORY-001',
            full_name='Student With History',
            email='history@example.edu',
            department='Science',
            academic_year='2026-2027',
        )
        mark = ExaminationMark.objects.create(
            student=student,
            subject_code='SC101',
            subject_name='Science Foundations',
            semester=1,
            internal_marks=20,
            external_marks=60,
        )

        confirmation = self.client.get(reverse('students:delete', args=[student.pk]))
        self.assertContains(confirmation, 'Deactivate student')
        response = self.client.post(reverse('students:delete', args=[student.pk]))
        self.assertRedirects(response, reverse('students:detail', args=[student.pk]))
        student.refresh_from_db()
        self.assertFalse(student.is_active)
        self.assertTrue(ExaminationMark.objects.filter(pk=mark.pk, student=student).exists())

        create_form = ExaminationMarkForm()
        self.assertFalse(create_form.fields['student'].queryset.filter(pk=student.pk).exists())
        edit_form = ExaminationMarkForm(instance=mark)
        self.assertTrue(edit_form.fields['student'].queryset.filter(pk=student.pk).exists())

    def test_student_status_can_be_reactivated_with_confirmation(self):
        student = Student.objects.create(
            roll_number='STU-STATUS-001',
            full_name='Inactive Student',
            email='inactive@example.edu',
            department='Science',
            academic_year='2026-2027',
            is_active=False,
        )
        confirmation = self.client.get(
            reverse('students:status', args=[student.pk, 'active'])
        )
        self.assertContains(confirmation, 'Reactivate')
        response = self.client.post(
            reverse('students:status', args=[student.pk, 'active'])
        )
        self.assertRedirects(response, reverse('students:detail', args=[student.pk]))
        student.refresh_from_db()
        self.assertTrue(student.is_active)

    def test_student_profile_includes_examination_history_and_summary(self):
        student = Student.objects.create(
            roll_number='STU-PROFILE-001',
            full_name='Profile Student',
            email='profile@example.edu',
            department='Engineering',
            academic_year='2026-2027',
        )
        ExaminationMark.objects.create(
            student=student,
            subject_code='EN101',
            subject_name='Engineering Basics',
            semester=1,
            internal_marks=20,
            external_marks=60,
        )
        response = self.client.get(reverse('students:detail', args=[student.pk]))
        self.assertEqual(response.context['mark_summary']['record_count'], 1)
        self.assertEqual(response.context['pass_percentage'], 100)
        self.assertContains(response, 'Engineering Basics')
        self.assertContains(response, 'ACADEMIC PROFILE')

    def test_dashboard_handles_empty_database_and_links_navigation(self):
        response = self.client.get(reverse('students:dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['student_count'], 0)
        self.assertEqual(response.context['marks_count'], 0)
        self.assertEqual(response.context['department_count'], 0)
        self.assertEqual(response.context['pass_percentage'], 0)
        self.assertContains(response, 'No departments yet')
        self.assertContains(response, 'No results to analyse')
        self.assertContains(response, 'Add first student')
        self.assertContains(response, 'Record first marks')
        self.assertContains(response, reverse('admin:index'))
        self.assertContains(response, 'aria-current="page"')

    def test_dashboard_uses_live_records_and_keeps_query_count_bounded(self):
        student = Student.objects.create(
            roll_number='STU-DASH-001',
            full_name='Dashboard Student',
            email='dashboard.student@example.edu',
            department='Engineering',
            academic_year='2026-2027',
        )
        ExaminationMark.objects.create(
            student=student,
            subject_code='EN101',
            subject_name='Introduction to Engineering',
            semester=1,
            internal_marks=20,
            external_marks=60,
        )
        with CaptureQueriesContext(connection) as captured:
            response = self.client.get(reverse('students:dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['student_count'], 1)
        self.assertEqual(response.context['marks_count'], 1)
        self.assertEqual(response.context['department_count'], 1)
        self.assertEqual(response.context['passed_count'], 1)
        self.assertEqual(response.context['pass_percentage'], 100)
        self.assertContains(response, 'Dashboard Student')
        self.assertContains(response, 'Introduction to Engineering')
        self.assertLessEqual(len(captured), 15)
