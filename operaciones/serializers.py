# ======================================================
# operaciones/serializers.py
# ======================================================
import re

from django.db import transaction
from rest_framework import serializers

from contratos.models import Cliente, PlanComercial, TipoServicio
from . import deuda, geo
from .models import (Cuadrilla, Despacho, DespachoEquipo, DespachoMaterial, HistorialOT, IntegranteCuadrilla, KitMaterial,
                     OrdenTrabajo, PlanAdicional, Solicitud, Vehiculo, VehiculoEquipo, ZonaCobertura, cotizar)


def _nombre_usuario(u):
    if not u:
        return ''
    return (getattr(u, 'nombre_completo', '') or '').strip() or str(getattr(u, 'codigocotel', '') or u)


def _opcion(choices, valor):
    return {'codigo': valor, 'nombre': dict(choices).get(valor, valor)}


def _cuadrilla(c):
    return {'id': c.id, 'nombre': c.nombre} if c else None


# ---------------- Zonas de cobertura ----------------

class ZonaCoberturaSerializer(serializers.ModelSerializer):
    almacen_nombre = serializers.CharField(source='almacen.nombre', read_only=True, default=None)
    area_km2 = serializers.SerializerMethodField()
    solicitudes = serializers.IntegerField(source='n_solicitudes', read_only=True, default=0)

    class Meta:
        model = ZonaCobertura
        fields = ['id', 'nombre', 'color', 'almacen', 'almacen_nombre', 'geometria', 'activo',
                  'observaciones', 'area_km2', 'solicitudes', 'created_at', 'updated_at']
        read_only_fields = ['created_at', 'updated_at']

    def get_area_km2(self, obj):
        return geo.area_km2(obj.geometria)

    def validate_nombre(self, v):
        v = (v or '').strip()
        if not v:
            raise serializers.ValidationError('El nombre es obligatorio.')
        qs = ZonaCobertura.objects.filter(nombre__iexact=v)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError('Ya existe una zona con ese nombre.')
        return v

    def validate_color(self, v):
        v = (v or '').strip().upper()
        if not re.fullmatch(r'#[0-9A-F]{6}', v):
            raise serializers.ValidationError('Color no válido (usa #RRGGBB).')
        return v

    def validate_geometria(self, v):
        geom, error = geo.validar_geometria(v)
        if error:
            raise serializers.ValidationError(error)
        return geom


# ---------------- Planes ----------------

class PlanSerializer(serializers.ModelSerializer):
    solicitudes_count = serializers.IntegerField(source='n_solicitudes', read_only=True, default=0)

    class Meta:
        model = PlanComercial
        fields = ['id', 'nombre', 'codigo_plan',
                  'velocidad_descarga', 'velocidad_subida', 'precio_mensual', 'precio_instalacion',
                  'descripcion', 'activo', 'solicitudes_count']

    def validate_codigo_plan(self, v):
        v = (v or '').strip().upper()
        if not v:
            raise serializers.ValidationError('El código es obligatorio.')
        qs = PlanComercial.objects.filter(codigo_plan__iexact=v)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError('Ya existe un plan con ese código.')
        return v

    def validate_nombre(self, v):
        v = (v or '').strip()
        if not v:
            raise serializers.ValidationError('El nombre es obligatorio.')
        return v

    def validate(self, attrs):
        for campo in ('velocidad_descarga', 'velocidad_subida', 'precio_mensual', 'precio_instalacion'):
            if attrs.get(campo) is not None and attrs[campo] < 0:
                raise serializers.ValidationError({campo: 'No puede ser negativo.'})
        if not self.instance and not attrs.get('velocidad_descarga'):
            raise serializers.ValidationError({'velocidad_descarga': 'Indica la velocidad del plan.'})
        return attrs

    def create(self, data):
        # Todo plan es de internet: la telefonía y la TV cable se marcan como adicionales en la solicitud
        data['tipo_servicio'], _ = TipoServicio.objects.get_or_create(nombre='Internet')
        return super().create(data)


