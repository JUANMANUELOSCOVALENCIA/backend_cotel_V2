from django.db import models

class Marca(models.Model):
    nombre = models.CharField(max_length=100, unique=True)
    descripcion = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.nombre

    class Meta:
        db_table = 'almacenes_marca'


class TipoEquipo(models.Model):
    nombre = models.CharField(max_length=50, unique=True)
    descripcion = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.nombre

    class Meta:
        db_table = 'almacenes_tipo_equipo'


class Componente(models.Model):
    nombre = models.CharField(max_length=100, unique=True)
    descripcion = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.nombre

    class Meta:
        db_table = 'almacenes_componente'


class EstadoEquipo(models.Model):
    nombre = models.CharField(max_length=50, unique=True)
    descripcion = models.TextField(blank=True)
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
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.marca.nombre} {self.nombre} ({self.codigo_modelo})"

    class Meta:
        unique_together = ['marca', 'nombre']
        db_table = 'almacenes_modelo'


class ModeloComponente(models.Model):
    modelo = models.ForeignKey(Modelo, on_delete=models.CASCADE)
    componente = models.ForeignKey(Componente, on_delete=models.CASCADE)
    cantidad = models.SmallIntegerField(default=1)

    class Meta:
        unique_together = ['modelo', 'componente']
        db_table = 'almacenes_modelo_componente'


class Lote(models.Model):
    numero_lote = models.CharField(max_length=50, unique=True)
    proveedor = models.CharField(max_length=100)
    # Importar TipoServicio desde la app contratos
    tipo_servicio = models.ForeignKey('contratos.TipoServicio', on_delete=models.CASCADE)
    fecha_ingreso = models.DateField(auto_now_add=True)
    observaciones = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.numero_lote} - {self.proveedor}"

    @property
    def cantidad_total(self):
        return sum(detalle.cantidad for detalle in self.detalles.all())

    class Meta:
        db_table = 'almacenes_lote'


class LoteDetalle(models.Model):
    lote = models.ForeignKey(Lote, on_delete=models.CASCADE, related_name='detalles')
    modelo = models.ForeignKey(Modelo, on_delete=models.CASCADE)
    cantidad = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['lote', 'modelo']
        db_table = 'almacenes_lote_detalle'


class EquipoONU(models.Model):
    codigo_interno = models.CharField(max_length=50, unique=True)
    modelo = models.ForeignKey(Modelo, on_delete=models.CASCADE)
    tipo_equipo = models.ForeignKey(TipoEquipo, on_delete=models.CASCADE)
    lote = models.ForeignKey(Lote, on_delete=models.CASCADE)
    mac_address = models.CharField(max_length=17, unique=True)  # PostgreSQL MACADDR como CharField
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
    """Relación entre equipos y contratos/servicios"""
    equipo_onu = models.ForeignKey(EquipoONU, on_delete=models.CASCADE)
    # Relacionar con el contrato en lugar de solicitud
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
