from django.urls import path

from . import views

app_name = "finance"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("upload/", views.upload_document, name="upload"),
    path("schulden/", views.debt_list, name="debt_list"),
    path("dokumente/", views.document_list, name="document_list"),
    path("schulden/<str:row_id>/uebernehmen/", views.confirm_debt, name="confirm_debt"),
    path("schulden/<str:row_id>/verwerfen/", views.reject_debt, name="reject_debt"),
    path("bankabgleich/", views.reconcile_banks, name="reconcile_banks"),
]
