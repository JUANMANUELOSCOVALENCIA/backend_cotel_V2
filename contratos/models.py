from django.db import models
from django.db.models import Max


class Cliente(models.Model):
    ci = models.CharField(max_length=15, unique=True)
    nombres = models.CharField(max_length=100)
    apellidos = models.CharField(max_length=100)
    direccion = models.TextField(blank=True)
    telefono = models.CharField(max_length=20, blank=True)
    # Campos adicionales para compatibilidad con solicitudes
    telefono_alternativo = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    zona = models.CharField(max_length=100, blank=True)
    ciudad = models.CharField(max_length=100, default='La Paz')
    estado = models.CharField(max_length=20, default='ACTIVO', choices=[
        ('ACTIVO', 'Activo'),
        ('SUSPENDIDO', 'Suspendido'),
        ('INACTIVO', 'Inactivo'),
    ])
    fecha_registro = models.DateField(auto_now_add=True)
    observaciones = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.nombres} {self.apellidos}"

    class Meta:
        db_table = 'contratos_cliente'


class TipoTramite(models.Model):
    nombre = models.CharField(max_length=50, unique=True)
    descripcion = models.TextField(blank=True)
    activo = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.nombre

    class Meta:
        db_table = 'contratos_tipo_tramite'


class FormaPago(models.Model):
    nombre = models.CharField(max_length=50, unique=True)
    descripcion = models.TextField(blank=True)
    activo = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.nombre

    class Meta:
        db_table = 'contratos_forma_pago'


class TipoServicio(models.Model):
    nombre = models.CharField(max_length=50, unique=True)
    descripcion = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.nombre

    class Meta:
        db_table = 'contratos_tipo_servicio'


class PlanComercial(models.Model):
    tipo_servicio = models.ForeignKey(TipoServicio, on_delete=models.CASCADE)
    nombre = models.CharField(max_length=100)
    codigo_plan = models.CharField(max_length=50, unique=True)
    velocidad_descarga = models.IntegerField(null=True, blank=True)  # Mbps
    velocidad_subida = models.IntegerField(null=True, blank=True)  # Mbps
    precio_mensual = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    precio_instalacion = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    descripcion = models.TextField(blank=True)
    activo = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.nombre} ({self.tipo_servicio.nombre})"

    class Meta:
        db_table = 'contratos_plan_comercial'


class Contrato(models.Model):
    numero_contrato = models.CharField(max_length=8, unique=True, blank=True)
    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE, related_name='contratos')
    fecha_firma = models.DateField(auto_now_add=True)
    # Campos adicionales para integración con solicitudes
    tipo_tramite = models.ForeignKey(TipoTramite, on_delete=models.CASCADE, null=True, blank=True)
    forma_pago = models.ForeignKey(FormaPago, on_delete=models.CASCADE, null=True, blank=True)
    estado_contrato = models.CharField(max_length=20, default='ACTIVO', choices=[
        ('PENDIENTE', 'Pendiente'),
        ('ACTIVO', 'Activo'),
        ('SUSPENDIDO', 'Suspendido'),
        ('CANCELADO', 'Cancelado'),
    ])
    direccion_instalacion = models.TextField()
    observaciones = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.numero_contrato:
            ultimo = Contrato.objects.aggregate(max_num=Max('numero_contrato'))['max_num'] or '00000000'
            siguiente = str(int(ultimo) + 1).zfill(8)
            if int(siguiente) < 80000000:
                siguiente = '80000000'
            self.numero_contrato = siguiente
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Contrato {self.numero_contrato} de {self.cliente}"

    class Meta:
        db_table = 'contratos_contrato'


class Servicio(models.Model):
    contrato = models.ForeignKey(Contrato, on_delete=models.CASCADE, related_name='servicios')
    plan_comercial = models.ForeignKey(PlanComercial, on_delete=models.CASCADE)
    fecha_activacion = models.DateField(auto_now_add=True)
    fecha_desactivacion = models.DateField(null=True, blank=True)
    estado_servicio = models.CharField(max_length=20, default='ACTIVO', choices=[
        ('ACTIVO', 'Activo'),
        ('SUSPENDIDO', 'Suspendido'),
        ('CANCELADO', 'Cancelado'),
    ])
    observaciones = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.plan_comercial.nombre} - {self.contrato.numero_contrato}"

    class Meta:
        unique_together = ['contrato', 'plan_comercial']
        db_table = 'contratos_servicio'


class OrdenTrabajo(models.Model):
    numero_ot = models.CharField(max_length=20, unique=True, blank=True)
    contrato = models.ForeignKey(Contrato, on_delete=models.CASCADE, related_name='ordenes_trabajo')
    tecnico_asignado = models.CharField(max_length=100, blank=True)
    fecha_asignacion = models.DateField(null=True, blank=True)
    fecha_programada = models.DateField(null=True, blank=True)
    fecha_ejecucion = models.DateField(null=True, blank=True)
    estado_ot = models.CharField(max_length=20, default='PENDIENTE', choices=[
        ('PENDIENTE', 'Pendiente'),
        ('ASIGNADA', 'Asignada'),
        ('EN_PROCESO', 'En Proceso'),
        ('COMPLETADA', 'Completada'),
        ('CANCELADA', 'Cancelada'),
    ])
    tipo_trabajo = models.CharField(max_length=50)
    observaciones_tecnico = models.TextField(blank=True)
    materiales_utilizados = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.numero_ot:
            from datetime import datetime
            anio = datetime.now().year
            ultimo = OrdenTrabajo.objects.filter(
                numero_ot__startswith=f'OT{anio}'
            ).aggregate(
                max_num=Max('numero_ot')
            )['max_num']

            if ultimo:
                siguiente_num = int(ultimo[6:]) + 1
            else:
                siguiente_num = 1

            self.numero_ot = f'OT{anio}{str(siguiente_num).zfill(4)}'
        super().save(*args, **kwargs)

    def __str__(self):
        return f"OT {self.numero_ot} - {self.contrato.numero_contrato}"

    class Meta:
        db_table = 'contratos_orden_trabajo'
