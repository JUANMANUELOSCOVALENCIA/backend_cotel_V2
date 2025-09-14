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


class EstadoDevolucion(models.Model):
    """Estados de devoluciones a proveedores"""
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
        db_table = 'almacenes_estado_devolucion'
        verbose_name = 'Estado de Devolución'
        verbose_name_plural = 'Estados de Devolución'
        ordering = ['orden', 'nombre']

    def __str__(self):
        return self.nombre


class RespuestaProveedor(models.Model):
    """Respuestas de proveedores a devoluciones"""
    codigo = models.CharField(max_length=20, unique=True)
    nombre = models.CharField(max_length=50)
    descripcion = models.TextField(blank=True)
    activo = models.BooleanField(default=True)
    orden = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'almacenes_respuesta_proveedor'
        verbose_name = 'Respuesta de Proveedor'
        verbose_name_plural = 'Respuestas de Proveedor'
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
                encargado = Usuario.objects.get(codigo_cotel=self.codigo_cotel_encargado)
                self.encargado = encargado
            except Usuario.DoesNotExist:
                raise ValidationError(f"No se encontró usuario con código COTEL: {self.codigo_cotel_encargado}")

    def save(self, *args, **kwargs):
        # Auto-asignar encargado por código COTEL
        if self.codigo_cotel_encargado and not self.encargado:
            try:
                from usuarios.models import Usuario
                self.encargado = Usuario.objects.get(codigocotel=self.codigo_cotel_encargado)
            except Usuario.DoesNotExist:
                pass

        super().save(*args, **kwargs)

    @property
    def encargado_info(self):
        """Información del encargado para la API"""
        if self.encargado:
            return {
                'id': self.encargado.id,
                'codigo_cotel': self.encargado.codigo_cotel,
                'nombre_completo': self.encargado.nombre_completo,
                'email': self.encargado.email,
                'telefono': getattr(self.encargado, 'telefono', ''),
                'cargo': getattr(self.encargado, 'cargo', '')
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

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.marca.nombre} {self.nombre} ({self.codigo_modelo})"

    class Meta:
        unique_together = ['marca', 'nombre']
        db_table = 'almacenes_modelo'

    def save(self, *args, **kwargs):
        # Heredar configuraciones del tipo de material si no están establecidas
        if self.tipo_material:
            if not self.unidad_medida_id:
                self.unidad_medida = self.tipo_material.unidad_medida_default

            if not hasattr(self, '_inspeccion_set'):
                self.requiere_inspeccion_inicial = self.tipo_material.requiere_inspeccion_inicial

        super().save(*args, **kwargs)


class ModeloComponente(models.Model):
    modelo = models.ForeignKey(Modelo, on_delete=models.CASCADE)
    componente = models.ForeignKey(Componente, on_delete=models.CASCADE)
    cantidad = models.SmallIntegerField(default=1)

    class Meta:
        unique_together = ['modelo', 'componente']
        db_table = 'almacenes_modelo_componente'


