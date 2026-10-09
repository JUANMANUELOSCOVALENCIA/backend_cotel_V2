# ======================================================
# operaciones/views.py
# Zonas de cobertura, planes, solicitudes y órdenes de trabajo.
# ======================================================
from django.db import transaction
from django.db.models import Case, Count, IntegerField, Max, Q, Sum, Value, When
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from almacenes.pagination import CustomPageNumberPagination
from contratos.models import Cliente, Contrato, PlanComercial
from usuarios.auditoria import AuditoriaMixin
from usuarios.permissions import PermisoPorRol

from . import deuda
from .management.commands.cargar_clientes import MARCA as MARCA_PRUEBA
from .models import OrdenTrabajo, PlanAdicional, Solicitud, ZonaCobertura
from .serializers import (
    ClienteEditarSerializer, ClienteMiniSerializer, OrdenDetailSerializer, PlanAdicionalSerializer, OrdenListSerializer, PlanSerializer,
    SolicitudCreateSerializer, SolicitudDetailSerializer, SolicitudEditarSerializer,
    SolicitudListSerializer, ZonaCoberturaSerializer, crear_orden,
)


def _lista(valor):
    return [v for v in (valor or '').split(',') if v]


def _texto(request, campo, minimo=5):
    texto = str(request.data.get(campo) or '').strip()
    return texto if len(texto) >= minimo else None


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
    lectura_alternativa = [('solicitudes', 'leer'), ('solicitudes', 'crear'), ('ordenes', 'leer')]
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
    GET  /ordenes/?estado=&tipo=&zona=&search=
    GET  /ordenes/resumen/
    POST /ordenes/{id}/anular/   { motivo }
    (programar / ejecutar / verificar llegan con cuadrillas y la PWA)
    """
    permission_classes = [PermisoPorRol]
    recurso_permiso = 'ordenes'
    auditoria_modelo = OrdenTrabajo
    pagination_class = CustomPageNumberPagination
    acciones_permiso = {'anular': 'actualizar', 'resumen': 'leer'}
    auditoria_acciones = {'anular': 'Anular OT'}

    def get_queryset(self):
        qs = OrdenTrabajo.objects.select_related(
            'solicitud__cliente', 'solicitud__plan', 'solicitud__plan_tv', 'solicitud__plan_telefonia', 'solicitud__zona_cobertura')
        if self.action == 'retrieve':
            qs = qs.prefetch_related('historial__usuario')
        p = self.request.query_params
        if self.action == 'list':
            if p.get('estado'):
                qs = qs.filter(estado__in=_lista(p['estado']))
            if p.get('tipo'):
                qs = qs.filter(tipo__in=_lista(p['tipo']))
            if p.get('zona'):
                qs = qs.filter(solicitud__zona_cobertura_id=p['zona'])
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
