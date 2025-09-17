from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend
from django_filters import rest_framework as django_filters
from rest_framework.views import APIView

from usuarios.permissions import GenericRolePermission
from .. import models
from ..models import Material, TipoMaterial, EstadoMaterialONU, Lote, Almacen, Modelo, InspeccionLaboratorio, \
    HistorialMaterial, TipoIngreso
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
        'modelo__marca', 'modelo__tipo_material', 'modelo__unidad_medida', 'lote', 'almacen_actual',
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


# En almacenes/views/material_views.py

class ReingresoMaterialView(APIView):
    """View para manejar reingresos de materiales de reposición"""
    permission_classes = [IsAuthenticated, GenericRolePermission]

    def post(self, request):
        """Registrar reingreso de material de reposición (desde devolución)"""
        try:
            material_original_id = request.data.get('material_original_id')

            if not material_original_id:
                return Response({
                    'success': False,
                    'error': 'ID del material original requerido'
                }, status=status.HTTP_400_BAD_REQUEST)

            # Obtener material original
            try:
                material_original = Material.objects.get(id=material_original_id)
            except Material.DoesNotExist:
                return Response({
                    'success': False,
                    'error': 'Material original no encontrado'
                }, status=status.HTTP_404_NOT_FOUND)

            # Validar que el material esté devuelto al proveedor
            try:
                estado_devuelto = EstadoMaterialONU.objects.get(codigo='DEVUELTO_PROVEEDOR', activo=True)
                if material_original.estado_onu != estado_devuelto:
                    return Response({
                        'success': False,
                        'error': 'El material original debe estar devuelto al proveedor'
                    }, status=status.HTTP_400_BAD_REQUEST)
            except EstadoMaterialONU.DoesNotExist:
                return Response({
                    'success': False,
                    'error': 'Estado DEVUELTO_PROVEEDOR no configurado'
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            # Validar unicidad de MAC y GPON
            mac_address = request.data.get('mac_address', '').upper()
            gpon_serial = request.data.get('gpon_serial', '')

            if not mac_address or not gpon_serial:
                return Response({
                    'success': False,
                    'error': 'MAC Address y GPON Serial son obligatorios'
                }, status=status.HTTP_400_BAD_REQUEST)

            if Material.objects.filter(mac_address=mac_address).exists():
                return Response({
                    'success': False,
                    'error': f'MAC Address {mac_address} ya existe en el sistema'
                }, status=status.HTTP_400_BAD_REQUEST)

            if Material.objects.filter(gpon_serial=gpon_serial).exists():
                return Response({
                    'success': False,
                    'error': f'GPON Serial {gpon_serial} ya existe en el sistema'
                }, status=status.HTTP_400_BAD_REQUEST)

            # Obtener estados para el nuevo material
            try:
                estado_disponible = EstadoMaterialONU.objects.get(codigo='DISPONIBLE', activo=True)
                tipo_reingreso = TipoIngreso.objects.get(codigo='REINGRESO', activo=True)
            except (EstadoMaterialONU.DoesNotExist, TipoIngreso.DoesNotExist):
                return Response({
                    'success': False,
                    'error': 'Estados o tipos no configurados correctamente'
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            with transaction.atomic():
                # Crear nuevo material de reposición
                nuevo_material = Material.objects.create(
                    # Heredar datos del material original
                    lote=material_original.lote,
                    modelo=material_original.modelo,
                    almacen_actual=material_original.almacen_actual,
                    tipo_material=material_original.tipo_material,

                    # Nuevos datos del equipo de reposición
                    mac_address=mac_address,
                    gpon_serial=gpon_serial,
                    serial_manufacturer=request.data.get('serial_manufacturer', ''),
                    codigo_item_equipo=request.data.get('codigo_item_equipo', ''),

                    # Estados y control
                    estado_onu=estado_disponible,
                    es_nuevo=False,  # Es reingreso
                    tipo_origen=tipo_reingreso,
                    cantidad=1.00,

                    # Referencias y metadatos
                    equipo_original=material_original,
                    motivo_reingreso=request.data.get('motivo_reingreso', 'Reposición por equipo defectuoso'),
                    numero_entrega_parcial=material_original.numero_entrega_parcial,
                    observaciones=f"Reposición de {material_original.codigo_interno} - MAC: {mac_address}"
                )

                # Actualizar el material original con referencia al reemplazo
                material_original.material_reemplazo = nuevo_material
                material_original.observaciones += f"\n[REEMPLAZADO] Por: {nuevo_material.codigo_interno} - {timezone.now().strftime('%Y-%m-%d %H:%M')}"
                material_original.save()

                # Crear entrada en historial para el nuevo material
                HistorialMaterial.objects.create(
                    material=nuevo_material,
                    estado_anterior='N/A',
                    estado_nuevo='DISPONIBLE',
                    almacen_anterior=None,
                    almacen_nuevo=nuevo_material.almacen_actual,
                    motivo=f'Reingreso por reposición de material defectuoso: {material_original.codigo_interno}',
                    observaciones=request.data.get('motivo_reingreso', ''),
                    usuario_responsable=request.user
                )

                # Crear entrada en historial para el material original
                HistorialMaterial.objects.create(
                    material=material_original,
                    estado_anterior='DEVUELTO_PROVEEDOR',
                    estado_nuevo='REEMPLAZADO',
                    almacen_anterior=material_original.almacen_actual,
                    almacen_nuevo=material_original.almacen_actual,
                    motivo=f'Material reemplazado por: {nuevo_material.codigo_interno}',
                    observaciones=f'Reposición registrada - Nuevo MAC: {mac_address}',
                    usuario_responsable=request.user
                )

            return Response({
                'success': True,
                'message': 'Reingreso registrado correctamente',
                'nuevo_material': {
                    'id': nuevo_material.id,
                    'codigo_interno': nuevo_material.codigo_interno,
                    'mac_address': nuevo_material.mac_address,
                    'gpon_serial': nuevo_material.gpon_serial,
                    'lote': nuevo_material.lote.numero_lote if nuevo_material.lote else None
                },
                'material_original': {
                    'id': material_original.id,
                    'codigo_interno': material_original.codigo_interno,
                    'estado': 'REEMPLAZADO'
                }
            })

        except Exception as e:
            return Response({
                'success': False,
                'error': f'Error interno: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)