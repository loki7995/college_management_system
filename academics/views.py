from datetime import timedelta
import logging
from smtplib import SMTPException

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.mail import send_mass_mail
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Avg, Count, DecimalField, F, Q, Sum, Value
from django.db.models.functions import Coalesce, TruncMonth
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from accounts.audit import capture_fields, record_change
from accounts.models import UserProfile
from accounts.permissions import (
    get_user_role,
    roles_required,
    visible_marks,
    visible_students,
)
from students.models import Student
from .forms import (
    AnnouncementForm,
    CampusEventForm,
    ClassSessionForm,
    CourseEnrollmentForm,
    CourseForm,
    ExaminationMarkForm,
    FeeInvoiceForm,
    FeePaymentForm,
    SemesterForm,
)
from .models import (
    Announcement,
    AttendanceRecord,
    CampusEvent,
    ClassSession,
    Course,
    CourseEnrollment,
    ExaminationMark,
    FeeInvoice,
    FeePayment,
    Semester,
)

logger = logging.getLogger(__name__)


@roles_required(
    UserProfile.Role.ADMIN,
    UserProfile.Role.REGISTRAR,
    UserProfile.Role.HOD,
    UserProfile.Role.FACULTY,
    UserProfile.Role.STUDENT,
)
def mark_list(request):
    all_records = visible_marks(request.user).select_related('student')
    records = all_records
    students = visible_students(request.user)
    query = request.GET.get('q', '').strip()
    semester = request.GET.get('semester', '').strip()
    department = request.GET.get('department', '').strip()
    result = request.GET.get('result', '').strip()
    academic_year = request.GET.get('academic_year', '').strip()

    if query:
        records = records.filter(
            Q(student__roll_number__icontains=query)
            | Q(student__full_name__icontains=query)
            | Q(student__email__icontains=query)
            | Q(subject_code__icontains=query)
            | Q(subject_name__icontains=query)
        )
    if semester.isdigit() and 1 <= int(semester) <= 12:
        records = records.filter(semester=int(semester))
    else:
        semester = ''
    departments = list(
        all_records.order_by('student__department')
        .values_list('student__department', flat=True)
        .distinct()
    )
    if department not in departments:
        department = ''
    if department:
        records = records.filter(student__department=department)
    else:
        department = ''
    if result in ExaminationMark.Result.values:
        records = records.filter(result=result)
    else:
        result = ''
    academic_years = list(
        students.order_by('academic_year')
        .values_list('academic_year', flat=True)
        .distinct()
    )
    if academic_year not in academic_years:
        academic_year = ''
    if academic_year:
        records = records.filter(student__academic_year=academic_year)

    paginator = Paginator(records, 12)
    page_obj = paginator.get_page(request.GET.get('page'))
    query_params = request.GET.copy()
    query_params.pop('page', None)
    context = {
        'page_obj': page_obj,
        'records': page_obj.object_list,
        'query': query,
        'selected_semester': semester,
        'selected_department': department,
        'selected_result': result,
        'selected_academic_year': academic_year,
        'departments': departments,
        'academic_year_choices': academic_years,
        'semester_choices': ExaminationMark._meta.get_field('semester').choices,
        'result_choices': ExaminationMark.Result.choices,
        'rules': settings.ACADEMIC_MARKS_RULES,
        'query_string': query_params.urlencode(),
        'student_count': students.count(),
        'marks_count': all_records.count(),
    }
    return render(request, 'academics/mark_list.html', context)


@roles_required(
    UserProfile.Role.ADMIN,
    UserProfile.Role.REGISTRAR,
    UserProfile.Role.HOD,
    UserProfile.Role.FACULTY,
    UserProfile.Role.STUDENT,
)
def mark_detail(request, pk):
    record = get_object_or_404(
        visible_marks(request.user).select_related('student'),
        pk=pk,
    )
    return render(
        request,
        'academics/mark_detail.html',
        {
            'record': record,
            'student_count': visible_students(request.user).count(),
            'marks_count': visible_marks(request.user).count(),
            'rules': settings.ACADEMIC_MARKS_RULES,
        },
    )


