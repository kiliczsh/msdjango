from rest_framework.routers import DefaultRouter

from balancer.views import RunViewSet, ServerViewSet

router = DefaultRouter()
router.register("servers", ServerViewSet)
router.register("runs", RunViewSet)
urlpatterns = router.urls
