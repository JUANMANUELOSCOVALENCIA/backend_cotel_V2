# ======================================================
# apps/contratos/views.py
# ======================================================

from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Count, Q
from datetime import date, datetime, timedelta
from .models import (
    Cliente, TipoTramite, FormaPago, TipoServicio, PlanComercial,
    Contrato, Servicio, OrdenTrabajo
)
from .serializers import (
    ClienteSerializer, TipoTramiteSerializer, FormaPagoSerializer,
    TipoServicioSerializer, PlanComercialSerializer, ContratoSerializer,
    ContratoCreateSerializer, ServicioSerializer, OrdenTrabajoSerializer
)


class TipoServicioViewSet(viewsets.ModelViewSet):
    queryset = TipoServicio.objects.all()
    serializer_class = TipoServicioSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['nombre', 'descripcion']
    ordering = ['nombre']

    @action(detail=True, methods=['get'])
    def planes(self, request, pk=None):
        """Obtiene todos los planes de un tipo de servicio"""
        tipo_servicio = self.get_object()
        planes = tipo_servicio.plancomercial_set.filter(activo=True)
        serializer = PlanComercialSerializer(planes, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def estadisticas(self, request):
        """Estadísticas de tipos de servicio"""
        stats = TipoServicio.objects.annotate(
            total_planes=Count('plancomercial'),
            total_servicios=Count('plancomercial__servicio')
        ).order_by('-total_servicios')

        data = []
        for tipo in stats:
            data.append({
                'id': tipo.id,
                'nombre': tipo.nombre,
                'total_planes': tipo.total_planes,
                'total_servicios': tipo.total_servicios
            })

        return Response(data)


class TipoTramiteViewSet(viewsets.ModelViewSet):
    queryset = TipoTramite.objects.filter(activo=True)
    serializer_class = TipoTramiteSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['nombre', 'descripcion']
    ordering = ['nombre']


class FormaPagoViewSet(viewsets.ModelViewSet):
    queryset = FormaPago.objects.filter(activo=True)
    serializer_class = FormaPagoSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['nombre', 'descripcion']
    ordering = ['nombre']


class ClienteViewSet(viewsets.ModelViewSet):
    queryset = Cliente.objects.all()
    serializer_class = ClienteSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['ci', 'nombres', 'apellidos', 'telefono']
    ordering_fields = ['nombres', 'apellidos', 'fecha_registro']
    ordering = ['-fecha_registro']
    filterset_fields = ['estado', 'zona', 'ciudad']

    @action(detail=True, methods=['get'])
    def contratos(self, request, pk=None):
        """Obtiene todos los contratos de un cliente"""
        cliente = self.get_object()
        contratos = cliente.contratos.all()
        serializer = ContratoSerializer(contratos, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def buscar_por_ci(self, request):
        """Buscar cliente por CI"""
        ci = request.query_params.get('ci')
        if not ci:
            return Response({'error': 'Parámetro CI requerido'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            cliente = Cliente.objects.get(ci=ci)
            serializer = self.get_serializer(cliente)
            return Response(serializer.data)
        except Cliente.DoesNotExist:
            return Response({'error': 'Cliente no encontrado'}, status=status.HTTP_404_NOT_FOUND)

    @action(detail=False, methods=['get'])
    def estadisticas(self, request):
        """Estadísticas de clientes"""
        total_clientes = self.queryset.count()
        por_estado = self.queryset.values('estado').annotate(
            cantidad=Count('id')
        ).order_by('-cantidad')

        por_zona = self.queryset.values('zona').annotate(
            cantidad=Count('id')
        ).order_by('-cantidad')[:10]

        return Response({
            'total_clientes': total_clientes,
            'por_estado': list(por_estado),
            'top_zonas': list(por_zona)
        })


class PlanComercialViewSet(viewsets.ModelViewSet):
    queryset = PlanComercial.objects.select_related('tipo_servicio')
    serializer_class = PlanComercialSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['nombre', 'codigo_plan', 'descripcion']
    ordering_fields = ['nombre', 'precio_mensual', 'created_at']
    ordering = ['tipo_servicio__nombre', 'precio_mensual']
    filterset_fields = ['tipo_servicio', 'activo']

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.action == 'list':
            # Solo planes activos en el listado
            queryset = queryset.filter(activo=True)
        return queryset

    @action(detail=False, methods=['get'])
    def por_tipo_servicio(self, request):
        """Planes agrupados por tipo de servicio"""
        tipo_servicio_id = request.query_params.get('tipo_servicio_id')
        if tipo_servicio_id:
            planes = self.queryset.filter(
                tipo_servicio_id=tipo_servicio_id,
                activo=True
            )
        else:
            planes = self.queryset.filter(activo=True)

        serializer = self.get_serializer(planes, many=True)
        return Response(serializer.data)


class ContratoViewSet(viewsets.ModelViewSet):
    queryset = Contrato.objects.select_related('cliente', 'tipo_tramite', 'forma_pago')
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['numero_contrato', 'cliente__nombres', 'cliente__apellidos', 'cliente__ci']
    ordering_fields = ['numero_contrato', 'fecha_firma']
    ordering = ['-fecha_firma']
    filterset_fields = ['estado_contrato', 'tipo_tramite', 'forma_pago']

    def get_serializer_class(self):
        if self.action == 'create':
            return ContratoCreateSerializer
        return ContratoSerializer

    @action(detail=True, methods=['post'])
    def agregar_servicio(self, request, pk=None):
        """Agregar servicio a un contrato existente"""
        contrato = self.get_object()
        plan_id = request.data.get('plan_comercial_id')

        try:
            plan = PlanComercial.objects.get(id=plan_id, activo=True)

            # Verificar que no exista ya este servicio en el contrato
            if contrato.servicios.filter(plan_comercial=plan).exists():
                return Response(
                    {'error': 'Este servicio ya existe en el contrato'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            servicio = Servicio.objects.create(
                contrato=contrato,
                plan_comercial=plan
            )

            serializer = ServicioSerializer(servicio)
            return Response(serializer.data, status=status.HTTP_201_CREATED)

        except PlanComercial.DoesNotExist:
            return Response(
                {'error': 'Plan comercial no encontrado'},
                status=status.HTTP_400_BAD_REQUEST
            )

    @action(detail=True, methods=['post'])
    def cambiar_estado(self, request, pk=None):
        """Cambiar estado del contrato"""
        contrato = self.get_object()
        nuevo_estado = request.data.get('estado')
        observaciones = request.data.get('observaciones', '')

        estados_validos = ['PENDIENTE', 'ACTIVO', 'SUSPENDIDO', 'CANCELADO']
        if nuevo_estado not in estados_validos:
            return Response(
                {'error': f'Estado inválido. Opciones: {estados_validos}'},
                status=status.HTTP_400_BAD_REQUEST
            )

        contrato.estado_contrato = nuevo_estado
        if observaciones:
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M')
            nueva_obs = f"[{timestamp}] Estado: {nuevo_estado} - {observaciones}"
            if contrato.observaciones:
                contrato.observaciones = f"{contrato.observaciones}\n{nueva_obs}"
            else:
                contrato.observaciones = nueva_obs

        contrato.save()

        serializer = self.get_serializer(contrato)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def estadisticas(self, request):
        """Estadísticas de contratos"""
        total_contratos = self.queryset.count()
        por_estado = self.queryset.values('estado_contrato').annotate(
            cantidad=Count('id')
        ).order_by('-cantidad')

        # Contratos por mes (últimos 12 meses)
        desde = date.today() - timedelta(days=365)
        por_mes = self.queryset.filter(
            fecha_firma__gte=desde
        ).extra(
            select={'mes': "DATE_TRUNC('month', fecha_firma)"}
        ).values('mes').annotate(
            cantidad=Count('id')
        ).order_by('mes')

        return Response({
            'total_contratos': total_contratos,
            'por_estado': list(por_estado),
            'por_mes': list(por_mes)
        })


class ServicioViewSet(viewsets.ModelViewSet):
    queryset = Servicio.objects.select_related('contrato__cliente', 'plan_comercial__tipo_servicio')
    serializer_class = ServicioSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['contrato__numero_contrato', 'contrato__cliente__nombres']
    ordering_fields = ['fecha_activacion']
    ordering = ['-fecha_activacion']

    # CAMBIAR: Eliminar filtros que causan problemas con templates
    # filterset_fields = ['estado_servicio', 'plan_comercial__tipo_servicio']

    def get_queryset(self):
        """Filtrar servicios que tengan plan_comercial válido"""
        queryset = super().get_queryset()
        # Filtrar solo servicios que tienen plan_comercial
        queryset = queryset.filter(plan_comercial__isnull=False)

        # Filtros manuales desde query params
        estado = self.request.query_params.get('estado_servicio')
        if estado:
            queryset = queryset.filter(estado_servicio=estado)

        tipo_servicio = self.request.query_params.get('tipo_servicio')
        if tipo_servicio:
            queryset = queryset.filter(plan_comercial__tipo_servicio_id=tipo_servicio)

        return queryset

    @action(detail=True, methods=['post'])
    def suspender(self, request, pk=None):
        """Suspender servicio"""
        servicio = self.get_object()
        observaciones = request.data.get('observaciones', '')

        servicio.estado_servicio = 'SUSPENDIDO'
        if observaciones:
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M')
            nueva_obs = f"[{timestamp}] Suspendido - {observaciones}"
            if servicio.observaciones:
                servicio.observaciones = f"{servicio.observaciones}\n{nueva_obs}"
            else:
                servicio.observaciones = nueva_obs

        servicio.save()

        serializer = self.get_serializer(servicio)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def reactivar(self, request, pk=None):
        """Reactivar servicio suspendido"""
        servicio = self.get_object()
        observaciones = request.data.get('observaciones', '')

        servicio.estado_servicio = 'ACTIVO'
        servicio.fecha_desactivacion = None
        if observaciones:
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M')
            nueva_obs = f"[{timestamp}] Reactivado - {observaciones}"
            if servicio.observaciones:
                servicio.observaciones = f"{servicio.observaciones}\n{nueva_obs}"
            else:
                servicio.observaciones = nueva_obs

        servicio.save()

        serializer = self.get_serializer(servicio)
        return Response(serializer.data)


class OrdenTrabajoViewSet(viewsets.ModelViewSet):
    queryset = OrdenTrabajo.objects.select_related('contrato__cliente')
    serializer_class = OrdenTrabajoSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['numero_ot', 'contrato__numero_contrato', 'tecnico_asignado']
    ordering_fields = ['fecha_programada', 'fecha_asignacion']
    ordering = ['fecha_programada', 'estado_ot']

    # CAMBIAR: Eliminar filterset_fields problemático
    # filterset_fields = ['estado_ot', 'tipo_trabajo', 'tecnico_asignado']

    def get_queryset(self):
        """Queryset que maneja relaciones faltantes"""
        queryset = OrdenTrabajo.objects.select_related('contrato__cliente')

        # Filtros manuales desde query params
        estado = self.request.query_params.get('estado_ot')
        if estado:
            queryset = queryset.filter(estado_ot=estado)

        tipo_trabajo = self.request.query_params.get('tipo_trabajo')
        if tipo_trabajo:
            queryset = queryset.filter(tipo_trabajo__icontains=tipo_trabajo)

        tecnico = self.request.query_params.get('tecnico_asignado')
        if tecnico:
            queryset = queryset.filter(tecnico_asignado__icontains=tecnico)

        return queryset

    @action(detail=False, methods=['get'])
    def agenda_tecnico(self, request):
        """Agenda de trabajo por técnico"""
        tecnico = request.query_params.get('tecnico')
        fecha = request.query_params.get('fecha')  # YYYY-MM-DD

        queryset = self.get_queryset()

        if tecnico:
            queryset = queryset.filter(tecnico_asignado__icontains=tecnico)

        if fecha:
            try:
                fecha_obj = datetime.strptime(fecha, '%Y-%m-%d').date()
                queryset = queryset.filter(fecha_programada=fecha_obj)
            except ValueError:
                return Response(
                    {'error': 'Formato de fecha inválido. Use YYYY-MM-DD'},
                    status=status.HTTP_400_BAD_REQUEST
                )

        queryset = queryset.filter(
            estado_ot__in=['PENDIENTE', 'ASIGNADA', 'EN_PROCESO']
        )

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def asignar_tecnico(self, request, pk=None):
        """Asignar técnico a una OT"""
        ot = self.get_object()
        tecnico = request.data.get('tecnico_asignado')
        fecha_programada = request.data.get('fecha_programada')

        if not tecnico:
            return Response(
                {'error': 'Técnico requerido'},
                status=status.HTTP_400_BAD_REQUEST
            )

        ot.tecnico_asignado = tecnico
        ot.estado_ot = 'ASIGNADA'
        ot.fecha_asignacion = date.today()

        if fecha_programada:
            try:
                ot.fecha_programada = datetime.strptime(fecha_programada, '%Y-%m-%d').date()
            except ValueError:
                return Response(
                    {'error': 'Formato de fecha inválido. Use YYYY-MM-DD'},
                    status=status.HTTP_400_BAD_REQUEST
                )

        ot.save()

        serializer = self.get_serializer(ot)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def completar(self, request, pk=None):
        """Completar orden de trabajo"""
        ot = self.get_object()
        observaciones = request.data.get('observaciones_tecnico', '')
        materiales = request.data.get('materiales_utilizados', '')

        ot.estado_ot = 'COMPLETADA'
        ot.fecha_ejecucion = date.today()
        ot.observaciones_tecnico = observaciones
        ot.materiales_utilizados = materiales

        ot.save()

        serializer = self.get_serializer(ot)
        return Response(serializer.data)
