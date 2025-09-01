# ======================================================
# apps/almacenes/serializers.py
# Serializers Completos para Sistema de Almacenes GPON/Fibra Óptica
# ======================================================

from django.db import transaction
from rest_framework import serializers
from decimal import Decimal
import pandas as pd
import re
from io import BytesIO

from .models import (
    # Modelos base
    Almacen, Proveedor,

    # Modelos existentes actualizados
    Marca, TipoEquipo, Componente, EstadoEquipo, Modelo, ModeloComponente,

    # Modelos de lotes
    Lote, LoteDetalle, EntregaParcialLote,

    # Modelo unificado
    Material,

    # Modelos de operaciones
    TraspasoAlmacen, TraspasoMaterial,
    DevolucionProveedor, DevolucionMaterial,
    HistorialMaterial,

    # Modelos para compatibilidad
    EquipoONU, EquipoServicio,

    # Enums
    TipoMaterialChoices, UnidadMedidaChoices,
    EstadoMaterialONUChoices, EstadoMaterialGeneralChoices,
    TipoIngresoChoices, EstadoLoteChoices
)


# ========== SERIALIZERS BASE ==========

class AlmacenSerializer(serializers.ModelSerializer):
    total_materiales = serializers.ReadOnlyField()
    materiales_disponibles = serializers.ReadOnlyField()
    created_by_nombre = serializers.CharField(source='created_by.nombre_completo', read_only=True)

    class Meta:
        model = Almacen
        fields = [
            'id', 'codigo', 'nombre', 'ciudad', 'tipo', 'direccion',
            'es_principal', 'activo', 'observaciones',
            'total_materiales', 'materiales_disponibles',
            'created_at', 'updated_at', 'created_by', 'created_by_nombre'
        ]
        read_only_fields = ['created_at', 'updated_at']

    def validate_codigo(self, value):
        if not value or len(value.strip()) < 2:
            raise serializers.ValidationError("El código debe tener al menos 2 caracteres")
        return value.strip().upper()

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
        return obj.lote_set.count()

    def validate_nombre_comercial(self, value):
        if not value or len(value.strip()) < 2:
            raise serializers.ValidationError("El nombre comercial debe tener al menos 2 caracteres")
        return value.strip()


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
        return obj.modelo_set.filter(activo=True).count()

    def get_materiales_count(self, obj):
        return sum(modelo.material_set.count() for modelo in obj.modelo_set.filter(activo=True))


class TipoEquipoSerializer(serializers.ModelSerializer):
    modelos_count = serializers.SerializerMethodField()
    materiales_count = serializers.SerializerMethodField()

    class Meta:
        model = TipoEquipo
        fields = ['id', 'nombre', 'descripcion', 'activo', 'modelos_count', 'materiales_count', 'created_at',
                  'updated_at']
        read_only_fields = ['created_at', 'updated_at']

    def get_modelos_count(self, obj):
        return obj.modelo_set.filter(activo=True).count()

    def get_materiales_count(self, obj):
        return obj.material_set.count()


class ComponenteSerializer(serializers.ModelSerializer):
    modelos_usando = serializers.SerializerMethodField()

    class Meta:
        model = Componente
        fields = ['id', 'nombre', 'descripcion', 'activo', 'modelos_usando', 'created_at', 'updated_at']
        read_only_fields = ['created_at', 'updated_at']

    def get_modelos_usando(self, obj):
        return obj.modelocomponente_set.filter(modelo__activo=True).count()


