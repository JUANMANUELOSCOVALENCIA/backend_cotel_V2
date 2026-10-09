# ======================================================
# almacenes/views/garantia_views.py
# Garantías con el proveedor.
#
#   DEFECTUOSO ──enviar──▶ EN GARANTÍA ──respuesta del proveedor──▶
#       · Cambiado por otro equipo → el nuevo entra como NUEVO (laboratorio) y el original queda REEMPLAZADO
#       · Devuelto reparado        → el mismo equipo vuelve a NUEVO (laboratorio)
#       · Sin reposición           → el original queda DADO DE BAJA
# ======================================================
import re
from datetime import timedelta

from django.db import transaction
from django.db.models import Count, Q, Prefetch
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from usuarios.auditoria import AuditoriaMixin
from ..models import (
    EnvioGarantia, EnvioGarantiaDetalle, EstadoMaterialONU, HistorialMaterial, InspeccionLaboratorio,
    Material, Proveedor, SectorSolicitante, TipoIngreso, PRUEBAS_LABORATORIO,
)
from ..pagination import CustomPageNumberPagination
from ..permisos import PermisoPorRol

DIAS_ALERTA = 30  # un equipo con más días en garantía se marca como demorado
NOMBRE_FALLA = {codigo: nombre for _, nombre, codigo in PRUEBAS_LABORATORIO}


def _estado(codigo):
    return EstadoMaterialONU.objects.get(codigo=codigo)


def _mac(valor):
    hexa = re.sub(r'[^0-9A-Fa-f]', '', str(valor or '')).upper()
    return ':'.join(hexa[i:i + 2] for i in range(0, 12, 2)) if len(hexa) == 12 else None


def _falla(material):
    """Texto de la falla según la última inspección de laboratorio."""
    insp = material.inspecciones_laboratorio.order_by('-fecha_inspeccion').first()
    if not insp:
        return ''
    fallas = ', '.join(NOMBRE_FALLA.get(f, f) for f in (insp.fallas_detectadas or []))
    texto = ' · '.join(t for t in (fallas, insp.observaciones_tecnico) if t)
    return texto[:200]


def _equipo(m):
    lote = m.lote
    hoy = timezone.localdate()
    return {
        'id': m.id,
        'gpon_serial': m.gpon_serial,
        'mac_address': m.mac_address,
        'serial_manufacturer': m.serial_manufacturer,
        'codigo_interno': m.codigo_interno,
        'modelo': f'{m.modelo.marca.nombre if m.modelo.marca_id else ""} {m.modelo.nombre}'.strip(),
        'lote': {
            'id': lote.id,
            'numero_lote': lote.numero_lote,
            'fecha_fin_garantia': lote.fecha_fin_garantia,
            'garantia_vigente': (lote.fecha_fin_garantia >= hoy) if lote.fecha_fin_garantia else None,
        },
        'proveedor': {'id': lote.proveedor_id, 'nombre': lote.proveedor.nombre_comercial if lote.proveedor_id else ''},
        'almacen': m.almacen_actual.nombre if m.almacen_actual_id else '',
    }


