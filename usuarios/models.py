from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db.models import Max, Q
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey
import re


# ========== MODELOS BASE PARA SOFT DELETE Y AUDITORÍA ==========

class SoftDeleteQuerySet(models.QuerySet):
    """QuerySet personalizado para soft delete"""

    def delete(self):
        """Override delete para hacer soft delete por defecto"""
        return self.update(eliminado=True, fecha_eliminacion=timezone.now())

    def hard_delete(self):
        """Eliminación física real (usar con precaución)"""
        return super().delete()

    def active(self):
        """Solo objetos no eliminados"""
        return self.filter(eliminado=False)

    def deleted(self):
        """Solo objetos eliminados"""
        return self.filter(eliminado=True)


class SoftDeleteManager(models.Manager):
    """Manager que excluye objetos eliminados por defecto"""

    def get_queryset(self):
        return SoftDeleteQuerySet(self.model, using=self._db).filter(eliminado=False)

    def with_deleted(self):
        """Incluir objetos eliminados"""
        return SoftDeleteQuerySet(self.model, using=self._db)

    def deleted_only(self):
        """Solo objetos eliminados"""
        return SoftDeleteQuerySet(self.model, using=self._db).filter(eliminado=True)


class SoftDeleteModel(models.Model):
    """Modelo base para eliminación lógica universal"""
    eliminado = models.BooleanField(default=False, db_index=True)
    fecha_eliminacion = models.DateTimeField(null=True, blank=True)
    eliminado_por = models.ForeignKey(
        'Usuario',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='%(app_label)s_%(class)s_eliminados'
    )

    objects = SoftDeleteManager()
    all_objects = models.Manager()  # Para acceder a todos los objetos

    class Meta:
        abstract = True

    def delete(self, using=None, keep_parents=False, user=None):
        """Soft delete por defecto"""
        self.eliminado = True
        self.fecha_eliminacion = timezone.now()
        if user:
            self.eliminado_por = user
        self.save(using=using, update_fields=['eliminado', 'fecha_eliminacion', 'eliminado_por'])

    def hard_delete(self, using=None, keep_parents=False):
        """Eliminación física real"""
        return super().delete(using=using, keep_parents=keep_parents)

    def restore(self):
        """Restaurar objeto eliminado"""
        self.eliminado = False
        self.fecha_eliminacion = None
        self.eliminado_por = None
        self.save(update_fields=['eliminado', 'fecha_eliminacion', 'eliminado_por'])


# ========== SISTEMA DE AUDITORÍA UNIVERSAL ==========

class AuditLog(models.Model):
    """Sistema de auditoría universal para TODAS las apps"""

    class AccionChoices(models.TextChoices):
        CREATE = 'CREATE', 'Crear'
        UPDATE = 'UPDATE', 'Actualizar'
        DELETE = 'DELETE', 'Eliminar'
        RESTORE = 'RESTORE', 'Restaurar'
        LOGIN = 'LOGIN', 'Iniciar Sesión'
        LOGOUT = 'LOGOUT', 'Cerrar Sesión'
        RESET_PASSWORD = 'RESET_PASSWORD', 'Resetear Contraseña'
        CHANGE_PASSWORD = 'CHANGE_PASSWORD', 'Cambiar Contraseña'
        MIGRATE_USER = 'MIGRATE_USER', 'Migrar Usuario'
        ACTIVATE_USER = 'ACTIVATE_USER', 'Activar Usuario'
        DEACTIVATE_USER = 'DEACTIVATE_USER', 'Desactivar Usuario'
        ASSIGN_ROLE = 'ASSIGN_ROLE', 'Asignar Rol'
        REVOKE_ROLE = 'REVOKE_ROLE', 'Revocar Rol'
        APPROVE = 'APPROVE', 'Aprobar'
        REJECT = 'REJECT', 'Rechazar'
        TRANSFER = 'TRANSFER', 'Transferir'
        CUSTOM = 'CUSTOM', 'Acción Personalizada'

    # Usuario que realizó la acción
    usuario = models.ForeignKey(
        'Usuario',
        on_delete=models.CASCADE,
        related_name='logs_realizados'
    )

    # Acción realizada
    accion = models.CharField(
        max_length=20,
        choices=AccionChoices.choices,
        db_index=True
    )
    accion_personalizada = models.CharField(
        max_length=100,
        blank=True,
        help_text="Descripción cuando accion=CUSTOM"
    )

    # Objeto afectado (Generic Foreign Key)
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.CharField(max_length=100, db_index=True)
    content_object = GenericForeignKey('content_type', 'object_id')

    # Información del objeto
    objeto_representacion = models.CharField(max_length=200)
    app_label = models.CharField(max_length=50, db_index=True)
    model_name = models.CharField(max_length=50, db_index=True)

    # Detalles (JSON)
    detalles = models.JSONField(default=dict, blank=True)

    # Información de sesión
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(null=True, blank=True)

    # Timestamp
    fecha_hora = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "Log de Auditoría"
        verbose_name_plural = "Logs de Auditoría"
        ordering = ['-fecha_hora']
        indexes = [
            models.Index(fields=['app_label', 'model_name', '-fecha_hora']),
            models.Index(fields=['usuario', '-fecha_hora']),
            models.Index(fields=['accion', '-fecha_hora']),
        ]

    def __str__(self):
        accion_display = self.accion_personalizada if self.accion == self.AccionChoices.CUSTOM else self.get_accion_display()
        return f"{self.usuario} - {accion_display} - {self.app_label}.{self.model_name}"