class EstadoEquipoSerializer(serializers.ModelSerializer):
    equipos_count = serializers.SerializerMethodField()

    class Meta:
        model = EstadoEquipo
        fields = ['id', 'nombre', 'descripcion', 'activo', 'equipos_count', 'created_at', 'updated_at']
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
    tipo_material_display = serializers.CharField(source='get_tipo_material_display', read_only=True)
    unidad_medida_display = serializers.CharField(source='get_unidad_medida_display', read_only=True)
    componentes = ModeloComponenteSerializer(source='modelocomponente_set', many=True, read_only=True)
    materiales_count = serializers.SerializerMethodField()
    materiales_disponibles = serializers.SerializerMethodField()

    # Para escritura
    componentes_data = serializers.ListField(
        child=serializers.DictField(),
        write_only=True,
        required=False
    )

    class Meta:
        model = Modelo
        fields = [
            'id', 'marca', 'marca_nombre', 'tipo_equipo', 'tipo_equipo_nombre',
            'nombre', 'codigo_modelo', 'descripcion', 'activo',
            'tipo_material', 'tipo_material_display', 'unidad_medida', 'unidad_medida_display',
            'cantidad_por_unidad', 'requiere_inspeccion_inicial',
            'componentes', 'materiales_count', 'materiales_disponibles',
            'created_at', 'updated_at', 'componentes_data'
        ]
        read_only_fields = ['created_at', 'updated_at']

    def get_materiales_count(self, obj):
        return obj.material_set.count()

    def get_materiales_disponibles(self, obj):
        if obj.tipo_material == TipoMaterialChoices.ONU:
            return obj.material_set.filter(
                estado_onu=EstadoMaterialONUChoices.DISPONIBLE
            ).count()
        else:
            return obj.material_set.filter(
                estado_general=EstadoMaterialGeneralChoices.DISPONIBLE
            ).count()

    def validate(self, data):
        # Validaciones específicas por tipo de material
        if data.get('tipo_material') == TipoMaterialChoices.ONU:
            data['requiere_inspeccion_inicial'] = True
            data['unidad_medida'] = UnidadMedidaChoices.PIEZA
            data['cantidad_por_unidad'] = Decimal('1.00')

        return data

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


# ========== SERIALIZERS DE LOTES ==========

class LoteDetalleSerializer(serializers.ModelSerializer):
    modelo_nombre = serializers.CharField(source='modelo.nombre', read_only=True)
    marca_nombre = serializers.CharField(source='modelo.marca.nombre', read_only=True)
    codigo_modelo = serializers.IntegerField(source='modelo.codigo_modelo', read_only=True)
    tipo_material = serializers.CharField(source='modelo.tipo_material', read_only=True)
    unidad_medida = serializers.CharField(source='modelo.unidad_medida', read_only=True)
    cantidad_recibida = serializers.ReadOnlyField()
    cantidad_pendiente = serializers.ReadOnlyField()

    class Meta:
        model = LoteDetalle
        fields = [
            'id', 'modelo', 'modelo_nombre', 'marca_nombre', 'codigo_modelo',
            'tipo_material', 'unidad_medida', 'cantidad',
            'cantidad_recibida', 'cantidad_pendiente', 'created_at'
        ]
        read_only_fields = ['created_at']


class EntregaParcialLoteSerializer(serializers.ModelSerializer):
    created_by_nombre = serializers.CharField(source='created_by.nombre_completo', read_only=True)

    class Meta:
        model = EntregaParcialLote
        fields = [
            'id', 'numero_entrega', 'fecha_entrega', 'cantidad_entregada',
            'estado_entrega', 'observaciones', 'created_at', 'created_by', 'created_by_nombre'
        ]
        read_only_fields = ['created_at']


