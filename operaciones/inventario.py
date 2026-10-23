# ======================================================
# operaciones/inventario.py
# Modelo EOQ (cantidad económica de pedido) y punto de reorden, con el CONSUMO REAL registrado
# en las OT (aporte de la tesis, cap. 4.4):
#   D  = demanda anual: consumo de los últimos PERIODO días (o desde el primer consumo) llevado a un año.
#        Si todavía no hay consumo, se usa la demanda estimada de los parámetros (datos de ejemplo).
#   EOQ = √(2·D·S / H)        ROP = d·L  (d = D/365)
#   Costo total anual = (D/Q)·S + (Q/2)·H
# Consumo de ONU: instaladas (rendición) + reportadas desde la app en despachos aún sin rendir.
# Consumo de material: ConsumoOT (rendición) + reportes de la app en despachos sin rendir.
# Stock: lo DISPONIBLE en los almacenes (sin lo que está en tránsito).
# ======================================================
import math
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Sum
from django.utils import timezone

from almacenes.models import Material, Modelo

from .models import ConsumoOT, Despacho, DespachoEquipo, DespachoMaterial, OrdenTrabajo, ParametroEOQ, ReporteCampo

PERIODO = 90          # días de consumo que se miran
MIN_DIAS = 7          # para no anualizar con 1 o 2 días de datos
DEFECTO = {'costo_pedido': Decimal('850'), 'costo_mantener': Decimal('45'), 'tiempo_entrega': 15, 'demanda_estimada': 700}
EJECUTADAS = (OrdenTrabajo.Estado.EJECUTADA, OrdenTrabajo.Estado.VERIFICADA, OrdenTrabajo.Estado.CERRADA)


def parametros_defecto():
    p = ParametroEOQ.objects.filter(modelo__isnull=True).first()
    return p or ParametroEOQ(**DEFECTO)


def _consumos(desde):
    """{modelo_id: [(fecha, cantidad)]} de ONU y material usados desde `desde`."""
    c = defaultdict(list)
    # ONU instaladas (rendición)
    for e in (DespachoEquipo.objects.filter(resultado=DespachoEquipo.Resultado.INSTALADO, despacho__fecha__gte=desde)
              .select_related('material', 'despacho')):
        c[e.material.modelo_id].append((e.despacho.fecha, Decimal(1)))
    # Reportadas desde la app, con el despacho todavía sin rendir
    pendientes = (ReporteCampo.objects.filter(orden__estado__in=EJECUTADAS, created_at__date__gte=desde)
                  .select_related('despacho_equipo__material', 'despacho_equipo__despacho'))
    lineas_pend = {}
    for r in pendientes:
        dia = timezone.localtime(r.created_at).date()
        e = r.despacho_equipo
        if e and e.resultado == DespachoEquipo.Resultado.PENDIENTE and e.despacho.estado == Despacho.Estado.ENTREGADO:
            c[e.material.modelo_id].append((dia, Decimal(1)))
        for m in r.materiales:
            lineas_pend.setdefault(m['despacho_material'], []).append((dia, Decimal(str(m['cantidad']))))
    # Material por cantidad (rendición)
    for k in ConsumoOT.objects.filter(despacho_material__despacho__fecha__gte=desde).select_related(
            'despacho_material__material', 'despacho_material__despacho'):
        c[k.despacho_material.material.modelo_id].append((k.despacho_material.despacho.fecha, k.cantidad))
    if lineas_pend:
        for dm in DespachoMaterial.objects.filter(pk__in=lineas_pend, despacho__estado=Despacho.Estado.ENTREGADO).select_related('material'):
            c[dm.material.modelo_id].extend(lineas_pend[dm.id])
    return c


def _stock():
    """{modelo_id: {'total': n, 'almacenes': {nombre: n}}} de lo disponible."""
    s = defaultdict(lambda: {'total': Decimal(0), 'almacenes': defaultdict(Decimal)})
    onus = (Material.objects.filter(tipo_material__es_unico=True, estado_onu__codigo='DISPONIBLE', traspaso_actual__isnull=True)
            .values('modelo_id', 'almacen_actual__nombre').annotate(n=Count('id')))
    for f in onus:
        s[f['modelo_id']]['total'] += f['n']
        s[f['modelo_id']]['almacenes'][f['almacen_actual__nombre']] += f['n']
    granel = (Material.objects.filter(tipo_material__es_unico=False, estado_general__codigo='DISPONIBLE')
              .values('modelo_id', 'almacen_actual__nombre').annotate(n=Sum('cantidad')))
    for f in granel:
        s[f['modelo_id']]['total'] += f['n'] or 0
        s[f['modelo_id']]['almacenes'][f['almacen_actual__nombre']] += f['n'] or 0
    return s