def crear_log_auditoria(usuario, accion, objeto, detalles=None, ip_address=None,
                        user_agent=None, accion_personalizada=None):
    """Función universal para crear logs de auditoría"""
    if not usuario or not objeto:
        return None

    content_type = ContentType.objects.get_for_model(objeto)

    return AuditLog.objects.create(
        usuario=usuario,
        accion=accion,
        accion_personalizada=accion_personalizada or '',
        content_type=content_type,
        object_id=str(objeto.pk),
        objeto_representacion=str(objeto)[:200],
        app_label=content_type.app_label,
        model_name=content_type.model,
        detalles=detalles or {},
        ip_address=ip_address,
        user_agent=user_agent
    )


# ========== MANAGER OPTIMIZADO PARA USUARIOS ==========

class UsuarioQuerySet(models.QuerySet):
    """QuerySet personalizado para Usuario"""

    def activos(self):
        """Usuarios activos y no eliminados"""
        return self.filter(is_active=True, eliminado=False)

    def manuales(self):
        """Usuarios creados manualmente (código >= 9000)"""
        return self.filter(codigocotel__gte=9000, persona__isnull=True)

    def migrados(self):
        """Usuarios migrados desde FDW"""
        return self.filter(Q(codigocotel__lt=9000) | Q(persona__isnull=False))

    def con_rol(self, rol_nombre):
        """Usuarios con un rol específico"""
        return self.filter(rol__nombre=rol_nombre, rol__activo=True)

    def bloqueados(self):
        """Usuarios actualmente bloqueados"""
        return self.filter(bloqueado_hasta__gt=timezone.now())

    def password_pendiente(self):
        """Usuarios que necesitan cambiar contraseña"""
        return self.filter(Q(password_changed=False) | Q(password_reset_required=True))


class UsuarioManager(BaseUserManager):
    """Manager optimizado para Usuario"""

    def get_queryset(self):
        return UsuarioQuerySet(self.model, using=self._db).filter(eliminado=False)

    def with_deleted(self):
        """Incluir usuarios eliminados"""
        return UsuarioQuerySet(self.model, using=self._db)

    def create_user(self, codigocotel, password=None, **extra_fields):
        """Crear usuario normal"""
        if not codigocotel:
            raise ValueError('El código COTEL es obligatorio')

        user = self.model(codigocotel=codigocotel, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, codigocotel, password=None, **extra_fields):
        """Crear superusuario"""
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)

        return self.create_user(codigocotel, password, **extra_fields)

    def generar_codigo_cotel_disponible(self):
        """Genera código COTEL >= 9000 disponible"""
        ultimo_codigo = self.with_deleted().filter(
            codigocotel__gte=9000
        ).aggregate(Max('codigocotel'))['codigocotel__max']

        codigo_candidato = max(9000, (ultimo_codigo or 8999) + 1)

        while True:
            # Verificar Usuario
            if self.with_deleted().filter(codigocotel=codigo_candidato).exists():
                codigo_candidato += 1
                continue

            # Verificar FDW
            try:
                if Empleado_fdw.objects.filter(codigocotel=codigo_candidato).exists():
                    codigo_candidato += 1
                    continue
            except:
                pass

            return codigo_candidato


