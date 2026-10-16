# ======================================================
# operaciones/plazos.py
# Plazo de atención según la ATT (RAR ATT-DJ-RAR-TL LP 589/2025, área urbana):
#   - Instalación y traslado (indicador TIS): 7 días calendario, contados desde las 00:00
#     del día siguiente al registro de la solicitud.
#   - Reparación de fallas (indicador TRF): 24 horas desde el registro de la falla.
#   - Retiro: la norma no fija plazo.
# El sistema SOLO AVISA (semáforo). Nunca cambia el estado de una OT por el plazo.
# Al ejecutarse, se sabe si la OT cumplió el plazo (base del indicador; meta ATT ≥ 85 %).
# ======================================================
from datetime import datetime, time, timedelta

from django.db.models import OuterRef, Q, Subquery
from django.utils import timezone

from .models import HistorialOT, OrdenTrabajo, Solicitud

T = Solicitud.Tipo
E = OrdenTrabajo.Estado
DIAS_INSTALACION = 7
HORAS_REPARACION = 24
AVISO_INSTALACION = timedelta(days=2)   # "por vencer" cuando faltan 2 días o menos
AVISO_REPARACION = timedelta(hours=6)   # "por vencer" cuando faltan 6 horas o menos
CON_PLAZO = (T.INSTALACION, T.TRASLADO, T.REPARACION)
# Estados en los que el trabajo ya se hizo (cuenta la hora en que quedó EJECUTADA)
HECHAS = (E.EJECUTADA, E.VERIFICADA, E.CERRADA)
# Estados en los que el plazo sigue corriendo
EN_CURSO = (E.PENDIENTE, E.PROGRAMADA, E.EN_CAMPO, E.NO_EJECUTADA)


def limite(tipo, registro):
    """Fecha y hora límite para una OT de `tipo` cuya solicitud se registró en `registro` (aware)."""
    if tipo in (T.INSTALACION, T.TRASLADO):
        dia = timezone.localtime(registro).date() + timedelta(days=1)
        inicio = timezone.make_aware(datetime.combine(dia, time.min))
        return inicio + timedelta(days=DIAS_INSTALACION)
    if tipo == T.REPARACION:
        return registro + timedelta(hours=HORAS_REPARACION)
    return None


def con_ejecucion(qs):
    """Anota `ejecutada_at`: primera vez que la OT quedó EJECUTADA (desde la PWA)."""
    primera = (HistorialOT.objects.filter(orden=OuterRef('pk'), estado_nuevo=E.EJECUTADA)
               .order_by('fecha').values('fecha')[:1])
    return qs.annotate(ejecutada_at=Subquery(primera))


def plazo(orden, ahora=None):
    """
    {'limite', 'estado', 'segundos'}:
      EN_PLAZO / POR_VENCER / VENCIDA mientras el trabajo no se hizo (segundos: lo que falta, negativo si pasó);
      CUMPLIDO / INCUMPLIDO cuando ya se ejecutó. None si el tipo no tiene plazo o la OT está anulada.
    """
    fin = limite(orden.tipo, orden.solicitud.created_at)
    if fin is None or orden.estado == E.ANULADA:
        return None
    if orden.estado in HECHAS:
        hecha = getattr(orden, 'ejecutada_at', None)
        if hecha is None:
            h = orden.historial.filter(estado_nuevo=E.EJECUTADA).order_by('fecha').first()
            hecha = h.fecha if h else None
        if hecha is None:
            return {'limite': fin, 'estado': None, 'segundos': None}
        return {'limite': fin, 'estado': 'CUMPLIDO' if hecha <= fin else 'INCUMPLIDO', 'segundos': None}
    falta = fin - (ahora or timezone.now())
    aviso = AVISO_REPARACION if orden.tipo == T.REPARACION else AVISO_INSTALACION
    estado = 'VENCIDA' if falta.total_seconds() <= 0 else 'POR_VENCER' if falta <= aviso else 'EN_PLAZO'
    return {'limite': fin, 'estado': estado, 'segundos': int(falta.total_seconds())}


def filtro(cual, ahora=None):
    """Q para OT en curso 'vencidas' o 'por_vencer' (para listar y contar en la base)."""
    ahora = ahora or timezone.now()
    hoy = timezone.localtime(ahora).date()
    # Instalación/traslado: límite = 00:00 del día (registro + 8) → vence cuando hoy ≥ registro + 8
    inst = Q(tipo__in=(T.INSTALACION, T.TRASLADO))
    rep = Q(tipo=T.REPARACION)
    if cual == 'vencidas':
        cond = (inst & Q(solicitud__created_at__date__lte=hoy - timedelta(days=DIAS_INSTALACION + 1))) | \
               (rep & Q(solicitud__created_at__lte=ahora - timedelta(hours=HORAS_REPARACION)))
    elif cual == 'por_vencer':
        dias_aviso = AVISO_INSTALACION.days
        cond = (inst & Q(solicitud__created_at__date__lte=hoy - timedelta(days=DIAS_INSTALACION + 1 - dias_aviso),
                         solicitud__created_at__date__gt=hoy - timedelta(days=DIAS_INSTALACION + 1))) | \
               (rep & Q(solicitud__created_at__lte=ahora - timedelta(hours=HORAS_REPARACION) + AVISO_REPARACION,
                        solicitud__created_at__gt=ahora - timedelta(hours=HORAS_REPARACION)))
    else:
        return Q()
    return Q(estado__in=EN_CURSO) & cond


def resumen(qs=None):
    qs = qs if qs is not None else OrdenTrabajo.objects.all()
    return {'vencidas': qs.filter(filtro('vencidas')).count(), 'por_vencer': qs.filter(filtro('por_vencer')).count()}