def calcular(hoy=None):
    """Una fila por modelo con consumo, stock o parámetros propios: D, EOQ, ROP, cobertura y alerta."""
    hoy = hoy or timezone.localdate()
    desde = hoy - timedelta(days=PERIODO - 1)
    consumos = _consumos(desde)
    stock = _stock()
    propios = {p.modelo_id: p for p in ParametroEOQ.objects.filter(modelo__isnull=False)}
    defecto = parametros_defecto()
    ids = set(consumos) | set(propios) | {m for m, v in stock.items() if v['total'] > 0}
    modelos = Modelo.objects.filter(id__in=ids).select_related('marca', 'tipo_material', 'unidad_medida')
    filas = []
    for m in modelos:
        es_onu = m.tipo_material.es_unico if m.tipo_material_id else False
        p = propios.get(m.id) or (defecto if es_onu else None)
        usos = consumos.get(m.id, [])
        consumo = sum((q for _, q in usos), Decimal(0))
        dias = max(MIN_DIAS, min(PERIODO, (hoy - min(d for d, _ in usos)).days + 1)) if usos else PERIODO
        st = stock.get(m.id, {'total': Decimal(0), 'almacenes': {}})
        fila = {
            'modelo': {'id': m.id, 'nombre': f'{m.marca.nombre} {m.nombre}' if m.marca_id and es_onu else m.nombre,
                       'es_onu': es_onu, 'unidad': 'ONU' if es_onu else (m.unidad_medida.simbolo if m.unidad_medida_id else '')},
            'consumo_periodo': float(consumo), 'dias_periodo': dias,
            'stock': float(st['total']), 'stock_almacenes': {k: float(v) for k, v in st['almacenes'].items()},
            'parametros': None, 'demanda_anual': None, 'fuente': None, 'eoq': None, 'rop': None,
            'cobertura_dias': None, 'pedir': False, 'pedidos_anio': None, 'costo_total': None,
        }
        if consumo > 0:
            D, fuente = float(consumo) / dias * 365, 'CONSUMO'
        elif p and p.demanda_estimada:
            D, fuente = float(p.demanda_estimada), 'ESTIMADA'
        else:
            D, fuente = None, None
        if p:
            S, H, L = float(p.costo_pedido), float(p.costo_mantener), p.tiempo_entrega
            fila['parametros'] = {'S': S, 'H': H, 'L': L, 'D_estimada': p.demanda_estimada, 'propios': m.id in propios}
            if D and H > 0:
                Q = math.sqrt(2 * D * S / H)
                d = D / 365
                fila.update({
                    'demanda_anual': round(D, 1), 'fuente': fuente, 'eoq': math.ceil(Q), 'rop': math.ceil(d * L),
                    'demanda_diaria': round(d, 2), 'cobertura_dias': round(float(st['total']) / d, 1) if d else None,
                    'pedir': float(st['total']) <= math.ceil(d * L), 'pedidos_anio': round(D / Q, 1),
                    'costo_total': round(D / Q * S + Q / 2 * H, 2),
                })
        elif D:
            fila.update({'demanda_anual': round(D, 1), 'fuente': fuente})
        filas.append(fila)
    filas.sort(key=lambda f: (not f['modelo']['es_onu'], not f['pedir'], f['modelo']['nombre']))
    return {'fecha': hoy, 'periodo_dias': PERIODO, 'defecto': {'S': float(defecto.costo_pedido), 'H': float(defecto.costo_mantener),
                                                                 'L': defecto.tiempo_entrega, 'D_estimada': defecto.demanda_estimada},
            'filas': filas, 'consumo_mensual': consumo_mensual(hoy)}


def consumo_mensual(hoy, meses=6):
    """ONU instaladas por mes (últimos `meses`), para ver la tendencia de la demanda."""
    inicio = (hoy.replace(day=1) - timedelta(days=31 * (meses - 1))).replace(day=1)
    c = _consumos(inicio)
    por_mes = defaultdict(lambda: defaultdict(Decimal))
    unidades = {}
    for mid, usos in c.items():
        for d, q in usos:
            por_mes[d.strftime('%Y-%m')][mid] += q
    modelos = {m.id: m for m in Modelo.objects.filter(id__in=c).select_related('tipo_material', 'marca', 'unidad_medida')}
    for mid, m in modelos.items():
        unidades[mid] = 'ONU' if m.tipo_material.es_unico else (m.unidad_medida.simbolo if m.unidad_medida_id else '')
    meses_lista = []
    d = inicio
    while d <= hoy:
        clave = d.strftime('%Y-%m')
        fila = por_mes.get(clave, {})
        meses_lista.append({'mes': clave, 'onu': float(sum(q for mid, q in fila.items() if unidades.get(mid) == 'ONU')),
                            'detalle': {modelos[mid].nombre: float(q) for mid, q in fila.items()}})
        d = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
    return meses_lista
