# ======================================================
# operaciones/campo.py
# Reglas de la app de campo (el técnico, desde el celular). Las usa CampoViewSet.
#
#   PROGRAMADA ──iniciar (GPS)──▶ EN_CAMPO ──fotos + ejecutar──▶ EJECUTADA
#   PROGRAMADA / EN_CAMPO ──no se pudo (motivo)──▶ NO_EJECUTADA
#
# Evidencias (antifraude, aporte de la tesis):
#   - Solo con la OT EN CAMPO (coherencia temporal) y con la hora del SERVIDOR.
#   - Distancia al domicilio de la solicitud (Haversine) ≤ RADIO_M; si no, se rechaza.
#   - Duplicados: SHA-256 igual (misma foto) o pHash a distancia de Hamming ≤ HAMMING_MAX
#     (foto casi igual) de otra ya aceptada, en cualquier OT; se rechaza.
#   - CNN (detección de la ONU): queda PENDIENTE hasta conectar el modelo YOLOv8.
#   Las rechazadas también se guardan (registro de intentos).
# ======================================================
import hashlib
from decimal import Decimal, InvalidOperation
from io import BytesIO

import numpy as np
from django.db import transaction
from django.utils import timezone

from . import geo
from .despacho import TIPOS_CON_ONU, compatible, servicios_onu, servicios_ot
from .models import (Despacho, DespachoEquipo, DespachoMaterial, EvidenciaOT, IntegranteCuadrilla, OrdenTrabajo, ReporteCampo,
                     Solicitud)
from .programacion import ErrorProgramacion as ErrorCampo

E = OrdenTrabajo.Estado
T = Solicitud.Tipo
RADIO_M = 100            # distancia máxima al domicilio (tesis, cap. 4)
HAMMING_MAX = 6          # pHash de 64 bits: ≤ 6 bits distintos = foto casi igual
MAX_BYTES = 10 * 1024 * 1024

# Motivo de no ejecución → a quién se atribuye (sirve para las exclusiones del indicador ATT)
MOTIVOS = [
    ('CLIENTE_AUSENTE', 'Cliente ausente', 'USUARIO'),
    ('CLIENTE_NO_PERMITE', 'El cliente no permitió el ingreso', 'USUARIO'),
    ('CLIENTE_OTRA_FECHA', 'El cliente pidió otra fecha', 'USUARIO'),
    ('DIRECCION', 'Dirección incorrecta o no ubicada', 'USUARIO'),
    ('FALTA_MATERIAL', 'Falta de material o equipo', 'OPERADOR'),
    ('RED', 'Problema en la red (sin puerto o sin señal)', 'OPERADOR'),
    ('TIEMPO', 'No alcanzó el tiempo', 'OPERADOR'),
    ('FUERZA_MAYOR', 'Clima, bloqueo u otra fuerza mayor', 'FUERZA_MAYOR'),
    ('OTRO', 'Otro motivo', 'OPERADOR'),
]
MOTIVO = {c: n for c, n, _ in MOTIVOS}


# ---------------- Cuadrilla del técnico ----------------

def cuadrilla_de(usuario):
    i = (IntegranteCuadrilla.objects.filter(usuario=usuario, hasta__isnull=True, cuadrilla__activo=True)
         .select_related('cuadrilla__almacen', 'cuadrilla__vehiculo').first())
    return i.cuadrilla if i else None


def _mi_orden(usuario, orden_id):
    """La OT con bloqueo, siempre que sea de la cuadrilla del técnico."""
    cuadrilla = cuadrilla_de(usuario)
    if not cuadrilla:
        raise ErrorCampo('No estás en ninguna cuadrilla activa.')
    orden = (OrdenTrabajo.objects.select_for_update(of=('self',)).select_related('solicitud')
             .filter(pk=orden_id, cuadrilla=cuadrilla).first())
    if not orden:
        raise ErrorCampo('Esa OT no está asignada a tu cuadrilla.')
    return orden, cuadrilla


