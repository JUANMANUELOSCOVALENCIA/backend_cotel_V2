# ======================================================
# operaciones/deuda.py
# ¿El cliente debe a COTEL? Se revisa por CI sumando sus contratos
# (contratos.Contrato.facturas_pendientes / monto_deuda).
#
# Los datos viven en el mismo PostgreSQL. Hoy se cargan con
# `python manage.py cargar_clientes` (datos del proyecto bigdata); cuando haya
# datos oficiales se cargan en las mismas tablas y esto sigue funcionando igual.
#
# Reglas (opcionales en settings.py):
#   DEUDA_FACTURAS_BLOQUEO = 2   se bloquea si ALGÚN contrato tiene esta cantidad o más de facturas impagas
#                                (una empresa con muchas líneas que solo debe el mes en curso no se bloquea)
#   DEUDA_TIPOS_BLOQUEADOS = ('INSTALACION', 'TRASLADO')
# ======================================================
from decimal import Decimal

from django.conf import settings
from django.db.models import Max


def bs(monto):
    """Bs 36.809,91 (formato boliviano)"""
    return 'Bs ' + f'{monto:,.2f}'.replace(',', '_').replace('.', ',').replace('_', '.')


def facturas_bloqueo():
    return int(getattr(settings, 'DEUDA_FACTURAS_BLOQUEO', 2))


def tipos_bloqueados():
    return tuple(getattr(settings, 'DEUDA_TIPOS_BLOQUEADOS', ('INSTALACION', 'TRASLADO')))


def normalizar_ci(ci):
    return ''.join(str(ci or '').split()).upper()


def consultar(ci):
    """{'fecha_corte', 'contratos': [...], 'facturas', 'monto', 'bloquea', 'mensaje', 'facturas_bloqueo'}"""
    from contratos.models import Contrato
    ci = normalizar_ci(ci)
    qs = Contrato.objects.filter(cliente__ci=ci, facturas_pendientes__gt=0).order_by('numero_contrato')
    corte = qs.aggregate(m=Max('deuda_actualizada'))['m']
    contratos = [{
        'contrato': c.numero_contrato,
        'servicio': ', '.join(s.plan_comercial.nombre for s in c.servicios.all()) or 'Servicio',
        'anulado': c.estado_contrato == 'CANCELADO',
        'facturas': c.facturas_pendientes,
        'monto': float(c.monto_deuda),
    } for c in qs.prefetch_related('servicios__plan_comercial')]
    facturas = sum(c['facturas'] for c in contratos)
    monto = sum((Decimal(str(c['monto'])) for c in contratos), Decimal('0'))
    morosos = [c for c in contratos if c['facturas'] >= facturas_bloqueo()]
    bloquea = bool(morosos)
    for c in contratos:
        c['bloquea'] = c['facturas'] >= facturas_bloqueo()
    if bloquea:
        mensaje = (f'El cliente tiene {facturas} factura(s) impaga(s) por {bs(monto)}; '
                   f'{len(morosos)} contrato(s) con {facturas_bloqueo()} o más meses sin pagar. '
                   'Debe regularizar su deuda antes de solicitar.')
    elif facturas:
        mensaje = f'El cliente tiene {facturas} factura(s) pendiente(s) por {bs(monto)} (no bloquea).'
    else:
        mensaje = 'Sin deuda registrada.'
    return {
        'disponible': True, 'fecha_corte': corte, 'contratos': contratos,
        'facturas': facturas, 'monto': float(monto), 'bloquea': bloquea, 'mensaje': mensaje,
        'facturas_bloqueo': facturas_bloqueo(),
    }