@roles_required(
    UserProfile.Role.ADMIN,
    UserProfile.Role.REGISTRAR,
    UserProfile.Role.HOD,
    UserProfile.Role.FACULTY,
)
def mark_create(request):
    if request.method == 'POST':
        form = ExaminationMarkForm(request.POST, user=request.user)
        if form.is_valid():
            try:
                with transaction.atomic():
                    record = form.save()
                    record_change(request, record, 'CREATE')
            except IntegrityError:
                form.add_error(
                    None,
                    'Marks already exist for this student, subject code, and semester.',
                )
            except ValidationError as error:
                for field, field_errors in error.message_dict.items():
                    for message in field_errors:
                        form.add_error(field if field in form.fields else None, message)
            else:
                messages.success(request, 'Examination marks were added successfully.')
                return redirect('academics:detail', pk=record.pk)
    else:
        form = ExaminationMarkForm(user=request.user)
    return render(
        request,
        'academics/mark_form.html',
        _form_context(form, 'Add examination marks', 'Save marks'),
    )


@roles_required(
    UserProfile.Role.ADMIN,
    UserProfile.Role.REGISTRAR,
    UserProfile.Role.HOD,
    UserProfile.Role.FACULTY,
)
def mark_update(request, pk):
    record = get_object_or_404(
        visible_marks(request.user).select_related('student'),
        pk=pk,
    )
    if request.method == 'POST':
        form = ExaminationMarkForm(request.POST, instance=record, user=request.user)
        if form.is_valid():
            try:
                with transaction.atomic():
                    before = capture_fields(record)
                    record = form.save()
                    record_change(request, record, 'UPDATE', before)
            except IntegrityError:
                form.add_error(
                    None,
                    'Marks already exist for this student, subject code, and semester.',
                )
            except ValidationError as error:
                for field, field_errors in error.message_dict.items():
                    for message in field_errors:
                        form.add_error(field if field in form.fields else None, message)
            else:
                messages.success(request, 'Examination marks were updated successfully.')
                return redirect('academics:detail', pk=record.pk)
    else:
        form = ExaminationMarkForm(instance=record, user=request.user)
    return render(
        request,
        'academics/mark_form.html',
        _form_context(form, 'Edit examination marks', 'Save changes', record),
    )


@roles_required(
    UserProfile.Role.ADMIN,
    UserProfile.Role.REGISTRAR,
    UserProfile.Role.HOD,
)
def mark_delete(request, pk):
    record = get_object_or_404(
        visible_marks(request.user).select_related('student'),
        pk=pk,
    )
    if request.method == 'POST':
        label = f'{record.subject_code} — {record.student.full_name}'
        before = capture_fields(record)
        record_change(request, record, 'DELETE', before)
        record.delete()
        messages.success(request, f'Marks for {label} were removed.')
        return redirect('academics:list')
    return render(
        request,
        'academics/mark_confirm_delete.html',
        {
            'record': record,
            'student_count': visible_students(request.user).count(),
            'marks_count': visible_marks(request.user).count(),
        },
    )


def _form_context(form, page_title, submit_label, record=None):
    return {
        'form': form,
        'record': record,
        'page_title': page_title,
        'submit_label': submit_label,
        'student_count': visible_students(form.user).count() if hasattr(form, 'user') else 0,
        'marks_count': visible_marks(form.user).count() if hasattr(form, 'user') else 0,
        'rules': settings.ACADEMIC_MARKS_RULES,
    }


@roles_required(
    UserProfile.Role.ADMIN,
    UserProfile.Role.REGISTRAR,
    UserProfile.Role.HOD,
    UserProfile.Role.FACULTY,
    UserProfile.Role.STUDENT,
)
def course_list(request):
    courses = Course.objects.filter(is_active=True)
    role = get_user_role(request.user)
    if role in (UserProfile.Role.HOD, UserProfile.Role.FACULTY):
        courses = courses.filter(department=request.user.role_profile.department)
    elif role == UserProfile.Role.STUDENT:
        courses = courses.filter(
            enrollments__student_id=request.user.role_profile.student_id
        ).distinct()
    query = request.GET.get('q', '').strip()[:100]
    if query:
        courses = courses.filter(
            Q(code__icontains=query)
            | Q(name__icontains=query)
            | Q(department__icontains=query)
        )
    page_obj = Paginator(courses.order_by('department', 'code'), 20).get_page(
        request.GET.get('page')
    )
    return render(
        request,
        'academics/module_list.html',
        {
            'page_title': 'Courses',
            'page_description': 'Courses available to your role and department.',
            'records': page_obj.object_list,
            'page_obj': page_obj,
            'query': query,
            'can_add': role in (UserProfile.Role.ADMIN, UserProfile.Role.REGISTRAR),
            'list_kind': 'course',
        },
    )


