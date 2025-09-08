# ======================================================
# almacenes/views/operacion_views.py - COMPLETO
# Views para traspasos y devoluciones
# ======================================================

from datetime import datetime, timedelta
from django.db import transaction
from django.db.models import Count, Q, Avg, F
from django.utils import timezone
from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend

from usuarios.permissions import GenericRolePermission
from ..models import (
    TraspasoAlmacen, TraspasoMaterial, DevolucionProveedor, DevolucionMaterial,
    Material, HistorialMaterial,
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

        # Filtro por usuario
        mi_usuario = self.request.query_params.get('mi_usuario')
        if mi_usuario == 'true':
            queryset = queryset.filter(
                Q(usuario_envio=self.request.user) | Q(usuario_recepcion=self.request.user)
            )

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

                # Crear entrada en historial
                HistorialMaterial.objects.create(
                    material=material,
                    estado_anterior=material.estado_display,
                    estado_nuevo='En tránsito',
                    almacen_anterior=material.almacen_actual,
                    almacen_nuevo=traspaso.almacen_destino,
                    motivo=f'Traspaso enviado: {traspaso.numero_traspaso}',
                    observaciones=observaciones,
                    traspaso_relacionado=traspaso,
                    usuario_responsable=request.user
                )

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
                    almacen_anterior = material.almacen_actual
                    material.almacen_actual = traspaso.almacen_destino
                    material.traspaso_actual = None
                    material.save()

                    # Marcar como recibido en el traspaso
                    traspaso_material.recibido = True
                    traspaso_material.observaciones = f"Recibido el {timezone.now().strftime('%Y-%m-%d %H:%M')}"
                    traspaso_material.save()

                    # Crear entrada en historial
                    HistorialMaterial.objects.create(
                        material=material,
                        estado_anterior='En tránsito',
                        estado_nuevo=material.estado_display,
                        almacen_anterior=almacen_anterior,
                        almacen_nuevo=material.almacen_actual,
                        motivo=f'Traspaso recibido: {traspaso.numero_traspaso}',
                        observaciones=observaciones,
                        traspaso_relacionado=traspaso,
                        usuario_responsable=request.user
                    )

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

                    # Crear entrada en historial
                    HistorialMaterial.objects.create(
                        material=material,
                        estado_anterior='En tránsito',
                        estado_nuevo=material.estado_display,
                        almacen_anterior=material.almacen_actual,
                        almacen_nuevo=material.almacen_actual,
                        motivo=f'Traspaso cancelado: {traspaso.numero_traspaso}',
                        observaciones=motivo_cancelacion,
                        traspaso_relacionado=traspaso,
                        usuario_responsable=request.user
                    )

            traspaso.estado = estado_cancelado
            traspaso.observaciones_envio += f"\n[CANCELADO {timezone.now().strftime('%Y-%m-%d %H:%M')}] {motivo_cancelacion}"
            traspaso.save()

        return Response({
            'message': f'Traspaso {traspaso.numero_traspaso} cancelado',
            'motivo': motivo_cancelacion
        })

    @action(detail=True, methods=['get'])
    def materiales_detalle(self, request, pk=None):
        """Obtener detalle de materiales en el traspaso"""
        traspaso = self.get_object()
        materiales = traspaso.materiales.all().select_related('material__modelo__marca')

        serializer = TraspasoMaterialSerializer(materiales, many=True)
        return Response({
            'traspaso': {
                'numero': traspaso.numero_traspaso,
                'estado': traspaso.estado.nombre if traspaso.estado else 'Sin estado',
                'almacen_origen': traspaso.almacen_origen.nombre,
                'almacen_destino': traspaso.almacen_destino.nombre,
                'cantidad_enviada': traspaso.cantidad_enviada,
                'cantidad_recibida': traspaso.cantidad_recibida
            },
            'materiales': serializer.data
        })

    @action(detail=True, methods=['get'])
    def seguimiento(self, request, pk=None):
        """Seguimiento detallado del traspaso"""
        traspaso = self.get_object()

        seguimiento = {
            'traspaso_info': {
                'numero': traspaso.numero_traspaso,
                'estado_actual': traspaso.estado.nombre if traspaso.estado else 'Sin estado',
                'progreso': self._calcular_progreso_traspaso(traspaso)
            },
            'cronologia': [
                {
                    'fecha': traspaso.created_at,
                    'evento': 'Traspaso creado',
                    'usuario': traspaso.usuario_envio.nombre_completo if traspaso.usuario_envio else 'Sistema',
                    'observaciones': 'Traspaso registrado en el sistema'
                }
            ]
        }

        if traspaso.fecha_envio:
            seguimiento['cronologia'].append({
                'fecha': traspaso.fecha_envio,
                'evento': 'Enviado',
                'usuario': traspaso.usuario_envio.nombre_completo if traspaso.usuario_envio else 'Sistema',
                'observaciones': traspaso.observaciones_envio or 'Sin observaciones'
            })

        if traspaso.fecha_recepcion:
            seguimiento['cronologia'].append({
                'fecha': traspaso.fecha_recepcion,
                'evento': 'Recibido',
                'usuario': traspaso.usuario_recepcion.nombre_completo if traspaso.usuario_recepcion else 'Sistema',
                'observaciones': traspaso.observaciones_recepcion or 'Sin observaciones'
            })

        # Ordenar cronología por fecha
        seguimiento['cronologia'].sort(key=lambda x: x['fecha'])

        return Response(seguimiento)

    def _calcular_progreso_traspaso(self, traspaso):
        """Calcular porcentaje de progreso del traspaso"""
        try:
            estado_pendiente = EstadoTraspaso.objects.get(codigo='PENDIENTE', activo=True)
            estado_transito = EstadoTraspaso.objects.get(codigo='EN_TRANSITO', activo=True)
            estado_recibido = EstadoTraspaso.objects.get(codigo='RECIBIDO', activo=True)
            estado_cancelado = EstadoTraspaso.objects.get(codigo='CANCELADO', activo=True)

            if traspaso.estado == estado_pendiente:
                return 25
            elif traspaso.estado == estado_transito:
                return 50
            elif traspaso.estado == estado_recibido:
                return 100
            elif traspaso.estado == estado_cancelado:
                return 0
            else:
                return 0
        except EstadoTraspaso.DoesNotExist:
            return 0

    @action(detail=False, methods=['get'])
    def estadisticas(self, request):
        """Estadísticas completas de traspasos"""
        # Por estado usando el nuevo modelo
        por_estado = {}
        estados = EstadoTraspaso.objects.filter(activo=True)
        for estado in estados:
            count = TraspasoAlmacen.objects.filter(estado=estado).count()
            por_estado[estado.nombre] = count

        # Traspasos por almacén (como origen)
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

        # Estadísticas por período
        hoy = timezone.now().date()
        hace_30_dias = hoy - timedelta(days=30)
        hace_7_dias = hoy - timedelta(days=7)

        traspasos_mes = TraspasoAlmacen.objects.filter(created_at__date__gte=hace_30_dias).count()
        traspasos_semana = TraspasoAlmacen.objects.filter(created_at__date__gte=hace_7_dias).count()

        # Eficiencia (% de traspasos completados)
        total_traspasos = TraspasoAlmacen.objects.count()
        completados = traspasos_completados.count()
        eficiencia = (completados / total_traspasos * 100) if total_traspasos > 0 else 0

        return Response({
            'totales': {
                'total_traspasos': total_traspasos,
                'pendientes': pendientes,
                'en_transito': en_transito,
                'completados': completados,
                'eficiencia_pct': round(eficiencia, 2)
            },
            'por_estado': por_estado,
            'por_almacen_origen': list(por_almacen_origen),
            'por_almacen_destino': list(por_almacen_destino),
            'tiempo_promedio_dias': tiempo_promedio_dias,
            'periodo': {
                'traspasos_mes': traspasos_mes,
                'traspasos_semana': traspasos_semana
            }
        })

    @action(detail=False, methods=['get'])
    def resumen_almacen(self, request):
        """Resumen de traspasos por almacén específico"""
        almacen_id = request.query_params.get('almacen_id')

        if not almacen_id:
            return Response(
                {'error': 'ID de almacén requerido'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Traspasos de salida
        salidas = TraspasoAlmacen.objects.filter(almacen_origen_id=almacen_id)
        # Traspasos de entrada
        entradas = TraspasoAlmacen.objects.filter(almacen_destino_id=almacen_id)

        return Response({
            'almacen_id': almacen_id,
            'salidas': {
                'total': salidas.count(),
                'pendientes': salidas.filter(estado__codigo='PENDIENTE').count(),
                'en_transito': salidas.filter(estado__codigo='EN_TRANSITO').count(),
                'completados': salidas.filter(estado__codigo='RECIBIDO').count()
            },
            'entradas': {
                'total': entradas.count(),
                'pendientes': entradas.filter(estado__codigo='PENDIENTE').count(),
                'en_transito': entradas.filter(estado__codigo='EN_TRANSITO').count(),
                'completados': entradas.filter(estado__codigo='RECIBIDO').count()
            }
        })

    @action(detail=False, methods=['get'])
    def alertas(self, request):
        """Alertas de traspasos que requieren atención"""
        alertas = []

        try:
            # Traspasos pendientes por más de 3 días
            hace_3_dias = timezone.now() - timedelta(days=3)
            estado_pendiente = EstadoTraspaso.objects.get(codigo='PENDIENTE', activo=True)

            traspasos_atrasados = TraspasoAlmacen.objects.filter(
                estado=estado_pendiente,
                created_at__lt=hace_3_dias
            )

            if traspasos_atrasados.exists():
                alertas.append({
                    'tipo': 'TRASPASOS_PENDIENTES_ATRASADOS',
                    'cantidad': traspasos_atrasados.count(),
                    'mensaje': f'{traspasos_atrasados.count()} traspasos pendientes por más de 3 días',
                    'prioridad': 'alta'
                })

            # Traspasos en tránsito por más de 7 días
            hace_7_dias = timezone.now() - timedelta(days=7)
            estado_transito = EstadoTraspaso.objects.get(codigo='EN_TRANSITO', activo=True)

            traspasos_transito_largos = TraspasoAlmacen.objects.filter(
                estado=estado_transito,
                fecha_envio__lt=hace_7_dias
            )

            if traspasos_transito_largos.exists():
                alertas.append({
                    'tipo': 'TRASPASOS_TRANSITO_LARGOS',
                    'cantidad': traspasos_transito_largos.count(),
                    'mensaje': f'{traspasos_transito_largos.count()} traspasos en tránsito por más de 7 días',
                    'prioridad': 'media'
                })

        except EstadoTraspaso.DoesNotExist:
            pass

        return Response({
            'alertas': alertas,
            'total_alertas': len(alertas)
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

    def get_queryset(self):
        """Filtros adicionales"""
        queryset = super().get_queryset()

        # Filtro por devoluciones pendientes
        pendientes = self.request.query_params.get('pendientes')
        if pendientes == 'true':
            try:
                estado_pendiente = EstadoDevolucion.objects.get(codigo='PENDIENTE', activo=True)
                queryset = queryset.filter(estado=estado_pendiente)
            except EstadoDevolucion.DoesNotExist:
                queryset = queryset.none()

        # Filtro por devoluciones sin respuesta
        sin_respuesta = self.request.query_params.get('sin_respuesta')
        if sin_respuesta == 'true':
            try:
                estado_enviado = EstadoDevolucion.objects.get(codigo='ENVIADO', activo=True)
                queryset = queryset.filter(estado=estado_enviado, respuesta_proveedor__isnull=True)
            except EstadoDevolucion.DoesNotExist:
                queryset = queryset.none()

        # Filtro por mis devoluciones
        mis_devoluciones = self.request.query_params.get('mis_devoluciones')
        if mis_devoluciones == 'true':
            queryset = queryset.filter(created_by=self.request.user)

        return queryset

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

        observaciones_envio = request.data.get('observaciones', '')

        with transaction.atomic():
            devolucion.estado = estado_enviado
            devolucion.fecha_envio = timezone.now()
            if observaciones_envio:
                devolucion.observaciones_proveedor = observaciones_envio
            devolucion.save()

            # Actualizar estado de materiales devueltos
            for devolucion_material in devolucion.materiales_devueltos.all():
                material = devolucion_material.material
                estado_anterior = material.estado_display

                if material.tipo_material.es_unico:
                    material.estado_onu = estado_devuelto_onu
                else:
                    material.estado_general = estado_baja_general
                material.save()

                # Crear entrada en historial
                HistorialMaterial.objects.create(
                    material=material,
                    estado_anterior=estado_anterior,
                    estado_nuevo=material.estado_display,
                    almacen_anterior=material.almacen_actual,
                    almacen_nuevo=material.almacen_actual,
                    motivo=f'Devolución enviada: {devolucion.numero_devolucion}',
                    observaciones=f'Enviado a proveedor {devolucion.proveedor.nombre_comercial}',
                    devolucion_relacionada=devolucion,
                    usuario_responsable=request.user
                )

        return Response({
            'message': f'Devolución {devolucion.numero_devolucion} enviada al proveedor',
            'fecha_envio': devolucion.fecha_envio,
            'proveedor': devolucion.proveedor.nombre_comercial
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
            devolucion.observaciones_proveedor = observaciones
            devolucion.fecha_confirmacion = timezone.now()
            devolucion.save()

            # Si la respuesta es reposición, marcar para reingresar
            if respuesta.codigo == 'REPOSICION':
                # Aquí se podría crear un nuevo lote de reingreso automáticamente
                # o marcar los materiales para seguimiento especial
                pass

        return Response({
            'message': f'Respuesta del proveedor confirmada para devolución {devolucion.numero_devolucion}',
            'respuesta': respuesta.nombre,
            'fecha_confirmacion': devolucion.fecha_confirmacion
        })

    @action(detail=True, methods=['post'])
    def rechazar(self, request, pk=None):
        """Rechazar devolución"""
        devolucion = self.get_object()

        try:
            estado_pendiente = EstadoDevolucion.objects.get(codigo='PENDIENTE', activo=True)
            estado_rechazado = EstadoDevolucion.objects.get(codigo='RECHAZADO', activo=True)
        except EstadoDevolucion.DoesNotExist:
            return Response(
                {'error': 'Estados de devolución no configurados correctamente'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        if devolucion.estado != estado_pendiente:
            return Response(
                {'error': 'Solo se pueden rechazar devoluciones pendientes'},
                status=status.HTTP_400_BAD_REQUEST
            )

        motivo_rechazo = request.data.get('motivo', 'Sin especificar')

        with transaction.atomic():
            devolucion.estado = estado_rechazado
            devolucion.observaciones_proveedor = f"RECHAZADO: {motivo_rechazo}"
            devolucion.save()

            # Revertir estado de materiales si es necesario
            # (esto depende de la lógica de negocio específica)

        return Response({
            'message': f'Devolución {devolucion.numero_devolucion} rechazada',
            'motivo': motivo_rechazo
        })

    @action(detail=True, methods=['get'])
    def materiales_detalle(self, request, pk=None):
        """Obtener detalle de materiales en la devolución"""
        devolucion = self.get_object()
        materiales = devolucion.materiales_devueltos.all().select_related('material__modelo__marca')

        serializer = DevolucionMaterialSerializer(materiales, many=True)
        return Response({
            'devolucion': {
                'numero': devolucion.numero_devolucion,
                'estado': devolucion.estado.nombre if devolucion.estado else 'Sin estado',
                'proveedor': devolucion.proveedor.nombre_comercial,
                'motivo': devolucion.motivo,
                'fecha_creacion': devolucion.fecha_creacion
            },
            'materiales': serializer.data
        })

    @action(detail=True, methods=['get'])
    def seguimiento(self, request, pk=None):
        """Seguimiento detallado de la devolución"""
        devolucion = self.get_object()

        seguimiento = {
            'devolucion_info': {
                'numero': devolucion.numero_devolucion,
                'estado_actual': devolucion.estado.nombre if devolucion.estado else 'Sin estado',
                'proveedor': devolucion.proveedor.nombre_comercial,
                'cantidad_materiales': devolucion.cantidad_materiales
            },
            'cronologia': [
                {
                    'fecha': devolucion.fecha_creacion,
                    'evento': 'Devolución creada',
                    'usuario': devolucion.created_by.nombre_completo if devolucion.created_by else 'Sistema',
                    'observaciones': devolucion.motivo
                }
            ]
        }

        if devolucion.fecha_envio:
            seguimiento['cronologia'].append({
                'fecha': devolucion.fecha_envio,
                'evento': 'Enviado al proveedor',
                'usuario': 'Sistema',
                'observaciones': 'Devolución enviada al proveedor'
            })

        if devolucion.fecha_confirmacion:
            seguimiento['cronologia'].append({
                'fecha': devolucion.fecha_confirmacion,
                'evento': 'Respuesta confirmada',
                'usuario': 'Sistema',
                'observaciones': f'Respuesta: {devolucion.respuesta_proveedor.nombre if devolucion.respuesta_proveedor else "Sin respuesta"}'
            })

        # Ordenar cronología por fecha
        seguimiento['cronologia'].sort(key=lambda x: x['fecha'])

        return Response(seguimiento)

    @action(detail=False, methods=['get'])
    def estadisticas(self, request):
        """Estadísticas completas de devoluciones"""
        # Por estado usando el nuevo modelo
        por_estado = {}
        estados = EstadoDevolucion.objects.filter(activo=True)
        for estado in estados:
            count = DevolucionProveedor.objects.filter(estado=estado).count()
            por_estado[estado.nombre] = count

        # Por respuesta de proveedor
        por_respuesta = {}
        respuestas = RespuestaProveedor.objects.filter(activo=True)
        for respuesta in respuestas:
            count = DevolucionProveedor.objects.filter(respuesta_proveedor=respuesta).count()
            por_respuesta[respuesta.nombre] = count

        # Devoluciones por proveedor
        por_proveedor = DevolucionProveedor.objects.values(
            'proveedor__nombre_comercial'
        ).annotate(
            total_devoluciones=Count('id')
        ).order_by('-total_devoluciones')[:10]

        # Tiempo promedio de respuesta del proveedor
        devoluciones_confirmadas = DevolucionProveedor.objects.filter(
            fecha_confirmacion__isnull=False,
            fecha_envio__isnull=False
        )

        tiempo_promedio_respuesta = 0
        if devoluciones_confirmadas.exists():
            tiempos = []
            for devolucion in devoluciones_confirmadas:
                tiempo = (devolucion.fecha_confirmacion - devolucion.fecha_envio).days
                tiempos.append(tiempo)

            if tiempos:
                tiempo_promedio_respuesta = sum(tiempos) / len(tiempos)

        # Contadores específicos
        try:
            pendientes = DevolucionProveedor.objects.filter(
                estado=EstadoDevolucion.objects.get(codigo='PENDIENTE', activo=True)
            ).count()
            enviadas = DevolucionProveedor.objects.filter(
                estado=EstadoDevolucion.objects.get(codigo='ENVIADO', activo=True)
            ).count()
        except EstadoDevolucion.DoesNotExist:
            pendientes = 0
            enviadas = 0

        # Estadísticas por período
        hoy = timezone.now().date()
        hace_30_dias = hoy - timedelta(days=30)
        hace_7_dias = hoy - timedelta(days=7)

        devoluciones_mes = DevolucionProveedor.objects.filter(fecha_creacion__date__gte=hace_30_dias).count()
        devoluciones_semana = DevolucionProveedor.objects.filter(fecha_creacion__date__gte=hace_7_dias).count()

        return Response({
            'totales': {
                'total_devoluciones': DevolucionProveedor.objects.count(),
                'pendientes': pendientes,
                'enviadas_sin_respuesta': enviadas,
                'tiempo_promedio_respuesta_dias': round(tiempo_promedio_respuesta, 1)
            },
            'por_estado': por_estado,
            'por_respuesta_proveedor': por_respuesta,
            'por_proveedor': list(por_proveedor),
            'periodo': {
                'devoluciones_mes': devoluciones_mes,
                'devoluciones_semana': devoluciones_semana
            }
        })

    @action(detail=False, methods=['get'])
    def resumen_mensual(self, request):
        """Resumen mensual de devoluciones"""
        # Último mes
        fecha_inicio = datetime.now().date() - timedelta(days=30)

        devoluciones_mes = DevolucionProveedor.objects.filter(
            fecha_creacion__date__gte=fecha_inicio
        )

        # Agrupado por día
        por_dia = devoluciones_mes.extra(
            select={'dia': 'DATE(fecha_creacion)'}
        ).values('dia').annotate(
            total=Count('id')
        ).order_by('dia')

        # Motivos más comunes
        motivos_comunes = devoluciones_mes.values(
            'motivo'
        ).annotate(
            count=Count('id')
        ).order_by('-count')[:5]

        # Análisis por proveedor
        analisis_proveedores = []
        proveedores_con_devoluciones = devoluciones_mes.values(
            'proveedor__nombre_comercial'
        ).annotate(
            total=Count('id'),
            materiales_total=Count('materiales_devueltos')
        ).order_by('-total')[:10]

        for proveedor_data in proveedores_con_devoluciones:
            analisis_proveedores.append({
                'proveedor': proveedor_data['proveedor__nombre_comercial'],
                'total_devoluciones': proveedor_data['total'],
                'total_materiales': proveedor_data['materiales_total'],
                'promedio_materiales_por_devolucion': round(
                    proveedor_data['materiales_total'] / proveedor_data['total'], 2
                ) if proveedor_data['total'] > 0 else 0
            })

        return Response({
            'periodo': f'Últimos 30 días desde {fecha_inicio}',
            'resumen': {
                'total_mes': devoluciones_mes.count(),
                'promedio_diario': round(devoluciones_mes.count() / 30, 2)
            },
            'por_dia': list(por_dia),
            'motivos_mas_comunes': list(motivos_comunes),
            'analisis_proveedores': analisis_proveedores
        })

    @action(detail=False, methods=['get'])
    def alertas(self, request):
        """Alertas de devoluciones que requieren atención"""
        alertas = []

        try:
            # Devoluciones pendientes por más de 5 días
            hace_5_dias = timezone.now() - timedelta(days=5)
            estado_pendiente = EstadoDevolucion.objects.get(codigo='PENDIENTE', activo=True)

            devoluciones_atrasadas = DevolucionProveedor.objects.filter(
                estado=estado_pendiente,
                fecha_creacion__lt=hace_5_dias
            )

            if devoluciones_atrasadas.exists():
                alertas.append({
                    'tipo': 'DEVOLUCIONES_PENDIENTES_ATRASADAS',
                    'cantidad': devoluciones_atrasadas.count(),
                    'mensaje': f'{devoluciones_atrasadas.count()} devoluciones pendientes por más de 5 días',
                    'prioridad': 'alta'
                })

            # Devoluciones enviadas sin respuesta por más de 15 días
            hace_15_dias = timezone.now() - timedelta(days=15)
            estado_enviado = EstadoDevolucion.objects.get(codigo='ENVIADO', activo=True)

            sin_respuesta_largos = DevolucionProveedor.objects.filter(
                estado=estado_enviado,
                fecha_envio__lt=hace_15_dias,
                respuesta_proveedor__isnull=True
            )

            if sin_respuesta_largos.exists():
                alertas.append({
                    'tipo': 'DEVOLUCIONES_SIN_RESPUESTA_LARGAS',
                    'cantidad': sin_respuesta_largos.count(),
                    'mensaje': f'{sin_respuesta_largos.count()} devoluciones sin respuesta por más de 15 días',
                    'prioridad': 'media'
                })

        except EstadoDevolucion.DoesNotExist:
            pass

        return Response({
            'alertas': alertas,
            'total_alertas': len(alertas)
        })