class LoteSerializer(serializers.ModelSerializer):
    proveedor_nombre = serializers.CharField(source='proveedor.nombre_comercial', read_only=True)
    almacen_destino_nombre = serializers.CharField(source='almacen_destino.nombre', read_only=True)
    tipo_servicio_nombre = serializers.CharField(source='tipo_servicio.nombre', read_only=True)
    tipo_ingreso_display = serializers.CharField(source='get_tipo_ingreso_display', read_only=True)
    estado_display = serializers.CharField(source='get_estado_display', read_only=True)

    detalles = LoteDetalleSerializer(many=True, read_only=True)
    entregas_parciales = EntregaParcialLoteSerializer(many=True, read_only=True)

    # Propiedades calculadas
    cantidad_total = serializers.ReadOnlyField()
    cantidad_recibida = serializers.ReadOnlyField()
    cantidad_pendiente = serializers.ReadOnlyField()
    porcentaje_recibido = serializers.ReadOnlyField()

    created_by_nombre = serializers.CharField(source='created_by.nombre_completo', read_only=True)

    class Meta:
        model = Lote
        fields = [
            'id', 'numero_lote', 'tipo_ingreso', 'tipo_ingreso_display',
            'proveedor', 'proveedor_nombre',
            'almacen_destino', 'almacen_destino_nombre',
            'tipo_servicio', 'tipo_servicio_nombre',
            'codigo_requerimiento_compra', 'codigo_nota_ingreso',
            'fecha_recepcion', 'fecha_inicio_garantia', 'fecha_fin_garantia',
            'estado', 'estado_display',
            'numero_informe', 'detalles_informe', 'fecha_informe',
            'total_entregas_parciales', 'observaciones',
            'detalles', 'entregas_parciales',
            'cantidad_total', 'cantidad_recibida', 'cantidad_pendiente', 'porcentaje_recibido',
            'created_at', 'updated_at', 'created_by', 'created_by_nombre'
        ]
        read_only_fields = ['created_at', 'updated_at']

    def validate_codigo_requerimiento_compra(self, value):
        if not (6 <= len(value) <= 10) or not value.isdigit():
            raise serializers.ValidationError("Debe tener entre 6 y 10 dígitos numéricos")
        return value

    def validate_codigo_nota_ingreso(self, value):
        if not (6 <= len(value) <= 10) or not value.isdigit():
            raise serializers.ValidationError("Debe tener entre 6 y 10 dígitos numéricos")
        return value

    def validate(self, data):
        # Validar fechas de garantía
        if data.get('fecha_fin_garantia') and data.get('fecha_inicio_garantia'):
            if data['fecha_fin_garantia'] <= data['fecha_inicio_garantia']:
                raise serializers.ValidationError("La fecha de fin de garantía debe ser posterior al inicio")

        # Validar almacén destino para lotes nuevos
        if data.get('tipo_ingreso') == TipoIngresoChoices.NUEVO:
            almacen = data.get('almacen_destino')
            if almacen and not almacen.es_principal:
                raise serializers.ValidationError("Los lotes nuevos solo pueden ir al almacén principal")

        return data


class LoteCreateSerializer(serializers.ModelSerializer):
    """Serializer para crear lotes con detalles"""
    detalles = LoteDetalleSerializer(many=True, write_only=True)

    class Meta:
        model = Lote
        fields = [
            'numero_lote', 'tipo_ingreso', 'proveedor', 'almacen_destino', 'tipo_servicio',
            'codigo_requerimiento_compra', 'codigo_nota_ingreso',
            'fecha_recepcion', 'fecha_inicio_garantia', 'fecha_fin_garantia',
            'observaciones', 'detalles'
        ]

    def validate_codigo_requerimiento_compra(self, value):
        if not (6 <= len(value) <= 10) or not value.isdigit():
            raise serializers.ValidationError("Debe tener entre 6 y 10 dígitos numéricos")
        return value

    def validate_codigo_nota_ingreso(self, value):
        if not (6 <= len(value) <= 10) or not value.isdigit():
            raise serializers.ValidationError("Debe tener entre 6 y 10 dígitos numéricos")
        return value

    def create(self, validated_data):
        detalles_data = validated_data.pop('detalles')

        with transaction.atomic():
            lote = Lote.objects.create(**validated_data)

            for detalle_data in detalles_data:
                LoteDetalle.objects.create(lote=lote, **detalle_data)

        return lote

    def to_representation(self, instance):
        return LoteSerializer(instance).data


# ========== SERIALIZERS DEL MODELO MATERIAL UNIFICADO ==========