class PlanAdicionalSerializer(serializers.ModelSerializer):
    tipo_nombre = serializers.CharField(source='get_tipo_display', read_only=True)
    solicitudes_count = serializers.IntegerField(source='n_solicitudes', read_only=True, default=0)

    class Meta:
        model = PlanAdicional
        fields = ['id', 'tipo', 'tipo_nombre', 'nombre', 'precio_mensual', 'costo_instalacion', 'unidades_incluidas',
                  'precio_unidad_extra', 'maximo_unidades', 'descripcion', 'activo', 'solicitudes_count']

    def validate_nombre(self, v):
        v = (v or '').strip()
        if not v:
            raise serializers.ValidationError('El nombre es obligatorio.')
        return v

    def validate(self, attrs):
        g = lambda k: attrs.get(k, getattr(self.instance, k, None))  # noqa: E731
        tipo, nombre = g('tipo'), g('nombre')
        qs = PlanAdicional.objects.filter(tipo=tipo, nombre__iexact=nombre)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError({'nombre': 'Ya existe un adicional de ese tipo con ese nombre.'})
        for campo in ('precio_mensual', 'costo_instalacion', 'precio_unidad_extra'):
            if attrs.get(campo) is not None and attrs[campo] < 0:
                raise serializers.ValidationError({campo: 'No puede ser negativo.'})
        incluidas, maximo = g('unidades_incluidas') or 0, g('maximo_unidades') or 0
        if incluidas < 1:
            raise serializers.ValidationError({'unidades_incluidas': 'Debe incluir al menos 1.'})
        if maximo < incluidas:
            raise serializers.ValidationError({'maximo_unidades': 'El máximo no puede ser menor a lo incluido.'})
        return attrs


# ---------------- Clientes ----------------

class ClienteMiniSerializer(serializers.ModelSerializer):
    nombre_completo = serializers.SerializerMethodField()

    class Meta:
        model = Cliente
        fields = ['id', 'ci', 'nombres', 'apellidos', 'nombre_completo', 'telefono', 'telefono_alternativo',
                  'email', 'direccion', 'zona', 'ciudad']

    def get_nombre_completo(self, obj):
        return f'{obj.nombres} {obj.apellidos}'.strip()


class ClienteEditarSerializer(serializers.ModelSerializer):
    class Meta:
        model = Cliente
        fields = ['nombres', 'apellidos', 'telefono', 'telefono_alternativo', 'email', 'direccion', 'zona', 'ciudad']

    def validate(self, attrs):
        for k in ('nombres', 'apellidos'):
            if k in attrs:
                attrs[k] = attrs[k].strip()
                if not attrs[k]:
                    raise serializers.ValidationError({k: 'Es obligatorio.'})
        for k in ('telefono', 'telefono_alternativo'):
            v = (attrs.get(k) or '').strip()
            if k in attrs:
                if v and not re.fullmatch(r'[0-9+\-\s()]{7,20}', v):
                    raise serializers.ValidationError({k: 'Teléfono no válido.'})
                attrs[k] = v
        if 'telefono' in attrs and not attrs['telefono']:
            raise serializers.ValidationError({'telefono': 'Es obligatorio.'})
        return attrs


class ClienteEntradaSerializer(serializers.Serializer):
    ci = serializers.CharField(max_length=15)
    nombres = serializers.CharField(max_length=100)
    apellidos = serializers.CharField(max_length=100)
    telefono = serializers.CharField(max_length=20)
    email = serializers.EmailField(required=False, allow_blank=True)

    def validate_ci(self, v):
        v = re.sub(r'\s+', '', v or '').upper()
        if not re.fullmatch(r'[0-9]{4,12}(-?[0-9A-Z]{1,3})?', v):
            raise serializers.ValidationError('CI no válido (solo números y, si tiene, complemento: 1234567-1A).')
        return v

    def validate_telefono(self, v):
        v = (v or '').strip()
        if not re.fullmatch(r'[0-9+\-\s()]{7,20}', v):
            raise serializers.ValidationError('Teléfono no válido.')
        return v


# ---------------- Órdenes de trabajo ----------------

class HistorialOTSerializer(serializers.ModelSerializer):
    usuario = serializers.SerializerMethodField()
    estado_anterior = serializers.SerializerMethodField()
    estado_nuevo = serializers.SerializerMethodField()

    cuadrilla_anterior = serializers.SerializerMethodField()
    cuadrilla_nueva = serializers.SerializerMethodField()

    class Meta:
        model = HistorialOT
        fields = ['id', 'estado_anterior', 'estado_nuevo', 'usuario', 'observacion', 'fecha',
                  'cuadrilla_anterior', 'cuadrilla_nueva', 'fecha_anterior', 'fecha_nueva']

    def get_cuadrilla_anterior(self, obj):
        return _cuadrilla(obj.cuadrilla_anterior)

    def get_cuadrilla_nueva(self, obj):
        return _cuadrilla(obj.cuadrilla_nueva)

    def get_usuario(self, obj):
        return _nombre_usuario(obj.usuario)

    def get_estado_anterior(self, obj):
        return _opcion(OrdenTrabajo.Estado.choices, obj.estado_anterior) if obj.estado_anterior else None

    def get_estado_nuevo(self, obj):
        return _opcion(OrdenTrabajo.Estado.choices, obj.estado_nuevo)


