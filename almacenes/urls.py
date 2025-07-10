# ======================================================
# apps/almacenes/urls.py
# ======================================================

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    MarcaViewSet, TipoEquipoViewSet, ComponenteViewSet, EstadoEquipoViewSet,
    ModeloViewSet, LoteViewSet, EquipoONUViewSet
)

router = DefaultRouter()
router.register(r'marcas', MarcaViewSet)
router.register(r'tipos-equipo', TipoEquipoViewSet)
router.register(r'componentes', ComponenteViewSet)
router.register(r'estados-equipo', EstadoEquipoViewSet)
router.register(r'modelos', ModeloViewSet)
router.register(r'lotes', LoteViewSet)
router.register(r'equipos', EquipoONUViewSet)

urlpatterns = [
    path('', include(router.urls)),
    ]