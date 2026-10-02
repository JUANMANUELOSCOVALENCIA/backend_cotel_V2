# ======================================================
# almacenes/views/laboratorio_views.py
# Laboratorio: control de calidad de equipos ONU.
#
# Recorrido de un equipo:
#   NUEVO / REINGRESADO / (re-prueba) ──enviar──▶ EN_LABORATORIO
#   EN_LABORATORIO ──inspección──▶ DISPONIBLE (aprobado) | DEFECTUOSO (rechazado)
#
# El resultado SOLO se registra con una inspección (queda el informe, las
# pruebas, el técnico y una línea en el historial del equipo).
# ======================================================

from datetime import timedelta

from django.db import IntegrityError, transaction
from django.db.models import Avg, Count, F, Q
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import (
    EstadoMaterialONU, HistorialMaterial, InspeccionLaboratorio, Lote, Material, PRUEBAS_LABORATORIO,
)
from ..permisos import PermisoPorRol

DIAS_LIMITE = 15  # a partir de aquí un equipo se considera demorado en laboratorio

# Estados desde los que un equipo puede (re)enviarse a laboratorio
ESTADOS_ENVIABLES = ('NUEVO', 'REINGRESADO', 'DISPONIBLE', 'DEFECTUOSO')

# Pruebas (campo, nombre, código de falla): definidas en models.PRUEBAS_LABORATORIO
PRUEBAS = PRUEBAS_LABORATORIO


# ---------- utilidades ----------

def _estado(codigo):
    return EstadoMaterialONU.objects.get(codigo=codigo)


def _onus():
    return Material.objects.filter(tipo_material__es_unico=True)


def _base_lista():
    return _onus().select_related(
        'modelo__marca', 'lote__proveedor', 'almacen_actual', 'estado_onu'
    )


def _filtrar(qs, params):
    """Filtros comunes: búsqueda libre, almacén y lote."""
    q = (params.get('search') or '').strip()
    if q:
        qs = qs.filter(
            Q(gpon_serial__icontains=q) | Q(mac_address__icontains=q)
            | Q(serial_manufacturer__icontains=q) | Q(codigo_interno__icontains=q)
            | Q(lote__numero_lote__icontains=q) | Q(modelo__nombre__icontains=q)
        )
    if params.get('almacen'):
        qs = qs.filter(almacen_actual_id=params['almacen'])
    if params.get('lote'):
        qs = qs.filter(lote_id=params['lote'])
    return qs


def _equipo(m, ahora=None):
    """Representación compacta de un equipo para las listas de laboratorio."""
    ahora = ahora or timezone.now()
    dias = None
    if m.estado_onu and m.estado_onu.codigo == 'EN_LABORATORIO' and m.fecha_envio_laboratorio:
        dias = (ahora - m.fecha_envio_laboratorio).days
    return {
        'id': m.id,
        'codigo_interno': m.codigo_interno,
        'gpon_serial': m.gpon_serial,
        'mac_address': m.mac_address,
        'serial_manufacturer': m.serial_manufacturer,
        'modelo': f'{m.modelo.marca.nombre if m.modelo.marca_id else ""} {m.modelo.nombre}'.strip(),
        'modelo_id': m.modelo_id,
        'lote': {
            'id': m.lote_id,
            'numero_lote': m.lote.numero_lote,
            'proveedor': m.lote.proveedor.nombre_comercial if m.lote.proveedor_id else '',
        },
        'numero_entrega_parcial': m.numero_entrega_parcial or 0,
        'almacen': m.almacen_actual.nombre if m.almacen_actual_id else '',
        'estado': {'codigo': m.estado_onu.codigo, 'nombre': m.estado_onu.nombre} if m.estado_onu_id else None,
        'es_nuevo': m.es_nuevo,
        'fecha_ingreso': m.created_at,
        'fecha_envio_laboratorio': m.fecha_envio_laboratorio,
        'dias_en_laboratorio': dias,
        'inspecciones_previas': getattr(m, 'n_inspecciones', 0),
        'pruebas': m.modelo.pruebas_aplicables,
    }


