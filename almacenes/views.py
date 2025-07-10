# ======================================================
# apps/almacenes/views.py
# ======================================================
from datetime import timezone

from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Count, Q
from .models import (
    Marca, TipoEquipo, Componente, EstadoEquipo, Modelo,
    Lote, LoteDetalle, EquipoONU, EquipoServicio, ModeloComponente
)
from .serializers import (
    MarcaSerializer, TipoEquipoSerializer, ComponenteSerializer,
    EstadoEquipoSerializer, ModeloSerializer, LoteSerializer,
    LoteCreateSerializer, LoteDetalleSerializer, EquipoONUSerializer,
    EquipoONUListSerializer, EquipoServicioSerializer, ModeloComponenteSerializer
)


class MarcaViewSet(viewsets.ModelViewSet):
    queryset = Marca.objects.all()
    serializer_class = MarcaSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['nombre', 'descripcion']
    ordering_fields = ['nombre', 'created_at']
    ordering = ['nombre']

    @action(detail=True, methods=['get'])
    def modelos(self, request, pk=None):
        """Obtiene todos los modelos de una marca"""
        marca = self.get_object()
        modelos = marca.modelo_set.all()
        serializer = ModeloSerializer(modelos, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def estadisticas(self, request):
        """Estadísticas de marcas"""
        marcas_stats = Marca.objects.annotate(
            total_modelos=Count('modelo'),
            total_equipos=Count('modelo__equipoonu')
        ).order_by('-total_equipos')

        data = []
        for marca in marcas_stats:
            data.append({
                'id': marca.id,
                'nombre': marca.nombre,
                'total_modelos': marca.total_modelos,
                'total_equipos': marca.total_equipos
            })

        return Response(data)


class TipoEquipoViewSet(viewsets.ModelViewSet):
    queryset = TipoEquipo.objects.all()
    serializer_class = TipoEquipoSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['nombre', 'descripcion']
    ordering = ['nombre']

    @action(detail=True, methods=['get'])
    def modelos(self, request, pk=None):
        """Modelos de este tipo de equipo"""
        tipo_equipo = self.get_object()
        modelos = tipo_equipo.modelo_set.all()
        serializer = ModeloSerializer(modelos, many=True)
        return Response(serializer.data)


class ComponenteViewSet(viewsets.ModelViewSet):
    queryset = Componente.objects.all()
    serializer_class = ComponenteSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['nombre', 'descripcion']
    ordering = ['nombre']


class EstadoEquipoViewSet(viewsets.ModelViewSet):
    queryset = EstadoEquipo.objects.all()
    serializer_class = EstadoEquipoSerializer
    filter_backends = [filters.OrderingFilter]
    ordering = ['nombre']

    @action(detail=False, methods=['get'])
    def distribucion(self, request):
        """Distribución de equipos por estado"""
        distribucion = EstadoEquipo.objects.annotate(
            cantidad_equipos=Count('equipoonu')
        ).values('id', 'nombre', 'cantidad_equipos')

        return Response(list(distribucion))


class ModeloViewSet(viewsets.ModelViewSet):
    queryset = Modelo.objects.select_related('marca', 'tipo_equipo')
    serializer_class = ModeloSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['nombre', 'marca__nombre', 'codigo_modelo']
    ordering_fields = ['nombre', 'codigo_modelo', 'created_at']
    ordering = ['marca__nombre', 'nombre']
    filterset_fields = ['marca', 'tipo_equipo']

    @action(detail=True, methods=['get'])
    def equipos(self, request, pk=None):
        """Equipos de este modelo"""
        modelo = self.get_object()
        equipos = modelo.equipoonu_set.all()

        # Filtros opcionales
        estado = request.query_params.get('estado')
        if estado:
            equipos = equipos.filter(estado__nombre__icontains=estado)

        serializer = EquipoONUListSerializer(equipos, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def disponibles(self, request, pk=None):
        """Equipos disponibles de este modelo"""
        modelo = self.get_object()
        equipos = modelo.equipoonu_set.filter(
            estado__nombre__icontains='DISPONIBLE'
        )
        serializer = EquipoONUListSerializer(equipos, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def agregar_componente(self, request, pk=None):
        """Agregar componente a un modelo"""
        modelo = self.get_object()
        componente_id = request.data.get('componente_id')
        cantidad = request.data.get('cantidad', 1)

        try:
            componente = Componente.objects.get(id=componente_id)
            modelo_componente, created = ModeloComponente.objects.get_or_create(
                modelo=modelo,
                componente=componente,
                defaults={'cantidad': cantidad}
            )

            if not created:
                modelo_componente.cantidad = cantidad
                modelo_componente.save()

            serializer = ModeloComponenteSerializer(modelo_componente)
            return Response(serializer.data)

        except Componente.DoesNotExist:
            return Response(
                {'error': 'Componente no encontrado'},
                status=status.HTTP_400_BAD_REQUEST
            )

    @action(detail=True, methods=['delete'])
    def remover_componente(self, request, pk=None):
        """Remover componente específico de un modelo"""
        modelo = self.get_object()
        componente_id = request.data.get('componente_id')

        try:
            modelo_componente = ModeloComponente.objects.get(
                modelo=modelo,
                componente_id=componente_id
            )
            modelo_componente.delete()

            # Devolver modelo actualizado
            serializer = self.get_serializer(modelo)
            return Response(serializer.data)

        except ModeloComponente.DoesNotExist:
            return Response(
                {'error': 'Componente no encontrado en este modelo'},
                status=status.HTTP_404_NOT_FOUND
            )

    @action(detail=True, methods=['patch'])
    def actualizar_componente(self, request, pk=None):
        """Actualizar cantidad de un componente específico"""
        modelo = self.get_object()
        componente_id = request.data.get('componente_id')
        nueva_cantidad = request.data.get('cantidad')

        try:
            modelo_componente = ModeloComponente.objects.get(
                modelo=modelo,
                componente_id=componente_id
            )
            modelo_componente.cantidad = nueva_cantidad
            modelo_componente.save()

            serializer = ModeloComponenteSerializer(modelo_componente)
            return Response(serializer.data)

        except ModeloComponente.DoesNotExist:
            return Response(
                {'error': 'Componente no encontrado en este modelo'},
                status=status.HTTP_404_NOT_FOUND
            )


class LoteViewSet(viewsets.ModelViewSet):
    queryset = Lote.objects.select_related('tipo_servicio')
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['numero_lote', 'proveedor']
    ordering_fields = ['numero_lote', 'fecha_ingreso', 'proveedor']
    ordering = ['-fecha_ingreso']
    filterset_fields = ['tipo_servicio', 'proveedor']

    def get_serializer_class(self):
        # CORREGIDO: Usar LoteCreateSerializer para crear Y actualizar
        if self.action in ['create', 'update', 'partial_update']:
            return LoteCreateSerializer
        return LoteSerializer

    # El resto de tus métodos se mantienen igual...
    @action(detail=True, methods=['post'])
    def agregar_detalle(self, request, pk=None):
        """Agregar detalle a un lote existente"""
        lote = self.get_object()
        serializer = LoteDetalleSerializer(data=request.data)

        if serializer.is_valid():
            serializer.save(lote=lote)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['get'])
    def resumen(self, request, pk=None):
        """Resumen estadístico del lote"""
        lote = self.get_object()
        equipos_registrados = lote.equipoonu_set.count()
        cantidad_total = lote.cantidad_total

        detalles_info = []
        for detalle in lote.detalles.all():
            equipos_del_modelo = detalle.modelo.equipoonu_set.filter(lote=lote).count()
            detalles_info.append({
                'modelo': f"{detalle.modelo.marca.nombre} {detalle.modelo.nombre}",
                'codigo_modelo': detalle.modelo.codigo_modelo,
                'cantidad_lote': detalle.cantidad,
                'equipos_registrados': equipos_del_modelo,
                'pendientes': max(0, detalle.cantidad - equipos_del_modelo)
            })

        return Response({
            'numero_lote': lote.numero_lote,
            'proveedor': lote.proveedor,
            'tipo_servicio': lote.tipo_servicio.nombre,
            'fecha_ingreso': lote.fecha_ingreso,
            'cantidad_total': cantidad_total,
            'equipos_registrados': equipos_registrados,
            'equipos_pendientes': max(0, cantidad_total - equipos_registrados),
            'porcentaje_registro': round(
                (equipos_registrados / cantidad_total * 100) if cantidad_total > 0 else 0, 2
            ),
            'detalles_por_modelo': detalles_info
        })

    @action(detail=False, methods=['get'])
    def estadisticas(self, request):
        """Estadísticas generales de lotes"""
        total_lotes = self.queryset.count()
        lotes_por_servicio = self.queryset.values(
            'tipo_servicio__nombre'
        ).annotate(
            cantidad=Count('id')
        ).order_by('-cantidad')

        return Response({
            'total_lotes': total_lotes,
            'por_tipo_servicio': list(lotes_por_servicio)
        })


class EquipoONUViewSet(viewsets.ModelViewSet):
    queryset = EquipoONU.objects.select_related(
        'modelo__marca', 'tipo_equipo', 'estado', 'lote'
    )
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['codigo_interno', 'mac_address', 'gpon_serial', 'serial_manufacturer']
    ordering_fields = ['codigo_interno', 'fecha_ingreso']
    ordering = ['-fecha_ingreso']

    # *** CORREGIR LOS FILTROS PARA INCLUIR MARCA ***
    filterset_fields = [
        'modelo',
        'modelo__marca',  # *** AGREGAR ESTO PARA FILTRAR POR MARCA ***
        'tipo_equipo',
        'estado',
        'lote'
    ]

    def get_serializer_class(self):
        if self.action == 'list':
            return EquipoONUListSerializer
        return EquipoONUSerializer

    # *** OPCIONAL: OVERRIDE PARA FILTROS PERSONALIZADOS ***
    def get_queryset(self):
        queryset = super().get_queryset()

        # Filtro personalizado por marca (si necesitas más control)
        marca_id = self.request.query_params.get('marca', None)
        if marca_id:
            queryset = queryset.filter(modelo__marca_id=marca_id)

        return queryset

    def perform_create(self, serializer):
        # Generar código interno si no se proporciona
        if not serializer.validated_data.get('codigo_interno'):
            import uuid
            while True:
                codigo = f"EQ-{str(uuid.uuid4().int)[:6]}"
                if not EquipoONU.objects.filter(codigo_interno=codigo).exists():
                    serializer.validated_data['codigo_interno'] = codigo
                    break
        serializer.save()

    @action(detail=False, methods=['get'])
    def disponibles(self, request):
        """Equipos disponibles para asignación"""
        equipos = self.queryset.filter(
            estado__nombre__icontains='DISPONIBLE'
        )

        # Filtros opcionales
        modelo_id = request.query_params.get('modelo_id')
        tipo_servicio_id = request.query_params.get('tipo_servicio_id')
        marca_id = request.query_params.get('marca_id')  # *** AGREGAR FILTRO DE MARCA ***

        if modelo_id:
            equipos = equipos.filter(modelo_id=modelo_id)

        if tipo_servicio_id:
            equipos = equipos.filter(lote__tipo_servicio_id=tipo_servicio_id)

        if marca_id:  # *** NUEVO FILTRO ***
            equipos = equipos.filter(modelo__marca_id=marca_id)

        serializer = EquipoONUListSerializer(equipos, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def cambiar_estado(self, request, pk=None):
        """Cambiar estado del equipo"""
        equipo = self.get_object()
        estado_id = request.data.get('estado_id')
        observaciones = request.data.get('observaciones', '')

        try:
            estado = EstadoEquipo.objects.get(id=estado_id)
            equipo.estado = estado

            if observaciones:
                timestamp = timezone.now().strftime('%Y-%m-%d %H:%M')
                nueva_obs = f"[{timestamp}] {observaciones}"
                if equipo.observaciones:
                    equipo.observaciones = f"{equipo.observaciones}\n{nueva_obs}"
                else:
                    equipo.observaciones = nueva_obs

            equipo.save()

            serializer = self.get_serializer(equipo)
            return Response(serializer.data)

        except EstadoEquipo.DoesNotExist:
            return Response(
                {'error': 'Estado no encontrado'},
                status=status.HTTP_400_BAD_REQUEST
            )

    @action(detail=False, methods=['get'])
    def estadisticas(self, request):
        """Estadísticas generales de equipos"""
        total_equipos = self.queryset.count()

        # Por estado
        por_estado = self.queryset.values(
            'estado__nombre'
        ).annotate(
            cantidad=Count('id')
        ).order_by('-cantidad')

        # Por modelo (top 10)
        por_modelo = self.queryset.values(
            'modelo__marca__nombre', 'modelo__nombre'
        ).annotate(
            cantidad=Count('id')
        ).order_by('-cantidad')[:10]

        # Por lote
        por_lote = self.queryset.values(
            'lote__numero_lote'
        ).annotate(
            cantidad=Count('id')
        ).order_by('-cantidad')[:10]

        return Response({
            'total_equipos': total_equipos,
            'por_estado': list(por_estado),
            'top_modelos': list(por_modelo),
            'top_lotes': list(por_lote)
        })

    @action(detail=True, methods=['get'])
    def historial(self, request, pk=None):
        """Historial de asignaciones del equipo"""
        equipo = self.get_object()
        asignaciones = equipo.equiposervicio_set.all().order_by('-fecha_asignacion')
        serializer = EquipoServicioSerializer(asignaciones, many=True)
        return Response(serializer.data)