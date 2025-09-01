# ======================================================
# apps/almacenes/models.py
# Sistema Integral de Gestión de Almacenes GPON/Fibra Óptica
# ======================================================

from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType
import re


# ========== ENUMS Y CHOICES ==========

class TipoIngresoChoices(models.TextChoices):
    NUEVO = 'NUEVO', 'Nuevo'
    REINGRESO = 'REINGRESO', 'Reingreso'
    DEVOLUCION = 'DEVOLUCION', 'Devolución'
    LABORATORIO = 'LABORATORIO', 'Laboratorio'


class EstadoLoteChoices(models.TextChoices):
    REGISTRADO = 'REGISTRADO', 'Registrado'
    PENDIENTE_RECEPCION = 'PENDIENTE_RECEPCION', 'Pendiente Recepción'
    RECEPCION_PARCIAL = 'RECEPCION_PARCIAL', 'Recepción Parcial'
    RECEPCION_COMPLETA = 'RECEPCION_COMPLETA', 'Recepción Completa'
    ACTIVO = 'ACTIVO', 'Activo'
    CERRADO = 'CERRADO', 'Cerrado'


class EstadoTraspasoChoices(models.TextChoices):
    PENDIENTE = 'PENDIENTE', 'Pendiente'
    EN_TRANSITO = 'EN_TRANSITO', 'En Tránsito'
    RECIBIDO = 'RECIBIDO', 'Recibido'
    CANCELADO = 'CANCELADO', 'Cancelado'


class TipoMaterialChoices(models.TextChoices):
    ONU = 'ONU', 'Equipo ONU'
    CABLE_DROP = 'CABLE_DROP', 'Cable Drop'
    CONECTOR_APC = 'CONECTOR_APC', 'Conector APC'
    CONECTOR_UPC = 'CONECTOR_UPC', 'Conector UPC'
    ROSETA_OPTICA = 'ROSETA_OPTICA', 'Roseta Óptica'
    PATCH_CORE = 'PATCH_CORE', 'Patch Core'
    TRIPLEXOR = 'TRIPLEXOR', 'Triplexor'
    OTRO = 'OTRO', 'Otro Material'


class UnidadMedidaChoices(models.TextChoices):
    PIEZA = 'PIEZA', 'Pieza'
    UNIDAD = 'UNIDAD', 'Unidad'
    METROS = 'METROS', 'Metros'
    CAJA = 'CAJA', 'Caja'
    ROLLO = 'ROLLO', 'Rollo'
    KIT = 'KIT', 'Kit'
    PAQUETE = 'PAQUETE', 'Paquete'


class EstadoMaterialONUChoices(models.TextChoices):
    NUEVO = 'NUEVO', 'Nuevo'
    DISPONIBLE = 'DISPONIBLE', 'Disponible'
    RESERVADO = 'RESERVADO', 'Reservado'
    ASIGNADO = 'ASIGNADO', 'Asignado'
    INSTALADO = 'INSTALADO', 'Instalado'
    EN_LABORATORIO = 'EN_LABORATORIO', 'En Laboratorio'
    DEFECTUOSO = 'DEFECTUOSO', 'Defectuoso'
    DEVUELTO_PROVEEDOR = 'DEVUELTO_PROVEEDOR', 'Devuelto a Proveedor'
    REINGRESADO = 'REINGRESADO', 'Reingresado'
    DADO_DE_BAJA = 'DADO_DE_BAJA', 'Dado de Baja'


class EstadoMaterialGeneralChoices(models.TextChoices):
    DISPONIBLE = 'DISPONIBLE', 'Disponible'
    RESERVADO = 'RESERVADO', 'Reservado'
    ASIGNADO = 'ASIGNADO', 'Asignado'
    CONSUMIDO = 'CONSUMIDO', 'Consumido'
    DEFECTUOSO = 'DEFECTUOSO', 'Defectuoso'
    DADO_DE_BAJA = 'DADO_DE_BAJA', 'Dado de Baja'


class TipoAlmacenChoices(models.TextChoices):
    PRINCIPAL = 'PRINCIPAL', 'Principal'
    REGIONAL = 'REGIONAL', 'Regional'
    TEMPORAL = 'TEMPORAL', 'Temporal'


class EstadoDevolucionChoices(models.TextChoices):
    PENDIENTE = 'PENDIENTE', 'Pendiente'
    ENVIADO = 'ENVIADO', 'Enviado'
    CONFIRMADO = 'CONFIRMADO', 'Confirmado'
    RECHAZADO = 'RECHAZADO', 'Rechazado'