def _enviar(materiales, usuario):
    """Envía a laboratorio. Devuelve (enviados, omitidos)."""
    enviados, omitidos = 0, []
    with transaction.atomic():
        for m in materiales:
            codigo = m.estado_onu.codigo if m.estado_onu_id else ''
            if codigo not in ESTADOS_ENVIABLES:
                omitidos.append(m.gpon_serial or m.codigo_interno)
                continue
            m.enviar_a_laboratorio(usuario=usuario)
            enviados += 1
    return enviados, omitidos


def _respuesta_envio(enviados, omitidos, contexto=''):
    if not enviados and not omitidos:
        return Response({'success': True, 'enviados': 0, 'message': f'No hay equipos pendientes de enviar{contexto}.'})
    msg = f'{enviados} equipo(s) enviados a laboratorio{contexto}.'
    if omitidos:
        msg += f' {len(omitidos)} no se enviaron por su estado actual.'
    return Response({'success': True, 'enviados': enviados, 'omitidos': omitidos, 'message': msg})


def _siguiente_informe(fecha_txt):
    """INF-AAAAMMDD-NNN siguiente libre para la fecha."""
    prefijo = f'INF-{fecha_txt}-'
    usados = InspeccionLaboratorio.objects.filter(numero_informe__startswith=prefijo).values_list('numero_informe', flat=True)
    mayor = 0
    for n in usados:
        resto = n[len(prefijo):]
        if resto.isdigit():
            mayor = max(mayor, int(resto))
    return prefijo, mayor + 1


# ---------- vistas ----------

class LaboratorioView(APIView):
    """GET: resumen del laboratorio. POST: enviar equipos a laboratorio."""
    permission_classes = [PermisoPorRol]
    recurso_permiso = 'laboratorio'
    accion_permiso = {'GET': 'leer', 'POST': 'actualizar'}

    def get(self, request):
        ahora = timezone.now()
        limite = ahora - timedelta(days=DIAS_LIMITE)
        hace_30 = ahora - timedelta(days=30)

        resumen = _onus().aggregate(
            por_enviar=Count('id', filter=Q(estado_onu__codigo='NUEVO')),
            en_laboratorio=Count('id', filter=Q(estado_onu__codigo='EN_LABORATORIO')),
            demorados=Count('id', filter=Q(estado_onu__codigo='EN_LABORATORIO', fecha_envio_laboratorio__lt=limite)),
        )
        ult = InspeccionLaboratorio.objects.filter(fecha_inspeccion__gte=hace_30).aggregate(
            total=Count('id'),
            aprobados=Count('id', filter=Q(aprobado=True)),
            rechazados=Count('id', filter=Q(aprobado=False)),
        )
        # Tiempo medio en laboratorio (envío → resultado) de lo procesado en 30 días
        dur = _onus().filter(
            fecha_retorno_laboratorio__gte=hace_30,
            fecha_envio_laboratorio__isnull=False,
            fecha_retorno_laboratorio__gt=F('fecha_envio_laboratorio'),
        ).aggregate(d=Avg(F('fecha_retorno_laboratorio') - F('fecha_envio_laboratorio')))['d']

        return Response({
            'resumen': resumen,
            'ultimos_30_dias': {
                **ult,
                'porcentaje_aprobacion': round(ult['aprobados'] * 100 / ult['total'], 1) if ult['total'] else None,
                'dias_promedio': round(dur.total_seconds() / 86400, 1) if dur else None,
            },
            'dias_limite': DIAS_LIMITE,
            'pruebas': [{'campo': c, 'nombre': n} for c, n, _ in PRUEBAS],
        })

    def post(self, request):
        """Enviar uno o varios equipos: {material_id} o {materiales_ids: [...]}."""
        if request.data.get('accion') == 'retornar':
            return Response({'error': 'El resultado de laboratorio se registra con una inspección.'},
                            status=status.HTTP_400_BAD_REQUEST)
        ids = request.data.get('materiales_ids') or (
            [request.data['material_id']] if request.data.get('material_id') else [])
        if not ids:
            return Response({'error': 'Indica qué equipos enviar.'}, status=status.HTTP_400_BAD_REQUEST)
        materiales = list(_onus().filter(id__in=ids).select_related('estado_onu', 'tipo_material', 'almacen_actual'))
        if not materiales:
            return Response({'error': 'No se encontraron los equipos indicados.'}, status=status.HTTP_404_NOT_FOUND)
        return _respuesta_envio(*_enviar(materiales, request.user))