@roles_required(UserProfile.Role.ADMIN, UserProfile.Role.REGISTRAR)
def course_create(request):
    form = CourseForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            with transaction.atomic():
                record = form.save()
                record_change(request, record, 'CREATE')
        except IntegrityError:
            form.add_error('code', 'A course with this code already exists.')
        except ValidationError as error:
            for field, errors in error.message_dict.items():
                for message in errors:
                    form.add_error(field if field in form.fields else None, message)
        else:
            messages.success(request, 'Course created.')
            return redirect('academics:course_list')
    return render(
        request,
        'academics/module_form.html',
        {'page_title': 'Add course', 'form': form, 'submit_label': 'Save course'},
    )


@roles_required(
    UserProfile.Role.ADMIN,
    UserProfile.Role.REGISTRAR,
    UserProfile.Role.HOD,
    UserProfile.Role.FACULTY,
    UserProfile.Role.STUDENT,
)
def course_detail(request, pk):
    course = get_object_or_404(Course.objects.filter(is_active=True), pk=pk)
    role = get_user_role(request.user)
    if role in (UserProfile.Role.HOD, UserProfile.Role.FACULTY):
        if course.department != request.user.role_profile.department:
            raise PermissionDenied
    elif role == UserProfile.Role.STUDENT:
        enrolled = CourseEnrollment.objects.filter(
            course=course,
            student_id=request.user.role_profile.student_id,
        ).exists()
        if not enrolled:
            raise PermissionDenied
    enrollments = CourseEnrollment.objects.filter(course=course).select_related(
        'student', 'semester'
    )
    if role == UserProfile.Role.STUDENT:
        enrollments = enrollments.filter(
            student_id=request.user.role_profile.student_id
        )
    return render(
        request,
        'academics/course_detail.html',
        {
            'course': course,
            'enrollments': enrollments,
            'sessions': _visible_sessions(request.user).filter(course=course),
            'enrollment_form': (
                CourseEnrollmentForm(course=course, user=request.user)
                if role in (
                    UserProfile.Role.ADMIN,
                    UserProfile.Role.REGISTRAR,
                    UserProfile.Role.HOD,
                )
                else None
            ),
            'can_enroll': role in (
                UserProfile.Role.ADMIN,
                UserProfile.Role.REGISTRAR,
                UserProfile.Role.HOD,
            ),
        },
    )


@roles_required(
    UserProfile.Role.ADMIN,
    UserProfile.Role.REGISTRAR,
    UserProfile.Role.HOD,
)
def course_enroll_student(request, pk):
    course = get_object_or_404(Course, pk=pk, is_active=True)
    if (
        get_user_role(request.user) == UserProfile.Role.HOD
        and course.department.casefold()
        != request.user.role_profile.department.casefold()
    ):
        raise PermissionDenied
    form = CourseEnrollmentForm(
        request.POST or None,
        course=course,
        user=request.user,
    )
    if request.method == 'POST' and form.is_valid():
        try:
            with transaction.atomic():
                enrollment = form.save()
                record_change(request, enrollment, 'CREATE')
        except IntegrityError:
            form.add_error(
                None,
                'This student is already enrolled in the selected course and semester.',
            )
        except ValidationError as error:
            for field, errors in error.message_dict.items():
                for message in errors:
                    form.add_error(field if field in form.fields else None, message)
        else:
            messages.success(request, 'Student enrolled in the course.')
            return redirect('academics:course_detail', pk=course.pk)
    return render(
        request,
        'academics/course_detail.html',
        {
            'course': course,
            'enrollments': CourseEnrollment.objects.filter(course=course).select_related(
                'student', 'semester'
            ),
            'sessions': _visible_sessions(request.user).filter(course=course),
            'enrollment_form': form,
            'can_enroll': True,
        },
    )