class MaterialSerializer(serializers.ModelSerializer):
    modelo_nombre = serializers.CharField(source='modelo.nombre', read_only=True)
    marca_nombre = serializers.CharField(source='modelo.marca.nombre', read_only=True)
    tipo_equipo_nombre = serializers.CharField(source='tipo_equipo.nombre', read_only=True)
    lote_numero = serializers.CharField(source='lote.numero_lote', read_only=True)
    almacen_nombre = serializers.CharField(source='almacen_actual.nombre', read_only=True)
    proveedor_nombre = serializers.CharField(source='lote.proveedor.nombre_comercial', read_only=True)

    # Estados y displays
    tipo_material_display = serializers.CharField(source='get_tipo_material_display', read_only=True)
    estado_display = serializers.ReadOnlyField()

    # Propiedades calculadas
    requiere_laboratorio = serializers.ReadOnlyField()
    puede_traspasar = serializers.ReadOnlyField()
    dias_en_laboratorio = serializers.ReadOnlyField()

    class Meta:
        model = Material
        fields = [
            'id', 'codigo_interno', 'tipo_material', 'tipo_material_display',
            'modelo', 'modelo_nombre', 'marca_nombre',
            'tipo_equipo', 'tipo_equipo_nombre',
            'lote', 'lote_numero', 'proveedor_nombre',
            'mac_address', 'gpon_serial', 'serial_manufacturer',
            'codigo_barras', 'especificaciones_tecnicas',
            'codigo_item_equipo',
            'almacen_actual', 'almacen_nombre',
            'estado_onu', 'estado_general', 'estado_display',
            'es_nuevo', 'tipo_origen',
            'fecha_envio_laboratorio', 'fecha_retorno_laboratorio',
            'cantidad', 'traspaso_actual', 'orden_trabajo',
            'requiere_laboratorio', 'puede_traspasar', 'dias_en_laboratorio',
            'observaciones', 'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at', 'codigo_interno']

    def validate_mac_address(self, value):
        """Validar MAC Address para equipos ONU"""
        if value:
            value = value.upper().replace('-', ':')
            if not re.match(r'^([0-9A-F]{2}[:-]){5}([0-9A-F]{2})$', value):
                raise serializers.ValidationError("Formato de MAC inválido. Use XX:XX:XX:XX:XX:XX")
        return value

    def validate_codigo_item_equipo(self, value):
        if not (6 <= len(value) <= 10) or not value.isdigit():
            raise serializers.ValidationError("Debe tener entre 6 y 10 dígitos numéricos")
        return value

    def validate(self, data):
        tipo_material = data.get('tipo_material') or (self.instance.tipo_material if self.instance else None)

        # Validaciones específicas para equipos ONU
        if tipo_material == TipoMaterialChoices.ONU:
            required_fields = ['mac_address', 'gpon_serial', 'serial_manufacturer']
            for field in required_fields:
                if not data.get(field) and (not self.instance or not getattr(self.instance, field, None)):
                    raise serializers.ValidationError(f"Los equipos ONU requieren {field}")

        return data


class MaterialListSerializer(serializers.ModelSerializer):
    """Serializer optimizado para listados"""
    modelo_completo = serializers.SerializerMethodField()
    estado_display = serializers.ReadOnlyField()
    almacen_codigo = serializers.CharField(source='almacen_actual.codigo', read_only=True)
    lote_numero = serializers.CharField(source='lote.numero_lote', read_only=True)

    class Meta:
        model = Material
        fields = [
            'id', 'codigo_interno', 'tipo_material', 'modelo_completo',
            'mac_address', 'gpon_serial', 'codigo_barras',
            'almacen_codigo', 'lote_numero', 'estado_display',
            'es_nuevo', 'cantidad', 'created_at'
        ]

    def get_modelo_completo(self, obj):
        return f"{obj.modelo.marca.nombre} {obj.modelo.nombre}"


# ========== SERIALIZERS DE IMPORTACIÓN MASIVA ==========