class OrdenListSerializer(serializers.ModelSerializer):
    estado = serializers.SerializerMethodField()
    tipo = serializers.SerializerMethodField()
    solicitud = serializers.SerializerMethodField()
    cliente = serializers.SerializerMethodField()
    zona = serializers.SerializerMethodField()
    dias = serializers.SerializerMethodField()
    cuadrilla = serializers.SerializerMethodField()
    plazo = serializers.SerializerMethodField()

    class Meta:
        model = OrdenTrabajo
        fields = ['id', 'numero', 'tipo', 'estado', 'prioridad', 'fecha_programada', 'cuadrilla', 'orden_visita',
                  'solicitud', 'cliente', 'zona', 'dias', 'plazo', 'created_at', 'fecha_cierre']

    def get_estado(self, obj):
        return _opcion(OrdenTrabajo.Estado.choices, obj.estado)

    def get_tipo(self, obj):
        return _opcion(Solicitud.Tipo.choices, obj.tipo)

    def get_solicitud(self, obj):
        s = obj.solicitud
        return {'id': s.id, 'numero': s.numero, 'direccion': s.direccion, 'zona_referencia': s.zona_referencia,
                'referencia': s.referencia, 'lat': float(s.latitud), 'lng': float(s.longitud),
                'plan': s.plan.nombre if s.plan_id else None, 'servicios': s.servicios}

    def get_cliente(self, obj):
        c = obj.solicitud.cliente
        return {'id': c.id, 'ci': c.ci, 'nombre': f'{c.nombres} {c.apellidos}'.strip(), 'telefono': obj.solicitud.telefono_contacto or c.telefono}

    def get_zona(self, obj):
        z = obj.solicitud.zona_cobertura
        return {'id': z.id, 'nombre': z.nombre, 'color': z.color} if z else None

    def get_dias(self, obj):
        from django.utils import timezone
        fin = obj.fecha_cierre or timezone.now()
        return (fin - obj.created_at).days

    def get_cuadrilla(self, obj):
        return _cuadrilla(obj.cuadrilla)

    def get_plazo(self, obj):
        """Plazo ATT (solo informa): EN_PLAZO / POR_VENCER / VENCIDA, o CUMPLIDO / INCUMPLIDO si ya se ejecutó."""
        from .plazos import plazo
        p = plazo(obj)
        return p and {**p, 'limite': p['limite'].isoformat()}


class OrdenDetailSerializer(OrdenListSerializer):
    historial = HistorialOTSerializer(many=True, read_only=True)
    ubicacion = serializers.SerializerMethodField()

    class Meta(OrdenListSerializer.Meta):
        fields = OrdenListSerializer.Meta.fields + ['observaciones', 'historial', 'ubicacion']

    def get_ubicacion(self, obj):
        s = obj.solicitud
        return {'lat': float(s.latitud), 'lng': float(s.longitud), 'referencia': s.referencia,
                'observaciones': s.observaciones}

    def get_cuadrilla(self, obj):
        # En el detalle (y la OT impresa): vehículo y quiénes formaban la cuadrilla en la fecha programada
        c = obj.cuadrilla
        if not c:
            return None
        integrantes = c.integrantes_en(obj.fecha_programada) if obj.fecha_programada else c.vigentes()
        return {**_cuadrilla(c),
                'vehiculo': {'placa': c.vehiculo.placa, 'descripcion': c.vehiculo.descripcion} if c.vehiculo_id else None,
                'integrantes': IntegranteSerializer(integrantes.select_related('usuario'), many=True).data}


# ---------------- Solicitudes ----------------

class SolicitudListSerializer(serializers.ModelSerializer):
    tipo = serializers.SerializerMethodField()
    estado = serializers.SerializerMethodField()
    cliente = serializers.SerializerMethodField()
    plan = serializers.SerializerMethodField()
    zona = serializers.SerializerMethodField()
    orden = serializers.SerializerMethodField()
    creado_por = serializers.SerializerMethodField()
    ubicacion = serializers.SerializerMethodField()
    adicionales = serializers.SerializerMethodField()

    class Meta:
        model = Solicitud
        fields = ['id', 'numero', 'tipo', 'estado', 'prioridad', 'cliente', 'plan', 'direccion', 'zona_referencia',
                  'zona', 'orden', 'creado_por', 'created_at', 'ubicacion', 'servicios', 'adicionales',
                  'monto_mensual_ref', 'monto_instalacion_ref']

    def get_tipo(self, obj):
        return _opcion(Solicitud.Tipo.choices, obj.tipo)

    def get_estado(self, obj):
        return _opcion(Solicitud.Estado.choices, obj.estado)

    def get_ubicacion(self, obj):
        return {'lat': float(obj.latitud), 'lng': float(obj.longitud)}

    def get_cliente(self, obj):
        c = obj.cliente
        return {'id': c.id, 'ci': c.ci, 'nombre': f'{c.nombres} {c.apellidos}'.strip(), 'telefono': obj.telefono_contacto or c.telefono}

    def get_plan(self, obj):
        p = obj.plan
        return {'id': p.id, 'nombre': p.nombre, 'velocidad': p.velocidad_descarga} if p else None

    def get_adicionales(self, obj):
        res = []
        for ad, n in ((obj.plan_tv, obj.cantidad_tv), (obj.plan_telefonia, obj.cantidad_lineas)):
            if ad:
                res.append({'id': ad.id, 'tipo': ad.tipo, 'nombre': ad.nombre, 'cantidad': n, 'detalle': ad.unidad(n)})
        return res

    def get_zona(self, obj):
        z = obj.zona_cobertura
        return {'id': z.id, 'nombre': z.nombre, 'color': z.color} if z else None

    def get_orden(self, obj):
        o = getattr(obj, 'orden', None)
        return {'id': o.id, 'numero': o.numero, 'estado': _opcion(OrdenTrabajo.Estado.choices, o.estado)} if o else None

    def get_creado_por(self, obj):
        return _nombre_usuario(obj.creado_por)