def _coord(valor, nombre):
    try:
        d = Decimal(str(valor))
    except (InvalidOperation, TypeError, ValueError):
        raise ErrorCampo(f'No se recibió la ubicación del teléfono ({nombre}). Activa el GPS y vuelve a intentar.')
    if abs(d) > (90 if nombre == 'latitud' else 180):
        raise ErrorCampo('Ubicación no válida.')
    return d.quantize(Decimal('0.000001'))


def _distancia(orden, lat, lng):
    s = orden.solicitud
    return geo.distancia_m(s.latitud, s.longitud, lat, lng)


# ---------------- Hash perceptual ----------------

def _matriz_dct(n):
    k = np.arange(n)
    m = np.cos(np.pi * (2 * k[None, :] + 1) * k[:, None] / (2 * n))
    m[0, :] *= 1 / np.sqrt(2)
    return m * np.sqrt(2 / n)


_DCT32 = _matriz_dct(32)


def phash(imagen):
    """pHash de 64 bits: gris 32×32 → DCT 2D → 8×8 de baja frecuencia → bit = valor > mediana."""
    g = np.asarray(imagen.convert('L').resize((32, 32)), dtype=np.float64)
    baja = (_DCT32 @ g @ _DCT32.T)[:8, :8].flatten()
    bits = baja > np.median(baja[1:])
    return f'{int("".join("1" if b else "0" for b in bits), 2):016x}'


def hamming(a, b):
    return bin(int(a, 16) ^ int(b, 16)).count('1')


def _leer_imagen(archivo):
    from PIL import Image, ImageOps, UnidentifiedImageError
    datos = archivo.read()
    if not datos:
        raise ErrorCampo('No llegó la foto.')
    if len(datos) > MAX_BYTES:
        raise ErrorCampo('La foto pesa demasiado (máximo 10 MB).')
    try:
        img = Image.open(BytesIO(datos))
        img.load()
    except (UnidentifiedImageError, OSError):
        raise ErrorCampo('El archivo no es una imagen válida.')
    return datos, ImageOps.exif_transpose(img)


# ---------------- Acciones ----------------

def iniciar(usuario, orden_id, lat, lng):
    """El técnico llegó al domicilio: PROGRAMADA → EN_CAMPO (hora del servidor y su GPS)."""
    lat, lng = _coord(lat, 'latitud'), _coord(lng, 'longitud')
    with transaction.atomic():
        orden, cuadrilla = _mi_orden(usuario, orden_id)
        if orden.estado != E.PROGRAMADA:
            raise ErrorCampo(f'La {orden.numero} está {orden.get_estado_display().lower()}; solo se inicia una OT programada.')
        if orden.fecha_programada and orden.fecha_programada > timezone.localdate():
            raise ErrorCampo(f'La {orden.numero} está programada para el {orden.fecha_programada:%d/%m/%Y}.')
        d = _distancia(orden, lat, lng)
        orden.cambiar_estado(E.EN_CAMPO, usuario, f'En campo ({cuadrilla}). GPS {lat}, {lng}: a {d:.0f} m del domicilio.')
    return orden, d