@roles_required(
    UserProfile.Role.ADMIN,
    UserProfile.Role.REGISTRAR,
    UserProfile.Role.HOD,
    UserProfile.Role.FACULTY,
    UserProfile.Role.STUDENT,
)
def semester_list(request):
    role = get_user_role(request.user)
    semesters = Semester.objects.all()
    if role == UserProfile.Role.STUDENT:
        enrolled_semester_ids = CourseEnrollment.objects.filter(
            student_id=request.user.role_profile.student_id
        ).values('semester_id')
        semesters = semesters.filter(
            Q(is_active=True) | Q(pk__in=enrolled_semester_ids)
        )
    page_obj = Paginator(semesters, 20).get_page(request.GET.get('page'))
    return render(
        request,
        'academics/module_list.html',
        {
            'page_title': 'Semesters',
            'page_description': 'Academic calendars and active semesters.',
            'records': page_obj.object_list,
            'page_obj': page_obj,
            'can_add': role in (UserProfile.Role.ADMIN, UserProfile.Role.REGISTRAR),
            'list_kind': 'semester',
        },
    )


@roles_required(UserProfile.Role.ADMIN, UserProfile.Role.REGISTRAR)
def semester_create(request):
    form = SemesterForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            with transaction.atomic():
                record = form.save()
                record_change(request, record, 'CREATE')
        except IntegrityError:
            form.add_error(None, 'This academic year and semester number already exist.')
        except ValidationError as error:
            for field, errors in error.message_dict.items():
                for message in errors:
                    form.add_error(field if field in form.fields else None, message)
        else:
            messages.success(request, 'Semester created.')
            return redirect('academics:semester_list')
    return render(
        request,
        'academics/module_form.html',
        {'page_title': 'Add semester', 'form': form, 'submit_label': 'Save semester'},
    )


def _visible_sessions(user):
    role = get_user_role(user)
    sessions = ClassSession.objects.select_related(
        'course', 'semester', 'faculty__user'
    )
    if role in (UserProfile.Role.ADMIN, UserProfile.Role.REGISTRAR):
        return sessions
    if role == UserProfile.Role.HOD:
        return sessions.filter(course__department=user.role_profile.department)
    if role == UserProfile.Role.FACULTY:
        return sessions.filter(faculty=user.role_profile)
    raise PermissionDenied


@roles_required(
    UserProfile.Role.ADMIN,
    UserProfile.Role.REGISTRAR,
    UserProfile.Role.HOD,
    UserProfile.Role.FACULTY,
)
def session_list(request):
    sessions = _visible_sessions(request.user)
    query = request.GET.get('q', '').strip()[:100]
    if query:
        sessions = sessions.filter(
            Q(course__code__icontains=query)
            | Q(course__name__icontains=query)
            | Q(room__icontains=query)
            | Q(faculty__user__username__icontains=query)
        )
    page_obj = Paginator(sessions, 20).get_page(request.GET.get('page'))
    return render(
        request,
        'academics/module_list.html',
        {
            'page_title': 'Attendance & timetable',
            'page_description': 'Scheduled classes and attendance sessions.',
            'records': page_obj.object_list,
            'page_obj': page_obj,
            'query': query,
            'can_add': get_user_role(request.user) in (
                UserProfile.Role.ADMIN,
                UserProfile.Role.REGISTRAR,
                UserProfile.Role.HOD,
            ),
            'list_kind': 'session',
        },
    )


