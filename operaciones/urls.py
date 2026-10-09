from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import ClientesViewSet, OrdenTrabajoViewSet, PlanAdicionalViewSet, PlanViewSet, SolicitudViewSet, ZonaCoberturaViewSet

router = DefaultRouter()
router.register(r'zonas', ZonaCoberturaViewSet, basename='zonas')
router.register(r'planes', PlanViewSet, basename='planes')
router.register(r'adicionales', PlanAdicionalViewSet, basename='adicionales')
router.register(r'solicitudes', SolicitudViewSet, basename='solicitudes')
router.register(r'ordenes', OrdenTrabajoViewSet, basename='ordenes')
router.register(r'clientes', ClientesViewSet, basename='clientes')

urlpatterns = [path('', include(router.urls))]
