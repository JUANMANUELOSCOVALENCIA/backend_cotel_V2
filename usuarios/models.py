from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db.models import Max


class UsuarioManager(BaseUserManager):
    def create_user(self, codigocotel, password=None, **extra_fields):
        if not codigocotel:
            raise ValueError('El código COTEL es obligatorio')
        user = self.model(codigocotel=codigocotel, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, codigocotel, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        return self.create_user(codigocotel, password, **extra_fields)

    # NUEVO: Método para generar código COTEL seguro
    def generar_codigo_cotel_disponible(self):
        """
        Genera un código COTEL >= 9000 que no esté en uso
        en la tabla Usuario ni en la tabla FDW
        """
        # Buscar el último código >= 9000 en la tabla Usuario
        ultimo_codigo = self.filter(codigocotel__gte=9000).aggregate(
            Max('codigocotel')
        )['codigocotel__max']

        # Si no hay códigos >= 9000, empezar desde 9000
        codigo_candidato = max(9000, (ultimo_codigo or 8999) + 1)

        while True:
            # Verificar que no existe en tabla Usuario
            if self.filter(codigocotel=codigo_candidato).exists():
                codigo_candidato += 1
                continue

            # Verificar que no existe en tabla FDW
            try:
                if Empleado_fdw.objects.filter(codigocotel=codigo_candidato).exists():
                    codigo_candidato += 1
                    continue
            except Exception as e:
                # Si hay error con FDW, loggear pero continuar
                print(f"⚠️ Error al verificar FDW para código {codigo_candidato}: {e}")
                pass

            # Código disponible encontrado
            return codigo_candidato


class Permission(models.Model):
    recurso = models.CharField(max_length=50)  # ej: "contratos"
    accion = models.CharField(max_length=10)  # ej: "crear", "leer", "actualizar", "eliminar"

    class Meta:
        unique_together = ('recurso', 'accion')
        verbose_name = "Permiso"
        verbose_name_plural = "Permisos"

    def __str__(self):
        return f"{self.recurso}:{self.accion}"

    # NUEVO: Validación de acciones permitidas
    def clean(self):
        from django.core.exceptions import ValidationError
        acciones_validas = ['crear', 'leer', 'actualizar', 'eliminar']
        if self.accion not in acciones_validas:
            raise ValidationError(f'Acción debe ser una de: {", ".join(acciones_validas)}')

    # NUEVO: Verificar si está en uso
    def esta_en_uso(self):
        """Verifica si el permiso está asignado a algún rol"""
        return self.roles_set.exists()


class Roles(models.Model):
    nombre = models.CharField(max_length=50, unique=True)
    permisos = models.ManyToManyField(Permission, blank=True)

    # NUEVO: Metadatos adicionales
    activo = models.BooleanField(default=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Rol"
        verbose_name_plural = "Roles"

    def __str__(self):
        return self.nombre

    # NUEVO: Métodos de utilidad
    def tiene_usuarios(self):
        """Verifica si el rol tiene usuarios asignados"""
        return self.usuario_set.exists()

    def cantidad_usuarios(self):
        """Retorna la cantidad de usuarios con este rol"""
        return self.usuario_set.count()

    def cantidad_permisos(self):
        """Retorna la cantidad de permisos asignados"""
        return self.permisos.count()

    def puede_eliminar(self):
        """Verifica si el rol puede ser eliminado (sin usuarios asignados)"""
        return not self.tiene_usuarios()


class Usuario(AbstractBaseUser, PermissionsMixin):
    codigocotel = models.IntegerField(unique=True)
    persona = models.IntegerField(null=True, blank=True)
    apellidopaterno = models.CharField(max_length=100, null=True, blank=True)
    apellidomaterno = models.CharField(max_length=100, null=True, blank=True)
    nombres = models.CharField(max_length=100, null=True, blank=True)
    estadoempleado = models.IntegerField(default=0)
    fechaingreso = models.DateField(null=True, blank=True)
    password_changed = models.BooleanField(default=False)

    rol = models.ForeignKey(Roles, on_delete=models.SET_NULL, null=True, blank=True)

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    is_superuser = models.BooleanField(default=False)

    # NUEVO: Campos adicionales para auditoría
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    creado_por = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='usuarios_creados'
    )

    USERNAME_FIELD = 'codigocotel'
    REQUIRED_FIELDS = ['persona', 'apellidopaterno', 'apellidomaterno', 'nombres']

    objects = UsuarioManager()

    class Meta:
        verbose_name = "Usuario"
        verbose_name_plural = "Usuarios"

    def __str__(self):
        return f"{self.nombres} {self.apellidopaterno} {self.apellidomaterno}"

    def tiene_permiso(self, recurso, accion):
        if self.is_superuser:
            return True
        if not self.rol:
            return False
        return self.rol.permisos.filter(recurso=recurso, accion=accion).exists()

    # NUEVO: Métodos de utilidad
    def es_usuario_manual(self):
        """Verifica si es un usuario creado manualmente (código >= 9000 y persona null)"""
        return self.codigocotel >= 9000 and self.persona is None

    def es_usuario_migrado(self):
        """Verifica si es un usuario migrado desde FDW"""
        return self.codigocotel < 9000 or self.persona is not None

    def nombre_completo(self):
        """Retorna el nombre completo del usuario"""
        return f"{self.nombres} {self.apellidopaterno} {self.apellidomaterno}".strip()

    def requiere_cambio_password(self):
        """Verifica si requiere cambio de contraseña"""
        return not self.password_changed

    def resetear_password(self):
        """Resetea la contraseña al código COTEL y marca como pendiente de cambio"""
        self.set_password(str(self.codigocotel))
        self.password_changed = False
        self.save()


class Empleado_fdw(models.Model):
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
        verbose_name = "Empleado FDW"
        verbose_name_plural = "Empleados FDW"

    def __str__(self):
        return f"{self.nombres} {self.apellidopaterno} - {self.codigocotel}"

    # NUEVO: Métodos de utilidad
    def esta_migrado(self):
        """Verifica si este empleado ya fue migrado a la tabla Usuario"""
        return Usuario.objects.filter(codigocotel=self.codigocotel).exists()

    def esta_activo(self):
        """Verifica si el empleado está activo"""
        return self.estadoempleado == 0

    def puede_migrar(self):
        """Verifica si el empleado puede ser migrado"""
        return self.esta_activo() and not self.esta_migrado()

    def nombre_completo(self):
        """Retorna el nombre completo del empleado"""
        return f"{self.nombres} {self.apellidopaterno} {self.apellidomaterno}".strip()
