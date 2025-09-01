# ======================================================
# almacenes/views/operacion_views.py
# Views para traspasos y devoluciones
# ======================================================

from django.db import transaction
from django.utils import timezone
from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend

from usuarios.permissions import GenericRolePermission
from ..models import (
    TraspasoAlmacen, TraspasoMaterial, DevolucionProveedor, DevolucionMaterial,
    Material, EstadoTraspasoChoices, EstadoDevolucionChoices,
    RespuestaProveedorChoices, TipoMaterialChoices,
    EstadoMaterialONUChoices, EstadoMaterialGeneralChoices
)
from ..serializers import (
    TraspasoAlmacenSerializer, TraspasoCreateSerializer, TraspasoMaterialSerializer,
    DevolucionProveedorSerializer, DevolucionCreateSerializer, DevolucionMaterialSerializer
)


class TraspasoAlmacenViewSet(viewsets.ModelViewSet):
    """ViewSet para gestión completa de traspasos entre almacenes"""
    queryset = TraspasoAlmacen.objects.all().select_related(
        'almacen_origen', 'almacen_destino', 'usuario_envio', 'usuario_recepcion'
    ).prefetch_related('materiales__material')
    permission_classes = [IsAuthenticated, GenericRolePermission]
    basename = 'traspasos'

    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = [
        'estado', 'almacen_origen', 'almacen_destino', 'usuario_envio', 'usuario_recepcion'
    ]
    search_fields = ['numero_traspaso', 'numero_solicitud', 'motivo']
    ordering_fields = ['numero_traspaso', 'fecha_envio', 'fecha_recepcion']
    ordering = ['-created_at']

    def get_serializer_class(self):
        if self.action == 'create':
            return TraspasoCreateSerializer
        return TraspasoAlmacenSerializer

    def get_queryset(self):
        """Filtros adicionales"""
        queryset = super().get_queryset()

        # Filtro por traspasos pendientes
        pendientes = self.request.query_params.get('pendientes')
        if pendientes == 'true':
            queryset = queryset.filter(estado=EstadoTraspasoChoices.PENDIENTE)

        # Filtro por traspasos en tránsito
        en_transito = self.request.query_params.get('en_transito')
        if en_transito == 'true':
            queryset = queryset.filter(estado=EstadoTraspasoChoices.EN_TRANSITO)

        # Filtros de fecha
        fecha_desde = self.request.query_params.get('fecha_desde')
        if fecha_desde:
            queryset = queryset.filter(fecha_envio__gte=fecha_desde)

        fecha_hasta = self.request.query_params.get('fecha_hasta')
        if fecha_hasta:
            queryset = queryset.filter(fecha_envio__lte=fecha_hasta)

        return queryset

    @action(detail=True, methods=['post'])
    def enviar(self, request, pk=None):
        """Confirmar envío del traspaso"""
        traspaso = self.get_object()

        if traspaso.estado != EstadoTraspasoChoices.PENDIENTE:
            return Response(
                {'error': 'Solo se pueden enviar traspasos pendientes'},
                status=status.HTTP_400_BAD_REQUEST
            )

        observaciones = request.data.get('observaciones_envio', '')

        with transaction.atomic():
            # Actualizar traspaso
            traspaso.estado = EstadoTraspasoChoices.EN_TRANSITO
            traspaso.fecha_envio = timezone.now()
            traspaso.observaciones_envio = observaciones
            traspaso.usuario_envio = request.user
            traspaso.save()

            # Actualizar estado de materiales
            for traspaso_material in traspaso.materiales.all():
                material = traspaso_material.material
                material.traspaso_actual = traspaso
                material.save()

        return Response({
            'message': f'Traspaso {traspaso.numero_traspaso} enviado correctamente',
            'estado': traspaso.get_estado_display(),
            'fecha_envio': traspaso.fecha_envio
        })

    @action(detail=True, methods=['post'])
    def recibir(self, request, pk=None):
        """Confirmar recepción del traspaso"""
        traspaso = self.get_object()

        if traspaso.estado != EstadoTraspasoChoices.EN_TRANSITO:
            return Response(
                {'error': 'Solo se pueden recibir traspasos en tránsito'},
                status=status.HTTP_400_BAD_REQUEST
            )

        cantidad_recibida = request.data.get('cantidad_recibida', traspaso.cantidad_enviada)
        observaciones = request.data.get('observaciones_recepcion', '')
        materiales_recibidos = request.data.get('materiales_recibidos', [])  # IDs de materiales

        if cantidad_recibida > traspaso.cantidad_enviada:
            return Response(
                {'error': 'No se puede recibir más cantidad de la enviada'},
                status=status.HTTP_400_BAD_REQUEST
            )

        with transaction.atomic():
            # Actualizar traspaso
            traspaso.cantidad_recibida = cantidad_recibida
            traspaso.fecha_recepcion = timezone.now()
            traspaso.observaciones_recepcion = observaciones
            traspaso.usuario_recepcion = request.user
            traspaso.estado = EstadoTraspasoChoices.RECIBIDO
            traspaso.save()

            # Actualizar materiales recibidos
            for traspaso_material in traspaso.materiales.all():
                material = traspaso_material.material

                if material.id in materiales_recibidos or not materiales_recibidos:
                    # Material recibido - actualizar ubicación
                    material.almacen_actual = traspaso.almacen_destino
                    material.traspaso_actual = None
                    material.save()

                    # Marcar como recibido en el traspaso
                    traspaso_material.recibido = True
                    traspaso_material.save()

        return Response({
            'message': f'Traspaso {traspaso.numero_traspaso} recibido correctamente',
            'cantidad_recibida': cantidad_recibida,
            'cantidad_enviada': traspaso.cantidad_enviada,
            'materiales_faltantes': traspaso.materiales_faltantes
        })

    @action(detail=True, methods=['post'])
    def cancelar(self, request, pk=None):
        """Cancelar traspaso"""
        traspaso = self.get_object()

        if traspaso.estado not in [EstadoTraspasoChoices.PENDIENTE, EstadoTraspasoChoices.EN_TRANSITO]:
            return Response(
                {'error': 'Solo se pueden cancelar traspasos pendientes o en tránsito'},
                status=status.HTTP_400_BAD_REQUEST
            )

        motivo_cancelacion = request.data.get('motivo', 'Sin especificar')

        with transaction.atomic():
            # Liberar materiales si estaba en tránsito
            if traspaso.estado == EstadoTraspasoChoices.EN_TRANSITO:
                for traspaso_material in traspaso.materiales.all():
                    material = traspaso_material.material
                    material.traspaso_actual = None
                    material.save()

            traspaso.estado = EstadoTraspasoChoices.CANCELADO
            traspaso.observaciones_envio += f"\n[CANCELADO] {motivo_cancelacion}"
            traspaso.save()

        return Response({
            'message': f'Traspaso {traspaso.numero_traspaso} cancelado',
            'motivo': motivo_cancelacion
        })

    @action(detail=True, methods=['get'])
    def materiales_detalle(self, request, pk=None):
        """Obtener detalle de materiales en el traspaso"""
        traspaso = self.get_object()
        materiales = traspaso.materiales.all()

        serializer = TraspasoMaterialSerializer(materiales, many=True)
        return Response({
            'traspaso': traspaso.numero_traspaso,
            'estado': traspaso.get_estado_display(),
            'materiales': serializer.data
        })

    @action(detail=False, methods=['get'])
    def estadisticas(self, request):
        """Estadísticas de traspasos"""
        # Por estado
        por_estado = {}
        for estado_choice in EstadoTraspasoChoices.choices:
            estado_codigo, estado_nombre = estado_choice
            count = TraspasoAlmacen.objects.filter(estado=estado_codigo).count()
            por_estado[estado_nombre] = count

        # Traspasos por almacén (como origen)
        from django.db.models import Count
        por_almacen_origen = TraspasoAlmacen.objects.values(
            'almacen_origen__nombre'
        ).annotate(
            total_enviados=Count('id')
        ).order_by('-total_enviados')[:10]

        # Traspasos por almacén (como destino)
        por_almacen_destino = TraspasoAlmacen.objects.values(
            'almacen_destino__nombre'
        ).annotate(
            total_recibidos=Count('id')
        ).order_by('-total_recibidos')[:10]

        # Tiempo promedio de tránsito
        traspasos_completados = TraspasoAlmacen.objects.filter(
            estado=EstadoTraspasoChoices.RECIBIDO,
            fecha_recepcion__isnull=False
        )

        if traspasos_completados.exists():
            from django.db.models import Avg
            from django.db.models import F
            tiempo_promedio = traspasos_completados.annotate(
                duracion=F('fecha_recepcion') - F('fecha_envio')
            ).aggregate(promedio=Avg('duracion'))['promedio']

            tiempo_promedio_dias = tiempo_promedio.days if tiempo_promedio else 0
        else:
            tiempo_promedio_dias = 0

        return Response({
            'total_traspasos': TraspasoAlmacen.objects.count(),
            'por_estado': por_estado,
            'por_almacen_origen': list(por_almacen_origen),
            'por_almacen_destino': list(por_almacen_destino),
            'tiempo_promedio_dias': tiempo_promedio_dias,
            'pendientes': TraspasoAlmacen.objects.filter(
                estado=EstadoTraspasoChoices.PENDIENTE
            ).count(),
            'en_transito': TraspasoAlmacen.objects.filter(
                estado=EstadoTraspasoChoices.EN_TRANSITO
            ).count()
        })


