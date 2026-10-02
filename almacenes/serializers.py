# ======================================================
# apps/almacenes/serializers.py - COMPLETO SIN TEXTCHOICES
# Serializers completos para React con objetos completos
# ======================================================

from django.db import transaction
from rest_framework import serializers
from decimal import Decimal
import pandas as pd
import re
from io import BytesIO
from django.utils import timezone

from usuarios.models import Usuario
from .models import (
    # Modelos base
    Almacen, Proveedor,

    # Modelos de choices (antes TextChoices)
    TipoIngreso, EstadoLote, EstadoTraspaso, TipoMaterial, UnidadMedida,
    EstadoMaterialONU, EstadoMaterialGeneral, TipoAlmacen,

    # Modelos existentes actualizados
    Marca, Componente, Modelo, ModeloComponente,

    # Modelos de lotes
    Lote, LoteDetalle, EntregaParcialLote,

    # Modelo unificado
    Material,

    # Modelos de operaciones
    TraspasoAlmacen, TraspasoMaterial,
    HistorialMaterial, InspeccionLaboratorio, SectorSolicitante,
)


# ========== SERIALIZERS PARA MODELOS DE CHOICES ==========


def nombre_sector(lote):
    """Nombre del sector solicitante del lote (ahora es opcional)."""
    return lote.sector_solicitante.nombre if lote and lote.sector_solicitante_id else 'sin sector'

class TipoIngresoSerializer(serializers.ModelSerializer):
    class Meta:
        model = TipoIngreso
        fields = ['id', 'codigo', 'nombre', 'descripcion', 'activo', 'orden']


class EstadoLoteSerializer(serializers.ModelSerializer):
    class Meta:
        model = EstadoLote
        fields = ['id', 'codigo', 'nombre', 'descripcion', 'color', 'es_final', 'activo', 'orden']


class EstadoTraspasoSerializer(serializers.ModelSerializer):
    class Meta:
        model = EstadoTraspaso
        fields = ['id', 'codigo', 'nombre', 'descripcion', 'color', 'es_final', 'activo', 'orden']


class TipoMaterialSerializer(serializers.ModelSerializer):
    unidad_medida_default_info = serializers.SerializerMethodField()
    materiales_count = serializers.ReadOnlyField()
    modelos_count = serializers.ReadOnlyField()
    created_by_nombre = serializers.CharField(source='created_by.nombre_completo', read_only=True)

    class Meta:
        model = TipoMaterial
        fields = [
            'id', 'codigo', 'nombre', 'descripcion', 'unidad_medida_default',
            'unidad_medida_default_info', 'requiere_inspeccion_inicial', 'es_unico',
            'activo', 'orden', 'materiales_count', 'modelos_count',
            'created_at', 'updated_at', 'created_by', 'created_by_nombre'
        ]
        read_only_fields = ['created_at', 'updated_at']

    def get_unidad_medida_default_info(self, obj):
        if obj.unidad_medida_default:
            return {
                'id': obj.unidad_medida_default.id,
                'codigo': obj.unidad_medida_default.codigo,
                'nombre': obj.unidad_medida_default.nombre,
                'simbolo': obj.unidad_medida_default.simbolo
            }
        return None


class UnidadMedidaSerializer(serializers.ModelSerializer):
    class Meta:
        model = UnidadMedida
        fields = ['id', 'codigo', 'nombre', 'simbolo', 'descripcion', 'activo', 'orden']


class EstadoMaterialONUSerializer(serializers.ModelSerializer):
    class Meta:
        model = EstadoMaterialONU
        fields = [
            'id', 'codigo', 'nombre', 'descripcion', 'color',
            'permite_asignacion', 'permite_traspaso', 'activo', 'orden'
        ]


class EstadoMaterialGeneralSerializer(serializers.ModelSerializer):
    class Meta:
        model = EstadoMaterialGeneral
        fields = [
            'id', 'codigo', 'nombre', 'descripcion', 'color',
            'permite_consumo', 'permite_traspaso', 'activo', 'orden'
        ]


class TipoAlmacenSerializer(serializers.ModelSerializer):
    class Meta:
        model = TipoAlmacen
        fields = ['id', 'codigo', 'nombre', 'descripcion', 'activo', 'orden']

# ========== SERIALIZERS BASE ACTUALIZADOS ==========

class AlmacenSerializer(serializers.ModelSerializer):
    # Información completa de relaciones ForeignKey
    tipo_info = serializers.SerializerMethodField()
    encargado_info = serializers.ReadOnlyField()

    # Propiedades calculadas (precalculadas por optimizar_almacenes() cuando es posible)
    total_materiales = serializers.SerializerMethodField()
    materiales_disponibles = serializers.SerializerMethodField()

    # Información de auditoría
    created_by_nombre = serializers.CharField(source='created_by.nombre_completo', read_only=True)

    class Meta:
        model = Almacen
        fields = [
            'id', 'codigo', 'nombre', 'ciudad', 'tipo', 'tipo_info',
            'direccion', 'es_principal', 'encargado', 'encargado_info',
            'codigo_cotel_encargado', 'activo', 'observaciones',
            'total_materiales', 'materiales_disponibles',
            'created_at', 'updated_at', 'created_by', 'created_by_nombre'
        ]
        read_only_fields = ['created_at', 'updated_at', 'encargado_info']

    def get_tipo_info(self, obj):
        if obj.tipo:
            return {
                'id': obj.tipo.id,
                'codigo': obj.tipo.codigo,
                'nombre': obj.tipo.nombre
            }
        return None

    def get_total_materiales(self, obj):
        v = getattr(obj, '_total_materiales', None)
        return obj.total_materiales if v is None else v

    def get_materiales_disponibles(self, obj):
        v = getattr(obj, '_materiales_disponibles', None)
        return obj.materiales_disponibles if v is None else v

    def validate_codigo(self, value):
        if not value or len(value.strip()) < 2:
            raise serializers.ValidationError("El código debe tener al menos 2 caracteres")
        return value.strip().upper()

    def validate_codigo_cotel_encargado(self, value):
        """Validar que el código COTEL del encargado exista"""
        if value:
            try:
                # USAR 'codigocotel' en lugar de 'codigo_cotel'
                Usuario.objects.get(codigocotel=value)
            except Usuario.DoesNotExist:
                raise serializers.ValidationError(
                    f"No existe un usuario con código COTEL: {value}"
                )
        return value

    def validate(self, data):
        # Validar que solo haya un almacén principal
        if data.get('es_principal'):
            queryset = Almacen.objects.filter(es_principal=True)
            if self.instance:
                queryset = queryset.exclude(pk=self.instance.pk)
            if queryset.exists():
                raise serializers.ValidationError("Solo puede existir un almacén principal")
        return data


class ProveedorSerializer(serializers.ModelSerializer):
    lotes_count = serializers.SerializerMethodField()
    created_by_nombre = serializers.CharField(source='created_by.nombre_completo', read_only=True)

    class Meta:
        model = Proveedor
        fields = [
            'id', 'codigo', 'nombre_comercial', 'razon_social',
            'contacto_principal', 'telefono', 'email', 'activo',
            'lotes_count', 'created_at', 'updated_at', 'created_by', 'created_by_nombre'
        ]
        read_only_fields = ['created_at', 'updated_at']

    def get_lotes_count(self, obj):
        v = getattr(obj, '_lotes_count', None)
        return obj.lote_set.count() if v is None else v


# ========== SERIALIZERS DE MODELOS EXISTENTES ACTUALIZADOS ==========

class MarcaSerializer(serializers.ModelSerializer):
    modelos_count = serializers.SerializerMethodField()
    materiales_count = serializers.SerializerMethodField()

    class Meta:
        model = Marca
        fields = ['id', 'nombre', 'descripcion', 'activo', 'modelos_count', 'materiales_count', 'created_at',
                  'updated_at']
        read_only_fields = ['created_at', 'updated_at']

    def get_modelos_count(self, obj):
        v = getattr(obj, '_modelos_count', None)
        return obj.modelo_set.filter(activo=True).count() if v is None else v

    def get_materiales_count(self, obj):
        v = getattr(obj, '_materiales_count', None)
        if v is not None:
            return v
        return sum(modelo.material_set.count() for modelo in obj.modelo_set.filter(activo=True))

class ComponenteSerializer(serializers.ModelSerializer):
    modelos_usando = serializers.SerializerMethodField()

    class Meta:
        model = Componente
        fields = ['id', 'nombre', 'descripcion', 'activo', 'modelos_usando', 'created_at', 'updated_at']
        read_only_fields = ['created_at', 'updated_at']

    def get_modelos_usando(self, obj):
        return obj.modelocomponente_set.filter(modelo__activo=True).count()

class ModeloComponenteSerializer(serializers.ModelSerializer):
    componente_info = serializers.SerializerMethodField()

    class Meta:
        model = ModeloComponente
        fields = ['id', 'componente', 'componente_info', 'cantidad']

    def get_componente_info(self, obj):
        return {
            'id': obj.componente.id,
            'nombre': obj.componente.nombre
        }