class RespuestaProveedorChoices(models.TextChoices):
    REPOSICION = 'REPOSICION', 'Reposición'
    CREDITO = 'CREDITO', 'Crédito'
    RECHAZO = 'RECHAZO', 'Rechazo'
    PENDIENTE = 'PENDIENTE', 'Pendiente'


# ========== MODELOS BASE ==========

class Almacen(models.Model):
    """Modelo para gestión de almacenes regionales"""
    codigo = models.CharField(max_length=10, unique=True, help_text="Código único del almacén")
    nombre = models.CharField(max_length=100, help_text="Nombre del almacén")
    ciudad = models.CharField(max_length=50, help_text="Ciudad donde se ubica")
    tipo = models.CharField(
        max_length=20,
        choices=TipoAlmacenChoices.choices,
        default=TipoAlmacenChoices.REGIONAL
    )
    direccion = models.TextField(blank=True, help_text="Dirección física")
    es_principal = models.BooleanField(default=False, help_text="Indica si es el almacén principal")
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
            # Solo un almacén puede ser principal
            otros_principales = Almacen.objects.filter(es_principal=True).exclude(pk=self.pk)
            if otros_principales.exists():
                raise ValidationError("Solo puede existir un almacén principal")

    def puede_eliminar(self):
        """Verificar si el almacén puede ser eliminado"""
        return not self.material_set.exists()

    @property
    def total_materiales(self):
        return self.material_set.count()

    @property
    def materiales_disponibles(self):
        return self.material_set.filter(
            estado_general=EstadoMaterialGeneralChoices.DISPONIBLE
        ).count()


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
    activo = models.BooleanField(default=True)  # NUEVO
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.nombre

    class Meta:
        db_table = 'almacenes_marca'


class TipoEquipo(models.Model):
    nombre = models.CharField(max_length=50, unique=True)
    descripcion = models.TextField(blank=True)
    activo = models.BooleanField(default=True)  # NUEVO
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.nombre

    class Meta:
        db_table = 'almacenes_tipo_equipo'


class Componente(models.Model):
    nombre = models.CharField(max_length=100, unique=True)
    descripcion = models.TextField(blank=True)
    activo = models.BooleanField(default=True)  # NUEVO
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.nombre

    class Meta:
        db_table = 'almacenes_componente'


class EstadoEquipo(models.Model):
    """Ahora será para compatibilidad, los nuevos estados están en el modelo Material"""
    nombre = models.CharField(max_length=50, unique=True)
    descripcion = models.TextField(blank=True)
    activo = models.BooleanField(default=True)  # NUEVO
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.nombre

    class Meta:
        db_table = 'almacenes_estado_equipo'


class Modelo(models.Model):
    marca = models.ForeignKey(Marca, on_delete=models.CASCADE)
    tipo_equipo = models.ForeignKey(TipoEquipo, on_delete=models.CASCADE)
    nombre = models.CharField(max_length=100)
    codigo_modelo = models.IntegerField(unique=True)
    descripcion = models.TextField(blank=True)
    activo = models.BooleanField(default=True)  # NUEVO

    # NUEVOS CAMPOS PARA SOPORTE DE DIFERENTES MATERIALES
    tipo_material = models.CharField(
        max_length=20,
        choices=TipoMaterialChoices.choices,
        default=TipoMaterialChoices.ONU,
        help_text="Tipo de material que representa este modelo"
    )
    unidad_medida = models.CharField(
        max_length=15,
        choices=UnidadMedidaChoices.choices,
        default=UnidadMedidaChoices.PIEZA,
        help_text="Unidad de medida para este tipo de material"
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

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.marca.nombre} {self.nombre} ({self.codigo_modelo})"

    class Meta:
        unique_together = ['marca', 'nombre']
        db_table = 'almacenes_modelo'

    def clean(self):
        """Validaciones específicas por tipo de material"""
        if self.tipo_material == TipoMaterialChoices.ONU:
            self.requiere_inspeccion_inicial = True  # ONUs siempre requieren inspección
            self.unidad_medida = UnidadMedidaChoices.PIEZA
            self.cantidad_por_unidad = 1.00


class ModeloComponente(models.Model):
    modelo = models.ForeignKey(Modelo, on_delete=models.CASCADE)
    componente = models.ForeignKey(Componente, on_delete=models.CASCADE)
    cantidad = models.SmallIntegerField(default=1)

    class Meta:
        unique_together = ['modelo', 'componente']
        db_table = 'almacenes_modelo_componente'