class DevolucionProveedorViewSet(viewsets.ModelViewSet):
    """ViewSet para gestión de devoluciones a proveedores"""
    queryset = DevolucionProveedor.objects.all().select_related(
        'lote_origen__proveedor', 'proveedor', 'created_by'
    ).prefetch_related('materiales_devueltos__material')
    permission_classes = [IsAuthenticated, GenericRolePermission]
    basename = 'devoluciones'

    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = [
        'estado', 'proveedor', 'lote_origen', 'respuesta_proveedor'
    ]
    search_fields = ['numero_devolucion', 'motivo', 'numero_informe_laboratorio']
    ordering_fields = ['numero_devolucion', 'fecha_creacion', 'fecha_envio']
    ordering = ['-fecha_creacion']

    def get_serializer_class(self):
        if self.action == 'create':
            return DevolucionCreateSerializer
        return DevolucionProveedorSerializer

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=['post'])
    def enviar_proveedor(self, request, pk=None):
        """Marcar devolución como enviada al proveedor"""
        devolucion = self.get_object()

        if devolucion.estado != EstadoDevolucionChoices.PENDIENTE:
            return Response(
                {'error': 'Solo se pueden enviar devoluciones pendientes'},
                status=status.HTTP_400_BAD_REQUEST
            )

        with transaction.atomic():
            devolucion.estado = EstadoDevolucionChoices.ENVIADO
            devolucion.fecha_envio = timezone.now()
            devolucion.save()

            # Actualizar estado de materiales devueltos
            for devolucion_material in devolucion.materiales_devueltos.all():
                material = devolucion_material.material
                if material.tipo_material == TipoMaterialChoices.ONU:
                    material.estado_onu = EstadoMaterialONUChoices.DEVUELTO_PROVEEDOR
                else:
                    material.estado_general = EstadoMaterialGeneralChoices.DADO_DE_BAJA
                material.save()

        return Response({
            'message': f'Devolución {devolucion.numero_devolucion} enviada al proveedor',
            'fecha_envio': devolucion.fecha_envio
        })

    @action(detail=True, methods=['post'])
    def confirmar_respuesta(self, request, pk=None):
        """Confirmar respuesta del proveedor"""
        devolucion = self.get_object()

        if devolucion.estado != EstadoDevolucionChoices.ENVIADO:
            return Response(
                {'error': 'Solo se puede confirmar respuesta de devoluciones enviadas'},
                status=status.HTTP_400_BAD_REQUEST
            )

        respuesta = request.data.get('respuesta_proveedor')
        observaciones = request.data.get('observaciones_proveedor', '')

        if respuesta not in [choice[0] for choice in RespuestaProveedorChoices.choices]:
            return Response(
                {'error': 'Respuesta del proveedor no válida'},
                status=status.HTTP_400_BAD_REQUEST
            )

        with transaction.atomic():
            devolucion.estado = EstadoDevolucionChoices.CONFIRMADO
            devolucion.respuesta_proveedor = respuesta
            devolucion.observaciones_proveedor = observaciones
            devolucion.fecha_confirmacion = timezone.now()
            devolucion.save()

        return Response({
            'message': f'Respuesta del proveedor confirmada: {devolucion.get_respuesta_proveedor_display()}',
            'respuesta': devolucion.get_respuesta_proveedor_display()
        })

    @action(detail=True, methods=['get'])
    def materiales_detalle(self, request, pk=None):
        """Obtener detalle de materiales en la devolución"""
        devolucion = self.get_object()
        materiales = devolucion.materiales_devueltos.all()

        serializer = DevolucionMaterialSerializer(materiales, many=True)
        return Response({
            'devolucion': devolucion.numero_devolucion,
            'proveedor': devolucion.proveedor.nombre_comercial,
            'estado': devolucion.get_estado_display(),
            'materiales': serializer.data
        })

    @action(detail=False, methods=['get'])
    def estadisticas(self, request):
        """Estadísticas de devoluciones"""
        # Por estado
        por_estado = {}
        for estado_choice in EstadoDevolucionChoices.choices:
            estado_codigo, estado_nombre = estado_choice
            count = DevolucionProveedor.objects.filter(estado=estado_codigo).count()
            por_estado[estado_nombre] = count

        # Por respuesta del proveedor
        por_respuesta = {}
        for respuesta_choice in RespuestaProveedorChoices.choices:
            respuesta_codigo, respuesta_nombre = respuesta_choice
            count = DevolucionProveedor.objects.filter(
                respuesta_proveedor=respuesta_codigo
            ).count()
            por_respuesta[respuesta_nombre] = count

        # Por proveedor
        from django.db.models import Count
        por_proveedor = DevolucionProveedor.objects.values(
            'proveedor__nombre_comercial'
        ).annotate(
            total_devoluciones=Count('id')
        ).order_by('-total_devoluciones')[:10]

        # Tiempo promedio de respuesta
        devoluciones_respondidas = DevolucionProveedor.objects.filter(
            estado=EstadoDevolucionChoices.CONFIRMADO,
            fecha_confirmacion__isnull=False,
            fecha_envio__isnull=False
        )

        if devoluciones_respondidas.exists():
            from django.db.models import Avg, F
            tiempo_promedio = devoluciones_respondidas.annotate(
                tiempo_respuesta=F('fecha_confirmacion') - F('fecha_envio')
            ).aggregate(promedio=Avg('tiempo_respuesta'))['promedio']

            tiempo_promedio_dias = tiempo_promedio.days if tiempo_promedio else 0
        else:
            tiempo_promedio_dias = 0

        return Response({
            'total_devoluciones': DevolucionProveedor.objects.count(),
            'por_estado': por_estado,
            'por_respuesta': por_respuesta,
            'por_proveedor': list(por_proveedor),
            'tiempo_promedio_respuesta_dias': tiempo_promedio_dias,
            'pendientes': DevolucionProveedor.objects.filter(
                estado=EstadoDevolucionChoices.PENDIENTE
            ).count(),
            'enviadas_sin_respuesta': DevolucionProveedor.objects.filter(
                estado=EstadoDevolucionChoices.ENVIADO
            ).count()
        })