# ======================================================
# operaciones/models.py
# Operación de campo: zonas de cobertura, solicitudes de clientes y
# órdenes de trabajo (OT).
#
#   Solicitud ──(con cobertura)──▶ OT PENDIENTE ──▶ PROGRAMADA ──▶ EN CAMPO ──▶ EJECUTADA ──▶ VERIFICADA ──▶ CERRADA
#             └─(sin cobertura)──▶ queda en SIN COBERTURA (demanda no atendida)
#
# Las OT se programan a una cuadrilla (vehículo + 2 o 3 técnicos) para una fecha.
# El cliente y los planes se reutilizan de la app `contratos`.
# ======================================================
from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from . import geo


def siguiente_numero(modelo, campo, prefijo):
    """Correlativo por año: PREFIJO-2026-0001."""
    base = f"{prefijo}-{timezone.localdate().year}-"
    usados = modelo.objects.filter(**{f'{campo}__startswith': base}).values_list(campo, flat=True)
    mayor = max([int(n[len(base):]) for n in usados if n[len(base):].isdigit()] or [0])
    return f"{base}{mayor + 1:04d}"


class ZonaCobertura(models.Model):
    """Área (polígono GeoJSON) donde COTEL puede instalar fibra."""
    nombre = models.CharField(max_length=100, unique=True)
    color = models.CharField(max_length=7, default='#F97316', help_text='Color en el mapa (#RRGGBB)')
    almacen = models.ForeignKey(
        'almacenes.Almacen', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='zonas_cobertura', help_text='Almacén que atiende la zona',
    )
    geometria = models.JSONField(help_text='Geometría GeoJSON (Polygon o MultiPolygon)')
    activo = models.BooleanField(default=True)
    observaciones = models.TextField(blank=True)
    creado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'operaciones_zona_cobertura'
        ordering = ['nombre']
        verbose_name = 'Zona de cobertura'
        verbose_name_plural = 'Zonas de cobertura'

    def __str__(self):
        return self.nombre

    def contiene(self, lat, lng):
        return geo.contiene(self.geometria, float(lat), float(lng))

    @classmethod
    def zona_de(cls, lat, lng):
        """Primera zona activa que contiene el punto (o None)."""
        if lat is None or lng is None:
            return None
        for zona in cls.objects.filter(activo=True).order_by('nombre'):
            if zona.contiene(lat, lng):
                return zona
        return None


class PlanAdicional(models.Model):
    """
    Servicio que se suma al plan de internet: TV cable o telefonía.
    Incluye cierta cantidad de unidades (televisores / líneas); cada unidad más
    se cobra aparte, hasta un máximo.
    """
    class Tipo(models.TextChoices):
        TV = 'TV', 'TV cable'
        TELEFONIA = 'TELEFONIA', 'Telefonía'

    UNIDAD = {Tipo.TV: ('televisor', 'televisores'), Tipo.TELEFONIA: ('línea', 'líneas')}

    tipo = models.CharField(max_length=10, choices=Tipo.choices)
    nombre = models.CharField(max_length=100)
    precio_mensual = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    costo_instalacion = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    unidades_incluidas = models.PositiveSmallIntegerField(default=1)
    precio_unidad_extra = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    maximo_unidades = models.PositiveSmallIntegerField(default=1)
    descripcion = models.TextField(blank=True)
    activo = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'operaciones_plan_adicional'
        ordering = ['tipo', 'precio_mensual', 'nombre']
        unique_together = [('tipo', 'nombre')]
        verbose_name = 'Plan adicional'
        verbose_name_plural = 'Planes adicionales'

    def __str__(self):
        return f'{self.get_tipo_display()} · {self.nombre}'

    def unidad(self, n):
        singular, plural = self.UNIDAD[self.tipo]
        return f'{n} {singular if n == 1 else plural}'

    def precio(self, cantidad):
        """Mensual para `cantidad` unidades: precio base + extras sobre lo incluido."""
        extra = max(int(cantidad) - self.unidades_incluidas, 0)
        return self.precio_mensual + self.precio_unidad_extra * extra


