from rest_framework.permissions import BasePermission, SAFE_METHODS


class GenericRolePermission(BasePermission):
    """
    Controla acceso basado en Usuario.tiene_permiso(recurso, accion).
    Usa view.basename & view.action (o método HTTP seguro) para mapear a acciones.

    Recursos soportados:
    - permisos: CRUD de permisos del sistema
    - roles: CRUD de roles del sistema
    - usuarios: CRUD de usuarios (manuales + migrados)
    - empleados-disponibles: Lista y migración de empleados FDW
    - cualquier otro recurso definido en el basename del ViewSet
    """

    def has_permission(self, request, view):
        # 1) Verificar autenticación
        if not request.user or not request.user.is_authenticated:
            return False

        # 2) Superusuarios tienen acceso completo
        if request.user.is_superuser:
            return True

        # 3) Obtener recurso desde el basename del ViewSet
        recurso = getattr(view, 'basename', None)
        if not recurso:
            # Si no hay basename definido, denegar acceso
            return False

        # 4) Determinar acción basada en método HTTP y action del ViewSet
        accion = self._determinar_accion(request, view)
        if not accion:
            # Si no se puede determinar la acción, denegar acceso
            return False

        # 5) Verificar permiso específico en el modelo Usuario
        return request.user.tiene_permiso(recurso, accion)

    def _determinar_accion(self, request, view):
        """
        Mapea métodos HTTP y acciones de ViewSet a acciones de permisos
        """
        # Para métodos seguros (GET, HEAD, OPTIONS) → acción "leer"
        if request.method in SAFE_METHODS:
            return "leer"

        # Para métodos no seguros, verificar la acción del ViewSet
        action = getattr(view, 'action', None)

        # Mapeo de acciones estándar de ViewSet
        if action == "create":
            return "crear"
        elif action in ("update", "partial_update"):
            return "actualizar"
        elif action == "destroy":
            return "eliminar"

        # Mapeo de acciones personalizadas
        elif action in self._get_acciones_personalizadas():
            return self._mapear_accion_personalizada(action)

        # Si no se reconoce la acción, por defecto denegar
        return None

    def _get_acciones_personalizadas(self):
        """
        Define las acciones personalizadas que requieren permisos específicos
        """
        return {
            # Acciones de usuarios
            'activar': 'actualizar',  # POST /usuarios/{id}/activar/
            'resetear_password': 'actualizar',  # POST /usuarios/{id}/resetear_password/
            'cambiar_rol': 'actualizar',  # POST /usuarios/{id}/cambiar_rol/

            # Acciones de roles
            'usuarios': 'leer',  # GET /roles/{id}/usuarios/
            'clonar': 'crear',  # POST /roles/{id}/clonar/

            # Acciones de permisos
            'recursos_disponibles': 'leer',  # GET /permisos/recursos_disponibles/
            'acciones_disponibles': 'leer',  # GET /permisos/acciones_disponibles/

            # Acciones de empleados disponibles
            'estadisticas': 'leer',  # GET /empleados-disponibles/estadisticas/
        }

    def _mapear_accion_personalizada(self, action):
        """
        Retorna la acción de permiso correspondiente a una acción personalizada
        """
        mapeo = self._get_acciones_personalizadas()
