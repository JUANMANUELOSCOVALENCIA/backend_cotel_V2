# ======================================================
# almacenes/views/__init__.py - ACTUALIZADO
# Exportar todas las views del módulo de almacenes
# ======================================================

# Views base (almacenes y proveedores)
from .base_views import (
    AlmacenViewSet,
    ProveedorViewSet
)

# Views de lotes
from .lote_views import (
    LoteViewSet,
    ImportacionMasivaView,
    LoteDetalleViewSet
)

# Views de materiales
from .material_views import (
    MaterialViewSet
)

# Views de operaciones
from .operacion_views import (
    TraspasoAlmacenViewSet,
    DevolucionProveedorViewSet
)

# Views de laboratorio
from .laboratorio_views import (
    LaboratorioView,
    LaboratorioMasivoView,
    LaboratorioConsultaView
)

# Views de reportes
from .reporte_views import (
    EstadisticasGeneralesView,
    DashboardView,
    ReporteInventarioView,
    ReporteMovimientosView,
    ReporteGarantiasView,
    ReporteEficienciaView
)

# Views de compatibilidad
from .compatibility_views import (
    MarcaViewSet,
    ModeloViewSet,
    ComponenteViewSet
)

# AGREGAR ESTAS IMPORTACIONES - Views para modelos de choices
from .choices_views import (
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
    InicializarDatosView
)

# Exportar todas las views
__all__ = [
    # Views base
    'AlmacenViewSet',
    'ProveedorViewSet',

    # Views de lotes
    'LoteViewSet',
    'ImportacionMasivaView',
    'LoteDetalleViewSet',

    # Views de materiales
    'MaterialViewSet',

    # Views de operaciones
    'TraspasoAlmacenViewSet',
    'DevolucionProveedorViewSet',

    # Views de laboratorio
    'LaboratorioView',
    'LaboratorioMasivoView',
    'LaboratorioConsultaView',

    # Views de reportes
    'EstadisticasGeneralesView',
    'DashboardView',
    'ReporteInventarioView',
    'ReporteMovimientosView',
    'ReporteGarantiasView',
    'ReporteEficienciaView',

    # Views de compatibilidad
    'MarcaViewSet',
    'ModeloViewSet',
    'ComponenteViewSet',

    # AGREGAR ESTAS EXPORTACIONES - Views para modelos de choices
    'TipoIngresoViewSet',
    'EstadoLoteViewSet',
    'EstadoTraspasoViewSet',
    'TipoMaterialViewSet',
    'UnidadMedidaViewSet',
    'EstadoMaterialONUViewSet',
    'EstadoMaterialGeneralViewSet',
    'TipoAlmacenViewSet',
    'EstadoDevolucionViewSet',
    'RespuestaProveedorViewSet',
    'OpcionesCompletasView',
    'InicializarDatosView',
]