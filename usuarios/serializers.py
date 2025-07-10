from rest_framework import serializers
from django.db import transaction
from django.utils import timezone
from usuarios.models import Usuario, Empleado_fdw, Permission, Roles
from django.contrib.auth import get_user_model

User = get_user_model()


class PermissionSerializer(serializers.ModelSerializer):
    esta_en_uso = serializers.SerializerMethodField()

    class Meta:
        model = Permission
        fields = ['id', 'recurso', 'accion', 'esta_en_uso']

    def get_esta_en_uso(self, obj):
        """Indica si el permiso está siendo usado por algún rol"""
        return obj.esta_en_uso()

    def validate_accion(self, value):
        """Validar que la acción sea una de las permitidas"""
        acciones_validas = ['crear', 'leer', 'actualizar', 'eliminar']
        if value not in acciones_validas:
            raise serializers.ValidationError(
                f"La acción debe ser una de: {', '.join(acciones_validas)}"
            )
        return value

    def validate_recurso(self, value):
        """Validar que el recurso no esté vacío y tenga formato válido"""
        if not value or not value.strip():
            raise serializers.ValidationError("El recurso es obligatorio")

        # Convertir a minúsculas y sin espacios
        value = value.strip().lower()

        # Validar caracteres permitidos (solo letras, números y guiones)
        import re
        if not re.match(r'^[a-z0-9-_]+$', value):
            raise serializers.ValidationError(
                "El recurso solo puede contener letras, números, guiones y guiones bajos"
            )

        return value

    def validate(self, data):
        """Validar que la combinación recurso+acción sea única"""
        recurso = data.get('recurso')
        accion = data.get('accion')

        # Verificar unicidad
        queryset = Permission.objects.filter(recurso=recurso, accion=accion)

        # Si estamos editando, excluir el registro actual
        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)

        if queryset.exists():
            raise serializers.ValidationError({
                'non_field_errors': [f"Ya existe un permiso '{recurso}:{accion}'"]
            })

        return data


class RolesSerializer(serializers.ModelSerializer):
    permisos = PermissionSerializer(many=True, read_only=True)
    permisos_ids = serializers.ListField(
        child=serializers.IntegerField(),
        write_only=True,
        required=False,
        allow_empty=True
    )
    cantidad_usuarios = serializers.SerializerMethodField()
    cantidad_permisos = serializers.SerializerMethodField()
    puede_eliminar = serializers.SerializerMethodField()

    class Meta:
        model = Roles
        fields = [
            'id', 'nombre', 'activo', 'fecha_creacion',
            'permisos', 'permisos_ids', 'cantidad_usuarios',
            'cantidad_permisos', 'puede_eliminar'
        ]
        read_only_fields = ['fecha_creacion']

    def get_cantidad_usuarios(self, obj):
        return obj.cantidad_usuarios()

    def get_cantidad_permisos(self, obj):
        return obj.cantidad_permisos()

    def get_puede_eliminar(self, obj):
        return obj.puede_eliminar()

    def validate_nombre(self, value):
        """Validar que el nombre del rol sea único y válido"""
        if not value or not value.strip():
            raise serializers.ValidationError("El nombre del rol es obligatorio")

        value = value.strip()

        # Verificar unicidad
        queryset = Roles.objects.filter(nombre__iexact=value)

        # Si estamos editando, excluir el registro actual
        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)

        if queryset.exists():
            raise serializers.ValidationError(f"Ya existe un rol con el nombre '{value}'")

        return value

    def validate_permisos_ids(self, value):
        """Validar que todos los IDs de permisos existan"""
        if not value:
            return value

        permisos_existentes = Permission.objects.filter(id__in=value)
        ids_encontrados = set(permisos_existentes.values_list('id', flat=True))
        ids_solicitados = set(value)

        ids_no_encontrados = ids_solicitados - ids_encontrados
        if ids_no_encontrados:
            raise serializers.ValidationError(
                f"Los siguientes IDs de permisos no existen: {list(ids_no_encontrados)}"
            )

        return value

    def create(self, validated_data):
        permisos_ids = validated_data.pop('permisos_ids', [])

        with transaction.atomic():
            rol = Roles.objects.create(**validated_data)

            if permisos_ids:
                permisos = Permission.objects.filter(id__in=permisos_ids)
                rol.permisos.set(permisos)

            return rol

    def update(self, instance, validated_data):
        permisos_ids = validated_data.pop('permisos_ids', None)

        with transaction.atomic():
            # Actualizar campos del rol
            for attr, value in validated_data.items():
                setattr(instance, attr, value)
            instance.save()

            # Actualizar permisos si se proporcionaron
            if permisos_ids is not None:
                permisos = Permission.objects.filter(id__in=permisos_ids)
                instance.permisos.set(permisos)

            return instance


