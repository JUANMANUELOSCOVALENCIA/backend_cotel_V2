# ======================================================
# apps/contratos/serializers.py
# ======================================================

from rest_framework import serializers
from django.core.validators import RegexValidator
from .models import (
    Cliente, TipoTramite, FormaPago, TipoServicio, PlanComercial,
    Contrato, Servicio, OrdenTrabajo
)


class TipoServicioSerializer(serializers.ModelSerializer):
    lotes_count = serializers.SerializerMethodField()
    planes_count = serializers.SerializerMethodField()

    class Meta:
        model = TipoServicio
        fields = ['id', 'nombre', 'descripcion', 'lotes_count', 'planes_count', 'created_at', 'updated_at']
        read_only_fields = ['created_at', 'updated_at']

    def get_lotes_count(self, obj):
        # Importar aquí para evitar circular imports
        try:
            from apps.almacenes.models import Lote
            return Lote.objects.filter(tipo_servicio=obj).count()
        except ImportError:
            return 0

    def get_planes_count(self, obj):
        return obj.plancomercial_set.count()


class TipoTramiteSerializer(serializers.ModelSerializer):
    contratos_count = serializers.SerializerMethodField()

    class Meta:
        model = TipoTramite
        fields = ['id', 'nombre', 'descripcion', 'activo', 'contratos_count', 'created_at', 'updated_at']
        read_only_fields = ['created_at', 'updated_at']

    def get_contratos_count(self, obj):
        return obj.contrato_set.count()


class FormaPagoSerializer(serializers.ModelSerializer):
    contratos_count = serializers.SerializerMethodField()

    class Meta:
        model = FormaPago
        fields = ['id', 'nombre', 'descripcion', 'activo', 'contratos_count', 'created_at', 'updated_at']
        read_only_fields = ['created_at', 'updated_at']

    def get_contratos_count(self, obj):
        return obj.contrato_set.count()


class ClienteSerializer(serializers.ModelSerializer):
    nombre_completo = serializers.SerializerMethodField()
    contratos_count = serializers.SerializerMethodField()
    contratos_activos = serializers.SerializerMethodField()

    class Meta:
        model = Cliente
        fields = [
            'id', 'ci', 'nombres', 'apellidos', 'nombre_completo',
            'direccion', 'telefono', 'telefono_alternativo', 'email',
            'zona', 'ciudad', 'estado', 'fecha_registro', 'observaciones',
            'contratos_count', 'contratos_activos', 'created_at', 'updated_at'
        ]
        read_only_fields = ['fecha_registro', 'created_at', 'updated_at']

    def get_nombre_completo(self, obj):
        return f"{obj.nombres} {obj.apellidos}"

    def get_contratos_count(self, obj):
        return obj.contratos.count()

    def get_contratos_activos(self, obj):
        return obj.contratos.filter(estado_contrato='ACTIVO').count()

    def validate_ci(self, value):
        """Validación para CI boliviano"""
        if not value.isdigit() or len(value) < 7 or len(value) > 8:
            raise serializers.ValidationError(
                "CI debe tener entre 7 y 8 dígitos numéricos"
            )
        return value

    def validate_telefono(self, value):
        """Validación para teléfonos bolivianos"""
        if value and not value.isdigit():
            raise serializers.ValidationError(
                "El teléfono debe contener solo números"
            )
        if value and (len(value) < 7 or len(value) > 8):
            raise serializers.ValidationError(
                "El teléfono debe tener entre 7 y 8 dígitos"
            )
        return value


class PlanComercialSerializer(serializers.ModelSerializer):
    tipo_servicio_nombre = serializers.CharField(source='tipo_servicio.nombre', read_only=True)
    servicios_count = serializers.SerializerMethodField()
    velocidad_completa = serializers.SerializerMethodField()

    class Meta:
        model = PlanComercial
        fields = [
            'id', 'tipo_servicio', 'tipo_servicio_nombre', 'nombre', 'codigo_plan',
            'velocidad_descarga', 'velocidad_subida', 'velocidad_completa',
            'precio_mensual', 'precio_instalacion', 'descripcion', 'activo',
            'servicios_count', 'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']

    def get_servicios_count(self, obj):
        return obj.servicio_set.count()

    def get_velocidad_completa(self, obj):
        if obj.velocidad_descarga and obj.velocidad_subida:
            return f"{obj.velocidad_descarga}MB/{obj.velocidad_subida}MB"
        elif obj.velocidad_descarga:
            return f"{obj.velocidad_descarga}MB"
        return None


