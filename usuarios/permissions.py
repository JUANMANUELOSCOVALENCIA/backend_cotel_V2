"""
Permisos del backend basados en roles (recurso x acción).

El backend es quien decide: aunque alguien llame a la API directamente
(sin pasar por el frontend), solo puede hacer lo que su rol permite.
El frontend sigue ocultando botones solo por comodidad visual.

Uso en una vista:
    permission_classes = [PermisoPorRol]
    recurso_permiso = 'usuarios'            # opcional; por defecto el basename del router
    accion_permiso = 'actualizar'           # opcional; fija la acción (APIView simples)
    lectura_alternativa = [('roles', 'leer')]  # opcional; otros permisos que también dejan LEER
    acciones_permiso = {'cerrar_lote': 'actualizar'}  # opcional; acción de permiso por @action
    solo_superusuario = True                # opcional; solo superusuarios

Acciones @action sin configurar: GET = leer, DELETE = eliminar,
POST sobre un registro (detail) = actualizar, POST general = crear.
"""
from rest_framework.permissions import BasePermission, SAFE_METHODS

# Acciones @action de los ViewSets -> acción de permiso
ACCIONES_PERSONALIZADAS = {
    # lectura
    'exportar': 'leer',
    'estadisticas': 'leer',
    'eliminados': 'leer',
    'usuarios': 'leer',
    'recursos_disponibles': 'leer',
    'acciones_disponibles': 'leer',
    # modificación
    'activar': 'actualizar',
    'desactivar': 'actualizar',
    'resetear_password': 'actualizar',
    'cambiar_rol': 'actualizar',
    'desbloquear': 'actualizar',
    'restaurar': 'actualizar',
    # creación
    'clonar': 'crear',
}

# Solo para mensajes de error legibles
VERBOS = {'leer': 'ver', 'crear': 'crear', 'actualizar': 'modificar', 'eliminar': 'eliminar'}
NOMBRES = {
    'logs': 'la auditoría', 'usuarios': 'usuarios', 'roles': 'roles', 'permisos': 'permisos',
    'almacenes': 'almacenes', 'proveedores': 'proveedores', 'marcas': 'marcas', 'modelos': 'modelos',
    'componentes': 'componentes', 'lotes': 'lotes', 'materiales': 'materiales', 'traspasos': 'traspasos',
    'laboratorio': 'el laboratorio', 'lote-detalles': 'detalles de lote', 'modelo-componentes': 'el contenido de los modelos',
    'sectores-solicitantes': 'sectores solicitantes', 'tipos-material': 'tipos de material',
    'unidades-medida': 'unidades de medida', 'tipos-almacen': 'tipos de almacén', 'tipos-ingreso': 'tipos de ingreso',
    'estados-lote': 'estados de lote', 'estados-traspaso': 'estados de traspaso',
    'estados-material-onu': 'estados de ONU', 'estados-material-general': 'estados de material',
    'solicitudes': 'solicitudes', 'ordenes': 'órdenes de trabajo', 'cobertura': 'zonas de cobertura',
    'planes': 'planes', 'contratos': 'contratos', 'clientes': 'clientes',
}

MSG_CAMBIO_PASSWORD = 'Debes cambiar tu contraseña antes de continuar.'


class PermisoPorRol(BasePermission):
    message = 'No tienes permiso para realizar esta acción.'

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if not user.is_active or getattr(user, 'eliminado', False):
            self.message = 'Tu usuario está inactivo.'
            return False

        # Con la contraseña inicial / reseteada solo se puede cambiar la contraseña
        if getattr(user, 'requiere_cambio_password', False):
            self.message = MSG_CAMBIO_PASSWORD
            return False

        if user.is_superuser:
            return True
        if getattr(view, 'solo_superusuario', False):
            self.message = 'Solo un superusuario puede realizar esta acción.'
            return False

        recurso = getattr(view, 'recurso_permiso', None) or getattr(view, 'basename', None)
        accion = self.determinar_accion(request, view)
        if not recurso or not accion:
            return False

        if user.tiene_permiso(recurso, accion):
            return True

        if accion == 'leer':
            for rec, acc in getattr(view, 'lectura_alternativa', ()):
                if user.tiene_permiso(rec, acc):
                    return True

        self.message = f'No tienes permiso para {VERBOS.get(accion, accion)} {NOMBRES.get(recurso, recurso)}.'
        return False

    @staticmethod
    def determinar_accion(request, view):
        fija = getattr(view, 'accion_permiso', None)
        if isinstance(fija, dict):
            return fija.get(request.method)
        if fija:
            return fija

        accion = getattr(view, 'action', None)
        propias = getattr(view, 'acciones_permiso', None) or {}
        if accion in propias:
            return propias[accion]
        if accion in ACCIONES_PERSONALIZADAS:
            return ACCIONES_PERSONALIZADAS[accion]
        if accion == 'create':
            return 'crear'
        if accion in ('update', 'partial_update'):
            return 'actualizar'
        if accion == 'destroy':
            return 'eliminar'

        if request.method in SAFE_METHODS:
            return 'leer'
        # @action personalizada: si actúa sobre un registro existente es "actualizar"
        if accion and request.method == 'POST' and getattr(view, 'detail', False):
            return 'actualizar'
        return {'POST': 'crear', 'PUT': 'actualizar', 'PATCH': 'actualizar', 'DELETE': 'eliminar'}.get(request.method)


class ProtegerUsuarios(PermisoPorRol):
    """
    Además del permiso por rol, evita escaladas con la gestión de usuarios:
    - nadie cambia su propio rol, estado o lo elimina (lo debe hacer otro administrador)
    - solo un superusuario puede modificar a otro superusuario
    """
    ACCIONES_SOBRE_SI_MISMO = {'cambiar_rol', 'desactivar', 'destroy', 'resetear_password'}
    CAMPOS_SENSIBLES = {'rol', 'is_active', 'is_superuser', 'is_staff'}

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        user = request.user

        if getattr(obj, 'is_superuser', False) and not user.is_superuser:
            self.message = 'Solo un superusuario puede modificar a otro superusuario.'
            return False

        if obj.pk == user.pk:
            accion = getattr(view, 'action', None)
            if accion in self.ACCIONES_SOBRE_SI_MISMO:
                self.message = 'No puedes cambiar tu propio rol, estado o contraseña desde aquí.'
                return False
            if accion in ('update', 'partial_update') and self.CAMPOS_SENSIBLES & set(request.data.keys()):
                self.message = 'No puedes cambiar tu propio rol o estado.'
                return False
        return True


class ProtegerRoles(PermisoPorRol):
    """
    Evita que alguien se dé más permisos editando su propio rol,
    y deja los roles del sistema solo para superusuarios.
    """
    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS or getattr(view, 'action', None) == 'clonar':
            return True
        user = request.user
        if user.is_superuser:
            return True
        if getattr(obj, 'es_sistema', False):
            self.message = 'Los roles del sistema solo los puede modificar un superusuario.'
            return False
        if user.rol_id and obj.pk == user.rol_id:
            self.message = 'No puedes modificar tu propio rol; pídeselo a otro administrador.'
            return False
        return True


# Compatibilidad con el nombre anterior
GenericRolePermission = PermisoPorRol