@roles_required(
    UserProfile.Role.ADMIN,
    UserProfile.Role.REGISTRAR,
    UserProfile.Role.HOD,
)
def session_create(request):
    form = ClassSessionForm(request.POST or None, user=request.user)
    if request.method == 'POST' and form.is_valid():
        try:
            with transaction.atomic():
                record = form.save()
                record_change(request, record, 'CREATE')
        except IntegrityError:
            form.add_error(None, 'The class could not be saved because of a conflicting record.')
        except ValidationError as error:
            for field, errors in error.message_dict.items():
                for message in errors:
                    form.add_error(field if field in form.fields else None, message)
        else:
            messages.success(request, 'Class session scheduled.')
            return redirect('academics:session_list')
    return render(
        request,
        'academics/module_form.html',
        {
            'page_title': 'Schedule a class',
            'form': form,
            'submit_label': 'Schedule class',
        },
    )


@roles_required(
    UserProfile.Role.ADMIN,
    UserProfile.Role.REGISTRAR,
    UserProfile.Role.HOD,
    UserProfile.Role.FACULTY,
)
def attendance_grid(request, pk):
    session = get_object_or_404(_visible_sessions(request.user), pk=pk)
    enrolled_students = Student.objects.filter(
        course_enrollments__course=session.course,
        course_enrollments__semester=session.semester,
        is_active=True,
    ).distinct().order_by('roll_number')
    records_by_student = {
        record.student_id: record
        for record in AttendanceRecord.objects.filter(session=session)
    }
    if request.method == 'POST':
        role = get_user_role(request.user)
        if role == UserProfile.Role.FACULTY and session.faculty_id != request.user.role_profile.pk:
            raise PermissionDenied
        updates = []
        for student in enrolled_students:
            status = request.POST.get(f'student_{student.pk}', AttendanceRecord.Status.PRESENT)
            if status not in AttendanceRecord.Status.values:
                messages.error(request, 'Choose a valid attendance status for each student.')
                break
            record = records_by_student.get(student.pk) or AttendanceRecord(
                session=session,
                student=student,
            )
            before = capture_fields(record) if record.pk else None
            record.status = status
            record.marked_by = request.user
            try:
                record.full_clean()
            except ValidationError as error:
                for errors in error.message_dict.values():
                    for message in errors:
                        messages.error(request, message)
                break
            updates.append((record, before))
        else:
            with transaction.atomic():
                for record, before in updates:
                    record.save()
                    record_change(
                        request,
                        record,
                        'UPDATE' if before else 'CREATE',
                        before,
                    )
            messages.success(request, 'Attendance was saved for the enrolled students.')
            return redirect('academics:attendance', pk=session.pk)
    return render(
        request,
        'academics/attendance_grid.html',
        {
            'session': session,
            'students': [
                {
                    'student': student,
                    'attendance': records_by_student.get(student.pk),
                }
                for student in enrolled_students
            ],
            'status_choices': AttendanceRecord.Status.choices,
            'student_count': enrolled_students.count(),
        },
    )


def _visible_invoices(user):
    role = get_user_role(user)
    invoices = FeeInvoice.objects.select_related('student').prefetch_related('payments')
    if role in (UserProfile.Role.ADMIN, UserProfile.Role.FINANCE):
        return invoices
    if role == UserProfile.Role.STUDENT:
        return invoices.filter(student_id=user.role_profile.student_id)
    raise PermissionDenied


@roles_required(UserProfile.Role.ADMIN, UserProfile.Role.FINANCE, UserProfile.Role.STUDENT)
def fee_list(request):
    invoices = _visible_invoices(request.user).annotate(
        total_paid=Coalesce(
            Sum('payments__amount'),
            Value(0),
            output_field=DecimalField(max_digits=12, decimal_places=2),
        )
    )
    query = request.GET.get('q', '').strip()[:100]
    status = request.GET.get('status', '').strip()
    if query:
        invoices = invoices.filter(
            Q(receipt_number__icontains=query)
            | Q(student__roll_number__icontains=query)
            | Q(student__full_name__icontains=query)
        )
    if status in ('PAID', 'PARTIAL', 'PENDING', 'OVERDUE'):
        if status == 'PAID':
            invoices = invoices.filter(total_paid__gte=F('amount_due'))
        elif status == 'PARTIAL':
            invoices = invoices.filter(total_paid__gt=0, total_paid__lt=F('amount_due'))
        elif status == 'PENDING':
            invoices = invoices.filter(total_paid=0, due_date__gte=timezone.localdate())
        else:
            invoices = invoices.filter(total_paid=0, due_date__lt=timezone.localdate())
    page_obj = Paginator(invoices.order_by('due_date'), 20).get_page(
        request.GET.get('page')
    )
    return render(
        request,
        'academics/module_list.html',
        {
            'page_title': 'Invoices & fees',
            'page_description': 'Fee invoices and recorded payments.',
            'records': page_obj.object_list,
            'page_obj': page_obj,
            'query': query,
            'can_add': get_user_role(request.user) in (
                UserProfile.Role.ADMIN,
                UserProfile.Role.FINANCE,
            ),
            'list_kind': 'fee',
        },
    )


