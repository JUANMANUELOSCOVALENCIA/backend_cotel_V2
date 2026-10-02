# ======================================================
# apps/almacenes/models.py - COMPLETO SIN TEXTCHOICES
# Todos los choices ahora son modelos en base de datos
# ======================================================

from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType
import re


# ========== MODELOS BASE PARA CHOICES ==========

class TipoIngreso(models.Model):
    """Tipos de ingreso de lotes"""
    codigo = models.CharField(max_length=20, unique=True)
    nombre = models.CharField(max_length=50)
    descripcion = models.TextField(blank=True)
    activo = models.BooleanField(default=True)
    orden = models.PositiveIntegerField(default=0, help_text="Orden de visualización")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'almacenes_tipo_ingreso'
        verbose_name = 'Tipo de Ingreso'
        verbose_name_plural = 'Tipos de Ingreso'
        ordering = ['orden', 'nombre']

    def __str__(self):
        return self.nombre


class EstadoLote(models.Model):
    """Estados de lotes"""
    codigo = models.CharField(max_length=30, unique=True)
    nombre = models.CharField(max_length=50)
    descripcion = models.TextField(blank=True)
    color = models.CharField(max_length=7, default='#6B7280', help_text="Color hex para UI")
    es_final = models.BooleanField(default=False, help_text="Indica si es un estado final")
    activo = models.BooleanField(default=True)
    orden = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'almacenes_estado_lote'
        verbose_name = 'Estado de Lote'
        verbose_name_plural = 'Estados de Lote'
        ordering = ['orden', 'nombre']

    def __str__(self):
        return self.nombre


class EstadoTraspaso(models.Model):
    """Estados de traspasos"""
    codigo = models.CharField(max_length=20, unique=True)
    nombre = models.CharField(max_length=50)
    descripcion = models.TextField(blank=True)
    color = models.CharField(max_length=7, default='#6B7280')
    es_final = models.BooleanField(default=False)
    activo = models.BooleanField(default=True)
    orden = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'almacenes_estado_traspaso'
        verbose_name = 'Estado de Traspaso'
        verbose_name_plural = 'Estados de Traspaso'
        ordering = ['orden', 'nombre']

    def __str__(self):
        return self.nombre


class TipoMaterial(models.Model):
    """Tipos de materiales"""
    codigo = models.CharField(max_length=20, unique=True)
    nombre = models.CharField(max_length=100)
    descripcion = models.TextField(blank=True)
    unidad_medida_default = models.ForeignKey(
        'UnidadMedida',
        on_delete=models.CASCADE,
        help_text="Unidad de medida por defecto"
    )
    requiere_inspeccion_inicial = models.BooleanField(default=False)
    es_unico = models.BooleanField(
        default=False,
        help_text="True para equipos únicos (ONU), False para materiales por cantidad"
    )
    activo = models.BooleanField(default=True)
    orden = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        'usuarios.Usuario',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='tipos_material_creados'
    )

    class Meta:
        db_table = 'almacenes_tipo_material'
        verbose_name = 'Tipo de Material'
        verbose_name_plural = 'Tipos de Material'
        ordering = ['orden', 'nombre']

    def __str__(self):
        return f"{self.codigo} - {self.nombre}"


class UnidadMedida(models.Model):
    """Unidades de medida"""
    codigo = models.CharField(max_length=15, unique=True)
    nombre = models.CharField(max_length=50)
    simbolo = models.CharField(max_length=10, help_text="Símbolo de la unidad (m, kg, pza, etc.)")
    descripcion = models.TextField(blank=True)
    activo = models.BooleanField(default=True)
    orden = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'almacenes_unidad_medida'
        verbose_name = 'Unidad de Medida'
        verbose_name_plural = 'Unidades de Medida'
        ordering = ['orden', 'nombre']

    def __str__(self):
        return f"{self.nombre} ({self.simbolo})"


class EstadoMaterialONU(models.Model):
    """Estados específicos para equipos ONU"""
    codigo = models.CharField(max_length=30, unique=True)
    nombre = models.CharField(max_length=50)
    descripcion = models.TextField(blank=True)
    color = models.CharField(max_length=7, default='#6B7280')
    permite_asignacion = models.BooleanField(default=False, help_text="Si permite asignar a servicios")
    permite_traspaso = models.BooleanField(default=True, help_text="Si permite traspasos")
    activo = models.BooleanField(default=True)
    orden = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'almacenes_estado_material_onu'
        verbose_name = 'Estado de Material ONU'
        verbose_name_plural = 'Estados de Material ONU'
        ordering = ['orden', 'nombre']

    def __str__(self):
        return self.nombre


class EstadoMaterialGeneral(models.Model):
    """Estados para materiales generales (no únicos)"""
    codigo = models.CharField(max_length=25, unique=True)
    nombre = models.CharField(max_length=50)
    descripcion = models.TextField(blank=True)
    color = models.CharField(max_length=7, default='#6B7280')
    permite_consumo = models.BooleanField(default=False, help_text="Si permite consumir en servicios")
    permite_traspaso = models.BooleanField(default=True)
    activo = models.BooleanField(default=True)
    orden = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'almacenes_estado_material_general'
        verbose_name = 'Estado de Material General'
        verbose_name_plural = 'Estados de Material General'
        ordering = ['orden', 'nombre']

    def __str__(self):
        return self.nombre


