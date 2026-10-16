# ======================================================
# operaciones/programacion.py
# Reglas de cuadrillas y de programación de OT. Las usan las vistas web y
# (más adelante) la app de campo, para que las reglas estén en un solo lugar.
#
#   PENDIENTE / NO_EJECUTADA ──programar──▶ PROGRAMADA ──reprogramar (motivo)──▶ PROGRAMADA
#   PROGRAMADA / NO_EJECUTADA ──desasignar (motivo)──▶ PENDIENTE
#   PROGRAMADA / EN_CAMPO ──no ejecutada (motivo)──▶ NO_EJECUTADA
#
# El sistema nunca cambia el estado de una OT por su cuenta: lo cambia el técnico desde la PWA (con
# evidencias) o un usuario con permiso y motivo. Una OT programada cuya fecha ya pasó sin ejecutarse
# sigue PROGRAMADA y se muestra como ATRASADA para que se reprograme o se marque no ejecutada con su
# motivo (la PWA puede sincronizar tarde un trabajo hecho sin señal).
#
# EN CAMPO y EJECUTADA no se marcan desde la web: llegan desde la app del
# técnico, con las fotos que verifican el trabajo.
# Cada cambio queda en HistorialOT con el usuario, la hora del servidor y,
# si cambió, la cuadrilla y la fecha anteriores y nuevas.
# ======================================================
from django.db import IntegrityError, transaction
from django.db.models import Max
from django.utils import timezone

from .models import Cuadrilla, Despacho, IntegranteCuadrilla, OrdenTrabajo

E = OrdenTrabajo.Estado
PROGRAMABLES = (E.PENDIENTE, E.PROGRAMADA, E.NO_EJECUTADA)
DESASIGNABLES = (E.PROGRAMADA, E.NO_EJECUTADA)
NO_EJECUTABLES = (E.PROGRAMADA, E.EN_CAMPO)
# Estados en los que la OT ocupa a la cuadrilla en su fecha
OCUPAN = (E.PROGRAMADA, E.EN_CAMPO, E.EJECUTADA)

# Permiso que habilita a un usuario para salir a campo (lo tiene el rol Técnico)
PERMISO_CAMPO = ('campo', 'actualizar')
MINIMO_MOTIVO = 5


class ErrorProgramacion(Exception):
    """Regla de negocio no cumplida; el mensaje se muestra tal cual al usuario."""


def _motivo(motivo, que):
    motivo = (motivo or '').strip()
    if len(motivo) < MINIMO_MOTIVO:
        raise ErrorProgramacion(f'Indica el motivo {que} (mínimo {MINIMO_MOTIVO} caracteres).')
    return motivo


def _fecha(f):
    return f.strftime('%d/%m/%Y') if f else '—'


# ---------------- Técnicos ----------------

def puede_ir_a_campo(usuario):
    """Usuario activo cuyo rol tiene campo:actualizar. (Un superusuario no entra solo por serlo.)"""
    if not usuario or not usuario.is_active or getattr(usuario, 'eliminado', False):
        return False
    rol = usuario.rol
    if not rol or not rol.activo or rol.eliminado:
        return False
    recurso, accion = PERMISO_CAMPO
    return rol.permisos.filter(recurso=recurso, accion=accion, activo=True, eliminado=False).exists()


def tecnicos_disponibles():
    """Usuarios habilitados para campo que hoy no están en ninguna cuadrilla."""
    from usuarios.models import Usuario
    recurso, accion = PERMISO_CAMPO
    return (Usuario.objects.activos()
            .filter(rol__activo=True, rol__eliminado=False,
                    rol__permisos__recurso=recurso, rol__permisos__accion=accion,
                    rol__permisos__activo=True, rol__permisos__eliminado=False)
            .exclude(id__in=IntegranteCuadrilla.objects.filter(hasta__isnull=True).values('usuario_id'))
            .select_related('rol').distinct()
            .order_by('apellidopaterno', 'apellidomaterno', 'nombres'))


# ---------------- Cuadrillas ----------------

@transaction.atomic
def agregar_integrante(cuadrilla, usuario, es_jefe=False):
    cuadrilla = Cuadrilla.objects.select_for_update().get(pk=cuadrilla.pk)
    if not cuadrilla.activo:
        raise ErrorProgramacion('La cuadrilla está inactiva.')
    if not puede_ir_a_campo(usuario):
        raise ErrorProgramacion(f'{usuario.nombre_completo} no tiene un rol habilitado para campo (rol Técnico).')
    actual = IntegranteCuadrilla.objects.filter(usuario=usuario, hasta__isnull=True).select_related('cuadrilla').first()
    if actual:
        raise ErrorProgramacion(f'{usuario.nombre_completo} ya está en la cuadrilla {actual.cuadrilla}.')
    if cuadrilla.vigentes().count() >= Cuadrilla.MAX_INTEGRANTES:
        raise ErrorProgramacion(f'La cuadrilla ya tiene {Cuadrilla.MAX_INTEGRANTES} técnicos.')
    if es_jefe:
        cuadrilla.vigentes().filter(es_jefe=True).update(es_jefe=False)
    try:
        with transaction.atomic():
            return IntegranteCuadrilla.objects.create(cuadrilla=cuadrilla, usuario=usuario, es_jefe=es_jefe)
    except IntegrityError:
        raise ErrorProgramacion(f'{usuario.nombre_completo} ya está en otra cuadrilla.')