class UsuarioListSerializer(serializers.ModelSerializer):
    """Serializer para listado de usuarios (datos básicos)"""
    rol_nombre = serializers.CharField(source='rol.nombre', read_only=True)
    nombre_completo = serializers.SerializerMethodField()
    tipo_usuario = serializers.SerializerMethodField()

    class Meta:
        model = Usuario
        fields = [
            'id', 'codigocotel', 'nombre_completo', 'nombres',
            'apellidopaterno', 'apellidomaterno', 'estadoempleado',
            'fechaingreso', 'fecha_creacion', 'is_active',
            'password_changed', 'rol_nombre', 'tipo_usuario'
        ]

    def get_nombre_completo(self, obj):
        return obj.nombre_completo()

    def get_tipo_usuario(self, obj):
        return 'manual' if obj.es_usuario_manual() else 'migrado'


class UsuarioManualSerializer(serializers.ModelSerializer):
    """Serializer para crear/editar usuarios manuales"""
    codigocotel = serializers.IntegerField(read_only=True)  # Auto-generado
    rol_nombre = serializers.CharField(source='rol.nombre', read_only=True)

    class Meta:
        model = Usuario
        fields = [
            'id', 'codigocotel', 'nombres', 'apellidopaterno',
            'apellidomaterno', 'rol', 'rol_nombre', 'is_active',
            'password_changed', 'fecha_creacion', 'creado_por'
        ]
        read_only_fields = [
            'codigocotel', 'fecha_creacion', 'creado_por', 'password_changed'
        ]

    def validate_nombres(self, value):
        """Validar nombres obligatorios"""
        if not value or not value.strip():
            raise serializers.ValidationError("Los nombres son obligatorios")
        return value.strip()

    def validate_apellidopaterno(self, value):
        """Validar apellido paterno obligatorio"""
        if not value or not value.strip():
            raise serializers.ValidationError("El apellido paterno es obligatorio")
        return value.strip()

    def validate_apellidomaterno(self, value):
        """Validar apellido materno obligatorio"""
        if not value or not value.strip():
            raise serializers.ValidationError("El apellido materno es obligatorio")
        return value.strip()

    def validate_rol(self, value):
        """Validar que el rol exista y esté activo"""
        if not value:
            raise serializers.ValidationError("El rol es obligatorio")

        if not value.activo:
            raise serializers.ValidationError("El rol seleccionado no está activo")

        return value

    def create(self, validated_data):
        """Crear usuario manual con código COTEL auto-generado"""
        with transaction.atomic():
            # Generar código COTEL único
            codigocotel = Usuario.objects.generar_codigo_cotel_disponible()

            # Obtener usuario que está creando (del contexto)
            request = self.context.get('request')
            creado_por = request.user if request and request.user.is_authenticated else None

            # Crear usuario manual
            usuario = Usuario.objects.create(
                codigocotel=codigocotel,
                persona=None,  # Usuarios manuales no tienen persona
                apellidopaterno=validated_data['apellidopaterno'],
                apellidomaterno=validated_data['apellidomaterno'],
                nombres=validated_data['nombres'],
                estadoempleado=0,  # Activo por defecto
                fechaingreso=timezone.now().date(),
                rol=validated_data['rol'],
                password_changed=False,  # Forzar cambio de contraseña
                creado_por=creado_por
            )

            # Establecer contraseña inicial = código COTEL
            usuario.set_password(str(codigocotel))
            usuario.save()

            return usuario

    def update(self, instance, validated_data):
        # Actualizar campos permitidos
        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        instance.save()
        return instance


