# ======================================================
# almacenes/urls.py
# URLs completas del sistema de almacenes
# ======================================================

from django.urls import path, include
from rest_framework.routers import DefaultRouter

# Importar todas las views desde el módulo organizado
from .views import (
    # Views base
    AlmacenViewSet, ProveedorViewSet,

    # Views de lotes
    LoteViewSet, LoteDetalleViewSet, ImportacionMasivaView,

    # Views de materiales
    MaterialViewSet,

    # Views de operaciones
    TraspasoAlmacenViewSet, DevolucionProveedorViewSet,

    # Views de laboratorio
    LaboratorioView, LaboratorioMasivoView, LaboratorioConsultaView,

    # Views de reportes
    EstadisticasGeneralesView, DashboardView, ReporteInventarioView,
    ReporteMovimientosView, ReporteGarantiasView, ReporteEficienciaView,

    # Views de compatibilidad
    EquipoONUViewSet, EquipoServicioViewSet, MarcaViewSet,
    TipoEquipoViewSet, ModeloViewSet, EstadoEquipoViewSet, ComponenteViewSet
)

# ========== CONFIGURACIÓN DEL ROUTER ==========

router = DefaultRouter()

# ===== REGISTRAR VIEWSETS PRINCIPALES =====

# Views base
router.register(r'almacenes', AlmacenViewSet, basename='almacenes')
router.register(r'proveedores', ProveedorViewSet, basename='proveedores')

# Views de lotes
router.register(r'lotes', LoteViewSet, basename='lotes')
router.register(r'lote-detalles', LoteDetalleViewSet, basename='lote-detalles')

# Views de materiales
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
router.register(r'estados-equipo', EstadoEquipoViewSet, basename='estados-equipo')  # Legacy

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
]

# ========== DOCUMENTACIÓN DE ENDPOINTS ==========