class ModeloSerializer(serializers.ModelSerializer):
    # Información completa de relaciones ForeignKey
    marca_info = serializers.SerializerMethodField()
    tipo_material_info = serializers.SerializerMethodField()
    unidad_medida_info = serializers.SerializerMethodField()

    # Componentes
    componentes = ModeloComponenteSerializer(source='modelocomponente_set', many=True, read_only=True)

    # Estadísticas
    materiales_count = serializers.SerializerMethodField()
    materiales_disponibles = serializers.SerializerMethodField()

    # Para escritura de componentes
    componentes_data = serializers.ListField(
        child=serializers.DictField(),
        write_only=True,
        required=False
    )

    class Meta:
        model = Modelo
        fields = [
            'id', 'marca', 'marca_info',
            'nombre', 'codigo_modelo', 'descripcion', 'activo',
            'tipo_material', 'tipo_material_info', 'unidad_medida', 'unidad_medida_info',
            'cantidad_por_unidad', 'requiere_inspeccion_inicial', 'pruebas_laboratorio',
            'componentes', 'materiales_count', 'materiales_disponibles',
            'created_at', 'updated_at', 'componentes_data'
        ]
        read_only_fields = ['created_at', 'updated_at']

    def get_marca_info(self, obj):
        return {
            'id': obj.marca.id,
            'nombre': obj.marca.nombre
        }

    def get_tipo_material_info(self, obj):
        return {
            'id': obj.tipo_material.id,
            'codigo': obj.tipo_material.codigo,
            'nombre': obj.tipo_material.nombre,
            'es_unico': obj.tipo_material.es_unico,
            'requiere_inspeccion_inicial': obj.tipo_material.requiere_inspeccion_inicial
        }

    def get_unidad_medida_info(self, obj):
        return {
            'id': obj.unidad_medida.id,
            'codigo': obj.unidad_medida.codigo,
            'nombre': obj.unidad_medida.nombre,
            'simbolo': obj.unidad_medida.simbolo
        }

    def get_materiales_count(self, obj):
        v = getattr(obj, '_materiales_count', None)
        return obj.material_set.count() if v is None else v

    def get_materiales_disponibles(self, obj):
        # Precalculado por optimizar_modelos()
        if hasattr(obj, '_disp_onu'):
            return obj._disp_onu if obj.tipo_material.es_unico else obj._disp_general
        if obj.tipo_material.es_unico:
            return obj.material_set.filter(
                estado_onu__permite_asignacion=True
            ).count()
        else:
            return obj.material_set.filter(
                estado_general__permite_consumo=True
            ).count()

    def create(self, validated_data):
        componentes_data = validated_data.pop('componentes_data', [])

        with transaction.atomic():
            modelo = Modelo.objects.create(**validated_data)
            self._crear_componentes(modelo, componentes_data)

        return modelo

    def update(self, instance, validated_data):
        componentes_data = validated_data.pop('componentes_data', None)

        with transaction.atomic():
            for attr, value in validated_data.items():
                setattr(instance, attr, value)
            instance.save()

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


# ========== SERIALIZERS DE LOTES ACTUALIZADOS ==========

class LoteDetalleSerializer(serializers.ModelSerializer):
    modelo_info = serializers.SerializerMethodField()
    cantidad_recibida = serializers.ReadOnlyField()
    cantidad_pendiente = serializers.ReadOnlyField()

    class Meta:
        model = LoteDetalle
        fields = [
            'id', 'modelo', 'modelo_info', 'cantidad',
            'cantidad_recibida', 'cantidad_pendiente', 'created_at'
        ]
        read_only_fields = ['created_at']

    def get_modelo_info(self, obj):
        return {
            'id': obj.modelo.id,
            'nombre': obj.modelo.nombre,
            'marca': obj.modelo.marca.nombre,
            'codigo_modelo': obj.modelo.codigo_modelo,
            'tipo_material': {
                'codigo': obj.modelo.tipo_material.codigo,
                'nombre': obj.modelo.tipo_material.nombre,
                'es_unico': obj.modelo.tipo_material.es_unico
            },
            'unidad_medida': {
                'codigo': obj.modelo.unidad_medida.codigo,
                'nombre': obj.modelo.unidad_medida.nombre,
                'simbolo': obj.modelo.unidad_medida.simbolo
            }
        }


class EntregaParcialLoteSerializer(serializers.ModelSerializer):
    estado_entrega_info = serializers.SerializerMethodField()
    created_by_nombre = serializers.CharField(source='created_by.nombre_completo', read_only=True)

    class Meta:
        model = EntregaParcialLote
        fields = [
            'id', 'lote', 'numero_entrega', 'fecha_entrega', 'cantidad_entregada',
            'estado_entrega', 'estado_entrega_info', 'observaciones',
            'created_at', 'created_by', 'created_by_nombre'
        ]
        read_only_fields = ['created_at']

    def get_estado_entrega_info(self, obj):
        return {
            'id': obj.estado_entrega.id,
            'codigo': obj.estado_entrega.codigo,
            'nombre': obj.estado_entrega.nombre,
            'color': obj.estado_entrega.color
        }


class LoteSerializer(serializers.ModelSerializer):
    # Información completa de relaciones ForeignKey
    proveedor_info = serializers.SerializerMethodField()
    almacen_destino_info = serializers.SerializerMethodField()
    tipo_servicio_info = serializers.SerializerMethodField()
    tipo_ingreso_info = serializers.SerializerMethodField()
    estado_info = serializers.SerializerMethodField()

    # Detalles y entregas
    detalles = LoteDetalleSerializer(many=True, read_only=True)
    entregas_parciales = EntregaParcialLoteSerializer(many=True, read_only=True)

    # Propiedades calculadas
    cantidad_total = serializers.ReadOnlyField()
    cantidad_recibida = serializers.ReadOnlyField()
    cantidad_pendiente = serializers.ReadOnlyField()
    porcentaje_recibido = serializers.ReadOnlyField()
    sector_solicitante_info = serializers.SerializerMethodField()

    # Auditoría
    created_by_nombre = serializers.CharField(source='created_by.nombre_completo', read_only=True)

    class Meta:
        model = Lote
        fields = [
            'id', 'numero_lote', 'tipo_ingreso', 'tipo_ingreso_info',
            'proveedor', 'proveedor_info',
            'almacen_destino', 'almacen_destino_info',
            'tipo_servicio', 'tipo_servicio_info',
            'codigo_requerimiento_compra', 'codigo_nota_ingreso',
            'fecha_recepcion', 'fecha_inicio_garantia', 'fecha_fin_garantia',
            'estado', 'estado_info',
            'numero_informe', 'detalles_informe', 'fecha_informe',
            'total_entregas_parciales', 'observaciones',
            'detalles', 'entregas_parciales',
            'cantidad_total', 'cantidad_recibida', 'cantidad_pendiente', 'porcentaje_recibido',
            'created_at', 'updated_at', 'created_by', 'created_by_nombre','sector_solicitante','sector_solicitante_info'
        ]
        read_only_fields = ['created_at', 'updated_at']

    def get_proveedor_info(self, obj):
        return {
            'id': obj.proveedor.id,
            'codigo': obj.proveedor.codigo,
            'nombre_comercial': obj.proveedor.nombre_comercial
        }

    def get_almacen_destino_info(self, obj):
        return {
            'id': obj.almacen_destino.id,
            'codigo': obj.almacen_destino.codigo,
            'nombre': obj.almacen_destino.nombre
        }

    def get_tipo_servicio_info(self, obj):
        if not obj.tipo_servicio_id:
            return None
        return {
            'id': obj.tipo_servicio.id,
            'nombre': obj.tipo_servicio.nombre
        }

    def get_tipo_ingreso_info(self, obj):
        return {
            'id': obj.tipo_ingreso.id,
            'codigo': obj.tipo_ingreso.codigo,
            'nombre': obj.tipo_ingreso.nombre
        }

    def get_estado_info(self, obj):
        return {
            'id': obj.estado.id,
            'codigo': obj.estado.codigo,
            'nombre': obj.estado.nombre,
            'color': obj.estado.color,
            'es_final': obj.estado.es_final
        }

    def get_sector_solicitante_info(self, obj):
        if obj.sector_solicitante:
            return {
                'id': obj.sector_solicitante.id,
                'nombre': obj.sector_solicitante.nombre
            }
        return None


