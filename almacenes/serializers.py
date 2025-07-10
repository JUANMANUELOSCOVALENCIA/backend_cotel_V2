# ======================================================
# apps/almacenes/serializers.py
# ======================================================
from django.db import transaction
from rest_framework import serializers
from .models import (
    Marca, TipoEquipo, Componente, EstadoEquipo, Modelo,
    ModeloComponente, Lote, LoteDetalle, EquipoONU, EquipoServicio
)


class MarcaSerializer(serializers.ModelSerializer):
    modelos_count = serializers.SerializerMethodField()
    equipos_count = serializers.SerializerMethodField()

    class Meta:
        model = Marca
        fields = ['id', 'nombre', 'descripcion', 'modelos_count', 'equipos_count', 'created_at', 'updated_at']
        read_only_fields = ['created_at', 'updated_at']

    def get_modelos_count(self, obj):
        return obj.modelo_set.count()

    def get_equipos_count(self, obj):
        return sum(modelo.equipoonu_set.count() for modelo in obj.modelo_set.all())


class TipoEquipoSerializer(serializers.ModelSerializer):
    modelos_count = serializers.SerializerMethodField()
    equipos_count = serializers.SerializerMethodField()

    class Meta:
        model = TipoEquipo
        fields = ['id', 'nombre', 'descripcion', 'modelos_count', 'equipos_count', 'created_at', 'updated_at']
        read_only_fields = ['created_at', 'updated_at']

    def get_modelos_count(self, obj):
        return obj.modelo_set.count()

    def get_equipos_count(self, obj):
        return obj.equipoonu_set.count()


class ComponenteSerializer(serializers.ModelSerializer):
    modelos_usando = serializers.SerializerMethodField()

    class Meta:
        model = Componente
        fields = ['id', 'nombre', 'descripcion', 'modelos_usando', 'created_at', 'updated_at']
        read_only_fields = ['created_at', 'updated_at']

    def get_modelos_usando(self, obj):
        return obj.modelocomponente_set.count()


class EstadoEquipoSerializer(serializers.ModelSerializer):
    equipos_count = serializers.SerializerMethodField()

    class Meta:
        model = EstadoEquipo
        fields = ['id', 'nombre', 'descripcion', 'equipos_count', 'created_at', 'updated_at']
        read_only_fields = ['created_at', 'updated_at']

    def get_equipos_count(self, obj):
        return obj.equipoonu_set.count()


class ModeloComponenteSerializer(serializers.ModelSerializer):
    componente_nombre = serializers.CharField(source='componente.nombre', read_only=True)

    class Meta:
        model = ModeloComponente
        fields = ['id', 'componente', 'componente_nombre', 'cantidad']


class ModeloSerializer(serializers.ModelSerializer):
    marca_nombre = serializers.CharField(source='marca.nombre', read_only=True)
    tipo_equipo_nombre = serializers.CharField(source='tipo_equipo.nombre', read_only=True)
    componentes = ModeloComponenteSerializer(source='modelocomponente_set', many=True, read_only=True)
    equipos_count = serializers.SerializerMethodField()
    equipos_disponibles = serializers.SerializerMethodField()

    componentes_data = serializers.ListField(
        child=serializers.DictField(),
        write_only=True,
        required=False
    )

    class Meta:
        model = Modelo
        fields = [
            'id', 'marca', 'marca_nombre', 'tipo_equipo', 'tipo_equipo_nombre',
            'nombre', 'codigo_modelo', 'descripcion', 'componentes',
            'equipos_count', 'equipos_disponibles', 'created_at', 'updated_at', 'componentes_data'
        ]
        read_only_fields = ['created_at', 'updated_at']

    def create(self, validated_data):
        componentes_data = validated_data.pop('componentes_data', [])

        with transaction.atomic():
            modelo = Modelo.objects.create(**validated_data)
            self._crear_componentes(modelo, componentes_data)

        return modelo

    def update(self, instance, validated_data):
        componentes_data = validated_data.pop('componentes_data', None)

        with transaction.atomic():
            # Actualizar campos básicos del modelo
            for attr, value in validated_data.items():
                setattr(instance, attr, value)
            instance.save()

            # Si se proporcionaron componentes, reemplazarlos
            if componentes_data is not None:
                instance.modelocomponente_set.all().delete()
                self._crear_componentes(instance, componentes_data)

        return instance

    def _crear_componentes(self, modelo, componentes_data):
        for comp_data in componentes_data:
            ModeloComponente.objects.create(
                modelo=modelo,
                componente_id=comp_data['componente_id'],
                cantidad=comp_data.get('cantidad', 1)
            )

    def get_equipos_count(self, obj):
        return obj.equipoonu_set.count()

    def get_equipos_disponibles(self, obj):
        # Asumiendo que estado con nombre 'DISPONIBLE' indica disponibilidad
        return obj.equipoonu_set.filter(
            estado__nombre__icontains='DISPONIBLE'
        ).count()


