# ======================================================
# python manage.py cargar_materiales_gpon [--inventario]
#
# Catálogo de MATERIALES DE INSTALACIÓN GPON (por cantidad) y los KITS por tipo de trabajo,
# que sugieren el despacho diario de cada cuadrilla:
#   cable drop (m), roseta óptica, patch cord SC/APC, conector rápido SC/APC, triplexor,
#   tensor/gancho de retención para drop, grapas.
# Las ONU NO van aquí: son equipos con serie y se registran por lotes en Almacenes.
#
#   --inventario   además crea un lote de stock inicial de estos materiales en cada almacén activo
#                  (proveedor "Distribuidora FTTH"), para poder despachar. Solo para desarrollo.
#
# Se puede ejecutar varias veces: no duplica (busca por nombre) y no cambia lo que ya editaste.
# Los kits y cantidades se ajustan en Operaciones › Cuadrillas › Kits de material.
# ======================================================
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from almacenes.models import (Almacen, EstadoLote, EstadoMaterialGeneral, Lote, LoteDetalle, Marca, Material, Modelo, Proveedor,
                              TipoIngreso, TipoMaterial, UnidadMedida)
from operaciones.models import KitMaterial
from usuarios.models import Usuario

# (código de tipo, nombre del tipo, unidad, nombre del modelo, descripción, stock inicial)
MATERIALES = [
    ('DROP', 'Cable drop', 'm', 'Cable drop FTTH 1 hilo', 'Acometida de fibra desde la NAP hasta el domicilio', 3000),
    ('ROSETA', 'Roseta óptica', 'pza', 'Roseta óptica 1 puerto SC/APC', 'Terminación del drop dentro del domicilio', 100),
    ('PATCHCORD', 'Patch cord', 'pza', 'Patch cord SC/APC - SC/APC 3 m', 'Une la roseta con la ONU', 150),
    ('CONECTOR', 'Conector de fibra', 'pza', 'Conector rápido SC/APC', 'Conectorización en campo del drop', 300),
    ('TRIPLEXOR', 'Triplexor', 'pza', 'Triplexor CATV', 'Separa la señal de TV cable (RF) de la fibra', 50),
    ('TENSOR', 'Herraje de retención', 'pza', 'Tensor / gancho de retención para drop', 'Sujeta el drop en postes y fachada', 400),
    ('GRAPA', 'Grapa de sujeción', 'pza', 'Grapa para cable drop', 'Fija el drop en paredes (bolsa de 100)', 2000),
]
UNIDADES = {'m': ('M', 'Metro'), 'pza': ('PZA', 'Pieza')}

# (tipo de trabajo, condición, nombre del modelo, cantidad)
KITS = [
    ('INSTALACION', 'SIEMPRE', 'Cable drop FTTH 1 hilo', 80),
    ('INSTALACION', 'SIEMPRE', 'Roseta óptica 1 puerto SC/APC', 1),
    ('INSTALACION', 'SIEMPRE', 'Patch cord SC/APC - SC/APC 3 m', 1),
    ('INSTALACION', 'SIEMPRE', 'Conector rápido SC/APC', 2),
    ('INSTALACION', 'SIEMPRE', 'Tensor / gancho de retención para drop', 2),
    ('INSTALACION', 'SIEMPRE', 'Grapa para cable drop', 15),
    ('INSTALACION', 'TV', 'Triplexor CATV', 1),
    ('TRASLADO', 'SIEMPRE', 'Cable drop FTTH 1 hilo', 80),
    ('TRASLADO', 'SIEMPRE', 'Roseta óptica 1 puerto SC/APC', 1),
    ('TRASLADO', 'SIEMPRE', 'Conector rápido SC/APC', 2),
    ('TRASLADO', 'SIEMPRE', 'Tensor / gancho de retención para drop', 2),
    ('TRASLADO', 'SIEMPRE', 'Grapa para cable drop', 15),
    ('REPARACION', 'SIEMPRE', 'Conector rápido SC/APC', 2),
    ('REPARACION', 'SIEMPRE', 'Patch cord SC/APC - SC/APC 3 m', 1),
]