class TipoAlmacen(models.Model):
    """Tipos de almacén"""
    codigo = models.CharField(max_length=20, unique=True)
    nombre = models.CharField(max_length=50)
    descripcion = models.TextField(blank=True)
    activo = models.BooleanField(default=True)
    orden = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'almacenes_tipo_almacen'
        verbose_name = 'Tipo de Almacén'
        verbose_name_plural = 'Tipos de Almacén'
        ordering = ['orden', 'nombre']

    def __str__(self):
        return self.nombre

class SectorSolicitante(models.Model):
    """Sectores que solicitan materiales/equipos - Versión simplificada"""
    nombre = models.CharField(max_length=100, unique=True)
    activo = models.BooleanField(default=True)
    orden = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'almacenes_sector_solicitante'
        verbose_name = 'Sector Solicitante'
        verbose_name_plural = 'Sectores Solicitantes'
        ordering = ['orden', 'nombre']

    def __str__(self):
        return self.nombre


# ========== MODELOS PRINCIPALES ==========

class Almacen(models.Model):
    """Modelo para gestión de almacenes regionales"""
    codigo = models.CharField(max_length=10, unique=True, help_text="Código único del almacén")
    nombre = models.CharField(max_length=100, help_text="Nombre del almacén")
    ciudad = models.CharField(max_length=50, help_text="Ciudad donde se ubica")
    tipo = models.ForeignKey(
        TipoAlmacen,
        on_delete=models.CASCADE,
        help_text="Tipo de almacén"
    )
    direccion = models.TextField(blank=True, help_text="Dirección física")
    es_principal = models.BooleanField(default=False, help_text="Indica si es el almacén principal")

    # NUEVO: Encargado opcional
    encargado = models.ForeignKey(
        'usuarios.Usuario',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='almacenes_a_cargo',
        help_text="Encargado del almacén (opcional)"
    )

    # NUEVO: Campo para código COTEL
    codigo_cotel_encargado = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        help_text="Código COTEL del encargado (se buscará automáticamente)"
    )

    activo = models.BooleanField(default=True)
    observaciones = models.TextField(blank=True)

    # Auditoría
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        'usuarios.Usuario',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='almacenes_creados'
    )

    class Meta:
        db_table = 'almacenes_almacen'
        verbose_name = 'Almacén'
        verbose_name_plural = 'Almacenes'

    def __str__(self):
        return f"{self.codigo} - {self.nombre}"

    def clean(self):
        if self.es_principal:
            otros_principales = Almacen.objects.filter(es_principal=True).exclude(pk=self.pk)
            if otros_principales.exists():
                raise ValidationError("Solo puede existir un almacén principal")

        # Validar código COTEL si se proporciona
        if self.codigo_cotel_encargado:
            try:
                from usuarios.models import Usuario
                encargado = Usuario.objects.get(codigocotel=self.codigo_cotel_encargado)
                self.encargado = encargado
            except Usuario.DoesNotExist:
                raise ValidationError(f"No se encontró usuario con código COTEL: {self.codigo_cotel_encargado}")

    def save(self, *args, **kwargs):
        # El encargado siempre sigue al código COTEL: si cambia el código cambia la persona,
        # y si se borra el código el almacén queda sin encargado.
        from usuarios.models import Usuario
        codigo = (self.codigo_cotel_encargado or '').strip()
        self.codigo_cotel_encargado = codigo or None
        if not codigo:
            self.encargado = None
        elif not self.encargado or str(self.encargado.codigocotel) != codigo:
            self.encargado = Usuario.objects.filter(codigocotel=codigo).first() if codigo.isdigit() else None

        super().save(*args, **kwargs)

    @property
    def encargado_info(self):
        """Información del encargado para la API"""
        if self.encargado:
            return {
                'id': self.encargado.id,
                'codigo_cotel': self.encargado.codigocotel,
                'nombre_completo': self.encargado.nombre_completo,
                'rol': self.encargado.rol.nombre if self.encargado.rol_id else None,
            }
        return None

    @property
    def total_materiales(self):
        return self.material_set.count()

    @property
    def materiales_disponibles(self):
        # Buscar por estados que permiten asignación/consumo
        onu_disponibles = self.material_set.filter(
            tipo_material__es_unico=True,
            estado_onu__permite_asignacion=True
        ).count()

        general_disponibles = self.material_set.filter(
            tipo_material__es_unico=False,
            estado_general__permite_consumo=True
        ).count()

        return onu_disponibles + general_disponibles


class Proveedor(models.Model):
    """Modelo para gestión de proveedores"""
    codigo = models.CharField(max_length=20, blank=True, help_text="Código interno del proveedor")
    nombre_comercial = models.CharField(max_length=100, unique=True, help_text="Nombre comercial del proveedor")
    razon_social = models.CharField(max_length=150, blank=True)
    contacto_principal = models.CharField(max_length=100, blank=True)
    telefono = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    activo = models.BooleanField(default=True)

    # Auditoría
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        'usuarios.Usuario',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='proveedores_creados'
    )

    class Meta:
        db_table = 'almacenes_proveedor'
        verbose_name = 'Proveedor'
        verbose_name_plural = 'Proveedores'

    def __str__(self):
        return self.nombre_comercial


# ========== MODELOS EXISTENTES ACTUALIZADOS ==========

class Marca(models.Model):
    nombre = models.CharField(max_length=100, unique=True)
    descripcion = models.TextField(blank=True)
    activo = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.nombre

    class Meta:
        db_table = 'almacenes_marca'

class Componente(models.Model):
    nombre = models.CharField(max_length=100, unique=True)
    descripcion = models.TextField(blank=True)
    activo = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.nombre

    class Meta:
        db_table = 'almacenes_componente'

