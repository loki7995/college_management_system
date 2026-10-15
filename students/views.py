from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.db.models.deletion import ProtectedError
from django.db.models import Avg, Count, Q, Window
from django.http import Http404
from django.utils import timezone

from accounts.audit import capture_fields, record_change
from accounts.models import UserProfile
from accounts.permissions import (
    get_user_role,
    roles_required,
    visible_marks,
    visible_students,
)
from academics.models import (
    Announcement,
    AttendanceRecord,
    CampusEvent,
    CourseEnrollment,
    ExaminationMark,
    FeeInvoice,
    FeePayment,
)

from .forms import StudentDocumentForm, StudentForm
from .models import Student, StudentDocument


@roles_required(
    UserProfile.Role.ADMIN,
    UserProfile.Role.REGISTRAR,
    UserProfile.Role.HOD,
    UserProfile.Role.FACULTY,
    UserProfile.Role.STUDENT,
    UserProfile.Role.FINANCE,
)
def dashboard(request):
    role = get_user_role(request.user)
    if role == UserProfile.Role.FINANCE:
        invoices = FeeInvoice.objects.select_related('student').prefetch_related('payments')
        amount_due = invoices.aggregate(due=Sum('amount_due'))['due'] or 0
        amount_collected = FeePayment.objects.aggregate(paid=Sum('amount'))['paid'] or 0
        return render(
            request,
            'students/finance_dashboard.html',
            {
                'invoice_count': invoices.count(),
                'amount_due': amount_due,
                'amount_collected': amount_collected,
                'recent_invoices': invoices.order_by('-created_at')[:8],
                'upcoming_events': CampusEvent.objects.filter(
                    starts_at__gte=timezone.now()
                ).order_by('starts_at')[:5],
            },
        )
    if role == UserProfile.Role.STUDENT:
        student = request.user.role_profile.student
        student_marks = student.examination_marks.order_by('-created_at', '-pk')
        summary = student_marks.aggregate(
            total=Count('pk'),
            passed=Count('pk', filter=Q(result=ExaminationMark.Result.PASS)),
            failed=Count('pk', filter=Q(result=ExaminationMark.Result.FAIL)),
            average=Avg('percentage'),
        )
        return render(
            request,
            'students/student_dashboard.html',
            {
                'student': student,
                'marks_count': summary['total'],
                'passed_count': summary['passed'],
                'failed_count': summary['failed'],
                'average_percentage': summary['average'],
                'pass_percentage': (
                    round(summary['passed'] * 100 / summary['total'], 1)
                    if summary['total']
                    else 0
                ),
                'recent_results': student_marks[:10],
            },
        )

    students = visible_students(request.user).filter(is_active=True)
    marks = visible_marks(request.user, ExaminationMark.objects.all())
    faculty_profiles = UserProfile.objects.filter(
        role__in=(UserProfile.Role.FACULTY, UserProfile.Role.HOD)
    ).select_related('user')
    if role in (UserProfile.Role.FACULTY, UserProfile.Role.HOD):
        faculty_profiles = faculty_profiles.filter(
            department=request.user.role_profile.department
        )
    department_count = students.values_list('department', flat=True).order_by().union(
        faculty_profiles.values_list('department', flat=True).order_by()
    ).count()
    marks_summary = marks.aggregate(
        total=Count('pk'),
        passed=Count('pk', filter=Q(result=ExaminationMark.Result.PASS)),
        failed=Count('pk', filter=Q(result=ExaminationMark.Result.FAIL)),
    )
    department_counts = list(
        students.values('department')
        .annotate(student_count=Count('pk'))
        .order_by('-student_count', 'department')[:6]
    )
    today_records = AttendanceRecord.objects.filter(
        session__starts_at__date=timezone.localdate()
    ).exclude(status=AttendanceRecord.Status.EXCUSED)
    if role in (UserProfile.Role.HOD, UserProfile.Role.FACULTY):
        today_records = today_records.filter(
            session__course__department=request.user.role_profile.department
        )
    attendance_summary = today_records.aggregate(
        total=Count('pk'),
        present=Count('pk', filter=Q(status=AttendanceRecord.Status.PRESENT)),
    )
    attendance_percentage = (
        round(attendance_summary['present'] * 100 / attendance_summary['total'], 1)
        if attendance_summary['total']
        else 0
    )
    upcoming_events = CampusEvent.objects.filter(
        starts_at__gte=timezone.now()
    )
    if role in (UserProfile.Role.HOD, UserProfile.Role.FACULTY):
        upcoming_events = upcoming_events.filter(
            Q(department='') | Q(department=request.user.role_profile.department)
        )
    invoice_summary = {'due': None, 'paid': None}
    if role in (UserProfile.Role.ADMIN, UserProfile.Role.REGISTRAR):
        invoice_summary = {
            'due': FeeInvoice.objects.aggregate(due=Sum('amount_due'))['due'],
            'paid': FeePayment.objects.aggregate(paid=Sum('amount'))['paid'],
        }
    max_department_count = max(
        (item['student_count'] for item in department_counts),
        default=0,
    )
    for item in department_counts:
        item['bar_width'] = round(item['student_count'] * 100 / max_department_count)

    recent_students = list(
        students.annotate(student_total=Window(expression=Count('pk')))
        .order_by('-created_at', 'pk')[:5]
    )
    recent_faculty = list(
        faculty_profiles.annotate(faculty_total=Window(expression=Count('pk')))
        .order_by('-created_at', 'pk')[:5]
    )
    marks_count = marks_summary['total']
    return render(
        request,
        'students/dashboard.html',
        {
            'student_count': recent_students[0].student_total if recent_students else 0,
            'department_count': department_count,
            'faculty_count': recent_faculty[0].faculty_total if recent_faculty else 0,
            'marks_count': marks_count,
            'passed_count': marks_summary['passed'],
            'failed_count': marks_summary['failed'],
            'pass_percentage': (
                round(marks_summary['passed'] * 100 / marks_count, 1)
                if marks_count
                else 0
            ),
            'failed_percentage': (
                round(marks_summary['failed'] * 100 / marks_count, 1)
                if marks_count
                else 0
            ),
            'recent_students': recent_students,
            'recent_faculty': recent_faculty,
            'recent_results': (
                marks.select_related('student')
                .order_by('-created_at', 'pk')[:5]
            ),
            'department_counts': department_counts,
            'max_department_count': max_department_count,
            'attendance_percentage': attendance_percentage,
            'attendance_total': attendance_summary['total'],
            'amount_due': invoice_summary['due'] or 0,
            'amount_collected': invoice_summary['paid'] or 0,
            'upcoming_event_count': upcoming_events.count(),
        },
    )