class LoteDetalleSerializer(serializers.ModelSerializer):
    modelo_nombre = serializers.CharField(source='modelo.nombre', read_only=True)
    marca_nombre = serializers.CharField(source='modelo.marca.nombre', read_only=True)
    codigo_modelo = serializers.IntegerField(source='modelo.codigo_modelo', read_only=True)

    class Meta:
        model = LoteDetalle
        fields = [
            'id', 'modelo', 'modelo_nombre', 'marca_nombre', 'codigo_modelo',
            'cantidad', 'created_at'
        ]
        read_only_fields = ['created_at']


class LoteSerializer(serializers.ModelSerializer):
    tipo_servicio_nombre = serializers.CharField(source='tipo_servicio.nombre', read_only=True)
    detalles = LoteDetalleSerializer(many=True, read_only=True)
    cantidad_total = serializers.ReadOnlyField()
    equipos_registrados = serializers.SerializerMethodField()
    equipos_pendientes = serializers.SerializerMethodField()

    class Meta:
        model = Lote
        fields = [
            'id', 'numero_lote', 'proveedor', 'tipo_servicio', 'tipo_servicio_nombre',
            'fecha_ingreso', 'observaciones', 'detalles', 'cantidad_total',
            'equipos_registrados', 'equipos_pendientes', 'created_at', 'updated_at'
        ]
        read_only_fields = ['fecha_ingreso', 'created_at', 'updated_at']

    def get_equipos_registrados(self, obj):
        return obj.equipoonu_set.count()

    def get_equipos_pendientes(self, obj):
        registrados = obj.equipoonu_set.count()
        total = obj.cantidad_total
        return max(0, total - registrados)


class LoteCreateSerializer(serializers.ModelSerializer):
    """Serializer para crear Y actualizar lotes con sus detalles"""
    detalles = LoteDetalleSerializer(many=True, write_only=True)

    class Meta:
        model = Lote
        fields = ['numero_lote', 'proveedor', 'tipo_servicio', 'observaciones', 'detalles']

    def create(self, validated_data):
        """Crear lote con detalles"""
        detalles_data = validated_data.pop('detalles')
        lote = Lote.objects.create(**validated_data)

        for detalle_data in detalles_data:
            LoteDetalle.objects.create(lote=lote, **detalle_data)

        return lote

    def update(self, instance, validated_data):
        """Actualizar lote con detalles - NUEVO"""
        detalles_data = validated_data.pop('detalles', [])

        # Actualizar campos básicos del lote
        instance.numero_lote = validated_data.get('numero_lote', instance.numero_lote)
        instance.proveedor = validated_data.get('proveedor', instance.proveedor)
        instance.tipo_servicio = validated_data.get('tipo_servicio', instance.tipo_servicio)
        instance.observaciones = validated_data.get('observaciones', instance.observaciones)
        instance.save()

        # Actualizar detalles si se proporcionaron
        if detalles_data:
            # Eliminar detalles existentes para reemplazarlos
            instance.detalles.all().delete()

            # Crear nuevos detalles
            for detalle_data in detalles_data:
                LoteDetalle.objects.create(
                    lote=instance,
                    modelo=detalle_data['modelo'],
                    cantidad=detalle_data['cantidad']
                )

        return instance

    def to_representation(self, instance):
        """Devolver representación completa usando LoteSerializer"""
        # Usar LoteSerializer para la respuesta con todos los campos calculados
        return LoteSerializer(instance).data
