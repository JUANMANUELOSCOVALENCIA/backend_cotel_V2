# ======================================================
# apps/contratos/urls.py
# ======================================================

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    TipoServicioViewSet, TipoTramiteViewSet, FormaPagoViewSet,
    ClienteViewSet, PlanComercialViewSet, ContratoViewSet,
    ServicioViewSet, OrdenTrabajoViewSet
)

router = DefaultRouter()
router.register(r'tipos-servicio', TipoServicioViewSet)
router.register(r'tipos-tramite', TipoTramiteViewSet)
router.register(r'formas-pago', FormaPagoViewSet)
router.register(r'clientes', ClienteViewSet)
router.register(r'planes-comerciales', PlanComercialViewSet)
router.register(r'contratos', ContratoViewSet)
router.register(r'servicios', ServicioViewSet)
router.register(r'ordenes-trabajo', OrdenTrabajoViewSet)

urlpatterns = [
    path('', include(router.urls)),
]