@roles_required(
    UserProfile.Role.ADMIN,
    UserProfile.Role.REGISTRAR,
    UserProfile.Role.HOD,
    UserProfile.Role.FACULTY,
)
def student_list(request):
    query = request.GET.get('q', '').strip()
    department = request.GET.get('department', '').strip()
    academic_year = request.GET.get('academic_year', '').strip()
    status = request.GET.get('status', '').strip()
    students = visible_students(request.user)
    if query:
        students = students.filter(
            Q(roll_number__icontains=query)
            | Q(full_name__icontains=query)
            | Q(email__icontains=query)
            | Q(department__icontains=query)
        )
    departments = list(
        visible_students(request.user).order_by('department')
        .values_list('department', flat=True)
        .distinct()
    )
    academic_years = list(
        visible_students(request.user).order_by('academic_year')
        .values_list('academic_year', flat=True)
        .distinct()
    )
    if department not in departments:
        department = ''
    if department:
        students = students.filter(department=department)
    if academic_year not in academic_years:
        academic_year = ''
    if academic_year:
        students = students.filter(academic_year=academic_year)
    if status not in ('active', 'inactive', 'all'):
        status = 'all'
    if status == 'active':
        students = students.filter(is_active=True)
    elif status == 'inactive':
        students = students.filter(is_active=False)

    paginator = Paginator(students, 20)
    page_obj = paginator.get_page(request.GET.get('page'))
    query_params = request.GET.copy()
    query_params.pop('page', None)
    context = {
        'students': page_obj.object_list,
        'page_obj': page_obj,
        'query': query,
        'department_choices': departments,
        'academic_year_choices': academic_years,
        'selected_department': department,
        'selected_academic_year': academic_year,
        'selected_status': status,
        'query_string': query_params.urlencode(),
        'student_count': page_obj.paginator.count,
    }
    return render(request, 'students/student_list.html', context)