class SolicitudDetailSerializer(SolicitudListSerializer):
    cliente = ClienteMiniSerializer(read_only=True)
    ubicacion = serializers.SerializerMethodField()

    class Meta(SolicitudListSerializer.Meta):
        fields = SolicitudListSerializer.Meta.fields + ['telefono_contacto', 'referencia', 'observaciones',
                                                        'motivo_anulacion', 'updated_at']


class SolicitudCreateSerializer(serializers.Serializer):
    """
    Registra la solicitud. El cliente se identifica por CI: si existe se reutiliza
    (y se actualizan sus datos de contacto), si no, se crea.
    Si el tipo necesita cobertura y el punto cae fuera de todas las zonas, la
    solicitud queda SIN COBERTURA y no se genera OT.
    """
    tipo = serializers.ChoiceField(choices=Solicitud.Tipo.choices)
    prioridad = serializers.ChoiceField(choices=Solicitud.Prioridad.choices, default=Solicitud.Prioridad.NORMAL)
    cliente = ClienteEntradaSerializer()
    plan = serializers.PrimaryKeyRelatedField(queryset=PlanComercial.objects.all(), required=False, allow_null=True)
    plan_tv = serializers.PrimaryKeyRelatedField(queryset=PlanAdicional.objects.filter(tipo='TV'), required=False, allow_null=True)
    cantidad_tv = serializers.IntegerField(required=False, min_value=0, default=0)
    plan_telefonia = serializers.PrimaryKeyRelatedField(queryset=PlanAdicional.objects.filter(tipo='TELEFONIA'), required=False, allow_null=True)
    cantidad_lineas = serializers.IntegerField(required=False, min_value=0, default=0)
    direccion = serializers.CharField(max_length=255)
    zona_referencia = serializers.CharField(max_length=100, required=False, allow_blank=True)
    referencia = serializers.CharField(required=False, allow_blank=True)
    latitud = serializers.DecimalField(max_digits=9, decimal_places=6, min_value=-90, max_value=90)
    longitud = serializers.DecimalField(max_digits=9, decimal_places=6, min_value=-180, max_value=180)
    observaciones = serializers.CharField(required=False, allow_blank=True)

    def validate_direccion(self, v):
        v = (v or '').strip()
        if len(v) < 5:
            raise serializers.ValidationError('Escribe la dirección completa.')
        return v

    def validate(self, attrs):
        tipo = attrs['tipo']
        plan = attrs.get('plan')
        if tipo == Solicitud.Tipo.INSTALACION:
            if not plan:
                raise serializers.ValidationError({'plan': 'Elige el plan a instalar.'})
            if not plan.activo:
                raise serializers.ValidationError({'plan': 'Ese plan ya no está vigente.'})
            for campo_plan, campo_cant in (('plan_tv', 'cantidad_tv'), ('plan_telefonia', 'cantidad_lineas')):
                ad = attrs.get(campo_plan)
                if not ad:
                    attrs[campo_cant] = 0
                    continue
                if not ad.activo:
                    raise serializers.ValidationError({campo_plan: f'{ad} ya no está vigente.'})
                n = attrs.get(campo_cant) or ad.unidades_incluidas
                if not 1 <= n <= ad.maximo_unidades:
                    raise serializers.ValidationError({campo_cant: f'{ad.get_tipo_display()}: entre 1 y {ad.maximo_unidades}.'})
                attrs[campo_cant] = n
        else:
            attrs['plan'] = attrs['plan_tv'] = attrs['plan_telefonia'] = None
            attrs['cantidad_tv'] = attrs['cantidad_lineas'] = 0

        ci = attrs['cliente']['ci']
        if tipo in deuda.tipos_bloqueados():
            estado = deuda.consultar(ci)
            if estado['bloquea']:
                raise serializers.ValidationError({'deuda': estado['mensaje']})
        abierta = Solicitud.objects.filter(cliente__ci=ci, tipo=tipo, estado=Solicitud.Estado.EN_CURSO).first()
        if abierta:
            raise serializers.ValidationError(
                {'tipo': f'El cliente ya tiene la solicitud {abierta.numero} de este tipo en curso.'})
        return attrs

    @transaction.atomic
    def create(self, data):
        from .models import OrdenTrabajo  # noqa
        usuario = self.context['request'].user
        dc = data.pop('cliente')
        cliente = Cliente.objects.filter(ci=dc['ci']).first()
        if cliente:
            cambios = {k: dc[k] for k in ('telefono', 'email') if dc.get(k) and dc[k] != getattr(cliente, k)}
            for k, v in cambios.items():
                setattr(cliente, k, v)
            if cambios:
                cliente.save(update_fields=list(cambios) + ['updated_at'])
        else:
            cliente = Cliente.objects.create(
                ci=dc['ci'], nombres=dc['nombres'].strip(), apellidos=dc['apellidos'].strip(),
                telefono=dc['telefono'], email=dc.get('email', ''),
                direccion=data['direccion'], zona=data.get('zona_referencia', ''),
            )

        if data['tipo'] == Solicitud.Tipo.INSTALACION:
            c = cotizar(data['plan'], data.get('plan_tv'), data.get('cantidad_tv', 0),
                        data.get('plan_telefonia'), data.get('cantidad_lineas', 0))
            data['monto_mensual_ref'], data['monto_instalacion_ref'] = c['mensual'], c['instalacion']
        zona = ZonaCobertura.zona_de(data['latitud'], data['longitud'])
        sin_cobertura = zona is None and data['tipo'] in Solicitud.TIPOS_CON_COBERTURA
        solicitud = Solicitud.objects.create(
            cliente=cliente, creado_por=usuario, zona_cobertura=zona,
            telefono_contacto=dc['telefono'],
            estado=Solicitud.Estado.SIN_COBERTURA if sin_cobertura else Solicitud.Estado.EN_CURSO,
            **data,
        )
        if not sin_cobertura:
            crear_orden(solicitud, usuario)
        return solicitud