def cotizar(plan, plan_tv=None, cantidad_tv=0, plan_telefonia=None, cantidad_lineas=0):
    """
    Monto referencial (no es facturación): desglose por concepto, total mensual y de instalación.
    """
    from decimal import Decimal
    lineas, mensual, instalacion = [], Decimal(0), Decimal(0)
    if plan:
        m, i = plan.precio_mensual or Decimal(0), plan.precio_instalacion or Decimal(0)
        vel = f' · {plan.velocidad_descarga} Mbps' if plan.velocidad_descarga else ''
        lineas.append({'concepto': f'Internet {plan.nombre}{vel}', 'mensual': float(m), 'instalacion': float(i)})
        mensual, instalacion = mensual + m, instalacion + i
    for adicional, cantidad in ((plan_tv, cantidad_tv), (plan_telefonia, cantidad_lineas)):
        if not adicional:
            continue
        m, i = adicional.precio(cantidad), adicional.costo_instalacion
        extra = max(int(cantidad) - adicional.unidades_incluidas, 0)
        detalle = f'{adicional.unidad(cantidad)}' + (f' ({adicional.unidades_incluidas} incluido(s) + {extra} extra)' if extra else '')
        lineas.append({'concepto': f'{adicional.get_tipo_display()} {adicional.nombre} · {detalle}', 'mensual': float(m), 'instalacion': float(i)})
        mensual, instalacion = mensual + m, instalacion + i
    return {'detalle': lineas, 'mensual': float(mensual), 'instalacion': float(instalacion)}


class Solicitud(models.Model):
    class Tipo(models.TextChoices):
        INSTALACION = 'INSTALACION', 'Instalación nueva'
        TRASLADO = 'TRASLADO', 'Traslado'
        REPARACION = 'REPARACION', 'Reparación / cambio de equipo'
        RETIRO = 'RETIRO', 'Retiro / baja'

    class Estado(models.TextChoices):
        EN_CURSO = 'EN_CURSO', 'En curso'
        SIN_COBERTURA = 'SIN_COBERTURA', 'Sin cobertura'
        ATENDIDA = 'ATENDIDA', 'Atendida'
        ANULADA = 'ANULADA', 'Anulada'

    class Prioridad(models.TextChoices):
        NORMAL = 'NORMAL', 'Normal'
        ALTA = 'ALTA', 'Alta'

    # Estos tipos necesitan que la ubicación esté dentro de una zona de cobertura
    TIPOS_CON_COBERTURA = (Tipo.INSTALACION, Tipo.TRASLADO)

    numero = models.CharField(max_length=20, unique=True, blank=True)
    tipo = models.CharField(max_length=15, choices=Tipo.choices)
    estado = models.CharField(max_length=15, choices=Estado.choices, default=Estado.EN_CURSO)
    prioridad = models.CharField(max_length=10, choices=Prioridad.choices, default=Prioridad.NORMAL)

    cliente = models.ForeignKey('contratos.Cliente', on_delete=models.PROTECT, related_name='solicitudes')
    plan = models.ForeignKey('contratos.PlanComercial', on_delete=models.PROTECT, null=True, blank=True, related_name='solicitudes')
    # Internet va siempre (es el plan); TV cable y telefonía son planes adicionales con cantidad
    plan_tv = models.ForeignKey(PlanAdicional, on_delete=models.PROTECT, null=True, blank=True, related_name='solicitudes_tv')
    cantidad_tv = models.PositiveSmallIntegerField(default=0)
    plan_telefonia = models.ForeignKey(PlanAdicional, on_delete=models.PROTECT, null=True, blank=True, related_name='solicitudes_telefonia')
    cantidad_lineas = models.PositiveSmallIntegerField(default=0)
    # Lo que se le informó al cliente en ese momento (referencial, no es facturación)
    monto_mensual_ref = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    monto_instalacion_ref = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    telefono_contacto = models.CharField(max_length=20, blank=True)

    # Ubicación del trabajo (para traslado: la dirección NUEVA)
    direccion = models.CharField(max_length=255)
    zona_referencia = models.CharField(max_length=100, blank=True, help_text='Barrio / zona escrita por el cliente')
    referencia = models.TextField(blank=True, help_text='Cómo llegar: color de la casa, tienda cercana…')
    latitud = models.DecimalField(max_digits=9, decimal_places=6)
    longitud = models.DecimalField(max_digits=9, decimal_places=6)
    zona_cobertura = models.ForeignKey(ZonaCobertura, on_delete=models.SET_NULL, null=True, blank=True, related_name='solicitudes')

    observaciones = models.TextField(blank=True)
    motivo_anulacion = models.TextField(blank=True)
    creado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='solicitudes_registradas')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'operaciones_solicitud'
        ordering = ['-created_at']
        indexes = [models.Index(fields=['estado', '-created_at']), models.Index(fields=['tipo'])]

    def __str__(self):
        return self.numero or 'Solicitud'

    def save(self, *args, **kwargs):
        if not self.numero:
            self.numero = siguiente_numero(Solicitud, 'numero', 'SOL')
        super().save(*args, **kwargs)

    @property
    def servicios(self):
        """['Internet', 'Telefonía', 'TV cable'] según lo solicitado (solo instalaciones)."""
        if self.tipo != self.Tipo.INSTALACION:
            return []
        lista = ['Internet']
        if self.plan_tv_id:
            lista.append(f'TV ({self.plan_tv.unidad(self.cantidad_tv)})')
        if self.plan_telefonia_id:
            lista.append(f'Telefonía ({self.plan_telefonia.unidad(self.cantidad_lineas)})')
        return lista

    @property
    def requiere_cobertura(self):
        return self.tipo in self.TIPOS_CON_COBERTURA