@roles_required(
    UserProfile.Role.ADMIN,
    UserProfile.Role.REGISTRAR,
    UserProfile.Role.HOD,
    UserProfile.Role.FACULTY,
    UserProfile.Role.STUDENT,
)
def student_detail(request, pk):
    student = get_object_or_404(visible_students(request.user), pk=pk)
    mark_summary = student.examination_marks.aggregate(
        record_count=Count('pk'),
        passed_count=Count('pk', filter=Q(result=ExaminationMark.Result.PASS)),
        average_percentage=Avg('percentage'),
    )
    recent_marks = student.examination_marks.order_by('-created_at', '-pk')[:10]
    from accounts.views import _take_account_setup_url
    enrollments = CourseEnrollment.objects.filter(student=student).select_related(
        'course', 'semester'
    )
    attendance_records = student.attendance_records.exclude(
        status=AttendanceRecord.Status.EXCUSED
    )
    attendance_summary = attendance_records.aggregate(
        total=Count('pk'),
        present=Count('pk', filter=Q(status=AttendanceRecord.Status.PRESENT)),
    )
    attendance_percentage = (
        round(attendance_summary['present'] * 100 / attendance_summary['total'], 1)
        if attendance_summary['total']
        else None
    )
    invoices = student.fee_invoices.prefetch_related('payments').order_by('-created_at')[:10]
    documents = student.documents.all()

    return render(
        request,
        'students/student_detail.html',
        {
            'student': student,
            'mark_summary': mark_summary,
            'recent_marks': recent_marks,
            'enrollments': enrollments,
            'attendance_percentage': attendance_percentage,
            'attendance_total': attendance_summary['total'],
            'invoices': invoices,
            'documents': documents,
            'can_view_fees': get_user_role(request.user) in (
                UserProfile.Role.ADMIN,
                UserProfile.Role.REGISTRAR,
                UserProfile.Role.STUDENT,
            ),
            'can_upload_documents': get_user_role(request.user) in (
                UserProfile.Role.ADMIN,
                UserProfile.Role.REGISTRAR,
                UserProfile.Role.STUDENT,
            ),
            'has_marks': bool(mark_summary['record_count']),
            'has_account': hasattr(student, 'user_profile'),
            'student_password_setup_url': (
                _take_account_setup_url(request, f'student-{student.pk}')
                if get_user_role(request.user) == UserProfile.Role.ADMIN
                else None
            ),
            'pass_percentage': (
                round(mark_summary['passed_count'] * 100 / mark_summary['record_count'], 1)
                if mark_summary['record_count']
                else 0
            ),
        },
    )


@roles_required(UserProfile.Role.ADMIN, UserProfile.Role.REGISTRAR)
def student_create(request):
    if request.method == 'POST':
        form = StudentForm(request.POST)
        if form.is_valid():
            student = form.save()
            record_change(request, student, 'CREATE')
            messages.success(request, f'{student.full_name} was added successfully.')
            return redirect('students:detail', pk=student.pk)
    else:
        form = StudentForm()
    return render(
        request,
        'students/student_form.html',
        {'form': form, 'page_title': 'Add a student', 'submit_label': 'Save student'},
    )


@roles_required(UserProfile.Role.ADMIN, UserProfile.Role.REGISTRAR)
def student_update(request, pk):
    student = get_object_or_404(Student, pk=pk)
    if request.method == 'POST':
        form = StudentForm(request.POST, instance=student)
        if form.is_valid():
            before = capture_fields(student)
            student = form.save()
            record_change(request, student, 'UPDATE', before)
            messages.success(request, f'{student.full_name}’s details were updated.')
            return redirect('students:detail', pk=student.pk)
    else:
        form = StudentForm(instance=student)
    return render(
        request,
        'students/student_form.html',
        {'form': form, 'student': student, 'page_title': 'Edit student', 'submit_label': 'Save changes'},
    )


