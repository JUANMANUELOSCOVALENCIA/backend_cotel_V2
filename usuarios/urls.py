from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    # Views existentes
    MigrarUsuarioView,
    LoginJWTView,
    ChangePasswordView,
    LogoutView,

    # ViewSets principales
    PermissionViewSet,
    RolesViewSet,
    UsuarioViewSet,
    EmpleadosDisponiblesViewSet,
    AuditLogViewSet,

    # Vistas adicionales
    ResetPasswordAdminView,
    UsuarioPerfilView,
    EstadisticasUsuariosView,
    ValidarCodigoCotelView,
    GenerarCodigoCotelView,
)

# Configurar router para ViewSets
router = DefaultRouter()

# Registrar ViewSets
router.register(r'permisos', PermissionViewSet, basename='permisos')
router.register(r'roles', RolesViewSet, basename='roles')
router.register(r'usuarios', UsuarioViewSet, basename='usuarios')
router.register(r'empleados-disponibles', EmpleadosDisponiblesViewSet, basename='empleados-disponibles')
router.register(r'logs', AuditLogViewSet, basename='logs')

urlpatterns = [
    # ========== URLs EXISTENTES (COMPATIBILIDAD) ==========
    path('migrar/', MigrarUsuarioView.as_view(), name='migrar_usuario'),
    path('login/', LoginJWTView.as_view(), name='login'),
    path('change-password/', ChangePasswordView.as_view(), name='change-password'),
    path('logout/', LogoutView.as_view(), name='logout'),

    # ========== NUEVAS URLs ESPECÍFICAS ==========

    # Gestión de usuarios
    path('reset-password/', ResetPasswordAdminView.as_view(), name='reset-password-admin'),
    path('perfil/', UsuarioPerfilView.as_view(), name='usuario-perfil'),

    # Utilidades
    path('estadisticas/', EstadisticasUsuariosView.as_view(), name='estadisticas-usuarios'),
    path('validar-cotel/', ValidarCodigoCotelView.as_view(), name='validar-cotel'),
    path('generar-cotel/', GenerarCodigoCotelView.as_view(), name='generar-cotel'),

    # ========== URLs DE ViewSets ==========
    path('', include(router.urls)),
]