# Pruebas de laboratorio para equipos ONU: (campo en InspeccionLaboratorio, nombre visible, código de falla)
PRUEBAS_LABORATORIO = [
    ('serie_logica_ok', 'Serie lógica', 'SERIE_LOGICA_DEFECTUOSA'),
    ('puerto_ethernet_ok', 'Puerto Ethernet', 'PUERTO_ETHERNET_DEFECTUOSO'),
    ('puerto_lan_ok', 'Puertos LAN', 'PUERTO_LAN_DEFECTUOSO'),
    ('wifi_24_ok', 'WiFi 2.4 GHz', 'WIFI_24_DEFECTUOSO'),
    ('wifi_5_ok', 'WiFi 5 GHz', 'WIFI_5_DEFECTUOSO'),
    ('puerto_catv_ok', 'Puerto CATV', 'PUERTO_CATV_DEFECTUOSO'),
    ('puerto_telefonia_rf_ok', 'Telefonía (POTS)', 'PUERTO_TELEFONIA_RF_DEFECTUOSO'),
    ('otros_ok', 'Otras pruebas', 'OTROS_DEFECTUOSOS'),
]
CAMPOS_PRUEBA = [c for c, _, _ in PRUEBAS_LABORATORIO]


class Modelo(models.Model):
    marca = models.ForeignKey(Marca, on_delete=models.CASCADE)
    nombre = models.CharField(max_length=100)
    codigo_modelo = models.IntegerField(unique=True)
    descripcion = models.TextField(blank=True)
    activo = models.BooleanField(default=True)

    # NUEVO: ForeignKey a TipoMaterial
    tipo_material = models.ForeignKey(
        TipoMaterial,
        on_delete=models.CASCADE,
        help_text="Tipo de material que representa este modelo"
    )

    # NUEVO: ForeignKey a UnidadMedida
    unidad_medida = models.ForeignKey(
        UnidadMedida,
        on_delete=models.CASCADE,
        help_text="Unidad de medida para este modelo"
    )

    cantidad_por_unidad = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=1.00,
        help_text="Cantidad por unidad (ej: metros por rollo, piezas por caja)"
    )
    requiere_inspeccion_inicial = models.BooleanField(
        default=True,
        help_text="Indica si requiere inspección en laboratorio al ingresar como NUEVO"
    )
    pruebas_laboratorio = models.JSONField(
        default=list, blank=True,
        help_text="Pruebas que aplican a este modelo (campos de PRUEBAS_LABORATORIO). Vacío = todas."
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.marca.nombre} {self.nombre} ({self.codigo_modelo})"

    @property
    def pruebas_aplicables(self):
        """Campos de prueba de laboratorio de este modelo (todas si no se configuró)."""
        elegidas = [c for c in CAMPOS_PRUEBA if c in (self.pruebas_laboratorio or [])]
        return elegidas or list(CAMPOS_PRUEBA)

    class Meta:
        unique_together = ['marca', 'nombre']
        db_table = 'almacenes_modelo'

    def save(self, *args, **kwargs):
        # Heredar la unidad de medida del tipo de material si no se indicó.
        # NOTA: requiere_inspeccion_inicial ya NO se pisa aquí; se respeta lo que
        # el usuario elige. El valor por defecto (según el tipo) lo pone el serializer.
        if self.tipo_material and not self.unidad_medida_id:
            self.unidad_medida = self.tipo_material.unidad_medida_default

        super().save(*args, **kwargs)


class ModeloComponente(models.Model):
    modelo = models.ForeignKey(Modelo, on_delete=models.CASCADE)
    componente = models.ForeignKey(Componente, on_delete=models.CASCADE)
    cantidad = models.SmallIntegerField(default=1)

    class Meta:
        unique_together = ['modelo', 'componente']
        db_table = 'almacenes_modelo_componente'


# ========== MODELO DE LOTE ==========
def generar_numero_lote():
    """Genera el siguiente número de lote correlativo en formato L000001, L000002, etc."""
    from django.db import transaction

    with transaction.atomic():
        # Obtener el último lote ordenado por numero_lote
        ultimo_lote = Lote.objects.filter(
            numero_lote__startswith='L'
        ).exclude(numero_lote='').order_by('numero_lote').last()

        if ultimo_lote:
            try:
                # Extraer el número del formato L000001 -> 1
                ultimo_numero = int(ultimo_lote.numero_lote[1:])
                siguiente_numero = ultimo_numero + 1
            except (ValueError, IndexError):
                # Si hay error en el formato, empezar desde 1
                siguiente_numero = 1
        else:
            # Primer lote
            siguiente_numero = 1

        # Formatear como L000001, L000002, etc. (6 dígitos con ceros a la izquierda)
        nuevo_numero = f"L{siguiente_numero:06d}"

        # Verificar que no exista (por seguridad)
        while Lote.objects.filter(numero_lote=nuevo_numero).exists():
            siguiente_numero += 1
            nuevo_numero = f"L{siguiente_numero:06d}"

        return nuevo_numero

