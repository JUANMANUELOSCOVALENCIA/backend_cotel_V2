# ======================================================
# almacenes/views/operacion_views.py
# Traspasos entre almacenes.
#
#   Enviar (origen) ──▶ EN TRÁNSITO ──recibir (destino)──▶ RECIBIDO
#                              └──cancelar──▶ CANCELADO (todo vuelve al origen)
#
# · Equipos ONU: viajan enteros. Mientras están en tránsito quedan bloqueados
#   (no se envían a laboratorio, garantía ni otro traspaso).
# · Material a granel: viaja una cantidad. Se descuenta del origen al enviar y se
#   suma al registro del mismo lote/modelo en el destino al recibir.
# · Al recibir se marca lo que llegó; lo que no llegó queda como FALTANTE y
#   vuelve a figurar en el almacén de origen para su revisión.
# ======================================================
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Count, Prefetch, Q
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from usuarios.auditoria import AuditoriaMixin
from ..models import (
    Almacen, EstadoTraspaso, HistorialMaterial, Material, TraspasoAlmacen, TraspasoMaterial,
)
from ..pagination import CustomPageNumberPagination
from ..permisos import PermisoPorRol


def _estado(codigo):
    return EstadoTraspaso.objects.get(codigo=codigo)


def _cant(v):
    return float(v) if v is not None else None


def _n(v):
    """Cantidad legible: 500.00 → 500, 12.50 → 12.5"""
    return f'{Decimal(v).normalize():f}'


def _item(tm):
    m = tm.material
    destino = tm.material_destino
    return {
        'id': tm.id,
        'material_id': m.id,
        'es_unico': m.tipo_material.es_unico,
        'gpon_serial': m.gpon_serial,
        'mac_address': m.mac_address,
        'codigo_interno': m.codigo_interno,
        'modelo': f'{m.modelo.marca.nombre if m.modelo.marca_id else ""} {m.modelo.nombre}'.strip(),
        'unidad': m.modelo.unidad_medida.simbolo if m.modelo.unidad_medida_id else '',
        'lote': m.lote.numero_lote if m.lote_id else '',
        'estado': (m.estado_onu.nombre if m.estado_onu_id else (m.estado_general.nombre if m.estado_general_id else '')),
        'cantidad': _cant(tm.cantidad),
        'recibido': tm.recibido,
        'faltante': tm.faltante,
        'observaciones': tm.observaciones,
        'material_destino_id': destino.id if destino else None,
    }


def _traspaso(t, con_items=False):
    items = list(t.materiales.all())
    data = {
        'id': t.id,
        'numero': t.numero_traspaso,
        'numero_solicitud': t.numero_solicitud,
        'estado': {'codigo': t.estado.codigo, 'nombre': t.estado.nombre} if t.estado_id else None,
        'origen': {'id': t.almacen_origen_id, 'nombre': t.almacen_origen.nombre, 'codigo': t.almacen_origen.codigo},
        'destino': {'id': t.almacen_destino_id, 'nombre': t.almacen_destino.nombre, 'codigo': t.almacen_destino.codigo},
        'motivo': t.motivo,
        'observaciones_envio': t.observaciones_envio,
        'observaciones_recepcion': t.observaciones_recepcion,
        'fecha_envio': t.fecha_envio,
        'fecha_recepcion': t.fecha_recepcion,
        'dias_transito': t.duracion_transito,
        'enviado_por': t.usuario_envio.nombre_completo if t.usuario_envio_id else '',
        'recibido_por': t.usuario_recepcion.nombre_completo if t.usuario_recepcion_id else '',
        'equipos': sum(1 for i in items if i.material.tipo_material.es_unico),
        'lineas_granel': sum(1 for i in items if not i.material.tipo_material.es_unico),
        'recibidos': sum(1 for i in items if i.recibido),
        'faltantes': sum(1 for i in items if i.faltante),
        'total': len(items),
    }
    if con_items:
        data['items'] = [_item(i) for i in items]
    return data


