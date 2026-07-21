from django.urls import path

from . import views

app_name = "finance"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("upload/", views.upload_document, name="upload"),
    path("schulden/", views.debt_list, name="debt_list"),
    path("dokumente/", views.document_list, name="document_list"),
]
