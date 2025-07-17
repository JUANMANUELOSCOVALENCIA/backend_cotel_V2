from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.html import format_html
from .models import Usuario, Permission, Roles, AuditLog, Empleado_fdw


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    """Administración de usuarios personalizada"""

    list_display = (
        'codigocotel', 'nombre_completo_admin', 'rol', 'is_active',
        'es_usuario_manual', 'password_changed', 'fecha_creacion'
    )
    list_filter = (
        'is_active', 'is_staff', 'is_superuser', 'rol',
        'password_changed', 'eliminado', 'fecha_creacion'
    )
    search_fields = ('codigocotel', 'nombres', 'apellidopaterno', 'apellidomaterno')
    ordering = ('-fecha_creacion',)

    # Campos para el formulario
    fieldsets = (
        ('Información Básica', {
            'fields': ('codigocotel', 'nombres', 'apellidopaterno', 'apellidomaterno')
        }),
        ('Información Laboral', {
            'fields': ('persona', 'estadoempleado', 'fechaingreso', 'rol')
        }),
        ('Permisos', {
            'fields': ('is_active', 'is_staff', 'is_superuser')
        }),
        ('Contraseñas', {
            'fields': ('password_changed', 'password_reset_required', 'password_reset_by')
        }),
        ('Seguridad', {
            'fields': ('intentos_login_fallidos', 'bloqueado_hasta', 'ultimo_login_ip')
        }),
        ('Auditoría', {
            'fields': ('fecha_creacion', 'creado_por', 'eliminado', 'fecha_eliminacion', 'eliminado_por')
        }),
    )

    readonly_fields = ('fecha_creacion', 'ultimo_login_ip')

    def nombre_completo_admin(self, obj):
        return obj.nombre_completo

    nombre_completo_admin.short_description = 'Nombre Completo'

    def es_usuario_manual(self, obj):
        if obj.es_usuario_manual:
            return format_html('<span style="color: green;">Manual</span>')
        else:
            return format_html('<span style="color: blue;">Migrado</span>')

    es_usuario_manual.short_description = 'Tipo'

    # Filtros personalizados
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('rol', 'creado_por')


@admin.register(Permission)
class PermissionAdmin(admin.ModelAdmin):
    """Administración de permisos"""

    list_display = ('recurso', 'accion', 'activo', 'esta_en_uso_admin', 'fecha_creacion')
    list_filter = ('accion', 'activo', 'eliminado', 'fecha_creacion')
    search_fields = ('recurso', 'descripcion')
    ordering = ('recurso', 'accion')

    fieldsets = (
        ('Información del Permiso', {
            'fields': ('recurso', 'accion', 'descripcion', 'activo')
        }),
        ('Auditoría', {
            'fields': ('fecha_creacion', 'fecha_modificacion', 'creado_por', 'eliminado')
        }),
    )

    readonly_fields = ('fecha_creacion', 'fecha_modificacion')

    def esta_en_uso_admin(self, obj):
        if obj.esta_en_uso():
            return format_html('<span style="color: red;">En Uso</span>')
        else:
            return format_html('<span style="color: green;">Libre</span>')

    esta_en_uso_admin.short_description = 'Estado'


@admin.register(Roles)
class RolesAdmin(admin.ModelAdmin):
    """Administración de roles"""

    list_display = ('nombre', 'activo', 'es_sistema', 'cantidad_usuarios_admin', 'cantidad_permisos_admin',
                    'fecha_creacion')
    list_filter = ('activo', 'es_sistema', 'eliminado', 'fecha_creacion')
    search_fields = ('nombre', 'descripcion')
    ordering = ('nombre',)
    filter_horizontal = ('permisos',)

    fieldsets = (
        ('Información del Rol', {
            'fields': ('nombre', 'descripcion', 'activo', 'es_sistema')
        }),
        ('Permisos', {
            'fields': ('permisos',)
        }),
        ('Auditoría', {
            'fields': ('fecha_creacion', 'fecha_modificacion', 'creado_por', 'eliminado')
        }),
    )

    readonly_fields = ('fecha_creacion', 'fecha_modificacion')

    def cantidad_usuarios_admin(self, obj):
        count = obj.cantidad_usuarios
        if count > 0:
            return format_html('<span style="color: blue;">{} usuarios</span>', count)
        return '0 usuarios'

    cantidad_usuarios_admin.short_description = 'Usuarios'

    def cantidad_permisos_admin(self, obj):
        count = obj.cantidad_permisos
        return f'{count} permisos'

    cantidad_permisos_admin.short_description = 'Permisos'


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    """Administración de logs de auditoría"""

    list_display = ('fecha_hora', 'usuario', 'accion', 'app_label', 'model_name', 'objeto_representacion', 'ip_address')
    list_filter = ('accion', 'app_label', 'model_name', 'fecha_hora')
    search_fields = ('usuario__nombres', 'objeto_representacion', 'ip_address')
    ordering = ('-fecha_hora',)

    fieldsets = (
        ('Información de la Acción', {
            'fields': ('usuario', 'accion', 'accion_personalizada', 'fecha_hora')
        }),
        ('Objeto Afectado', {
            'fields': ('app_label', 'model_name', 'object_id', 'objeto_representacion')
        }),
        ('Detalles', {
            'fields': ('detalles', 'ip_address', 'user_agent')
        }),
    )

    readonly_fields = ('fecha_hora',)

    # Solo lectura
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Empleado_fdw)
class EmpleadoFdwAdmin(admin.ModelAdmin):
    """Administración de empleados FDW (solo lectura)"""

    list_display = ('codigocotel', 'nombre_completo_admin', 'estadoempleado', 'fechaingreso', 'esta_migrado_admin')
    list_filter = ('estadoempleado',)
    search_fields = ('codigocotel', 'nombres', 'apellidopaterno', 'apellidomaterno')
    ordering = ('apellidopaterno', 'apellidomaterno', 'nombres')

    def nombre_completo_admin(self, obj):
        return obj.nombre_completo

    nombre_completo_admin.short_description = 'Nombre Completo'

    def esta_migrado_admin(self, obj):
        if obj.esta_migrado:
            return format_html('<span style="color: green;">Migrado</span>')
        else:
            return format_html('<span style="color: orange;">Pendiente</span>')

    esta_migrado_admin.short_description = 'Estado Migración'

    # Solo lectura
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


# Personalizar el admin site
admin.site.site_header = "Administración COTEL"
admin.site.site_title = "COTEL Admin"
admin.site.index_title = "Panel de Administración"