class TraspasoAlmacenViewSet(AuditoriaMixin, viewsets.GenericViewSet):
    """Traspasos de equipos y material entre almacenes."""
    permission_classes = [PermisoPorRol]
    recurso_permiso = 'traspasos'
    accion_permiso = {'GET': 'leer', 'POST': 'actualizar'}
    queryset = TraspasoAlmacen.objects.all()
    pagination_class = CustomPageNumberPagination
    auditoria_acciones = {'create': 'Enviar traspaso', 'recibir': 'Recibir traspaso', 'cancelar': 'Cancelar traspaso'}

    def get_queryset(self):
        items = TraspasoMaterial.objects.select_related(
            'material__tipo_material', 'material__modelo__marca', 'material__modelo__unidad_medida',
            'material__lote', 'material__estado_onu', 'material__estado_general', 'material_destino',
        ).order_by('id')
        return TraspasoAlmacen.objects.select_related(
            'almacen_origen', 'almacen_destino', 'estado', 'usuario_envio', 'usuario_recepcion'
        ).prefetch_related(Prefetch('materiales', queryset=items)).order_by('-fecha_envio', '-id')

    # ---------- consultas ----------
    def list(self, request):
        qs = self.get_queryset()
        p = request.query_params
        if p.get('estado'):
            qs = qs.filter(estado__codigo__in=p['estado'].split(','))
        if p.get('almacen'):
            qs = qs.filter(Q(almacen_origen_id=p['almacen']) | Q(almacen_destino_id=p['almacen']))
        q = (p.get('search') or '').strip()
        if q:
            qs = qs.filter(Q(numero_traspaso__icontains=q) | Q(numero_solicitud__icontains=q) | Q(motivo__icontains=q)
                           | Q(materiales__material__gpon_serial__icontains=q)
                           | Q(materiales__material__mac_address__icontains=q)).distinct()
        pagina = self.paginate_queryset(qs)
        return self.get_paginated_response([_traspaso(t) for t in pagina])

    def retrieve(self, request, pk=None):
        return Response(_traspaso(self.get_object(), con_items=True))

    @action(detail=False, methods=['get'])
    def resumen(self, request):
        transito = TraspasoAlmacen.objects.filter(estado__codigo='EN_TRANSITO')
        return Response({
            'en_transito': transito.count(),
            'equipos_en_transito': Material.objects.filter(traspaso_actual__estado__codigo='EN_TRANSITO').count(),
            'con_faltantes': TraspasoAlmacen.objects.filter(materiales__faltante=True).distinct().count(),
        })

    @action(detail=False, methods=['get'])
    def disponibles(self, request):
        """Lo que se puede enviar desde un almacén: equipos ONU (paginado) o material a granel."""
        p = request.query_params
        almacen = Almacen.objects.filter(id=p.get('almacen')).first()
        if not almacen:
            return Response({'error': 'Elige el almacén de origen.'}, status=status.HTTP_400_BAD_REQUEST)
        if p.get('tipo') == 'granel':
            qs = Material.objects.filter(
                almacen_actual=almacen, tipo_material__es_unico=False, traspaso_actual__isnull=True,
                estado_general__permite_traspaso=True, cantidad__gt=0,
            ).select_related('modelo__marca', 'modelo__unidad_medida', 'lote', 'estado_general').order_by('modelo__nombre', 'lote__numero_lote')
            q = (p.get('search') or '').strip()
            if q:
                qs = qs.filter(Q(modelo__nombre__icontains=q) | Q(modelo__marca__nombre__icontains=q) | Q(lote__numero_lote__icontains=q))
            return Response({'results': [{
                'id': m.id,
                'modelo': f'{m.modelo.marca.nombre if m.modelo.marca_id else ""} {m.modelo.nombre}'.strip(),
                'unidad': m.modelo.unidad_medida.simbolo if m.modelo.unidad_medida_id else '',
                'lote': m.lote.numero_lote if m.lote_id else '',
                'cantidad': float(m.cantidad),
            } for m in qs[:200]]})

        qs = Material.objects.filter(
            almacen_actual=almacen, tipo_material__es_unico=True, traspaso_actual__isnull=True,
            estado_onu__permite_traspaso=True,
        ).select_related('modelo__marca', 'lote', 'estado_onu').order_by('modelo__nombre', 'gpon_serial')
        if p.get('modelo'):
            qs = qs.filter(modelo_id=p['modelo'])
        q = (p.get('search') or '').strip()
        if q:
            hexa = ''.join(ch for ch in q if ch.isalnum()).upper()
            filtro = Q(gpon_serial__icontains=q) | Q(mac_address__icontains=q) | Q(serial_manufacturer__icontains=q) | Q(lote__numero_lote__icontains=q)
            if len(hexa) == 12:
                filtro |= Q(mac_address=':'.join(hexa[i:i + 2] for i in range(0, 12, 2)))
            qs = qs.filter(filtro)
        pagina = self.paginate_queryset(qs)
        return self.get_paginated_response([{
            'id': m.id,
            'gpon_serial': m.gpon_serial,
            'mac_address': m.mac_address,
            'serial_manufacturer': m.serial_manufacturer,
            'modelo': f'{m.modelo.marca.nombre if m.modelo.marca_id else ""} {m.modelo.nombre}'.strip(),
            'lote': m.lote.numero_lote if m.lote_id else '',
            'estado': {'codigo': m.estado_onu.codigo, 'nombre': m.estado_onu.nombre},
        } for m in pagina])

    # ---------- enviar ----------
    def create(self, request):
        d = request.data
        origen = Almacen.objects.filter(id=d.get('almacen_origen')).first()
        destino = Almacen.objects.filter(id=d.get('almacen_destino')).first()
        errores = {}
        if not origen:
            errores['almacen_origen'] = ['Elige el almacén de origen.']
        if not destino:
            errores['almacen_destino'] = ['Elige el almacén de destino.']
        if origen and destino and origen.id == destino.id:
            errores['almacen_destino'] = ['El destino debe ser distinto del origen.']
        motivo = (d.get('motivo') or '').strip()
        if len(motivo) < 5:
            errores['motivo'] = ['Indica el motivo (mínimo 5 caracteres).']
        solicitud = str(d.get('numero_solicitud') or '').strip()
        if solicitud and not (solicitud.isdigit() and 6 <= len(solicitud) <= 10):
            errores['numero_solicitud'] = ['Debe tener entre 6 y 10 dígitos.']
        try:
            ids = list(dict.fromkeys(int(x) for x in (d.get('equipos') or [])))
            granel = [(int(g['material_id']), Decimal(str(g['cantidad']))) for g in (d.get('granel') or [])]
        except (TypeError, ValueError, KeyError, InvalidOperation):
            return Response({'error': 'Datos de equipos o cantidades no válidos.'}, status=status.HTTP_400_BAD_REQUEST)
        if not ids and not granel:
            errores['items'] = ['Agrega al menos un equipo o material.']
        if errores:
            return Response({'error': next(iter(errores.values()))[0], **errores}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            # Bloqueo de filas: nadie más puede mover estos registros mientras se envía
            equipos = list(Material.objects.select_for_update(of=('self',)).filter(id__in=ids).select_related('estado_onu', 'tipo_material'))
            if len(equipos) != len(ids):
                return Response({'error': 'Alguno de los equipos no existe.'}, status=400)
            for m in equipos:
                nombre = m.gpon_serial or m.codigo_interno
                if not m.tipo_material.es_unico:
                    return Response({'error': f'{nombre} es material a granel: envíalo por cantidad.'}, status=400)
                if m.almacen_actual_id != origen.id:
                    return Response({'error': f'{nombre} no está en {origen.nombre}.'}, status=400)
                if m.traspaso_actual_id:
                    return Response({'error': f'{nombre} ya está en otro traspaso.'}, status=400)
                if not (m.estado_onu_id and m.estado_onu.permite_traspaso):
                    return Response({'error': f'{nombre} está {m.estado_onu.nombre if m.estado_onu_id else "sin estado"} y no se puede traspasar.'}, status=400)
            lineas = []
            for mid, cant in granel:
                m = Material.objects.select_for_update(of=('self',)).select_related('estado_general', 'tipo_material', 'modelo__unidad_medida').filter(id=mid).first()
                if not m or m.tipo_material.es_unico:
                    return Response({'error': 'Material a granel no válido.'}, status=400)
                if m.almacen_actual_id != origen.id:
                    return Response({'error': f'{m.modelo.nombre} (lote {m.lote.numero_lote}) no está en {origen.nombre}.'}, status=400)
                if not (m.estado_general_id and m.estado_general.permite_traspaso):
                    return Response({'error': f'{m.modelo.nombre}: su estado no permite traspaso.'}, status=400)
                if cant <= 0 or cant > m.cantidad:
                    unidad = m.modelo.unidad_medida.simbolo if m.modelo.unidad_medida_id else ''
                    return Response({'error': f'{m.modelo.nombre}: la cantidad debe ser mayor a 0 y como máximo {_n(m.cantidad)} {unidad}.'}, status=400)
                lineas.append((m, cant))

            ahora = timezone.now()
            t = TraspasoAlmacen.objects.create(
                numero_solicitud=solicitud, almacen_origen=origen, almacen_destino=destino,
                fecha_envio=ahora, estado=_estado('EN_TRANSITO'),
                cantidad_enviada=len(equipos) + len(lineas), motivo=motivo,
                observaciones_envio=(d.get('observaciones') or '').strip(), usuario_envio=request.user,
            )
            for m in equipos:
                TraspasoMaterial.objects.create(traspaso=t, material=m)
                m.traspaso_actual = t
                m.save(update_fields=['traspaso_actual', 'updated_at'])
                self._historial(m, t, f'Enviado a {destino.nombre} ({t.numero_traspaso})', request.user, destino_almacen=destino)
            for m, cant in lineas:
                TraspasoMaterial.objects.create(traspaso=t, material=m, cantidad=cant)
                m.cantidad = m.cantidad - cant
                m.save(update_fields=['cantidad', 'updated_at'])
                self._historial(m, t, f'Salen {_n(cant)} a {destino.nombre} ({t.numero_traspaso})', request.user, destino_almacen=destino)

        t = self.get_queryset().get(pk=t.pk)
        return Response({**_traspaso(t, con_items=True), 'message': f'Traspaso {t.numero_traspaso} enviado a {destino.nombre}.'},
                        status=status.HTTP_201_CREATED)

    # ---------- recibir ----------
    @action(detail=True, methods=['post'])
    def recibir(self, request, pk=None):
        t = self.get_object()
        if not t.estado_id or t.estado.codigo != 'EN_TRANSITO':
            return Response({'error': 'Solo se recibe un traspaso que está en tránsito.'}, status=400)
        items = list(t.materiales.all())
        llegaron = request.data.get('recibidos')
        try:
            llegaron = {int(x) for x in llegaron} if llegaron is not None else {i.id for i in items}
        except (TypeError, ValueError):
            return Response({'error': 'Lista de recibidos no válida.'}, status=400)
        faltan = [i for i in items if i.id not in llegaron]
        obs = (request.data.get('observaciones') or '').strip()
        if faltan and len(obs) < 5:
            return Response({'error': f'Faltan {len(faltan)} ítem(s): explica en las observaciones qué pasó (mínimo 5 caracteres).',
                             'observaciones': ['Obligatorio si falta algo.']}, status=400)

        with transaction.atomic():
            for i in items:
                m = Material.objects.select_for_update(of=('self',)).get(pk=i.material_id)
                if i.id in llegaron:
                    if i.cantidad is None:  # equipo
                        anterior = m.almacen_actual
                        m.almacen_actual = t.almacen_destino
                        m.traspaso_actual = None
                        m.save(update_fields=['almacen_actual', 'traspaso_actual', 'updated_at'])
                        self._historial(m, t, f'Recibido en {t.almacen_destino.nombre} ({t.numero_traspaso})', request.user,
                                        anterior=anterior, destino_almacen=t.almacen_destino, obs=obs)
                        i.material_destino = m
                    else:  # granel: se suma al registro del mismo lote y modelo en el destino
                        destino = Material.objects.select_for_update(of=('self',)).filter(
                            almacen_actual=t.almacen_destino, lote_id=m.lote_id, modelo_id=m.modelo_id,
                            tipo_material_id=m.tipo_material_id, estado_general__codigo='DISPONIBLE', traspaso_actual__isnull=True,
                        ).first()
                        if destino:
                            destino.cantidad = destino.cantidad + i.cantidad
                            destino.save(update_fields=['cantidad', 'updated_at'])
                        else:
                            destino = Material(
                                tipo_material=m.tipo_material, modelo=m.modelo, lote=m.lote, tipo_origen=m.tipo_origen,
                                codigo_item_equipo=m.codigo_item_equipo, almacen_actual=t.almacen_destino,
                                estado_general=m.estado_general, es_nuevo=m.es_nuevo, cantidad=i.cantidad,
                                numero_entrega_parcial=m.numero_entrega_parcial,
                                observaciones=f'Recibido por traspaso {t.numero_traspaso}',
                            )
                            destino._sin_historial_ingreso = True
                            destino.save()
                        self._historial(destino, t, f'Entran {_n(i.cantidad)} desde {t.almacen_origen.nombre} ({t.numero_traspaso})',
                                        request.user, anterior=t.almacen_origen, destino_almacen=t.almacen_destino, obs=obs)
                        i.material_destino = destino
                    i.recibido = True
                else:
                    # No llegó: vuelve a figurar en el origen para revisarlo
                    if i.cantidad is None:
                        m.traspaso_actual = None
                        m.save(update_fields=['traspaso_actual', 'updated_at'])
                    else:
                        m.cantidad = m.cantidad + i.cantidad
                        m.save(update_fields=['cantidad', 'updated_at'])
                    self._historial(m, t, f'Faltante en traspaso {t.numero_traspaso}: no llegó a {t.almacen_destino.nombre}',
                                    request.user, obs=obs)
                    i.faltante = True
                i.save()
            t.estado = _estado('RECIBIDO')
            t.fecha_recepcion = timezone.now()
            t.usuario_recepcion = request.user
            t.cantidad_recibida = len(items) - len(faltan)
            t.observaciones_recepcion = obs
            t.save()

        t = self.get_queryset().get(pk=t.pk)
        msg = f'Traspaso {t.numero_traspaso} recibido en {t.almacen_destino.nombre}.'
        if faltan:
            msg += f' {len(faltan)} ítem(s) quedan como faltantes y vuelven a figurar en {t.almacen_origen.nombre}.'
        return Response({**_traspaso(t, con_items=True), 'message': msg})

    # ---------- cancelar ----------
    @action(detail=True, methods=['post'])
    def cancelar(self, request, pk=None):
        t = self.get_object()
        if not t.estado_id or t.estado.codigo != 'EN_TRANSITO':
            return Response({'error': 'Solo se cancela un traspaso que está en tránsito.'}, status=400)
        motivo = (request.data.get('motivo') or '').strip()
        if len(motivo) < 5:
            return Response({'error': 'Indica el motivo de la cancelación (mínimo 5 caracteres).', 'motivo': ['Obligatorio.']}, status=400)
        with transaction.atomic():
            for i in t.materiales.all():
                m = Material.objects.select_for_update(of=('self',)).get(pk=i.material_id)
                if i.cantidad is None:
                    m.traspaso_actual = None
                    m.save(update_fields=['traspaso_actual', 'updated_at'])
                else:
                    m.cantidad = m.cantidad + i.cantidad
                    m.save(update_fields=['cantidad', 'updated_at'])
                self._historial(m, t, f'Traspaso {t.numero_traspaso} cancelado: sigue en {t.almacen_origen.nombre}', request.user, obs=motivo)
            t.estado = _estado('CANCELADO')
            t.observaciones_recepcion = f'Cancelado: {motivo}'
            t.usuario_recepcion = request.user
            t.fecha_recepcion = timezone.now()
            t.save()
        t = self.get_queryset().get(pk=t.pk)
        return Response({**_traspaso(t, con_items=True), 'message': f'Traspaso {t.numero_traspaso} cancelado. Todo sigue en {t.almacen_origen.nombre}.'})

    @staticmethod
    def _historial(m, t, motivo, usuario, anterior=None, destino_almacen=None, obs=''):
        estado = (m.estado_onu.codigo if m.estado_onu_id else (m.estado_general.codigo if m.estado_general_id else ''))[:25]
        HistorialMaterial.objects.create(
            material=m, estado_anterior=estado, estado_nuevo=estado,
            almacen_anterior=anterior or m.almacen_actual, almacen_nuevo=destino_almacen or m.almacen_actual,
            motivo=motivo[:100], observaciones=obs, traspaso_relacionado=t, usuario_responsable=usuario,
        )