def _envio(e, con_detalles=False):
    hoy = timezone.localdate()
    fin = timezone.localtime(e.fecha_cierre).date() if e.fecha_cierre else hoy
    detalles = list(e.detalles.all())
    cuenta = {r: 0 for r, _ in EnvioGarantiaDetalle.RESULTADOS}
    for d in detalles:
        cuenta[d.resultado] += 1
    data = {
        'id': e.id,
        'numero': e.numero,
        'proveedor': {'id': e.proveedor_id, 'nombre': e.proveedor.nombre_comercial},
        'fecha_envio': e.fecha_envio,
        'referencia': e.referencia,
        'area_tramite': {'id': e.area_tramite_id, 'nombre': e.area_tramite.nombre} if e.area_tramite_id else None,
        'observaciones': e.observaciones,
        'cerrado': e.cerrado,
        'fecha_cierre': e.fecha_cierre,
        'dias': (fin - e.fecha_envio).days,
        'creado_por': e.created_by.nombre_completo if e.created_by_id else '',
        'total': len(detalles),
        'pendientes': cuenta['PENDIENTE'],
        'reemplazados': cuenta['REEMPLAZADO'],
        'reparados': cuenta['REPARADO'],
        'sin_reposicion': cuenta['SIN_REPOSICION'],
    }
    if con_detalles:
        data['detalles'] = [{
            'id': d.id,
            'material': _equipo(d.material),
            'falla': d.falla,
            'resultado': d.resultado,
            'resultado_display': d.get_resultado_display(),
            'reposicion': {
                'id': d.material_reposicion_id,
                'gpon_serial': d.material_reposicion.gpon_serial,
                'mac_address': d.material_reposicion.mac_address,
            } if d.material_reposicion_id else None,
            'fecha_respuesta': d.fecha_respuesta,
            'observaciones': d.observaciones,
            'respondido_por': d.respondido_por.nombre_completo if d.respondido_por_id else '',
        } for d in detalles]
    return data


