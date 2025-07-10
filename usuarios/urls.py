from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    # Views existentes
    MigrarUsuarioView,
    LoginJWTView,
    ChangePasswordView,
    # Nuevos ViewSets
    PermissionViewSet,
    RolesViewSet,
    UsuarioManualViewSet,
    EmpleadosDisponiblesViewSet
)

# Configurar router para ViewSets
router = DefaultRouter()

# Registrar ViewSets con sus nombres base
router.register(r'permisos', PermissionViewSet, basename='permisos')
router.register(r'roles', RolesViewSet, basename='roles')
router.register(r'usuarios', UsuarioManualViewSet, basename='usuarios')
router.register(r'empleados-disponibles', EmpleadosDisponiblesViewSet, basename='empleados-disponibles')

urlpatterns = [
    # ========== URLs EXISTENTES (MANTENER) ==========
    path('migrar/', MigrarUsuarioView.as_view(), name='migrar_usuario'),
    path('login/', LoginJWTView.as_view(), name='login'),
    path('change-password/', ChangePasswordView.as_view(), name='change-password'),

    # ========== NUEVAS URLs DE ViewSets ==========
    # Incluir todas las rutas de los ViewSets registrados
    path('', include(router.urls)),
]
