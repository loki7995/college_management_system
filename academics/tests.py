from decimal import Decimal
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import UserProfile
from students.models import Student

from .forms import CourseForm, ExaminationMarkForm
from .grading import calculate_outcome
from .models import (
    Announcement,
    ClassSession,
    Course,
    ExaminationMark,
    FeeInvoice,
    FeePayment,
    Semester,
)


class MarksRulesTests(TestCase):
    def setUp(self):
        self.student = Student.objects.create(
            roll_number='STU-MARKS-001',
            full_name='Taylor Student',
            email='taylor.student@example.edu',
            department='Computer Science',
            academic_year='2026-2027',
        )

    def make_mark(self, **overrides):
        values = {
            'student': self.student,
            'subject_code': 'CS201',
            'subject_name': 'Data Structures',
            'semester': 1,
            'internal_marks': Decimal('20'),
            'external_marks': Decimal('60'),
        }
        values.update(overrides)
        return ExaminationMark(**values)

    def test_total_percentage_grade_and_pass_are_calculated_on_save(self):
        mark = self.make_mark()
        mark.save()
        self.assertEqual(mark.total_marks, Decimal('80'))
        self.assertEqual(mark.percentage, Decimal('80'))
        self.assertEqual(mark.grade, 'A')
        self.assertEqual(mark.result, ExaminationMark.Result.PASS)

    def test_each_grade_boundary(self):
        cases = (
            ('0', 'F'),
            ('49.99', 'F'),
            ('50', 'D'),
            ('59.99', 'D'),
            ('60', 'C'),
            ('69.99', 'C'),
            ('70', 'B'),
            ('79.99', 'B'),
            ('80', 'A'),
            ('89.99', 'A'),
            ('90', 'A+'),
            ('100', 'A+'),
        )
        for total, expected_grade in cases:
            with self.subTest(total=total):
                outcome = calculate_outcome(
                    Decimal('0'),
                    Decimal(total),
                )
                self.assertEqual(outcome['total_marks'], Decimal(total))
                self.assertEqual(outcome['percentage'], Decimal(total))
                self.assertEqual(outcome['grade'], expected_grade)

    def test_pass_requires_both_total_and_external_threshold(self):
        passed = self.make_mark(internal_marks=Decimal('12'), external_marks=Decimal('28'))
        passed.save()
        self.assertEqual(passed.result, ExaminationMark.Result.PASS)
        low_total = self.make_mark(
            subject_code='CS202',
            internal_marks=Decimal('11'),
            external_marks=Decimal('28'),
        )
        low_total.save()
        self.assertEqual(low_total.result, ExaminationMark.Result.FAIL)
        low_external = self.make_mark(
            subject_code='CS203',
            internal_marks=Decimal('30'),
            external_marks=Decimal('27.99'),
        )
        low_external.save()
        self.assertEqual(low_external.result, ExaminationMark.Result.FAIL)

    def test_invalid_internal_and_external_marks_are_rejected(self):
        invalid_cases = (
            ({'internal_marks': Decimal('-0.01')}, 'internal_marks'),
            ({'internal_marks': Decimal('30.01')}, 'internal_marks'),
            ({'external_marks': Decimal('-0.01')}, 'external_marks'),
            ({'external_marks': Decimal('70.01')}, 'external_marks'),
        )
        for overrides, field in invalid_cases:
            with self.subTest(overrides=overrides):
                mark = self.make_mark(**overrides)
                with self.assertRaises(ValidationError) as raised:
                    mark.save()
                self.assertIn(field, raised.exception.message_dict)

    def test_duplicate_student_subject_semester_is_rejected_clearly(self):
        self.make_mark().save()
        form = ExaminationMarkForm(
            {
                'student': self.student.pk,
                'subject_code': 'cs201',
                'subject_name': 'Data Structures',
                'semester': 1,
                'internal_marks': '20',
                'external_marks': '60',
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn(
            'Marks already exist for this student, subject code, and semester.',
            form.non_field_errors(),
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ExaminationMark.objects.bulk_create([self.make_mark()])

    def test_marks_are_linked_to_existing_student(self):
        mark = self.make_mark()
        mark.save()
        self.assertEqual(mark.student_id, self.student.pk)
        self.assertEqual(self.student.examination_marks.get(), mark)
        self.assertEqual(ExaminationMark._meta.get_field('student').remote_field.model, Student)


class DepartmentDropdownTests(TestCase):
    def test_course_form_rejects_unlisted_departments_and_keeps_legacy_edit_values(self):
        invalid_form = CourseForm(
            {
                'code': 'NEW101',
                'name': 'New Course',
                'department': 'Unlisted Department',
                'credits': 3,
            }
        )
        self.assertFalse(invalid_form.is_valid())
        self.assertIn('department', invalid_form.errors)

        course = Course.objects.create(
            code='OLD101',
            name='Legacy Course',
            department='Legacy Department',
        )
        edit_form = CourseForm(
            {
                'code': course.code,
                'name': course.name,
                'department': 'Legacy Department',
                'credits': course.credits,
            },
            instance=course,
        )
        self.assertTrue(edit_form.is_valid(), edit_form.errors)


class MarksWorkflowTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_superuser(
            username='test-marks-admin',
            email='test-marks-admin@example.edu',
            password='Test-only-marks-password-592!',
        )
        self.client.force_login(user)
        self.student = Student.objects.create(
            roll_number='STU-WEB-001',
            full_name='Morgan Lee',
            email='morgan.lee@example.edu',
            department='Engineering',
            academic_year='2026-2027',
        )

    def post_data(self, **overrides):
        data = {
            'student': self.student.pk,
            'subject_code': 'EE101',
            'subject_name': 'Circuit Fundamentals',
            'semester': 2,
            'internal_marks': '25.50',
            'external_marks': '60.00',
        }
        data.update(overrides)
        return data

    def add_mark(self, **overrides):
        values = {
            'student': self.student,
            'subject_code': 'EE101',
            'subject_name': 'Circuit Fundamentals',
            'semester': 2,
            'internal_marks': Decimal('25.50'),
            'external_marks': Decimal('60'),
        }
        values.update(overrides)
        mark = ExaminationMark(**values)
        mark.save()
        return mark

    def test_create_edit_and_delete_workflow(self):
        response = self.client.post(reverse('academics:create'), self.post_data())
        self.assertEqual(
            response.status_code,
            302,
            response.context['form'].errors if response.context else response.content[:500],
        )
        mark = ExaminationMark.objects.get(subject_code='EE101')
        self.assertRedirects(response, reverse('academics:detail', args=[mark.pk]))
        self.assertEqual(mark.total_marks, Decimal('85.50'))
        self.assertEqual(mark.grade, 'A')

        edit_response = self.client.post(
            reverse('academics:update', args=[mark.pk]),
            self.post_data(internal_marks='20', external_marks='55'),
        )
        self.assertRedirects(edit_response, reverse('academics:detail', args=[mark.pk]))
        mark.refresh_from_db()
        self.assertEqual(mark.total_marks, Decimal('75'))
        self.assertEqual(mark.grade, 'B')

        self.assertEqual(
            self.client.get(reverse('academics:delete', args=[mark.pk])).status_code,
            200,
        )
        self.assertTrue(ExaminationMark.objects.filter(pk=mark.pk).exists())
        delete_response = self.client.post(reverse('academics:delete', args=[mark.pk]))
        self.assertRedirects(delete_response, reverse('academics:list'))
        self.assertFalse(ExaminationMark.objects.filter(pk=mark.pk).exists())

    def test_search_and_semester_department_result_filters(self):
        self.add_mark()
        other_student = Student.objects.create(
            roll_number='STU-WEB-002',
            full_name='Avery Smith',
            email='avery.smith@example.edu',
            department='Science',
            academic_year='2025-2026',
        )
        ExaminationMark(
            student=other_student,
            subject_code='BIOL202',
            subject_name='Cell Biology',
            semester=3,
            internal_marks=Decimal('10'),
            external_marks=Decimal('25'),
        ).save()
        response = self.client.get(
            reverse('academics:list'),
            {
                'q': 'Morgan',
                'semester': '2',
                'department': 'Engineering',
                'result': 'PASS',
            },
        )
        self.assertContains(response, 'Circuit Fundamentals')
        self.assertNotContains(response, 'Cell Biology')
        self.assertEqual(response.context['page_obj'].paginator.count, 1)

        by_email_and_year = self.client.get(
            reverse('academics:list'),
            {'q': 'avery.smith@example.edu', 'academic_year': '2025-2026'},
        )
        self.assertContains(by_email_and_year, 'Cell Biology')
        self.assertEqual(by_email_and_year.context['page_obj'].paginator.count, 1)
        self.assertEqual(by_email_and_year.context['rules']['internal_max'], 30)
        self.assertContains(by_email_and_year, 'Pass requires at least 40 total')

    def test_list_paginates_and_empty_state_renders(self):
        empty_response = self.client.get(reverse('academics:list'))
        self.assertContains(empty_response, 'No examination marks recorded yet')
        for number in range(13):
            self.add_mark(
                subject_code=f'EE{number:03}',
                subject_name=f'Electrical Subject {number}',
            )
        response = self.client.get(reverse('academics:list'))
        self.assertEqual(response.context['page_obj'].paginator.num_pages, 2)
        self.assertEqual(len(response.context['records']), 12)
        second_page = self.client.get(reverse('academics:list'), {'page': 2})
        self.assertEqual(len(second_page.context['records']), 1)

    def test_dashboard_statistics_are_database_backed(self):
        self.add_mark()
        student_two = Student.objects.create(
            roll_number='STU-WEB-003',
            full_name='Casey Kim',
            email='casey.kim@example.edu',
            department='Arts',
            academic_year='2026-2027',
        )
        ExaminationMark(
            student=student_two,
            subject_code='ART102',
            subject_name='Art History',
            semester=1,
            internal_marks=Decimal('5'),
            external_marks=Decimal('20'),
        ).save()
        response = self.client.get(reverse('students:dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['student_count'], 2)
        self.assertEqual(response.context['marks_count'], 2)
        self.assertEqual(response.context['passed_count'], 1)
        self.assertEqual(response.context['pass_percentage'], 50)
        self.assertContains(response, 'Circuit Fundamentals')
        self.assertContains(response, '50.0%')

    def test_created_values_cannot_be_submitted_from_browser(self):
        data = self.post_data()
        data.update(
            {
                'total_marks': '0',
                'percentage': '0',
                'grade': 'F',
                'result': 'FAIL',
            }
        )
        response = self.client.post(reverse('academics:create'), data)
        self.assertEqual(
            response.status_code,
            302,
            response.context['form'].errors if response.context else response.content[:500],
        )
        mark = ExaminationMark.objects.get(subject_code='EE101')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(mark.total_marks, Decimal('85.50'))
        self.assertEqual(mark.percentage, Decimal('85.50'))
        self.assertEqual(mark.grade, 'A')
        self.assertEqual(mark.result, ExaminationMark.Result.PASS)

    def test_inactive_students_cannot_be_selected_for_new_marks(self):
        inactive_student = Student.objects.create(
            roll_number='STU-INACTIVE-001',
            full_name='Inactive Student',
            email='inactive.marks@example.edu',
            department='Engineering',
            academic_year='2026-2027',
            is_active=False,
        )
        form = ExaminationMarkForm()
        self.assertFalse(form.fields['student'].queryset.filter(pk=inactive_student.pk).exists())


class CampusPortalRegressionTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.admin = user_model.objects.create_superuser(
            username='campus-regression-admin',
            email='campus-regression-admin@example.edu',
            password='Test-only-campus-password-926!',
        )
        self.client.force_login(self.admin)
        self.student = Student.objects.create(
            roll_number='STU-CAMPUS-001',
            full_name='Jamie Student',
            email='jamie.student@example.edu',
            department='Engineering',
            academic_year='2026-2027',
        )

    def test_faculty_can_read_department_scoped_analytics(self):
        faculty = get_user_model().objects.create_user(
            username='engineering-faculty',
            password='Test-only-faculty-password-627!',
        )
        UserProfile.objects.create(
            user=faculty,
            role=UserProfile.Role.FACULTY,
            department='Engineering',
        )
        Student.objects.create(
            roll_number='STU-CAMPUS-002',
            full_name='Other Department Student',
            email='other.student@example.edu',
            department='Arts',
            academic_year='2026-2027',
        )
        self.client.force_login(faculty)

        response = self.client.get(reverse('academics:analytics_data'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['active_students'], 1)
        self.assertEqual(
            response.json()['departments'],
            [{'name': 'Engineering', 'students': 1}],
        )

    def test_students_cannot_read_staff_analytics_endpoint(self):
        student_user = get_user_model().objects.create_user(
            username='campus-student',
            password='Test-only-student-password-229!',
        )
        UserProfile.objects.create(
            user=student_user,
            role=UserProfile.Role.STUDENT,
            student=self.student,
        )
        self.client.force_login(student_user)

        response = self.client.get(reverse('academics:analytics_data'))

        self.assertEqual(response.status_code, 403)

    def test_hod_is_valid_as_the_assigned_class_instructor(self):
        hod_user = get_user_model().objects.create_user(
            username='engineering-hod',
            password='Test-only-hod-password-828!',
        )
        hod_profile = UserProfile.objects.create(
            user=hod_user,
            role=UserProfile.Role.HOD,
            department='Engineering',
        )
        semester = Semester.objects.create(
            academic_year='2026-2027',
            number=1,
            starts_on=date(2026, 8, 1),
            ends_on=date(2026, 12, 31),
            is_active=True,
        )
        course = Course.objects.create(
            code='ENG101',
            name='Engineering Foundations',
            department='Engineering',
        )
        starts_at = timezone.now() + timedelta(days=1)
        session = ClassSession(
            course=course,
            semester=semester,
            faculty=hod_profile,
            room='ENG-101',
            starts_at=starts_at,
            ends_at=starts_at + timedelta(hours=1),
        )

        session.full_clean()

    def test_fee_payment_cannot_overpay_invoice(self):
        invoice = FeeInvoice.objects.create(
            student=self.student,
            fee_type=FeeInvoice.FeeType.TUITION,
            academic_year='2026-2027',
            amount_due=Decimal('100.00'),
            due_date=date(2026, 12, 31),
        )
        FeePayment.objects.create(
            invoice=invoice,
            reference='PAY-CAMPUS-001',
            amount=Decimal('60.00'),
            recorded_by=self.admin,
        )

        response = self.client.post(
            reverse('academics:fee_payment_create', args=[invoice.pk]),
            {'reference': 'PAY-CAMPUS-002', 'amount': '50.00'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(invoice.payments.count(), 1)
        self.assertContains(response, 'outstanding invoice balance')

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_announcement_email_only_targets_matching_active_students(self):
        Student.objects.create(
            roll_number='STU-CAMPUS-003',
            full_name='Another Engineering Student',
            email='another.engineering@example.edu',
            department='Engineering',
            academic_year='2026-2027',
        )
        Student.objects.create(
            roll_number='STU-CAMPUS-004',
            full_name='Arts Student',
            email='arts.student@example.edu',
            department='Arts',
            academic_year='2026-2027',
        )

        response = self.client.post(
            reverse('academics:announcement_create'),
            {
                'title': 'Engineering update',
                'body': 'Please review the updated schedule.',
                'department': 'Engineering',
                'academic_year': '2026-2027',
                'student': '',
                'send_email': 'on',
            },
        )

        self.assertRedirects(response, reverse('academics:announcement_list'))
        self.assertEqual(Announcement.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(
            {message.to[0] for message in mail.outbox},
            {'jamie.student@example.edu', 'another.engineering@example.edu'},
        )