class Vehiculo(models.Model):
    """Vehículo de una cuadrilla. Su equipamiento fijo es una lista de control (no inventario)."""
    placa = models.CharField(max_length=15, unique=True)
    descripcion = models.CharField(max_length=120, help_text='Ej: Camioneta Toyota blanca')
    activo = models.BooleanField(default=True)
    observaciones = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'operaciones_vehiculo'
        ordering = ['placa']
        verbose_name = 'Vehículo'
        verbose_name_plural = 'Vehículos'

    def __str__(self):
        return f'{self.placa} · {self.descripcion}'

    def save(self, *args, **kwargs):
        self.placa = ''.join((self.placa or '').split()).upper()
        super().save(*args, **kwargs)


class VehiculoEquipo(models.Model):
    """Herramienta o equipo que va siempre en el vehículo (escalera, empalmadora, medidor de potencia…)."""
    vehiculo = models.ForeignKey(Vehiculo, on_delete=models.CASCADE, related_name='equipamiento')
    nombre = models.CharField(max_length=100)
    cantidad = models.PositiveSmallIntegerField(default=1)
    nota = models.CharField(max_length=200, blank=True)

    class Meta:
        db_table = 'operaciones_vehiculo_equipo'
        ordering = ['id']

    def __str__(self):
        return f'{self.nombre} ×{self.cantidad}'


class Cuadrilla(models.Model):
    """Equipo de campo: un vehículo y de 2 a 3 técnicos (uno es el jefe), atendido por un almacén."""
    MIN_INTEGRANTES = 2
    MAX_INTEGRANTES = 3

    # Código automático CUA-01, CUA-02… (no se escribe a mano)
    nombre = models.CharField(max_length=60, unique=True, blank=True)
    almacen = models.ForeignKey('almacenes.Almacen', on_delete=models.PROTECT, related_name='cuadrillas',
                                help_text='Almacén del que sale su material')
    vehiculo = models.ForeignKey(Vehiculo, on_delete=models.PROTECT, null=True, blank=True, related_name='cuadrillas')
    zonas = models.ManyToManyField(ZonaCobertura, blank=True, related_name='cuadrillas',
                                   help_text='Zonas de cobertura que atiende de preferencia')
    capacidad_diaria = models.PositiveSmallIntegerField(null=True, blank=True,
                                                        help_text='OT por día (solo avisa al pasarla)')
    activo = models.BooleanField(default=True)
    observaciones = models.TextField(blank=True)
    creado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'operaciones_cuadrilla'
        ordering = ['nombre']
        constraints = [
            # Un vehículo solo sale con una cuadrilla activa
            models.UniqueConstraint(fields=['vehiculo'], condition=Q(activo=True), name='uq_cuadrilla_vehiculo_activa'),
        ]

    def __str__(self):
        return self.nombre

    def save(self, *args, **kwargs):
        if not self.nombre:
            usados = Cuadrilla.objects.filter(nombre__startswith='CUA-').values_list('nombre', flat=True)
            mayor = max([int(n[4:]) for n in usados if n[4:].isdigit()] or [0])
            self.nombre = f'CUA-{mayor + 1:02d}'
        super().save(*args, **kwargs)

    def vigentes(self):
        """Integrantes actuales (sin fecha de salida)."""
        return self.integrantes.filter(hasta__isnull=True)

    def integrantes_en(self, fecha):
        """Quiénes formaban la cuadrilla en esa fecha (para la hoja del día y la responsabilidad)."""
        return self.integrantes.filter(desde__lte=fecha).filter(Q(hasta__isnull=True) | Q(hasta__gte=fecha))


