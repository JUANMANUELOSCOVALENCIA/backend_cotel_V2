# ======================================================
# almacenes/urls.py - VERSIÓN CORREGIDA COMPLETA
# ======================================================

from django.urls import path, include
from rest_framework.routers import DefaultRouter

# Importar todas las views desde el módulo organizado
from .views import (
    # Views base
    AlmacenViewSet, ProveedorViewSet,

    # Views de lotes
    LoteViewSet, LoteDetalleViewSet, ImportacionMasivaView,

    # Views de operaciones
    TraspasoAlmacenViewSet, DevolucionProveedorViewSet,

    # Views de laboratorio
    LaboratorioView, LaboratorioMasivoView, LaboratorioConsultaView,

    # Views de reportes
    EstadisticasGeneralesView, DashboardView, ReporteInventarioView,
    ReporteMovimientosView, ReporteGarantiasView, ReporteEficienciaView,

    # Views de compatibilidad
    EquipoONUViewSet, EquipoServicioViewSet, MarcaViewSet,
    TipoEquipoViewSet, ModeloViewSet, EstadoEquipoViewSet, ComponenteViewSet,

    # Views de choices
    TipoIngresoViewSet,
    EstadoLoteViewSet,
    EstadoTraspasoViewSet,
    TipoMaterialViewSet,
    UnidadMedidaViewSet,
    EstadoMaterialONUViewSet,
    EstadoMaterialGeneralViewSet,
    TipoAlmacenViewSet,
    EstadoDevolucionViewSet,
    RespuestaProveedorViewSet,
    OpcionesCompletasView,
    InicializarDatosView,
)
from .views.compatibility_views import ModeloComponenteViewSet

# IMPORTAR MaterialViewSet SOLO UNA VEZ
from .views.material_views import MaterialViewSet

# ========== CONFIGURACIÓN DEL ROUTER ==========
router = DefaultRouter()

# ===== REGISTRAR VIEWSETS PRINCIPALES =====

# Views base
router.register(r'almacenes', AlmacenViewSet, basename='almacenes')
router.register(r'proveedores', ProveedorViewSet, basename='proveedores')

# Views de lotes
router.register(r'lotes', LoteViewSet, basename='lotes')
router.register(r'lote-detalles', LoteDetalleViewSet, basename='lote-detalles')

# Views de materiales - REGISTRAR SOLO UNA VEZ
router.register(r'materiales', MaterialViewSet, basename='materiales')

# Views de operaciones
router.register(r'traspasos', TraspasoAlmacenViewSet, basename='traspasos')
router.register(r'devoluciones', DevolucionProveedorViewSet, basename='devoluciones')

# Views de compatibilidad (sistema legacy)
router.register(r'equipos-onu', EquipoONUViewSet, basename='equipos-onu')
router.register(r'equipo-servicios', EquipoServicioViewSet, basename='equipo-servicios')

# Views de modelos básicos actualizados
router.register(r'marcas', MarcaViewSet, basename='marcas')
router.register(r'tipos-equipo', TipoEquipoViewSet, basename='tipos-equipo')
router.register(r'modelos', ModeloViewSet, basename='modelos')
router.register(r'componentes', ComponenteViewSet, basename='componentes')
router.register(r'estados-equipo', EstadoEquipoViewSet, basename='estados-equipo')

# Views de choices/configuraciones
router.register(r'tipos-ingreso', TipoIngresoViewSet, basename='tipos-ingreso')
router.register(r'estados-lote', EstadoLoteViewSet, basename='estados-lote')
router.register(r'estados-traspaso', EstadoTraspasoViewSet, basename='estados-traspaso')
router.register(r'tipos-material', TipoMaterialViewSet, basename='tipos-material')
router.register(r'unidades-medida', UnidadMedidaViewSet, basename='unidades-medida')
router.register(r'estados-material-onu', EstadoMaterialONUViewSet, basename='estados-material-onu')
router.register(r'estados-material-general', EstadoMaterialGeneralViewSet, basename='estados-material-general')
router.register(r'tipos-almacen', TipoAlmacenViewSet, basename='tipos-almacen')
router.register(r'estados-devolucion', EstadoDevolucionViewSet, basename='estados-devolucion')
router.register(r'respuestas-proveedor', RespuestaProveedorViewSet, basename='respuestas-proveedor')
router.register(r'modelo-componentes', ModeloComponenteViewSet, basename='modelo-componentes')


# ========== URLS PRINCIPALES ==========

urlpatterns = [
    # ===== ENDPOINTS DE VIEWSETS (AUTO-GENERADOS) =====
    path('', include(router.urls)),

    # ===== ENDPOINTS ESPECIALES (VIEWS INDIVIDUALES) =====

    # --- IMPORTACIÓN MASIVA ---
    path('importacion/masiva/', ImportacionMasivaView.as_view(), name='importacion-masiva'),

    # --- LABORATORIO ---
    path('laboratorio/', LaboratorioView.as_view(), name='laboratorio-dashboard'),
    path('laboratorio/masivo/', LaboratorioMasivoView.as_view(), name='laboratorio-masivo'),
    path('laboratorio/consultas/', LaboratorioConsultaView.as_view(), name='laboratorio-consultas'),

    # --- REPORTES Y ESTADÍSTICAS ---
    path('estadisticas/', EstadisticasGeneralesView.as_view(), name='estadisticas-generales'),
    path('dashboard/', DashboardView.as_view(), name='dashboard-operativo'),

    # --- REPORTES ESPECÍFICOS ---
    path('reportes/inventario/', ReporteInventarioView.as_view(), name='reporte-inventario'),
    path('reportes/movimientos/', ReporteMovimientosView.as_view(), name='reporte-movimientos'),
    path('reportes/garantias/', ReporteGarantiasView.as_view(), name='reporte-garantias'),
    path('reportes/eficiencia/', ReporteEficienciaView.as_view(), name='reporte-eficiencia'),

    # --- CONFIGURACIÓN Y DATOS ---
    path('opciones-completas/', OpcionesCompletasView.as_view(), name='opciones-completas'),
    path('inicializar-datos/', InicializarDatosView.as_view(), name='inicializar-datos'),

    # QUITAR ESTA LÍNEA REDUNDANTE:
    # path('materiales/', include(router.urls)),
]