@roles_required(UserProfile.Role.ADMIN, UserProfile.Role.FINANCE)
def fee_create(request):
    form = FeeInvoiceForm(request.POST or None, user=request.user)
    if request.method == 'POST' and form.is_valid():
        try:
            with transaction.atomic():
                record = form.save()
                record_change(request, record, 'CREATE')
        except ValidationError as error:
            for field, errors in error.message_dict.items():
                for message in errors:
                    form.add_error(field if field in form.fields else None, message)
        else:
            messages.success(request, 'Fee invoice created.')
            return redirect('academics:fee_detail', pk=record.pk)
    return render(
        request,
        'academics/module_form.html',
        {'page_title': 'Create fee invoice', 'form': form, 'submit_label': 'Create invoice'},
    )


@roles_required(UserProfile.Role.ADMIN, UserProfile.Role.FINANCE, UserProfile.Role.STUDENT)
def fee_detail(request, pk):
    invoice = get_object_or_404(_visible_invoices(request.user), pk=pk)
    return render(
        request,
        'academics/invoice_detail.html',
        {
            'invoice': invoice,
            'payments': invoice.payments.select_related('recorded_by'),
            'can_record_payment': get_user_role(request.user) in (
                UserProfile.Role.ADMIN,
                UserProfile.Role.FINANCE,
            ),
            'payment_form': FeePaymentForm(invoice=invoice),
        },
    )


@roles_required(UserProfile.Role.ADMIN, UserProfile.Role.FINANCE)
def fee_payment_create(request, pk):
    invoice = get_object_or_404(_visible_invoices(request.user), pk=pk)
    form = FeePaymentForm(request.POST or None, invoice=invoice)
    if request.method == 'POST':
        payment_saved = False
        try:
            with transaction.atomic():
                invoice = FeeInvoice.objects.select_for_update().get(pk=invoice.pk)
                form = FeePaymentForm(request.POST, invoice=invoice)
                if form.is_valid():
                    payment = form.save(commit=False)
                    payment.invoice = invoice
                    payment.recorded_by = request.user
                    payment.full_clean()
                    payment.save()
                    record_change(request, payment, 'CREATE')
                    payment_saved = True
        except IntegrityError:
            form.add_error('reference', 'This payment reference has already been recorded.')
        except ValidationError as error:
            for field, errors in error.message_dict.items():
                for message in errors:
                    form.add_error(field if field in form.fields else None, message)
        if payment_saved:
            messages.success(request, 'Payment recorded.')
            return redirect('academics:fee_detail', pk=invoice.pk)
    return render(
        request,
        'academics/invoice_detail.html',
        {
            'invoice': invoice,
            'payments': invoice.payments.select_related('recorded_by'),
            'can_record_payment': True,
            'payment_form': form,
        },
    )


@roles_required(
    UserProfile.Role.ADMIN,
    UserProfile.Role.REGISTRAR,
    UserProfile.Role.HOD,
    UserProfile.Role.FACULTY,
    UserProfile.Role.STUDENT,
)
def event_list(request):
    role = get_user_role(request.user)
    events = CampusEvent.objects.all()
    department = ''
    if role in (UserProfile.Role.HOD, UserProfile.Role.FACULTY):
        department = request.user.role_profile.department
    elif role == UserProfile.Role.STUDENT:
        department = request.user.role_profile.student.department
    if department:
        events = events.filter(Q(department='') | Q(department=department))
    page_obj = Paginator(events, 20).get_page(request.GET.get('page'))
    return render(
        request,
        'academics/module_list.html',
        {
            'page_title': 'Campus events',
            'page_description': 'Upcoming examinations and campus events.',
            'records': page_obj.object_list,
            'page_obj': page_obj,
            'can_add': role in (UserProfile.Role.ADMIN, UserProfile.Role.REGISTRAR),
            'list_kind': 'event',
        },
    )


