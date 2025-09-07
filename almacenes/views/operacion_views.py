# ======================================================
# almacenes/views/operacion_views.py - ACTUALIZADO SIN TEXTCHOICES
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
    Material,
    # Modelos de choices (antes TextChoices)
    EstadoTraspaso, EstadoDevolucion, RespuestaProveedor, TipoMaterial,
    EstadoMaterialONU, EstadoMaterialGeneral
)
from ..serializers import (
    TraspasoAlmacenSerializer, TraspasoCreateSerializer, TraspasoMaterialSerializer,
    DevolucionProveedorSerializer, DevolucionCreateSerializer, DevolucionMaterialSerializer
)


class TraspasoAlmacenViewSet(viewsets.ModelViewSet):
    """ViewSet para gestión completa de traspasos entre almacenes"""
    queryset = TraspasoAlmacen.objects.all().select_related(
        'almacen_origen', 'almacen_destino', 'usuario_envio', 'usuario_recepcion', 'estado'
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
            try:
                estado_pendiente = EstadoTraspaso.objects.get(codigo='PENDIENTE', activo=True)
                queryset = queryset.filter(estado=estado_pendiente)
            except EstadoTraspaso.DoesNotExist:
                queryset = queryset.none()

        # Filtro por traspasos en tránsito
        en_transito = self.request.query_params.get('en_transito')
        if en_transito == 'true':
            try:
                estado_transito = EstadoTraspaso.objects.get(codigo='EN_TRANSITO', activo=True)
                queryset = queryset.filter(estado=estado_transito)
            except EstadoTraspaso.DoesNotExist:
                queryset = queryset.none()

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

        try:
            estado_pendiente = EstadoTraspaso.objects.get(codigo='PENDIENTE', activo=True)
            estado_transito = EstadoTraspaso.objects.get(codigo='EN_TRANSITO', activo=True)
        except EstadoTraspaso.DoesNotExist:
            return Response(
                {'error': 'Estados de traspaso no configurados correctamente'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        if traspaso.estado != estado_pendiente:
            return Response(
                {'error': 'Solo se pueden enviar traspasos pendientes'},
                status=status.HTTP_400_BAD_REQUEST
            )

        observaciones = request.data.get('observaciones_envio', '')

        with transaction.atomic():
            # Actualizar traspaso
            traspaso.estado = estado_transito
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
            'estado': traspaso.estado.nombre if traspaso.estado else 'Sin estado',
            'fecha_envio': traspaso.fecha_envio
        })

    @action(detail=True, methods=['post'])
    def recibir(self, request, pk=None):
        """Confirmar recepción del traspaso"""
        traspaso = self.get_object()

        try:
            estado_transito = EstadoTraspaso.objects.get(codigo='EN_TRANSITO', activo=True)
            estado_recibido = EstadoTraspaso.objects.get(codigo='RECIBIDO', activo=True)
        except EstadoTraspaso.DoesNotExist:
            return Response(
                {'error': 'Estados de traspaso no configurados correctamente'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        if traspaso.estado != estado_transito:
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
            traspaso.estado = estado_recibido
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

        try:
            estado_pendiente = EstadoTraspaso.objects.get(codigo='PENDIENTE', activo=True)
            estado_transito = EstadoTraspaso.objects.get(codigo='EN_TRANSITO', activo=True)
            estado_cancelado = EstadoTraspaso.objects.get(codigo='CANCELADO', activo=True)
        except EstadoTraspaso.DoesNotExist:
            return Response(
                {'error': 'Estados de traspaso no configurados correctamente'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        if traspaso.estado not in [estado_pendiente, estado_transito]:
            return Response(
                {'error': 'Solo se pueden cancelar traspasos pendientes o en tránsito'},
                status=status.HTTP_400_BAD_REQUEST
            )

        motivo_cancelacion = request.data.get('motivo', 'Sin especificar')

        with transaction.atomic():
            # Liberar materiales si estaba en tránsito
            if traspaso.estado == estado_transito:
                for traspaso_material in traspaso.materiales.all():
                    material = traspaso_material.material
                    material.traspaso_actual = None
                    material.save()

            traspaso.estado = estado_cancelado
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
            'estado': traspaso.estado.nombre if traspaso.estado else 'Sin estado',
            'materiales': serializer.data
        })

    @action(detail=False, methods=['get'])
    def estadisticas(self, request):
        """Estadísticas de traspasos"""
        # Por estado usando el nuevo modelo
        por_estado = {}
        estados = EstadoTraspaso.objects.filter(activo=True)
        for estado in estados:
            count = TraspasoAlmacen.objects.filter(estado=estado).count()
            por_estado[estado.nombre] = count

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
        try:
            estado_recibido = EstadoTraspaso.objects.get(codigo='RECIBIDO', activo=True)
            traspasos_completados = TraspasoAlmacen.objects.filter(
                estado=estado_recibido,
                fecha_recepcion__isnull=False
            )
        except EstadoTraspaso.DoesNotExist:
            traspasos_completados = TraspasoAlmacen.objects.none()

        if traspasos_completados.exists():
            from django.db.models import Avg
            from django.db.models import F
            tiempo_promedio = traspasos_completados.annotate(
                duracion=F('fecha_recepcion') - F('fecha_envio')
            ).aggregate(promedio=Avg('duracion'))['promedio']

            tiempo_promedio_dias = tiempo_promedio.days if tiempo_promedio else 0
        else:
            tiempo_promedio_dias = 0

        # Contadores por estado específico
        try:
            pendientes = TraspasoAlmacen.objects.filter(
                estado=EstadoTraspaso.objects.get(codigo='PENDIENTE', activo=True)
            ).count()
            en_transito = TraspasoAlmacen.objects.filter(
                estado=EstadoTraspaso.objects.get(codigo='EN_TRANSITO', activo=True)
            ).count()
        except EstadoTraspaso.DoesNotExist:
            pendientes = 0
            en_transito = 0

        return Response({
            'total_traspasos': TraspasoAlmacen.objects.count(),
            'por_estado': por_estado,
            'por_almacen_origen': list(por_almacen_origen),
            'por_almacen_destino': list(por_almacen_destino),
            'tiempo_promedio_dias': tiempo_promedio_dias,
            'pendientes': pendientes,
            'en_transito': en_transito
        })


class DevolucionProveedorViewSet(viewsets.ModelViewSet):
    """ViewSet para gestión de devoluciones a proveedores"""
    queryset = DevolucionProveedor.objects.all().select_related(
        'lote_origen__proveedor', 'proveedor', 'created_by', 'estado', 'respuesta_proveedor'
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

        try:
            estado_pendiente = EstadoDevolucion.objects.get(codigo='PENDIENTE', activo=True)
            estado_enviado = EstadoDevolucion.objects.get(codigo='ENVIADO', activo=True)
            estado_devuelto_onu = EstadoMaterialONU.objects.get(codigo='DEVUELTO_PROVEEDOR', activo=True)
            estado_baja_general = EstadoMaterialGeneral.objects.get(codigo='DADO_DE_BAJA', activo=True)
        except (EstadoDevolucion.DoesNotExist, EstadoMaterialONU.DoesNotExist, EstadoMaterialGeneral.DoesNotExist):
            return Response(
                {'error': 'Estados no configurados correctamente'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        if devolucion.estado != estado_pendiente:
            return Response(
                {'error': 'Solo se pueden enviar devoluciones pendientes'},
                status=status.HTTP_400_BAD_REQUEST
            )

        with transaction.atomic():
            devolucion.estado = estado_enviado
            devolucion.fecha_envio = timezone.now()
            devolucion.save()

            # Actualizar estado de materiales devueltos
            for devolucion_material in devolucion.materiales_devueltos.all():
                material = devolucion_material.material
                if material.tipo_material.es_unico:
                    material.estado_onu = estado_devuelto_onu
                else:
                    material.estado_general = estado_baja_general
                material.save()

        return Response({
            'message': f'Devolución {devolucion.numero_devolucion} enviada al proveedor',
            'fecha_envio': devolucion.fecha_envio
        })

    @action(detail=True, methods=['post'])
    def confirmar_respuesta(self, request, pk=None):
        """Confirmar respuesta del proveedor"""
        devolucion = self.get_object()

        try:
            estado_enviado = EstadoDevolucion.objects.get(codigo='ENVIADO', activo=True)
            estado_confirmado = EstadoDevolucion.objects.get(codigo='CONFIRMADO', activo=True)
        except EstadoDevolucion.DoesNotExist:
            return Response(
                {'error': 'Estados de devolución no configurados correctamente'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        if devolucion.estado != estado_enviado:
            return Response(
                {'error': 'Solo se puede confirmar respuesta de devoluciones enviadas'},
                status=status.HTTP_400_BAD_REQUEST
            )

        respuesta_id = request.data.get('respuesta_proveedor_id')
        observaciones = request.data.get('observaciones_proveedor', '')

        if not respuesta_id:
            return Response(
                {'error': 'ID de respuesta del proveedor requerido'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            respuesta = RespuestaProveedor.objects.get(id=respuesta_id, activo=True)
        except RespuestaProveedor.DoesNotExist:
            return Response(
                {'error': 'Respuesta del proveedor no válida'},
                status=status.HTTP_400_BAD_REQUEST
            )

        with transaction.atomic():
            devolucion.estado = estado_confirmado
            devolucion.respuesta_proveedor = respuesta
            devolucion