class LaboratorioMasivoView(APIView):
    """Envíos masivos: lote completo, una entrega del lote o todos los pendientes."""
    permission_classes = [PermisoPorRol]
    recurso_permiso = 'laboratorio'
    accion_permiso = 'actualizar'

    def post(self, request):
        accion = request.data.get('accion')
        criterios = request.data.get('criterios') or {}
        pendientes = _onus().filter(estado_onu__codigo='NUEVO').select_related('estado_onu', 'tipo_material', 'almacen_actual')

        if accion == 'enviar_pendientes':
            return _respuesta_envio(*_enviar(pendientes, request.user))

        if accion in ('enviar_lote_completo', 'enviar_entrega_parcial'):
            lote = Lote.objects.filter(id=criterios.get('lote_id')).first()
            if not lote:
                return Response({'error': 'Lote no encontrado.'}, status=status.HTTP_404_NOT_FOUND)
            qs = pendientes.filter(lote=lote)
            contexto = f' del lote {lote.numero_lote}'
            if accion == 'enviar_entrega_parcial':
                n = criterios.get('numero_entrega')
                if n is None or str(n).strip() == '':
                    return Response({'error': 'Indica la entrega.'}, status=status.HTTP_400_BAD_REQUEST)
                n = int(n)
                qs = qs.filter(numero_entrega_parcial=n) if n else qs.filter(Q(numero_entrega_parcial=0) | Q(numero_entrega_parcial__isnull=True))
                contexto = f' (entrega #{n}){contexto}' if n else f' (recepción inicial){contexto}'
            return _respuesta_envio(*_enviar(qs, request.user), contexto)

        if accion == 'retornar_masivo':
            return Response({'error': 'El resultado de laboratorio se registra con una inspección.'},
                            status=status.HTTP_400_BAD_REQUEST)
        return Response({'error': 'Acción no válida.'}, status=status.HTTP_400_BAD_REQUEST)


class LaboratorioConsultaView(APIView):
    """Listas del laboratorio: ?tipo=pendientes_inspeccion | en_laboratorio | tiempo_excesivo"""
    permission_classes = [PermisoPorRol]
    recurso_permiso = 'laboratorio'
    accion_permiso = 'leer'

    def get(self, request):
        tipo = request.query_params.get('tipo', 'en_laboratorio')
        qs = _filtrar(_base_lista(), request.query_params).annotate(n_inspecciones=Count('inspecciones_laboratorio'))

        if tipo == 'pendientes_inspeccion':
            qs = qs.filter(estado_onu__codigo='NUEVO').order_by('lote__numero_lote', 'numero_entrega_parcial', 'id')
        elif tipo == 'en_laboratorio':
            qs = qs.filter(estado_onu__codigo='EN_LABORATORIO').order_by('fecha_envio_laboratorio', 'id')
        elif tipo == 'tiempo_excesivo':
            dias = int(request.query_params.get('dias_limite') or DIAS_LIMITE)
            qs = qs.filter(estado_onu__codigo='EN_LABORATORIO',
                           fecha_envio_laboratorio__lt=timezone.now() - timedelta(days=dias)
                           ).order_by('fecha_envio_laboratorio')
        else:
            return Response({'error': 'Tipo de consulta no válido.'}, status=status.HTTP_400_BAD_REQUEST)

        ahora = timezone.now()
        datos = [_equipo(m, ahora) for m in qs]
        return Response({'total': len(datos), 'materiales': datos})