# ========== MODELO DE PERMISOS ==========

class Permission(SoftDeleteModel):
    """Permisos del sistema"""

    class AccionChoices(models.TextChoices):
        CREAR = 'crear', 'Crear'
        LEER = 'leer', 'Leer'
        ACTUALIZAR = 'actualizar', 'Actualizar'
        ELIMINAR = 'eliminar', 'Eliminar'

    recurso = models.CharField(max_length=50)
    accion = models.CharField(max_length=10, choices=AccionChoices.choices)
    descripcion = models.TextField(blank=True)
    activo = models.BooleanField(default=True)

    # Auditoría
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_modificacion = models.DateTimeField(auto_now=True)
    creado_por = models.ForeignKey(
        'Usuario',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='permisos_creados'
    )

    class Meta:
        unique_together = [('recurso', 'accion')]
        verbose_name = "Permiso"
        verbose_name_plural = "Permisos"
        # Sin constraints de regex para evitar problemas

    def __str__(self):
        return f"{self.recurso}:{self.accion}"

    def clean(self):
        if self.recurso:
            self.recurso = self.recurso.strip().lower()
            # Validación en Python en lugar de constraint de BD
            if not re.match(r'^[a-z0-9\-_]+$', self.recurso):
                raise ValidationError('Recurso con formato inválido')

    def esta_en_uso(self):
        """Verifica si está asignado a algún rol activo"""
        return self.roles_set.filter(activo=True, eliminado=False).exists()


# ========== MODELO DE ROLES ==========

class Roles(SoftDeleteModel):
    """Roles del sistema"""

    nombre = models.CharField(max_length=50, unique=True)
    descripcion = models.TextField(blank=True)
    permisos = models.ManyToManyField(Permission, blank=True)
    activo = models.BooleanField(default=True)
    es_sistema = models.BooleanField(default=False)

    # Auditoría
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_modificacion = models.DateTimeField(auto_now=True)
    creado_por = models.ForeignKey(
        'Usuario',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='roles_creados'
    )

    class Meta:
        verbose_name = "Rol"
        verbose_name_plural = "Roles"

    def __str__(self):
        return self.nombre

    def clean(self):
        if self.nombre:
            self.nombre = self.nombre.strip()

    @property
    def cantidad_usuarios(self):
        return self.usuario_set.activos().count()

    @property
    def cantidad_permisos(self):
        return self.permisos.filter(activo=True, eliminado=False).count()

    def puede_eliminar(self):
        return not self.es_sistema and not self.usuario_set.activos().exists()


# ========== MODELO DE USUARIO ==========