class Lote(models.Model):
    """Modelo de lote con referencias a ForeignKeys"""
    numero_lote = models.CharField(max_length=50, unique=True)
    tipo_ingreso = models.ForeignKey(
        TipoIngreso,
        on_delete=models.CASCADE,
        help_text="Tipo de ingreso del lote"
    )
    proveedor = models.ForeignKey(Proveedor, on_delete=models.CASCADE)
    almacen_destino = models.ForeignKey(
        Almacen,
        on_delete=models.CASCADE,
        help_text="Almacén donde se reciben los materiales"
    )
    # Opcionales: el servicio se define al instalar (contrato), no al comprar
    tipo_servicio = models.ForeignKey('contratos.TipoServicio', on_delete=models.CASCADE, null=True, blank=True)
    sector_solicitante = models.ForeignKey(
        SectorSolicitante,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text="Sector que solicitó la compra (opcional)"
    )

    # Códigos SPRINT
    codigo_requerimiento_compra = models.CharField(
        max_length=10,
        help_text="Código de requerimiento de compra SPRINT (6-10 dígitos)"
    )
    codigo_nota_ingreso = models.CharField(
        max_length=10,
        help_text="Código de nota de ingreso SPRINT (6-10 dígitos)"
    )

    # Fechas
    fecha_recepcion = models.DateField(help_text="Fecha de recepción del lote")
    fecha_inicio_garantia = models.DateField(help_text="Inicio de garantía")
    fecha_fin_garantia = models.DateField(help_text="Fin de garantía")

    # Estado del lote
    estado = models.ForeignKey(
        EstadoLote,
        on_delete=models.CASCADE,
        help_text="Estado actual del lote"
    )

    # Campos específicos para lotes de laboratorio
    numero_informe = models.CharField(max_length=50, blank=True, help_text="Número de informe de laboratorio")
    detalles_informe = models.TextField(blank=True, help_text="Detalles del informe de laboratorio")
    fecha_informe = models.DateField(null=True, blank=True, help_text="Fecha del informe de laboratorio")

    # Control de entregas parciales
    total_entregas_parciales = models.PositiveIntegerField(default=0)

    observaciones = models.TextField(blank=True)

    # Auditoría
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        'usuarios.Usuario',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='lotes_creados'
    )

    class Meta:
        db_table = 'almacenes_lote'
        verbose_name = 'Lote'
        verbose_name_plural = 'Lotes'

    def __str__(self):
        return f"{self.numero_lote} - {self.proveedor.nombre_comercial}"

    def save(self, *args, **kwargs):
        """Override save para generar número automático si no existe o está vacío"""
        if not self.numero_lote or self.numero_lote.strip() == '':
            self.numero_lote = generar_numero_lote()
        super().save(*args, **kwargs)

    @property
    def cantidad_total(self):
        return sum(detalle.cantidad for detalle in self.detalles.all())

    @property
    def cantidad_recibida(self):
        # Suma por detalle: equipos únicos cuentan filas, materiales a granel suman cantidades
        return sum(detalle.cantidad_recibida for detalle in self.detalles.all())

    @property
    def cantidad_pendiente(self):
        return max(0, self.cantidad_total - self.cantidad_recibida)

    @property
    def porcentaje_recibido(self):
        total = self.cantidad_total
        if total == 0:
            return 0
        return round((self.cantidad_recibida / total) * 100, 2)

    # Tipos de ingreso válidos para un lote (lo que entrega un proveedor):
    #   NUEVO = Compra, REPOSICION = Reposición por garantía. Ambos traen equipos nuevos.
    # Reingresos y devoluciones de equipos usados NO son lotes (tienen su propio flujo).
    TIPOS_INGRESO_LOTE = ('NUEVO', 'REPOSICION')

    @property
    def recibe_equipos_nuevos(self):
        return bool(self.tipo_ingreso_id) and self.tipo_ingreso.codigo in self.TIPOS_INGRESO_LOTE

    # ---------- Reglas únicas de recepción (usar SIEMPRE estas) ----------
    def siguiente_numero_entrega(self):
        """Próximo número de entrega parcial (no depende del contador, que podía desfasarse)."""
        ultimo = self.entregas_parciales.aggregate(m=models.Max('numero_entrega'))['m'] or 0
        return ultimo + 1

    def actualizar_estado_recepcion(self, guardar=True):
        """
        Recalcula el estado según lo REALMENTE recibido (materiales del lote) y
        sincroniza el contador de entregas. Un lote cerrado no cambia de estado.
          nada recibido -> REGISTRADO | parte -> RECEPCION_PARCIAL | todo -> RECEPCION_COMPLETA
        """
        # Olvidar detalles/entregas precargados: pudieron cambiar en esta misma petición
        getattr(self, '_prefetched_objects_cache', {}).pop('detalles', None)
        getattr(self, '_prefetched_objects_cache', {}).pop('entregas_parciales', None)
        self.total_entregas_parciales = self.entregas_parciales.count()
        if not (self.estado and self.estado.codigo == 'CERRADO'):
            recibida, total = self.cantidad_recibida, self.cantidad_total
            codigo = 'REGISTRADO' if recibida <= 0 else ('RECEPCION_COMPLETA' if total and recibida >= total else 'RECEPCION_PARCIAL')
            nuevo = EstadoLote.objects.filter(codigo=codigo, activo=True).first()
            if nuevo:
                self.estado = nuevo
        if guardar:
            self.save(update_fields=['estado', 'total_entregas_parciales', 'updated_at'])
        return self.estado