# ========== MODELO DE LOTE ==========

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

    @property
    def cantidad_total(self):
        return sum(detalle.cantidad for detalle in self.detalles.all())

    @property
    def cantidad_recibida(self):
        return self.material_set.count()

    @property
    def cantidad_pendiente(self):
        return max(0, self.cantidad_total - self.cantidad_recibida)

    @property
    def porcentaje_recibido(self):
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
        return self.lote.material_set.filter(modelo=self.modelo).count()

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
                try:
                    estado_nuevo = EstadoMaterialONU.objects.get(codigo='NUEVO', activo=True)
                    self.estado_onu = estado_nuevo
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

        super().save(*args, **kwargs)

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
        if self.tipo_material.es_unico:
            try:
                estado_laboratorio = EstadoMaterialONU.objects.get(codigo='EN_LABORATORIO', activo=True)
                self.estado_onu = estado_laboratorio
            except EstadoMaterialONU.DoesNotExist:
                pass

        self.fecha_envio_laboratorio = timezone.now()
        self.save()

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
    estado = models.ForeignKey(
        EstadoDevolucion,
        on_delete=models.CASCADE,
        help_text="Estado actual de la devolución"
    )

    # Fechas
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_envio = models.DateTimeField(null=True, blank=True)
    fecha_confirmacion = models.DateTimeField(null=True, blank=True)

    # Respuesta del proveedor
    respuesta_proveedor = models.ForeignKey(
        RespuestaProveedor,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text="Respuesta del proveedor a la devolución"
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

        # Asignar estado inicial si no tiene
        if not self.estado_id:
            try:
                estado_pendiente = EstadoDevolucion.objects.get(codigo='PENDIENTE', activo=True)
                self.estado = estado_pendiente
            except EstadoDevolucion.DoesNotExist:
                pass

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

    # Resultado general
    aprobado = models.BooleanField()

    # Observaciones
    observaciones_tecnico = models.TextField(blank=True)
    comentarios_adicionales = models.TextField(blank=True)
    fallas_detectadas = models.JSONField(default=list, blank=True)

    # Información del proceso
    tecnico_revisor = models.CharField(max_length=50, blank=True)
    tiempo_inspeccion_minutos = models.PositiveIntegerField(default=0)

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

# ========== FUNCIÓN PARA CREAR DATOS INICIALES ==========

def crear_datos_iniciales():
    """Función para crear todos los datos iniciales del sistema"""

    # 1. Unidades de Medida
    unidades = [
        ('PIEZA', 'Pieza', 'pza'),
        ('UNIDAD', 'Unidad', 'und'),
        ('METROS', 'Metros', 'm'),
        ('CAJA', 'Caja', 'cja'),
        ('ROLLO', 'Rollo', 'rll'),
        ('KIT', 'Kit', 'kit'),
        ('PAQUETE', 'Paquete', 'pqt'),
    ]

    for codigo, nombre, simbolo in unidades:
        UnidadMedida.objects.get_or_create(
            codigo=codigo,
            defaults={'nombre': nombre, 'simbolo': simbolo, 'orden': len(unidades)}
        )

    # 2. Tipos de Ingreso
    tipos_ingreso = [
        ('NUEVO', 'Nuevo', 'Ingreso de materiales nuevos'),
        ('REINGRESO', 'Reingreso', 'Reingreso de materiales devueltos'),
        ('DEVOLUCION', 'Devolución', 'Devolución de materiales de campo'),
        ('LABORATORIO', 'Laboratorio', 'Materiales provenientes de laboratorio'),
    ]

    for i, (codigo, nombre, desc) in enumerate(tipos_ingreso):
        TipoIngreso.objects.get_or_create(
            codigo=codigo,
            defaults={'nombre': nombre, 'descripcion': desc, 'orden': i}
        )

    # 3. Estados de Lote
    estados_lote = [
        ('REGISTRADO', 'Registrado', '#9CA3AF', False),
        ('PENDIENTE_RECEPCION', 'Pendiente Recepción', '#F59E0B', False),
        ('RECEPCION_PARCIAL', 'Recepción Parcial', '#3B82F6', False),
        ('RECEPCION_COMPLETA', 'Recepción Completa', '#10B981', False),
        ('ACTIVO', 'Activo', '#059669', False),
        ('CERRADO', 'Cerrado', '#6B7280', True),
    ]

    for i, (codigo, nombre, color, es_final) in enumerate(estados_lote):
        EstadoLote.objects.get_or_create(
            codigo=codigo,
            defaults={'nombre': nombre, 'color': color, 'es_final': es_final, 'orden': i}
        )

    # 4. Estados de Traspaso
    estados_traspaso = [
        ('PENDIENTE', 'Pendiente', '#F59E0B', False),
        ('EN_TRANSITO', 'En Tránsito', '#3B82F6', False),
        ('RECIBIDO', 'Recibido', '#10B981', True),
        ('CANCELADO', 'Cancelado', '#EF4444', True),
    ]

    for i, (codigo, nombre, color, es_final) in enumerate(estados_traspaso):
        EstadoTraspaso.objects.get_or_create(
            codigo=codigo,
            defaults={'nombre': nombre, 'color': color, 'es_final': es_final, 'orden': i}
        )

    # 5. Estados de Material ONU
    estados_onu = [
        ('NUEVO', 'Nuevo', '#9CA3AF', False, False),
        ('DISPONIBLE', 'Disponible', '#10B981', True, True),
        ('RESERVADO', 'Reservado', '#F59E0B', False, True),
        ('ASIGNADO', 'Asignado', '#3B82F6', False, False),
        ('INSTALADO', 'Instalado', '#8B5CF6', False, False),
        ('EN_LABORATORIO', 'En Laboratorio', '#F97316', False, False),
        ('DEFECTUOSO', 'Defectuoso', '#EF4444', False, False),
        ('DEVUELTO_PROVEEDOR', 'Devuelto a Proveedor', '#6B7280', False, False),
        ('REINGRESADO', 'Reingresado', '#06B6D4', True, True),
        ('DADO_DE_BAJA', 'Dado de Baja', '#374151', False, False),
    ]

    for i, (codigo, nombre, color, permite_asig, permite_tras) in enumerate(estados_onu):
        EstadoMaterialONU.objects.get_or_create(
            codigo=codigo,
            defaults={
                'nombre': nombre,
                'color': color,
                'permite_asignacion': permite_asig,
                'permite_traspaso': permite_tras,
                'orden': i
            }
        )

    # 6. Estados de Material General
    estados_general = [
        ('DISPONIBLE', 'Disponible', '#10B981', True, True),
        ('RESERVADO', 'Reservado', '#F59E0B', False, True),
        ('ASIGNADO', 'Asignado', '#3B82F6', False, False),
        ('CONSUMIDO', 'Consumido', '#6B7280', False, False),
        ('DEFECTUOSO', 'Defectuoso', '#EF4444', False, False),
        ('DADO_DE_BAJA', 'Dado de Baja', '#374151', False, False),
    ]

    for i, (codigo, nombre, color, permite_cons, permite_tras) in enumerate(estados_general):
        EstadoMaterialGeneral.objects.get_or_create(
            codigo=codigo,
            defaults={
                'nombre': nombre,
                'color': color,
                'permite_consumo': permite_cons,
                'permite_traspaso': permite_tras,
                'orden': i
            }
        )

    # 7. Tipos de Almacén
    tipos_almacen = [
        ('PRINCIPAL', 'Principal'),
        ('REGIONAL', 'Regional'),
        ('TEMPORAL', 'Temporal'),
    ]

    for i, (codigo, nombre) in enumerate(tipos_almacen):
        TipoAlmacen.objects.get_or_create(
            codigo=codigo,
            defaults={'nombre': nombre, 'orden': i}
        )

    # 8. Estados de Devolución
    estados_devolucion = [
        ('PENDIENTE', 'Pendiente', '#F59E0B', False),
        ('ENVIADO', 'Enviado', '#3B82F6', False),
        ('CONFIRMADO', 'Confirmado', '#10B981', True),
        ('RECHAZADO', 'Rechazado', '#EF4444', True),
    ]

    for i, (codigo, nombre, color, es_final) in enumerate(estados_devolucion):
        EstadoDevolucion.objects.get_or_create(
            codigo=codigo,
            defaults={'nombre': nombre, 'color': color, 'es_final': es_final, 'orden': i}
        )

    # 9. Respuestas de Proveedor
    respuestas = [
        ('REPOSICION', 'Reposición'),
        ('CREDITO', 'Crédito'),
        ('RECHAZO', 'Rechazo'),
        ('PENDIENTE', 'Pendiente'),
    ]

    for i, (codigo, nombre) in enumerate(respuestas):
        RespuestaProveedor.objects.get_or_create(
            codigo=codigo,
            defaults={'nombre': nombre, 'orden': i}
        )

    # 10. Tipos de Material
    unidad_pieza = UnidadMedida.objects.get(codigo='PIEZA')
    unidad_metros = UnidadMedida.objects.get(codigo='METROS')

    tipos_material = [
        ('ONU', 'Equipo ONU', 'Equipos de red de fibra óptica (ONUs)', unidad_pieza, True, True),
        ('CABLE_DROP', 'Cable Drop', 'Cable de fibra óptica para conexión domiciliaria', unidad_metros, False, False),
        ('CONECTOR_APC', 'Conector APC', 'Conectores ópticos tipo APC', unidad_pieza, False, False),
        ('CONECTOR_UPC', 'Conector UPC', 'Conectores ópticos tipo UPC', unidad_pieza, False, False),
        ('ROSETA_OPTICA', 'Roseta Óptica', 'Rosetas para instalación óptica domiciliaria', unidad_pieza, False, False),
        ('PATCH_CORE', 'Patch Core', 'Cables patch para core de red', unidad_pieza, False, False),
        ('TRIPLEXOR', 'Triplexor', 'Dispositivos triplexores para red óptica', unidad_pieza, False, False),
    ]

    for i, (codigo, nombre, desc, unidad, inspeccion, es_unico) in enumerate(tipos_material):
        TipoMaterial.objects.get_or_create(
            codigo=codigo,
            defaults={
                'nombre': nombre,
                'descripcion': desc,
                'unidad_medida_default': unidad,
                'requiere_inspeccion_inicial': inspeccion,
                'es_unico': es_unico,
                'orden': i
            }
        )