class EnvioGarantiaViewSet(AuditoriaMixin, viewsets.GenericViewSet):
    """Envíos de equipos defectuosos al proveedor y su respuesta."""
    permission_classes = [PermisoPorRol]
    recurso_permiso = 'materiales'
    accion_permiso = {'GET': 'leer', 'POST': 'actualizar'}
    queryset = EnvioGarantia.objects.all()
    pagination_class = CustomPageNumberPagination
    auditoria_acciones = {'create': 'Enviar a garantía', 'resolver': 'Respuesta del proveedor'}

    def get_queryset(self):
        detalles = EnvioGarantiaDetalle.objects.select_related(
            'material__modelo__marca', 'material__lote__proveedor', 'material__almacen_actual',
            'material_reposicion', 'respondido_por',
        ).order_by('id')
        return EnvioGarantia.objects.select_related('proveedor', 'area_tramite', 'created_by').prefetch_related(
            Prefetch('detalles', queryset=detalles)
        )

    # ----- listas -----
    def list(self, request):
        qs = self.get_queryset()
        p = request.query_params
        if p.get('cerrado') in ('true', 'false'):
            qs = qs.filter(cerrado=p['cerrado'] == 'true')
        if p.get('proveedor'):
            qs = qs.filter(proveedor_id=p['proveedor'])
        q = (p.get('search') or '').strip()
        if q:
            qs = qs.filter(Q(numero__icontains=q) | Q(referencia__icontains=q)
                           | Q(detalles__material__gpon_serial__icontains=q)
                           | Q(detalles__material__mac_address__icontains=q)
                           | Q(detalles__material_reposicion__gpon_serial__icontains=q)).distinct()
        pagina = self.paginate_queryset(qs)
        datos = [_envio(e, con_detalles=p.get('detalles') == 'true') for e in (pagina if pagina is not None else qs)]
        return self.get_paginated_response(datos) if pagina is not None else Response(datos)

    def retrieve(self, request, pk=None):
        return Response(_envio(self.get_object(), con_detalles=True))

    @action(detail=False, methods=['get'])
    def por_enviar(self, request):
        """Equipos rechazados por laboratorio que todavía no se enviaron al proveedor."""
        qs = Material.objects.filter(tipo_material__es_unico=True, estado_onu__codigo='DEFECTUOSO').select_related(
            'modelo__marca', 'lote__proveedor', 'almacen_actual'
        ).prefetch_related(
            Prefetch('inspecciones_laboratorio', queryset=InspeccionLaboratorio.objects.order_by('-fecha_inspeccion'))
        ).order_by('lote__proveedor__nombre_comercial', 'lote__numero_lote', 'id')
        datos = []
        for m in qs:
            d = _equipo(m)
            insp = next(iter(m.inspecciones_laboratorio.all()), None)
            if insp:
                fallas = ', '.join(NOMBRE_FALLA.get(f, f) for f in (insp.fallas_detectadas or []))
                d['falla'] = ' · '.join(t for t in (fallas, insp.observaciones_tecnico) if t)[:200]
                d['fecha_rechazo'] = insp.fecha_inspeccion
            else:
                d['falla'], d['fecha_rechazo'] = '', None
            datos.append(d)
        return Response({'total': len(datos), 'equipos': datos})

    @action(detail=False, methods=['get'])
    def resumen(self, request):
        limite = timezone.localdate() - timedelta(days=DIAS_ALERTA)
        pend = EnvioGarantiaDetalle.objects.filter(resultado=EnvioGarantiaDetalle.PENDIENTE)
        return Response({
            'por_enviar': Material.objects.filter(tipo_material__es_unico=True, estado_onu__codigo='DEFECTUOSO').count(),
            'en_garantia': pend.count(),
            'envios_abiertos': EnvioGarantia.objects.filter(cerrado=False).count(),
            'demorados': pend.filter(envio__fecha_envio__lt=limite).count(),
            'dias_alerta': DIAS_ALERTA,
        })

    # ----- enviar a garantía -----
    def create(self, request):
        d = request.data
        errores = {}
        proveedor = Proveedor.objects.filter(id=d.get('proveedor')).first()
        if not proveedor:
            errores['proveedor'] = ['Elige el proveedor.']
        try:
            ids = list(dict.fromkeys(int(x) for x in (d.get('materiales_ids') or [])))
        except (TypeError, ValueError):
            ids = []
        if not ids:
            errores['materiales_ids'] = ['Selecciona al menos un equipo.']
        area = None
        if d.get('area_tramite'):
            area = SectorSolicitante.objects.filter(id=d.get('area_tramite')).first()
            if not area:
                errores['area_tramite'] = ['Área no válida.']
        fecha = d.get('fecha_envio') or timezone.localdate().isoformat()
        try:
            fecha = timezone.datetime.strptime(str(fecha), '%Y-%m-%d').date()
            if fecha > timezone.localdate():
                errores['fecha_envio'] = ['La fecha de envío no puede ser futura.']
        except ValueError:
            errores['fecha_envio'] = ['Fecha no válida.']
        if errores:
            return Response({'error': next(iter(errores.values()))[0], **errores}, status=status.HTTP_400_BAD_REQUEST)

        equipos = list(Material.objects.filter(id__in=ids).select_related('estado_onu', 'lote', 'almacen_actual')
                       .prefetch_related('inspecciones_laboratorio'))
        no_defectuosos = [m.gpon_serial or m.codigo_interno for m in equipos if not m.estado_onu_id or m.estado_onu.codigo != 'DEFECTUOSO']
        if len(equipos) != len(ids) or no_defectuosos:
            return Response({'error': 'Solo se envían equipos en estado Defectuoso. '
                                      + (f'No lo están: {", ".join(no_defectuosos[:5])}.' if no_defectuosos else '')},
                            status=status.HTTP_400_BAD_REQUEST)
        de_otro = [m.gpon_serial or m.codigo_interno for m in equipos if m.lote.proveedor_id != proveedor.id]
        if de_otro:
            return Response({'error': f'Estos equipos no se compraron a {proveedor.nombre_comercial}: {", ".join(de_otro[:5])}. '
                                      'Envía cada grupo a su proveedor.'}, status=status.HTTP_400_BAD_REQUEST)

        en_garantia = _estado('DEVUELTO_PROVEEDOR')
        with transaction.atomic():
            envio = EnvioGarantia.objects.create(
                numero=EnvioGarantia.siguiente_numero(), proveedor=proveedor, fecha_envio=fecha,
                referencia=(d.get('referencia') or '').strip()[:100], area_tramite=area,
                observaciones=(d.get('observaciones') or '').strip(), created_by=request.user,
            )
            for m in equipos:
                EnvioGarantiaDetalle.objects.create(envio=envio, material=m, falla=_falla(m))
                m.estado_onu = en_garantia
                m.save(update_fields=['estado_onu', 'updated_at'])
                HistorialMaterial.objects.create(
                    material=m, estado_anterior='DEFECTUOSO', estado_nuevo='DEVUELTO_PROVEEDOR',
                    almacen_anterior=m.almacen_actual, almacen_nuevo=m.almacen_actual,
                    motivo=f'Enviado a garantía {envio.numero}',
                    observaciones=f'{proveedor.nombre_comercial}{" · " + envio.referencia if envio.referencia else ""}',
                    usuario_responsable=request.user,
                )
        envio = self.get_queryset().get(pk=envio.pk)
        return Response({**_envio(envio, con_detalles=True), 'message': f'{len(equipos)} equipo(s) enviados a garantía ({envio.numero}).'},
                        status=status.HTTP_201_CREATED)

    # ----- respuesta del proveedor por equipo -----
    @action(detail=True, methods=['post'])
    def resolver(self, request, pk=None):
        envio = self.get_object()
        d = request.data
        det = envio.detalles.filter(id=d.get('detalle')).select_related('material__estado_onu', 'material__modelo', 'material__lote').first()
        if not det:
            return Response({'error': 'Equipo no encontrado en este envío.'}, status=status.HTTP_400_BAD_REQUEST)
        if det.resultado != EnvioGarantiaDetalle.PENDIENTE:
            return Response({'error': 'Este equipo ya tiene registrada la respuesta del proveedor.'}, status=status.HTTP_400_BAD_REQUEST)
        resultado = d.get('resultado')
        obs = (d.get('observaciones') or '').strip()
        original = det.material

        if resultado == EnvioGarantiaDetalle.REEMPLAZADO:
            mac = _mac(d.get('mac_address'))
            gpon = str(d.get('gpon_serial') or '').strip().upper()
            dsn = str(d.get('serial_manufacturer') or '').strip()
            if not d.get('mac_address'):
                return Response({'error': 'Ingresa la MAC del equipo nuevo.', 'mac_address': ['Obligatoria.']}, status=400)
            if not mac:
                return Response({'error': 'MAC no válida: deben ser 12 caracteres hexadecimales (AA:BB:CC:DD:EE:FF).',
                                 'mac_address': ['Formato no válido.']}, status=400)
            if len(gpon) < 8:
                return Response({'error': 'El GPON serial debe tener al menos 8 caracteres.', 'gpon_serial': ['Muy corto.']}, status=400)
            if dsn and len(dsn) < 6:
                return Response({'error': 'El D-SN debe tener al menos 6 caracteres.', 'serial_manufacturer': ['Muy corto.']}, status=400)
            if mac == (original.mac_address or '').upper() or gpon == (original.gpon_serial or '').upper():
                return Response({'error': 'Esos datos son del mismo equipo enviado. Si el proveedor lo devolvió reparado, elige "Devuelto reparado".'},
                                status=400)
            for campo, valor, nombre, clave in (('mac_address', mac, 'La MAC', 'mac_address'), ('gpon_serial__iexact', gpon, 'El GPON', 'gpon_serial')):
                otro = Material.objects.select_related('estado_onu').filter(**{campo: valor}).first()
                if otro:
                    estado = otro.estado_onu.nombre if otro.estado_onu_id else 'sin estado'
                    return Response({'error': f'{nombre} {valor} ya pertenece al equipo {otro.gpon_serial or otro.codigo_interno} ({estado}).',
                                     clave: ['Ya registrada.']}, status=400)
            with transaction.atomic():
                nuevo = Material(
                    tipo_material=original.tipo_material, modelo=original.modelo, lote=original.lote,
                    mac_address=mac, gpon_serial=gpon, serial_manufacturer=dsn or None,
                    codigo_item_equipo=original.codigo_item_equipo, almacen_actual=original.almacen_actual,
                    estado_onu=_estado('NUEVO'), es_nuevo=True, cantidad=1,
                    tipo_origen=TipoIngreso.objects.filter(codigo='REPOSICION').first() or original.tipo_origen,
                    equipo_original=original, numero_entrega_parcial=original.numero_entrega_parcial,
                    observaciones=f'Reposición por garantía {envio.numero} (reemplaza {original.gpon_serial})',
                )
                nuevo._sin_historial_ingreso = True
                nuevo.save()
                HistorialMaterial.objects.create(
                    material=nuevo, estado_anterior='', estado_nuevo='NUEVO',
                    almacen_anterior=None, almacen_nuevo=nuevo.almacen_actual,
                    motivo=f'Ingreso por garantía {envio.numero}', observaciones=f'Reemplaza {original.gpon_serial}',
                    usuario_responsable=request.user,
                )
                self._cerrar_original(original, 'REEMPLAZADO', f'Reemplazado por {gpon} (garantía {envio.numero})', obs, request.user)
                det.material_reposicion = nuevo
                mensaje = f'Equipo {gpon} registrado como Nuevo (pasa a laboratorio). {original.gpon_serial} queda Reemplazado.'
        elif resultado == EnvioGarantiaDetalle.REPARADO:
            with transaction.atomic():
                original.estado_onu = _estado('NUEVO')
                original.fecha_envio_laboratorio = None
                original.fecha_retorno_laboratorio = None
                original.save(update_fields=['estado_onu', 'fecha_envio_laboratorio', 'fecha_retorno_laboratorio', 'updated_at'])
                HistorialMaterial.objects.create(
                    material=original, estado_anterior='DEVUELTO_PROVEEDOR', estado_nuevo='NUEVO',
                    almacen_anterior=original.almacen_actual, almacen_nuevo=original.almacen_actual,
                    motivo=f'Vuelve reparado de garantía {envio.numero}', observaciones=obs, usuario_responsable=request.user,
                )
                mensaje = f'{original.gpon_serial} vuelve como Nuevo y pasa otra vez por laboratorio.'
        elif resultado == EnvioGarantiaDetalle.SIN_REPOSICION:
            if len(obs) < 5:
                return Response({'error': 'Indica el motivo (mínimo 5 caracteres): por ejemplo, garantía vencida.',
                                 'observaciones': ['Obligatorio.']}, status=400)
            with transaction.atomic():
                self._cerrar_original(original, 'BAJA', f'Dado de baja: sin reposición (garantía {envio.numero})', obs, request.user)
                mensaje = f'{original.gpon_serial} queda Dado de baja.'
        else:
            return Response({'error': 'Elige la respuesta del proveedor.'}, status=status.HTTP_400_BAD_REQUEST)

        det.resultado = resultado
        det.fecha_respuesta = timezone.now()
        det.observaciones = obs
        det.respondido_por = request.user
        det.save()
        envio.actualizar_cierre()
        envio = self.get_queryset().get(pk=envio.pk)
        return Response({**_envio(envio, con_detalles=True),
                         'message': mensaje + (' Envío completo.' if envio.cerrado else '')})

    @staticmethod
    def _cerrar_original(original, codigo, motivo, obs, usuario):
        original.estado_onu = _estado(codigo)
        original.save(update_fields=['estado_onu', 'updated_at'])
        HistorialMaterial.objects.create(
            material=original, estado_anterior='DEVUELTO_PROVEEDOR', estado_nuevo=codigo,
            almacen_anterior=original.almacen_actual, almacen_nuevo=original.almacen_actual,
            motivo=motivo[:100], observaciones=obs, usuario_responsable=usuario,
        )