class EquipoONUSerializer(serializers.ModelSerializer):
    modelo_nombre = serializers.CharField(source='modelo.nombre', read_only=True)
    marca_nombre = serializers.CharField(source='modelo.marca.nombre', read_only=True)
    tipo_equipo_nombre = serializers.CharField(source='tipo_equipo.nombre', read_only=True)
    estado_nombre = serializers.CharField(source='estado.nombre', read_only=True)
    lote_numero = serializers.CharField(source='lote.numero_lote', read_only=True)
    esta_asignado = serializers.SerializerMethodField()

    class Meta:
        model = EquipoONU
        fields = [
            'id', 'codigo_interno', 'modelo', 'modelo_nombre', 'marca_nombre',
            'tipo_equipo', 'tipo_equipo_nombre', 'lote', 'lote_numero',
            'mac_address', 'gpon_serial', 'serial_manufacturer',
            'fecha_ingreso', 'estado', 'estado_nombre', 'esta_asignado',
            'observaciones', 'created_at', 'updated_at'
        ]
        read_only_fields = ['fecha_ingreso', 'created_at', 'updated_at']

    def get_esta_asignado(self, obj):
        return obj.equiposervicio_set.filter(estado_asignacion='ACTIVO').exists()

    def validate_mac_address(self, value):
        """Validación personalizada para MAC address"""
        if value:
            # Normalizar formato (convertir a mayúsculas con :)
            import re
            value = value.upper().replace('-', ':')
            if not re.match(r'^([0-9A-F]{2}[:-]){5}([0-9A-F]{2})$', value):
                raise serializers.ValidationError(
                    "Formato de MAC inválido. Use XX:XX:XX:XX:XX:XX"
                )
        return value

    def validate_codigo_interno(self, value):
        """Generar código interno si no se proporciona"""
        if not value:
            import uuid
            while True:
                codigo = f"EQ-{str(uuid.uuid4().int)[:6]}"
                if not EquipoONU.objects.filter(codigo_interno=codigo).exists():
                    return codigo
        return value


class EquipoONUListSerializer(serializers.ModelSerializer):
    """Serializer para listados con todos los campos necesarios"""
    modelo_nombre = serializers.CharField(source='modelo.nombre', read_only=True)
    marca_nombre = serializers.CharField(source='modelo.marca.nombre', read_only=True)
    tipo_equipo_nombre = serializers.CharField(source='tipo_equipo.nombre', read_only=True)
    estado_nombre = serializers.CharField(source='estado.nombre', read_only=True)
    lote_numero = serializers.CharField(source='lote.numero_lote', read_only=True)
    esta_asignado = serializers.SerializerMethodField()

    class Meta:
        model = EquipoONU
        fields = [
            'id', 'codigo_interno', 'modelo', 'modelo_nombre', 'marca_nombre',
            'tipo_equipo', 'tipo_equipo_nombre', 'lote', 'lote_numero',
            'mac_address', 'gpon_serial', 'serial_manufacturer',
            'fecha_ingreso', 'estado', 'estado_nombre', 'esta_asignado',
            'observaciones'
        ]

    def get_esta_asignado(self, obj):
        return obj.equiposervicio_set.filter(estado_asignacion='ACTIVO').exists()

    def get_modelo_completo(self, obj):
        return f"{obj.modelo.marca.nombre} {obj.modelo.nombre}"

    def get_estado_info(self, obj):
        if obj.estado:
            return {
                'id': obj.estado.id,
                'nombre': obj.estado.nombre
            }
        return None


class EquipoServicioSerializer(serializers.ModelSerializer):
    equipo_codigo = serializers.CharField(source='equipo_onu.codigo_interno', read_only=True)
    contrato_numero = serializers.CharField(source='contrato.numero_contrato', read_only=True)

    class Meta:
        model = EquipoServicio
        fields = [
            'id', 'equipo_onu', 'equipo_codigo', 'contrato', 'contrato_numero',
            'servicio', 'fecha_asignacion', 'fecha_desasignacion',
            'estado_asignacion', 'observaciones', 'created_at', 'updated_at'
        ]
        read_only_fields = ['fecha_asignacion', 'created_at', 'updated_at']