@roles_required(UserProfile.Role.ADMIN, UserProfile.Role.REGISTRAR)
def event_create(request):
    form = CampusEventForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        record = form.save(commit=False)
        record.created_by = request.user
        try:
            with transaction.atomic():
                record.full_clean()
                record.save()
                record_change(request, record, 'CREATE')
        except ValidationError as error:
            for field, errors in error.message_dict.items():
                for message in errors:
                    form.add_error(field if field in form.fields else None, message)
        else:
            messages.success(request, 'Campus event created.')
            return redirect('academics:event_list')
    return render(
        request,
        'academics/module_form.html',
        {'page_title': 'Add campus event', 'form': form, 'submit_label': 'Save event'},
    )


@roles_required(
    UserProfile.Role.ADMIN,
    UserProfile.Role.REGISTRAR,
    UserProfile.Role.HOD,
    UserProfile.Role.FACULTY,
    UserProfile.Role.STUDENT,
)
def announcement_list(request):
    role = get_user_role(request.user)
    announcements = Announcement.objects.select_related('student', 'created_by')
    if role == UserProfile.Role.STUDENT:
        student = request.user.role_profile.student
        announcements = announcements.filter(
            Q(student=student)
            | (
                Q(student__isnull=True)
                & (Q(department='') | Q(department=student.department))
                & (Q(academic_year='') | Q(academic_year=student.academic_year))
            )
        )
    elif role in (UserProfile.Role.HOD, UserProfile.Role.FACULTY):
        announcements = announcements.filter(
            Q(student__isnull=True)
            & (Q(department='') | Q(department=request.user.role_profile.department))
        )
    page_obj = Paginator(announcements, 20).get_page(request.GET.get('page'))
    return render(
        request,
        'academics/module_list.html',
        {
            'page_title': 'Announcements',
            'page_description': 'College notices shared with your role.',
            'records': page_obj.object_list,
            'page_obj': page_obj,
            'can_add': role in (UserProfile.Role.ADMIN, UserProfile.Role.REGISTRAR),
            'list_kind': 'announcement',
        },
    )


@roles_required(UserProfile.Role.ADMIN, UserProfile.Role.REGISTRAR)
def announcement_create(request):
    form = AnnouncementForm(request.POST or None, user=request.user)
    if request.method == 'POST' and form.is_valid():
        record = form.save(commit=False)
        record.created_by = request.user
        try:
            with transaction.atomic():
                record.full_clean()
                record.save()
                record_change(request, record, 'CREATE')
        except ValidationError as error:
            for field, errors in error.message_dict.items():
                for message in errors:
                    form.add_error(field if field in form.fields else None, message)
        else:
            messages.success(request, 'Announcement published.')
            if record.send_email:
                recipients = Student.objects.filter(is_active=True).exclude(email='').order_by().values_list(
                    'email', flat=True
                )
                if record.student_id:
                    recipients = recipients.filter(pk=record.student_id)
                else:
                    if record.department:
                        recipients = recipients.filter(department__iexact=record.department)
                    if record.academic_year:
                        recipients = recipients.filter(academic_year=record.academic_year)
                recipient_list = list(recipients.distinct())
                if not recipient_list:
                    messages.warning(
                        request,
                        'The announcement was published, but no active student email addresses matched its target.',
                    )
                else:
                    safe_subject = ' '.join(record.title.splitlines()).strip()
                    messages_to_send = [
                        (
                            safe_subject,
                            record.body,
                            settings.DEFAULT_FROM_EMAIL,
                            [recipient],
                        )
                        for recipient in recipient_list
                    ]
                    try:
                        sent_count = send_mass_mail(
                            messages_to_send,
                            fail_silently=False,
                        )
                    except (OSError, SMTPException) as error:
                        logger.warning(
                            'Announcement email dispatch failed for announcement %s (%s).',
                            record.pk,
                            type(error).__name__,
                        )
                        messages.error(
                            request,
                            'The announcement was published, but email delivery failed. Check the configured email backend and server logs.',
                        )
                    else:
                        messages.info(
                            request,
                            f'Email delivery was accepted for {sent_count} of {len(recipient_list)} targeted student(s).',
                        )
            return redirect('academics:announcement_list')
    return render(
        request,
        'academics/module_form.html',
        {
            'page_title': 'Publish announcement',
            'form': form,
            'submit_label': 'Publish announcement',
        },
    )