class EntregaParcialLote(models.Model):
    """Modelo para control de entregas parciales de lotes"""
    lote = models.ForeignKey(Lote, on_delete=models.CASCADE, related_name='entregas_parciales')
    numero_entrega = models.PositiveIntegerField(help_text="Número de entrega parcial (1, 2, 3, etc.)")
    fecha_entrega = models.DateField(help_text="Fecha de esta entrega parcial")
    cantidad_entregada = models.PositiveIntegerField(help_text="Cantidad entregada en esta parte")
    estado_entrega = models.ForeignKey(
        EstadoLote,
        on_delete=models.CASCADE,
        help_text="Estado de esta entrega parcial"
    )
    observaciones = models.TextField(blank=True)

    # Auditoría
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        'usuarios.Usuario',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='entregas_parciales_creadas'
    )

    class Meta:
        db_table = 'almacenes_entrega_parcial_lote'
        unique_together = ['lote', 'numero_entrega']
        ordering = ['lote', 'numero_entrega']

    def __str__(self):
        return f"{self.lote.numero_lote} - Entrega {self.numero_entrega}"


class LoteDetalle(models.Model):
    """Detalle de materiales esperados en un lote"""
    lote = models.ForeignKey(Lote, on_delete=models.CASCADE, related_name='detalles')
    modelo = models.ForeignKey(Modelo, on_delete=models.CASCADE)
    cantidad = models.IntegerField(default=0, help_text="Cantidad esperada de este modelo")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['lote', 'modelo']
        db_table = 'almacenes_lote_detalle'

    def __str__(self):
        return f"{self.lote.numero_lote} - {self.modelo.nombre} ({self.cantidad})"

    @property
    def cantidad_recibida(self):
        es_unico = self.modelo.tipo_material.es_unico
        # Si el listado ya lo precalculó (optimizar_lotes), no se consulta de nuevo
        if '_rec_count' in self.__dict__:
            if es_unico:
                return self._rec_count
            total = self._rec_sum or 0
            return int(total) if total == int(total) else float(total)

        materiales = self.lote.material_set.filter(modelo=self.modelo)
        if es_unico:
            # ONUs: 1 fila = 1 equipo
            return materiales.count()
        # Materiales a granel (cable, conectores): se suma la cantidad de cada ingreso
        total = materiales.aggregate(total=models.Sum('cantidad'))['total'] or 0
        return int(total) if total == int(total) else float(total)

    @property
    def cantidad_pendiente(self):
        return max(0, self.cantidad - self.cantidad_recibida)


# ========== MODELO UNIFICADO DE MATERIAL ==========

