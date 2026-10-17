from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_not_required
from django.urls import path, reverse_lazy
from django.views.generic import TemplateView

from . import views

app_name = 'accounts'

urlpatterns = [
    path(
        'login/',
        views.PortalLoginView.as_view(),
        name='login',
    ),
    path('', views.portal_home, name='portal_home'),
    path('search/', views.command_search, name='command_search'),
    path(
        'login/admin/',
        views.PortalLoginView.as_view(portal='admin'),
        name='admin_login',
    ),
    path(
        'login/student/',
        views.PortalLoginView.as_view(portal='student'),
        name='student_login',
    ),
    path(
        'login/faculty/',
        views.PortalLoginView.as_view(portal='faculty'),
        name='faculty_login',
    ),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path(
        'password/reset/',
        login_not_required(views.ThrottledPasswordResetView.as_view()),
        name='password_reset',
    ),
    path(
        'password/reset/done/',
        login_not_required(
            TemplateView.as_view(
                template_name='accounts/password_reset_done.html',
            )
        ),
        name='password_reset_done',
    ),
    path('faculty/', views.faculty_list, name='faculty_list'),
    path('faculty/add/', views.faculty_create, name='faculty_create'),
    path('faculty/<int:pk>/', views.faculty_detail, name='faculty_detail'),
    path('faculty/<int:pk>/edit/', views.faculty_update, name='faculty_update'),
    path(
        'faculty/<int:pk>/<str:status>/',
        views.faculty_status,
        name='faculty_status',
    ),
    path(
        'students/<int:pk>/account/',
        views.student_account_create,
        name='student_account_create',
    ),
    path('users/', views.user_account_list, name='user_list'),
    path(
        'password/change/',
        auth_views.PasswordChangeView.as_view(
            template_name='accounts/password_change_form.html',
            success_url=reverse_lazy('accounts:password_change_done'),
        ),
        name='password_change',
    ),
    path(
        'password/change/done/',
        TemplateView.as_view(template_name='accounts/password_change_done.html'),
        name='password_change_done',
    ),
    path(
        'password/reset/confirm/<uidb64>/<token>/',
        login_not_required(
            auth_views.PasswordResetConfirmView.as_view(
                template_name='accounts/password_reset_confirm.html',
                success_url=reverse_lazy('accounts:password_reset_complete'),
            )
        ),
        name='password_reset_confirm',
    ),
    path(
        'password/reset/complete/',
        login_not_required(
            auth_views.PasswordResetCompleteView.as_view(
                template_name='accounts/password_reset_complete.html',
            )
        ),
        name='password_reset_complete',
    ),
]
