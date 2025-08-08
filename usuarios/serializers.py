from rest_framework import serializers
from django.db import transaction
from django.utils import timezone
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from .models import Usuario, Empleado_fdw, Permission, Roles, AuditLog, crear_log_auditoria
import re


def get_client_ip(request):
    """Obtener IP del cliente"""
    if not request:
        return None
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def get_user_agent(request):
    """Obtener User Agent del cliente"""
    return request.META.get('HTTP_USER_AGENT', '') if request else ''


# ========== SERIALIZERS DE AUDITORÍA ==========

class AuditLogSerializer(serializers.ModelSerializer):
    usuario_nombre = serializers.CharField(source='usuario.nombre_completo', read_only=True)
    accion_display = serializers.CharField(source='get_accion_display', read_only=True)
    fecha_hora_formateada = serializers.SerializerMethodField()

    class Meta:
        model = AuditLog
        fields = [
            'id', 'usuario', 'usuario_nombre', 'accion', 'accion_display',
            'accion_personalizada', 'app_label', 'model_name', 'object_id',
            'objeto_representacion', 'detalles', 'ip_address', 'user_agent',
            'fecha_hora', 'fecha_hora_formateada'
        ]
        read_only_fields = ['id', 'fecha_hora']

    def get_fecha_hora_formateada(self, obj):
        return obj.fecha_hora.strftime('%d/%m/%Y %H:%M:%S')


# ========== SERIALIZERS DE PERMISOS ==========