class Material(models.Model):
    """Modelo unificado para todos los tipos de materiales y equipos"""

    # Identificación básica
    codigo_interno = models.CharField(max_length=50, unique=True,
                                      help_text="Código interno único generado automáticamente")

    # NUEVO: ForeignKey a TipoMaterial
    tipo_material = models.ForeignKey(
        TipoMaterial,
        on_delete=models.CASCADE,
        help_text="Tipo de material"
    )

    # Relaciones básicas
    modelo = models.ForeignKey(Modelo, on_delete=models.CASCADE)
    lote = models.ForeignKey(Lote, on_delete=models.CASCADE, help_text="Lote de origen")

    # Campos específicos para equipos únicos
    mac_address = models.CharField(max_length=17, blank=True, unique=True, null=True,
                                   help_text="MAC Address para equipos únicos")
    gpon_serial = models.CharField(max_length=100, blank=True, unique=True, null=True,
                                   help_text="GPON Serial para equipos únicos")

    serial_manufacturer = models.CharField(
        max_length=100,
        blank=True,  # Permitir vacío en formularios
        null=True,  # Permitir NULL en base de datos
        help_text="D-SN/Serial Manufacturer para equipos únicos (opcional)"
    )

    # ELIMINADO: codigo_barras
    especificaciones_tecnicas = models.JSONField(default=dict, blank=True,
                                                 help_text="Especificaciones técnicas del material")

    # Código SPRINT
    codigo_item_equipo = models.CharField(
        max_length=10,
        help_text="Código SPRINT Item Equipo (6-10 dígitos)"
    )

    # Ubicación y estados
    almacen_actual = models.ForeignKey(Almacen, on_delete=models.CASCADE,
                                       help_text="Almacén donde se encuentra actualmente")

    # Estados específicos según tipo de material
    estado_onu = models.ForeignKey(
        EstadoMaterialONU,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text="Estado específico para equipos únicos (ONU, etc.)"
    )
    estado_general = models.ForeignKey(
        EstadoMaterialGeneral,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text="Estado para materiales por cantidad"
    )

    # Control de origen y nuevos ingresos
    es_nuevo = models.BooleanField(
        default=True,
        help_text="TRUE solo en primera entrada, FALSE en reingresos"
    )
    tipo_origen = models.ForeignKey(
        TipoIngreso,
        on_delete=models.CASCADE,
        help_text="Tipo de origen del material"
    )

    # Control de laboratorio
    fecha_envio_laboratorio = models.DateTimeField(null=True, blank=True)
    fecha_retorno_laboratorio = models.DateTimeField(null=True, blank=True)

    # Cantidad (para materiales no únicos)
    cantidad = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=1.00,
        help_text="Cantidad para materiales no únicos (metros, unidades, etc.)"
    )

    # Traspaso actual
    traspaso_actual = models.ForeignKey(
        'TraspasoAlmacen',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Traspaso en el que está involucrado actualmente"
    )

    # Orden de trabajo futura
    orden_trabajo = models.CharField(max_length=50, blank=True, help_text="Orden de trabajo asignada (futuro)")

    observaciones = models.TextField(blank=True)

    # Auditoría
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # NUEVOS CAMPOS PARA ENTREGAS PARCIALES
    numero_entrega_parcial = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Número de entrega parcial a la que pertenece este material"
    )

    # CAMPOS PARA REINGRESOS
    equipo_original = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reingresos',
        help_text="Equipo original que está siendo reemplazado (para reingresos)"
    )

    motivo_reingreso = models.TextField(
        blank=True,
        help_text="Motivo del reingreso/reposición"
    )

    # CAMPOS PARA OBSERVACIONES DE LABORATORIO
    observaciones_laboratorio = models.JSONField(
        default=dict,
        blank=True,
        help_text="Observaciones detalladas del laboratorio"
    )

    numero_informe_laboratorio = models.CharField(
        max_length=50,
        blank=True,
        help_text="Número de informe de laboratorio"
    )

    material_reemplazo = models.OneToOneField(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='material_original',
        help_text='Material que reemplaza a este (en caso de devolución/reposición)'
    )

    class Meta:
        db_table = 'almacenes_material'
        verbose_name = 'Material'
        verbose_name_plural = 'Materiales'

    def __str__(self):
        if self.tipo_material.es_unico:
            return f"{self.codigo_interno} - {self.modelo.nombre} ({self.mac_address})"
        else:
            return f"{self.codigo_interno} - {self.modelo.nombre} (Cant: {self.cantidad})"

    def clean(self):
        """Validaciones específicas por tipo de material"""
        # Validación de código SPRINT
        if not (6 <= len(self.codigo_item_equipo) <= 10):
            raise ValidationError("El código item equipo debe tener entre 6 y 10 dígitos")

        if not self.codigo_item_equipo.isdigit():
            raise ValidationError("El código item equipo solo puede contener números")

        # Validaciones para equipos únicos
        if self.tipo_material.es_unico:
            # ✅ MAC obligatorio con formato
            if not self.mac_address:
                raise ValidationError("Los equipos únicos requieren MAC Address")
            if not re.match(r'^([0-9A-F]{2}[:-]){5}([0-9A-F]{2})$', self.mac_address.upper()):
                raise ValidationError("Formato de MAC Address inválido. Use XX:XX:XX:XX:XX:XX")

            # ✅ GPON obligatorio con formato
            if not self.gpon_serial:
                raise ValidationError("Los equipos únicos requieren GPON Serial")
            if len(self.gpon_serial) < 8:
                raise ValidationError("GPON Serial debe tener al menos 8 caracteres")

            # ✅ SN OPCIONAL pero con formato si se proporciona
            if self.serial_manufacturer:  # Solo validar si tiene valor
                if len(self.serial_manufacturer) < 6:
                    raise ValidationError("D-SN debe tener al menos 6 caracteres si se proporciona")

    def save(self, *args, **kwargs):
        # Generar código interno si no existe
        if not self.codigo_interno:
            self.codigo_interno = self._generar_codigo_interno()

        # Normalizar MAC Address
        if self.mac_address:
            self.mac_address = self.mac_address.upper().replace('-', ':')

        # Asignar estado inicial según tipo de material
        if self.tipo_material.es_unico and not self.estado_onu:
            # Buscar estado por código para equipos únicos
            if self.es_nuevo:
                # Si el modelo requiere inspección -> NUEVO (pendiente de laboratorio);
                # si no, entra directo como DISPONIBLE.
                codigo_inicial = 'NUEVO' if (not self.modelo_id or self.modelo.requiere_inspeccion_inicial) else 'DISPONIBLE'
                try:
                    self.estado_onu = EstadoMaterialONU.objects.get(codigo=codigo_inicial, activo=True)
                except EstadoMaterialONU.DoesNotExist:
                    pass
            else:
                try:
                    estado_reingresado = EstadoMaterialONU.objects.get(codigo='REINGRESADO', activo=True)
                    self.estado_onu = estado_reingresado
                except EstadoMaterialONU.DoesNotExist:
                    pass

        elif not self.tipo_material.es_unico and not self.estado_general:
            # Buscar estado por código para materiales generales
            try:
                estado_disponible = EstadoMaterialGeneral.objects.get(codigo='DISPONIBLE', activo=True)
                self.estado_general = estado_disponible
            except EstadoMaterialGeneral.DoesNotExist:
                pass

        es_nuevo_registro = self._state.adding
        super().save(*args, **kwargs)

        # Primer movimiento del historial: el ingreso al almacén
        responsable = getattr(self, '_usuario', None) or (self.lote.created_by if self.lote_id else None)
        if es_nuevo_registro and responsable:  # el historial exige usuario responsable
            estado = self.estado_onu if self.tipo_material.es_unico else self.estado_general
            HistorialMaterial.objects.create(
                material=self,
                estado_anterior='',
                estado_nuevo=(estado.codigo if estado else '')[:25],
                almacen_anterior=None,
                almacen_nuevo=self.almacen_actual,
                motivo=(f'Ingreso por lote {self.lote.numero_lote}' if self.lote_id else 'Ingreso al almacén')[:100],
                observaciones=f'Cantidad: {self.cantidad}' if not self.tipo_material.es_unico else '',
                usuario_responsable=responsable,
            )

    def _generar_codigo_interno(self):
        """Generar código interno único"""
        import uuid
        while True:
            if self.tipo_material.es_unico:
                prefijo = "EQ"
            else:
                prefijo = "MAT"

            codigo = f"{prefijo}-{str(uuid.uuid4().int)[:8]}"
            if not Material.objects.filter(codigo_interno=codigo).exists():
                return codigo

    @property
    def estado_display(self):
        """Obtener estado para mostrar según el tipo de material"""
        if self.tipo_material.es_unico:
            return self.estado_onu.nombre if self.estado_onu else 'Sin estado'
        else:
            return self.estado_general.nombre if self.estado_general else 'Sin estado'

    @property
    def requiere_laboratorio(self):
        """Determinar si el material requiere ir a laboratorio"""
        if self.tipo_material.es_unico:
            return (self.es_nuevo and
                    self.modelo.requiere_inspeccion_inicial and
                    self.tipo_origen.codigo == 'NUEVO' and
                    self.estado_onu and self.estado_onu.codigo == 'NUEVO')
        return False

    @property
    def puede_traspasar(self):
        """Verificar si el material puede ser traspasado"""
        if self.tipo_material.es_unico:
            return self.estado_onu.permite_traspaso if self.estado_onu else False
        else:
            return self.estado_general.permite_traspaso if self.estado_general else False

    @property
    def dias_en_laboratorio(self):
        """Calcular días que lleva en laboratorio"""
        if self.fecha_envio_laboratorio and not self.fecha_retorno_laboratorio:
            return (timezone.now() - self.fecha_envio_laboratorio).days
        return 0

    def enviar_a_laboratorio(self, usuario=None):
        """Enviar material a laboratorio"""
        anterior = self.estado_onu.codigo if self.estado_onu_id else ''
        if self.tipo_material.es_unico:
            try:
                estado_laboratorio = EstadoMaterialONU.objects.get(codigo='EN_LABORATORIO', activo=True)
                self.estado_onu = estado_laboratorio
            except EstadoMaterialONU.DoesNotExist:
                pass

        self.fecha_envio_laboratorio = timezone.now()
        self.fecha_retorno_laboratorio = None  # nuevo ciclo de laboratorio
        self.save()
        if usuario:  # el historial exige usuario responsable
            HistorialMaterial.objects.create(
                material=self,
                estado_anterior=anterior[:25],
                estado_nuevo=(self.estado_onu.codigo if self.estado_onu_id else '')[:25],
                almacen_anterior=self.almacen_actual,
                almacen_nuevo=self.almacen_actual,
                motivo='Enviado a laboratorio para inspección',
                usuario_responsable=usuario,
            )

    def retornar_de_laboratorio(self, resultado_exitoso=True, informe_numero=None, detalles=None):
        """Retornar material de laboratorio"""
        self.fecha_retorno_laboratorio = timezone.now()

        if self.tipo_material.es_unico:
            if resultado_exitoso:
                try:
                    estado_disponible = EstadoMaterialONU.objects.get(codigo='DISPONIBLE', activo=True)
                    self.estado_onu = estado_disponible
                except EstadoMaterialONU.DoesNotExist:
                    pass
            else:
                try:
                    estado_defectuoso = EstadoMaterialONU.objects.get(codigo='DEFECTUOSO', activo=True)
                    self.estado_onu = estado_defectuoso
                except EstadoMaterialONU.DoesNotExist:
                    pass

        self.save()

    @property
    def tipo_equipo(self):
        """Obtener tipo de equipo desde el modelo"""
        return self.modelo.tipo_equipo if self.modelo else None