@transaction.atomic
def marcar_jefe(cuadrilla, usuario):
    integrante = cuadrilla.vigentes().filter(usuario=usuario).first()
    if not integrante:
        raise ErrorProgramacion('Ese técnico no está en la cuadrilla.')
    cuadrilla.vigentes().filter(es_jefe=True).exclude(pk=integrante.pk).update(es_jefe=False)
    integrante.es_jefe = True
    integrante.save(update_fields=['es_jefe'])
    return integrante


@transaction.atomic
def retirar_integrante(cuadrilla, usuario):
    """El técnico deja la cuadrilla desde hoy; su paso por ella queda registrado."""
    integrante = cuadrilla.vigentes().filter(usuario=usuario).first()
    if not integrante:
        raise ErrorProgramacion('Ese técnico no está en la cuadrilla.')
    integrante.hasta = timezone.localdate()
    integrante.save(update_fields=['hasta'])
    return integrante


@transaction.atomic
def desactivar_cuadrilla(cuadrilla):
    cuadrilla = Cuadrilla.objects.select_for_update().get(pk=cuadrilla.pk)
    pendientes = cuadrilla.ordenes.filter(estado__in=(E.PROGRAMADA, E.EN_CAMPO)).count()
    if pendientes:
        raise ErrorProgramacion(f'La cuadrilla tiene {pendientes} OT programada(s) o en campo. '
                                'Reprográmalas o desasígnalas antes de desactivarla.')
    cuadrilla.vigentes().update(hasta=timezone.localdate())
    cuadrilla.activo = False
    cuadrilla.save(update_fields=['activo', 'updated_at'])
    return cuadrilla


def validar_para_programar(cuadrilla):
    if not cuadrilla.activo:
        raise ErrorProgramacion(f'La cuadrilla {cuadrilla} está inactiva.')
    vigentes = list(cuadrilla.vigentes())
    if len(vigentes) < Cuadrilla.MIN_INTEGRANTES:
        raise ErrorProgramacion(f'La cuadrilla {cuadrilla} necesita al menos {Cuadrilla.MIN_INTEGRANTES} técnicos.')
    if not any(i.es_jefe for i in vigentes):
        raise ErrorProgramacion(f'La cuadrilla {cuadrilla} no tiene jefe.')


# ---------------- OT atrasadas ----------------

def atrasadas(hoy=None):
    """OT programadas o en campo de un día anterior a hoy, sin ejecución registrada. Solo se informan."""
    hoy = hoy or timezone.localdate()
    return (OrdenTrabajo.objects.filter(estado__in=NO_EJECUTABLES, fecha_programada__lt=hoy)
            .select_related('cuadrilla').order_by('fecha_programada', 'cuadrilla__nombre', 'orden_visita'))


# ---------------- Programación de OT ----------------

def carga(cuadrilla, fecha, excluir=None):
    qs = OrdenTrabajo.objects.filter(cuadrilla=cuadrilla, fecha_programada=fecha, estado__in=OCUPAN)
    if excluir:
        qs = qs.exclude(pk=excluir.pk)
    return qs.count()


def avisos(orden, cuadrilla, fecha):
    """Situaciones que no impiden programar, pero conviene saber."""
    lista = []
    n = carga(cuadrilla, fecha, excluir=orden) + 1
    if cuadrilla.capacidad_diaria and n > cuadrilla.capacidad_diaria:
        lista.append(f'{cuadrilla} queda con {n} OT el {_fecha(fecha)} (su capacidad es {cuadrilla.capacidad_diaria}).')
    zona_id = orden.solicitud.zona_cobertura_id
    zonas = set(cuadrilla.zonas.values_list('id', flat=True))
    if zonas and zona_id not in zonas:
        zona = orden.solicitud.zona_cobertura
        lista.append(f'{orden.numero} está en {zona or "una ubicación sin zona"}, fuera de las zonas de {cuadrilla}.')
    despacho = Despacho.objects.filter(cuadrilla=cuadrilla, fecha=fecha).exclude(estado=Despacho.Estado.ANULADO).first()
    if despacho and despacho.estado == Despacho.Estado.RENDIDO:
        lista.append(f'{cuadrilla} ya rindió su despacho del {_fecha(fecha)} ({despacho.numero}): no tiene material para esta OT.')
    elif despacho:
        lista.append(f'{cuadrilla} ya recibió su despacho del {_fecha(fecha)} ({despacho.numero}). Si esta OT necesita ONU '
                     'o material, agrégalo con Despachar: se suma al mismo despacho.')
    return lista