class SolicitudEditarSerializer(serializers.ModelSerializer):
    """Corrige datos de contacto / ubicación mientras la OT aún no salió a campo."""

    class Meta:
        model = Solicitud
        fields = ['telefono_contacto', 'direccion', 'zona_referencia', 'referencia', 'latitud', 'longitud',
                  'observaciones', 'prioridad']

    def validate(self, attrs):
        s = self.instance
        orden = getattr(s, 'orden', None)
        if s.estado == Solicitud.Estado.ANULADA or s.estado == Solicitud.Estado.ATENDIDA:
            raise serializers.ValidationError('La solicitud ya no se puede modificar.')
        if orden and orden.estado not in (OrdenTrabajo.Estado.PENDIENTE, OrdenTrabajo.Estado.PROGRAMADA):
            raise serializers.ValidationError('La OT ya salió a campo; ya no se puede cambiar la solicitud.')
        return attrs

    @transaction.atomic
    def update(self, instance, data):
        movida = 'latitud' in data or 'longitud' in data
        antes = (instance.latitud, instance.longitud)
        instance = super().update(instance, data)
        if movida:
            zona = ZonaCobertura.zona_de(instance.latitud, instance.longitud)
            sin_cobertura = instance.estado == Solicitud.Estado.SIN_COBERTURA
            if zona is None and instance.requiere_cobertura and not sin_cobertura:
                raise serializers.ValidationError({'latitud': 'La nueva ubicación está fuera de cobertura.'})
            instance.zona_cobertura = zona
            if sin_cobertura and zona is not None:
                # Corrigieron el punto y ahora sí hay cobertura: pasa a OT
                instance.estado = Solicitud.Estado.EN_CURSO
                instance.save(update_fields=['zona_cobertura', 'estado', 'updated_at'])
                self.orden_generada = crear_orden(instance, self.context.get('usuario'))
            else:
                instance.save(update_fields=['zona_cobertura', 'updated_at'])
        orden = getattr(instance, 'orden', None)
        if orden and 'prioridad' in data and orden.prioridad != instance.prioridad:
            orden.prioridad = instance.prioridad
            orden.save(update_fields=['prioridad', 'updated_at'])
        despues = (instance.latitud, instance.longitud)
        if movida and orden and not getattr(self, 'orden_generada', None) and antes != despues:
            # La ubicación es la referencia para validar las fotos en campo: el cambio queda en el historial de la OT
            HistorialOT.objects.create(
                orden=orden, estado_anterior=orden.estado, estado_nuevo=orden.estado, usuario=self.context.get('usuario'),
                observacion=f'Ubicación corregida: {antes[0]:.6f}, {antes[1]:.6f} → {despues[0]:.6f}, {despues[1]:.6f}')
        return instance