"""
ENDPOINTS DISPONIBLES:

=== GESTIÓN BASE ===
GET    /api/almacenes/                          # Listar almacenes
POST   /api/almacenes/                          # Crear almacén
GET    /api/almacenes/{id}/                     # Detalle almacén
PUT    /api/almacenes/{id}/                     # Actualizar almacén
DELETE /api/almacenes/{id}/                     # Eliminar almacén
GET    /api/almacenes/{id}/materiales/          # Materiales del almacén
GET    /api/almacenes/{id}/estadisticas/        # Estadísticas del almacén
GET    /api/almacenes/{id}/movimientos/         # Historial de movimientos
GET    /api/almacenes/principal/                # Almacén principal
GET    /api/almacenes/resumen_general/          # Resumen de todos los almacenes

GET    /api/proveedores/                        # Listar proveedores
POST   /api/proveedores/                        # Crear proveedor
GET    /api/proveedores/{id}/                   # Detalle proveedor
GET    /api/proveedores/{id}/lotes/             # Lotes del proveedor
GET    /api/proveedores/{id}/estadisticas/      # Estadísticas del proveedor
GET    /api/proveedores/activos/                # Solo proveedores activos
GET    /api/proveedores/top_proveedores/        # Top 10 proveedores

=== GESTIÓN DE LOTES ===
GET    /api/lotes/                              # Listar lotes
POST   /api/lotes/                              # Crear lote con detalles
GET    /api/lotes/{id}/                         # Detalle completo del lote
PUT    /api/lotes/{id}/                         # Actualizar lote
GET    /api/lotes/{id}/resumen/                 # Resumen estadístico del lote
POST   /api/lotes/{id}/agregar_entrega_parcial/ # Agregar entrega parcial
POST   /api/lotes/{id}/cerrar_lote/             # Cerrar lote
POST   /api/lotes/{id}/reabrir_lote/            # Reabrir lote (admin)
GET    /api/lotes/{id}/materiales/              # Materiales del lote
POST   /api/lotes/{id}/enviar_laboratorio_masivo/ # Envío masivo a laboratorio
GET    /api/lotes/estadisticas/                 # Estadísticas generales de lotes

=== IMPORTACIÓN MASIVA ===
GET    /api/importacion/masiva/                 # Plantilla e instrucciones
POST   /api/importacion/masiva/                 # Procesar archivo Excel/CSV

=== GESTIÓN DE MATERIALES ===
GET    /api/materiales/                         # Listar materiales (paginado)
POST   /api/materiales/                         # Crear material individual
GET    /api/materiales/{id}/                    # Detalle del material
PUT    /api/materiales/{id}/                    # Actualizar material
GET    /api/materiales/{id}/historial/          # Historial completo del material
POST   /api/materiales/{id}/cambiar_estado/     # Cambiar estado del material
POST   /api/materiales/{id}/enviar_laboratorio/ # Enviar a laboratorio
POST   /api/materiales/{id}/retornar_laboratorio/ # Retornar de laboratorio
POST   /api/materiales/busqueda_avanzada/       # Búsqueda con múltiples criterios
GET    /api/materiales/estadisticas/            # Estadísticas de materiales
GET    /api/materiales/disponibles_para_asignacion/ # Materiales disponibles
GET    /api/materiales/validar_unicidad/        # Validar MAC, GPON, D-SN únicos
POST   /api/materiales/operacion_masiva/        # Operaciones masivas

=== TRASPASOS ENTRE ALMACENES ===
GET    /api/traspasos/                          # Listar traspasos
POST   /api/traspasos/                          # Crear traspaso con materiales
GET    /api/traspasos/{id}/                     # Detalle del traspaso
POST   /api/traspasos/{id}/enviar/              # Confirmar envío
POST   /api/traspasos/{id}/recibir/             # Confirmar recepción
POST   /api/traspasos/{id}/cancelar/            # Cancelar traspaso
GET    /api/traspasos/{id}/materiales_detalle/  # Detalle de materiales
GET    /api/traspasos/estadisticas/             # Estadísticas de traspasos

=== DEVOLUCIONES A PROVEEDORES ===
GET    /api/devoluciones/                       # Listar devoluciones
POST   /api/devoluciones/                       # Crear devolución
GET    /api/devoluciones/{id}/                  # Detalle devolución
POST   /api/devoluciones/{id}/enviar_proveedor/ # Marcar como enviada
POST   /api/devoluciones/{id}/confirmar_respuesta/ # Confirmar respuesta del proveedor
GET    /api/devoluciones/{id}/materiales_detalle/ # Materiales en la devolución
GET    /api/devoluciones/estadisticas/          # Estadísticas de devoluciones

=== LABORATORIO ===
GET    /api/laboratorio/                        # Dashboard de laboratorio
POST   /api/laboratorio/                        # Operación individual
POST   /api/laboratorio/masivo/                 # Operaciones masivas
GET    /api/laboratorio/consultas/              # Consultas específicas
        ?tipo=en_laboratorio                    # Materiales en laboratorio
        ?tipo=pendientes_inspeccion             # Pendientes de inspección
        ?tipo=tiempo_excesivo&dias_limite=15    # Con tiempo excesivo
        ?tipo=historial_laboratorio&dias=30     # Historial de procesamiento

=== ESTADÍSTICAS Y REPORTES ===
GET    /api/estadisticas/                       # Estadísticas generales del sistema
GET    /api/dashboard/                          # Dashboard operativo
GET    /api/reportes/inventario/                # Reporte de inventario
        ?formato=json|csv                       # Formato de salida
        ?almacen_id=1                          # Filtrar por almacén
        ?tipo_material=ONU                      # Filtrar por tipo
GET    /api/reportes/movimientos/               # Reporte de movimientos
        ?fecha_desde=2024-01-01                # Período
        ?fecha_hasta=2024-12-31
        ?tipo=traspaso|devolucion              # Tipo de movimiento
GET    /api/reportes/garantias/                 # Reporte de garantías
        ?dias=30                               # Días de anticipación
GET    /api/reportes/eficiencia/                # KPIs operativos
        ?periodo_dias=30                       # Período de análisis

=== COMPATIBILIDAD (SISTEMA LEGACY) ===
GET    /api/equipos-onu/                       # Equipos ONU legacy
GET    /api/equipos-onu/{id}/historial_servicios/ # Historial de servicios
POST   /api/equipos-onu/{id}/cambiar_estado_legacy/ # Cambiar estado legacy
GET    /api/equipos-onu/disponibles_legacy/    # Equipos disponibles legacy
GET    /api/equipos-onu/estadisticas_legacy/   # Estadísticas legacy

GET    /api/equipo-servicios/                  # Relaciones equipo-servicio
POST   /api/equipo-servicios/{id}/desasignar/  # Desasignar equipo
GET    /api/equipo-servicios/por_contrato/     # Por contrato específico

=== MODELOS BÁSICOS ===
GET    /api/marcas/                            # Marcas
POST   /api/marcas/{id}/toggle_activo/         # Activar/desactivar
GET    /api/marcas/{id}/modelos_activos/       # Modelos activos de la marca

GET    /api/tipos-equipo/                      # Tipos de equipo
GET    /api/modelos/                           # Modelos
GET    /api/modelos/{id}/materiales_nuevos/    # Materiales del nuevo sistema
GET    /api/modelos/{id}/equipos_legacy/       # Equipos del sistema legacy
GET    /api/componentes/                       # Componentes
GET    /api/estados-equipo/                    # Estados legacy

=== FILTROS COMUNES ===
Todos los listados soportan:
?search=texto                                   # Búsqueda de texto
?page=1&page_size=20                           # Paginación
?ordering=campo                                # Ordenamiento
?incluir_inactivos=true                        # Incluir elementos inactivos

=== CÓDIGOS DE RESPUESTA ===
200 - OK: Operación exitosa
201 - Created: Recurso creado exitosamente
400 - Bad Request: Error en los datos enviados
401 - Unauthorized: No autenticado
403 - Forbidden: Sin permisos
404 - Not Found: Recurso no encontrado
500 - Internal Server Error: Error del servidor

=== FORMATOS DE RESPUESTA ===
Todas las respuestas JSON incluyen:
{
    "results": [...],           # Datos principales (en listados paginados)
    "count": 100,              # Total de elementos (en listados)
    "next": "url",             # Siguiente página (si hay)
    "previous": "url",         # Página anterior (si hay)
    "message": "texto",        # Mensaje de confirmación (en operaciones)
    "error": "texto"           # Mensaje de error (si hay error)
}
"""