class ServicioSerializer(serializers.ModelSerializer):
    plan_nombre = serializers.CharField(source='plan_comercial.nombre', read_only=True)
    tipo_servicio = serializers.CharField(source='plan_comercial.tipo_servicio.nombre', read_only=True)
    contrato_numero = serializers.CharField(source='contrato.numero_contrato', read_only=True)

    class Meta:
        model = Servicio
        fields = [
            'id', 'contrato', 'contrato_numero', 'plan_comercial', 'plan_nombre',
            'tipo_servicio', 'fecha_activacion', 'fecha_desactivacion',
            'estado_servicio', 'observaciones', 'created_at', 'updated_at'
        ]
        read_only_fields = ['fecha_activacion', 'created_at', 'updated_at']


class ContratoSerializer(serializers.ModelSerializer):
    cliente_nombre = serializers.CharField(source='cliente.nombres', read_only=True)
    cliente_apellidos = serializers.CharField(source='cliente.apellidos', read_only=True)
    cliente_completo = serializers.SerializerMethodField()
    tipo_tramite_nombre = serializers.CharField(source='tipo_tramite.nombre', read_only=True)
    forma_pago_nombre = serializers.CharField(source='forma_pago.nombre', read_only=True)
    servicios = ServicioSerializer(many=True, read_only=True)
    servicios_count = serializers.SerializerMethodField()
    ordenes_trabajo_count = serializers.SerializerMethodField()

    class Meta:
        model = Contrato
        fields = [
            'id', 'numero_contrato', 'cliente', 'cliente_nombre', 'cliente_apellidos',
            'cliente_completo', 'fecha_firma', 'tipo_tramite', 'tipo_tramite_nombre',
            'forma_pago', 'forma_pago_nombre', 'estado_contrato', 'direccion_instalacion',
            'observaciones', 'servicios', 'servicios_count', 'ordenes_trabajo_count',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['numero_contrato', 'fecha_firma', 'created_at', 'updated_at']

    def get_cliente_completo(self, obj):
        return f"{obj.cliente.nombres} {obj.cliente.apellidos}"

    def get_servicios_count(self, obj):
        return obj.servicios.count()

    def get_ordenes_trabajo_count(self, obj):
        return obj.ordenes_trabajo.count()


class ContratoCreateSerializer(serializers.ModelSerializer):
    """Serializer para crear contratos con servicios"""
    servicios = serializers.ListField(
        child=serializers.IntegerField(),
        write_only=True,
        help_text="Lista de IDs de planes comerciales"
    )

    class Meta:
        model = Contrato
        fields = [
            'cliente', 'tipo_tramite', 'forma_pago', 'direccion_instalacion',
            'observaciones', 'servicios'
        ]

    def create(self, validated_data):
        servicios_ids = validated_data.pop('servicios')
        contrato = Contrato.objects.create(**validated_data)

        # Crear servicios asociados
        for plan_id in servicios_ids:
            try:
                plan = PlanComercial.objects.get(id=plan_id, activo=True)
                Servicio.objects.create(
                    contrato=contrato,
                    plan_comercial=plan
                )
            except PlanComercial.DoesNotExist:
                pass  # Ignorar planes que no existen o no están activos

        return contrato


class OrdenTrabajoSerializer(serializers.ModelSerializer):
    contrato_numero = serializers.CharField(source='contrato.numero_contrato', read_only=True)
    cliente_nombre = serializers.SerializerMethodField()
    servicios_contrato = serializers.SerializerMethodField()

    class Meta:
        model = OrdenTrabajo
        fields = [
            'id', 'numero_ot', 'contrato', 'contrato_numero', 'cliente_nombre',
            'tecnico_asignado', 'fecha_asignacion', 'fecha_programada', 'fecha_ejecucion',
            'estado_ot', 'tipo_trabajo', 'observaciones_tecnico', 'materiales_utilizados',
            'servicios_contrato', 'created_at', 'updated_at'
        ]
        read_only_fields = ['numero_ot', 'created_at', 'updated_at']

    def get_cliente_nombre(self, obj):
        try:
            return f"{obj.contrato.cliente.nombres} {obj.contrato.cliente.apellidos}"
        except AttributeError:
            return "Cliente no disponible"

    def get_servicios_contrato(self, obj):
        try:
            servicios = obj.contrato.servicios.filter(estado_servicio='ACTIVO')
            servicios_info = []
            for s in servicios:
                try:
                    info = f"{s.plan_comercial.tipo_servicio.nombre}: {s.plan_comercial.nombre}"
                    servicios_info.append(info)
                except AttributeError:
                    # Si un servicio no tiene plan_comercial, omitirlo
                    continue
            return servicios_info
        except AttributeError:
            return []