class ImportacionMasivaSerializer(serializers.Serializer):
    """Serializer para importación masiva desde Excel/CSV"""
    archivo = serializers.FileField()
    lote_id = serializers.IntegerField()
    almacen_id = serializers.IntegerField()

    def validate_archivo(self, value):
        if not value.name.endswith(('.xlsx', '.xls', '.csv')):
            raise serializers.ValidationError("Solo se permiten archivos Excel (.xlsx, .xls) o CSV")

        if value.size > 5 * 1024 * 1024:  # 5MB
            raise serializers.ValidationError("El archivo no puede ser mayor a 5MB")

        return value

    def validate_lote_id(self, value):
        try:
            lote = Lote.objects.get(id=value)
            if lote.estado == EstadoLoteChoices.CERRADO:
                raise serializers.ValidationError("No se puede importar a un lote cerrado")
        except Lote.DoesNotExist:
            raise serializers.ValidationError("El lote no existe")

        return value

    def validate_almacen_id(self, value):
        try:
            almacen = Almacen.objects.get(id=value, activo=True)
        except Almacen.DoesNotExist:
            raise serializers.ValidationError("El almacén no existe o no está activo")

        return value

    def procesar_importacion(self):
        """Procesar el archivo de importación"""
        archivo = self.validated_data['archivo']
        lote_id = self.validated_data['lote_id']
        almacen_id = self.validated_data['almacen_id']

        try:
            # Leer archivo según extensión
            if archivo.name.endswith('.csv'):
                df = pd.read_csv(BytesIO(archivo.read()))
            else:
                df = pd.read_excel(BytesIO(archivo.read()))

            # Validar columnas requeridas
            columnas_requeridas = ['MAC', 'GPON_SN', 'D_SN', 'ITEM_EQUIPO']
            columnas_faltantes = set(columnas_requeridas) - set(df.columns)

            if columnas_faltantes:
                raise serializers.ValidationError(
                    f"Faltan columnas requeridas: {', '.join(columnas_faltantes)}"
                )

            # Procesar datos
            lote = Lote.objects.get(id=lote_id)
            almacen = Almacen.objects.get(id=almacen_id)

            materiales_creados = []
            errores = []

            for index, row in df.iterrows():
                try:
                    # Validaciones específicas
                    mac = str(row['MAC']).strip().upper().replace('-', ':')
                    gpon_sn = str(row['GPON_SN']).strip()
                    d_sn = str(row['D_SN']).strip()
                    item_equipo = str(row['ITEM_EQUIPO']).strip()

                    # Validar MAC Address
                    if not re.match(r'^([0-9A-F]{2}[:-]){5}([0-9A-F]{2})$', mac):
                        errores.append(f"Fila {index + 2}: MAC inválida '{row['MAC']}'")
                        continue

                    # Validar duplicados
                    if Material.objects.filter(mac_address=mac).exists():
                        errores.append(f"Fila {index + 2}: MAC ya existe '{mac}'")
                        continue

                    if Material.objects.filter(gpon_serial=gpon_sn).exists():
                        errores.append(f"Fila {index + 2}: GPON Serial ya existe '{gpon_sn}'")
                        continue

                    if Material.objects.filter(serial_manufacturer=d_sn).exists():
                        errores.append(f"Fila {index + 2}: D-SN ya existe '{d_sn}'")
                        continue

                    # Obtener modelo del lote (asumiendo que hay uno solo para simplicidad)
                    # En implementación real, se debería mapear por código de modelo
                    detalle = lote.detalles.first()
                    if not detalle:
                        errores.append(f"Fila {index + 2}: El lote no tiene modelos definidos")
                        continue

                    # Crear material
                    material = Material.objects.create(
                        tipo_material=TipoMaterialChoices.ONU,
                        modelo=detalle.modelo,
                        tipo_equipo=detalle.modelo.tipo_equipo,
                        lote=lote,
                        mac_address=mac,
                        gpon_serial=gpon_sn,
                        serial_manufacturer=d_sn,
                        codigo_item_equipo=item_equipo,
                        almacen_actual=almacen,
                        es_nuevo=True if lote.tipo_ingreso == TipoIngresoChoices.NUEVO else False,
                        tipo_origen=lote.tipo_ingreso,
                        estado_onu=EstadoMaterialONUChoices.NUEVO if lote.tipo_ingreso == TipoIngresoChoices.NUEVO else EstadoMaterialONUChoices.DISPONIBLE
                    )

                    materiales_creados.append(material)

                except Exception as e:
                    errores.append(f"Fila {index + 2}: Error inesperado - {str(e)}")

            return {
                'materiales_creados': len(materiales_creados),
                'errores': errores,
                'total_filas': len(df),
                'exitoso': len(errores) == 0
            }

        except Exception as e:
            raise serializers.ValidationError(f"Error procesando archivo: {str(e)}")


# ========== SERIALIZERS DE TRASPASOS ==========