class Usuario(AbstractBaseUser, PermissionsMixin, SoftDeleteModel):
    """Modelo de usuario optimizado"""

    # Campos principales
    codigocotel = models.IntegerField(unique=True)
    persona = models.IntegerField(null=True, blank=True)  # Para migrados de FDW

    # Información personal
    apellidopaterno = models.CharField(max_length=100, null=True, blank=True)
    apellidomaterno = models.CharField(max_length=100, null=True, blank=True)
    nombres = models.CharField(max_length=100, null=True, blank=True)

    # Estado laboral
    estadoempleado = models.IntegerField(default=0)
    fechaingreso = models.DateField(null=True, blank=True)

    # Control de contraseñas
    password_changed = models.BooleanField(default=False)
    password_reset_required = models.BooleanField(default=False)
    password_reset_date = models.DateTimeField(null=True, blank=True)
    password_reset_by = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='passwords_reseteados'
    )

    # Seguridad
    ultimo_login_ip = models.GenericIPAddressField(null=True, blank=True)
    intentos_login_fallidos = models.IntegerField(default=0)
    bloqueado_hasta = models.DateTimeField(null=True, blank=True)

    # Rol
    rol = models.ForeignKey(
        Roles,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        limit_choices_to={'activo': True, 'eliminado': False}
    )

    # Django User fields
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    is_superuser = models.BooleanField(default=False)

    # Auditoría
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    creado_por = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='usuarios_creados'
    )

    USERNAME_FIELD = 'codigocotel'
    REQUIRED_FIELDS = ['nombres', 'apellidopaterno', 'apellidomaterno']

    objects = UsuarioManager()

    class Meta:
        verbose_name = "Usuario"
        verbose_name_plural = "Usuarios"
        indexes = [
            models.Index(fields=['codigocotel']),
            models.Index(fields=['is_active', 'eliminado']),
            models.Index(fields=['rol']),
        ]

    def __str__(self):
        if self.nombres and self.apellidopaterno:
            return f"{self.nombres} {self.apellidopaterno} {self.apellidomaterno or ''}".strip()
        return f"Usuario {self.codigocotel}"

    def clean(self):
        """Validaciones"""
        if self.es_usuario_manual():
            if not all([self.nombres, self.apellidopaterno, self.apellidomaterno]):
                raise ValidationError('Nombres y apellidos son obligatorios para usuarios manuales')

    # ========== MÉTODOS DE PERMISOS ==========

    def tiene_permiso(self, recurso, accion):
        """Verifica permisos específicos"""
        if self.is_superuser:
            return True

        if not self.is_active or self.eliminado or not self.rol:
            return False

        if not self.rol.activo or self.rol.eliminado:
            return False

        return self.rol.permisos.filter(
            recurso=recurso,
            accion=accion,
            activo=True,
            eliminado=False
        ).exists()

    # ========== MÉTODOS ÚTILES ==========

    @property
    def es_usuario_manual(self):
        return self.codigocotel >= 9000 and self.persona is None

    @property
    def es_usuario_migrado(self):
        return self.codigocotel < 9000 or self.persona is not None

    @property
    def nombre_completo(self):
        partes = [p for p in [self.nombres, self.apellidopaterno, self.apellidomaterno] if p]
        return ' '.join(partes) or f"Usuario {self.codigocotel}"

    @property
    def requiere_cambio_password(self):
        return not self.password_changed or self.password_reset_required

    @property
    def esta_bloqueado(self):
        return self.bloqueado_hasta and timezone.now() < self.bloqueado_hasta

    # ========== MÉTODOS DE ACCIÓN ==========

    def resetear_password(self, admin_user=None):
        """Resetea contraseña al código COTEL"""
        self.set_password(str(self.codigocotel))
        self.password_changed = False
        self.password_reset_required = True
        self.password_reset_date = timezone.now()
        self.password_reset_by = admin_user
        self.save()

    def bloquear_temporalmente(self, minutos=30):
        """Bloquea usuario temporalmente"""
        self.bloqueado_hasta = timezone.now() + timezone.timedelta(minutes=minutos)
        self.save(update_fields=['bloqueado_hasta'])

    def incrementar_intentos_fallidos(self):
        """Incrementa intentos fallidos"""
        self.intentos_login_fallidos += 1
        if self.intentos_login_fallidos >= 5:
            self.bloquear_temporalmente()
        self.save()

    def reset_intentos_fallidos(self):
        """Resetea intentos fallidos"""
        self.intentos_login_fallidos = 0
        self.bloqueado_hasta = None
        self.save(update_fields=['intentos_login_fallidos', 'bloqueado_hasta'])

    def puede_eliminar(self):
        """Verifica si puede ser eliminado"""
        return not self.is_superuser and not self.usuarios_creados.activos().exists()


# ========== MODELO FDW ==========

class Empleado_fdw(models.Model):
    """Modelo FDW - tabla externa"""
    persona = models.IntegerField(primary_key=True)
    apellidopaterno = models.CharField(max_length=100)
    apellidomaterno = models.CharField(max_length=100)
    nombres = models.CharField(max_length=100)
    estadoempleado = models.IntegerField()
    codigocotel = models.IntegerField(unique=True)
    fechaingreso = models.DateField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = "empleados_activos_fdw"

    def __str__(self):
        return f"{self.nombres} {self.apellidopaterno} - {self.codigocotel}"

    @property
    def esta_migrado(self):
        return Usuario.objects.with_deleted().filter(codigocotel=self.codigocotel).exists()

    @property
    def esta_activo(self):
        return self.estadoempleado == 0

    @property
    def puede_migrar(self):
        return self.esta_activo and not self.esta_migrado

    @property
    def nombre_completo(self):
        return f"{self.nombres} {self.apellidopaterno} {self.apellidomaterno}".strip()
