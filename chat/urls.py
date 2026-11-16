from django.urls import path

from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path("api/ask/", views.ask, name="ask"),
    path("api/reset/", views.reset, name="reset"),
    path("api/display/", views.display, name="display"),
]
