from django.contrib.auth.views import LoginView, LogoutView
from django.urls import path

from . import views
from .forms import DeveloperAuthenticationForm

urlpatterns = [
    path("", views.index, name="index"),
    path(
        "developer/login/",
        LoginView.as_view(
            template_name="chat/developer_login.html",
            authentication_form=DeveloperAuthenticationForm,
            next_page="manage_sources",
        ),
        name="developer_login",
    ),
    path(
        "developer/logout/",
        LogoutView.as_view(next_page="index"),
        name="developer_logout",
    ),
    path("sources/", views.manage_sources, name="manage_sources"),
    path("api/ask/", views.ask, name="ask"),
    path("api/reset/", views.reset, name="reset"),
    path("api/display/", views.display, name="display"),
]
