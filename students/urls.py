from django.urls import path

from . import views

app_name = 'students'

urlpatterns = [
    path('dashboard/', views.dashboard, name='dashboard'),
    path('', views.student_list, name='list'),
    path('students/add/', views.student_create, name='create'),
    path('students/<int:pk>/', views.student_detail, name='detail'),
    path('students/<int:pk>/edit/', views.student_update, name='update'),
    path('students/<int:pk>/delete/', views.student_delete, name='delete'),
    path('students/<int:pk>/status/<str:status>/', views.student_status, name='status'),
    path('students/<int:pk>/documents/upload/', views.student_document_upload, name='document_upload'),
    path(
        'students/<int:pk>/documents/<int:document_pk>/download/',
        views.student_document_download,
        name='document_download',
    ),
]