def registrar_evidencia(usuario, orden_id, archivo, lat, lng, tipo=EvidenciaOT.Tipo.ONU, precision=None):
    """Guarda la foto y la valida. Devuelve la evidencia (ACEPTADA o RECHAZADA con su motivo)."""
    lat, lng = _coord(lat, 'latitud'), _coord(lng, 'longitud')
    if tipo not in EvidenciaOT.Tipo.values:
        raise ErrorCampo('Tipo de foto no válido.')
    datos, img = _leer_imagen(archivo)
    sha = hashlib.sha256(datos).hexdigest()
    ph = phash(img)
    with transaction.atomic():
        orden, _ = _mi_orden(usuario, orden_id)
        if orden.estado != E.EN_CAMPO:
            raise ErrorCampo('Primero marca que llegaste al domicilio (la OT debe estar En campo).')
        d = _distancia(orden, lat, lng)
        motivo = ''
        if d > RADIO_M:
            motivo = f'La foto se tomó a {d:.0f} m del domicilio (máximo {RADIO_M} m).'
        else:
            validas = EvidenciaOT.objects.exclude(estado=EvidenciaOT.Estado.RECHAZADA)
            igual = validas.filter(sha256=sha).select_related('orden').first()
            if igual:
                motivo = f'Es la misma foto que ya se registró en la {igual.orden.numero}.'
            else:
                for e in validas.only('phash', 'orden__numero').select_related('orden'):
                    if hamming(e.phash, ph) <= HAMMING_MAX:
                        motivo = f'Es casi igual a una foto ya registrada en la {e.orden.numero}.'
                        break
        ev = EvidenciaOT(orden=orden, tipo=tipo, sha256=sha, phash=ph, latitud=lat, longitud=lng,
                         precision_m=float(precision) if precision not in (None, '') else None, distancia_m=round(d, 1),
                         estado=EvidenciaOT.Estado.RECHAZADA if motivo else EvidenciaOT.Estado.ACEPTADA, motivo=motivo,
                         cnn=EvidenciaOT.Cnn.PENDIENTE if tipo == EvidenciaOT.Tipo.ONU else EvidenciaOT.Cnn.NO_APLICA,
                         tomada_por=usuario)
        from django.core.files.base import ContentFile
        ev.imagen.save(getattr(archivo, 'name', 'foto.jpg') or 'foto.jpg', ContentFile(datos), save=False)
        ev.save()
    return ev


def onus_a_cargo(cuadrilla):
    """ONU que la cuadrilla tiene a su cargo (despachos sin rendir) y que nadie reportó instaladas."""
    reportadas = ReporteCampo.objects.filter(despacho_equipo__isnull=False).values('despacho_equipo_id')
    return (DespachoEquipo.objects.filter(despacho__cuadrilla=cuadrilla, despacho__estado=Despacho.Estado.ENTREGADO,
                                          resultado=DespachoEquipo.Resultado.PENDIENTE)
            .exclude(pk__in=reportadas).select_related('material__modelo__marca', 'despacho'))


def material_a_cargo(cuadrilla):
    return (DespachoMaterial.objects.filter(despacho__cuadrilla=cuadrilla, despacho__estado=Despacho.Estado.ENTREGADO)
            .select_related('material__modelo__unidad_medida', 'despacho'))


def reportado(linea):
    """Cuánto de esta línea de material ya informaron los técnicos en sus OT."""
    total = Decimal(0)
    for r in ReporteCampo.objects.filter(orden__estado__in=(E.EJECUTADA, E.VERIFICADA, E.CERRADA),
                                         materiales__contains=[{'despacho_material': linea.id}]):
        for m in r.materiales:
            if m.get('despacho_material') == linea.id:
                total += Decimal(str(m.get('cantidad') or 0))
    return total


