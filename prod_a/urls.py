# ======================================================
# prod_a/urls.py
# URLs globales del proyecto - Sistema Completo
# ======================================================

from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
    TokenVerifyView
)

# Importar vista personalizada para la raíz
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods


@require_http_methods(["GET"])
def api_root(request):
    """Vista raíz de la API con información del sistema"""
    return JsonResponse({
        "sistema": "Sistema Integral de Gestión GPON/Fibra Óptica",
        "version": "1.0.0",
        "descripcion": "API REST para gestión completa de almacenes, materiales y equipos de telecomunicaciones",
        "modulos_disponibles": {
            "usuarios": "/api/usuarios/",
            "almacenes": "/api/almacenes/",
            "contratos": "/api/contratos/"
        },
        "endpoints_principales": {
            "autenticacion": {
                "login": "/api/token/",
                "refresh": "/api/token/refresh/",
                "verify": "/api/token/verify/"
            },
            "almacenes": {
                "almacenes": "/api/almacenes/almacenes/",
                "materiales": "/api/almacenes/materiales/",
                "lotes": "/api/almacenes/lotes/",
                "traspasos": "/api/almacenes/traspasos/",
                "laboratorio": "/api/almacenes/laboratorio/",
                "reportes": "/api/almacenes/estadisticas/"
            },
            "usuarios": {
                "usuarios": "/api/usuarios/usuarios/",
                "roles": "/api/usuarios/roles/",
                "permisos": "/api/usuarios/permisos/"
            }
        },
        "documentacion": {
            "api_docs": "/api/docs/" if settings.DEBUG else "Contactar administrador",
            "admin": "/admin/",
            "health_check": "/api/health/"
        }
    })


# ========== HEALTH CHECK ==========
@require_http_methods(["GET"])
def health_check(request):
    """Endpoint para verificar estado del sistema"""
    try:
        from django.db import connection
        from usuarios.models import Usuario

        # Verificar conexión a BD
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")

        # Verificar que hay usuarios en el sistema
        usuarios_count = Usuario.objects.count()

        return JsonResponse({
            "status": "healthy",
            "timestamp": "2025-01-01T00:00:00Z",  # Se puede usar timezone.now()
            "database": "connected",
            "usuarios_sistema": usuarios_count,
            "version": "1.0.0"
        })
    except Exception as e:
        return JsonResponse({
            "status": "unhealthy",
            "error": str(e),
            "timestamp": "2025-01-01T00:00:00Z"
        }, status=500)


# ========== URLs PRINCIPALES ==========

urlpatterns = [
    # ===== ADMINISTRACIÓN =====
    path('admin/', admin.site.urls),

    # ===== ENDPOINTS DE SISTEMA =====
    path('api/', api_root, name='api-root'),
    path('api/health/', health_check, name='health-check'),

    # ===== AUTENTICACIÓN JWT =====
    path('api/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('api/token/verify/', TokenVerifyView.as_view(), name='token_verify'),

    # ===== MÓDULOS DE LA APLICACIÓN =====

    # Módulo de Usuarios (autenticación, roles, permisos)
    path('api/usuarios/', include('usuarios.urls')),

    # Módulo de Almacenes (NUEVO - sistema completo)
    path('api/almacenes/', include('almacenes.urls')),

    # Módulo de Contratos (existente)
    path('api/contratos/', include('contratos.urls')),
]

# ===== CONFIGURACIÓN PARA DESARROLLO =====
if settings.DEBUG:
    # Servir archivos estáticos en desarrollo
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

    # Si usas archivos media (uploads)
    if hasattr(settings, 'MEDIA_URL') and hasattr(settings, 'MEDIA_ROOT'):
        urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

    # ===== DOCUMENTACIÓN DE LA API (SOLO EN DEBUG) =====
    try:
        from drf_spectacular.views import (
            SpectacularAPIView,
            SpectacularSwaggerView,
            SpectacularRedocView
        )

        urlpatterns += [
            # Generar schema OpenAPI
            path('api/schema/', SpectacularAPIView.as_view(), name='schema'),

            # Documentación interactiva Swagger
            path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),

            # Documentación Redoc
            path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
        ]
    except ImportError:
        # Si no está instalado drf-spectacular, agregar endpoint básico
        def api_docs(request):
            return JsonResponse({
                "message": "Documentación de API no disponible",
                "suggestion": "Instalar drf-spectacular para documentación automática",
                "endpoints_disponibles": "Ver /api/ para lista completa"
            })


        urlpatterns += [
            path('api/docs/', api_docs, name='api-docs-fallback'),
        ]

