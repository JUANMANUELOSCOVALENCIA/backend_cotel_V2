from rest_framework.permissions import BasePermission, SAFE_METHODS


class GenericRolePermission(BasePermission):
    """
    Permiso basado en roles y permisos granulares
    Verifica Usuario.tiene_permiso(recurso, accion)
    """

    def has_permission(self, request, view):
        # Verificar autenticación
        if not request.user or not request.user.is_authenticated:
            return False

        # Superusuarios tienen acceso completo
        if request.user.is_superuser:
            return True

        # Verificar que el usuario esté activo
        if not request.user.is_active or request.user.eliminado:
            return False

        # Obtener recurso desde el basename del ViewSet
        recurso = getattr(view, 'basename', None)
        if not recurso:
            return False

        # Determinar acción
        accion = self._determinar_accion(request, view)
        if not accion:
            return False

        # Verificar permiso específico
        return request.user.tiene_permiso(recurso, accion)

    def has_object_permission(self, request, view, obj):
        # Verificaciones básicas
        if not self.has_permission(request, view):
            return False

        # El usuario puede acceder a su propio perfil
        if hasattr(obj, 'codigocotel') and obj.codigocotel == request.user.codigocotel:
            return True

        return True

    def _determinar_accion(self, request, view):
        """Mapea métodos HTTP y acciones de ViewSet a acciones de permisos"""

        # Métodos seguros = leer
        if request.method in SAFE_METHODS:
            return "leer"

        # Acciones del ViewSet
        action = getattr(view, 'action', None)

        if action == "create":
            return "crear"
        elif action in ("update", "partial_update"):
            return "actualizar"
        elif action == "destroy":
            return "eliminar"

        # Acciones personalizadas
        acciones_personalizadas = {
            # Usuarios
            'activar': 'actualizar',
            'desactivar': 'actualizar',
            'resetear_password': 'actualizar',
            'cambiar_rol': 'actualizar',
            'desbloquear': 'actualizar',
            'restaurar': 'actualizar',

            # Roles
            'usuarios': 'leer',
            'clonar': 'crear',

            # Permisos
            'recursos_disponibles': 'leer',
            'acciones_disponibles': 'leer',

            # Empleados
            'estadisticas': 'leer',

            # Logs
            'estadisticas': 'leer',
        }

        if action in acciones_personalizadas:
            return acciones_personalizadas[action]

        # Métodos HTTP sin action específica
        if request.method == "POST":
            return "crear"
        elif request.method in ("PUT", "PATCH"):
            return "actualizar"
        elif request.method == "DELETE":
            return "eliminar"

        return None