def crear_orden(solicitud, usuario):
    orden = OrdenTrabajo.objects.create(solicitud=solicitud, tipo=solicitud.tipo, prioridad=solicitud.prioridad)
    HistorialOT.objects.create(orden=orden, estado_anterior='', estado_nuevo=orden.estado, usuario=usuario,
                               observacion=f'Generada desde la solicitud {solicitud.numero}')
    return orden


# ---------------- Vehículos y cuadrillas ----------------

class VehiculoEquipoSerializer(serializers.ModelSerializer):
    class Meta:
        model = VehiculoEquipo
        fields = ['id', 'nombre', 'cantidad', 'nota']
        read_only_fields = ['id']

    def validate_nombre(self, v):
        v = (v or '').strip()
        if not v:
            raise serializers.ValidationError('Indica el equipo.')
        return v

    def validate_cantidad(self, v):
        if v < 1:
            raise serializers.ValidationError('Mínimo 1.')
        return v


class VehiculoSerializer(serializers.ModelSerializer):
    """El equipamiento se envía completo: la lista recibida reemplaza a la anterior."""
    equipamiento = VehiculoEquipoSerializer(many=True, required=False)
    cuadrilla = serializers.SerializerMethodField()

    class Meta:
        model = Vehiculo
        fields = ['id', 'placa', 'descripcion', 'activo', 'observaciones', 'equipamiento', 'cuadrilla',
                  'created_at', 'updated_at']
        read_only_fields = ['created_at', 'updated_at']

    def get_cuadrilla(self, obj):
        c = next((c for c in obj.cuadrillas.all() if c.activo), None)
        return _cuadrilla(c)

    def validate_placa(self, v):
        v = ''.join((v or '').split()).upper()
        if not re.fullmatch(r'[0-9A-Z-]{5,15}', v):
            raise serializers.ValidationError('Placa no válida (ej: 2345ABC).')
        qs = Vehiculo.objects.filter(placa=v)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError('Ya existe un vehículo con esa placa.')
        return v

    def validate_descripcion(self, v):
        v = (v or '').strip()
        if not v:
            raise serializers.ValidationError('Describe el vehículo.')
        return v

    def validate_activo(self, v):
        if self.instance and not v and self.instance.cuadrillas.filter(activo=True).exists():
            raise serializers.ValidationError('El vehículo está asignado a una cuadrilla activa; quítaselo primero.')
        return v

    def _guardar_equipamiento(self, vehiculo, items):
        if items is None:
            return
        vehiculo.equipamiento.all().delete()
        VehiculoEquipo.objects.bulk_create([VehiculoEquipo(vehiculo=vehiculo, **i) for i in items])

    @transaction.atomic
    def create(self, data):
        items = data.pop('equipamiento', [])
        vehiculo = super().create(data)
        self._guardar_equipamiento(vehiculo, items)
        return vehiculo

    @transaction.atomic
    def update(self, instance, data):
        items = data.pop('equipamiento', None)
        vehiculo = super().update(instance, data)
        self._guardar_equipamiento(vehiculo, items)
        return vehiculo


class IntegranteSerializer(serializers.ModelSerializer):
    usuario = serializers.SerializerMethodField()

    class Meta:
        model = IntegranteCuadrilla
        fields = ['id', 'usuario', 'es_jefe', 'desde', 'hasta']

    def get_usuario(self, obj):
        u = obj.usuario
        return {'id': u.id, 'codigocotel': u.codigocotel, 'nombre': _nombre_usuario(u)}


class TecnicoSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    codigocotel = serializers.IntegerField()
    nombre = serializers.SerializerMethodField()
    rol = serializers.CharField(source='rol.nombre', default=None)

    def get_nombre(self, obj):
        return _nombre_usuario(obj)


