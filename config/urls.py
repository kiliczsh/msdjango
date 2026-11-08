from django.urls import include, path

from balancer.views import dashboard, health, sample_requests

urlpatterns = [
    path("", dashboard, name="dashboard"),
    path("sample/requests.csv", sample_requests, name="sample-requests"),
    path("api/health/", health),
    path("api/", include("balancer.urls")),
]