class PermissionSerializer(serializers.ModelSerializer):
    esta_en_uso = serializers.SerializerMethodField()
    creado_por_nombre = serializers.CharField(source='creado_por.nombre_completo', read_only=True)

    class Meta:
        model = Permission
        fields = [
            'id', 'recurso', 'accion', 'descripcion', 'activo',
            'fecha_creacion', 'fecha_modificacion', 'creado_por',
            'creado_por_nombre', 'esta_en_uso'
        ]
        read_only_fields = ['fecha_creacion', 'fecha_modificacion']

    def get_esta_en_uso(self, obj):
        return obj.esta_en_uso()

    def validate_recurso(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError("El recurso es obligatorio")

        value = value.strip().lower()

        if len(value) < 2:
            raise serializers.ValidationError("El recurso debe tener al menos 2 caracteres")
        if len(value) > 50:
            raise serializers.ValidationError("El recurso no puede tener más de 50 caracteres")

        if not re.match(r'^[a-z0-9-_]+$', value):
            raise serializers.ValidationError(
                "El recurso solo puede contener letras minúsculas, números, guiones y guiones bajos"
            )

        return value

    def validate(self, data):
        recurso = data.get('recurso')
        accion = data.get('accion')

        if recurso and accion:
            queryset = Permission.objects.filter(recurso=recurso, accion=accion)
            if self.instance:
                queryset = queryset.exclude(pk=self.instance.pk)

            if queryset.exists():
                raise serializers.ValidationError({
                    'non_field_errors': [f"Ya existe un permiso '{recurso}:{accion}'"]
                })

        return data

    def create(self, validated_data):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            validated_data['creado_por'] = request.user

        permiso = super().create(validated_data)

        # Log de auditoría
        if request and request.user.is_authenticated:
            crear_log_auditoria(
                usuario=request.user,
                accion='CREATE',
                objeto=permiso,
                detalles={'recurso': permiso.recurso, 'accion': permiso.accion},
                ip_address=get_client_ip(request),
                user_agent=get_user_agent(request)
            )

        return permiso

    def update(self, instance, validated_data):
        request = self.context.get('request')
        valores_anteriores = {
            'recurso': instance.recurso,
            'accion': instance.accion,
            'activo': instance.activo
        }

        permiso = super().update(instance, validated_data)

        # Log de auditoría
        if request and request.user.is_authenticated:
            crear_log_auditoria(
                usuario=request.user,
                accion='UPDATE',
                objeto=permiso,
                detalles={
                    'valores_anteriores': valores_anteriores,
                    'valores_nuevos': validated_data
                },
                ip_address=get_client_ip(request),
                user_agent=get_user_agent(request)
            )

        return permiso


# ========== SERIALIZERS DE ROLES ==========

class RolesSerializer(serializers.ModelSerializer):
    permisos = PermissionSerializer(many=True, read_only=True)
    permisos_ids = serializers.ListField(
        child=serializers.IntegerField(),
        write_only=True,
        required=False,
        allow_empty=True
    )
    cantidad_usuarios = serializers.ReadOnlyField()
    cantidad_permisos = serializers.ReadOnlyField()
    puede_eliminar = serializers.SerializerMethodField()
    creado_por_nombre = serializers.CharField(source='creado_por.nombre_completo', read_only=True)

    class Meta:
        model = Roles
        fields = [
            'id', 'nombre', 'descripcion', 'activo', 'es_sistema',
            'fecha_creacion', 'fecha_modificacion', 'creado_por',
            'creado_por_nombre', 'permisos', 'permisos_ids',
            'cantidad_usuarios', 'cantidad_permisos', 'puede_eliminar'
        ]
        read_only_fields = ['fecha_creacion', 'fecha_modificacion', 'es_sistema']

    def get_puede_eliminar(self, obj):
        return obj.puede_eliminar()

    def validate_nombre(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError("El nombre del rol es obligatorio")

        value = value.strip()

        if len(value) < 2:
            raise serializers.ValidationError("El nombre debe tener al menos 2 caracteres")
        if len(value) > 50:
            raise serializers.ValidationError("El nombre no puede tener más de 50 caracteres")

        # Verificar unicidad
        queryset = Roles.objects.filter(nombre__iexact=value)
        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)

        if queryset.exists():
            raise serializers.ValidationError(f"Ya existe un rol con el nombre '{value}'")

        return value

    def validate_permisos_ids(self, value):
        if not value:
            return value

        permisos_existentes = Permission.objects.filter(
            id__in=value,
            activo=True,
            eliminado=False
        )
        ids_encontrados = set(permisos_existentes.values_list('id', flat=True))
        ids_solicitados = set(value)

        ids_no_encontrados = ids_solicitados - ids_encontrados
        if ids_no_encontrados:
            raise serializers.ValidationError(
                f"Los siguientes IDs de permisos no existen o no están activos: {list(ids_no_encontrados)}"
            )

        return value

    def create(self, validated_data):
        permisos_ids = validated_data.pop('permisos_ids', [])
        request = self.context.get('request')

        if request and request.user.is_authenticated:
            validated_data['creado_por'] = request.user

        with transaction.atomic():
            rol = Roles.objects.create(**validated_data)

            if permisos_ids:
                permisos = Permission.objects.filter(id__in=permisos_ids)
                rol.permisos.set(permisos)

            # Log de auditoría
            if request and request.user.is_authenticated:
                crear_log_auditoria(
                    usuario=request.user,
                    accion='CREATE',
                    objeto=rol,
                    detalles={'nombre': rol.nombre, 'permisos_asignados': permisos_ids},
                    ip_address=get_client_ip(request),
                    user_agent=get_user_agent(request)
                )

            return rol

    def update(self, instance, validated_data):
        permisos_ids = validated_data.pop('permisos_ids', None)
        request = self.context.get('request')

        with transaction.atomic():
            for attr, value in validated_data.items():
                setattr(instance, attr, value)
            instance.save()

            if permisos_ids is not None:
                permisos = Permission.objects.filter(id__in=permisos_ids)
                instance.permisos.set(permisos)

            # Log de auditoría
            if request and request.user.is_authenticated:
                crear_log_auditoria(
                    usuario=request.user,
                    accion='UPDATE',
                    objeto=instance,
                    detalles={'permisos_nuevos': permisos_ids},
                    ip_address=get_client_ip(request),
                    user_agent=get_user_agent(request)
                )

            return instance


# ========== SERIALIZERS DE USUARIOS ==========

class UsuarioListSerializer(serializers.ModelSerializer):
    rol_nombre = serializers.CharField(source='rol.nombre', read_only=True)
    nombre_completo = serializers.ReadOnlyField()
    tipo_usuario = serializers.SerializerMethodField()
    estado_password = serializers.SerializerMethodField()
    esta_bloqueado = serializers.ReadOnlyField()
    creado_por_nombre = serializers.CharField(source='creado_por.nombre_completo', read_only=True)

    class Meta:
        model = Usuario
        fields = [
            'id', 'codigocotel', 'nombre_completo', 'nombres',
            'apellidopaterno', 'apellidomaterno', 'estadoempleado',
            'fechaingreso', 'fecha_creacion', 'is_active',
            'password_changed', 'password_reset_required', 'rol_nombre',
            'tipo_usuario', 'estado_password', 'esta_bloqueado',
            'creado_por_nombre', 'last_login', 'intentos_login_fallidos'
        ]

    def get_tipo_usuario(self, obj):
        return 'manual' if obj.es_usuario_manual else 'migrado'

    def get_estado_password(self, obj):
        if obj.password_reset_required:
            return 'reset_requerido'
        elif not obj.password_changed:
            return 'cambio_requerido'
        else:
            return 'ok'


class UsuarioDetailSerializer(UsuarioListSerializer):
    permisos = serializers.SerializerMethodField()

    class Meta(UsuarioListSerializer.Meta):
        fields = UsuarioListSerializer.Meta.fields + [
            'permisos', 'ultimo_login_ip', 'password_reset_date', 'bloqueado_hasta'
        ]

    def get_permisos(self, obj):
        if obj.rol:
            return list(obj.rol.permisos.filter(
                activo=True,
                eliminado=False
            ).values('id', 'recurso', 'accion', 'descripcion'))
        return []


class UsuarioManualSerializer(serializers.ModelSerializer):
    codigocotel = serializers.IntegerField(read_only=True)
    rol_nombre = serializers.CharField(source='rol.nombre', read_only=True)
    nombre_completo = serializers.ReadOnlyField()

    class Meta:
        model = Usuario
        fields = [
            'id', 'codigocotel', 'nombres', 'apellidopaterno',
            'apellidomaterno', 'rol', 'rol_nombre', 'nombre_completo',
            'is_active', 'password_changed', 'password_reset_required',
            'fecha_creacion', 'creado_por'
        ]
        read_only_fields = [
            'codigocotel', 'fecha_creacion', 'creado_por',
            'password_changed', 'password_reset_required'
        ]

    def validate_nombres(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError("Los nombres son obligatorios")

        value = value.strip()
        if len(value) < 2:
            raise serializers.ValidationError("Los nombres deben tener al menos 2 caracteres")

        if not re.match(r'^[a-zA-ZáéíóúÁÉÍÓÚñÑ\s\-\'\.]+$', value):
            raise serializers.ValidationError(
                "Los nombres solo pueden contener letras, espacios, guiones, apostrofes y puntos"
            )

        return value

    def validate_apellidopaterno(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError("El apellido paterno es obligatorio")

        value = value.strip()
        if len(value) < 2:
            raise serializers.ValidationError("El apellido paterno debe tener al menos 2 caracteres")

        if not re.match(r'^[a-zA-ZáéíóúÁÉÍÓÚñÑ\s\-\'\.]+$', value):
            raise serializers.ValidationError(
                "El apellido paterno solo puede contener letras, espacios, guiones, apostrofes y puntos"
            )

        return value

    def validate_apellidomaterno(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError("El apellido materno es obligatorio")

        value = value.strip()
        if len(value) < 2:
            raise serializers.ValidationError("El apellido materno debe tener al menos 2 caracteres")

        if not re.match(r'^[a-zA-ZáéíóúÁÉÍÓÚñÑ\s\-\'\.]+$', value):
            raise serializers.ValidationError(
                "El apellido materno solo puede contener letras, espacios, guiones, apostrofes y puntos"
            )

        return value

    def validate_rol(self, value):
        if not value:
            raise serializers.ValidationError("El rol es obligatorio")

        if not value.activo or value.eliminado:
            raise serializers.ValidationError("El rol seleccionado no está activo")

        return value

    def create(self, validated_data):
        request = self.context.get('request')

        with transaction.atomic():
            codigocotel = Usuario.objects.generar_codigo_cotel_disponible()

            usuario = Usuario.objects.create(
                codigocotel=codigocotel,
                persona=None,
                apellidopaterno=validated_data['apellidopaterno'],
                apellidomaterno=validated_data['apellidomaterno'],
                nombres=validated_data['nombres'],
                estadoempleado=0,
                fechaingreso=timezone.now().date(),
                rol=validated_data['rol'],
                password_changed=False,
                password_reset_required=False,
                creado_por=request.user if request and request.user.is_authenticated else None
            )

            usuario.set_password(str(codigocotel))
            usuario.save()

            # Log de auditoría
            if request and request.user.is_authenticated:
                crear_log_auditoria(
                    usuario=request.user,
                    accion='CREATE',
                    objeto=usuario,
                    detalles={
                        'tipo': 'manual',
                        'codigocotel': codigocotel,
                        'rol': validated_data['rol'].nombre
                    },
                    ip_address=get_client_ip(request),
                    user_agent=get_user_agent(request)
                )

            return usuario

    def update(self, instance, validated_data):
        request = self.context.get('request')

        # Guardar valores anteriores para auditoría
        valores_anteriores = {}
        for field in validated_data.keys():
            if hasattr(instance, field):
                old_value = getattr(instance, field)
                if field == 'rol' and old_value:
                    # Serializar el rol anterior como diccionario
                    valores_anteriores[field] = {
                        'id': old_value.id,
                        'nombre': old_value.nombre
                    }
                else:
                    valores_anteriores[field] = old_value

        # Preparar valores nuevos para auditoría
        valores_nuevos = {}
        for field, value in validated_data.items():
            if field == 'rol' and value:
                # Serializar el rol nuevo como diccionario
                valores_nuevos[field] = {
                    'id': value.id,
                    'nombre': value.nombre
                }
            else:
                valores_nuevos[field] = value

        # Actualizar la instancia
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        # Log de auditoría con datos serializables
        if request and request.user.is_authenticated:
            try:
                crear_log_auditoria(
                    usuario=request.user,
                    accion='UPDATE',
                    objeto=instance,
                    detalles={
                        'valores_anteriores': valores_anteriores,
                        'valores_nuevos': valores_nuevos,
                        'campos_actualizados': list(validated_data.keys())
                    },
                    ip_address=get_client_ip(request),
                    user_agent=get_user_agent(request)
                )
            except Exception as e:
                # Si hay error en auditoría, solo loggearlo pero no fallar
                print(f"Error en log de auditoría: {str(e)}")

        return instance


# ========== SERIALIZERS DE EMPLEADOS FDW ==========

class EmpleadoDisponibleSerializer(serializers.ModelSerializer):
    nombre_completo = serializers.ReadOnlyField()
    puede_migrar = serializers.ReadOnlyField()
    esta_activo = serializers.ReadOnlyField()
    estado_texto = serializers.SerializerMethodField()

    class Meta:
        model = Empleado_fdw
        fields = [
            'persona', 'codigocotel', 'nombres', 'apellidopaterno',
            'apellidomaterno', 'nombre_completo', 'estadoempleado',
            'estado_texto', 'fechaingreso', 'puede_migrar', 'esta_activo'
        ]

    def get_estado_texto(self, obj):
        return 'Activo' if obj.esta_activo else 'Inactivo'


class MigrarEmpleadoSerializer(serializers.Serializer):
    empleado_persona = serializers.IntegerField()
    rol_id = serializers.IntegerField()

    def validate_empleado_persona(self, value):
        try:
            empleado = Empleado_fdw.objects.get(persona=value)
        except Empleado_fdw.DoesNotExist:
            raise serializers.ValidationError("El empleado no existe")

        if not empleado.puede_migrar:
            if empleado.esta_migrado:
                raise serializers.ValidationError("El empleado ya está migrado")
            else:
                raise serializers.ValidationError("El empleado no está activo")

        return value

    def validate_rol_id(self, value):
        try:
            rol = Roles.objects.get(id=value)
        except Roles.DoesNotExist:
            raise serializers.ValidationError("El rol no existe")

        if not rol.activo or rol.eliminado:
            raise serializers.ValidationError("El rol no está activo")

        return value

    def create(self, validated_data):
        empleado_persona = validated_data['empleado_persona']
        rol_id = validated_data['rol_id']
        request = self.context.get('request')

        with transaction.atomic():
            empleado = Empleado_fdw.objects.get(persona=empleado_persona)
            rol = Roles.objects.get(id=rol_id)

            if not empleado.puede_migrar:
                raise serializers.ValidationError("El empleado ya no puede ser migrado")

            usuario = Usuario.objects.create(
                codigocotel=empleado.codigocotel,
                persona=empleado.persona,
                apellidopaterno=empleado.apellidopaterno,
                apellidomaterno=empleado.apellidomaterno,
                nombres=empleado.nombres,
                estadoempleado=empleado.estadoempleado,
                fechaingreso=empleado.fechaingreso,
                rol=rol,
                password_changed=False,
                password_reset_required=False,
                creado_por=request.user if request and request.user.is_authenticated else None
            )

            usuario.set_password(str(empleado.codigocotel))
            usuario.save()

            # Log de auditoría
            if request and request.user.is_authenticated:
                crear_log_auditoria(
                    usuario=request.user,
                    accion='MIGRATE_USER',
                    objeto=usuario,
                    detalles={
                        'tipo': 'migrado',
                        'empleado_persona': empleado_persona,
                        'rol': rol.nombre
                    },
                    ip_address=get_client_ip(request),
                    user_agent=get_user_agent(request)
                )

            return usuario


# ========== SERIALIZERS DE CONTRASEÑAS ==========

class ResetPasswordSerializer(serializers.Serializer):
    usuario_id = serializers.IntegerField()
    motivo = serializers.CharField(max_length=200, required=False, allow_blank=True)

    def validate_usuario_id(self, value):
        try:
            usuario = Usuario.objects.get(id=value)
        except Usuario.DoesNotExist:
            raise serializers.ValidationError("El usuario no existe")

        if usuario.is_superuser:
            raise serializers.ValidationError("No se puede resetear la contraseña de un superusuario")

        if usuario.eliminado:
            raise serializers.ValidationError("No se puede resetear la contraseña de un usuario eliminado")

        return value

    def save(self):
        usuario_id = self.validated_data['usuario_id']
        motivo = self.validated_data.get('motivo', '')
        request = self.context.get('request')

        with transaction.atomic():
            usuario = Usuario.objects.get(id=usuario_id)
            usuario.resetear_password(
                admin_user=request.user if request and request.user.is_authenticated else None
            )

            # Log de auditoría
            if request and request.user.is_authenticated:
                crear_log_auditoria(
                    usuario=request.user,
                    accion='RESET_PASSWORD',
                    objeto=usuario,
                    detalles={'motivo': motivo},
                    ip_address=get_client_ip(request),
                    user_agent=get_user_agent(request)
                )

            return usuario


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(required=True)
    new_password = serializers.CharField(required=True, min_length=8)
    confirm_password = serializers.CharField(required=True)

    def validate_new_password(self, value):
        try:
            validate_password(value)
        except DjangoValidationError as e:
            raise serializers.ValidationError(list(e.messages))
        return value

    def validate(self, data):
        if data['new_password'] != data['confirm_password']:
            raise serializers.ValidationError("Las contraseñas no coinciden")
        return data

    def save(self, user):
        request = self.context.get('request')

        with transaction.atomic():
            user.set_password(self.validated_data['new_password'])
            user.password_changed = True
            user.password_reset_required = False
            user.reset_intentos_fallidos()
            user.save()

            # Log de auditoría
            if request:
                crear_log_auditoria(
                    usuario=user,
                    accion='CHANGE_PASSWORD',
                    objeto=user,
                    detalles={'cambio_exitoso': True},
                    ip_address=get_client_ip(request),
                    user_agent=get_user_agent(request)
                )

        return user


# ========== SERIALIZERS LEGACY (COMPATIBILIDAD) ==========

class UsuarioSerializer(serializers.ModelSerializer):
    class Meta:
        model = Usuario
        fields = [
            'codigocotel', 'persona', 'apellidopaterno',
            'apellidomaterno', 'nombres', 'estadoempleado',
            'fechaingreso', 'password'
        ]
        extra_kwargs = {
            'password': {'write_only': True}
        }

    def create(self, validated_data):
        password = validated_data.pop('password', None)
        usuario = Usuario.objects.create(**validated_data)
        if password:
            usuario.set_password(password)
            usuario.save()
        return usuario


class EmpleadoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Empleado_fdw
        fields = [
            'persona', 'apellidopaterno', 'apellidomaterno',
            'nombres', 'estadoempleado', 'codigocotel',
            'fechaingreso'
        ]