class IntegranteCuadrilla(models.Model):
    """Técnico en una cuadrilla desde/hasta una fecha. `hasta` vacío = integrante vigente."""
    cuadrilla = models.ForeignKey(Cuadrilla, on_delete=models.CASCADE, related_name='integrantes')
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='cuadrillas_integradas')
    es_jefe = models.BooleanField(default=False)
    desde = models.DateField(default=timezone.localdate)
    hasta = models.DateField(null=True, blank=True)

    class Meta:
        db_table = 'operaciones_integrante_cuadrilla'
        ordering = ['-es_jefe', 'desde', 'id']
        constraints = [
            # Un técnico solo está en una cuadrilla a la vez
            models.UniqueConstraint(fields=['usuario'], condition=Q(hasta__isnull=True), name='uq_integrante_una_cuadrilla'),
            # Un solo jefe vigente por cuadrilla
            models.UniqueConstraint(fields=['cuadrilla'], condition=Q(es_jefe=True, hasta__isnull=True), name='uq_cuadrilla_un_jefe'),
        ]

    def __str__(self):
        return f'{self.usuario} en {self.cuadrilla}'


class OrdenTrabajo(models.Model):
    class Estado(models.TextChoices):
        PENDIENTE = 'PENDIENTE', 'Pendiente'
        PROGRAMADA = 'PROGRAMADA', 'Programada'
        EN_CAMPO = 'EN_CAMPO', 'En campo'
        EJECUTADA = 'EJECUTADA', 'Ejecutada'
        NO_EJECUTADA = 'NO_EJECUTADA', 'No ejecutada'
        VERIFICADA = 'VERIFICADA', 'Verificada'
        CERRADA = 'CERRADA', 'Cerrada'
        ANULADA = 'ANULADA', 'Anulada'

    ABIERTAS = (Estado.PENDIENTE, Estado.PROGRAMADA, Estado.EN_CAMPO, Estado.EJECUTADA, Estado.NO_EJECUTADA, Estado.VERIFICADA)
    ANULABLES = (Estado.PENDIENTE, Estado.PROGRAMADA, Estado.NO_EJECUTADA)

    numero = models.CharField(max_length=20, unique=True, blank=True)
    solicitud = models.OneToOneField(Solicitud, on_delete=models.PROTECT, related_name='orden')
    tipo = models.CharField(max_length=15, choices=Solicitud.Tipo.choices)
    estado = models.CharField(max_length=15, choices=Estado.choices, default=Estado.PENDIENTE)
    prioridad = models.CharField(max_length=10, choices=Solicitud.Prioridad.choices, default=Solicitud.Prioridad.NORMAL)
    fecha_programada = models.DateField(null=True, blank=True)
    cuadrilla = models.ForeignKey(Cuadrilla, on_delete=models.PROTECT, null=True, blank=True, related_name='ordenes')
    orden_visita = models.PositiveSmallIntegerField(null=True, blank=True, help_text='Orden en la hoja del día')
    fecha_cierre = models.DateTimeField(null=True, blank=True)
    observaciones = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'operaciones_orden_trabajo'
        ordering = ['-created_at']
        indexes = [models.Index(fields=['estado', '-created_at']),
                   models.Index(fields=['cuadrilla', 'fecha_programada'])]
        verbose_name = 'Orden de trabajo'
        verbose_name_plural = 'Órdenes de trabajo'

    def __str__(self):
        return self.numero or 'OT'

    def save(self, *args, **kwargs):
        if not self.numero:
            self.numero = siguiente_numero(OrdenTrabajo, 'numero', 'OT')
        super().save(*args, **kwargs)

    def cambiar_estado(self, nuevo, usuario=None, observacion='', **historial):
        """`historial`: cuadrilla_anterior/nueva y fecha_anterior/nueva cuando cambia la programación."""
        anterior = self.estado
        self.estado = nuevo
        if nuevo in (self.Estado.CERRADA, self.Estado.ANULADA):
            self.fecha_cierre = timezone.now()
        self.save()
        HistorialOT.objects.create(orden=self, estado_anterior=anterior, estado_nuevo=nuevo, usuario=usuario,
                                   observacion=observacion, **historial)