class CuadrillaSerializer(serializers.ModelSerializer):
    almacen_nombre = serializers.CharField(source='almacen.nombre', read_only=True)
    vehiculo_info = serializers.SerializerMethodField()
    zonas_info = serializers.SerializerMethodField()
    integrantes = serializers.SerializerMethodField()
    ordenes_abiertas = serializers.IntegerField(source='n_abiertas', read_only=True, default=0)
    # Al crear: los técnicos van en el mismo formulario (el primero o el indicado es el jefe)
    tecnicos = serializers.ListField(child=serializers.IntegerField(), write_only=True, required=False)
    jefe = serializers.IntegerField(write_only=True, required=False, allow_null=True)

    class Meta:
        model = Cuadrilla
        fields = ['id', 'nombre', 'almacen', 'almacen_nombre', 'vehiculo', 'vehiculo_info', 'zonas', 'zonas_info',
                  'capacidad_diaria', 'activo', 'observaciones', 'integrantes', 'ordenes_abiertas',
                  'tecnicos', 'jefe', 'created_at', 'updated_at']
        read_only_fields = ['nombre', 'activo', 'created_at', 'updated_at']
        extra_kwargs = {'zonas': {'required': False}}

    def get_vehiculo_info(self, obj):
        v = obj.vehiculo
        return {'id': v.id, 'placa': v.placa, 'descripcion': v.descripcion} if v else None

    def get_zonas_info(self, obj):
        return [{'id': z.id, 'nombre': z.nombre, 'color': z.color} for z in obj.zonas.all()]

    def get_integrantes(self, obj):
        vigentes = [i for i in obj.integrantes.all() if i.hasta is None]
        return IntegranteSerializer(vigentes, many=True).data

    def validate(self, attrs):
        tecnicos = attrs.get('tecnicos')
        if self.instance:
            # Al editar, los técnicos se cambian con agregar / retirar
            attrs.pop('tecnicos', None)
            attrs.pop('jefe', None)
            return attrs
        tecnicos = list(dict.fromkeys(tecnicos or []))
        if not Cuadrilla.MIN_INTEGRANTES <= len(tecnicos) <= Cuadrilla.MAX_INTEGRANTES:
            raise serializers.ValidationError({'tecnicos': f'Elige de {Cuadrilla.MIN_INTEGRANTES} a {Cuadrilla.MAX_INTEGRANTES} técnicos.'})
        jefe = attrs.get('jefe') or tecnicos[0]
        if jefe not in tecnicos:
            raise serializers.ValidationError({'jefe': 'El jefe debe ser uno de los técnicos elegidos.'})
        attrs['tecnicos'], attrs['jefe'] = tecnicos, jefe
        return attrs

    @transaction.atomic
    def create(self, data):
        from usuarios.models import Usuario
        from .programacion import ErrorProgramacion, agregar_integrante
        tecnicos, jefe = data.pop('tecnicos'), data.pop('jefe')
        cuadrilla = super().create(data)
        usuarios = {u.id: u for u in Usuario.objects.filter(pk__in=tecnicos).select_related('rol')}
        try:
            for uid in tecnicos:
                if uid not in usuarios:
                    raise ErrorProgramacion('Alguno de los técnicos no existe.')
                agregar_integrante(cuadrilla, usuarios[uid], es_jefe=(uid == jefe))
        except ErrorProgramacion as e:
            raise serializers.ValidationError({'tecnicos': str(e)})
        return cuadrilla

    def validate_almacen(self, v):
        if not v.activo:
            raise serializers.ValidationError('Ese almacén está inactivo.')
        return v

    def validate_vehiculo(self, v):
        if not v:
            return v
        if not v.activo:
            raise serializers.ValidationError('Ese vehículo está inactivo.')
        otra = v.cuadrillas.filter(activo=True)
        if self.instance:
            otra = otra.exclude(pk=self.instance.pk)
        otra = otra.first()
        if otra:
            raise serializers.ValidationError(f'El vehículo ya está asignado a {otra}.')
        return v

    def validate_capacidad_diaria(self, v):
        if v is not None and v < 1:
            raise serializers.ValidationError('Mínimo 1 (o déjala vacía).')
        return v


# ---------------- Despacho y rendición ----------------

def _onu(m):
    return {'id': m.id, 'gpon_serial': m.gpon_serial, 'mac': m.mac_address, 'codigo': m.codigo_interno,
            'modelo': f'{m.modelo.marca.nombre} {m.modelo.nombre}' if m.modelo.marca_id else m.modelo.nombre,
            'tv': m.modelo.soporta_tv, 'telefonia': m.modelo.soporta_telefonia}


def _ot_corta(o):
    s = o.solicitud
    return {'id': o.id, 'numero': o.numero, 'estado': _opcion(OrdenTrabajo.Estado.choices, o.estado),
            'tipo': _opcion(Solicitud.Tipo.choices, o.tipo), 'cliente': f'{s.cliente.nombres} {s.cliente.apellidos}'.strip(),
            'direccion': s.direccion,
            'servicios': {'tv': o.tipo == 'INSTALACION' and bool(s.plan_tv_id),
                          'telefonia': o.tipo == 'INSTALACION' and bool(s.plan_telefonia_id)}}


def _granel(m):
    return {'id': m.id, 'modelo_id': m.modelo_id, 'nombre': m.modelo.nombre, 'lote': m.lote.numero_lote if m.lote_id else None,
            'unidad': m.modelo.unidad_medida.simbolo if m.modelo.unidad_medida_id else '', 'cantidad': float(m.cantidad)}


