# ======================================================
# python manage.py cargar_planes_ejemplo
#
# Crea planes de internet y adicionales (TV cable / telefonía) DE EJEMPLO.
# Solo crea los que no existen (por código de plan / tipo + nombre); no modifica
# los que ya registraste. Cambia precios y nombres desde la pantalla Planes.
# ======================================================
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from contratos.models import PlanComercial, TipoServicio
from operaciones.models import PlanAdicional

PLANES = [
    # código, nombre, bajada, subida, mensual, instalación
    ('FIBRA-20', 'Fibra 20', 20, 10, '99', '0'),
    ('FIBRA-40', 'Fibra 40', 40, 20, '119', '0'),
    ('FIBRA-60', 'Fibra 60', 60, 30, '129', '0'),
    ('FIBRA-100', 'Fibra 100', 100, 50, '169', '0'),
]

ADICIONALES = [
    # tipo, nombre, mensual, instalación, incluidas, extra c/u, máximo, descripción
    ('TV', 'TV Básica', '50', '30', 1, '15', 5, 'Canales básicos; incluye 1 televisor'),
    ('TV', 'TV Familiar', '70', '30', 2, '15', 6, 'Más canales; incluye 2 televisores'),
    ('TELEFONIA', 'Línea fija', '25', '0', 1, '20', 2, 'Telefonía sobre GPON; incluye 1 línea'),
]


class Command(BaseCommand):
    help = 'Carga planes de internet y adicionales de ejemplo (no pisa los existentes).'

    @transaction.atomic
    def handle(self, *args, **o):
        internet, _ = TipoServicio.objects.get_or_create(nombre='Internet')
        creados_p = 0
        for codigo, nombre, baja, sube, mensual, inst in PLANES:
            _, nuevo = PlanComercial.objects.get_or_create(codigo_plan=codigo, defaults={
                'tipo_servicio': internet, 'nombre': nombre, 'velocidad_descarga': baja, 'velocidad_subida': sube,
                'precio_mensual': Decimal(mensual), 'precio_instalacion': Decimal(inst), 'activo': True,
                'descripcion': 'Plan de ejemplo',
            })
            creados_p += nuevo
        creados_a = 0
        for tipo, nombre, mensual, inst, incl, extra, maximo, desc in ADICIONALES:
            if PlanAdicional.objects.filter(tipo=tipo, nombre__iexact=nombre).exists():
                continue
            PlanAdicional.objects.create(tipo=tipo, nombre=nombre, precio_mensual=Decimal(mensual),
                                         costo_instalacion=Decimal(inst), unidades_incluidas=incl,
                                         precio_unidad_extra=Decimal(extra), maximo_unidades=maximo, descripcion=desc)
            creados_a += 1
        self.stdout.write(self.style.SUCCESS(
            f'Planes de internet creados: {creados_p} de {len(PLANES)} · Adicionales creados: {creados_a} de {len(ADICIONALES)} '
            '(los que ya existían no se tocaron)'))
