# ======================================================
# almacenes/views/lote_views.py
# Views para gestión de lotes y importación masiva
# ======================================================

from django.db import transaction
from django.http import JsonResponse
from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
from django_filters.rest_framework import DjangoFilterBackend

from usuarios.permissions import GenericRolePermission
from ..models import (
    Lote, LoteDetalle, EntregaParcialLote, Material, Almacen,
    TipoIngresoChoices, EstadoLoteChoices, TipoMaterialChoices,
    EstadoMaterialONUChoices
)
from ..serializers import (
    LoteSerializer, LoteCreateSerializer, LoteDetalleSerializer,
    EntregaParcialLoteSerializer, ImportacionMasivaSerializer,
    MaterialListSerializer
)


class LoteViewSet(viewsets.ModelViewSet):
    """ViewSet para gestión completa de lotes"""
    queryset = Lote.objects.all().select_related(
        'proveedor', 'almacen_destino', 'tipo_servicio', 'created_by'
    ).prefetch_related('detalles__modelo__marca')
    permission_classes = [IsAuthenticated, GenericRolePermission]
    basename = 'lotes'

    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = [
        'tipo_ingreso', 'estado', 'proveedor', 'almacen_destino', 'tipo_servicio'
    ]
    search_fields = [
        'numero_lote', 'codigo_requerimiento_compra', 'codigo_nota_ingreso'
    ]
    ordering_fields = ['numero_lote', 'fecha_recepcion', 'created_at']
    ordering = ['-created_at']

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return LoteCreateSerializer
        return LoteSerializer

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=['get'])
    def resumen(self, request, pk=None):
        """Resumen estadístico completo del lote"""
        lote = self.get_object()

        # Estadísticas básicas
        cantidad_total = lote.cantidad_total
        cantidad_recibida = lote.cantidad_recibida
        cantidad_pendiente = lote.cantidad_pendiente
        porcentaje_recibido = lote.porcentaje_recibido

        # Resumen por modelo
        detalles_info = []
        for detalle in lote.detalles.all():
            materiales_del_modelo = lote.material_set.filter(modelo=detalle.modelo)

            # Estados de materiales de este modelo (solo para ONUs)
            estados_info = {}
            if detalle.modelo.tipo_material == TipoMaterialChoices.ONU:
                for estado_choice in EstadoMaterialONUChoices.choices:
                    estado_codigo, estado_nombre = estado_choice
                    count = materiales_del_modelo.filter(estado_onu=estado_codigo).count()
                    if count > 0:
                        estados_info[estado_nombre] = count

            detalles_info.append({
                'modelo_id': detalle.modelo.id,
                'modelo_nombre': f"{detalle.modelo.marca.nombre} {detalle.modelo.nombre}",
                'codigo_modelo': detalle.modelo.codigo_modelo,
                'tipo_material': detalle.modelo.get_tipo_material_display(),
                'unidad_medida': detalle.modelo.get_unidad_medida_display(),
                'cantidad_esperada': detalle.cantidad,
                'cantidad_recibida': materiales_del_modelo.count(),
                'cantidad_pendiente': max(0, detalle.cantidad - materiales_del_modelo.count()),
                'porcentaje_recibido': round(
                    (materiales_del_modelo.count() / detalle.cantidad * 100), 2
                ) if detalle.cantidad > 0 else 0,
                'estados_materiales': estados_info
            })

        # Entregas parciales
        entregas = lote.entregas_parciales.all().order_by('numero_entrega')

        return Response({
            'lote': {
                'id': lote.id,
                'numero_lote': lote.numero_lote,
                'proveedor': lote.proveedor.nombre_comercial,
                'tipo_ingreso': lote.get_tipo_ingreso_display(),
                'estado': lote.get_estado_display(),
                'almacen_destino': lote.almacen_destino.nombre,
                'fecha_recepcion': lote.fecha_recepcion,
                'fecha_inicio_garantia': lote.fecha_inicio_garantia,
                'fecha_fin_garantia': lote.fecha_fin_garantia
            },
            'estadisticas': {
                'cantidad_total': cantidad_total,
                'cantidad_recibida': cantidad_recibida,
                'cantidad_pendiente': cantidad_pendiente,
                'porcentaje_recibido': porcentaje_recibido,
                'total_entregas_parciales': lote.total_entregas_parciales
            },
            'detalles_por_modelo': detalles_info,
            'entregas_parciales': EntregaParcialLoteSerializer(entregas, many=True).data,
            'requiere_laboratorio': any(
                detalle.modelo.requiere_inspeccion_inicial
                for detalle in lote.detalles.all()
            )
        })

    @action(detail=True, methods=['post'])
    def agregar_entrega_parcial(self, request, pk=None):
        """Agregar una nueva entrega parcial al lote"""
        lote = self.get_object()

        if lote.estado == EstadoLoteChoices.CERRADO:
            return Response(
                {'error': 'No se pueden agregar entregas a un lote cerrado'},
                status=status.HTTP_400_BAD_REQUEST
            )

        data = request.data.copy()
        data['lote'] = lote.id
        data['numero_entrega'] = lote.total_entregas_parciales + 1

        serializer = EntregaParcialLoteSerializer(data=data)
        if serializer.is_valid():
            with transaction.atomic():
                entrega = serializer.save(created_by=request.user)

                # Actualizar contador en el lote
                lote.total_entregas_parciales += 1

                # Actualizar estado del lote según las entregas
                if lote.cantidad_recibida >= lote.cantidad_total:
                    lote.estado = EstadoLoteChoices.RECEPCION_COMPLETA
                else:
                    lote.estado = EstadoLoteChoices.RECEPCION_PARCIAL

                lote.save()

            return Response(
                EntregaParcialLoteSerializer(entrega).data,
                status=status.HTTP_201_CREATED
            )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def cerrar_lote(self, request, pk=None):
        """Cerrar lote (no se pueden agregar más materiales)"""
        lote = self.get_object()

        if lote.estado == EstadoLoteChoices.CERRADO:
            return Response(
                {'error': 'El lote ya está cerrado'},
                status=status.HTTP_400_BAD_REQUEST
            )

        with transaction.atomic():
            lote.estado = EstadoLoteChoices.CERRADO
            lote.save()

        return Response({
            'message': f'Lote {lote.numero_lote} cerrado correctamente',
            'estado': lote.get_estado_display(),
            'fecha_cierre': lote.updated_at
        })

    @action(detail=True, methods=['post'])
    def reabrir_lote(self, request, pk=None):
        """Reabrir lote cerrado (solo para administradores)"""
        lote = self.get_object()

        if lote.estado != EstadoLoteChoices.CERRADO:
            return Response(
                {'error': 'Solo se pueden reabrir lotes cerrados'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Verificar permisos especiales (puedes personalizar esto)
        if not request.user.is_superuser:
            return Response(
                {'error': 'Solo administradores pueden reabrir lotes'},
                status=status.HTTP_403_FORBIDDEN
            )

        with transaction.atomic():
            lote.estado = EstadoLoteChoices.ACTIVO
            lote.save()

        return Response({
            'message': f'Lote {lote.numero_lote} reabierto correctamente',
            'estado': lote.get_estado_display()
        })

    @action(detail=True, methods=['get'])
    def materiales(self, request, pk=None):
        """Obtener todos los materiales del lote"""
        lote = self.get_object()
        materiales = lote.material_set.all()

        # Filtros opcionales
        tipo_material = request.query_params.get('tipo_material')
        estado = request.query_params.get('estado')
        modelo_id = request.query_params.get('modelo_id')

        if tipo_material:
            materiales = materiales.filter(tipo_material=tipo_material)

        if estado:
            if tipo_material == TipoMaterialChoices.ONU:
                materiales = materiales.filter(estado_onu=estado)
            else:
                materiales = materiales.filter(estado_general=estado)

        if modelo_id:
            materiales = materiales.filter(modelo_id=modelo_id)

        page = self.paginate_queryset(materiales)
        if page is not None:
            serializer = MaterialListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = MaterialListSerializer(materiales, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def enviar_laboratorio_masivo(self, request, pk=None):
        """Enviar todos los materiales nuevos del lote a laboratorio"""
        lote = self.get_object()

        if lote.tipo_ingreso != TipoIngresoChoices.NUEVO:
            return Response(
                {'error': 'Solo los lotes nuevos requieren inspección inicial'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Filtrar materiales que requieren laboratorio
        materiales_nuevos = lote.material_set.filter(
            tipo_material=TipoMaterialChoices.ONU,
            es_nuevo=True,
            estado_onu=EstadoMaterialONUChoices.NUEVO
        )

        if not materiales_nuevos.exists():
            return Response(
                {'error': 'No hay materiales nuevos que requieran inspección'},
                status=status.HTTP_200_OK
            )

        with transaction.atomic():
            count = 0
            for material in materiales_nuevos:
                material.enviar_a_laboratorio(usuario=request.user)
                count += 1

        return Response({
            'message': f'{count} materiales enviados a laboratorio para inspección inicial',
            'materiales_enviados': count,
            'lote': lote.numero_lote
        })

    @action(detail=False, methods=['get'])
    def estadisticas(self, request):
        """Estadísticas generales de lotes"""
        # Lotes por estado
        por_estado = {}
        for estado_choice in EstadoLoteChoices.choices:
            estado_codigo, estado_nombre = estado_choice
            count = Lote.objects.filter(estado=estado_codigo).count()
            por_estado[estado_nombre] = count

        # Lotes por tipo de ingreso
        por_tipo = {}
        for tipo_choice in TipoIngresoChoices.choices:
            tipo_codigo, tipo_nombre = tipo_choice
            count = Lote.objects.filter(tipo_ingreso=tipo_codigo).count()
            por_tipo[tipo_nombre] = count

        # Top proveedores por cantidad de lotes
        from django.db.models import Count
        top_proveedores = Lote.objects.values(
            'proveedor__nombre_comercial'
        ).annotate(
            total_lotes=Count('id')
        ).order_by('-total_lotes')[:10]

        return Response({
            'total_lotes': Lote.objects.count(),
            'por_estado': por_estado,
            'por_tipo_ingreso': por_tipo,
            'top_proveedores': list(top_proveedores),
            'lotes_activos': Lote.objects.filter(
                estado__in=[EstadoLoteChoices.ACTIVO, EstadoLoteChoices.RECEPCION_PARCIAL]
            ).count()
        })


class ImportacionMasivaView(APIView):
    """View para importación masiva de materiales desde Excel/CSV"""
    permission_classes = [IsAuthenticated, GenericRolePermission]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, *args, **kwargs):
        """Procesar archivo de importación masiva"""

        serializer = ImportacionMasivaSerializer(
            data=request.data,
            context={'request': request}
        )

        if serializer.is_valid():
            try:
                resultado = serializer.procesar_importacion()

                return Response({
                    'success': True,
                    'message': 'Importación procesada correctamente',
                    'resultado': resultado
                }, status=status.HTTP_200_OK)

            except Exception as e:
                return Response({
                    'success': False,
                    'error': f'Error procesando importación: {str(e)}'
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({
            'success': False,
            'errors': serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)

    def get(self, request, *args, **kwargs):
        """Obtener plantilla de importación y instrucciones"""
        return Response({
            'plantilla': {
                'columnas_requeridas': ['MAC', 'GPON_SN', 'D_SN', 'ITEM_EQUIPO'],
                'formato_mac': 'XX:XX:XX:XX:XX:XX (mayúsculas, separado por :)',
                'formato_item_equipo': '6-10 dígitos numéricos',
                'ejemplo': {
                    'MAC': '00:11:22:33:44:55',
                    'GPON_SN': 'HWTC12345678',
                    'D_SN': 'SN123456789',
                    'ITEM_EQUIPO': '1234567890'
                }
            },
            'instrucciones': [
                '1. Usar formato Excel (.xlsx) o CSV',
                '2. La primera fila debe contener los nombres exactos de las columnas',
                '3. No dejar filas vacías entre los datos',
                '4. Verificar que todos los MACs sean únicos',
                '5. El archivo no debe ser mayor a 5MB',
                '6. Máximo 1000 equipos por importación'
            ],
            'validaciones': [
                'MAC Address debe ser único en el sistema',
                'GPON Serial debe ser único',
                'D-SN debe ser único',
                'Formato de MAC debe ser válido',
                'Item Equipo debe tener 6-10 dígitos'
            ]
        })


class LoteDetalleViewSet(viewsets.ModelViewSet):
    """ViewSet para gestión de detalles de lotes"""
    queryset = LoteDetalle.objects.all().select_related('lote', 'modelo__marca')
    serializer_class = LoteDetalleSerializer
    permission_classes = [IsAuthenticated, GenericRolePermission]
    basename = 'lote-detalles'

    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['lote', 'modelo']

    def get_queryset(self):
        """Filtrar por lote si se proporciona en la URL"""
        queryset = super().get_queryset()
        lote_id = self.request.query_params.get('lote_id')

        if lote_id:
            queryset = queryset.filter(lote_id=lote_id)

        return queryset