def ejecutar(usuario, orden_id, onu_id=None, materiales=(), serial_recuperado='', observaciones='', lat=None, lng=None):
    """
    EN_CAMPO → EJECUTADA. Exige la foto de la ONU aceptada (u observada). En instalación exige la
    ONU instalada: una de las que la cuadrilla tiene a cargo y compatible con los servicios del plan.
    materiales: [(despacho_material_id, cantidad)]
    """
    with transaction.atomic():
        orden, cuadrilla = _mi_orden(usuario, orden_id)
        if orden.estado != E.EN_CAMPO:
            raise ErrorCampo(f'La {orden.numero} está {orden.get_estado_display().lower()}; debe estar En campo.')
        if not orden.evidencias.filter(tipo=EvidenciaOT.Tipo.ONU).exclude(estado=EvidenciaOT.Estado.RECHAZADA).exists():
            raise ErrorCampo('Falta la foto de la ONU (tomada en el domicilio).')

        equipo = None
        if onu_id:
            equipo = onus_a_cargo(cuadrilla).filter(pk=onu_id).first()
            if not equipo:
                raise ErrorCampo('Esa ONU no está a cargo de tu cuadrilla o ya se reportó en otra OT.')
            if orden.tipo not in TIPOS_CON_ONU:
                raise ErrorCampo(f'Una OT de {orden.get_tipo_display().lower()} no instala ONU nueva.')
            if not compatible(servicios_onu(equipo.material), servicios_ot(orden)):
                raise ErrorCampo('Esa ONU no tiene los servicios del plan del cliente (TV o telefonía).')
        elif orden.tipo == T.INSTALACION:
            raise ErrorCampo('Indica qué ONU instalaste.')

        lineas = {m.id: m for m in material_a_cargo(cuadrilla)}
        usados = []
        for linea_id, cant in materiales:
            try:
                cant = Decimal(str(cant))
            except (InvalidOperation, TypeError, ValueError):
                raise ErrorCampo('Cantidad de material no válida.')
            if cant <= 0:
                continue
            linea = lineas.get(int(linea_id))
            if not linea:
                raise ErrorCampo('Ese material no está a cargo de tu cuadrilla.')
            libre = linea.cantidad - reportado(linea)
            if cant > libre:
                raise ErrorCampo(f'{linea.material.modelo.nombre}: te quedan {libre.normalize():f} a cargo.')
            usados.append({'despacho_material': linea.id, 'cantidad': f'{cant.normalize():f}'})

        ReporteCampo.objects.update_or_create(orden=orden, defaults={
            'despacho_equipo': equipo, 'materiales': usados, 'serial_recuperado': (serial_recuperado or '').strip().upper()[:100],
            'observaciones': (observaciones or '').strip(), 'usuario': usuario,
            'latitud': _coord(lat, 'latitud') if lat not in (None, '') else None,
            'longitud': _coord(lng, 'longitud') if lng not in (None, '') else None,
        })
        partes = [f'Ejecutada ({cuadrilla}).']
        if equipo:
            partes.append(f'ONU {equipo.material.gpon_serial or equipo.material.codigo_interno}.')
        if serial_recuperado:
            partes.append(f'Equipo recuperado {serial_recuperado.strip().upper()}.')
        if observaciones:
            partes.append(observaciones.strip())
        orden.cambiar_estado(E.EJECUTADA, usuario, ' '.join(partes))
    return orden


def no_se_pudo(usuario, orden_id, motivo, detalle=''):
    if motivo not in MOTIVO:
        raise ErrorCampo('Elige el motivo.')
    detalle = (detalle or '').strip()
    if motivo == 'OTRO' and len(detalle) < 5:
        raise ErrorCampo('Explica el motivo (mínimo 5 caracteres).')
    with transaction.atomic():
        orden, cuadrilla = _mi_orden(usuario, orden_id)
        if orden.estado not in (E.PROGRAMADA, E.EN_CAMPO):
            raise ErrorCampo(f'La {orden.numero} está {orden.get_estado_display().lower()}.')
        texto = f'No ejecutada (desde campo, {cuadrilla}). Motivo: {MOTIVO[motivo]}' + (f'. {detalle}' if detalle else '')
        orden.cambiar_estado(E.NO_EJECUTADA, usuario, texto)
    return orden


def mis_ordenes(cuadrilla, fecha):
    base = (OrdenTrabajo.objects.filter(cuadrilla=cuadrilla).exclude(estado=E.ANULADA)
            .select_related('solicitud__cliente', 'solicitud__plan', 'solicitud__plan_tv', 'solicitud__plan_telefonia',
                            'solicitud__zona_cobertura', 'cuadrilla__vehiculo')
            .prefetch_related('evidencias'))
    del_dia = base.filter(fecha_programada=fecha).order_by('orden_visita', 'id')
    # Pendientes de días anteriores (atrasadas): se pueden seguir trabajando
    previas = (base.filter(fecha_programada__lt=fecha, estado__in=(E.PROGRAMADA, E.EN_CAMPO))
               .order_by('fecha_programada', 'orden_visita'))
    return list(previas), list(del_dia)
