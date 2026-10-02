# ======================================================
# almacenes/optimizaciones.py
# Contadores calculados en la misma consulta SQL (subconsultas) para evitar
# el problema "N+1": antes cada fila del listado hacía 2-5 consultas extra.
# Los serializers usan estos valores (_xxx) si existen y, si no, calculan como antes.
# ======================================================
from django.db.models import Count, IntegerField, OuterRef, Prefetch, Q, Subquery, Value
from django.db.models.functions import Coalesce

from django.db.models import Sum

from .models import EntregaParcialLote, Lote, LoteDetalle, Material, Modelo, ModeloComponente


def _contar(qs, campo):
    """COUNT(*) de `qs` agrupado por `campo` (que debe estar filtrado con OuterRef)."""
    sub = qs.order_by().values(campo).annotate(c=Count('pk')).values('c')[:1]
    return Coalesce(Subquery(sub, output_field=IntegerField()), Value(0))


def _disponibles(qs):
    """Materiales que se pueden usar: ONU en estado asignable o general en estado consumible."""
    return qs.filter(
        Q(tipo_material__es_unico=True, estado_onu__permite_asignacion=True) |
        Q(tipo_material__es_unico=False, estado_general__permite_consumo=True)
    )


def optimizar_modelos(qs):
    return qs.select_related('marca', 'tipo_material', 'unidad_medida').prefetch_related(
        # los componentes con su componente en 1 sola consulta
        Prefetch(
            'modelocomponente_set', queryset=ModeloComponente.objects.select_related('componente')
        )
    ).annotate(
        _materiales_count=_contar(Material.objects.filter(modelo=OuterRef('pk')), 'modelo'),
        _disp_onu=_contar(Material.objects.filter(modelo=OuterRef('pk'), estado_onu__permite_asignacion=True), 'modelo'),
        _disp_general=_contar(Material.objects.filter(modelo=OuterRef('pk'), estado_general__permite_consumo=True), 'modelo'),
    )


def optimizar_marcas(qs):
    return qs.annotate(
        _modelos_count=_contar(Modelo.objects.filter(marca=OuterRef('pk'), activo=True), 'marca'),
        _materiales_count=_contar(Material.objects.filter(modelo__marca=OuterRef('pk'), modelo__activo=True), 'modelo__marca'),
    )


def optimizar_proveedores(qs):
    return qs.select_related('created_by').annotate(
        _lotes_count=_contar(Lote.objects.filter(proveedor=OuterRef('pk')), 'proveedor'),
    )


def optimizar_almacenes(qs):
    return qs.select_related('tipo', 'encargado', 'created_by').annotate(
        _total_materiales=_contar(Material.objects.filter(almacen_actual=OuterRef('pk')), 'almacen_actual'),
        _materiales_disponibles=_contar(_disponibles(Material.objects.filter(almacen_actual=OuterRef('pk'))), 'almacen_actual'),
    )


def optimizar_sectores(qs):
    return qs.annotate(
        _materiales_count=_contar(Material.objects.filter(lote__sector_solicitante=OuterRef('pk')), 'lote__sector_solicitante'),
        _lotes_count=_contar(Lote.objects.filter(sector_solicitante=OuterRef('pk')), 'sector_solicitante'),
    )


def optimizar_lotes(qs):
    """Detalles con sus cantidades recibidas precalculadas (antes ~6 consultas por detalle)."""
    materiales = Material.objects.filter(lote=OuterRef('lote'), modelo=OuterRef('modelo')).order_by()
    detalles = LoteDetalle.objects.select_related(
        'modelo__marca', 'modelo__tipo_material', 'modelo__unidad_medida'
    ).annotate(
        _rec_count=_contar(materiales, 'lote'),
        _rec_sum=Subquery(
            materiales.values('lote').annotate(t=Sum('cantidad')).values('t')[:1],
            output_field=Material._meta.get_field('cantidad'),
        ),
    )
    return qs.select_related('sector_solicitante').prefetch_related(None).prefetch_related(
        Prefetch('detalles', queryset=detalles),
        Prefetch('entregas_parciales', queryset=EntregaParcialLote.objects.select_related('estado_entrega', 'created_by')),
    )