# ========== MODELO DE TRASPASOS ==========

class TraspasoAlmacen(models.Model):
    """Modelo para control de movimientos entre almacenes"""

    numero_traspaso = models.CharField(max_length=20, unique=True,
                                       help_text="Número único de traspaso generado automáticamente")
    numero_solicitud = models.CharField(max_length=10, help_text="Número de solicitud (6-10 dígitos)")

    # Almacenes origen y destino
    almacen_origen = models.ForeignKey(
        Almacen,
        on_delete=models.CASCADE,
        related_name='traspasos_salida'
    )
    almacen_destino = models.ForeignKey(
        Almacen,
        on_delete=models.CASCADE,
        related_name='traspasos_entrada'
    )

    # Fechas del traspaso
    fecha_envio = models.DateTimeField(help_text="Fecha y hora de envío")
    fecha_recepcion = models.DateTimeField(null=True, blank=True, help_text="Fecha y hora de recepción")

    # Estado del traspaso
    estado = models.ForeignKey(
        EstadoTraspaso,
        on_delete=models.CASCADE,
        help_text="Estado actual del traspaso"
    )

    # Cantidades
    cantidad_enviada = models.PositiveIntegerField(help_text="Cantidad de materiales enviados")
    cantidad_recibida = models.PositiveIntegerField(default=0, help_text="Cantidad de materiales recibidos")

    # Información del traspaso
    motivo = models.TextField(help_text="Motivo del traspaso")
    observaciones_envio = models.TextField(blank=True)
    observaciones_recepcion = models.TextField(blank=True)

    # Usuarios responsables
    usuario_envio = models.ForeignKey(
        'usuarios.Usuario',
        on_delete=models.CASCADE,
        related_name='traspasos_enviados'
    )
    usuario_recepcion = models.ForeignKey(
        'usuarios.Usuario',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='traspasos_recibidos'
    )

    # Auditoría
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'almacenes_traspaso_almacen'
        verbose_name = 'Traspaso de Almacén'
        verbose_name_plural = 'Traspasos de Almacén'

    def __str__(self):
        return f"{self.numero_traspaso} - {self.almacen_origen.codigo} → {self.almacen_destino.codigo}"

    def save(self, *args, **kwargs):
        if not self.numero_traspaso:
            self.numero_traspaso = self._generar_numero_traspaso()

        # Asignar estado inicial si no tiene
        if not self.estado_id:
            try:
                estado_pendiente = EstadoTraspaso.objects.get(codigo='PENDIENTE', activo=True)
                self.estado = estado_pendiente
            except EstadoTraspaso.DoesNotExist:
                pass

        super().save(*args, **kwargs)

    def _generar_numero_traspaso(self):
        """Generar número de traspaso único"""
        import uuid
        while True:
            numero = f"TR-{timezone.now().year}-{str(uuid.uuid4().int)[:6]}"
            if not TraspasoAlmacen.objects.filter(numero_traspaso=numero).exists():
                return numero

    @property
    def duracion_transito(self):
        """Duración del tránsito en días"""
        if self.fecha_recepcion:
            return (self.fecha_recepcion - self.fecha_envio).days
        else:
            return (timezone.now() - self.fecha_envio).days

    @property
    def materiales_faltantes(self):
        """Cantidad de materiales faltantes en la recepción"""
        return max(0, self.cantidad_enviada - self.cantidad_recibida)


