from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (CampoViewSet, ClientesViewSet, InventarioViewSet, CuadrillaViewSet, DespachoViewSet, KitMaterialViewSet, OrdenTrabajoViewSet, PlanAdicionalViewSet, PlanViewSet, SolicitudViewSet,
                    VehiculoViewSet, ZonaCoberturaViewSet)

router = DefaultRouter()
router.register(r'zonas', ZonaCoberturaViewSet, basename='zonas')
router.register(r'planes', PlanViewSet, basename='planes')
router.register(r'adicionales', PlanAdicionalViewSet, basename='adicionales')
router.register(r'solicitudes', SolicitudViewSet, basename='solicitudes')
router.register(r'ordenes', OrdenTrabajoViewSet, basename='ordenes')
router.register(r'clientes', ClientesViewSet, basename='clientes')
router.register(r'vehiculos', VehiculoViewSet, basename='vehiculos')
router.register(r'cuadrillas', CuadrillaViewSet, basename='cuadrillas')
router.register(r'despachos', DespachoViewSet, basename='despachos')
router.register(r'kits', KitMaterialViewSet, basename='kits')
router.register(r'campo', CampoViewSet, basename='campo')
router.register(r'inventario', InventarioViewSet, basename='inventario')

urlpatterns = [path('', include(router.urls))]