class HistorialOT(models.Model):
    orden = models.ForeignKey(OrdenTrabajo, on_delete=models.CASCADE, related_name='historial')
    estado_anterior = models.CharField(max_length=15, blank=True)
    estado_nuevo = models.CharField(max_length=15)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+')
    observacion = models.TextField(blank=True)
    # Cambios de programación (asignar, reprogramar, desasignar)
    cuadrilla_anterior = models.ForeignKey(Cuadrilla, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    cuadrilla_nueva = models.ForeignKey(Cuadrilla, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    fecha_anterior = models.DateField(null=True, blank=True)
    fecha_nueva = models.DateField(null=True, blank=True)
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'operaciones_historial_ot'
        ordering = ['fecha', 'id']



# ---------------- Despacho y rendición diaria ----------------

class Despacho(models.Model):
    """
    Lo que el almacén entrega a una cuadrilla para su día de trabajo: las ONU (cada una por
    su serie, quedan a cargo de la cuadrilla) y el material por cantidad. La ONU NO se ata a
    una OT al salir: se asocia cuando se instala. Al volver, la rendición indica en qué OT se
    instaló cada ONU, qué material usó cada OT, qué se devuelve, qué falta (a cargo de la
    cuadrilla) y qué equipos se recuperaron de los clientes (retiros / cambios).
    """
    class Estado(models.TextChoices):
        ENTREGADO = 'ENTREGADO', 'Entregado'
        RENDIDO = 'RENDIDO', 'Rendido'
        ANULADO = 'ANULADO', 'Anulado'

    numero = models.CharField(max_length=20, unique=True, blank=True)
    cuadrilla = models.ForeignKey(Cuadrilla, on_delete=models.PROTECT, related_name='despachos')
    fecha = models.DateField()
    almacen = models.ForeignKey('almacenes.Almacen', on_delete=models.PROTECT, related_name='despachos')
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.ENTREGADO)
    observaciones = models.TextField(blank=True)
    entregado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    rendido_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    rendido_at = models.DateTimeField(null=True, blank=True)
    observaciones_rendicion = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'operaciones_despacho'
        ordering = ['-fecha', 'cuadrilla__nombre']
        constraints = [
            # Un despacho vigente por cuadrilla y día
            models.UniqueConstraint(fields=['cuadrilla', 'fecha'], condition=~Q(estado='ANULADO'), name='uq_despacho_cuadrilla_dia'),
        ]

    def __str__(self):
        return self.numero or 'Despacho'

    def save(self, *args, **kwargs):
        if not self.numero:
            self.numero = siguiente_numero(Despacho, 'numero', 'DES')
        super().save(*args, **kwargs)


class DespachoEquipo(models.Model):
    """Una ONU entregada a la cuadrilla. `orden` = OT donde se instaló (se registra al instalarla)."""
    class Resultado(models.TextChoices):
        PENDIENTE = 'PENDIENTE', 'Pendiente'
        INSTALADO = 'INSTALADO', 'Instalado'
        DEVUELTO = 'DEVUELTO', 'Devuelto'
        FALTANTE = 'FALTANTE', 'Faltante'

    despacho = models.ForeignKey(Despacho, on_delete=models.CASCADE, related_name='equipos')
    material = models.ForeignKey('almacenes.Material', on_delete=models.PROTECT, related_name='despachos_equipo')
    orden = models.ForeignKey(OrdenTrabajo, on_delete=models.PROTECT, null=True, blank=True, related_name='equipos_despachados')
    resultado = models.CharField(max_length=10, choices=Resultado.choices, default=Resultado.PENDIENTE)

    class Meta:
        db_table = 'operaciones_despacho_equipo'
        ordering = ['id']
        constraints = [models.UniqueConstraint(fields=['despacho', 'material'], name='uq_despacho_equipo')]


class DespachoMaterial(models.Model):
    """Material por cantidad (drop, rosetas, conectores…) entregado a la cuadrilla."""
    despacho = models.ForeignKey(Despacho, on_delete=models.CASCADE, related_name='materiales')
    material = models.ForeignKey('almacenes.Material', on_delete=models.PROTECT, related_name='despachos_material',
                                 help_text='Registro del almacén del que salió')
    cantidad = models.DecimalField(max_digits=10, decimal_places=2)
    usada = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    devuelta = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    class Meta:
        db_table = 'operaciones_despacho_material'
        ordering = ['id']
        constraints = [models.UniqueConstraint(fields=['despacho', 'material'], name='uq_despacho_material')]

    @property
    def faltante(self):
        if self.usada is None or self.devuelta is None:
            return None
        return self.cantidad - self.usada - self.devuelta


class ConsumoOT(models.Model):
    """Material por cantidad usado en una OT (base del consumo real para el EOQ)."""
    despacho_material = models.ForeignKey(DespachoMaterial, on_delete=models.CASCADE, related_name='consumos')
    orden = models.ForeignKey(OrdenTrabajo, on_delete=models.PROTECT, related_name='consumos')
    cantidad = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        db_table = 'operaciones_consumo_ot'
        ordering = ['id']
        constraints = [models.UniqueConstraint(fields=['despacho_material', 'orden'], name='uq_consumo_material_ot')]


class EquipoRecuperado(models.Model):
    """Equipo que la cuadrilla trae de un cliente (retiro o cambio de equipo). Vuelve al almacén para laboratorio."""
    despacho = models.ForeignKey(Despacho, on_delete=models.CASCADE, related_name='recuperados')
    orden = models.ForeignKey(OrdenTrabajo, on_delete=models.PROTECT, related_name='equipos_recuperados')
    serial = models.CharField(max_length=100, help_text='GPON SN o MAC tal como se leyó')
    material = models.ForeignKey('almacenes.Material', on_delete=models.SET_NULL, null=True, blank=True, related_name='recuperaciones',
                                 help_text='Equipo del inventario (vacío si no estaba registrado: se ingresa por reingreso)')
    observacion = models.CharField(max_length=200, blank=True)

    class Meta:
        db_table = 'operaciones_equipo_recuperado'
        ordering = ['id']


class KitMaterial(models.Model):
    """
    Material estándar por tipo de trabajo, para sugerir el despacho del día.
    condicion: SIEMPRE, o solo si la OT incluye TV cable / telefonía.
    """
    class Condicion(models.TextChoices):
        SIEMPRE = 'SIEMPRE', 'Siempre'
        TV = 'TV', 'Si incluye TV cable'
        TELEFONIA = 'TELEFONIA', 'Si incluye telefonía'

    tipo = models.CharField(max_length=15, choices=Solicitud.Tipo.choices)
    condicion = models.CharField(max_length=10, choices=Condicion.choices, default=Condicion.SIEMPRE)
    modelo = models.ForeignKey('almacenes.Modelo', on_delete=models.PROTECT, related_name='kits')
    cantidad = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        db_table = 'operaciones_kit_material'
        ordering = ['tipo', 'condicion', 'id']
        constraints = [models.UniqueConstraint(fields=['tipo', 'condicion', 'modelo'], name='uq_kit_material')]


# ---------------- App de campo: evidencias y reporte del técnico ----------------

def _ruta_evidencia(instance, filename):
    ext = (filename.rsplit('.', 1)[-1] if '.' in filename else 'jpg').lower()[:5]
    return f'evidencias/{timezone.localdate():%Y/%m}/{instance.orden.numero}-{instance.sha256[:12]}.{ext}'


class EvidenciaOT(models.Model):
    """
    Foto tomada por el técnico desde la app (cámara en vivo, sin galería). Se guarda con la hora
    del SERVIDOR, el GPS del teléfono, SHA-256 (integridad del archivo) y pHash (para detectar fotos
    iguales o casi iguales). Las rechazadas también se guardan: son el registro de los intentos.
    """
    class Tipo(models.TextChoices):
        ONU = 'ONU', 'Foto de la ONU'
        ADICIONAL = 'ADICIONAL', 'Foto adicional'

    class Estado(models.TextChoices):
        ACEPTADA = 'ACEPTADA', 'Aceptada'
        RECHAZADA = 'RECHAZADA', 'Rechazada'
        OBSERVADA = 'OBSERVADA', 'Observada'

    class Cnn(models.TextChoices):
        PENDIENTE = 'PENDIENTE', 'Pendiente'
        DETECTADA = 'DETECTADA', 'ONU detectada'
        NO_DETECTADA = 'NO_DETECTADA', 'ONU no detectada'
        NO_APLICA = 'NO_APLICA', 'No aplica'

    orden = models.ForeignKey(OrdenTrabajo, on_delete=models.PROTECT, related_name='evidencias')
    tipo = models.CharField(max_length=10, choices=Tipo.choices, default=Tipo.ONU)
    imagen = models.FileField(upload_to=_ruta_evidencia)
    sha256 = models.CharField(max_length=64, db_index=True)
    phash = models.CharField(max_length=16, help_text='Hash perceptual (64 bits en hexadecimal)')
    latitud = models.DecimalField(max_digits=9, decimal_places=6)
    longitud = models.DecimalField(max_digits=9, decimal_places=6)
    precision_m = models.FloatField(null=True, blank=True, help_text='Precisión del GPS informada por el teléfono')
    distancia_m = models.FloatField(help_text='Distancia (Haversine) al domicilio de la solicitud')
    estado = models.CharField(max_length=10, choices=Estado.choices)
    motivo = models.CharField(max_length=200, blank=True, help_text='Por qué se rechazó u observó')
    cnn = models.CharField(max_length=12, choices=Cnn.choices, default=Cnn.PENDIENTE)
    cnn_confianza = models.FloatField(null=True, blank=True)
    tomada_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'operaciones_evidencia_ot'
        ordering = ['created_at', 'id']


class ReporteCampo(models.Model):
    """
    Lo que informa el técnico al marcar la OT como ejecutada: la ONU que instaló (de las que la
    cuadrilla tiene a cargo), el material usado y el equipo recuperado. Prellena la rendición.
    """
    orden = models.OneToOneField(OrdenTrabajo, on_delete=models.CASCADE, related_name='reporte_campo')
    despacho_equipo = models.ForeignKey(DespachoEquipo, on_delete=models.SET_NULL, null=True, blank=True, related_name='reportes',
                                        help_text='ONU instalada')
    materiales = models.JSONField(default=list, blank=True, help_text='[{"despacho_material": id, "cantidad": "12.5"}]')
    serial_recuperado = models.CharField(max_length=100, blank=True, help_text='Equipo retirado del cliente (retiro o cambio)')
    observaciones = models.TextField(blank=True)
    latitud = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitud = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'operaciones_reporte_campo'


# ---------------- Inventario: parámetros del modelo EOQ ----------------

class ParametroEOQ(models.Model):
    """
    Costos y tiempos para el modelo EOQ y el punto de reorden.
    `modelo` vacío = valores por defecto para las ONU (datos de ejemplo de la tesis, editables).
    La demanda D se calcula del consumo registrado; `demanda_estimada` se usa solo si aún no hay consumo.
    """
    modelo = models.OneToOneField('almacenes.Modelo', on_delete=models.CASCADE, null=True, blank=True, related_name='parametro_eoq')
    costo_pedido = models.DecimalField(max_digits=10, decimal_places=2, help_text='S: costo de hacer un pedido (Bs)')
    costo_mantener = models.DecimalField(max_digits=10, decimal_places=2, help_text='H: costo de mantener una unidad un año (Bs)')
    tiempo_entrega = models.PositiveSmallIntegerField(help_text='L: días que tarda el proveedor')
    demanda_estimada = models.PositiveIntegerField(null=True, blank=True, help_text='D estimada (unidades/año) si no hay consumo')
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')

    class Meta:
        db_table = 'operaciones_parametro_eoq'
        constraints = [models.UniqueConstraint(fields=['modelo'], condition=Q(modelo__isnull=True), name='uq_parametro_eoq_defecto')]
