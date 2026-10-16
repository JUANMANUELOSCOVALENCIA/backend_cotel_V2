# ======================================================
# operaciones/views.py
# Zonas de cobertura, planes, solicitudes y órdenes de trabajo.
# ======================================================
from datetime import date

from django.db import transaction
from django.db.models import Case, Count, IntegerField, Max, Prefetch, Q, Sum, Value, When
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from almacenes.models import Almacen
from almacenes.pagination import CustomPageNumberPagination
from contratos.models import Cliente, Contrato, PlanComercial
from usuarios.auditoria import AuditoriaMixin
from usuarios.permissions import PermisoPorRol

from usuarios.models import Usuario

from . import despacho, deuda, plazos, programacion
from .management.commands.cargar_clientes import MARCA as MARCA_PRUEBA
from .models import (Cuadrilla, Despacho, DespachoEquipo, DespachoMaterial, IntegranteCuadrilla, KitMaterial, OrdenTrabajo, PlanAdicional,
                     Solicitud, Vehiculo, ZonaCobertura)
from .programacion import ErrorProgramacion
from .serializers import (
    ClienteEditarSerializer, ClienteMiniSerializer, CuadrillaSerializer, DespachoSerializer, IntegranteSerializer, KitMaterialSerializer,
    OrdenDetailSerializer,
    PlanAdicionalSerializer, OrdenListSerializer, PlanSerializer,
    SolicitudCreateSerializer, SolicitudDetailSerializer, SolicitudEditarSerializer,
    SolicitudListSerializer, TecnicoSerializer, VehiculoSerializer, ZonaCoberturaSerializer, crear_orden,
)


def _lista(valor):
    return [v for v in (valor or '').split(',') if v]


def _texto(request, campo, minimo=5):
    texto = str(request.data.get(campo) or '').strip()
    return texto if len(texto) >= minimo else None


def _fecha(valor):
    """'2026-10-14' → date (None si no es válida)."""
    try:
        return date.fromisoformat(str(valor or '').strip())
    except ValueError:
        return None


def _error(e):
    return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


# ---------------- Zonas de cobertura ----------------

class ZonaCoberturaViewSet(AuditoriaMixin, viewsets.ModelViewSet):
    """
    CRUD de zonas. Quien registra solicitudes también puede LEER las zonas
    (las necesita para ver el mapa de cobertura).
    GET /zonas/verificar/?lat=&lng=  → zona que cubre el punto (o null)
    """
    serializer_class = ZonaCoberturaSerializer
    permission_classes = [PermisoPorRol]
    recurso_permiso = 'cobertura'
    auditoria_modelo = ZonaCobertura
    lectura_alternativa = [('solicitudes', 'leer'), ('solicitudes', 'crear'), ('ordenes', 'leer'), ('cuadrillas', 'leer')]
    acciones_permiso = {'verificar': 'leer'}
    pagination_class = None

    def get_queryset(self):
        qs = ZonaCobertura.objects.select_related('almacen').annotate(n_solicitudes=Count('solicitudes'))
        if self.request.query_params.get('activas') == 'true':
            qs = qs.filter(activo=True)
        return qs.order_by('nombre')

    def perform_create(self, serializer):
        serializer.save(creado_por=self.request.user)

    def destroy(self, request, *args, **kwargs):
        zona = self.get_object()
        n = zona.solicitudes.count()
        if n:
            return Response({'error': f'La zona tiene {n} solicitud(es) registradas. Desactívala en lugar de eliminarla.'},
                            status=status.HTTP_400_BAD_REQUEST)
        return super().destroy(request, *args, **kwargs)

    @action(detail=False, methods=['get'])
    def verificar(self, request):
        try:
            lat = float(request.query_params.get('lat'))
            lng = float(request.query_params.get('lng'))
        except (TypeError, ValueError):
            return Response({'error': 'Indica lat y lng.'}, status=status.HTTP_400_BAD_REQUEST)
        zona = ZonaCobertura.zona_de(lat, lng)
        return Response({'zona': {'id': zona.id, 'nombre': zona.nombre, 'color': zona.color} if zona else None})


# ---------------- Planes ----------------

class PlanViewSet(AuditoriaMixin, viewsets.ModelViewSet):
    serializer_class = PlanSerializer
    permission_classes = [PermisoPorRol]
    recurso_permiso = 'planes'
    lectura_alternativa = [('solicitudes', 'leer'), ('solicitudes', 'crear')]
    auditoria_modelo = PlanComercial
    pagination_class = None

    def get_queryset(self):
        # TEL-FIJA es el servicio de los datos de deuda cargados: no es un plan que se ofrezca
        qs = PlanComercial.objects.exclude(codigo_plan='TEL-FIJA').annotate(n_solicitudes=Count('solicitudes'))
        if self.request.query_params.get('activos') == 'true':
            qs = qs.filter(activo=True)
        return qs.order_by('velocidad_descarga', 'precio_mensual', 'nombre')

    def destroy(self, request, *args, **kwargs):
        plan = self.get_object()
        if plan.solicitudes.exists() or plan.servicio_set.exists():
            return Response({'error': 'El plan ya se usó en solicitudes o servicios. Desactívalo en lugar de eliminarlo.'},
                            status=status.HTTP_400_BAD_REQUEST)
        return super().destroy(request, *args, **kwargs)


class PlanAdicionalViewSet(AuditoriaMixin, viewsets.ModelViewSet):
    """TV cable y telefonía: precio base con unidades incluidas + precio por unidad extra."""
    serializer_class = PlanAdicionalSerializer
    permission_classes = [PermisoPorRol]
    recurso_permiso = 'planes'
    lectura_alternativa = [('solicitudes', 'leer'), ('solicitudes', 'crear')]
    auditoria_modelo = PlanAdicional
    pagination_class = None

    def get_queryset(self):
        qs = PlanAdicional.objects.annotate(n_solicitudes=Count('solicitudes_tv') + Count('solicitudes_telefonia'))
        if self.request.query_params.get('activos') == 'true':
            qs = qs.filter(activo=True)
        if self.request.query_params.get('tipo'):
            qs = qs.filter(tipo=self.request.query_params['tipo'])
        return qs.order_by('tipo', 'precio_mensual', 'nombre')

    def destroy(self, request, *args, **kwargs):
        ad = self.get_object()
        if ad.solicitudes_tv.exists() or ad.solicitudes_telefonia.exists():
            return Response({'error': 'Ya se usó en solicitudes. Desactívalo en lugar de eliminarlo.'}, status=status.HTTP_400_BAD_REQUEST)
        return super().destroy(request, *args, **kwargs)


# ---------------- Solicitudes ----------------