class TraspasoMaterialSerializer(serializers.ModelSerializer):
    material_codigo = serializers.CharField(source='material.codigo_interno', read_only=True)
    material_descripcion = serializers.SerializerMethodField()

    class Meta:
        model = TraspasoMaterial
        fields = ['id', 'material', 'material_codigo', 'material_descripcion', 'recibido', 'observaciones']

    def get_material_descripcion(self, obj):
        return f"{obj.material.modelo.nombre} - {obj.material.codigo_interno}"


class TraspasoAlmacenSerializer(serializers.ModelSerializer):
    almacen_origen_nombre = serializers.CharField(source='almacen_origen.nombre', read_only=True)
    almacen_destino_nombre = serializers.CharField(source='almacen_destino.nombre', read_only=True)
    usuario_envio_nombre = serializers.CharField(source='usuario_envio.nombre_completo', read_only=True)
    usuario_recepcion_nombre = serializers.CharField(source='usuario_recepcion.nombre_completo', read_only=True)
    estado_display = serializers.CharField(source='get_estado_display', read_only=True)

    materiales = TraspasoMaterialSerializer(many=True, read_only=True)
    duracion_transito = serializers.ReadOnlyField()
    materiales_faltantes = serializers.ReadOnlyField()

    class Meta:
        model = TraspasoAlmacen
        fields = [
            'id', 'numero_traspaso', 'numero_solicitud',
            'almacen_origen', 'almacen_origen_nombre',
            'almacen_destino', 'almacen_destino_nombre',
            'fecha_envio', 'fecha_recepcion',
            'estado', 'estado_display',
            'cantidad_enviada', 'cantidad_recibida', 'materiales_faltantes',
            'motivo', 'observaciones_envio', 'observaciones_recepcion',
            'usuario_envio', 'usuario_envio_nombre',
            'usuario_recepcion', 'usuario_recepcion_nombre',
            'materiales', 'duracion_transito',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['numero_traspaso', 'created_at', 'updated_at']

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


# ========== SERIALIZERS DE DEVOLUCIONES ==========

class DevolucionMaterialSerializer(serializers.ModelSerializer):
    material_codigo = serializers.CharField(source='material.codigo_interno', read_only=True)
    material_descripcion = serializers.SerializerMethodField()

    class Meta:
        model = DevolucionMaterial
        fields = ['id', 'material', 'material_codigo', 'material_descripcion', 'motivo_especifico']

    def get_material_descripcion(self, obj):
        return f"{obj.material.modelo.nombre} - {obj.material.codigo_interno}"


class DevolucionProveedorSerializer(serializers.ModelSerializer):
    lote_numero = serializers.CharField(source='lote_origen.numero_lote', read_only=True)
    proveedor_nombre = serializers.CharField(source='proveedor.nombre_comercial', read_only=True)
    estado_display = serializers.CharField(source='get_estado_display', read_only=True)
    respuesta_proveedor_display = serializers.CharField(source='get_respuesta_proveedor_display', read_only=True)
    created_by_nombre = serializers.CharField(source='created_by.nombre_completo', read_only=True)

    materiales_devueltos = DevolucionMaterialSerializer(many=True, read_only=True)
    cantidad_materiales = serializers.ReadOnlyField()

    class Meta:
        model = DevolucionProveedor
        fields = [
            'id', 'numero_devolucion', 'lote_origen', 'lote_numero',
            'proveedor', 'proveedor_nombre',
            'motivo', 'numero_informe_laboratorio',
            'estado', 'estado_display',
            'fecha_creacion', 'fecha_envio', 'fecha_confirmacion',
            'respuesta_proveedor', 'respuesta_proveedor_display',
            'observaciones_proveedor',
            'materiales_devueltos', 'cantidad_materiales',
            'created_by', 'created_by_nombre', 'updated_at'
        ]
        read_only_fields = ['numero_devolucion', 'fecha_creacion', 'updated_at']


class DevolucionCreateSerializer(serializers.ModelSerializer):
    """Serializer para crear devoluciones con materiales"""
    materiales_ids = serializers.ListField(
        child=serializers.IntegerField(),
        write_only=True,
        help_text="IDs de los materiales a devolver"
    )

    class Meta:
        model = DevolucionProveedor
        fields = [
            'lote_origen', 'motivo', 'numero_informe_laboratorio', 'materiales_ids'
        ]

    def validate_materiales_ids(self, value):
        if not value:
            raise serializers.ValidationError("Debe seleccionar al menos un material")

        # Verificar que todos los materiales existan y estén defectuosos
        materiales = Material.objects.filter(id__in=value)

        if materiales.count() != len(value):
            raise serializers.ValidationError("Algunos materiales no existen")

        for material in materiales:
            if material.tipo_material == TipoMaterialChoices.ONU:
                if material.estado_onu != EstadoMaterialONUChoices.DEFECTUOSO:
                    raise serializers.ValidationError(
                        f"El material {material.codigo_interno} debe estar defectuoso para devolverlo"
                    )
            else:
                if material.estado_general != EstadoMaterialGeneralChoices.DEFECTUOSO:
                    raise serializers.ValidationError(
                        f"El material {material.codigo_interno} debe estar defectuoso para devolverlo"
                    )

        return value

    def validate(self, data):
        # Verificar que los materiales pertenezcan al lote especificado
        lote = data.get('lote_origen')
        materiales_ids = data.get('materiales_ids', [])

        if lote:
            materiales_lote = Material.objects.filter(
                id__in=materiales_ids,
                lote=lote
            ).count()

            if materiales_lote != len(materiales_ids):
                raise serializers.ValidationError(
                    "Todos los materiales deben pertenecer al lote especificado"
                )

        return data

    def create(self, validated_data):
        materiales_ids = validated_data.pop('materiales_ids')
        request = self.context.get('request')

        with transaction.atomic():
            # Crear devolución
            devolucion = DevolucionProveedor.objects.create(
                **validated_data,
                proveedor=validated_data['lote_origen'].proveedor,
                created_by=request.user if request else None
            )

            # Crear relaciones con materiales
            materiales = Material.objects.filter(id__in=materiales_ids)
            for material in materiales:
                DevolucionMaterial.objects.create(
                    devolucion=devolucion,
                    material=material
                )

                # Actualizar estado del material
                if material.tipo_material == TipoMaterialChoices.ONU:
                    material.estado_onu = EstadoMaterialONUChoices.DEVUELTO_PROVEEDOR
                else:
                    material.estado_general = EstadoMaterialGeneralChoices.DADO_DE_BAJA
                material.save()

        return devolucion

    def to_representation(self, instance):
        return DevolucionProveedorSerializer(instance).data


# ========== SERIALIZERS DE HISTORIAL ==========

class HistorialMaterialSerializer(serializers.ModelSerializer):
    material_codigo = serializers.CharField(source='material.codigo_interno', read_only=True)
    almacen_anterior_nombre = serializers.CharField(source='almacen_anterior.nombre', read_only=True)
    almacen_nuevo_nombre = serializers.CharField(source='almacen_nuevo.nombre', read_only=True)
    usuario_nombre = serializers.CharField(source='usuario_responsable.nombre_completo', read_only=True)
    traspaso_numero = serializers.CharField(source='traspaso_relacionado.numero_traspaso', read_only=True)
    devolucion_numero = serializers.CharField(source='devolucion_relacionada.numero_devolucion', read_only=True)

    class Meta:
        model = HistorialMaterial
        fields = [
            'id', 'material', 'material_codigo',
            'estado_anterior', 'estado_nuevo',
            'almacen_anterior', 'almacen_anterior_nombre',
            'almacen_nuevo', 'almacen_nuevo_nombre',
            'motivo', 'observaciones',
            'traspaso_relacionado', 'traspaso_numero',
            'devolucion_relacionada', 'devolucion_numero',
            'fecha_cambio', 'usuario_responsable', 'usuario_nombre'
        ]


# ========== SERIALIZERS PARA COMPATIBILIDAD ==========

class EquipoONUSerializer(serializers.ModelSerializer):
    """Serializer de compatibilidad para el modelo existente"""
    modelo_nombre = serializers.CharField(source='modelo.nombre', read_only=True)
    marca_nombre = serializers.CharField(source='modelo.marca.nombre', read_only=True)
    tipo_equipo_nombre = serializers.CharField(source='tipo_equipo.nombre', read_only=True)
    estado_nombre = serializers.CharField(source='estado.nombre', read_only=True)
    lote_numero = serializers.CharField(source='lote.numero_lote', read_only=True)

    class Meta:
        model = EquipoONU
        fields = [
            'id', 'codigo_interno', 'modelo', 'modelo_nombre', 'marca_nombre',
            'tipo_equipo', 'tipo_equipo_nombre', 'lote', 'lote_numero',
            'mac_address', 'gpon_serial', 'serial_manufacturer',
            'fecha_ingreso', 'estado', 'estado_nombre',
            'observaciones', 'created_at', 'updated_at'
        ]
        read_only_fields = ['fecha_ingreso', 'created_at', 'updated_at']


class EquipoServicioSerializer(serializers.ModelSerializer):
    """Serializer de compatibilidad para relaciones con contratos"""
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


# ========== SERIALIZERS DE ESTADÍSTICAS Y REPORTES ==========

class EstadisticasAlmacenSerializer(serializers.Serializer):
    """Serializer para estadísticas de almacenes"""
    almacen_id = serializers.IntegerField()
    almacen_nombre = serializers.CharField()
    total_materiales = serializers.IntegerField()
    materiales_disponibles = serializers.IntegerField()
    materiales_reservados = serializers.IntegerField()
    materiales_en_transito = serializers.IntegerField()
    materiales_defectuosos = serializers.IntegerField()
    por_tipo_material = serializers.DictField()


class EstadisticasGeneralesSerializer(serializers.Serializer):
    """Serializer para estadísticas generales del sistema"""
    total_almacenes = serializers.IntegerField()
    total_proveedores = serializers.IntegerField()
    total_lotes = serializers.IntegerField()
    total_materiales = serializers.IntegerField()
    lotes_activos = serializers.IntegerField()
    traspasos_pendientes = serializers.IntegerField()
    materiales_en_laboratorio = serializers.IntegerField()
    devoluciones_pendientes = serializers.IntegerField()
    por_almacen = EstadisticasAlmacenSerializer(many=True)
    top_proveedores = serializers.ListField()
    materiales_proximos_vencer = serializers.IntegerField()


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
            if not material.requiere_laboratorio and material.tipo_material == TipoMaterialChoices.ONU:
                if material.estado_onu == EstadoMaterialONUChoices.EN_LABORATORIO:
                    raise serializers.ValidationError("El material ya está en laboratorio")

        elif accion == 'retornar':
            if material.tipo_material == TipoMaterialChoices.ONU:
                if material.estado_onu != EstadoMaterialONUChoices.EN_LABORATORIO:
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
    nuevo_estado = serializers.CharField()
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
        nuevo_estado = data['nuevo_estado']

        # Validar que el nuevo estado sea válido para el tipo de material
        if material.tipo_material == TipoMaterialChoices.ONU:
            estados_validos = [choice[0] for choice in EstadoMaterialONUChoices.choices]
            if nuevo_estado not in estados_validos:
                raise serializers.ValidationError(f"Estado inválido para equipo ONU: {nuevo_estado}")
        else:
            estados_validos = [choice[0] for choice in EstadoMaterialGeneralChoices.choices]
            if nuevo_estado not in estados_validos:
                raise serializers.ValidationError(f"Estado inválido para este material: {nuevo_estado}")

        return data

    def ejecutar_cambio(self):
        """Ejecutar el cambio de estado"""
        material = Material.objects.get(id=self.validated_data['material_id'])
        nuevo_estado = self.validated_data['nuevo_estado']
        motivo = self.validated_data['motivo']
        observaciones = self.validated_data.get('observaciones', '')

        # Guardar estado anterior
        if material.tipo_material == TipoMaterialChoices.ONU:
            estado_anterior = material.estado_onu
            material.estado_onu = nuevo_estado
        else:
            estado_anterior = material.estado_general
            material.estado_general = nuevo_estado

        material.save()

        # Crear registro en historial
        HistorialMaterial.objects.create(
            material=material,
            estado_anterior=estado_anterior,
            estado_nuevo=nuevo_estado,
            almacen_anterior=material.almacen_actual,
            almacen_nuevo=material.almacen_actual,
            motivo=motivo,
            observaciones=observaciones,
            usuario_responsable=self.context.get('request').user if self.context.get('request') else None
        )

        return material