class LoteCreateSerializer(serializers.ModelSerializer):
    """Serializer para crear lotes con detalles"""
    detalles = LoteDetalleSerializer(many=True, write_only=True)

    class Meta:
        model = Lote
        fields = [
            'tipo_ingreso', 'proveedor', 'almacen_destino', 'tipo_servicio',
            'sector_solicitante',
            'codigo_requerimiento_compra', 'codigo_nota_ingreso',
            'fecha_recepcion', 'fecha_inicio_garantia', 'fecha_fin_garantia',
            'observaciones', 'detalles'
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # ✅ SOLUCIÓN: Si es actualización, detalles no es requerido
        if self.instance is not None:  # UPDATE operation
            self.fields['detalles'].required = False
            self.fields['detalles'].allow_empty = True

    # ✅ AGREGAR: Validación personalizada para almacén por defecto
    def validate(self, data):
        # Validar detalles solo en creación
        if self.instance is None:  # CREATE
            if not data.get('detalles'):
                raise serializers.ValidationError({"detalles": "Los detalles son requeridos para crear un lote"})

        # ✅ NUEVO: Si no se proporciona almacén, usar el ID=1 por defecto
        if not data.get('almacen_destino'):
            try:
                from .models import Almacen
                almacen_principal = Almacen.objects.get(id=1)
                data['almacen_destino'] = almacen_principal
            except Almacen.DoesNotExist:
                raise serializers.ValidationError("Almacén principal (ID=1) no encontrado")

        # Códigos SPRINT: solo números, de 6 a 10 dígitos
        for campo, nombre in (('codigo_requerimiento_compra', 'requerimiento de compra'), ('codigo_nota_ingreso', 'nota de ingreso')):
            valor = (data.get(campo) or '').strip()
            if campo in data:
                if not re.fullmatch(r'\d{6,10}', valor):
                    raise serializers.ValidationError({campo: f'El código de {nombre} debe tener de 6 a 10 dígitos.'})
                data[campo] = valor

        # Cada modelo una sola vez y con cantidad positiva
        vistos = set()
        for d in data.get('detalles') or []:
            if d.get('cantidad') is None or d['cantidad'] < 1:
                raise serializers.ValidationError({'detalles': f'La cantidad de {d["modelo"].nombre} debe ser mayor a 0.'})
            if d['modelo'].id in vistos:
                raise serializers.ValidationError({'detalles': f'El modelo {d["modelo"].nombre} está repetido.'})
            vistos.add(d['modelo'].id)

        # Validar fechas de garantía
        if data.get('fecha_fin_garantia') and data.get('fecha_inicio_garantia'):
            if data['fecha_fin_garantia'] <= data['fecha_inicio_garantia']:
                raise serializers.ValidationError("La fecha de fin de garantía debe ser posterior al inicio")

        # Un lote es lo que entrega un proveedor: compra o reposición por garantía.
        # (Los equipos que vuelven de clientes no se registran como lote.)
        # El almacén destino es libre (por defecto el principal en el formulario).
        tipo_ingreso = data.get('tipo_ingreso')
        if tipo_ingreso and tipo_ingreso.codigo not in Lote.TIPOS_INGRESO_LOTE:
            raise serializers.ValidationError({'tipo_ingreso': 'Un lote solo puede ser de compra o de reposición por garantía.'})

        return data

    def create(self, validated_data):
        detalles_data = validated_data.pop('detalles')

        with transaction.atomic():
            # Asignar estado inicial al lote
            try:
                estado_registrado = EstadoLote.objects.get(codigo='REGISTRADO', activo=True)
                validated_data['estado'] = estado_registrado
            except EstadoLote.DoesNotExist:
                pass

            # ✅ NUEVO: Generar número de lote automáticamente
            # (El método save() del modelo se encargará de esto)

            lote = Lote.objects.create(**validated_data)

            for detalle_data in detalles_data:
                LoteDetalle.objects.create(lote=lote, **detalle_data)

        return lote

    def update(self, instance, validated_data):
        detalles_data = validated_data.pop('detalles', None)
        validated_data.pop('numero_lote', None)  # el número no se cambia

        with transaction.atomic():
            for attr, value in validated_data.items():
                setattr(instance, attr, value)
            instance.save()

            # Modelos y cantidades: se pueden agregar modelos y cambiar cantidades,
            # pero nunca por debajo de lo ya recibido; un modelo con material recibido no se quita.
            if detalles_data is not None:
                if instance.estado and instance.estado.codigo == 'CERRADO':
                    raise serializers.ValidationError({'detalles': 'El lote está cerrado: no se pueden cambiar sus modelos o cantidades.'})
                if not detalles_data:
                    raise serializers.ValidationError({'detalles': 'El lote debe tener al menos un modelo.'})
                actuales = {d.modelo_id: d for d in instance.detalles.select_related('modelo__tipo_material', 'modelo__marca')}
                pedidos = {}
                for d in detalles_data:
                    modelo = d['modelo']
                    if modelo.id in pedidos:
                        raise serializers.ValidationError({'detalles': f'El modelo {modelo.nombre} está repetido.'})
                    pedidos[modelo.id] = d
                errores = []
                for modelo_id, detalle in actuales.items():
                    recibido = detalle.cantidad_recibida
                    nombre = f'{detalle.modelo.marca.nombre} {detalle.modelo.nombre}'
                    if modelo_id not in pedidos:
                        if recibido > 0:
                            errores.append(f'No se puede quitar {nombre}: ya se recibieron {recibido}.')
                    elif pedidos[modelo_id]['cantidad'] < recibido:
                        errores.append(f'{nombre}: la cantidad no puede ser menor a lo ya recibido ({recibido}).')
                if errores:
                    raise serializers.ValidationError({'detalles': ' '.join(errores)})
                for modelo_id, detalle in actuales.items():
                    if modelo_id not in pedidos:
                        detalle.delete()
                    elif detalle.cantidad != pedidos[modelo_id]['cantidad']:
                        detalle.cantidad = pedidos[modelo_id]['cantidad']
                        detalle.save(update_fields=['cantidad'])
                for modelo_id, d in pedidos.items():
                    if modelo_id not in actuales:
                        LoteDetalle.objects.create(lote=instance, modelo=d['modelo'], cantidad=d['cantidad'])
                instance.actualizar_estado_recepcion()

        return instance

    def to_representation(self, instance):
        return LoteSerializer(instance).data
# ========== SERIALIZERS DEL MODELO MATERIAL UNIFICADO ==========

class MaterialSerializer(serializers.ModelSerializer):
    # Información completa de relaciones
    modelo_info = serializers.SerializerMethodField()
    tipo_equipo_info = serializers.SerializerMethodField()
    tipo_material_info = serializers.SerializerMethodField()
    lote_info = serializers.SerializerMethodField()
    almacen_info = serializers.SerializerMethodField()
    estado_onu_info = serializers.SerializerMethodField()
    estado_general_info = serializers.SerializerMethodField()
    tipo_origen_info = serializers.SerializerMethodField()

    # Estado unificado
    estado_display = serializers.ReadOnlyField()

    # Propiedades calculadas
    requiere_laboratorio = serializers.ReadOnlyField()
    puede_traspasar = serializers.ReadOnlyField()
    dias_en_laboratorio = serializers.ReadOnlyField()

    class Meta:
        model = Material
        fields = [
            'id', 'codigo_interno', 'tipo_material', 'tipo_material_info',
            'modelo', 'modelo_info', 'tipo_equipo', 'tipo_equipo_info',
            'lote', 'lote_info', 'almacen_actual', 'almacen_info',
            'mac_address', 'gpon_serial', 'serial_manufacturer',
            'especificaciones_tecnicas', 'codigo_item_equipo',
            'estado_onu', 'estado_onu_info', 'estado_general', 'estado_general_info',
            'estado_display', 'es_nuevo', 'tipo_origen', 'tipo_origen_info',
            'fecha_envio_laboratorio', 'fecha_retorno_laboratorio',
            'cantidad', 'traspaso_actual', 'orden_trabajo',
            'requiere_laboratorio', 'puede_traspasar', 'dias_en_laboratorio',
            'observaciones', 'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at', 'codigo_interno']

    def get_modelo_info(self, obj):
        return {
            'id': obj.modelo.id,
            'nombre': obj.modelo.nombre,
            'marca': obj.modelo.marca.nombre,
            'codigo_modelo': obj.modelo.codigo_modelo
        }

    def get_tipo_equipo_info(self, obj):
        return {
            'id': obj.tipo_equipo.id,
            'nombre': obj.tipo_equipo.nombre
        }

    def get_tipo_material_info(self, obj):
        return {
            'id': obj.tipo_material.id,
            'codigo': obj.tipo_material.codigo,
            'nombre': obj.tipo_material.nombre,
            'es_unico': obj.tipo_material.es_unico
        }

    def get_lote_info(self, obj):
        return {
            'id': obj.lote.id,
            'numero_lote': obj.lote.numero_lote,
            'proveedor': obj.lote.proveedor.nombre_comercial
        }

    def get_almacen_info(self, obj):
        return {
            'id': obj.almacen_actual.id,
            'codigo': obj.almacen_actual.codigo,
            'nombre': obj.almacen_actual.nombre
        }

    def get_estado_onu_info(self, obj):
        if obj.estado_onu:
            return {
                'id': obj.estado_onu.id,
                'codigo': obj.estado_onu.codigo,
                'nombre': obj.estado_onu.nombre,
                'color': obj.estado_onu.color,
                'permite_asignacion': obj.estado_onu.permite_asignacion,
                'permite_traspaso': obj.estado_onu.permite_traspaso
            }
        return None

    def get_estado_general_info(self, obj):
        if obj.estado_general:
            return {
                'id': obj.estado_general.id,
                'codigo': obj.estado_general.codigo,
                'nombre': obj.estado_general.nombre,
                'color': obj.estado_general.color,
                'permite_consumo': obj.estado_general.permite_consumo,
                'permite_traspaso': obj.estado_general.permite_traspaso
            }
        return None

    def get_tipo_origen_info(self, obj):
        return {
            'id': obj.tipo_origen.id,
            'codigo': obj.tipo_origen.codigo,
            'nombre': obj.tipo_origen.nombre
        }

    def validate_mac_address(self, value):
        """Validar MAC Address con formato mantenido"""
        if value:
            value = value.upper().replace('-', ':')
            if not re.match(r'^([0-9A-F]{2}[:-]){5}([0-9A-F]{2})$', value):
                raise serializers.ValidationError("Formato de MAC inválido. Use XX:XX:XX:XX:XX:XX")
        return value

    def validate_gpon_serial(self, value):
        """Validar GPON Serial con formato mantenido"""
        if value and len(value) < 8:
            raise serializers.ValidationError("GPON Serial debe tener al menos 8 caracteres")
        return value

    def validate_serial_manufacturer(self, value):
        """Validar D-SN con formato mantenido - OPCIONAL"""
        if value and len(value) < 6:  # ✅ Solo validar si tiene valor
            raise serializers.ValidationError("D-SN debe tener al menos 6 caracteres si se proporciona")
        return value or None  # ✅ Convertir string vacío a None

    def validate_codigo_item_equipo(self, value):
        if not (6 <= len(value) <= 10) or not value.isdigit():
            raise serializers.ValidationError("Debe tener entre 6 y 10 dígitos numéricos")
        return value

    def validate(self, data):
        tipo_material = data.get('tipo_material') or (self.instance.tipo_material if self.instance else None)

        # Validaciones específicas para equipos únicos
        if tipo_material and tipo_material.es_unico:
            required_fields = ['mac_address', 'gpon_serial']
            for field in required_fields:
                if not data.get(field) and (not self.instance or not getattr(self.instance, field, None)):
                    raise serializers.ValidationError(f"Los equipos únicos requieren {field}")

        return data


class MaterialListSerializer(serializers.ModelSerializer):
    """Serializer optimizado para listados con información expandida"""
    modelo_info = serializers.SerializerMethodField()
    lote_info = serializers.SerializerMethodField()
    almacen_info = serializers.SerializerMethodField()
    entrega_parcial_info = serializers.SerializerMethodField()
    estado_display = serializers.SerializerMethodField()
    tipo_material_info = serializers.SerializerMethodField()

    class Meta:
        model = Material
        fields = [
            'id', 'codigo_interno', 'mac_address', 'gpon_serial',
            'serial_manufacturer', 'codigo_item_equipo', 'cantidad',
            'es_nuevo', 'numero_entrega_parcial',  # ← Este YA funciona
            'created_at', 'updated_at',
            'modelo_info', 'lote_info', 'almacen_info',  # ← Restablecer estos
            'entrega_parcial_info', 'estado_display', 'tipo_material_info'
        ]

    def get_modelo_info(self, obj):
        return {
            'id': obj.modelo.id,
            'nombre': obj.modelo.nombre,
            'codigo_modelo': obj.modelo.codigo_modelo,
            'marca': obj.modelo.marca.nombre if obj.modelo.marca else 'Sin Marca',
            'tipo_material': obj.modelo.tipo_material.nombre if obj.modelo.tipo_material else 'Sin Tipo',
            'unidad_medida': obj.modelo.unidad_medida.simbolo if obj.modelo.unidad_medida_id else ''
        }

    def get_lote_info(self, obj):
        return {
            'id': obj.lote.id,
            'numero_lote': obj.lote.numero_lote,
            'proveedor_info': {
                'id': obj.lote.proveedor.id if obj.lote.proveedor else None,
                'nombre_comercial': obj.lote.proveedor.nombre_comercial if obj.lote.proveedor else 'Sin Proveedor'
            },
            'fecha_recepcion': obj.lote.fecha_recepcion,
            'almacen_destino_info': {
                'id': obj.lote.almacen_destino.id if obj.lote.almacen_destino else None,
                'nombre': obj.lote.almacen_destino.nombre if obj.lote.almacen_destino else 'Sin Almacén',
                'codigo': obj.lote.almacen_destino.codigo if obj.lote.almacen_destino else None
            }
        }

    def get_almacen_info(self, obj):
        return {
            'id': obj.almacen_actual.id,
            'codigo': obj.almacen_actual.codigo,
            'nombre': obj.almacen_actual.nombre,
            'ciudad': getattr(obj.almacen_actual, 'ciudad', None)
        }

    def get_entrega_parcial_info(self, obj):
        """VERSIÓN SIMPLIFICADA que funciona con numero_entrega_parcial"""
        numero_entrega = getattr(obj, 'numero_entrega_parcial', None) or 0
        es_parcial = numero_entrega > 0

        return {
            'id': None,
            'numero_entrega': numero_entrega,
            'fecha_entrega': None,
            'cantidad_entregada': 1,
            'observaciones': f'Entrega #{numero_entrega}' if es_parcial else 'Recepción inicial',
            'es_parcial': es_parcial
        }

    def get_estado_display(self, obj):
        if obj.tipo_material.es_unico and obj.estado_onu:
            return {
                'id': obj.estado_onu.id,
                'codigo': obj.estado_onu.codigo,
                'nombre': obj.estado_onu.nombre,
                'color': getattr(obj.estado_onu, 'color', '#gray'),
                'permite_asignacion': getattr(obj.estado_onu, 'permite_asignacion', False)
            }
        elif not obj.tipo_material.es_unico and obj.estado_general:
            # Para materiales no únicos
            return {
                'id': obj.estado_general.id,
                'codigo': obj.estado_general.codigo,
                'nombre': obj.estado_general.nombre,
                'color': getattr(obj.estado_general, 'color', '#gray'),
                'permite_consumo': getattr(obj.estado_general, 'permite_consumo', False)
            }
        return None

    def get_tipo_material_info(self, obj):
        return {
            'id': obj.tipo_material.id,
            'codigo': obj.tipo_material.codigo,
            'nombre': obj.tipo_material.nombre,
            'es_unico': obj.tipo_material.es_unico
        }
# ========== SERIALIZERS DE OPERACIONES ACTUALIZADOS ==========

class TraspasoMaterialSerializer(serializers.ModelSerializer):
    material_info = serializers.SerializerMethodField()

    class Meta:
        model = TraspasoMaterial
        fields = ['id', 'material', 'material_info', 'recibido', 'observaciones']

    def get_material_info(self, obj):
        return {
            'codigo_interno': obj.material.codigo_interno,
            'descripcion': f"{obj.material.modelo.nombre} - {obj.material.codigo_interno}",
            'tipo_material': obj.material.tipo_material.nombre
        }


class TraspasoAlmacenSerializer(serializers.ModelSerializer):
    # Información completa de relaciones
    almacen_origen_info = serializers.SerializerMethodField()
    almacen_destino_info = serializers.SerializerMethodField()
    estado_info = serializers.SerializerMethodField()
    usuario_envio_info = serializers.SerializerMethodField()
    usuario_recepcion_info = serializers.SerializerMethodField()

    # Materiales y propiedades
    materiales = TraspasoMaterialSerializer(many=True, read_only=True)
    duracion_transito = serializers.ReadOnlyField()
    materiales_faltantes = serializers.ReadOnlyField()

    class Meta:
        model = TraspasoAlmacen
        fields = [
            'id', 'numero_traspaso', 'numero_solicitud',
            'almacen_origen', 'almacen_origen_info',
            'almacen_destino', 'almacen_destino_info',
            'fecha_envio', 'fecha_recepcion',
            'estado', 'estado_info',
            'cantidad_enviada', 'cantidad_recibida', 'materiales_faltantes',
            'motivo', 'observaciones_envio', 'observaciones_recepcion',
            'usuario_envio', 'usuario_envio_info',
            'usuario_recepcion', 'usuario_recepcion_info',
            'materiales', 'duracion_transito',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['numero_traspaso', 'created_at', 'updated_at']

    def get_almacen_origen_info(self, obj):
        return {
            'id': obj.almacen_origen.id,
            'codigo': obj.almacen_origen.codigo,
            'nombre': obj.almacen_origen.nombre
        }

    def get_almacen_destino_info(self, obj):
        return {
            'id': obj.almacen_destino.id,
            'codigo': obj.almacen_destino.codigo,
            'nombre': obj.almacen_destino.nombre
        }

    def get_estado_info(self, obj):
        return {
            'id': obj.estado.id,
            'codigo': obj.estado.codigo,
            'nombre': obj.estado.nombre,
            'color': obj.estado.color,
            'es_final': obj.estado.es_final
        }

    def get_usuario_envio_info(self, obj):
        if obj.usuario_envio:
            return {
                'id': obj.usuario_envio.id,
                'nombre_completo': obj.usuario_envio.nombre_completo
            }
        return None

    def get_usuario_recepcion_info(self, obj):
        if obj.usuario_recepcion:
            return {
                'id': obj.usuario_recepcion.id,
                'nombre_completo': obj.usuario_recepcion.nombre_completo
            }
        return None

    def validate_numero_solicitud(self, value):
        if not (6 <= len(value) <= 10) or not value.isdigit():
            raise serializers.ValidationError("Debe tener entre 6 y 10 dígitos numéricos")
        return value

    def validate(self, data):
        if data.get('almacen_origen') == data.get('almacen_destino'):
            raise serializers.ValidationError("El almacén origen y destino deben ser diferentes")
        return data


class TraspasoCreateSerializer(serializers.ModelSerializer):
    """Serializer para crear traspasos con materiales"""
    materiales_ids = serializers.ListField(
        child=serializers.IntegerField(),
        write_only=True,
        help_text="IDs de los materiales a traspasar"
    )

    class Meta:
        model = TraspasoAlmacen
        fields = [
            'numero_solicitud', 'almacen_origen', 'almacen_destino',
            'motivo', 'observaciones_envio', 'materiales_ids'
        ]

    def validate_materiales_ids(self, value):
        if not value:
            raise serializers.ValidationError("Debe seleccionar al menos un material")

        # Verificar que todos los materiales existan y puedan ser traspasados
        materiales = Material.objects.filter(id__in=value)

        if materiales.count() != len(value):
            raise serializers.ValidationError("Algunos materiales no existen")

        # Verificar que todos los materiales puedan ser traspasados
        for material in materiales:
            if not material.puede_traspasar:
                raise serializers.ValidationError(
                    f"El material {material.codigo_interno} no puede ser traspasado"
                )

        return value

    def create(self, validated_data):
        materiales_ids = validated_data.pop('materiales_ids')
        request = self.context.get('request')

        with transaction.atomic():
            # Buscar estado inicial
            try:
                estado_pendiente = EstadoTraspaso.objects.get(codigo='PENDIENTE', activo=True)
                validated_data['estado'] = estado_pendiente
            except EstadoTraspaso.DoesNotExist:
                pass

            # Crear traspaso
            traspaso = TraspasoAlmacen.objects.create(
                **validated_data,
                fecha_envio=timezone.now(),
                cantidad_enviada=len(materiales_ids),
                usuario_envio=request.user if request else None
            )

            # Crear relaciones con materiales
            materiales = Material.objects.filter(id__in=materiales_ids)
            for material in materiales:
                TraspasoMaterial.objects.create(
                    traspaso=traspaso,
                    material=material
                )

                # Actualizar estado del material
                material.traspaso_actual = traspaso
                material.save()

        return traspaso

    def to_representation(self, instance):
        return TraspasoAlmacenSerializer(instance).data

# ========== SERIALIZERS DE HISTORIAL ==========

class HistorialMaterialSerializer(serializers.ModelSerializer):
    material_info = serializers.SerializerMethodField()
    almacen_anterior_info = serializers.SerializerMethodField()
    almacen_nuevo_info = serializers.SerializerMethodField()
    usuario_info = serializers.SerializerMethodField()
    traspaso_info = serializers.SerializerMethodField()
    devolucion_info = serializers.SerializerMethodField()

    class Meta:
        model = HistorialMaterial
        fields = [
            'id', 'material', 'material_info',
            'estado_anterior', 'estado_nuevo',
            'almacen_anterior', 'almacen_anterior_info',
            'almacen_nuevo', 'almacen_nuevo_info',
            'motivo', 'observaciones',
            'traspaso_relacionado', 'traspaso_info',
            'devolucion_relacionada', 'devolucion_info',
            'fecha_cambio', 'usuario_responsable', 'usuario_info'
        ]

    def get_material_info(self, obj):
        return {
            'codigo_interno': obj.material.codigo_interno
        }

    def get_almacen_anterior_info(self, obj):
        if obj.almacen_anterior:
            return {
                'codigo': obj.almacen_anterior.codigo,
                'nombre': obj.almacen_anterior.nombre
            }
        return None

    def get_almacen_nuevo_info(self, obj):
        return {
            'codigo': obj.almacen_nuevo.codigo,
            'nombre': obj.almacen_nuevo.nombre
        }

    def get_usuario_info(self, obj):
        return {
            'nombre_completo': obj.usuario_responsable.nombre_completo
        }

    def get_traspaso_info(self, obj):
        if obj.traspaso_relacionado:
            return {
                'numero_traspaso': obj.traspaso_relacionado.numero_traspaso
            }
        return None

    def get_devolucion_info(self, obj):
        if obj.devolucion_relacionada:
            return {
                'numero_devolucion': obj.devolucion_relacionada.numero_devolucion
            }
        return None

# ========== SERIALIZERS DE OPERACIONES ESPECIALES ==========

class LaboratorioOperacionSerializer(serializers.Serializer):
    """Serializer para operaciones de laboratorio"""
    material_id = serializers.IntegerField()
    accion = serializers.ChoiceField(choices=['enviar', 'retornar'])
    numero_informe = serializers.CharField(required=False, allow_blank=True)
    detalles_informe = serializers.CharField(required=False, allow_blank=True)
    resultado_exitoso = serializers.BooleanField(default=True)
    observaciones = serializers.CharField(required=False, allow_blank=True)

    def validate_material_id(self, value):
        try:
            material = Material.objects.get(id=value)
        except Material.DoesNotExist:
            raise serializers.ValidationError("El material no existe")

        return value

    def validate(self, data):
        material = Material.objects.get(id=data['material_id'])
        accion = data['accion']

        if accion == 'enviar':
            if not material.requiere_laboratorio and material.tipo_material.es_unico:
                if material.estado_onu and material.estado_onu.codigo == 'EN_LABORATORIO':
                    raise serializers.ValidationError("El material ya está en laboratorio")

        elif accion == 'retornar':
            if material.tipo_material.es_unico:
                if not material.estado_onu or material.estado_onu.codigo != 'EN_LABORATORIO':
                    raise serializers.ValidationError("El material no está en laboratorio")

            if not data.get('numero_informe'):
                raise serializers.ValidationError("El número de informe es obligatorio para retornar")

        return data

    def ejecutar_operacion(self):
        """Ejecutar la operación de laboratorio"""
        material = Material.objects.get(id=self.validated_data['material_id'])
        accion = self.validated_data['accion']

        if accion == 'enviar':
            material.enviar_a_laboratorio()

        elif accion == 'retornar':
            material.retornar_de_laboratorio(
                resultado_exitoso=self.validated_data['resultado_exitoso'],
                informe_numero=self.validated_data.get('numero_informe'),
                detalles=self.validated_data.get('detalles_informe')
            )

        return material


class CambioEstadoMaterialSerializer(serializers.Serializer):
    """Serializer para cambios de estado de materiales"""
    material_id = serializers.IntegerField()
    nuevo_estado_id = serializers.IntegerField()
    motivo = serializers.CharField()
    observaciones = serializers.CharField(required=False, allow_blank=True)

    def validate_material_id(self, value):
        try:
            material = Material.objects.get(id=value)
        except Material.DoesNotExist:
            raise serializers.ValidationError("El material no existe")

        return value

    def validate(self, data):
        material = Material.objects.get(id=data['material_id'])
        nuevo_estado_id = data['nuevo_estado_id']

        # Validar que el nuevo estado sea válido para el tipo de material
        if material.tipo_material.es_unico:
            try:
                EstadoMaterialONU.objects.get(id=nuevo_estado_id, activo=True)
            except EstadoMaterialONU.DoesNotExist:
                raise serializers.ValidationError("Estado inválido para equipo único")
        else:
            try:
                EstadoMaterialGeneral.objects.get(id=nuevo_estado_id, activo=True)
            except EstadoMaterialGeneral.DoesNotExist:
                raise serializers.ValidationError("Estado inválido para este material")

        return data

    def ejecutar_cambio(self):
        """Ejecutar el cambio de estado"""
        material = Material.objects.get(id=self.validated_data['material_id'])
        nuevo_estado_id = self.validated_data['nuevo_estado_id']
        motivo = self.validated_data['motivo']
        observaciones = self.validated_data.get('observaciones', '')

        # Guardar estado anterior
        if material.tipo_material.es_unico:
            estado_anterior = material.estado_onu.nombre if material.estado_onu else 'Sin estado'
            nuevo_estado = EstadoMaterialONU.objects.get(id=nuevo_estado_id)
            material.estado_onu = nuevo_estado
            estado_nuevo = nuevo_estado.nombre
        else:
            estado_anterior = material.estado_general.nombre if material.estado_general else 'Sin estado'
            nuevo_estado = EstadoMaterialGeneral.objects.get(id=nuevo_estado_id)
            material.estado_general = nuevo_estado
            estado_nuevo = nuevo_estado.nombre

        material.save()

        # Crear registro en historial
        HistorialMaterial.objects.create(
            material=material,
            estado_anterior=estado_anterior,
            estado_nuevo=estado_nuevo,
            almacen_anterior=material.almacen_actual,
            almacen_nuevo=material.almacen_actual,
            motivo=motivo,
            observaciones=observaciones,
            usuario_responsable=self.context.get('request').user if self.context.get('request') else None
        )

        return material


# ========== SERIALIZER PARA IMPORTACIÓN MASIVA ==========

class ImportacionMasivaSerializer(serializers.Serializer):
    """Serializer para importación masiva de equipos desde archivo Excel/CSV"""

    archivo = serializers.FileField(
        help_text="Archivo Excel (.xlsx) o CSV con datos de equipos"
    )
    lote_id = serializers.IntegerField(
        help_text="ID del lote al que pertenecen los equipos"
    )
    modelo_id = serializers.IntegerField(
        help_text="ID del modelo de los equipos a importar"
    )
    validar_solo = serializers.BooleanField(
        default=False,
        help_text="Solo validar sin importar (preview)"
    )

    def validate_archivo(self, value):
        """Validar archivo subido"""
        # Verificar tamaño (máximo 5MB)
        if value.size > 5 * 1024 * 1024:
            raise serializers.ValidationError("El archivo no puede ser mayor a 5MB")

        # Verificar extensión
        nombre = value.name.lower()
        if not (nombre.endswith('.xlsx') or nombre.endswith('.csv')):
            raise serializers.ValidationError("Solo se permiten archivos .xlsx o .csv")

        return value

    def validate_lote_id(self, value):
        """Validar que el lote existe y está activo"""
        try:
            lote = Lote.objects.get(id=value)

            # Verificar que el lote no esté cerrado
            try:
                estado_cerrado = EstadoLote.objects.get(codigo='CERRADO', activo=True)
                if lote.estado == estado_cerrado:
                    raise serializers.ValidationError("No se puede importar a un lote cerrado")
            except EstadoLote.DoesNotExist:
                pass

            return value
        except Lote.DoesNotExist:
            raise serializers.ValidationError("El lote especificado no existe")

    def validate_modelo_id(self, value):
        """Validar que el modelo existe y es de tipo ONU"""
        try:
            modelo = Modelo.objects.get(id=value, activo=True)

            # Verificar que sea tipo ONU (equipo único)
            if not modelo.tipo_material.es_unico:
                raise serializers.ValidationError("Solo se pueden importar equipos únicos (ONUs)")

            return value
        except Modelo.DoesNotExist:
            raise serializers.ValidationError("El modelo especificado no existe o no está activo")

    def procesar_importacion(self):
        """Procesar el archivo de importación"""
        archivo = self.validated_data['archivo']
        lote_id = self.validated_data['lote_id']
        modelo_id = self.validated_data['modelo_id']
        validar_solo = self.validated_data['validar_solo']

        # Leer archivo según extensión
        try:
            if archivo.name.lower().endswith('.xlsx'):
                df = pd.read_excel(archivo)
            else:  # CSV
                df = pd.read_csv(archivo)
        except Exception as e:
            raise serializers.ValidationError(f"Error leyendo archivo: {str(e)}")

        # Validar columnas requeridas
        columnas_requeridas = ['MAC', 'GPON_SN', 'D_SN', 'ITEM_EQUIPO']
        # Validar columnas requeridas
        columnas_requeridas = ['MAC', 'GPON_SN', 'D_SN', 'ITEM_EQUIPO']
        columnas_faltantes = [col for col in columnas_requeridas if col not in df.columns]

        if columnas_faltantes:
            raise serializers.ValidationError(
                f"Columnas faltantes: {', '.join(columnas_faltantes)}"
            )

        # Limpiar y validar datos
        resultados = {
            'validados': 0,
            'errores': 0,
            'importados': 0,
            'detalles_errores': [],
            'equipos_validos': []
        }

        lote = Lote.objects.get(id=lote_id)
        modelo = Modelo.objects.get(id=modelo_id)

        equipos_validos = []

        # ✅ VERSIÓN CORREGIDA COMPLETA
        for index, row in df.iterrows():
            fila_num = index + 2  # +2 porque pandas es 0-indexed y hay header
            errores_fila = []

            # Extraer y limpiar datos
            mac = str(row['MAC']).strip().upper() if pd.notna(row['MAC']) else ''
            gpon_sn = str(row['GPON_SN']).strip() if pd.notna(row['GPON_SN']) else ''
            d_sn = str(row['D_SN']).strip() if pd.notna(row['D_SN']) else ''
            item_equipo = str(row['ITEM_EQUIPO']).strip() if pd.notna(row['ITEM_EQUIPO']) else ''

            # Validar campos requeridos
            if not mac:
                errores_fila.append("MAC Address requerido")
            if not gpon_sn:
                errores_fila.append("GPON Serial requerido")
            if not d_sn:
                errores_fila.append("D-SN requerido")
            if not item_equipo:
                errores_fila.append("Item Equipo requerido")

            # Validar formato MAC
            if mac and not re.match(r'^([0-9A-F]{2}[:-]){5}([0-9A-F]{2})$', mac):
                errores_fila.append("Formato de MAC inválido")
            else:
                # Normalizar MAC
                if mac:
                    mac = mac.replace('-', ':')

            # Validar Item Equipo
            if item_equipo and (not item_equipo.isdigit() or not (6 <= len(item_equipo) <= 10)):
                errores_fila.append("Item Equipo debe tener 6-10 dígitos")

            # Validar unicidad
            if mac:
                if Material.objects.filter(mac_address=mac).exists():
                    errores_fila.append(f"MAC {mac} ya existe en el sistema")

            if gpon_sn:
                if Material.objects.filter(gpon_serial=gpon_sn).exists():
                    errores_fila.append(f"GPON Serial {gpon_sn} ya existe")

            if d_sn:
                if Material.objects.filter(serial_manufacturer=d_sn).exists():
                    errores_fila.append(f"D-SN {d_sn} ya existe")

            # Registrar resultados
            if errores_fila:
                resultados['errores'] += 1
                resultados['detalles_errores'].append({
                    'fila': fila_num,
                    'mac': mac,
                    'errores': errores_fila
                })
            else:
                resultados['validados'] += 1
                equipos_validos.append({
                    'mac_address': mac,
                    'gpon_serial': gpon_sn,
                    'serial_manufacturer': d_sn,
                    'codigo_item_equipo': item_equipo
                })

        # Si solo es validación, retornar resultados
        if validar_solo:
            resultados['equipos_validos'] = equipos_validos
            return resultados

        # Si hay errores, no importar nada
        if resultados['errores'] > 0:
            raise serializers.ValidationError({
                'errores_validacion': resultados['detalles_errores'],
                'total_errores': resultados['errores']
            })

        # Proceder con la importación
        try:
            # Obtener estados necesarios
            tipo_onu = TipoMaterial.objects.get(codigo='ONU', activo=True)
            estado_nuevo = EstadoMaterialONU.objects.get(codigo='NUEVO', activo=True)
            tipo_nuevo = TipoIngreso.objects.get(codigo='NUEVO', activo=True)

            with transaction.atomic():
                for equipo_data in equipos_validos:
                    material = Material.objects.create(
                        tipo_material=tipo_onu,
                        modelo=modelo,
                        lote=lote,
                        mac_address=equipo_data['mac_address'],
                        gpon_serial=equipo_data['gpon_serial'],
                        serial_manufacturer=equipo_data['serial_manufacturer'],
                        codigo_item_equipo=equipo_data['codigo_item_equipo'],
                        almacen_actual=lote.almacen_destino,
                        estado_onu=estado_nuevo,
                        es_nuevo=True,
                        tipo_origen=tipo_nuevo,
                        cantidad=1.00
                    )
                    resultados['importados'] += 1

                # Actualizar estado del lote si es necesario
                try:
                    if lote.cantidad_recibida >= lote.cantidad_total:
                        estado_completa = EstadoLote.objects.get(codigo='RECEPCION_COMPLETA', activo=True)
                        lote.estado = estado_completa
                    else:
                        estado_parcial = EstadoLote.objects.get(codigo='RECEPCION_PARCIAL', activo=True)
                        lote.estado = estado_parcial
                    lote.save()
                except EstadoLote.DoesNotExist:
                    pass

        except Exception as e:
            raise serializers.ValidationError(f"Error durante la importación: {str(e)}")

        return resultados


# ========== SERIALIZERS PARA ENDPOINTS ESPECIALES ==========

class EstadisticasGeneralesSerializer(serializers.Serializer):
    """Serializer para estadísticas generales - solo para documentación de la API"""

    total_almacenes = serializers.IntegerField(read_only=True)
    total_proveedores = serializers.IntegerField(read_only=True)
    total_lotes = serializers.IntegerField(read_only=True)
    total_materiales = serializers.IntegerField(read_only=True)

    class Meta:
        # Este serializer no se asocia a un modelo específico
        # Se usa solo para estructurar la respuesta de estadísticas
        pass

class ListaOpcionesSerializer(serializers.Serializer):
    """Serializer para endpoints que devuelven listas de opciones para React"""

    def to_representation(self, instance):
        from contratos.models import TipoServicio
        return {
            'tipos_servicio': [
                {
                    'id': ts.id,
                    'nombre': ts.nombre,
                    'descripcion': ts.descripcion or ''
                }
                for ts in TipoServicio.objects.all().order_by('nombre')
            ],
            'tipos_ingreso': TipoIngresoSerializer(
                TipoIngreso.objects.filter(activo=True).order_by('orden'), many=True
            ).data,
            'estados_lote': EstadoLoteSerializer(
                EstadoLote.objects.filter(activo=True).order_by('orden'), many=True
            ).data,
            'estados_traspaso': EstadoTraspasoSerializer(
                EstadoTraspaso.objects.filter(activo=True).order_by('orden'), many=True
            ).data,
            'tipos_material': TipoMaterialSerializer(
                TipoMaterial.objects.filter(activo=True).order_by('orden'), many=True
            ).data,
            'unidades_medida': UnidadMedidaSerializer(
                UnidadMedida.objects.filter(activo=True).order_by('orden'), many=True
            ).data,
            'estados_material_onu': EstadoMaterialONUSerializer(
                EstadoMaterialONU.objects.filter(activo=True).order_by('orden'), many=True
            ).data,
            'estados_material_general': EstadoMaterialGeneralSerializer(
                EstadoMaterialGeneral.objects.filter(activo=True).order_by('orden'), many=True
            ).data,
            'tipos_almacen': TipoAlmacenSerializer(
                TipoAlmacen.objects.filter(activo=True).order_by('orden'), many=True
            ).data,
            'estados_devolucion': EstadoDevolucionSerializer(
                EstadoDevolucion.objects.filter(activo=True).order_by('orden'), many=True
            ).data,
            'respuestas_proveedor': RespuestaProveedorSerializer(
                RespuestaProveedor.objects.filter(activo=True).order_by('orden'), many=True
            ).data,
            'marcas': MarcaSerializer(
                Marca.objects.filter(activo=True).order_by('nombre'), many=True
            ).data,
            'almacenes': AlmacenSerializer(
                Almacen.objects.filter(activo=True).order_by('codigo'), many=True
            ).data,
            'proveedores': ProveedorSerializer(
                Proveedor.objects.filter(activo=True).order_by('nombre_comercial'), many=True
            ).data
        }

class MaterialDetailSerializer(MaterialListSerializer):
    """Serializer detallado para un material específico"""
    historial = serializers.SerializerMethodField()
    inspecciones = serializers.SerializerMethodField()
    especificaciones_tecnicas = serializers.JSONField(read_only=True)

    class Meta(MaterialListSerializer.Meta):
        fields = MaterialListSerializer.Meta.fields + [
            'historial', 'inspecciones', 'especificaciones_tecnicas', 'observaciones',
            'fecha_envio_laboratorio', 'fecha_retorno_laboratorio',
            'traspaso_actual', 'orden_trabajo'
        ]

    def get_inspecciones(self, obj):
        return [{
            'id': i.id,
            'numero_informe': i.numero_informe,
            'fecha': i.fecha_inspeccion,
            'aprobado': i.aprobado,
            'pruebas': dict(i.resultados_pruebas),
            'fallas': i.fallas_detectadas or [],
            'observaciones': i.observaciones_tecnico or i.comentarios_adicionales,
            'tecnico': (i.usuario_responsable.nombre_completo if i.usuario_responsable_id else '') or i.tecnico_revisor,
        } for i in obj.inspecciones_laboratorio.select_related('usuario_responsable').all()[:20]] if hasattr(obj, 'inspecciones_laboratorio') else []

    def get_historial(self, obj):
        # Historial completo (más reciente primero)
        historial = obj.historial.select_related('almacen_anterior', 'almacen_nuevo', 'usuario_responsable').all()[:50]
        return [{
            'id': h.id,
            'fecha_cambio': h.fecha_cambio,
            'motivo': h.motivo,
            'observaciones': h.observaciones,
            'estado_anterior': h.estado_anterior,
            'estado_nuevo': h.estado_nuevo,
            'almacen_anterior': h.almacen_anterior.nombre if h.almacen_anterior else None,
            'almacen_nuevo': h.almacen_nuevo.nombre if h.almacen_nuevo else None,
            'usuario': getattr(h.usuario_responsable, 'nombre_completo', 'Usuario') if h.usuario_responsable else None
        } for h in historial]

class ComponenteCreateUpdateSerializer(serializers.ModelSerializer):
    """Serializer para crear/actualizar componentes"""

    class Meta:
        model = Componente
        fields = [
            'nombre', 'descripcion', 'activo'
        ]

    def validate_nombre(self, value):
        """Validar que el nombre sea único"""
        instance = getattr(self, 'instance', None)
        if Componente.objects.filter(nombre=value).exclude(
                id=instance.id if instance else None
        ).exists():
            raise serializers.ValidationError(
                f"Ya existe un componente con nombre: {value}"
            )
        return value

class ModeloCreateUpdateSerializer(serializers.ModelSerializer):
    """Serializer para crear/actualizar modelos (incluye contenido de la caja)"""
    componentes_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        write_only=True,
        help_text="(Compatibilidad) Lista de IDs de componentes, cantidad 1"
    )
    componentes = serializers.ListField(
        child=serializers.DictField(),
        required=False,
        write_only=True,
        help_text="Contenido de la caja: [{'componente_id': 1, 'cantidad': 2}]"
    )

    class Meta:
        model = Modelo
        fields = [
            'marca', 'tipo_material', 'unidad_medida',
            'nombre', 'codigo_modelo', 'descripcion', 'cantidad_por_unidad',
            'requiere_inspeccion_inicial', 'pruebas_laboratorio', 'activo', 'componentes_ids', 'componentes'
        ]

    def validate_pruebas_laboratorio(self, value):
        """Lista de pruebas del laboratorio que aplican al modelo (vacía = todas)."""
        from .models import CAMPOS_PRUEBA
        if value in (None, ''):
            return []
        if not isinstance(value, list):
            raise serializers.ValidationError('Debe ser una lista de pruebas.')
        desconocidas = [v for v in value if v not in CAMPOS_PRUEBA]
        if desconocidas:
            raise serializers.ValidationError(f'Pruebas no válidas: {", ".join(map(str, desconocidas))}')
        # se guardan en el orden oficial y sin repetir
        return [c for c in CAMPOS_PRUEBA if c in value]

    def validate_codigo_modelo(self, value):
        """Validar que el código de modelo sea único"""
        instance = getattr(self, 'instance', None)
        if Modelo.objects.filter(codigo_modelo=value).exclude(
                id=instance.id if instance else None
        ).exists():
            raise serializers.ValidationError(
                f"Ya existe un modelo con código: {value}"
            )
        return value

    def validate_componentes(self, value):
        """Valida la lista [{componente_id, cantidad}]"""
        limpios = []
        vistos = set()
        for item in value:
            try:
                componente_id = int(item.get('componente_id'))
                cantidad = int(item.get('cantidad', 1))
            except (TypeError, ValueError):
                raise serializers.ValidationError('Cada componente necesita componente_id y cantidad numéricos')

            if cantidad < 1 or cantidad > 999:
                raise serializers.ValidationError('La cantidad debe estar entre 1 y 999')
            if componente_id in vistos:
                raise serializers.ValidationError('Un componente no puede repetirse en el mismo modelo')
            vistos.add(componente_id)
            limpios.append({'componente_id': componente_id, 'cantidad': cantidad})

        existentes = set(Componente.objects.filter(id__in=vistos).values_list('id', flat=True))
        faltantes = vistos - existentes
        if faltantes:
            raise serializers.ValidationError(f'Componentes inexistentes: {sorted(faltantes)}')
        return limpios

    def _extraer_componentes(self, validated_data):
        """Devuelve la lista final de componentes, o None si no se enviaron"""
        componentes = validated_data.pop('componentes', None)
        componentes_ids = validated_data.pop('componentes_ids', None)
        if componentes is not None:
            return componentes
        if componentes_ids is not None:
            return [{'componente_id': cid, 'cantidad': 1} for cid in dict.fromkeys(componentes_ids)]
        return None

    def _guardar_componentes(self, modelo, componentes):
        modelo.modelocomponente_set.all().delete()
        ModeloComponente.objects.bulk_create([
            ModeloComponente(modelo=modelo, componente_id=c['componente_id'], cantidad=c['cantidad'])
            for c in componentes
        ])

    def create(self, validated_data):
        componentes = self._extraer_componentes(validated_data)

        # Si no se indicó, la inspección inicial se hereda del tipo de material
        if 'requiere_inspeccion_inicial' not in self.initial_data and validated_data.get('tipo_material'):
            validated_data['requiere_inspeccion_inicial'] = validated_data['tipo_material'].requiere_inspeccion_inicial

        with transaction.atomic():
            modelo = Modelo.objects.create(**validated_data)
            if componentes:
                self._guardar_componentes(modelo, componentes)

        return modelo

    def update(self, instance, validated_data):
        componentes = self._extraer_componentes(validated_data)

        with transaction.atomic():
            for attr, value in validated_data.items():
                setattr(instance, attr, value)
            instance.save()

            # Solo se reemplazan si se enviaron (None = no tocar)
            if componentes is not None:
                self._guardar_componentes(instance, componentes)

        return instance

    def to_representation(self, instance):
        # Responder con el detalle completo (incluye componentes con nombre y cantidad)
        return ModeloSerializer(instance, context=self.context).data

class InspeccionLaboratorioSerializer(serializers.ModelSerializer):
    material_info = serializers.SerializerMethodField()

    class Meta:
        model = InspeccionLaboratorio
        fields = [
            'id', 'material', 'material_info', 'numero_informe',

            # Las 5 pruebas originales
            'serie_logica_ok', 'wifi_24_ok', 'wifi_5_ok',
            'puerto_ethernet_ok', 'puerto_lan_ok',

            # Pruebas adicionales
            'puerto_catv_ok', 'puerto_telefonia_rf_ok', 'otros_ok',

            # Resultado simple
            'aprobado',

            # Observaciones
            'observaciones_tecnico', 'comentarios_adicionales',
            'fallas_detectadas', 'tecnico_revisor', 'tiempo_inspeccion_minutos',

            # Auditoría
            'fecha_inspeccion', 'usuario_responsable'
        ]
        read_only_fields = ['fecha_inspeccion', 'usuario_responsable']

    def create(self, validated_data):
        request = self.context.get('request')
        if request and request.user:
            validated_data['usuario_responsable'] = request.user
        return super().create(validated_data)

    def get_material_info(self, obj):
        return {
            'id': obj.material.id,
            'codigo_interno': obj.material.codigo_interno,
            'mac_address': obj.material.mac_address,
            'gpon_serial': getattr(obj.material, 'gpon_serial', ''),
            'modelo': {
                'id': obj.material.modelo.id,
                'nombre': obj.material.modelo.nombre,
                'marca': obj.material.modelo.marca.nombre if obj.material.modelo.marca else 'Sin Marca'
            },
            'lote': {
                'id': obj.material.lote.id,
                'numero_lote': obj.material.lote.numero_lote,
                'proveedor': obj.material.lote.proveedor.nombre_comercial if obj.material.lote.proveedor else 'Sin Proveedor'
            }
        }

class ReingresoMaterialSerializer(serializers.Serializer):
    material_original_id = serializers.IntegerField()
    mac_address = serializers.CharField(max_length=17)
    gpon_serial = serializers.CharField(max_length=100)
    serial_manufacturer = serializers.CharField(max_length=100)
    codigo_item_equipo = serializers.CharField(max_length=10)
    motivo_reingreso = serializers.CharField(required=False)

class SectorSolicitanteSerializer(serializers.ModelSerializer):
    materiales_count = serializers.SerializerMethodField()
    lotes_count = serializers.SerializerMethodField()

    class Meta:
        model = SectorSolicitante
        fields = [
            'id', 'nombre', 'activo', 'orden',
            'materiales_count', 'lotes_count',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']

    def get_materiales_count(self, obj):
        v = getattr(obj, '_materiales_count', None)
        return Material.objects.filter(lote__sector_solicitante=obj).count() if v is None else v

    def get_lotes_count(self, obj):
        v = getattr(obj, '_lotes_count', None)
        return obj.lote_set.count() if v is None else v

    def validate_nombre(self, value):
        """Validar que el nombre sea único"""
        instance = getattr(self, 'instance', None)
        if SectorSolicitante.objects.filter(nombre=value).exclude(
                id=instance.id if instance else None
        ).exists():
            raise serializers.ValidationError(f"Ya existe un sector con nombre: {value}")
        return value


# ========== SERIALIZER PARA DEVOLUCIÓN A SECTOR ==========

class DevolucionSectorSerializer(serializers.Serializer):
    """Devolver materiales defectuosos al sector solicitante"""

    materiales_ids = serializers.ListField(
        child=serializers.IntegerField(),
        help_text="IDs de los materiales defectuosos a devolver"
    )
    motivo = serializers.CharField(max_length=500)

    def validate_materiales_ids(self, value):
        if not value:
            raise serializers.ValidationError("Debe seleccionar al menos un material")

        # Verificar que estén defectuosos
        estado_defectuoso = EstadoMaterialONU.objects.get(codigo='DEFECTUOSO', activo=True)
        materiales = Material.objects.filter(id__in=value)

        for material in materiales:
            if material.estado_onu != estado_defectuoso:
                raise serializers.ValidationError(
                    f"Material {material.codigo_interno} debe estar DEFECTUOSO"
                )

        return value

    def ejecutar(self, user):
        """Cambiar estado a DEVUELTO_SECTOR_SOLICITANTE"""
        estado_devuelto = EstadoMaterialONU.objects.get(codigo='DEVUELTO_SECTOR_SOLICITANTE', activo=True)
        materiales = Material.objects.filter(id__in=self.validated_data['materiales_ids'])
        motivo = self.validated_data['motivo']

        with transaction.atomic():
            for material in materiales:
                material.estado_onu = estado_devuelto
                material.observaciones += f"\n[DEVUELTO SECTOR] {timezone.localdate()} - {motivo}"
                material.save()

                # Historial
                HistorialMaterial.objects.create(
                    material=material,
                    estado_anterior='DEFECTUOSO',
                    estado_nuevo='DEVUELTO_SECTOR',
                    almacen_anterior=material.almacen_actual,
                    almacen_nuevo=material.almacen_actual,
                    motivo=f'Devuelto a sector: {nombre_sector(material.lote)}',
                    observaciones=motivo,
                    usuario_responsable=user
                )

        return len(materiales)


# ========== SERIALIZER PARA REINGRESO DESDE SECTOR ==========

class ReingresoSectorSerializer(serializers.Serializer):
    """Reingresar nuevos equipos desde sector solicitante"""

    materiales_originales_ids = serializers.ListField(
        child=serializers.IntegerField(),
        help_text="IDs de materiales devueltos al sector"
    )
    nuevos_equipos = serializers.ListField(
        child=serializers.DictField(),
        help_text="Nuevos equipos: [{mac_address, gpon_serial, serial_manufacturer, codigo_item_equipo}]"
    )

    def validate_materiales_originales_ids(self, value):
        estado_devuelto = EstadoMaterialONU.objects.get(codigo='DEVUELTO_SECTOR_SOLICITANTE', activo=True)
        materiales = Material.objects.filter(id__in=value)

        for material in materiales:
            if material.estado_onu != estado_devuelto:
                raise serializers.ValidationError(
                    f"Material {material.codigo_interno} debe estar DEVUELTO_SECTOR_SOLICITANTE"
                )

        return value

    def validate_nuevos_equipos(self, value):
        for i, equipo in enumerate(value):
            # Validar campos requeridos
            if not equipo.get('mac_address'):
                raise serializers.ValidationError(f"Equipo {i + 1}: MAC requerido")
            if not equipo.get('gpon_serial'):
                raise serializers.ValidationError(f"Equipo {i + 1}: GPON requerido")
            if not equipo.get('codigo_item_equipo'):
                raise serializers.ValidationError(f"Equipo {i + 1}: Item Equipo requerido")

            # Validar formatos
            mac = equipo['mac_address'].upper().replace('-', ':')
            if not re.match(r'^([0-9A-F]{2}[:-]){5}([0-9A-F]{2})$', mac):
                raise serializers.ValidationError(f"Equipo {i + 1}: MAC inválido")

            # Verificar unicidad
            if Material.objects.filter(mac_address=mac).exists():
                raise serializers.ValidationError(f"MAC {mac} ya existe")

        return value

    def ejecutar(self, user):
        """Crear nuevos materiales de reingreso y marcar originales como REEMPLAZADO"""
        estado_nuevo = EstadoMaterialONU.objects.get(codigo='NUEVO', activo=True)
        estado_reemplazado = EstadoMaterialONU.objects.get(codigo='REEMPLAZADO', activo=True)  # Cambio aquí

        tipo_reingreso = TipoIngreso.objects.get(codigo='REINGRESO', activo=True)
        tipo_onu = TipoMaterial.objects.get(codigo='ONU', activo=True)

        materiales_originales = Material.objects.filter(
            id__in=self.validated_data['materiales_originales_ids']
        )
        nuevos_equipos = self.validated_data['nuevos_equipos']

        materiales_creados = []

        with transaction.atomic():
            for i, material_original in enumerate(materiales_originales):
                equipo = nuevos_equipos[i]

                # Crear nuevo material como NUEVO
                nuevo_material = Material.objects.create(
                    tipo_material=tipo_onu,
                    modelo=material_original.modelo,
                    lote=material_original.lote,
                    mac_address=equipo['mac_address'].upper().replace('-', ':'),
                    gpon_serial=equipo['gpon_serial'],
                    serial_manufacturer=equipo.get('serial_manufacturer', '') or None,
                    codigo_item_equipo=equipo['codigo_item_equipo'],
                    almacen_actual=material_original.almacen_actual,
                    estado_onu=estado_nuevo,
                    es_nuevo=True,
                    tipo_origen=tipo_reingreso,
                    cantidad=1.00,
                    equipo_original=material_original,
                    numero_entrega_parcial=material_original.numero_entrega_parcial,
                    observaciones=f"Equipo de reposición desde {nombre_sector(material_original.lote)}"
                )

                # Marcar original como REEMPLAZADO
                material_original.estado_onu = estado_reemplazado
                material_original.observaciones += f"\n[REEMPLAZADO] {timezone.localdate()} - Sustituido por: {nuevo_material.codigo_interno}"
                material_original.save()

                # Historial para el nuevo
                HistorialMaterial.objects.create(
                    material=nuevo_material,
                    estado_anterior='N/A',
                    estado_nuevo='NUEVO',
                    almacen_anterior=None,
                    almacen_nuevo=nuevo_material.almacen_actual,
                    motivo=f'Reposición desde {nombre_sector(material_original.lote)}',
                    observaciones=f'Reemplaza {material_original.codigo_interno}',
                    usuario_responsable=user
                )

                # Historial para el original
                HistorialMaterial.objects.create(
                    material=material_original,
                    estado_anterior='DEVUELTO_SECTOR',
                    estado_nuevo='REEMPLAZADO',
                    almacen_anterior=material_original.almacen_actual,
                    almacen_nuevo=material_original.almacen_actual,
                    motivo='Equipo reemplazado por reposición',
                    observaciones=f'Sustituido por {nuevo_material.codigo_interno}',
                    usuario_responsable=user
                )

                materiales_creados.append(nuevo_material)

        return materiales_creados