class DespachoSerializer(serializers.Serializer):
    """Solo lectura. (Serializer simple: con ModelSerializer, DRF reemplaza 'estado' por un campo oculto
    porque forma parte de la condición de la restricción única cuadrilla + fecha.)"""
    id = serializers.IntegerField(read_only=True)
    numero = serializers.CharField(read_only=True)
    fecha = serializers.DateField(read_only=True)
    observaciones = serializers.CharField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    rendido_at = serializers.DateTimeField(read_only=True)
    observaciones_rendicion = serializers.CharField(read_only=True)
    cuadrilla = serializers.SerializerMethodField()
    almacen = serializers.SerializerMethodField()
    estado = serializers.SerializerMethodField()
    entregado_por = serializers.SerializerMethodField()
    rendido_por = serializers.SerializerMethodField()
    equipos = serializers.SerializerMethodField()
    materiales = serializers.SerializerMethodField()
    recuperados = serializers.SerializerMethodField()
    ordenes = serializers.SerializerMethodField()

    def get_cuadrilla(self, obj):
        # Vehículo y técnicos de ese día: datos del vale de salida
        c = obj.cuadrilla
        v = c.vehiculo
        return {**_cuadrilla(c), 'vehiculo': {'placa': v.placa, 'descripcion': v.descripcion} if v else None,
                'integrantes': IntegranteSerializer(c.integrantes_en(obj.fecha).select_related('usuario'), many=True).data}

    def get_almacen(self, obj):
        return {'id': obj.almacen_id, 'nombre': obj.almacen.nombre}

    def get_estado(self, obj):
        return _opcion(Despacho.Estado.choices, obj.estado)

    def get_entregado_por(self, obj):
        return _nombre_usuario(obj.entregado_por)

    def get_rendido_por(self, obj):
        return _nombre_usuario(obj.rendido_por)

    def get_equipos(self, obj):
        return [{
            'id': e.id, 'onu': _onu(e.material),
            'orden': {'id': e.orden_id, 'numero': e.orden.numero} if e.orden_id else None,
            'resultado': _opcion(DespachoEquipo.Resultado.choices, e.resultado),
        } for e in obj.equipos.all()]

    def get_materiales(self, obj):
        return [{
            'id': x.id, 'material_id': x.material_id, 'nombre': x.material.modelo.nombre,
            'lote': x.material.lote.numero_lote if x.material.lote_id else None,
            'unidad': x.material.modelo.unidad_medida.simbolo if x.material.modelo.unidad_medida_id else '',
            'cantidad': float(x.cantidad), 'usada': None if x.usada is None else float(x.usada),
            'devuelta': None if x.devuelta is None else float(x.devuelta),
            'faltante': None if x.faltante is None else float(x.faltante),
            'consumos': [{'orden': c.orden_id, 'numero': c.orden.numero, 'cantidad': float(c.cantidad)} for c in x.consumos.all()],
        } for x in obj.materiales.all()]

    def get_recuperados(self, obj):
        return [{'id': r.id, 'serial': r.serial, 'orden': {'id': r.orden_id, 'numero': r.orden.numero},
                 'en_inventario': bool(r.material_id), 'observacion': r.observacion} for r in obj.recuperados.all()]

    def get_ordenes(self, obj):
        # OT de la cuadrilla en esa fecha (para la rendición: dónde se instaló cada ONU, consumo por OT, recuperados)
        if not self.context.get('con_ordenes'):
            return None
        from .despacho import ordenes_del_dia
        return [_ot_corta(o) for o in ordenes_del_dia(obj.cuadrilla, obj.fecha)]


class KitMaterialSerializer(serializers.ModelSerializer):
    tipo_nombre = serializers.CharField(source='get_tipo_display', read_only=True)
    condicion_nombre = serializers.CharField(source='get_condicion_display', read_only=True)
    modelo_nombre = serializers.CharField(source='modelo.nombre', read_only=True)
    unidad = serializers.SerializerMethodField()

    class Meta:
        model = KitMaterial
        fields = ['id', 'tipo', 'tipo_nombre', 'condicion', 'condicion_nombre', 'modelo', 'modelo_nombre', 'unidad', 'cantidad']

    def get_unidad(self, obj):
        return obj.modelo.unidad_medida.simbolo if obj.modelo.unidad_medida_id else ''

    def validate_modelo(self, v):
        if v.tipo_material.es_unico:
            raise serializers.ValidationError('Los equipos con serie (ONU) no van en el kit: se despachan escaneando cada uno.')
        return v

    def validate_cantidad(self, v):
        if v <= 0:
            raise serializers.ValidationError('Debe ser mayor a 0.')
        return v

    def validate(self, attrs):
        g = lambda k: attrs.get(k, getattr(self.instance, k, None))  # noqa: E731
        qs = KitMaterial.objects.filter(tipo=g('tipo'), condicion=g('condicion'), modelo=g('modelo'))
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError({'modelo': 'Ese material ya está en este kit.'})
        return attrs