class TraspasoMaterial(models.Model):
    """Tabla intermedia para materials en traspasos"""
    traspaso = models.ForeignKey(TraspasoAlmacen, on_delete=models.CASCADE, related_name='materiales')
    material = models.ForeignKey(Material, on_delete=models.CASCADE)
    recibido = models.BooleanField(default=False)
    observaciones = models.TextField(blank=True)

    class Meta:
        db_table = 'almacenes_traspaso_material'
        unique_together = ['traspaso', 'material']

    def __str__(self):
        return f"{self.traspaso.numero_traspaso} - {self.material.codigo_interno}"

# ========== MODELO DE HISTORIAL ==========

class HistorialMaterial(models.Model):
    """Historial de cambios de estado y ubicación de materiales"""

    material = models.ForeignKey(Material, on_delete=models.CASCADE, related_name='historial')

    # Estados anteriores
    estado_anterior = models.CharField(max_length=25, blank=True)
    estado_nuevo = models.CharField(max_length=25)

    # Ubicaciones
    almacen_anterior = models.ForeignKey(
        Almacen,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='historiales_salida'
    )
    almacen_nuevo = models.ForeignKey(
        Almacen,
        on_delete=models.CASCADE,
        related_name='historiales_entrada'
    )

    # Información del cambio
    motivo = models.CharField(max_length=100, help_text="Motivo del cambio")
    observaciones = models.TextField(blank=True)

    # Referencias a otros modelos si aplica
    traspaso_relacionado = models.ForeignKey(
        TraspasoAlmacen,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    # Auditoría
    fecha_cambio = models.DateTimeField(auto_now_add=True)
    usuario_responsable = models.ForeignKey(
        'usuarios.Usuario',
        on_delete=models.CASCADE
    )

    class Meta:
        db_table = 'almacenes_historial_material'
        ordering = ['-fecha_cambio']

    def __str__(self):
        return f"{self.material.codigo_interno} - {self.motivo} ({self.fecha_cambio})"

# En almacenes/models.py

class InspeccionLaboratorio(models.Model):
    """Modelo para registrar inspecciones detalladas de laboratorio"""

    material = models.ForeignKey(
        Material,
        on_delete=models.CASCADE,
        related_name='inspecciones_laboratorio'
    )

    numero_informe = models.CharField(max_length=50, unique=True)

    # Resultados de inspección
    serie_logica_ok = models.BooleanField(help_text="Serie lógica coincide")
    wifi_24_ok = models.BooleanField(help_text="WiFi 2.4GHz funciona")
    wifi_5_ok = models.BooleanField(help_text="WiFi 5GHz funciona")
    puerto_ethernet_ok = models.BooleanField(help_text="Puerto Ethernet OK")
    puerto_lan_ok = models.BooleanField(help_text="Puerto LAN OK")

    puerto_catv_ok = models.BooleanField(default=True, help_text='Puerto CATV (TV por cable) funciona')
    puerto_telefonia_rf_ok = models.BooleanField(default=True, help_text='Puerto de Telefonía RF (POTS/FXS) funciona')
    otros_ok = models.BooleanField(default=True, help_text='Otras pruebas adicionales OK')

    # Resultado general
    aprobado = models.BooleanField()

    # Observaciones
    observaciones_tecnico = models.TextField(blank=True)
    comentarios_adicionales = models.TextField(blank=True)
    fallas_detectadas = models.JSONField(default=list, blank=True)

    # Información del proceso
    tecnico_revisor = models.CharField(max_length=50, blank=True)
    tiempo_inspeccion_minutos = models.PositiveIntegerField(default=0)
    pruebas_aplicadas = models.JSONField(
        default=list, blank=True,
        help_text="Pruebas que se hicieron (según el modelo). Vacío = todas (registros anteriores)."
    )

    # Auditoría
    fecha_inspeccion = models.DateTimeField(auto_now_add=True)
    usuario_responsable = models.ForeignKey(
        'usuarios.Usuario',
        on_delete=models.CASCADE
    )

    class Meta:
        db_table = 'almacenes_inspeccion_laboratorio'
        ordering = ['-fecha_inspeccion']

    def __str__(self):
        return f"{self.numero_informe} - {self.material.codigo_interno}"

    @property
    def resultados_pruebas(self):
        """[(nombre, ok)] solo de las pruebas que se hicieron."""
        hechas = self.pruebas_aplicadas or CAMPOS_PRUEBA
        return [(n, getattr(self, c)) for c, n, _ in PRUEBAS_LABORATORIO if c in hechas]