class SolicitudViewSet(AuditoriaMixin, viewsets.ModelViewSet):
    """
    GET    /solicitudes/?estado=&tipo=&zona=&search=
    POST   /solicitudes/                      registrar (genera la OT si hay cobertura)
    PATCH  /solicitudes/{id}/                 corregir contacto / ubicación (antes de salir a campo)
    POST   /solicitudes/{id}/anular/          { motivo }
    POST   /solicitudes/revisar_cobertura/    las SIN COBERTURA que ahora caen en una zona pasan a OT
    GET    /solicitudes/cliente/?ci=          datos del cliente y sus últimas solicitudes
    GET    /solicitudes/resumen/
    """
    permission_classes = [PermisoPorRol]
    recurso_permiso = 'solicitudes'
    auditoria_modelo = Solicitud
    pagination_class = CustomPageNumberPagination
    http_method_names = ['get', 'post', 'patch']
    acciones_permiso = {'anular': 'actualizar', 'revisar_cobertura': 'actualizar', 'cliente': 'leer', 'resumen': 'leer'}
    auditoria_acciones = {'anular': 'Anular solicitud', 'revisar_cobertura': 'Revisar cobertura'}

    def get_queryset(self):
        qs = Solicitud.objects.select_related(
            'cliente', 'plan', 'plan_tv', 'plan_telefonia', 'zona_cobertura', 'orden', 'creado_por')
        p = self.request.query_params
        if self.action == 'list':
            if p.get('estado'):
                qs = qs.filter(estado__in=_lista(p['estado']))
            if p.get('tipo'):
                qs = qs.filter(tipo__in=_lista(p['tipo']))
            if p.get('zona'):
                qs = qs.filter(zona_cobertura_id=p['zona'])
            q = (p.get('search') or '').strip()
            if q:
                qs = qs.filter(Q(numero__icontains=q) | Q(cliente__ci__icontains=q) | Q(cliente__nombres__icontains=q)
                               | Q(cliente__apellidos__icontains=q) | Q(direccion__icontains=q)
                               | Q(zona_referencia__icontains=q) | Q(orden__numero__icontains=q))
        return qs.order_by('-created_at')

    def get_serializer_class(self):
        if self.action == 'create':
            return SolicitudCreateSerializer
        if self.action == 'partial_update':
            return SolicitudEditarSerializer
        if self.action == 'retrieve':
            return SolicitudDetailSerializer
        return SolicitudListSerializer

    def create(self, request, *args, **kwargs):
        ser = SolicitudCreateSerializer(data=request.data, context={'request': request})
        ser.is_valid(raise_exception=True)
        solicitud = ser.save()
        data = SolicitudDetailSerializer(solicitud).data
        if solicitud.estado == Solicitud.Estado.SIN_COBERTURA:
            data['message'] = f'Solicitud {solicitud.numero} registrada SIN COBERTURA: no se generó OT.'
        else:
            data['message'] = f'Solicitud {solicitud.numero} registrada. Se generó la {solicitud.orden.numero}.'
        return Response(data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        solicitud = self.get_object()
        ser = SolicitudEditarSerializer(solicitud, data=request.data, partial=True, context={'usuario': request.user})
        ser.is_valid(raise_exception=True)
        ser.save()
        solicitud = self.get_queryset().get(pk=solicitud.pk)
        data = SolicitudDetailSerializer(solicitud).data
        nueva = getattr(ser, 'orden_generada', None)
        data['message'] = (f'Solicitud actualizada: ahora tiene cobertura y se generó la {nueva.numero}.'
                           if nueva else 'Solicitud actualizada.')
        return Response(data)

    def update(self, request, *args, **kwargs):
        return Response({'error': 'Usa PATCH.'}, status=status.HTTP_405_METHOD_NOT_ALLOWED)

    @action(detail=True, methods=['post'])
    @transaction.atomic
    def anular(self, request, pk=None):
        solicitud = Solicitud.objects.select_for_update().get(pk=self.get_object().pk)
        motivo = _texto(request, 'motivo')
        if not motivo:
            return Response({'motivo': ['Indica el motivo (mínimo 5 caracteres).']}, status=status.HTTP_400_BAD_REQUEST)
        if solicitud.estado in (Solicitud.Estado.ANULADA, Solicitud.Estado.ATENDIDA):
            return Response({'error': f'La solicitud ya está {solicitud.get_estado_display().lower()}.'}, status=status.HTTP_400_BAD_REQUEST)
        orden = getattr(solicitud, 'orden', None)
        if orden and orden.estado not in OrdenTrabajo.ANULABLES:
            return Response({'error': f'La {orden.numero} está {orden.get_estado_display().lower()}; ya no se puede anular.'},
                            status=status.HTTP_400_BAD_REQUEST)
        if orden:
            orden.cambiar_estado(OrdenTrabajo.Estado.ANULADA, request.user, motivo)
        solicitud.estado = Solicitud.Estado.ANULADA
        solicitud.motivo_anulacion = motivo
        solicitud.save(update_fields=['estado', 'motivo_anulacion', 'updated_at'])
        data = SolicitudDetailSerializer(solicitud).data
        data['message'] = f'Solicitud {solicitud.numero} anulada' + (f' junto con la {orden.numero}.' if orden else '.')
        return Response(data)

    @action(detail=False, methods=['post'])
    @transaction.atomic
    def revisar_cobertura(self, request):
        generadas = []
        for s in Solicitud.objects.select_for_update().filter(estado=Solicitud.Estado.SIN_COBERTURA):
            zona = ZonaCobertura.zona_de(s.latitud, s.longitud)
            if not zona:
                continue
            s.zona_cobertura = zona
            s.estado = Solicitud.Estado.EN_CURSO
            s.save(update_fields=['zona_cobertura', 'estado', 'updated_at'])
            orden = crear_orden(s, request.user)
            generadas.append({'solicitud': s.numero, 'orden': orden.numero, 'zona': zona.nombre})
        quedan = Solicitud.objects.filter(estado=Solicitud.Estado.SIN_COBERTURA).count()
        if generadas:
            msg = f'{len(generadas)} solicitud(es) ya tienen cobertura y pasaron a OT.'
        else:
            msg = 'Ninguna solicitud sin cobertura cae todavía dentro de una zona.'
        return Response({'message': msg, 'generadas': generadas, 'siguen_sin_cobertura': quedan})

    @action(detail=False, methods=['get'])
    def cliente(self, request):
        ci = (request.query_params.get('ci') or '').strip().upper()
        if not ci:
            return Response({'error': 'Indica el CI.'}, status=status.HTTP_400_BAD_REQUEST)
        cliente = Cliente.objects.filter(ci=ci).first()
        estado_deuda = deuda.consultar(ci)
        estado_deuda['tipos_bloqueados'] = list(deuda.tipos_bloqueados())
        if not cliente:
            return Response({'cliente': None, 'solicitudes': [], 'deuda': estado_deuda})
        ultimas = Solicitud.objects.filter(cliente=cliente).select_related(
            'plan', 'plan_tv', 'plan_telefonia', 'zona_cobertura', 'orden', 'creado_por', 'cliente')[:5]
        return Response({'cliente': ClienteMiniSerializer(cliente).data,
                         'solicitudes': SolicitudListSerializer(ultimas, many=True).data,
                         'deuda': estado_deuda})

    @action(detail=False, methods=['get'])
    def resumen(self, request):
        por_estado = dict(Solicitud.objects.values_list('estado').annotate(n=Count('id')))
        return Response({e: por_estado.get(e, 0) for e in Solicitud.Estado.values})


# ---------------- Órdenes de trabajo ----------------

class OrdenTrabajoViewSet(AuditoriaMixin, viewsets.ReadOnlyModelViewSet):
    """
    GET  /ordenes/?estado=&tipo=&zona=&cuadrilla=&fecha=&sin_cuadrilla=true&search=&plazo=vencidas|por_vencer
    GET  /ordenes/resumen/
    POST /ordenes/{id}/anular/            { motivo }
    GET  /ordenes/programacion/?fecha=&almacen=   cuadrillas activas con sus OT del día
    POST /ordenes/{id}/programar/         { cuadrilla, fecha, motivo }   (motivo obligatorio si ya estaba programada)
    POST /ordenes/programar_varias/       { ordenes: [ids], cuadrilla, fecha }
    POST /ordenes/{id}/desasignar/        { motivo }   vuelve a PENDIENTE
    POST /ordenes/{id}/no_ejecutada/      { motivo }   la cuadrilla no pudo hacer el trabajo
    POST /ordenes/ordenar_visitas/        { cuadrilla, fecha, ordenes: [ids en orden] }
    (EN CAMPO y EJECUTADA llegan desde la app del técnico, con las fotos)
    """
    permission_classes = [PermisoPorRol]
    recurso_permiso = 'ordenes'
    auditoria_modelo = OrdenTrabajo
    pagination_class = CustomPageNumberPagination
    acciones_permiso = {'anular': 'actualizar', 'resumen': 'leer', 'programacion': 'leer',
                        'programar': 'actualizar', 'programar_varias': 'actualizar', 'desasignar': 'actualizar',
                        'no_ejecutada': 'actualizar', 'ordenar_visitas': 'actualizar'}
    auditoria_acciones = {'anular': 'Anular OT', 'programar': 'Programar OT', 'programar_varias': 'Programar OT',
                          'desasignar': 'Desasignar OT', 'no_ejecutada': 'OT no ejecutada',
                          'ordenar_visitas': 'Ordenar hoja del día'}

    def get_queryset(self):
        qs = OrdenTrabajo.objects.select_related(
            'solicitud__cliente', 'solicitud__plan', 'solicitud__plan_tv', 'solicitud__plan_telefonia', 'solicitud__zona_cobertura',
            'cuadrilla__vehiculo')
        qs = plazos.con_ejecucion(qs)  # para saber si cumplió el plazo ATT sin consultas extra
        if self.action == 'retrieve':
            qs = qs.prefetch_related('historial__usuario', 'historial__cuadrilla_anterior', 'historial__cuadrilla_nueva')
        p = self.request.query_params
        if self.action == 'list':
            if p.get('estado'):
                qs = qs.filter(estado__in=_lista(p['estado']))
            if p.get('tipo'):
                qs = qs.filter(tipo__in=_lista(p['tipo']))
            if p.get('zona'):
                qs = qs.filter(solicitud__zona_cobertura_id=p['zona'])
            if p.get('cuadrilla'):
                qs = qs.filter(cuadrilla_id=p['cuadrilla'])
            if p.get('sin_cuadrilla') == 'true':
                qs = qs.filter(cuadrilla__isnull=True)
            if _fecha(p.get('fecha')):
                qs = qs.filter(fecha_programada=_fecha(p['fecha']))
            if p.get('plazo') in ('vencidas', 'por_vencer'):
                qs = qs.filter(plazos.filtro(p['plazo']))
            q = (p.get('search') or '').strip()
            if q:
                qs = qs.filter(Q(numero__icontains=q) | Q(solicitud__numero__icontains=q)
                               | Q(solicitud__cliente__ci__icontains=q) | Q(solicitud__cliente__nombres__icontains=q)
                               | Q(solicitud__cliente__apellidos__icontains=q) | Q(solicitud__direccion__icontains=q))
        # Primero las urgentes, después las más antiguas (se atienden en orden de llegada)
        if p.get('estado') and not set(_lista(p['estado'])) - set(OrdenTrabajo.ABIERTAS):
            return qs.order_by(Case(When(prioridad='ALTA', then=Value(0)), default=Value(1), output_field=IntegerField()), 'created_at')
        return qs.order_by('-created_at')

    def get_serializer_class(self):
        return OrdenDetailSerializer if self.action in ('retrieve', 'anular') else OrdenListSerializer

    @action(detail=False, methods=['get'])
    def resumen(self, request):
        por_estado = dict(OrdenTrabajo.objects.values_list('estado').annotate(n=Count('id')))
        datos = {e: por_estado.get(e, 0) for e in OrdenTrabajo.Estado.values}
        datos['urgentes'] = OrdenTrabajo.objects.filter(estado__in=OrdenTrabajo.ABIERTAS, prioridad='ALTA').count()
        return Response(datos)

    @action(detail=True, methods=['post'])
    @transaction.atomic
    def anular(self, request, pk=None):
        orden = OrdenTrabajo.objects.select_for_update().get(pk=self.get_object().pk)
        motivo = _texto(request, 'motivo')
        if not motivo:
            return Response({'motivo': ['Indica el motivo (mínimo 5 caracteres).']}, status=status.HTTP_400_BAD_REQUEST)
        if orden.estado not in OrdenTrabajo.ANULABLES:
            return Response({'error': f'La OT está {orden.get_estado_display().lower()}; ya no se puede anular.'},
                            status=status.HTTP_400_BAD_REQUEST)
        orden.cambiar_estado(OrdenTrabajo.Estado.ANULADA, request.user, motivo)
        s = orden.solicitud
        s.estado = Solicitud.Estado.ANULADA
        s.motivo_anulacion = motivo
        s.save(update_fields=['estado', 'motivo_anulacion', 'updated_at'])
        data = OrdenDetailSerializer(OrdenTrabajo.objects.get(pk=orden.pk)).data
        data['message'] = f'{orden.numero} anulada (y su solicitud {s.numero}).'
        return Response(data)

    # ---- Programación ----

    def _detalle(self, orden, message, avisos=None):
        data = OrdenDetailSerializer(self.get_queryset().get(pk=orden.pk)).data
        data['message'] = message
        data['avisos'] = avisos or []
        return Response(data)

    @staticmethod
    def _cuadrilla(request):
        cuadrilla = Cuadrilla.objects.filter(pk=request.data.get('cuadrilla')).prefetch_related('zonas').first()
        fecha = _fecha(request.data.get('fecha'))
        errores = {}
        if not cuadrilla:
            errores['cuadrilla'] = ['Elige la cuadrilla.']
        if not fecha:
            errores['fecha'] = ['Indica la fecha.']
        return cuadrilla, fecha, errores

    @action(detail=False, methods=['get'])
    def programacion(self, request):
        """Tablero del día: cada cuadrilla activa con su carga, integrantes de esa fecha y sus OT en orden de visita."""
        fecha = _fecha(request.query_params.get('fecha')) or timezone.localdate()
        cuadrillas = (Cuadrilla.objects.filter(activo=True).select_related('almacen', 'vehiculo').prefetch_related('zonas')
                      .order_by('nombre'))
        if request.query_params.get('almacen'):
            cuadrillas = cuadrillas.filter(almacen_id=request.query_params['almacen'])
        cuadrillas = list(cuadrillas)
        ordenes = (self.get_queryset().filter(cuadrilla__in=cuadrillas, fecha_programada=fecha)
                   .exclude(estado=OrdenTrabajo.Estado.ANULADA).order_by('orden_visita', 'id'))
        por_cuadrilla = {}
        for o in ordenes:
            por_cuadrilla.setdefault(o.cuadrilla_id, []).append(o)
        despachos = {d.cuadrilla_id: d for d in Despacho.objects.filter(cuadrilla__in=cuadrillas, fecha=fecha)
                     .exclude(estado=Despacho.Estado.ANULADO)}
        # ONU instalada en cada OT (se asocia al instalarla) y cuántas lleva cada despacho
        equipos = list(DespachoEquipo.objects.filter(despacho__in=despachos.values()).select_related('material'))
        onus = {e.orden_id: e.material.gpon_serial for e in equipos if e.orden_id and e.resultado == DespachoEquipo.Resultado.INSTALADO}
        n_onus = {}
        for e in equipos:
            n_onus[e.despacho_id] = n_onus.get(e.despacho_id, 0) + 1
        integrantes = {}
        for i in (IntegranteCuadrilla.objects.filter(cuadrilla__in=cuadrillas, desde__lte=fecha)
                  .filter(Q(hasta__isnull=True) | Q(hasta__gte=fecha)).select_related('usuario')):
            integrantes.setdefault(i.cuadrilla_id, []).append(i)
        res = []
        for c in cuadrillas:
            lista = por_cuadrilla.get(c.id, [])
            gente = sorted(integrantes.get(c.id, []), key=lambda i: (not i.es_jefe, i.desde))
            res.append({
                'id': c.id, 'nombre': c.nombre, 'capacidad_diaria': c.capacidad_diaria,
                'almacen': {'id': c.almacen_id, 'nombre': c.almacen.nombre},
                'vehiculo': {'placa': c.vehiculo.placa, 'descripcion': c.vehiculo.descripcion} if c.vehiculo_id else None,
                'zonas': [{'id': z.id, 'nombre': z.nombre, 'color': z.color} for z in c.zonas.all()],
                'integrantes': IntegranteSerializer(gente, many=True).data,
                'lista_para_programar': len([i for i in gente if i.hasta is None]) >= Cuadrilla.MIN_INTEGRANTES
                                        and any(i.es_jefe and i.hasta is None for i in gente),
                'carga': len([o for o in lista if o.estado in programacion.OCUPAN]),
                'despacho': ({'id': despachos[c.id].id, 'numero': despachos[c.id].numero, 'onus': n_onus.get(despachos[c.id].id, 0),
                              'estado': {'codigo': despachos[c.id].estado, 'nombre': despachos[c.id].get_estado_display()}}
                             if c.id in despachos else None),
                'ordenes': [{**d, 'onu': onus.get(d['id'])} for d in OrdenListSerializer(lista, many=True).data],
            })
        # Despachos de días anteriores que la cuadrilla todavía no rindió (bloquean su próximo despacho)
        sin_rendir = (Despacho.objects.filter(estado=Despacho.Estado.ENTREGADO, fecha__lt=timezone.localdate())
                      .select_related('cuadrilla').order_by('fecha', 'cuadrilla__nombre'))
        atrasadas = programacion.atrasadas()
        if request.query_params.get('almacen'):
            sin_rendir = sin_rendir.filter(almacen_id=request.query_params['almacen'])
            atrasadas = atrasadas.filter(cuadrilla__almacen_id=request.query_params['almacen'])
        return Response({'fecha': fecha, 'cuadrillas': res,
                         # Plazo ATT de las OT en curso (solo aviso): {'vencidas', 'por_vencer'}
                         'plazos': plazos.resumen(),
                         # Programadas de días pasados sin ejecución registrada: no cambian de estado solas
                         'atrasadas': [{'id': o.id, 'numero': o.numero, 'fecha': o.fecha_programada,
                                        'cuadrilla': o.cuadrilla.nombre if o.cuadrilla_id else ''} for o in atrasadas],
                         'sin_rendir': [{'id': d.id, 'numero': d.numero, 'fecha': d.fecha, 'cuadrilla': d.cuadrilla.nombre,
                                         'cuadrilla_id': d.cuadrilla_id} for d in sin_rendir]})

    @action(detail=True, methods=['post'])
    def programar(self, request, pk=None):
        orden = self.get_object()
        cuadrilla, fecha, errores = self._cuadrilla(request)
        if errores:
            return Response(errores, status=status.HTTP_400_BAD_REQUEST)
        reprograma = orden.estado == OrdenTrabajo.Estado.PROGRAMADA
        try:
            avisos = programacion.programar(orden, cuadrilla, fecha, request.user, request.data.get('motivo'))
        except ErrorProgramacion as e:
            return _error(e)
        verbo = 'reprogramada' if reprograma else 'programada'
        return self._detalle(orden, f'{orden.numero} {verbo} para el {fecha:%d/%m/%Y} con {cuadrilla}.', avisos)

    @action(detail=False, methods=['post'])
    def programar_varias(self, request):
        """Asigna varias OT pendientes a la misma cuadrilla y fecha (todo o nada)."""
        cuadrilla, fecha, errores = self._cuadrilla(request)
        ids = request.data.get('ordenes') or []
        if not isinstance(ids, list) or not ids:
            errores['ordenes'] = ['Selecciona al menos una OT.']
        if errores:
            return Response(errores, status=status.HTTP_400_BAD_REQUEST)
        ordenes = list(OrdenTrabajo.objects.filter(pk__in=ids).order_by(
            Case(When(prioridad='ALTA', then=Value(0)), default=Value(1), output_field=IntegerField()), 'created_at'))
        if len(ordenes) != len(set(ids)):
            return _error('Alguna OT ya no existe. Actualiza la pantalla.')
        ya = [o.numero for o in ordenes if o.estado == OrdenTrabajo.Estado.PROGRAMADA]
        if ya:
            return _error(f'Ya están programadas: {", ".join(ya)}. Reprográmalas una por una indicando el motivo.')
        avisos = []
        try:
            with transaction.atomic():
                for o in ordenes:
                    avisos += programacion.programar(o, cuadrilla, fecha, request.user)
        except ErrorProgramacion as e:
            return _error(e)
        # El aviso de capacidad sale una vez por OT; basta el último
        capacidad = [a for a in avisos if 'capacidad' in a][-1:]
        avisos = [a for a in avisos if 'capacidad' not in a] + capacidad
        return Response({'message': f'{len(ordenes)} OT programada(s) para el {fecha:%d/%m/%Y} con {cuadrilla}.',
                         'avisos': avisos, 'ordenes': [o.numero for o in ordenes]})

    @action(detail=True, methods=['post'])
    def desasignar(self, request, pk=None):
        orden = self.get_object()
        try:
            programacion.desasignar(orden, request.user, request.data.get('motivo'))
        except ErrorProgramacion as e:
            return _error(e)
        return self._detalle(orden, f'{orden.numero} desasignada; volvió a pendientes.')

    @action(detail=True, methods=['post'])
    def no_ejecutada(self, request, pk=None):
        orden = self.get_object()
        try:
            programacion.no_ejecutada(orden, request.user, request.data.get('motivo'))
        except ErrorProgramacion as e:
            return _error(e)
        return self._detalle(orden, f'{orden.numero} quedó como no ejecutada; aparece en pendientes para reprogramarla.')

    @action(detail=False, methods=['post'])
    def ordenar_visitas(self, request):
        cuadrilla, fecha, errores = self._cuadrilla(request)
        if errores:
            return Response(errores, status=status.HTTP_400_BAD_REQUEST)
        try:
            programacion.ordenar_visitas(cuadrilla, fecha, request.data.get('ordenes') or [])
        except ErrorProgramacion as e:
            return _error(e)
        return Response({'message': 'Orden de visita guardado.'})


# ---------------- Vehículos y cuadrillas ----------------

class VehiculoViewSet(AuditoriaMixin, viewsets.ModelViewSet):
    """
    GET    /vehiculos/?activos=true
    POST   /vehiculos/            { placa, descripcion, observaciones, equipamiento: [{ nombre, cantidad, nota }] }
    PATCH  /vehiculos/{id}/       (si viene equipamiento, reemplaza la lista)
    DELETE /vehiculos/{id}/       solo si nunca se asignó a una cuadrilla (si no, se desactiva)
    """
    serializer_class = VehiculoSerializer
    permission_classes = [PermisoPorRol]
    recurso_permiso = 'cuadrillas'
    auditoria_modelo = Vehiculo
    pagination_class = None
    http_method_names = ['get', 'post', 'patch', 'delete']

    def get_queryset(self):
        qs = Vehiculo.objects.prefetch_related('equipamiento', 'cuadrillas')
        if self.request.query_params.get('activos') == 'true':
            qs = qs.filter(activo=True)
        return qs.order_by('-activo', 'placa')

    def destroy(self, request, *args, **kwargs):
        vehiculo = self.get_object()
        if vehiculo.cuadrillas.exists():
            return _error('El vehículo ya se asignó a cuadrillas. Desactívalo en lugar de eliminarlo.')
        return super().destroy(request, *args, **kwargs)


class CuadrillaViewSet(AuditoriaMixin, viewsets.ModelViewSet):
    """
    GET    /cuadrillas/?activas=true&almacen=
    POST   /cuadrillas/                         { nombre, almacen, vehiculo, zonas: [ids], capacidad_diaria, observaciones }
    PATCH  /cuadrillas/{id}/
    DELETE /cuadrillas/{id}/                    solo si nunca tuvo técnicos ni OT (si no, se desactiva)
    GET    /cuadrillas/almacenes/               almacenes activos (para el formulario)
    GET    /cuadrillas/tecnicos/                técnicos habilitados para campo que no están en ninguna cuadrilla
    POST   /cuadrillas/{id}/agregar_tecnico/    { usuario, es_jefe }
    POST   /cuadrillas/{id}/retirar_tecnico/    { usuario }   deja la cuadrilla desde hoy
    POST   /cuadrillas/{id}/marcar_jefe/        { usuario }
    POST   /cuadrillas/{id}/desactivar/ | /activar/
    """
    serializer_class = CuadrillaSerializer
    permission_classes = [PermisoPorRol]
    recurso_permiso = 'cuadrillas'
    # Quien programa OT necesita ver las cuadrillas
    lectura_alternativa = [('ordenes', 'leer')]
    auditoria_modelo = Cuadrilla
    pagination_class = None
    http_method_names = ['get', 'post', 'patch', 'delete']
    acciones_permiso = {'tecnicos': 'leer', 'almacenes': 'leer', 'en_poder': 'leer', 'agregar_tecnico': 'actualizar',
                        'retirar_tecnico': 'actualizar', 'marcar_jefe': 'actualizar'}
    auditoria_acciones = {'agregar_tecnico': 'Agregar técnico a cuadrilla', 'retirar_tecnico': 'Retirar técnico de cuadrilla',
                          'marcar_jefe': 'Cambiar jefe de cuadrilla', 'desactivar': 'Desactivar cuadrilla',
                          'activar': 'Activar cuadrilla'}

    def get_queryset(self):
        abiertas = Q(ordenes__estado__in=(OrdenTrabajo.Estado.PROGRAMADA, OrdenTrabajo.Estado.EN_CAMPO))
        qs = (Cuadrilla.objects.select_related('almacen', 'vehiculo')
              .prefetch_related('zonas', Prefetch('integrantes', queryset=IntegranteCuadrilla.objects.select_related('usuario')))
              .annotate(n_abiertas=Count('ordenes', filter=abiertas, distinct=True)))
        p = self.request.query_params
        if p.get('activas') == 'true':
            qs = qs.filter(activo=True)
        if p.get('almacen'):
            qs = qs.filter(almacen_id=p['almacen'])
        return qs.order_by('-activo', 'nombre')

    def _respuesta(self, cuadrilla, message, code=status.HTTP_200_OK):
        data = CuadrillaSerializer(self.get_queryset().get(pk=cuadrilla.pk)).data
        data['message'] = message
        return Response(data, status=code)

    def create(self, request, *args, **kwargs):
        ser = self.get_serializer(data=request.data)
        ser.is_valid(raise_exception=True)
        cuadrilla = ser.save(creado_por=request.user)
        return self._respuesta(cuadrilla, f'Cuadrilla {cuadrilla} creada. Agrega sus técnicos.', status.HTTP_201_CREATED)

    def destroy(self, request, *args, **kwargs):
        cuadrilla = self.get_object()
        if cuadrilla.ordenes.exists() or cuadrilla.integrantes.exists():
            return _error('La cuadrilla ya tuvo técnicos u OT. Desactívala en lugar de eliminarla.')
        return super().destroy(request, *args, **kwargs)

    def _usuario(self, request):
        return Usuario.objects.filter(pk=request.data.get('usuario')).select_related('rol').first()

    @action(detail=False, methods=['get'])
    def almacenes(self, request):
        """Almacenes activos para elegir el de la cuadrilla (sin pedir permisos de almacenes)."""
        return Response(list(Almacen.objects.filter(activo=True).order_by('nombre').values('id', 'codigo', 'nombre', 'ciudad')))

    @action(detail=False, methods=['get'])
    def tecnicos(self, request):
        return Response(TecnicoSerializer(programacion.tecnicos_disponibles(), many=True).data)

    @action(detail=True, methods=['post'])
    def agregar_tecnico(self, request, pk=None):
        cuadrilla = self.get_object()
        usuario = self._usuario(request)
        if not usuario:
            return Response({'usuario': ['Elige el técnico.']}, status=status.HTTP_400_BAD_REQUEST)
        try:
            programacion.agregar_integrante(cuadrilla, usuario, bool(request.data.get('es_jefe')))
        except ErrorProgramacion as e:
            return _error(e)
        return self._respuesta(cuadrilla, f'{usuario.nombre_completo} se unió a {cuadrilla}.')

    @action(detail=True, methods=['post'])
    def retirar_tecnico(self, request, pk=None):
        cuadrilla = self.get_object()
        usuario = self._usuario(request)
        if not usuario:
            return Response({'usuario': ['Elige el técnico.']}, status=status.HTTP_400_BAD_REQUEST)
        try:
            integrante = programacion.retirar_integrante(cuadrilla, usuario)
        except ErrorProgramacion as e:
            return _error(e)
        msg = f'{usuario.nombre_completo} dejó la cuadrilla {cuadrilla}.'
        if integrante.es_jefe:
            msg += ' Era el jefe: elige otro.'
        return self._respuesta(cuadrilla, msg)

    @action(detail=True, methods=['post'])
    def marcar_jefe(self, request, pk=None):
        cuadrilla = self.get_object()
        usuario = self._usuario(request)
        if not usuario:
            return Response({'usuario': ['Elige el técnico.']}, status=status.HTTP_400_BAD_REQUEST)
        try:
            programacion.marcar_jefe(cuadrilla, usuario)
        except ErrorProgramacion as e:
            return _error(e)
        return self._respuesta(cuadrilla, f'{usuario.nombre_completo} es ahora el jefe de {cuadrilla}.')

    @action(detail=True, methods=['post'])
    def desactivar(self, request, pk=None):
        cuadrilla = self.get_object()
        try:
            programacion.desactivar_cuadrilla(cuadrilla)
        except ErrorProgramacion as e:
            return _error(e)
        return self._respuesta(cuadrilla, f'Cuadrilla {cuadrilla} desactivada; sus técnicos quedaron libres.')

    @action(detail=True, methods=['get'])
    def en_poder(self, request, pk=None):
        """Equipos y material que la cuadrilla tiene a su cargo (despachos sin rendir)."""
        from .serializers import _onu
        equipos, materiales = despacho.en_poder(self.get_object())
        return Response({
            'onus': [{**_onu(e.material), 'despacho': e.despacho.numero, 'fecha': e.despacho.fecha} for e in equipos],
            'materiales': [{'nombre': x.material.modelo.nombre, 'cantidad': float(x.cantidad),
                            'unidad': x.material.modelo.unidad_medida.simbolo if x.material.modelo.unidad_medida_id else '',
                            'despacho': x.despacho.numero} for x in materiales],
        })

    @action(detail=True, methods=['post'])
    def activar(self, request, pk=None):
        cuadrilla = self.get_object()
        if cuadrilla.vehiculo_id and Cuadrilla.objects.filter(vehiculo_id=cuadrilla.vehiculo_id, activo=True).exists():
            return _error('Su vehículo ya está en otra cuadrilla activa. Cámbialo antes de activarla.')
        cuadrilla.activo = True
        cuadrilla.save(update_fields=['activo', 'updated_at'])
        return self._respuesta(cuadrilla, f'Cuadrilla {cuadrilla} activada. Revisa sus técnicos.')


# ---------------- Clientes (ficha: datos, contratos, deuda, solicitudes) ----------------

class ClientesViewSet(AuditoriaMixin, viewsets.GenericViewSet):
    """
    GET   /clientes/?search=&situacion=deuda|bloqueado|al_dia&prueba=true|false
    GET   /clientes/resumen/
    GET   /clientes/{id}/         ficha completa
    PATCH /clientes/{id}/         corregir datos de contacto
    Los clientes y contratos existentes se cargan con `manage.py cargar_clientes` y sirven
    para verificar deuda; los contratos GPON nuevos nacerán de las solicitudes.
    """
    permission_classes = [PermisoPorRol]
    recurso_permiso = 'clientes'
    lectura_alternativa = [('solicitudes', 'leer')]
    acciones_permiso = {'resumen': 'leer'}
    auditoria_modelo = Cliente
    pagination_class = CustomPageNumberPagination
    http_method_names = ['get', 'patch']

    def get_queryset(self):
        return Cliente.objects.all()

    def list(self, request):
        p = request.query_params
        lim = deuda.facturas_bloqueo()
        qs = Cliente.objects.annotate(
            n_contratos=Count('contratos', distinct=True),
            facturas=Sum('contratos__facturas_pendientes'),
            monto=Sum('contratos__monto_deuda'),
            peor=Max('contratos__facturas_pendientes'),
        )
        for palabra in (p.get('search') or '').split()[:4]:
            qs = qs.filter(Q(ci__istartswith=palabra) | Q(nombres__icontains=palabra) | Q(apellidos__icontains=palabra)
                           | Q(telefono__contains=palabra))
        situacion = p.get('situacion')
        if situacion == 'deuda':
            qs = qs.filter(facturas__gt=0)
        elif situacion == 'bloqueado':
            qs = qs.filter(peor__gte=lim)
        elif situacion == 'al_dia':
            qs = qs.filter(Q(facturas=0) | Q(facturas__isnull=True))
        if p.get('prueba') in ('true', 'false'):
            filtro = Q(observaciones__startswith=MARCA_PRUEBA)
            qs = qs.filter(filtro) if p['prueba'] == 'true' else qs.exclude(filtro)
        orden = {'deuda': ('-monto', 'apellidos'), 'bloqueado': ('-monto', 'apellidos')}.get(situacion, ('apellidos', 'nombres'))
        qs = qs.order_by(*orden, 'id')
        pagina = self.paginate_queryset(qs)
        return self.get_paginated_response([{
            'id': c.id, 'ci': c.ci, 'nombre': f'{c.nombres} {c.apellidos}'.strip(), 'telefono': c.telefono,
            'zona': c.zona, 'ciudad': c.ciudad, 'contratos': c.n_contratos,
            'facturas': c.facturas or 0, 'monto': float(c.monto or 0),
            'situacion': 'bloqueado' if (c.peor or 0) >= lim else 'deuda' if (c.facturas or 0) > 0 else 'al_dia',
            'prueba': c.observaciones.startswith(MARCA_PRUEBA),
        } for c in pagina])

    def _ficha(self, c):
        lim = deuda.facturas_bloqueo()
        contratos = c.contratos.prefetch_related('servicios__plan_comercial').order_by('-facturas_pendientes', 'numero_contrato')
        solicitudes = Solicitud.objects.filter(cliente=c).select_related(
            'plan', 'plan_tv', 'plan_telefonia', 'zona_cobertura', 'orden', 'creado_por', 'cliente')[:20]
        return {
            'id': c.id, 'ci': c.ci, 'nombres': c.nombres, 'apellidos': c.apellidos,
            'nombre': f'{c.nombres} {c.apellidos}'.strip(), 'telefono': c.telefono,
            'telefono_alternativo': c.telefono_alternativo, 'email': c.email, 'direccion': c.direccion,
            'zona': c.zona, 'ciudad': c.ciudad, 'estado': c.estado, 'fecha_registro': c.fecha_registro,
            'prueba': c.observaciones.startswith(MARCA_PRUEBA),
            'contratos': [{
                'id': k.id, 'numero': k.numero_contrato,
                'servicios': [s.plan_comercial.nombre for s in k.servicios.all()],
                'facturas': k.facturas_pendientes, 'monto': float(k.monto_deuda), 'bloquea': k.facturas_pendientes >= lim,
            } for k in contratos],
            'solicitudes': SolicitudListSerializer(solicitudes, many=True).data,
            'deuda': deuda.consultar(c.ci),
        }

    def retrieve(self, request, pk=None):
        return Response(self._ficha(self.get_object()))

    def partial_update(self, request, pk=None):
        c = self.get_object()
        ser = ClienteEditarSerializer(c, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        nombre_cambio = any(k in ser.validated_data and ser.validated_data[k] != getattr(c, k) for k in ('nombres', 'apellidos'))
        c = ser.save()
        if nombre_cambio and c.observaciones.startswith(MARCA_PRUEBA):
            # Ya tiene datos reales: la carga de prueba no lo volverá a pisar
            c.observaciones = ''
            c.save(update_fields=['observaciones', 'updated_at'])
        datos = self._ficha(c)
        datos['message'] = 'Datos del cliente actualizados.'
        return Response(datos)

    @action(detail=False, methods=['get'])
    def resumen(self, request):
        lim = deuda.facturas_bloqueo()
        con_deuda = Contrato.objects.filter(facturas_pendientes__gt=0)
        datos = con_deuda.aggregate(corte=Max('deuda_actualizada'), monto=Sum('monto_deuda'))
        return Response({
            'clientes': Cliente.objects.count(),
            'prueba': Cliente.objects.filter(observaciones__startswith=MARCA_PRUEBA).count(),
            'con_deuda': con_deuda.values('cliente_id').distinct().count(),
            'bloqueados': Contrato.objects.filter(facturas_pendientes__gte=lim).values('cliente_id').distinct().count(),
            'monto_total': float(datos['monto'] or 0), 'fecha_corte': datos['corte'],
            'facturas_bloqueo': lim, 'tipos_bloqueados': list(deuda.tipos_bloqueados()),
        })


# ---------------- Despacho y rendición ----------------

class DespachoViewSet(AuditoriaMixin, viewsets.GenericViewSet):
    """
    GET  /despachos/?fecha=&cuadrilla=&estado=
    GET  /despachos/{id}/                         con las OT del día de la cuadrilla (para la rendición)
    GET  /despachos/requerimiento/?cuadrilla=&fecha=
         OT del día con sus servicios, ONU disponibles (con TV/telefonía), material sugerido por los kits
    GET  /despachos/buscar/?cuadrilla=&serie=     ONU escaneada (GPON SN, MAC o código interno) en el almacén de la cuadrilla
    GET  /despachos/disponibles/?cuadrilla=&search=&modelo=&tv=&telefonia=   buscador de ONU disponibles (FIFO, paginado)
    GET  /despachos/sugerir/?cuadrilla=&fecha=&ya=1,2   ONU (FIFO) que cubren las instalaciones del día que faltan
    POST /despachos/                              { cuadrilla, fecha, onus: [ids], materiales: [{ material, cantidad }], observaciones }
    POST /despachos/{id}/rendir/                  { equipos: [{ id, resultado, orden }],
                                                    materiales: [{ id, devuelta, consumos: [{ orden, cantidad }] }],
                                                    recuperados: [{ orden, serial, observacion }], observaciones }
    POST /despachos/{id}/anular/                  { motivo }   todo vuelve al almacén
    """
    permission_classes = [PermisoPorRol]
    recurso_permiso = 'despachos'
    lectura_alternativa = [('ordenes', 'leer')]
    auditoria_modelo = Despacho
    pagination_class = CustomPageNumberPagination
    acciones_permiso = {'requerimiento': 'leer', 'buscar': 'leer', 'disponibles': 'leer', 'sugerir': 'leer',
                        'rendir': 'actualizar', 'anular': 'actualizar'}
    auditoria_acciones = {'rendir': 'Rendición de cuadrilla', 'anular': 'Anular despacho'}

    def get_queryset(self):
        qs = Despacho.objects.select_related('cuadrilla__vehiculo', 'almacen', 'entregado_por', 'rendido_por').prefetch_related(
            Prefetch('equipos', queryset=DespachoEquipo.objects.select_related('orden', 'material__modelo__marca')),
            Prefetch('materiales', queryset=DespachoMaterial.objects.select_related('material__modelo__unidad_medida', 'material__lote')
                     .prefetch_related('consumos__orden')),
            'recuperados__orden')
        p = self.request.query_params
        if _fecha(p.get('fecha')):
            qs = qs.filter(fecha=_fecha(p['fecha']))
        if p.get('cuadrilla'):
            qs = qs.filter(cuadrilla_id=p['cuadrilla'])
        if p.get('estado'):
            qs = qs.filter(estado__in=_lista(p['estado']))
        return qs.order_by('-fecha', 'cuadrilla__nombre')

    def _respuesta(self, d, message, code=status.HTTP_200_OK, avisos=None):
        data = DespachoSerializer(self.get_queryset().get(pk=d.pk), context={'con_ordenes': True}).data
        data['message'] = message
        data['avisos'] = avisos or []
        return Response(data, status=code)

    def list(self, request):
        pagina = self.paginate_queryset(self.get_queryset())
        return self.get_paginated_response(DespachoSerializer(pagina, many=True).data)

    def retrieve(self, request, pk=None):
        return Response(DespachoSerializer(self.get_object(), context={'con_ordenes': True}).data)

    @staticmethod
    def _cuadrilla(request):
        return Cuadrilla.objects.select_related('almacen').filter(pk=request.query_params.get('cuadrilla')).first()

    @action(detail=False, methods=['get'])
    def requerimiento(self, request):
        from .serializers import _granel, _onu, _ot_corta
        cuadrilla = self._cuadrilla(request)
        fecha = _fecha(request.query_params.get('fecha'))
        if not cuadrilla or not fecha:
            return _error('Indica la cuadrilla y la fecha.')
        a = cuadrilla.almacen
        ots, material = despacho.requerimiento(cuadrilla, fecha)
        granel = list(despacho.granel_disponible(a))
        actual = (Despacho.objects.filter(cuadrilla=cuadrilla, fecha=fecha).exclude(estado=Despacho.Estado.ANULADO)
                  .prefetch_related(Prefetch('equipos', queryset=DespachoEquipo.objects.select_related('material__modelo__marca'))).first())
        previo = despacho.pendiente_de_rendir(cuadrilla, excluir_fecha=fecha)
        return Response({
            'almacen': {'id': a.id, 'nombre': a.nombre},
            'ordenes': [{**_ot_corta(o), 'lleva_onu': o.tipo in despacho.TIPOS_CON_ONU,
                         'onu_obligatoria': o.tipo == Solicitud.Tipo.INSTALACION} for o in ots],
            'onus_disponibles': despacho.onus_disponibles(a).count(),
            'modelos': [{'id': m.id, 'nombre': f'{m.marca.nombre} {m.nombre}' if m.marca_id else m.nombre, 'disponibles': n,
                         'tv': m.soporta_tv, 'telefonia': m.soporta_telefonia} for m, n in despacho.modelos_disponibles(a)],
            'material': [{'modelo_id': f['modelo'].id, 'nombre': f['modelo'].nombre,
                          'unidad': f['modelo'].unidad_medida.simbolo if f['modelo'].unidad_medida_id else '',
                          'sugerido': float(f['cantidad'])} for f in material],
            'granel': [_granel(m) for m in granel],
            'despacho': ({'id': actual.id, 'numero': actual.numero, 'estado': actual.estado,
                          'onus': [_onu(e.material) for e in actual.equipos.all()]} if actual else None),
            'pendiente_previo': {'numero': previo.numero, 'fecha': previo.fecha} if previo else None,
        })

    @action(detail=False, methods=['get'])
    def buscar(self, request):
        from .serializers import _onu
        cuadrilla = self._cuadrilla(request)
        serie = (request.query_params.get('serie') or '').strip()
        if not cuadrilla or not serie:
            return _error('Indica la cuadrilla y la serie.')
        m = despacho._buscar_onu(serie)
        if not m:
            return _error(f'No hay ninguna ONU registrada con la serie {serie}.')
        if m.almacen_actual_id != cuadrilla.almacen_id:
            return _error(f'La ONU {m.gpon_serial} está en {m.almacen_actual.nombre}, no en {cuadrilla.almacen.nombre}.')
        if m.traspaso_actual_id or not m.estado_onu_id or m.estado_onu.codigo != 'DISPONIBLE':
            estado = m.estado_onu.nombre if m.estado_onu_id else 'sin estado'
            return _error(f'La ONU {m.gpon_serial} está {estado.lower()}; solo se despachan ONU disponibles.')
        return Response(_onu(m))

    @action(detail=False, methods=['get'])
    def disponibles(self, request):
        from .serializers import _onu
        cuadrilla = self._cuadrilla(request)
        if not cuadrilla:
            return _error('Indica la cuadrilla.')
        p = request.query_params
        qs = despacho.buscar_disponibles(cuadrilla.almacen, p.get('search'), p.get('modelo') or None,
                                         {'tv': p.get('tv') == 'true', 'telefonia': p.get('telefonia') == 'true'})
        pagina = self.paginate_queryset(qs)
        return self.get_paginated_response([{**_onu(m), 'lote': m.lote.numero_lote if m.lote_id else ''} for m in pagina])

    @action(detail=False, methods=['get'])
    def sugerir(self, request):
        from .serializers import _onu
        cuadrilla = self._cuadrilla(request)
        fecha = _fecha(request.query_params.get('fecha'))
        if not cuadrilla or not fecha:
            return _error('Indica la cuadrilla y la fecha.')
        try:
            ya = [int(x) for x in _lista(request.query_params.get('ya') or '')]
        except ValueError:
            return _error('Lista de ONU no válida.')
        onus, sin_stock = despacho.sugerir_onus(cuadrilla, fecha, ya)
        return Response({'onus': [{**_onu(m), 'lote': m.lote.numero_lote if m.lote_id else ''} for m in onus],
                         'sin_stock': sin_stock})

    def create(self, request):
        d = request.data
        cuadrilla = Cuadrilla.objects.select_related('almacen').filter(pk=d.get('cuadrilla')).first()
        fecha = _fecha(d.get('fecha'))
        if not cuadrilla or not fecha:
            return _error('Indica la cuadrilla y la fecha.')
        try:
            onus = [int(x) for x in (d.get('onus') or [])]
            materiales = [(int(x['material']), x['cantidad']) for x in (d.get('materiales') or [])]
        except (TypeError, ValueError, KeyError):
            return _error('Datos de equipos o materiales no válidos.')
        try:
            des, avisos = despacho.despachar(cuadrilla, fecha, onus, materiales, request.user, d.get('observaciones') or '')
        except programacion.ErrorProgramacion as e:
            return _error(e)
        return self._respuesta(des, f'Despacho {des.numero} registrado: {cuadrilla} sale con {des.equipos.count()} ONU.',
                               status.HTTP_201_CREATED, avisos)

    @action(detail=True, methods=['post'])
    def rendir(self, request, pk=None):
        des = self.get_object()
        d = request.data

        def _id(v):
            return int(v) if v not in (None, '') else None
        try:
            equipos = {int(x['id']): (x.get('resultado'), _id(x.get('orden'))) for x in (d.get('equipos') or [])}
            consumos, devoluciones = {}, {}
            for x in (d.get('materiales') or []):
                consumos[int(x['id'])] = {int(c['orden']): c.get('cantidad') for c in (x.get('consumos') or [])}
                devoluciones[int(x['id'])] = x.get('devuelta')
            recuperados = [(_id(x.get('orden')), x.get('serial'), x.get('observacion') or '') for x in (d.get('recuperados') or [])]
        except (TypeError, ValueError, KeyError):
            return _error('Datos de la rendición no válidos.')
        try:
            despacho.rendir(des, equipos, consumos, devoluciones, recuperados, request.user, d.get('observaciones') or '')
        except programacion.ErrorProgramacion as e:
            return _error(e)
        return self._respuesta(des, f'Rendición del despacho {des.numero} registrada.')

    @action(detail=True, methods=['post'])
    def anular(self, request, pk=None):
        des = self.get_object()
        try:
            despacho.anular(des, request.user, request.data.get('motivo'))
        except programacion.ErrorProgramacion as e:
            return _error(e)
        return self._respuesta(des, f'Despacho {des.numero} anulado; todo volvió a {des.almacen.nombre}.')


class KitMaterialViewSet(AuditoriaMixin, viewsets.ModelViewSet):
    """
    Material estándar por tipo de trabajo (sugiere el despacho del día).
    GET/POST /kits/   PATCH/DELETE /kits/{id}/   GET /kits/materiales/  (modelos de material por cantidad)
    """
    serializer_class = KitMaterialSerializer
    permission_classes = [PermisoPorRol]
    recurso_permiso = 'cuadrillas'
    lectura_alternativa = [('despachos', 'leer')]
    auditoria_modelo = KitMaterial
    pagination_class = None
    http_method_names = ['get', 'post', 'patch', 'delete']
    acciones_permiso = {'materiales': 'leer'}

    def get_queryset(self):
        return KitMaterial.objects.select_related('modelo__unidad_medida').order_by('tipo', 'condicion', 'modelo__nombre')

    @action(detail=False, methods=['get'])
    def materiales(self, request):
        from almacenes.models import Modelo
        qs = Modelo.objects.filter(activo=True, tipo_material__es_unico=False).select_related('unidad_medida').order_by('nombre')
        return Response([{'id': m.id, 'nombre': m.nombre, 'unidad': m.unidad_medida.simbolo if m.unidad_medida_id else ''} for m in qs])
