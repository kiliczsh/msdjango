from django.urls import include, path

from balancer.views import dashboard, health

urlpatterns = [
    path("", dashboard, name="dashboard"),
    path("api/health/", health),
    path("api/", include("balancer.urls")),
]
