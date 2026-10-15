from django.urls import path

from . import views

app_name = 'academics'

urlpatterns = [
    path('', views.mark_list, name='list'),
    path('analytics/data/', views.analytics_data, name='analytics_data'),
    path('courses/', views.course_list, name='course_list'),
    path('courses/add/', views.course_create, name='course_create'),
    path('courses/<int:pk>/', views.course_detail, name='course_detail'),
    path('courses/<int:pk>/enrol/', views.course_enroll_student, name='course_enrol'),
    path('semesters/', views.semester_list, name='semester_list'),
    path('semesters/add/', views.semester_create, name='semester_create'),
    path('sessions/', views.session_list, name='session_list'),
    path('sessions/add/', views.session_create, name='session_create'),
    path('sessions/<int:pk>/attendance/', views.attendance_grid, name='attendance'),
    path('fees/', views.fee_list, name='fee_list'),
    path('fees/add/', views.fee_create, name='fee_create'),
    path('fees/<int:pk>/', views.fee_detail, name='fee_detail'),
    path('fees/<int:pk>/payments/add/', views.fee_payment_create, name='fee_payment_create'),
    path('events/', views.event_list, name='event_list'),
    path('events/add/', views.event_create, name='event_create'),
    path('announcements/', views.announcement_list, name='announcement_list'),
    path('announcements/add/', views.announcement_create, name='announcement_create'),
    path('marks/add/', views.mark_create, name='create'),
    path('marks/<int:pk>/', views.mark_detail, name='detail'),
    path('marks/<int:pk>/edit/', views.mark_update, name='update'),
    path('marks/<int:pk>/delete/', views.mark_delete, name='delete'),
]