def programar(orden, cuadrilla, fecha, usuario, motivo=''):
    """
    Asigna (o reasigna) la OT a una cuadrilla para una fecha. Si ya estaba
    programada es una reprogramación y el motivo es obligatorio.
    Devuelve la lista de avisos.
    """
    with transaction.atomic():
        orden = OrdenTrabajo.objects.select_for_update(of=('self',)).select_related('solicitud__zona_cobertura', 'cuadrilla').get(pk=orden.pk)
        if orden.estado not in PROGRAMABLES:
            raise ErrorProgramacion(f'La {orden.numero} está {orden.get_estado_display().lower()}; no se puede programar.')
        if fecha < timezone.localdate():
            raise ErrorProgramacion('La fecha no puede ser anterior a hoy.')
        validar_para_programar(cuadrilla)

        reprogramacion = orden.estado == E.PROGRAMADA
        if reprogramacion and orden.cuadrilla_id == cuadrilla.id and orden.fecha_programada == fecha:
            raise ErrorProgramacion(f'La {orden.numero} ya está programada con {cuadrilla} el {_fecha(fecha)}.')
        motivo = _motivo(motivo, 'de la reprogramación') if reprogramacion else (motivo or '').strip()

        lista = avisos(orden, cuadrilla, fecha)
        anterior = {'cuadrilla_anterior': orden.cuadrilla, 'fecha_anterior': orden.fecha_programada}
        ultima = (OrdenTrabajo.objects.filter(cuadrilla=cuadrilla, fecha_programada=fecha)
                  .exclude(pk=orden.pk).aggregate(m=Max('orden_visita'))['m'] or 0)
        orden.cuadrilla, orden.fecha_programada, orden.orden_visita = cuadrilla, fecha, ultima + 1

        texto = f'{"Reprogramada" if reprogramacion else "Programada"} para el {_fecha(fecha)} con {cuadrilla}'
        if reprogramacion:
            texto += f' (antes: {anterior["cuadrilla_anterior"]}, {_fecha(anterior["fecha_anterior"])}). Motivo: {motivo}'
        elif motivo:
            texto += f'. {motivo}'
        orden.cambiar_estado(E.PROGRAMADA, usuario, texto, cuadrilla_nueva=cuadrilla, fecha_nueva=fecha, **anterior)
    return lista


def desasignar(orden, usuario, motivo):
    """Quita la cuadrilla y la fecha; la OT vuelve a pendientes."""
    with transaction.atomic():
        orden = OrdenTrabajo.objects.select_for_update(of=('self',)).select_related('cuadrilla').get(pk=orden.pk)
        if orden.estado not in DESASIGNABLES:
            raise ErrorProgramacion(f'La {orden.numero} está {orden.get_estado_display().lower()}; no se puede desasignar.')
        motivo = _motivo(motivo, 'para desasignar')
        anterior = {'cuadrilla_anterior': orden.cuadrilla, 'fecha_anterior': orden.fecha_programada}
        orden.cuadrilla = orden.fecha_programada = orden.orden_visita = None
        orden.cambiar_estado(E.PENDIENTE, usuario, f'Desasignada de {anterior["cuadrilla_anterior"] or "—"}. Motivo: {motivo}',
                             **anterior)
    return orden


def no_ejecutada(orden, usuario, motivo):
    """La cuadrilla no pudo hacer el trabajo (cliente ausente, falta de material…). Conserva cuadrilla y fecha."""
    with transaction.atomic():
        orden = OrdenTrabajo.objects.select_for_update().get(pk=orden.pk)
        if orden.estado not in NO_EJECUTABLES:
            raise ErrorProgramacion(f'La {orden.numero} está {orden.get_estado_display().lower()}; '
                                    'solo una OT programada o en campo puede quedar no ejecutada.')
        motivo = _motivo(motivo, 'por el que no se ejecutó')
        orden.cambiar_estado(E.NO_EJECUTADA, usuario, f'No ejecutada. Motivo: {motivo}')
    return orden


@transaction.atomic
def ordenar_visitas(cuadrilla, fecha, ids):
    """Fija el orden de la hoja del día con la lista completa de OT de esa cuadrilla y fecha."""
    ordenes = {o.id: o for o in OrdenTrabajo.objects.select_for_update()
               .filter(cuadrilla=cuadrilla, fecha_programada=fecha, estado__in=OCUPAN)}
    try:
        ids = [int(i) for i in ids]
    except (TypeError, ValueError):
        raise ErrorProgramacion('Lista de órdenes no válida.')
    if len(ids) != len(set(ids)) or set(ids) != set(ordenes):
        raise ErrorProgramacion('La lista no coincide con las OT de la cuadrilla en esa fecha. Actualiza la pantalla.')
    for n, i in enumerate(ids, start=1):
        ordenes[i].orden_visita = n
    OrdenTrabajo.objects.bulk_update(ordenes.values(), ['orden_visita'])