class Command(BaseCommand):
    help = 'Catálogo de materiales de instalación GPON y kits por tipo de trabajo (y stock inicial con --inventario).'

    def add_arguments(self, parser):
        parser.add_argument('--inventario', action='store_true', help='Crear un lote de stock inicial en cada almacén activo')

    @transaction.atomic
    def handle(self, *args, **opts):
        marca = Marca.objects.filter(nombre__iexact='Genérico').first() or Marca.objects.create(nombre='Genérico')
        siguiente = max((Modelo.objects.aggregate(m=Max('codigo_modelo'))['m'] or 0) + 1, 900001)
        modelos, nuevos = {}, 0
        for codigo, tipo_nombre, simbolo, nombre, desc, _ in MATERIALES:
            unidad = UnidadMedida.objects.filter(simbolo__iexact=simbolo).first()
            if not unidad:
                ucod, unom = UNIDADES[simbolo]
                unidad = UnidadMedida.objects.filter(codigo=ucod).first() or UnidadMedida.objects.create(codigo=ucod, nombre=unom, simbolo=simbolo)
            tipo = TipoMaterial.objects.filter(nombre__iexact=tipo_nombre).first() or TipoMaterial.objects.filter(codigo=codigo).first()
            if not tipo:
                tipo = TipoMaterial.objects.create(codigo=codigo, nombre=tipo_nombre, unidad_medida_default=unidad, es_unico=False,
                                                   requiere_inspeccion_inicial=False)
            modelo = Modelo.objects.filter(nombre__iexact=nombre).first()
            if not modelo:
                modelo = Modelo.objects.create(marca=marca, nombre=nombre, codigo_modelo=siguiente, descripcion=desc, tipo_material=tipo,
                                               unidad_medida=unidad, requiere_inspeccion_inicial=False)
                siguiente += 1
                nuevos += 1
            modelos[nombre] = modelo
        self.stdout.write(f'Materiales de instalación GPON: {len(modelos)} ({nuevos} nuevos)')

        kits = 0
        for tipo, condicion, nombre, cantidad in KITS:
            _, creado = KitMaterial.objects.get_or_create(tipo=tipo, condicion=condicion, modelo=modelos[nombre],
                                                          defaults={'cantidad': Decimal(cantidad)})
            kits += creado
        self.stdout.write(f'Kits por tipo de trabajo: {kits} línea(s) nuevas')

        if opts['inventario']:
            self._inventario(modelos)

    def _inventario(self, modelos):
        usuario = Usuario.objects.filter(is_superuser=True).order_by('id').first() or Usuario.objects.order_by('id').first()
        disponible = EstadoMaterialGeneral.objects.filter(codigo='DISPONIBLE').first()
        ingreso = TipoIngreso.objects.filter(codigo='NUEVO').first()
        estado_lote = EstadoLote.objects.filter(codigo='RECEPCION_COMPLETA').first() or EstadoLote.objects.order_by('id').first()
        if not (usuario and disponible and ingreso and estado_lote):
            self.stderr.write('Faltan catálogos de almacén (estado DISPONIBLE, tipo de ingreso NUEVO o estados de lote): no se creó stock.')
            return
        proveedor = Proveedor.objects.filter(nombre_comercial='Distribuidora FTTH').first() or \
            Proveedor.objects.create(nombre_comercial='Distribuidora FTTH', razon_social='Distribuidora FTTH')
        hoy = timezone.localdate()
        for almacen in Almacen.objects.filter(activo=True):
            numero = f'MAT-{almacen.codigo}-001'
            if Lote.objects.filter(numero_lote=numero).exists():
                self.stdout.write(f'{almacen.nombre}: ya tiene el lote {numero}')
                continue
            lote = Lote.objects.create(numero_lote=numero, tipo_ingreso=ingreso, proveedor=proveedor, almacen_destino=almacen,
                                       estado=estado_lote, fecha_recepcion=hoy, fecha_inicio_garantia=hoy, fecha_fin_garantia=hoy,
                                       observaciones='Stock inicial de materiales de instalación', created_by=usuario)
            for _, _, _, nombre, _, stock in MATERIALES:
                modelo = modelos[nombre]
                LoteDetalle.objects.create(lote=lote, modelo=modelo, cantidad=stock)
                m = Material(tipo_material=modelo.tipo_material, modelo=modelo, lote=lote, tipo_origen=ingreso,
                             codigo_item_equipo=str(modelo.codigo_modelo).zfill(6)[:10], almacen_actual=almacen,
                             estado_general=disponible, cantidad=Decimal(stock))
                m._usuario = usuario
                m.save()
            self.stdout.write(f'{almacen.nombre}: lote {numero} con {len(MATERIALES)} materiales')