class InspeccionLaboratorioView(APIView):
    """GET: historial de inspecciones (paginado). POST: registrar resultado."""
    permission_classes = [PermisoPorRol]
    recurso_permiso = 'laboratorio'
    accion_permiso = {'GET': 'leer', 'POST': 'actualizar'}

    # ----- historial -----
    def get(self, request):
        p = request.query_params
        qs = InspeccionLaboratorio.objects.select_related(
            'material__modelo__marca', 'material__lote__proveedor', 'usuario_responsable'
        ).order_by('-fecha_inspeccion', '-id')
        if p.get('material_id'):
            qs = qs.filter(material_id=p['material_id'])
        else:
            dias = p.get('dias') or p.get('days')
            if dias and str(dias).isdigit() and int(dias) > 0:
                qs = qs.filter(fecha_inspeccion__gte=timezone.now() - timedelta(days=int(dias)))
        if p.get('aprobado') in ('true', 'false'):
            qs = qs.filter(aprobado=p['aprobado'] == 'true')
        q = (p.get('search') or '').strip()
        if q:
            qs = qs.filter(
                Q(numero_informe__icontains=q) | Q(material__gpon_serial__icontains=q)
                | Q(material__mac_address__icontains=q) | Q(material__codigo_interno__icontains=q)
                | Q(material__lote__numero_lote__icontains=q)
            )

        total = qs.count()
        try:
            page_size = max(1, min(int(p.get('page_size', 20)), 200))
            page = max(1, int(p.get('page', 1)))
        except ValueError:
            page_size, page = 20, 1
        filas = qs[(page - 1) * page_size: page * page_size]

        def fila(i):
            m = i.material
            return {
                'id': i.id,
                'numero_informe': i.numero_informe,
                'fecha_inspeccion': i.fecha_inspeccion,
                'aprobado': i.aprobado,
                'pruebas': [{'nombre': n, 'ok': ok} for n, ok in i.resultados_pruebas],
                'fallas': [n for n, ok in i.resultados_pruebas if not ok],
                'observaciones': i.observaciones_tecnico,
                'comentarios': i.comentarios_adicionales,
                'tecnico': i.usuario_responsable.nombre_completo if i.usuario_responsable_id else i.tecnico_revisor,
                'material': {
                    'id': m.id,
                    'codigo_interno': m.codigo_interno,
                    'gpon_serial': m.gpon_serial,
                    'mac_address': m.mac_address,
                    'modelo': f'{m.modelo.marca.nombre if m.modelo.marca_id else ""} {m.modelo.nombre}'.strip(),
                    'lote': m.lote.numero_lote,
                },
            }

        return Response({
            'count': total,
            'results': [fila(i) for i in filas],
            # compatibilidad con la versión anterior
            'total': total,
        })

    # ----- registrar resultado -----
    def post(self, request):
        d = request.data
        ids = d.get('materiales_ids') or ([d['material']] if d.get('material') else [])
        try:
            ids = list(dict.fromkeys(int(x) for x in ids))
        except (TypeError, ValueError):
            return Response({'error': 'Lista de equipos no válida.'}, status=status.HTTP_400_BAD_REQUEST)
        if not ids:
            return Response({'error': 'Selecciona al menos un equipo.'}, status=status.HTTP_400_BAD_REQUEST)

        materiales = list(_onus().filter(id__in=ids).select_related('estado_onu', 'almacen_actual', 'modelo'))
        en_lab = [m for m in materiales if m.estado_onu_id and m.estado_onu.codigo == 'EN_LABORATORIO']
        if len(en_lab) != len(ids):
            fuera = [m.gpon_serial or m.codigo_interno for m in materiales if m not in en_lab]
            msg = 'Solo se pueden inspeccionar equipos que están en laboratorio.'
            if fuera:
                msg += f' No lo están: {", ".join(fuera[:5])}{"…" if len(fuera) > 5 else ""}.'
            return Response({'error': msg}, status=status.HTTP_400_BAD_REQUEST)

        # Resultado de las pruebas (el servidor decide aprobado/fallas)
        def bool_(v):
            return v in (True, 'true', 'True', 1, '1')
        enviados = {c: bool_(d.get(c, True)) for c, _, _ in PRUEBAS}

        def evaluar(m):
            """Solo cuentan las pruebas que aplican al modelo del equipo."""
            aplica = m.modelo.pruebas_aplicables
            res = {c: (enviados[c] if c in aplica else True) for c, _, _ in PRUEBAS}
            fallas = [codigo for c, _, codigo in PRUEBAS if c in aplica and not enviados[c]]
            return aplica, res, fallas

        evaluados = [(m, *evaluar(m)) for m in en_lab]
        hay_rechazo = any(f for _, _, _, f in evaluados)
        observaciones = (d.get('observaciones_tecnico') or '').strip()
        comentarios = (d.get('comentarios_adicionales') or '').strip()
        if hay_rechazo and len(observaciones) < 5:
            return Response({'error': 'Describe la falla en las observaciones (mínimo 5 caracteres).',
                             'observaciones_tecnico': ['Describe la falla encontrada.']},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            minutos = max(0, int(d.get('tiempo_inspeccion_minutos') or 0))
        except (TypeError, ValueError):
            minutos = 0

        # Número de informe: el indicado por el técnico o uno automático
        informe = (d.get('numero_informe') or '').strip().upper()
        if len(informe) > 40:
            return Response({'error': 'El número de informe es demasiado largo (máx. 40).'}, status=status.HTTP_400_BAD_REQUEST)
        if informe:
            numeros = [informe] if len(en_lab) == 1 else [f'{informe}-{i:03d}' for i in range(1, len(en_lab) + 1)]
            repetidos = list(InspeccionLaboratorio.objects.filter(numero_informe__in=numeros).values_list('numero_informe', flat=True))
            if repetidos:
                return Response({'error': f'El informe {repetidos[0]} ya está registrado. Usa otro número o déjalo vacío.',
                                 'numero_informe': ['Ese número ya está registrado.']},
                                status=status.HTTP_400_BAD_REQUEST)
        else:
            prefijo, desde = _siguiente_informe(timezone.localdate().strftime('%Y%m%d'))
            numeros = [f'{prefijo}{desde + i:03d}' for i in range(len(en_lab))]

        estado_ok, estado_mal = _estado('DISPONIBLE'), _estado('DEFECTUOSO')
        ahora = timezone.now()
        aprobados = 0
        try:
            with transaction.atomic():
                for (m, aplica, resultados, fallas), numero in zip(evaluados, numeros):
                    aprobado = not fallas
                    aprobados += aprobado
                    nuevo_estado = estado_ok if aprobado else estado_mal
                    # en un lote mixto, la descripción de la falla solo va a los rechazados
                    obs = observaciones if (not aprobado or not hay_rechazo) else ''
                    insp = InspeccionLaboratorio.objects.create(
                        material=m, numero_informe=numero, aprobado=aprobado, pruebas_aplicadas=aplica,
                        observaciones_tecnico=obs, comentarios_adicionales=comentarios,
                        fallas_detectadas=fallas, tecnico_revisor=getattr(request.user, 'codigocotel', '') or '',
                        tiempo_inspeccion_minutos=minutos, usuario_responsable=request.user,
                        **resultados,
                    )
                    m.estado_onu = nuevo_estado
                    m.fecha_retorno_laboratorio = ahora
                    m.observaciones_laboratorio = {
                        'ultima_inspeccion': insp.id,
                        'numero_informe': numero,
                        'aprobado': aprobado,
                        'fallas_detectadas': fallas,
                        'observaciones': obs,
                    }
                    m.save(update_fields=['estado_onu', 'fecha_retorno_laboratorio', 'observaciones_laboratorio', 'updated_at'])
                    HistorialMaterial.objects.create(
                        material=m,
                        estado_anterior='EN_LABORATORIO',
                        estado_nuevo=nuevo_estado.codigo,
                        almacen_anterior=m.almacen_actual,
                        almacen_nuevo=m.almacen_actual,
                        motivo=f'Inspección {"aprobada" if aprobado else "rechazada"}: {numero}'[:100],
                        observaciones=obs or comentarios,
                        usuario_responsable=request.user,
                    )
        except IntegrityError:
            return Response({'error': 'Otro usuario registró un informe con el mismo número. Intenta de nuevo.'},
                            status=status.HTTP_409_CONFLICT)

        n = len(en_lab)
        rechazados = n - aprobados
        partes = []
        if aprobados:
            partes.append(f'{aprobados} aprobado(s)')
        if rechazados:
            partes.append(f'{rechazados} rechazado(s) como defectuoso(s)')
        return Response({
            'success': True,
            'message': f'{" y ".join(partes).capitalize()}. Informe {numeros[0]}{" …" if n > 1 else ""}',
            'aprobado': rechazados == 0,
            'aprobados': aprobados,
            'rechazados': rechazados,
            'procesados': n,
            'informes': numeros,
        }, status=status.HTTP_201_CREATED)