# ========== NUEVO MODELO DE LOTE COMPLETO ==========

class Lote(models.Model):
    """Modelo de lote completamente rediseñado"""
    numero_lote = models.CharField(max_length=50, unique=True)
    tipo_ingreso = models.CharField(
        max_length=20,
        choices=TipoIngresoChoices.choices,
        default=TipoIngresoChoices.NUEVO
    )
    proveedor = models.ForeignKey(Proveedor, on_delete=models.CASCADE)
    almacen_destino = models.ForeignKey(
        Almacen,
        on_delete=models.CASCADE,
        help_text="Almacén donde se reciben los materiales"
    )
    tipo_servicio = models.ForeignKey('contratos.TipoServicio', on_delete=models.CASCADE)

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
    estado = models.CharField(
        max_length=25,
        choices=EstadoLoteChoices.choices,
        default=EstadoLoteChoices.REGISTRADO
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

    def clean(self):
        """Validaciones del lote"""
        # Validar códigos SPRINT
        if not (6 <= len(self.codigo_requerimiento_compra) <= 10):
            raise ValidationError("El código de requerimiento debe tener entre 6 y 10 dígitos")

        if not (6 <= len(self.codigo_nota_ingreso) <= 10):
            raise ValidationError("El código de nota de ingreso debe tener entre 6 y 10 dígitos")

        if not self.codigo_requerimiento_compra.isdigit():
            raise ValidationError("El código de requerimiento solo puede contener números")

        if not self.codigo_nota_ingreso.isdigit():
            raise ValidationError("El código de nota de ingreso solo puede contener números")

        # Validar fechas
        if self.fecha_fin_garantia <= self.fecha_inicio_garantia:
            raise ValidationError("La fecha de fin de garantía debe ser posterior al inicio")

        # Validar almacén destino para lotes nuevos
        if self.tipo_ingreso == TipoIngresoChoices.NUEVO:
            if not self.almacen_destino.es_principal:
                raise ValidationError("Los lotes nuevos solo pueden ir al almacén principal")

    @property
    def cantidad_total(self):
        """Cantidad total esperada en el lote"""
        return sum(detalle.cantidad for detalle in self.detalles.all())

    @property
    def cantidad_recibida(self):
        """Cantidad total recibida (materiales creados)"""
        return self.material_set.count()

    @property
    def cantidad_pendiente(self):
        """Cantidad pendiente de recibir"""
        return max(0, self.cantidad_total - self.cantidad_recibida)

    @property
    def porcentaje_recibido(self):
        """Porcentaje de materiales recibidos"""
        total = self.cantidad_total
        if total == 0:
            return 0
        return round((self.cantidad_recibida / total) * 100, 2)


class EntregaParcialLote(models.Model):
    """Modelo para control de entregas parciales de lotes"""
    lote = models.ForeignKey(Lote, on_delete=models.CASCADE, related_name='entregas_parciales')
    numero_entrega = models.PositiveIntegerField(help_text="Número de entrega parcial (1, 2, 3, etc.)")
    fecha_entrega = models.DateField(help_text="Fecha de esta entrega parcial")
    cantidad_entregada = models.PositiveIntegerField(help_text="Cantidad entregada en esta parte")
    estado_entrega = models.CharField(
        max_length=25,
        choices=EstadoLoteChoices.choices,
        default=EstadoLoteChoices.RECEPCION_PARCIAL
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
        """Cantidad recibida de este modelo en el lote"""
        return self.lote.material_set.filter(modelo=self.modelo).count()

    @property
    def cantidad_pendiente(self):
        """Cantidad pendiente de este modelo"""
        return max(0, self.cantidad - self.cantidad_recibida)


# ========== MODELO UNIFICADO DE MATERIAL ==========

class Material(models.Model):
    """Modelo unificado para todos los tipos de materiales y equipos"""

    # Identificación básica
    codigo_interno = models.CharField(max_length=50, unique=True,
                                      help_text="Código interno único generado automáticamente")
    tipo_material = models.CharField(
        max_length=20,
        choices=TipoMaterialChoices.choices,
        help_text="Tipo de material"
    )

    # Relaciones básicas
    modelo = models.ForeignKey(Modelo, on_delete=models.CASCADE)
    tipo_equipo = models.ForeignKey(TipoEquipo, on_delete=models.CASCADE)  # Para compatibilidad
    lote = models.ForeignKey(Lote, on_delete=models.CASCADE, help_text="Lote de origen")

    # Campos específicos para equipos ONU (solo aplican si tipo_material = 'ONU')
    mac_address = models.CharField(max_length=17, blank=True, unique=True, null=True,
                                   help_text="MAC Address para equipos ONU")
    gpon_serial = models.CharField(max_length=100, blank=True, unique=True, null=True,
                                   help_text="GPON Serial para equipos ONU")
    serial_manufacturer = models.CharField(max_length=100, blank=True, unique=True, null=True,
                                           help_text="D-SN/Serial Manufacturer para equipos ONU")

    # Campos para otros materiales
    codigo_barras = models.CharField(max_length=100, blank=True,
                                     help_text="Código de barras o identificador alternativo")
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
    estado_onu = models.CharField(
        max_length=25,
        choices=EstadoMaterialONUChoices.choices,
        blank=True,
        help_text="Estado específico para equipos ONU"
    )
    estado_general = models.CharField(
        max_length=20,
        choices=EstadoMaterialGeneralChoices.choices,
        default=EstadoMaterialGeneralChoices.DISPONIBLE,
        help_text="Estado para otros materiales"
    )

    # Control de origen y nuevos ingresos
    es_nuevo = models.BooleanField(
        default=True,
        help_text="TRUE solo en primera entrada, FALSE en reingresos"
    )
    tipo_origen = models.CharField(
        max_length=20,
        choices=TipoIngresoChoices.choices,
        default=TipoIngresoChoices.NUEVO,
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

    class Meta:
        db_table = 'almacenes_material'
        verbose_name = 'Material'
        verbose_name_plural = 'Materiales'

    def __str__(self):
        if self.tipo_material == TipoMaterialChoices.ONU:
            return f"{self.codigo_interno} - {self.modelo.nombre} ({self.mac_address})"
        else:
            return f"{self.codigo_interno} - {self.modelo.nombre}"

    def clean(self):
        """Validaciones específicas por tipo de material"""
        # Validación de código SPRINT
        if not (6 <= len(self.codigo_item_equipo) <= 10):
            raise ValidationError("El código item equipo debe tener entre 6 y 10 dígitos")

        if not self.codigo_item_equipo.isdigit():
            raise ValidationError("El código item equipo solo puede contener números")

        # Validaciones específicas para equipos ONU
        if self.tipo_material == TipoMaterialChoices.ONU:
            if not all([self.mac_address, self.gpon_serial, self.serial_manufacturer]):
                raise ValidationError("Los equipos ONU requieren MAC Address, GPON Serial y Serial Manufacturer")

            # Validar formato de MAC Address
            if not re.match(r'^([0-9A-F]{2}[:-]){5}([0-9A-F]{2})$', self.mac_address.upper()):
                raise ValidationError("Formato de MAC Address inválido")

    def save(self, *args, **kwargs):
        # Generar código interno si no existe
        if not self.codigo_interno:
            self.codigo_interno = self._generar_codigo_interno()

        # Establecer tipo_material basado en el modelo si no está definido
        if not self.tipo_material and self.modelo:
            self.tipo_material = self.modelo.tipo_material

        # Normalizar MAC Address
        if self.mac_address:
            self.mac_address = self.mac_address.upper().replace('-', ':')

        # Asignar estado inicial según tipo de material
        if self.tipo_material == TipoMaterialChoices.ONU:
            if not self.estado_onu:
                if self.es_nuevo and self.tipo_origen == TipoIngresoChoices.NUEVO:
                    self.estado_onu = EstadoMaterialONUChoices.NUEVO
                else:
                    self.estado_onu = EstadoMaterialONUChoices.REINGRESADO

        super().save(*args, **kwargs)

    def _generar_codigo_interno(self):
        """Generar código interno único"""
        import uuid
        while True:
            if self.tipo_material == TipoMaterialChoices.ONU:
                prefijo = "EQ"
            else:
                prefijo = "MAT"

            codigo = f"{prefijo}-{str(uuid.uuid4().int)[:8]}"
            if not Material.objects.filter(codigo_interno=codigo).exists():
                return codigo

    @property
    def estado_display(self):
        """Obtener estado para mostrar según el tipo de material"""
        if self.tipo_material == TipoMaterialChoices.ONU:
            return self.get_estado_onu_display() if self.estado_onu else 'Sin estado'
        else:
            return self.get_estado_general_display()

    @property
    def requiere_laboratorio(self):
        """Determinar si el material requiere ir a laboratorio"""
        if self.tipo_material == TipoMaterialChoices.ONU:
            return (self.es_nuevo and
                    self.tipo_origen == TipoIngresoChoices.NUEVO and
                    self.estado_onu == EstadoMaterialONUChoices.NUEVO)
        return False

    @property
    def puede_traspasar(self):
        """Verificar si el material puede ser traspasado"""
        estados_no_traspasables = [
            EstadoMaterialONUChoices.EN_LABORATORIO,
            EstadoMaterialONUChoices.DEFECTUOSO,
            EstadoMaterialONUChoices.DADO_DE_BAJA,
            EstadoMaterialGeneralChoices.DEFECTUOSO,
            EstadoMaterialGeneralChoices.DADO_DE_BAJA
        ]

        if self.tipo_material == TipoMaterialChoices.ONU:
            return self.estado_onu not in estados_no_traspasables
        else:
            return self.estado_general not in estados_no_traspasables

    @property
    def dias_en_laboratorio(self):
        """Calcular días que lleva en laboratorio"""
        if self.fecha_envio_laboratorio and not self.fecha_retorno_laboratorio:
            return (timezone.now() - self.fecha_envio_laboratorio).days
        return 0

    def enviar_a_laboratorio(self, usuario=None):
        """Enviar material a laboratorio"""
        if self.tipo_material == TipoMaterialChoices.ONU:
            self.estado_onu = EstadoMaterialONUChoices.EN_LABORATORIO
        self.fecha_envio_laboratorio = timezone.now()
        self.save()

    def retornar_de_laboratorio(self, resultado_exitoso=True, informe_numero=None, detalles=None):
        """Retornar material de laboratorio"""
        self.fecha_retorno_laboratorio = timezone.now()

        if self.tipo_material == TipoMaterialChoices.ONU:
            if resultado_exitoso:
                self.estado_onu = EstadoMaterialONUChoices.DISPONIBLE
            else:
                self.estado_onu = EstadoMaterialONUChoices.DEFECTUOSO

        self.save()


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
    estado = models.CharField(
        max_length=15,
        choices=EstadoTraspasoChoices.choices,
        default=EstadoTraspasoChoices.PENDIENTE
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

    def clean(self):
        # Validar número de solicitud
        if not (6 <= len(self.numero_solicitud) <= 10):
            raise ValidationError("El número de solicitud debe tener entre 6 y 10 dígitos")

        if not self.numero_solicitud.isdigit():
            raise ValidationError("El número de solicitud solo puede contener números")

        # Validar que origen y destino sean diferentes
        if self.almacen_origen == self.almacen_destino:
            raise ValidationError("El almacén origen y destino deben ser diferentes")

    def save(self, *args, **kwargs):
        if not self.numero_traspaso:
            self.numero_traspaso = self._generar_numero_traspaso()
        super().save(*args, **kwargs)

    def _generar_numero_traspaso(self):
        """Generar número de traspaso único"""
        import uuid
        while True:
            numero = f"TR-{timezone.now().year}-{str(uuid.uuid4().int)[:6]}"
            if not TraspasoAlmacen.objects.filter(numero_traspaso=numero).exists():
                return numero

    def confirmar_recepcion(self, usuario_recepcion, cantidad_recibida, observaciones=""):
        """Confirmar recepción del traspaso"""
        self.usuario_recepcion = usuario_recepcion
        self.cantidad_recibida = cantidad_recibida
        self.fecha_recepcion = timezone.now()
        self.observaciones_recepcion = observaciones
        self.estado = EstadoTraspasoChoices.RECIBIDO
        self.save()

        # Actualizar ubicación de materiales
        for material in self.materiales.all():
            material.almacen_actual = self.almacen_destino
            material.traspaso_actual = None
            material.save()

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


# ========== MODELO DE DEVOLUCIONES AL PROVEEDOR ==========

class DevolucionProveedor(models.Model):
    """Modelo para devoluciones al proveedor"""

    numero_devolucion = models.CharField(max_length=20, unique=True, help_text="Número único de devolución")
    lote_origen = models.ForeignKey(Lote, on_delete=models.CASCADE, help_text="Lote de donde provienen los materiales")
    proveedor = models.ForeignKey(Proveedor, on_delete=models.CASCADE)

    # Información de la devolución
    motivo = models.TextField(help_text="Motivo de la devolución basado en informe de laboratorio")
    numero_informe_laboratorio = models.CharField(max_length=50,
                                                  help_text="Número de informe de laboratorio que justifica la devolución")

    # Estado de la devolución
    estado = models.CharField(
        max_length=15,
        choices=EstadoDevolucionChoices.choices,
        default=EstadoDevolucionChoices.PENDIENTE
    )

    # Fechas
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_envio = models.DateTimeField(null=True, blank=True)
    fecha_confirmacion = models.DateTimeField(null=True, blank=True)

    # Respuesta del proveedor
    respuesta_proveedor = models.CharField(
        max_length=15,
        choices=RespuestaProveedorChoices.choices,
        default=RespuestaProveedorChoices.PENDIENTE
    )
    observaciones_proveedor = models.TextField(blank=True)

    # Auditoría
    created_by = models.ForeignKey(
        'usuarios.Usuario',
        on_delete=models.CASCADE,
        related_name='devoluciones_creadas'
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'almacenes_devolucion_proveedor'
        verbose_name = 'Devolución a Proveedor'
        verbose_name_plural = 'Devoluciones a Proveedores'

    def __str__(self):
        return f"{self.numero_devolucion} - {self.proveedor.nombre_comercial}"

    def save(self, *args, **kwargs):
        if not self.numero_devolucion:
            self.numero_devolucion = self._generar_numero_devolucion()
        super().save(*args, **kwargs)

    def _generar_numero_devolucion(self):
        """Generar número de devolución único"""
        import uuid
        while True:
            numero = f"DEV-{timezone.now().year}-{str(uuid.uuid4().int)[:6]}"
            if not DevolucionProveedor.objects.filter(numero_devolucion=numero).exists():
                return numero

    @property
    def cantidad_materiales(self):
        return self.materiales_devueltos.count()


class DevolucionMaterial(models.Model):
    """Materiales específicos incluidos en una devolución"""
    devolucion = models.ForeignKey(
        DevolucionProveedor,
        on_delete=models.CASCADE,
        related_name='materiales_devueltos'
    )
    material = models.ForeignKey(Material, on_delete=models.CASCADE)
    motivo_especifico = models.TextField(blank=True, help_text="Motivo específico para este material")

    class Meta:
        db_table = 'almacenes_devolucion_material'
        unique_together = ['devolucion', 'material']

    def __str__(self):
        return f"{self.devolucion.numero_devolucion} - {self.material.codigo_interno}"


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
    devolucion_relacionada = models.ForeignKey(
        DevolucionProveedor,
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


# ========== MODELO PARA COMPATIBILIDAD CON EQUIPOONU EXISTENTE ==========

class EquipoONU(models.Model):
    """Modelo existente - mantener para compatibilidad"""
    codigo_interno = models.CharField(max_length=50, unique=True)
    modelo = models.ForeignKey(Modelo, on_delete=models.CASCADE)
    tipo_equipo = models.ForeignKey(TipoEquipo, on_delete=models.CASCADE)
    lote = models.ForeignKey(Lote, on_delete=models.CASCADE)
    mac_address = models.CharField(max_length=17, unique=True)
    gpon_serial = models.CharField(max_length=100, unique=True)
    serial_manufacturer = models.CharField(max_length=100, unique=True)
    fecha_ingreso = models.DateField(auto_now_add=True)
    estado = models.ForeignKey(EstadoEquipo, on_delete=models.SET_NULL, null=True, blank=True)
    observaciones = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.codigo_interno} - {self.modelo}"

    class Meta:
        db_table = 'almacenes_equipo_onu'


class EquipoServicio(models.Model):
    """Relación entre equipos y contratos/servicios - mantener para compatibilidad"""
    equipo_onu = models.ForeignKey(EquipoONU, on_delete=models.CASCADE)
    contrato = models.ForeignKey('contratos.Contrato', on_delete=models.CASCADE)
    servicio = models.ForeignKey('contratos.Servicio', on_delete=models.CASCADE)
    fecha_asignacion = models.DateField(auto_now_add=True)
    fecha_desasignacion = models.DateField(null=True, blank=True)
    estado_asignacion = models.CharField(max_length=20, default='ACTIVO', choices=[
        ('ACTIVO', 'Activo'),
        ('SUSPENDIDO', 'Suspendido'),
        ('CANCELADO', 'Cancelado'),
    ])
    observaciones = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'almacenes_equipo_servicio'