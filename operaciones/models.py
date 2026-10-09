# ======================================================
# operaciones/models.py
# Operación de campo: zonas de cobertura, solicitudes de clientes y
# órdenes de trabajo (OT).
#
#   Solicitud ──(con cobertura)──▶ OT PENDIENTE ──▶ PROGRAMADA ──▶ EN CAMPO ──▶ EJECUTADA ──▶ VERIFICADA ──▶ CERRADA
#             └─(sin cobertura)──▶ queda en SIN COBERTURA (demanda no atendida)
#
# El cliente y los planes se reutilizan de la app `contratos`.
# ======================================================
from django.conf import settings
from django.db import models
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
    fecha_cierre = models.DateTimeField(null=True, blank=True)
    observaciones = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'operaciones_orden_trabajo'
        ordering = ['-created_at']
        indexes = [models.Index(fields=['estado', '-created_at'])]
        verbose_name = 'Orden de trabajo'
        verbose_name_plural = 'Órdenes de trabajo'

    def __str__(self):
        return self.numero or 'OT'

    def save(self, *args, **kwargs):
        if not self.numero:
            self.numero = siguiente_numero(OrdenTrabajo, 'numero', 'OT')
        super().save(*args, **kwargs)

    def cambiar_estado(self, nuevo, usuario=None, observacion=''):
        anterior = self.estado
        self.estado = nuevo
        if nuevo in (self.Estado.CERRADA, self.Estado.ANULADA):
            self.fecha_cierre = timezone.now()
        self.save()
        HistorialOT.objects.create(orden=self, estado_anterior=anterior, estado_nuevo=nuevo, usuario=usuario, observacion=observacion)


class HistorialOT(models.Model):
    orden = models.ForeignKey(OrdenTrabajo, on_delete=models.CASCADE, related_name='historial')
    estado_anterior = models.CharField(max_length=15, blank=True)
    estado_nuevo = models.CharField(max_length=15)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+')
    observacion = models.TextField(blank=True)
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'operaciones_historial_ot'
        ordering = ['fecha', 'id']