class EmpleadoDisponibleSerializer(serializers.ModelSerializer):
    """Serializer para empleados FDW disponibles para migración"""
    nombre_completo = serializers.SerializerMethodField()
    puede_migrar = serializers.SerializerMethodField()
    estado_texto = serializers.SerializerMethodField()

    class Meta:
        model = Empleado_fdw
        fields = [
            'persona', 'codigocotel', 'nombres', 'apellidopaterno',
            'apellidomaterno', 'nombre_completo', 'estadoempleado',
            'estado_texto', 'fechaingreso', 'puede_migrar'
        ]

    def get_nombre_completo(self, obj):
        return obj.nombre_completo()

    def get_puede_migrar(self, obj):
        return obj.puede_migrar()

    def get_estado_texto(self, obj):
        return 'Activo' if obj.esta_activo() else 'Inactivo'


class MigrarEmpleadoSerializer(serializers.Serializer):
    """Serializer para migrar empleado desde lista FDW"""
    empleado_persona = serializers.IntegerField()
    rol_id = serializers.IntegerField()

    def validate_empleado_persona(self, value):
        """Validar que el empleado exista y pueda ser migrado"""
        try:
            empleado = Empleado_fdw.objects.get(persona=value)
        except Empleado_fdw.DoesNotExist:
            raise serializers.ValidationError("El empleado no existe")

        if not empleado.puede_migrar():
            if empleado.esta_migrado():
                raise serializers.ValidationError("El empleado ya está migrado")
            else:
                raise serializers.ValidationError("El empleado no está activo")

        return value

    def validate_rol_id(self, value):
        """Validar que el rol exista y esté activo"""
        try:
            rol = Roles.objects.get(id=value)
        except Roles.DoesNotExist:
            raise serializers.ValidationError("El rol no existe")

        if not rol.activo:
            raise serializers.ValidationError("El rol no está activo")

        return value

    def create(self, validated_data):
        """Migrar empleado FDW a tabla Usuario"""
        empleado_persona = validated_data['empleado_persona']
        rol_id = validated_data['rol_id']

        with transaction.atomic():
            # Obtener empleado FDW
            empleado = Empleado_fdw.objects.get(persona=empleado_persona)
            rol = Roles.objects.get(id=rol_id)

            # Verificar nuevamente que puede migrar (por concurrencia)
            if not empleado.puede_migrar():
                raise serializers.ValidationError("El empleado ya no puede ser migrado")

            # Obtener usuario que está migrando
            request = self.context.get('request')
            creado_por = request.user if request and request.user.is_authenticated else None

            # Crear usuario migrado
            usuario = Usuario.objects.create(
                codigocotel=empleado.codigocotel,
                persona=empleado.persona,
                apellidopaterno=empleado.apellidopaterno,
                apellidomaterno=empleado.apellidomaterno,
                nombres=empleado.nombres,
                estadoempleado=empleado.estadoempleado,
                fechaingreso=empleado.fechaingreso,
                rol=rol,
                password_changed=False,  # Forzar cambio de contraseña
                creado_por=creado_por
            )

            # Establecer contraseña inicial = código COTEL
            usuario.set_password(str(empleado.codigocotel))
            usuario.save()

            return usuario


# Mantener serializers existentes
class UsuarioSerializer(serializers.ModelSerializer):
    class Meta:
        model = Usuario
        fields = [
            'codigocotel',
            'persona',
            'apellidopaterno',
            'apellidomaterno',
            'nombres',
            'estadoempleado',
            'fechaingreso',
            'password'
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
            'persona',
            'apellidopaterno',
            'apellidomaterno',
            'nombres',
            'estadoempleado',
            'codigocotel',
            'fechaingreso'
        ]


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(required=True)
    new_password = serializers.CharField(required=True, min_length=8)