@roles_required(
    UserProfile.Role.ADMIN,
    UserProfile.Role.REGISTRAR,
    UserProfile.Role.HOD,
    UserProfile.Role.FACULTY,
)
def analytics_data(request):
    role = get_user_role(request.user)
    now = timezone.now()
    students = visible_students(request.user).filter(is_active=True)
    if role == UserProfile.Role.HOD:
        students = students.filter(department=request.user.role_profile.department)
    departments = list(
        students.values('department')
        .order_by('department')
        .annotate(total=Count('pk'))
    )
    attendance = AttendanceRecord.objects.filter(
        session__starts_at__gte=now - timedelta(days=180)
    ).exclude(status=AttendanceRecord.Status.EXCUSED)
    marks = visible_marks(request.user)
    if role in (UserProfile.Role.HOD, UserProfile.Role.FACULTY):
        attendance = attendance.filter(
            session__course__department=request.user.role_profile.department
        )
    attendance_months = list(
        attendance.annotate(month=TruncMonth('session__starts_at'))
        .values('month')
        .annotate(
            present=Count('pk', filter=Q(status=AttendanceRecord.Status.PRESENT)),
            total=Count('pk'),
        )
        .order_by('month')
    )
    semester_results = list(
        marks.values('semester')
        .annotate(
            average=Avg('percentage'),
            passed=Count('pk', filter=Q(result=ExaminationMark.Result.PASS)),
            total=Count('pk'),
        )
        .order_by('semester')
    )
    fee_statuses = None
    if role in (UserProfile.Role.ADMIN, UserProfile.Role.REGISTRAR):
        invoices = FeeInvoice.objects.annotate(
            total_paid=Coalesce(
                Sum('payments__amount'),
                Value(0),
                output_field=DecimalField(max_digits=12, decimal_places=2),
            )
        )
        fee_statuses = invoices.aggregate(
            paid=Count('pk', filter=Q(total_paid__gte=F('amount_due'))),
            partial=Count(
                'pk',
                filter=Q(total_paid__gt=0, total_paid__lt=F('amount_due')),
            ),
            overdue=Count(
                'pk',
                filter=Q(total_paid=0, due_date__lt=timezone.localdate()),
            ),
            pending=Count(
                'pk',
                filter=Q(total_paid=0, due_date__gte=timezone.localdate()),
            ),
        )
    return JsonResponse(
        {
            'active_students': students.count(),
            'departments': [
                {'name': item['department'], 'students': item['total']}
                for item in departments
            ],
            'upcoming_events': CampusEvent.objects.filter(
                starts_at__gte=now
            ).filter(
                Q(department='') | Q(department=request.user.role_profile.department)
            ).count()
            if role in (UserProfile.Role.HOD, UserProfile.Role.FACULTY)
            else CampusEvent.objects.filter(starts_at__gte=now).count(),
            'attendance_months': [
                {
                    'month': item['month'].strftime('%b %Y'),
                    'present': item['present'],
                    'total': item['total'],
                }
                for item in attendance_months
            ],
            'semester_results': [
                {
                    'semester': item['semester'],
                    'average_percentage': float(item['average'] or 0),
                    'pass_rate': (
                        round(item['passed'] * 100 / item['total'], 1)
                        if item['total']
                        else 0
                    ),
                }
                for item in semester_results
            ],
            'fee_statuses': fee_statuses,
        }
    )