@roles_required(UserProfile.Role.ADMIN, UserProfile.Role.REGISTRAR)
def student_delete(request, pk):
    student = get_object_or_404(visible_students(request.user), pk=pk)
    has_marks = student.examination_marks.exists()
    has_account = hasattr(student, 'user_profile')
    if request.method == 'POST':
        if has_marks or has_account:
            before = capture_fields(student)
            student.is_active = False
            student.save(update_fields=['is_active', 'updated_at'])
            record_change(request, student, 'UPDATE', before)
            messages.success(
                request,
                f'{student.full_name} was deactivated so their academic history is preserved.',
            )
            return redirect('students:detail', pk=student.pk)
        full_name = student.full_name
        before = capture_fields(student)
        try:
            student.delete()
        except ProtectedError:
            student.is_active = False
            student.save(update_fields=['is_active', 'updated_at'])
            record_change(request, student, 'UPDATE', before)
            messages.success(
                request,
                f'{full_name} was deactivated so their academic history is preserved.',
            )
            return redirect('students:detail', pk=student.pk)
        record_change(request, student, 'DELETE', before)
        messages.success(request, f'{full_name} was removed.')
        return redirect('students:list')
    return render(
        request,
        'students/student_confirm_delete.html',
        {'student': student, 'has_marks': has_marks, 'has_account': has_account},
    )


@roles_required(UserProfile.Role.ADMIN, UserProfile.Role.REGISTRAR)
def student_status(request, pk, status):
    if status not in ('active', 'inactive'):
        raise Http404
    student = get_object_or_404(visible_students(request.user), pk=pk)
    is_active = status == 'active'
    if request.method == 'POST':
        if student.is_active != is_active:
            before = capture_fields(student)
            student.is_active = is_active
            student.save(update_fields=['is_active', 'updated_at'])
            record_change(request, student, 'UPDATE', before)
            action = 'reactivated' if is_active else 'deactivated'
            messages.success(request, f'{student.full_name} was {action}.')
        else:
            messages.info(request, f'{student.full_name} is already {"active" if is_active else "inactive"}.')
        return redirect('students:detail', pk=student.pk)
    return render(
        request,
        'students/student_status_confirm.html',
        {
            'student': student,
            'target_status': status,
            'target_is_active': is_active,
            'has_marks': student.examination_marks.exists(),
        },
    )


@roles_required(
    UserProfile.Role.ADMIN,
    UserProfile.Role.REGISTRAR,
    UserProfile.Role.HOD,
    UserProfile.Role.FACULTY,
    UserProfile.Role.STUDENT,
)
def student_document_upload(request, pk):
    student = get_object_or_404(visible_students(request.user), pk=pk)
    if get_user_role(request.user) not in (
        UserProfile.Role.ADMIN,
        UserProfile.Role.REGISTRAR,
        UserProfile.Role.STUDENT,
    ):
        raise PermissionDenied
    form = StudentDocumentForm(
        request.POST or None,
        request.FILES or None,
    )
    if request.method == 'POST' and form.is_valid():
        document = form.save(commit=False)
        document.student = student
        document.uploaded_by = request.user
        try:
            document.full_clean()
            document.save()
            record_change(request, document, 'CREATE')
        except ValidationError as error:
            for errors in error.message_dict.values():
                for message in errors:
                    form.add_error(None, message)
        else:
            messages.success(request, 'Student document uploaded securely.')
            return redirect('students:detail', pk=student.pk)
    return render(
        request,
        'students/student_document_form.html',
        {'student': student, 'form': form},
    )


@roles_required(
    UserProfile.Role.ADMIN,
    UserProfile.Role.REGISTRAR,
    UserProfile.Role.HOD,
    UserProfile.Role.FACULTY,
    UserProfile.Role.STUDENT,
)
def student_document_download(request, pk, document_pk):
    student = get_object_or_404(visible_students(request.user), pk=pk)
    document = get_object_or_404(StudentDocument, pk=document_pk, student=student)
    return FileResponse(
        document.file.open('rb'),
        as_attachment=True,
        filename=document.file.name.rsplit('/', 1)[-1],
        content_type='application/octet-stream',
    )