# ========== CONFIGURACIÓN DEL ADMIN ==========
admin.site.site_header = "Sistema GPON/Fibra Óptica"
admin.site.site_title = "Administración GPON"
admin.site.index_title = "Panel de Administración"

# ========== MANEJO DE ERRORES ==========
handler404 = lambda request, exception: JsonResponse({
    "error": "Endpoint no encontrado",
    "suggestion": "Verificar la URL o consultar /api/ para endpoints disponibles"
}, status=404)

handler500 = lambda request: JsonResponse({
    "error": "Error interno del servidor",
    "suggestion": "Contactar al administrador del sistema"
}, status=500)

# ========== DOCUMENTACIÓN DE ENDPOINTS GLOBALES ==========

"""
ESTRUCTURA COMPLETA DE URLs:

=== SISTEMA ===
GET  /api/                          # Información general de la API
GET  /api/health/                   # Health check del sistema
GET  /admin/                        # Panel de administración Django

=== AUTENTICACIÓN ===
POST /api/token/                    # Obtener tokens JWT (login)
     {"codigocotel": "123", "password": "password"}
POST /api/token/refresh/            # Refrescar token
     {"refresh": "refresh_token_here"}  
POST /api/token/verify/             # Verificar token
     {"token": "access_token_here"}

=== MÓDULO USUARIOS ===
/api/usuarios/                      # Ver usuarios/urls.py para detalles completos
    usuarios/                       # CRUD de usuarios
    roles/                          # Gestión de roles
    permisos/                       # Gestión de permisos
    logs/                           # Logs de auditoría
    empleados-disponibles/          # Empleados FDW para migrar
    migrar/                         # Migración de usuarios
    login/                          # Login (alternativo a /api/token/)
    change-password/                # Cambio de contraseña

=== MÓDULO ALMACENES ===  
/api/almacenes/                     # Ver almacenes/urls.py para detalles completos
    almacenes/                      # Gestión de almacenes
    proveedores/                    # Gestión de proveedores
    lotes/                          # Gestión de lotes
    materiales/                     # Materiales unificados (ONU + otros)
    traspasos/                      # Traspasos entre almacenes
    devoluciones/                   # Devoluciones a proveedores
    laboratorio/                    # Operaciones de laboratorio
    importacion/masiva/             # Importación Excel/CSV
    estadisticas/                   # Estadísticas generales
    dashboard/                      # Dashboard operativo
    reportes/                       # Reportes específicos

    # Compatibilidad legacy
    equipos-onu/                    # Equipos ONU legacy
    marcas/                         # Marcas
    modelos/                        # Modelos

=== MÓDULO CONTRATOS ===
/api/contratos/                     # Ver contratos/urls.py para detalles
    contratos/                      # Gestión de contratos
    servicios/                      # Servicios
    clientes/                       # Clientes
    # ... otros endpoints de contratos

=== DESARROLLO (solo en DEBUG=True) ===
GET  /api/schema/                   # Schema OpenAPI
GET  /api/docs/                     # Documentación Swagger
GET  /api/redoc/                    # Documentación Redoc

=== HEADERS REQUERIDOS ===
Authorization: Bearer <access_token>    # Para endpoints protegidos
Content-Type: application/json          # Para requests POST/PUT
Accept: application/json                 # Para responses JSON

=== EJEMPLOS DE USO ===

1. Login:
   POST /api/token/
   {"codigocotel": "1001", "password": "1001"}

2. Listar almacenes:
   GET /api/almacenes/almacenes/
   Headers: {"Authorization": "Bearer <token>"}

3. Crear material:
   POST /api/almacenes/materiales/
   Headers: {"Authorization": "Bearer <token>", "Content-Type": "application/json"}
   Body: {"tipo_material": "ONU", "mac_address": "00:11:22:33:44:55", ...}

4. Importar materiales:
   POST /api/almacenes/importacion/masiva/
   Headers: {"Authorization": "Bearer <token>"}
   Form-data: {"archivo": <file>, "lote_id": 1, "almacen_id": 1}

=== CÓDIGOS DE ESTADO HTTP ===
200 OK - Operación exitosa
201 Created - Recurso creado
400 Bad Request - Error en datos enviados
401 Unauthorized - Token inválido/faltante
403 Forbidden - Sin permisos
404 Not Found - Recurso no encontrado  
422 Unprocessable Entity - Error de validación
500 Internal Server Error - Error del servidor
"""