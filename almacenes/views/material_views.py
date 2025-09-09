from django.db.models import Q
from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend
from django_filters import rest_framework as django_filters

from usuarios.permissions import GenericRolePermission
from .. import models
from ..models import Material, TipoMaterial, EstadoMaterialONU, Lote, Almacen, Modelo
from ..serializers import MaterialListSerializer, MaterialDetailSerializer


class MaterialFilter(django_filters.FilterSet):
    """Filtros personalizados para materiales"""

    # Filtros de texto con búsqueda parcial
    codigo_interno = django_filters.CharFilter(lookup_expr='icontains')
    mac_address = django_filters.CharFilter(lookup_expr='icontains')
    gpon_serial = django_filters.CharFilter(lookup_expr='icontains')
    serial_manufacturer = django_filters.CharFilter(lookup_expr='icontains')
    codigo_item_equipo = django_filters.CharFilter(lookup_expr='icontains')

    # Filtros por relaciones
    lote_numero = django_filters.CharFilter(field_name='lote__numero_lote', lookup_expr='icontains')
    almacen_codigo = django_filters.CharFilter(field_name='almacen_actual__codigo', lookup_expr='icontains')
    modelo_nombre = django_filters.CharFilter(field_name='modelo__nombre', lookup_expr='icontains')
    marca_nombre = django_filters.CharFilter(field_name='modelo__marca__nombre', lookup_expr='icontains')

    # Filtros por fechas
    fecha_desde = django_filters.DateFilter(field_name='created_at', lookup_expr='gte')
    fecha_hasta = django_filters.DateFilter(field_name='created_at', lookup_expr='lte')

    # Filtros booleanos
    es_nuevo = django_filters.BooleanFilter()

    def filter_tipo_material(self, queryset, name, value):
        """Filtro personalizado para tipo_material"""
        if value:
            try:
                tipo = TipoMaterial.objects.get(codigo=value, activo=True)
                return queryset.filter(tipo_material=tipo)
            except TipoMaterial.DoesNotExist:
                return queryset.none()
        return queryset

    class Meta:
        model = Material
        fields = {
            'lote': ['exact'],
            'almacen_actual': ['exact'],
            'modelo': ['exact'],
            'estado_onu': ['exact'],
            'tipo_origen': ['exact'],
        }


class MaterialViewSet(viewsets.ModelViewSet):
    """ViewSet para gestión de materiales (ONUs y otros)"""
    queryset = Material.objects.select_related(
        'modelo__marca', 'modelo__tipo_equipo', 'lote', 'almacen_actual',
        'estado_onu', 'estado_general', 'tipo_material', 'tipo_origen'
    ).order_by('-created_at')

    permission_classes = [IsAuthenticated, GenericRolePermission]
    basename = 'materiales'

    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = MaterialFilter

    search_fields = [
        'codigo_interno', 'mac_address', 'gpon_serial', 'serial_manufacturer',
        'codigo_item_equipo', 'lote__numero_lote', 'modelo__nombre'
    ]

    ordering_fields = [
        'created_at', 'codigo_interno', 'mac_address', 'gpon_serial',
        'lote__numero_lote', 'almacen_actual__codigo'
    ]

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return MaterialDetailSerializer
        return MaterialListSerializer

    def get_queryset(self):
        queryset = super().get_queryset()

        # Filtro por tipo de material (solo ONUs por defecto)
        tipo_material = self.request.query_params.get('tipo_material', 'ONU')
        if tipo_material:
            try:
                tipo = TipoMaterial.objects.get(codigo=tipo_material, activo=True)
                queryset = queryset.filter(tipo_material=tipo)
            except TipoMaterial.DoesNotExist:
                pass

        return queryset

    @action(detail=False, methods=['get'])
    def estadisticas(self, request):
        """Estadísticas de materiales"""
        queryset = self.filter_queryset(self.get_queryset())

        # Estadísticas por estado
        estados_stats = {}
        for estado in EstadoMaterialONU.objects.filter(activo=True):
            count = queryset.filter(estado_onu=estado).count()
            estados_stats[estado.nombre] = count

        # Estadísticas por almacén
        almacenes_stats = {}
        for almacen in Almacen.objects.filter(activo=True):
            count = queryset.filter(almacen_actual=almacen).count()
            if count > 0:
                almacenes_stats[almacen.nombre] = count

        # Estadísticas por lote
        lotes_stats = queryset.values(
            'lote__numero_lote'
        ).annotate(
            count=models.Count('id')
        ).order_by('-count')[:10]

        return Response({
            'total': queryset.count(),
            'por_estado': estados_stats,
            'por_almacen': almacenes_stats,
            'top_lotes': list(lotes_stats),
            'nuevos': queryset.filter(es_nuevo=True).count(),
            'reingresados': queryset.filter(es_nuevo=False).count(),
        })

    @action(detail=False, methods=['get'])
    def solo_onus(self, request):
        """Obtener solo equipos ONUs"""
        try:
            tipo_onu = TipoMaterial.objects.get(codigo='ONU', activo=True)
            queryset = self.get_queryset().filter(tipo_material=tipo_onu)

            page = self.paginate_queryset(queryset)
            if page is not None:
                serializer = self.get_serializer(page, many=True)
                return self.get_paginated_response(serializer.data)

            serializer = self.get_serializer(queryset, many=True)
            return Response(serializer.data)
        except TipoMaterial.DoesNotExist:
            return Response([], status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def cambiar_estado(self, request, pk=None):
        """Cambiar estado de un material"""
        material = self.get_object()
        nuevo_estado_id = request.data.get('estado_id')

        if not nuevo_estado_id:
            return Response(
                {'error': 'estado_id es requerido'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            if material.tipo_material.es_unico:
                nuevo_estado = EstadoMaterialONU.objects.get(id=nuevo_estado_id, activo=True)
                material.estado_onu = nuevo_estado
            else:
                from ..models import EstadoMaterialGeneral
                nuevo_estado = EstadoMaterialGeneral.objects.get(id=nuevo_estado_id, activo=True)
                material.estado_general = nuevo_estado

            material.save()

            return Response({
                'message': f'Estado cambiado a {nuevo_estado.nombre}',
                'nuevo_estado': nuevo_estado.nombre
            })

        except (EstadoMaterialONU.DoesNotExist, EstadoMaterialGeneral.DoesNotExist):
            return Response(
                {'error': 'Estado no encontrado'},
                status=status.HTTP_404_NOT_FOUND
            )

    @action(detail=False, methods=['post'])
    def busqueda_avanzada(self, request):
        """Búsqueda avanzada con múltiples criterios"""
        queryset = self.get_queryset()

        # Aplicar filtros del request
        filtros = Q()

        if request.data.get('texto_busqueda'):
            texto = request.data['texto_busqueda']
            filtros |= (
                    Q(codigo_interno__icontains=texto) |
                    Q(mac_address__icontains=texto) |
                    Q(gpon_serial__icontains=texto) |
                    Q(serial_manufacturer__icontains=texto) |
                    Q(lote__numero_lote__icontains=texto)
            )

        if request.data.get('lote_ids'):
            filtros &= Q(lote_id__in=request.data['lote_ids'])

        if request.data.get('almacen_ids'):
            filtros &= Q(almacen_actual_id__in=request.data['almacen_ids'])

        if request.data.get('estado_ids'):
            filtros &= Q(estado_onu_id__in=request.data['estado_ids'])

        queryset = queryset.filter(filtros)

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)