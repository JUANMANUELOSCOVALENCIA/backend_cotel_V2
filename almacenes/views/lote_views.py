# ======================================================
# almacenes/views/lote_views.py - ACTUALIZADO COMPLETO
# Views para gestión de lotes y importación masiva
# ======================================================
import pandas as pd
import re
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.db.models import Max, Sum
from django.db.models import Count, F, Q
from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
from django_filters.rest_framework import DjangoFilterBackend

from usuarios.permissions import GenericRolePermission
from ..models import (
    Lote, LoteDetalle, EntregaParcialLote, Material, Almacen,
    TipoIngreso, EstadoLote, TipoMaterial, EstadoMaterialONU, Modelo,
    EntregaParcialLote, generar_numero_lote, EstadoMaterialGeneral
)
from ..serializers import (
    LoteSerializer, LoteCreateSerializer, LoteDetalleSerializer,
    EntregaParcialLoteSerializer,
    MaterialListSerializer, ImportacionMasivaSerializer
)


class LoteViewSet(viewsets.ModelViewSet):
    """ViewSet para gestión completa de lotes"""
    queryset = Lote.objects.all().select_related(
        'proveedor', 'almacen_destino', 'tipo_servicio', 'created_by',
        'tipo_ingreso', 'estado'
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
    def info_importacion(self, request, pk=None):
        """Información del lote para modal de importación masiva"""
        lote = self.get_object()

        # Verificar si el lote permite más importaciones
        try:
            estado_cerrado = EstadoLote.objects.get(codigo='CERRADO', activo=True)
            if lote.estado == estado_cerrado:
                return Response(
                    {'error': 'El lote está cerrado y no permite más importaciones'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        except EstadoLote.DoesNotExist:
            pass

        # Obtener entregas parciales ordenadas
        entregas_parciales = lote.entregas_parciales.all().order_by('numero_entrega')

        # Calcular estadísticas
        cantidad_total = lote.cantidad_total
        cantidad_recibida = lote.cantidad_recibida
        cantidad_pendiente = lote.cantidad_pendiente

        # Información de la próxima entrega
        proxima_entrega = lote.total_entregas_parciales + 1

        # Verificar si el lote es de recepción completa o parcial
        tiene_entregas_parciales = lote.total_entregas_parciales > 0

        # Obtener modelos disponibles en este lote
        modelos_lote = []
        for detalle in lote.detalles.all():
            modelos_lote.append({
                'id': detalle.modelo.id,
                'nombre': f"{detalle.modelo.marca.nombre} {detalle.modelo.nombre}",
                'codigo_modelo': detalle.modelo.codigo_modelo,
                'cantidad_esperada': detalle.cantidad,
                'cantidad_recibida': detalle.cantidad_recibida,
                'cantidad_pendiente': detalle.cantidad_pendiente,
                'tipo_material': {
                    'codigo': detalle.modelo.tipo_material.codigo,
                    'nombre': detalle.modelo.tipo_material.nombre,
                    'es_unico': detalle.modelo.tipo_material.es_unico
                }
            })

        return Response({
            'lote': {
                'id': lote.id,
                'numero_lote': lote.numero_lote,
                'proveedor': lote.proveedor.nombre_comercial,
                'estado': {
                    'id': lote.estado.id,
                    'codigo': lote.estado.codigo,
                    'nombre': lote.estado.nombre,
                    'color': lote.estado.color
                } if lote.estado else None,
                'almacen_destino': {
                    'id': lote.almacen_destino.id,
                    'codigo': lote.almacen_destino.codigo,
                    'nombre': lote.almacen_destino.nombre
                },
                'tipo_ingreso': {
                    'id': lote.tipo_ingreso.id,
                    'codigo': lote.tipo_ingreso.codigo,
                    'nombre': lote.tipo_ingreso.nombre
                } if lote.tipo_ingreso else None,
                'fecha_recepcion': lote.fecha_recepcion,
                'modelos_disponibles': modelos_lote
            },
            'estadisticas': {
                'cantidad_total': cantidad_total,
                'cantidad_recibida': cantidad_recibida,
                'cantidad_pendiente': cantidad_pendiente,
                'porcentaje_recibido': lote.porcentaje_recibido,
                'tiene_entregas_parciales': tiene_entregas_parciales
            },
            'entregas_parciales': {
                'lista': EntregaParcialLoteSerializer(entregas_parciales, many=True).data,
                'total': lote.total_entregas_parciales,
                'proxima_entrega': proxima_entrega,
                'permite_nueva_entrega': cantidad_pendiente > 0
            },
            'configuracion_importacion': {
                'requiere_numero_entrega': tiene_entregas_parciales or cantidad_pendiente < cantidad_total,
                'entrega_sugerida': proxima_entrega if cantidad_pendiente > 0 else None,
                'permite_importacion': cantidad_pendiente > 0,
                'es_lote_nuevo': lote.tipo_ingreso.codigo == 'NUEVO' if lote.tipo_ingreso else False
            }
        })

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
            if detalle.modelo.tipo_material.es_unico:
                estados_onu = EstadoMaterialONU.objects.filter(activo=True)
                for estado in estados_onu:
                    count = materiales_del_modelo.filter(estado_onu=estado).count()
                    if count > 0:
                        estados_info[estado.nombre] = count

            detalles_info.append({
                'modelo_id': detalle.modelo.id,
                'modelo_nombre': f"{detalle.modelo.marca.nombre} {detalle.modelo.nombre}",
                'codigo_modelo': detalle.modelo.codigo_modelo,
                'tipo_material': detalle.modelo.tipo_material.nombre if detalle.modelo.tipo_material else 'Sin tipo',
                'unidad_medida': detalle.modelo.unidad_medida.simbolo if detalle.modelo.unidad_medida else 'N/A',
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
                'tipo_ingreso': lote.tipo_ingreso.nombre if lote.tipo_ingreso else 'Sin tipo',
                'estado': lote.estado.nombre if lote.estado else 'Sin estado',
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

    @action(detail=True, methods=['get'])
    def entregas_parciales(self, request, pk=None):
        """Obtener entregas parciales de un lote"""
        lote = self.get_object()
        entregas = lote.entregas_parciales.all().order_by('numero_entrega')

        serializer = EntregaParcialLoteSerializer(entregas, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def agregar_entrega_parcial(self, request, pk=None):
        """Agregar una nueva entrega parcial al lote"""
        lote = self.get_object()

        try:
            estado_cerrado = EstadoLote.objects.get(codigo='CERRADO', activo=True)
            if lote.estado == estado_cerrado:
                return Response(
                    {'error': 'No se pueden agregar entregas a un lote cerrado'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        except EstadoLote.DoesNotExist:
            pass

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
                try:
                    if lote.cantidad_recibida >= lote.cantidad_total:
                        estado_completa = EstadoLote.objects.get(codigo='RECEPCION_COMPLETA', activo=True)
                        lote.estado = estado_completa
                    else:
                        estado_parcial = EstadoLote.objects.get(codigo='RECEPCION_PARCIAL', activo=True)
                        lote.estado = estado_parcial
                except EstadoLote.DoesNotExist:
                    pass

                lote.save()

            return Response(
                EntregaParcialLoteSerializer(entrega).data,
                status=status.HTTP_201_CREATED
            )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['get'], url_path='entregas_parciales_disponibles')
    def entregas_parciales_disponibles(self, request, pk=None):
        """Obtener entregas parciales disponibles para importación"""
        lote = self.get_object()

        # Obtener entregas con información de materiales asociados
        entregas = EntregaParcialLote.objects.filter(
            lote=lote
        ).annotate(
            materiales_count=Count('lote__material', filter=Q(
                lote__material__numero_entrega_parcial=F('numero_entrega')
            ))
        ).order_by('numero_entrega')

        entregas_data = []
        for entrega in entregas:
            equipos_restantes = entrega.cantidad_entregada - entrega.materiales_count

            entregas_data.append({
                'id': entrega.id,
                'numero_entrega': entrega.numero_entrega,
                'cantidad_entregada': entrega.cantidad_entregada,
                'materiales_count': entrega.materiales_count,
                'equipos_restantes': equipos_restantes,
                'fecha_entrega': entrega.fecha_entrega,
                'observaciones': entrega.observaciones,
                'puede_recibir_equipos': equipos_restantes > 0,
                'estado': entrega.estado_entrega.nombre if entrega.estado_entrega else None
            })

        return Response({
            'entregas': entregas_data,
            'total_entregas': len(entregas_data)
        })

    @action(detail=True, methods=['delete'], url_path='eliminar')
    def eliminar(self, request, pk=None):
        """Eliminar una entrega parcial específica con opciones para materiales"""
        lote = self.get_object()

        entrega_id = request.query_params.get('entrega_id')
        force = request.query_params.get('force', 'false').lower() == 'true'
        delete_materials = request.query_params.get('delete_materials', 'false').lower() == 'true'

        if not entrega_id:
            return Response(
                {'error': 'Se requiere el ID de la entrega parcial'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            entrega = EntregaParcialLote.objects.get(id=entrega_id, lote=lote)
        except EntregaParcialLote.DoesNotExist:
            return Response(
                {'error': 'Entrega parcial no encontrada'},
                status=status.HTTP_404_NOT_FOUND
            )

        # Verificar que el lote no esté cerrado
        try:
            estado_cerrado = EstadoLote.objects.get(codigo='CERRADO', activo=True)
            if lote.estado == estado_cerrado:
                return Response(
                    {'error': 'No se pueden eliminar entregas de un lote cerrado'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        except EstadoLote.DoesNotExist:
            pass

        # Verificar materiales asociados
        materiales_asociados = Material.objects.filter(
            lote=lote,
            numero_entrega_parcial=entrega.numero_entrega
        )

        materiales_count = materiales_asociados.count()

        # Si tiene materiales y no se fuerza, devolver información para confirmación
        if materiales_count > 0 and not force:
            # Obtener muestra de materiales para mostrar al usuario
            materiales_muestra = list(materiales_asociados[:5].values(
                'id', 'codigo_interno', 'mac_address', 'gpon_serial', 'serial_manufacturer'
            ))

            return Response(
                {
                    'requires_confirmation': True,
                    'entrega_info': {
                        'id': entrega.id,
                        'numero_entrega': entrega.numero_entrega,
                        'fecha_entrega': entrega.fecha_entrega,
                        'cantidad_entregada': entrega.cantidad_entregada,
                        'observaciones': entrega.observaciones,
                        'created_by_nombre': entrega.created_by.nombre_completo if entrega.created_by else 'Sistema'
                    },
                    'materiales_info': {
                        'total_count': materiales_count,
                        'muestra': materiales_muestra,
                        'warning': f'Esta entrega tiene {materiales_count} materiales asociados'
                    },
                    'opciones': {
                        'desasociar': {
                            'descripcion': 'Eliminar solo la entrega, mantener materiales en el lote',
                            'accion': 'Los materiales permanecerán en el lote pero sin número de entrega',
                            'url': f'/almacenes/lotes/{lote.id}/eliminar/?entrega_id={entrega_id}&force=true'
                        },
                        'eliminar_todo': {
                            'descripcion': 'Eliminar la entrega Y todos los materiales asociados',
                            'accion': f'Se eliminarán permanentemente {materiales_count} materiales del sistema',
                            'url': f'/almacenes/lotes/{lote.id}/eliminar/?entrega_id={entrega_id}&force=true&delete_materials=true',
                            'warning': 'Esta acción eliminará completamente los equipos del sistema'
                        }
                    }
                },
                status=status.HTTP_409_CONFLICT
            )

        # Verificar permisos
        if not (request.user.is_superuser or
                entrega.created_by == request.user or
                request.user.tiene_permiso('lotes', 'eliminar')):
            return Response(
                {'error': 'No tienes permisos para eliminar esta entrega'},
                status=status.HTTP_403_FORBIDDEN
            )

        # Proceder con la eliminación
        with transaction.atomic():
            numero_entrega_eliminada = entrega.numero_entrega
            materiales_eliminados = 0

            print(f"🗑️ BACKEND: Eliminando entrega #{numero_entrega_eliminada}")
            print(f"🗑️ BACKEND: delete_materials={delete_materials}, materiales_count={materiales_count}")

            if materiales_count > 0:
                if delete_materials:
                    # Opción 1: Eliminar completamente los materiales
                    print(f"🗑️ BACKEND: Eliminando {materiales_count} materiales del sistema")

                    # Verificar si los materiales tienen dependencias
                    materiales_con_dependencias = []
                    for material in materiales_asociados:
                        # Verificar si el material está en otros procesos (laboratorio, etc.)
                        if hasattr(material, 'enviado_laboratorio') and material.enviado_laboratorio:
                            materiales_con_dependencias.append(material.codigo_interno)

                    if materiales_con_dependencias and not request.user.is_superuser:
                        return Response(
                            {
                                'error': 'Algunos materiales no se pueden eliminar porque están en otros procesos',
                                'materiales_con_dependencias': materiales_con_dependencias[:10],
                                'solucion': 'Solo los administradores pueden forzar la eliminación de materiales con dependencias'
                            },
                            status=status.HTTP_400_BAD_REQUEST
                        )

                    # Eliminar materiales
                    materiales_eliminados = materiales_count
                    materiales_asociados.delete()
                    print(f"✅ BACKEND: {materiales_eliminados} materiales eliminados del sistema")

                else:
                    # Opción 2: Solo desasociar materiales (comportamiento anterior)
                    materiales_asociados.update(numero_entrega_parcial=None)
                    print(f"🔄 BACKEND: {materiales_count} materiales desasociados")

            # Eliminar la entrega
            entrega.delete()

            # Reordenar números de entregas posteriores
            entregas_posteriores = EntregaParcialLote.objects.filter(
                lote=lote,
                numero_entrega__gt=numero_entrega_eliminada
            ).order_by('numero_entrega')

            print(f"🔄 BACKEND: Reordenando {len(entregas_posteriores)} entregas posteriores")

            for entrega_posterior in entregas_posteriores:
                nuevo_numero = entrega_posterior.numero_entrega - 1
                entrega_posterior.numero_entrega = nuevo_numero
                entrega_posterior.save()

                # Actualizar materiales de entregas posteriores (solo si no se eliminaron)
                if not delete_materials:
                    Material.objects.filter(
                        lote=lote,
                        numero_entrega_parcial=entrega_posterior.numero_entrega + 1
                    ).update(numero_entrega_parcial=nuevo_numero)

            # Actualizar contador del lote
            lote.total_entregas_parciales = max(0, lote.total_entregas_parciales - 1)

            # Actualizar estado del lote
            try:
                entregas_restantes = lote.entregas_parciales.count()
                if entregas_restantes == 0:
                    estado_registrado = EstadoLote.objects.get(codigo='REGISTRADO', activo=True)
                    lote.estado = estado_registrado
                else:
                    # Recalcular estado basado en entregas restantes
                    total_en_entregas = sum(e.cantidad_entregada for e in lote.entregas_parciales.all())
                    total_materiales_restantes = Material.objects.filter(lote=lote).count()

                    if total_materiales_restantes == 0:
                        estado_registrado = EstadoLote.objects.get(codigo='REGISTRADO', activo=True)
                        lote.estado = estado_registrado
                    elif total_en_entregas >= lote.cantidad_total:
                        estado_completa = EstadoLote.objects.get(codigo='RECEPCION_COMPLETA', activo=True)
                        lote.estado = estado_completa
                    else:
                        estado_parcial = EstadoLote.objects.get(codigo='RECEPCION_PARCIAL', activo=True)
                        lote.estado = estado_parcial
            except EstadoLote.DoesNotExist:
                pass

            lote.save()

            print(f"✅ BACKEND: Operación completada exitosamente")

        # Preparar mensaje de respuesta
        if delete_materials and materiales_eliminados > 0:
            message = f'Entrega #{numero_entrega_eliminada} y {materiales_eliminados} materiales eliminados completamente'
        elif materiales_count > 0:
            message = f'Entrega #{numero_entrega_eliminada} eliminada, {materiales_count} materiales desasociados'
        else:
            message = f'Entrega #{numero_entrega_eliminada} eliminada correctamente'

        return Response({
            'message': message,
            'entrega_eliminada': numero_entrega_eliminada,
            'materiales_desasociados': materiales_count if not delete_materials else 0,
            'materiales_eliminados': materiales_eliminados,
            'entregas_reordenadas': len(entregas_posteriores),
            'nuevo_estado_lote': lote.estado.nombre if lote.estado else 'Sin estado'
        })

    @action(detail=True, methods=['post'])
    def cerrar_lote(self, request, pk=None):
        """Cerrar lote (no se pueden agregar más materiales)"""
        lote = self.get_object()

        try:
            estado_cerrado = EstadoLote.objects.get(codigo='CERRADO', activo=True)
            if lote.estado == estado_cerrado:
                return Response(
                    {'error': 'El lote ya está cerrado'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        except EstadoLote.DoesNotExist:
            return Response(
                {'error': 'Estado CERRADO no configurado'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        with transaction.atomic():
            lote.estado = estado_cerrado
            lote.save()

        return Response({
            'message': f'Lote {lote.numero_lote} cerrado correctamente',
            'estado': lote.estado.nombre if lote.estado else 'Sin estado',
            'fecha_cierre': lote.updated_at
        })

    @action(detail=True, methods=['post'])
    def reabrir_lote(self, request, pk=None):
        """Reabrir lote cerrado (solo para administradores)"""
        lote = self.get_object()

        try:
            estado_cerrado = EstadoLote.objects.get(codigo='CERRADO', activo=True)
            estado_activo = EstadoLote.objects.get(codigo='ACTIVO', activo=True)

            if lote.estado != estado_cerrado:
                return Response(
                    {'error': 'Solo se pueden reabrir lotes cerrados'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        except EstadoLote.DoesNotExist:
            return Response(
                {'error': 'Estados de lote no configurados correctamente'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        if not request.user.is_superuser:
            return Response(
                {'error': 'Solo administradores pueden reabrir lotes'},
                status=status.HTTP_403_FORBIDDEN
            )

        with transaction.atomic():
            lote.estado = estado_activo
            lote.save()

        return Response({
            'message': f'Lote {lote.numero_lote} reabierto correctamente',
            'estado': lote.estado.nombre if lote.estado else 'Sin estado'
        })

    @action(detail=False, methods=['get'])
    def proximo_numero(self, request):
        """Obtener el próximo número de lote disponible"""
        try:
            proximo_numero = generar_numero_lote()
            return Response({
                'proximo_numero': proximo_numero,
                'mensaje': f'El próximo lote será: {proximo_numero}'
            })
        except Exception as e:
            return Response(
                {'error': f'Error al generar próximo número: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=True, methods=['get'])
    def materiales(self, request, pk=None):
        """Obtener todos los materiales del lote"""
        lote = self.get_object()
        materiales = lote.material_set.all()

        # Filtros opcionales
        tipo_material_codigo = request.query_params.get('tipo_material')
        estado = request.query_params.get('estado')
        modelo_id = request.query_params.get('modelo_id')

        if tipo_material_codigo:
            try:
                tipo_material = TipoMaterial.objects.get(codigo=tipo_material_codigo, activo=True)
                materiales = materiales.filter(tipo_material=tipo_material)
            except TipoMaterial.DoesNotExist:
                pass

        if estado:
            if tipo_material_codigo:
                try:
                    tipo_material = TipoMaterial.objects.get(codigo=tipo_material_codigo, activo=True)
                    if tipo_material.es_unico:
                        try:
                            estado_obj = EstadoMaterialONU.objects.get(codigo=estado, activo=True)
                            materiales = materiales.filter(estado_onu=estado_obj)
                        except EstadoMaterialONU.DoesNotExist:
                            pass
                    else:
                        try:
                            from ..models import EstadoMaterialGeneral
                            estado_obj = EstadoMaterialGeneral.objects.get(codigo=estado, activo=True)
                            materiales = materiales.filter(estado_general=estado_obj)
                        except:
                            pass
                except TipoMaterial.DoesNotExist:
                    pass

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

        try:
            tipo_nuevo = TipoIngreso.objects.get(codigo='NUEVO', activo=True)
            tipo_onu = TipoMaterial.objects.get(codigo='ONU', activo=True)
            estado_nuevo = EstadoMaterialONU.objects.get(codigo='NUEVO', activo=True)

            if lote.tipo_ingreso != tipo_nuevo:
                return Response(
                    {'error': 'Solo los lotes nuevos requieren inspección inicial'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        except (TipoIngreso.DoesNotExist, TipoMaterial.DoesNotExist, EstadoMaterialONU.DoesNotExist):
            return Response(
                {'error': 'Configuración de tipos y estados incompleta'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        # Filtrar materiales que requieren laboratorio
        materiales_nuevos = lote.material_set.filter(
            tipo_material=tipo_onu,
            es_nuevo=True,
            estado_onu=estado_nuevo
        )

        if not materiales_nuevos.exists():
            return Response(
                {'message': 'No hay materiales nuevos que requieran inspección'},
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
        estados = EstadoLote.objects.filter(activo=True)
        for estado in estados:
            count = Lote.objects.filter(estado=estado).count()
            por_estado[estado.nombre] = count

        # Lotes por tipo de ingreso
        por_tipo = {}
        tipos = TipoIngreso.objects.filter(activo=True)
        for tipo in tipos:
            count = Lote.objects.filter(tipo_ingreso=tipo).count()
            por_tipo[tipo.nombre] = count

        # Top proveedores por cantidad de lotes
        from django.db.models import Count
        top_proveedores = Lote.objects.values(
            'proveedor__nombre_comercial'
        ).annotate(
            total_lotes=Count('id')
        ).order_by('-total_lotes')[:10]

        # Lotes activos
        try:
            estado_activo = EstadoLote.objects.get(codigo='ACTIVO', activo=True)
            estado_parcial = EstadoLote.objects.get(codigo='RECEPCION_PARCIAL', activo=True)
            lotes_activos = Lote.objects.filter(estado__in=[estado_activo, estado_parcial]).count()
        except EstadoLote.DoesNotExist:
            lotes_activos = 0

        return Response({
            'total_lotes': Lote.objects.count(),
            'por_estado': por_estado,
            'por_tipo_ingreso': por_tipo,
            'top_proveedores': list(top_proveedores),
            'lotes_activos': lotes_activos
        })

    @action(detail=True, methods=['post'])
    def completar_recepcion(self, request, pk=None):
        """Auto-completar materiales no únicos según LoteDetalle"""
        lote = self.get_object()

        # Validar que no esté cerrado
        try:
            estado_cerrado = EstadoLote.objects.get(codigo='CERRADO', activo=True)
            if lote.estado == estado_cerrado:
                return Response({
                    'error': 'El lote está cerrado'
                }, status=status.HTTP_400_BAD_REQUEST)
        except EstadoLote.DoesNotExist:
            pass

        with transaction.atomic():
            materiales_creados = []

            for detalle in lote.detalles.all():
                # Solo procesar materiales NO únicos
                if not detalle.modelo.tipo_material.es_unico:
                    cantidad_pendiente = detalle.cantidad_pendiente

                    if cantidad_pendiente > 0:
                        # Crear material por cantidad
                        try:
                            estado_disponible = EstadoMaterialGeneral.objects.get(
                                codigo='DISPONIBLE', activo=True
                            )
                        except EstadoMaterialGeneral.DoesNotExist:
                            estado_disponible = None

                        material = Material.objects.create(
                            lote=lote,
                            modelo=detalle.modelo,
                            tipo_material=detalle.modelo.tipo_material,
                            almacen_actual=lote.almacen_destino,
                            cantidad=cantidad_pendiente,
                            codigo_item_equipo=request.data.get('codigo_item_equipo', ''),
                            estado_general=estado_disponible,
                            es_nuevo=lote.tipo_ingreso.codigo == 'NUEVO',
                            tipo_origen=lote.tipo_ingreso,
                            observaciones=f"Auto-completado: {cantidad_pendiente} {detalle.modelo.unidad_medida.simbolo if detalle.modelo.unidad_medida else 'unidades'}"
                        )
                        materiales_creados.append(material)

            return Response({
                'message': f'{len(materiales_creados)} materiales auto-completados',
                'materiales_creados': len(materiales_creados)
            })


# ======================================================
# almacenes/views/lote_views.py - ImportacionMasivaView COMPLETA
# ======================================================

class ImportacionMasivaView(APIView):
    """View para importación masiva de materiales desde Excel/CSV - SOPORTE DUAL"""
    permission_classes = [IsAuthenticated, GenericRolePermission]
    parser_classes = [MultiPartParser, FormParser]
    basename = 'lotes'

    def post(self, request, *args, **kwargs):
        """Procesar archivo de importación masiva - DETECCIÓN AUTOMÁTICA DE TIPO"""
        print("🔍 === INICIO IMPORTACION MASIVA DUAL ===")
        try:
            # Obtener parámetros
            lote_id = request.data.get('lote_id')
            modelo_id = request.data.get('modelo_id')
            archivo = request.FILES.get('archivo')
            numero_entrega = request.data.get('numero_entrega')
            entrega_seleccionada = request.data.get('entrega_seleccionada')
            es_validacion = request.data.get('validacion', 'false').lower() == 'true'

            print(f"🔍 DEBUG PARAMETROS RECIBIDOS:")
            print(f"   lote_id: '{lote_id}' (tipo: {type(lote_id)})")
            print(f"   modelo_id: '{modelo_id}' (tipo: {type(modelo_id)})")
            print(f"   archivo: {archivo.name if archivo else 'None'}")
            print(f"   numero_entrega: '{numero_entrega}' (tipo: {type(numero_entrega)})")
            print(f"   entrega_seleccionada: '{entrega_seleccionada}' (tipo: {type(entrega_seleccionada)})")
            print(f"   es_validacion: {es_validacion}")

            # Validar parámetros requeridos básicos
            if not all([lote_id, modelo_id, archivo]):
                print(f"❌ Faltan parámetros:")
                print(f"   lote_id presente: {bool(lote_id)}")
                print(f"   modelo_id presente: {bool(modelo_id)}")
                print(f"   archivo presente: {bool(archivo)}")
                return Response({
                    'success': False,
                    'error': 'Faltan parámetros requeridos: lote_id, modelo_id, archivo'
                }, status=status.HTTP_400_BAD_REQUEST)

            if entrega_seleccionada:
                numero_entrega = entrega_seleccionada
                print(f"   Usando entrega seleccionada: {numero_entrega}")

            # Validar que el lote y modelo existen
            try:
                lote = Lote.objects.get(id=lote_id)
                modelo = Modelo.objects.get(id=modelo_id)
                print(f"✅ Lote encontrado: {lote.numero_lote}")
                print(f"✅ Modelo encontrado: {modelo.nombre}")
            except (Lote.DoesNotExist, Modelo.DoesNotExist):
                return Response({
                    'success': False,
                    'error': 'Lote o modelo no encontrado'
                }, status=status.HTTP_404_NOT_FOUND)

            # ✅ DETECCIÓN AUTOMÁTICA DEL TIPO DE MATERIAL
            es_material_unico = modelo.tipo_material.es_unico
            print(f"🔍 TIPO DE MATERIAL DETECTADO:")
            print(f"   Modelo: {modelo.nombre}")
            print(f"   Tipo Material: {modelo.tipo_material.nombre} (código: {modelo.tipo_material.codigo})")
            print(f"   Es Único: {es_material_unico}")

            if es_material_unico:
                print("🔄 Procesando como MATERIAL ÚNICO (ONU)")
                return self._procesar_materiales_unicos(
                    request, lote, modelo, archivo, numero_entrega, es_validacion
                )
            else:
                print("🔄 Procesando como MATERIAL NO ÚNICO (cantidad)")
                return self._procesar_materiales_no_unicos(
                    request, lote, modelo, archivo, numero_entrega, es_validacion
                )

        except Exception as e:
            print(f"💥 ERROR GENERAL: {str(e)}")
            import traceback
            traceback.print_exc()
            return Response({
                'success': False,
                'error': f'Error interno: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        finally:
            print("🔍 === FIN IMPORTACION MASIVA DUAL ===")

    def _procesar_materiales_unicos(self, request, lote, modelo, archivo, numero_entrega, es_validacion):
        """Procesar materiales únicos (ONUs) - CÓDIGO ORIGINAL MEJORADO"""
        print("🔍 === PROCESANDO MATERIALES ÚNICOS (ONUs) ===")

        try:
            # Obtener ITEM_EQUIPO desde request
            item_equipo = request.data.get('item_equipo')
            item_equipo_str = str(item_equipo).strip() if item_equipo else ""
            print(f"🔍 ITEM_EQUIPO procesado: '{item_equipo_str}' (length: {len(item_equipo_str)})")

            # Validar formato ITEM_EQUIPO
            if not re.match(r'^\d{6,10}$', item_equipo_str):
                print(f"❌ ITEM_EQUIPO regex failed para: '{item_equipo_str}'")
                return Response({
                    'success': False,
                    'error': f'ITEM_EQUIPO debe tener entre 6 y 10 dígitos numéricos. Recibido: "{item_equipo_str}"'
                }, status=status.HTTP_400_BAD_REQUEST)

            print(f"✅ ITEM_EQUIPO válido: '{item_equipo_str}'")
            item_equipo = item_equipo_str

            # Verificar modelo Material
            print("🔍 Verificando modelo Material...")
            try:
                total_materiales_antes = Material.objects.count()
                materiales_lote_antes = Material.objects.filter(lote_id=lote.id).count()
                print(f"📊 Materiales en sistema: {total_materiales_antes}")
                print(f"📊 Materiales en lote {lote.id}: {materiales_lote_antes}")
            except Exception as e:
                print(f"❌ Error accediendo a Material: {e}")
                return Response({
                    'success': False,
                    'error': 'Error interno: modelos no disponibles'
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            # Procesar archivo
            try:
                if archivo.name.endswith('.csv'):
                    df = pd.read_csv(archivo)
                elif archivo.name.endswith('.xlsx'):
                    df = pd.read_excel(archivo)
                else:
                    return Response({
                        'success': False,
                        'error': 'Formato de archivo no soportado. Use CSV o Excel (.xlsx)'
                    }, status=status.HTTP_400_BAD_REQUEST)

                print(f"✅ Archivo leído: {len(df)} filas")
                print(f"📝 Columnas disponibles: {list(df.columns)}")

            except Exception as e:
                print(f"💥 Error leyendo archivo: {str(e)}")
                return Response({
                    'success': False,
                    'error': f'Error al leer archivo: {str(e)}'
                }, status=status.HTTP_400_BAD_REQUEST)

            # ✅ VALIDAR COLUMNAS - D_SN AHORA OPCIONAL
            columnas_requeridas = ['GPON_SN', 'MAC']
            columnas_opcionales = ['D_SN']

            columnas_faltantes = [col for col in columnas_requeridas if col not in df.columns]

            if columnas_faltantes:
                return Response({
                    'success': False,
                    'error': f'Columnas faltantes: {", ".join(columnas_faltantes)}. Requeridas: {", ".join(columnas_requeridas)}. Opcionales: {", ".join(columnas_opcionales)}'
                }, status=status.HTTP_400_BAD_REQUEST)

            print(f"✅ Columnas validadas. D_SN es opcional: {'D_SN' in df.columns}")

            # Validar tamaño del archivo
            if len(df) > 1000:
                return Response({
                    'success': False,
                    'error': 'El archivo no puede tener más de 1000 filas'
                }, status=status.HTTP_400_BAD_REQUEST)

            # ✅ PROCESAR DATOS CON SN OPCIONAL
            equipos_validos = []
            errores = []
            macs_duplicados = set()
            gpon_duplicados = set()
            dsn_duplicados = set()

            for index, row in df.iterrows():
                fila_num = index + 2
                errores_fila = []

                # ✅ EXTRAER DATOS - D_SN OPCIONAL
                mac = str(row['MAC']).strip().upper() if pd.notna(row['MAC']) else ''
                gpon_sn = str(row['GPON_SN']).strip() if pd.notna(row['GPON_SN']) else ''

                # D_SN opcional - puede no existir la columna o estar vacío
                d_sn = ''
                if 'D_SN' in df.columns and 'D_SN' in row and pd.notna(row['D_SN']):
                    d_sn = str(row['D_SN']).strip()

                # Crear datos del equipo
                equipo_data = {
                    'mac_address': mac,
                    'gpon_serial': gpon_sn,
                    'serial_manufacturer': d_sn,  # ✅ Puede estar vacío
                    'codigo_item_equipo': item_equipo,
                    'fila': fila_num
                }

                # ✅ VALIDACIONES CON FORMATOS MANTENIDOS

                # MAC Address - OBLIGATORIO con formato
                if not mac:
                    errores_fila.append('MAC Address es requerido')
                else:
                    # Validar formato MAC
                    mac_pattern = r'^([0-9A-F]{2}[:-]){5}([0-9A-F]{2})$'
                    if not re.match(mac_pattern, mac):
                        errores_fila.append('Formato de MAC inválido. Use XX:XX:XX:XX:XX:XX')
                    else:
                        # Normalizar MAC
                        mac = mac.replace('-', ':')
                        equipo_data['mac_address'] = mac

                        # Verificar duplicados en archivo
                        if mac in macs_duplicados:
                            errores_fila.append('MAC duplicada en el archivo')
                        else:
                            macs_duplicados.add(mac)

                # GPON Serial - OBLIGATORIO con formato
                if not gpon_sn:
                    errores_fila.append('GPON Serial es requerido')
                elif len(gpon_sn) < 8:
                    errores_fila.append('GPON Serial debe tener al menos 8 caracteres')
                else:
                    # Verificar duplicados en archivo
                    if gpon_sn in gpon_duplicados:
                        errores_fila.append('GPON Serial duplicado en el archivo')
                    else:
                        gpon_duplicados.add(gpon_sn)

                # ✅ D_SN - OPCIONAL con formato si se proporciona
                if d_sn:  # Solo validar si tiene valor
                    if len(d_sn) < 6:
                        errores_fila.append('D-SN debe tener al menos 6 caracteres si se proporciona')
                    else:
                        # Verificar duplicados en archivo
                        if d_sn in dsn_duplicados:
                            errores_fila.append('D-SN duplicado en el archivo')
                        else:
                            dsn_duplicados.add(d_sn)

                # ✅ VERIFICAR DUPLICADOS EN BASE DE DATOS (solo si no es validación)
                if not errores_fila and not es_validacion:
                    # MAC siempre verificar (obligatorio)
                    if Material.objects.filter(mac_address=mac).exists():
                        errores_fila.append('MAC ya existe en el sistema')

                    # GPON siempre verificar (obligatorio)
                    if Material.objects.filter(gpon_serial=gpon_sn).exists():
                        errores_fila.append('GPON Serial ya existe en el sistema')

                    # D_SN solo verificar si tiene valor
                    if d_sn and Material.objects.filter(serial_manufacturer=d_sn).exists():
                        errores_fila.append('D-SN ya existe en el sistema')

                # Registrar errores o equipos válidos
                if errores_fila:
                    errores.append({
                        'fila': fila_num,
                        'mac': mac,
                        'gpon': gpon_sn,
                        'd_sn': d_sn,
                        'errores': errores_fila
                    })
                else:
                    equipos_validos.append(equipo_data)

            # Preparar resultado
            resultado = {
                'total_filas': len(df),
                'validados': len(equipos_validos),
                'errores': len(errores),
                'item_equipo_aplicado': item_equipo,
                'numero_entrega': numero_entrega,
                'columna_d_sn_presente': 'D_SN' in df.columns,
                'tipo_material': 'UNICO'
            }

            print(f"📊 Procesamiento completado:")
            print(f"   Total filas: {len(df)}")
            print(f"   Equipos válidos: {len(equipos_validos)}")
            print(f"   Errores: {len(errores)}")

            # Si es solo validación, devolver preview
            if es_validacion:
                resultado.update({
                    'equipos_validos': equipos_validos[:5],  # Solo primeros 5 para preview
                    'detalles_errores': errores[:10]  # Solo primeros 10 errores
                })

                return Response({
                    'success': True,
                    'message': 'Validación completada',
                    'resultado': resultado
                })

            # Si no hay equipos válidos, devolver error
            if len(equipos_validos) == 0:
                return Response({
                    'success': False,
                    'error': 'No hay equipos válidos para importar',
                    'resultado': resultado,
                    'detalles_errores': errores[:20]  # Mostrar errores para debug
                }, status=status.HTTP_400_BAD_REQUEST)

            # ✅ VERIFICAR CAPACIDAD ANTES DE CREAR MATERIALES
            if len(equipos_validos) > 0 and not es_validacion and numero_entrega:
                try:
                    entrega_parcial = EntregaParcialLote.objects.get(
                        lote=lote,
                        numero_entrega=int(numero_entrega)
                    )

                    # Contar materiales EXISTENTES (antes de crear nuevos)
                    materiales_actuales = Material.objects.filter(
                        lote=lote,
                        numero_entrega_parcial=entrega_parcial.numero_entrega
                    ).count()

                    equipos_disponibles = entrega_parcial.cantidad_entregada - materiales_actuales
                    equipos_a_importar = len(equipos_validos)

                    print(f"🔍 VERIFICACION PREVIA:")
                    print(
                        f"   Entrega #{numero_entrega}: {materiales_actuales}/{entrega_parcial.cantidad_entregada} equipos")
                    print(f"   Capacidad disponible: {equipos_disponibles} equipos")
                    print(f"   Intentando importar: {equipos_a_importar} equipos")

                    if equipos_a_importar > equipos_disponibles:
                        return Response({
                            'success': False,
                            'error': f'La entrega #{numero_entrega} solo puede recibir {equipos_disponibles} equipos más. Intentando importar {equipos_a_importar}.',
                            'detalles': {
                                'entrega_numero': entrega_parcial.numero_entrega,
                                'cantidad_registrada': entrega_parcial.cantidad_entregada,
                                'equipos_actuales': materiales_actuales,
                                'capacidad_disponible': equipos_disponibles,
                                'intentando_importar': equipos_a_importar
                            }
                        }, status=status.HTTP_400_BAD_REQUEST)

                except EntregaParcialLote.DoesNotExist:
                    return Response({
                        'success': False,
                        'error': f'La entrega #{numero_entrega} no existe'
                    }, status=status.HTTP_404_NOT_FOUND)

            # ✅ PROCEDER CON LA IMPORTACIÓN REAL
            with transaction.atomic():
                importados = 0
                errores_importacion = []

                print(f"🔍 Iniciando importación de {len(equipos_validos)} equipos")

                # Obtener referencias necesarias
                try:
                    tipo_onu = TipoMaterial.objects.get(codigo='ONU', activo=True)
                    estado_nuevo = EstadoMaterialONU.objects.get(codigo='NUEVO', activo=True)
                    tipo_ingreso_nuevo = TipoIngreso.objects.get(codigo='NUEVO', activo=True)

                    print(f"✅ Referencias obtenidas:")
                    print(f"   Tipo ONU: {tipo_onu}")
                    print(f"   Estado NUEVO: {estado_nuevo}")
                    print(f"   Tipo ingreso NUEVO: {tipo_ingreso_nuevo}")

                except (TipoMaterial.DoesNotExist, EstadoMaterialONU.DoesNotExist, TipoIngreso.DoesNotExist) as e:
                    print(f"❌ Error obteniendo referencias: {e}")
                    return Response({
                        'success': False,
                        'error': f'Configuración incompleta: {str(e)}'
                    }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

                # ✅ CREAR CADA MATERIAL
                for index, equipo in enumerate(equipos_validos):
                    try:
                        print(f"📦 Creando material {index + 1}/{len(equipos_validos)}: MAC {equipo['mac_address']}")

                        material = Material.objects.create(
                            # Relaciones básicas
                            tipo_material=tipo_onu,
                            modelo=modelo,
                            lote=lote,

                            # ✅ DATOS DEL EQUIPO ONU - SN OPCIONAL
                            mac_address=equipo['mac_address'],
                            gpon_serial=equipo['gpon_serial'],
                            serial_manufacturer=equipo['serial_manufacturer'] or None,  # ✅ NULL si vacío
                            codigo_item_equipo=equipo['codigo_item_equipo'],

                            # ✅ NÚMERO DE ENTREGA PARCIAL
                            numero_entrega_parcial=numero_entrega,

                            # Ubicación y estado
                            almacen_actual=lote.almacen_destino,
                            estado_onu=estado_nuevo,

                            # Control de origen
                            es_nuevo=True,
                            tipo_origen=tipo_ingreso_nuevo,

                            # Cantidad (1 para equipos únicos)
                            cantidad=1.00,

                            # Observaciones
                            observaciones=f"Importación masiva - Entrega #{numero_entrega}" if numero_entrega else "Importación masiva"
                        )

                        print(f"✅ Material creado: ID={material.id}, Código={material.codigo_interno}")
                        importados += 1

                    except Exception as e:
                        error_msg = f"Error creando material MAC {equipo['mac_address']}: {str(e)}"
                        print(f"❌ {error_msg}")
                        errores_importacion.append({
                            'mac': equipo['mac_address'],
                            'gpon': equipo['gpon_serial'],
                            'd_sn': equipo.get('serial_manufacturer', ''),
                            'error': str(e)
                        })
                        continue

                print(f"🎯 Importación completada: {importados} materiales creados")

                # ✅ CREAR O ACTUALIZAR ENTREGA PARCIAL AUTOMÁTICAMENTE
                if importados > 0:
                    try:
                        print(f"📦 Procesando entrega parcial...")

                        if numero_entrega:
                            # Caso: Se seleccionó una entrega específica
                            print(f"🔍 Actualizando entrega #{numero_entrega} seleccionada...")

                            try:
                                entrega_parcial = EntregaParcialLote.objects.get(
                                    lote=lote,
                                    numero_entrega=int(numero_entrega)
                                )

                                # Actualizar observaciones
                                nueva_observacion = f"Importados {importados} equipos el {timezone.now().date()}"
                                if entrega_parcial.observaciones:
                                    entrega_parcial.observaciones += f" | {nueva_observacion}"
                                else:
                                    entrega_parcial.observaciones = nueva_observacion

                                entrega_parcial.save()

                                print(f"✅ Entrega #{numero_entrega} actualizada exitosamente")

                            except EntregaParcialLote.DoesNotExist:
                                return Response({
                                    'success': False,
                                    'error': f'La entrega #{numero_entrega} no existe'
                                }, status=status.HTTP_404_NOT_FOUND)

                        else:
                            # Caso: Crear nueva entrega automática
                            print(f"🆕 Creando nueva entrega automática...")

                            # Obtener el próximo número de entrega
                            ultima_entrega = EntregaParcialLote.objects.filter(
                                lote=lote
                            ).order_by('-numero_entrega').first()

                            siguiente_numero = (ultima_entrega.numero_entrega + 1) if ultima_entrega else 1

                            try:
                                estado_activo = EstadoLote.objects.get(codigo='ACTIVO', activo=True)
                            except EstadoLote.DoesNotExist:
                                # Usar el primer estado disponible como fallback
                                estado_activo = EstadoLote.objects.filter(activo=True).first()
                            # Crear nueva entrega parcial
                            nueva_entrega = EntregaParcialLote.objects.create(
                                lote=lote,
                                numero_entrega=siguiente_numero,
                                cantidad_entregada=importados,
                                fecha_entrega=timezone.now().date(),
                                estado_entrega=estado_activo,
                                observaciones=f"Entrega automática - Importados {importados} equipos"
                            )

                            # Actualizar los materiales con el número de entrega
                            Material.objects.filter(
                                lote=lote,
                                numero_entrega_parcial__isnull=True
                            ).update(numero_entrega_parcial=siguiente_numero)

                            print(f"✅ Nueva entrega #{siguiente_numero} creada con {importados} equipos")

                    except Exception as e:
                        print(f"⚠️ Error procesando entrega parcial: {e}")
                        return Response({
                            'success': False,
                            'error': f'Error procesando entrega parcial: {str(e)}'
                        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

                # ✅ ACTUALIZAR ESTADO DEL LOTE BASADO EN ENTREGAS REALES
                try:
                    print(f"📊 Actualizando estado del lote...")

                    # Calcular total entregado basado en entregas parciales
                    total_entregado_entregas = EntregaParcialLote.objects.filter(
                        lote=lote
                    ).aggregate(total=Sum('cantidad_entregada'))['total'] or 0

                    print(f"📊 Total en entregas parciales: {total_entregado_entregas}/{lote.cantidad_total}")

                    # Actualizar estado según el progreso real
                    if total_entregado_entregas >= lote.cantidad_total:
                        estado_completa = EstadoLote.objects.get(codigo='RECEPCION_COMPLETA', activo=True)
                        lote.estado = estado_completa
                        print(f"✅ Lote completado: {estado_completa.nombre}")
                    elif total_entregado_entregas > 0:
                        estado_parcial = EstadoLote.objects.get(codigo='RECEPCION_PARCIAL', activo=True)
                        lote.estado = estado_parcial
                        print(f"✅ Lote parcial: {estado_parcial.nombre}")
                    else:
                        # Mantener estado actual si no hay entregas
                        print(
                            f"ℹ️ Sin entregas registradas, manteniendo estado: {lote.estado.nombre if lote.estado else 'Sin estado'}")

                    lote.save()
                    print(f"✅ Estado del lote actualizado: {lote.estado.nombre}")

                except EstadoLote.DoesNotExist as e:
                    print(f"⚠️ Estado de lote no encontrado: {e}")
                except Exception as e:
                    print(f"⚠️ Error actualizando estado del lote: {e}")

                # Actualizar estadísticas del resultado
                resultado['importados'] = importados
                resultado['errores_importacion'] = errores_importacion

            # Verificar resultados finales
            total_materiales_despues = Material.objects.count()
            materiales_lote_despues = Material.objects.filter(lote_id=lote.id).count()
            print(f"📊 Materiales en sistema después: {total_materiales_despues}")
            print(f"📊 Materiales en lote después: {materiales_lote_despues}")

            # ✅ RESPUESTA EXITOSA
            return Response({
                'success': True,
                'message': f'Importación completada: {importados} equipos registrados' +
                           (f' en entrega #{numero_entrega}' if numero_entrega else ''),
                'resultado': resultado
            })

        except Exception as e:
            print(f"💥 ERROR EN MATERIALES ÚNICOS: {str(e)}")
            import traceback
            traceback.print_exc()
            return Response({
                'success': False,
                'error': f'Error procesando materiales únicos: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def _procesar_materiales_no_unicos(self, request, lote, modelo, archivo, numero_entrega, es_validacion):
        """Procesar materiales no únicos (cables, conectores, etc.) - NUEVO FLUJO"""
        print("🔍 === PROCESANDO MATERIALES NO ÚNICOS (CANTIDAD) ===")

        try:
            # Procesar archivo
            try:
                if archivo.name.endswith('.csv'):
                    df = pd.read_csv(archivo)
                elif archivo.name.endswith('.xlsx'):
                    df = pd.read_excel(archivo)
                else:
                    return Response({
                        'success': False,
                        'error': 'Formato de archivo no soportado. Use CSV o Excel (.xlsx)'
                    }, status=status.HTTP_400_BAD_REQUEST)

                print(f"✅ Archivo leído: {len(df)} filas")
                print(f"📝 Columnas disponibles: {list(df.columns)}")

            except Exception as e:
                print(f"💥 Error leyendo archivo: {str(e)}")
                return Response({
                    'success': False,
                    'error': f'Error al leer archivo: {str(e)}'
                }, status=status.HTTP_400_BAD_REQUEST)

            # ✅ VALIDAR COLUMNAS PARA MATERIALES NO ÚNICOS
            columnas_requeridas = ['CANTIDAD', 'ITEM_EQUIPO']
            columnas_opcionales = ['OBSERVACIONES', 'LOTE_PROVEEDOR']

            columnas_faltantes = [col for col in columnas_requeridas if col not in df.columns]

            if columnas_faltantes:
                return Response({
                    'success': False,
                    'error': f'Para materiales no únicos se requieren las columnas: {", ".join(columnas_requeridas)}. Faltantes: {", ".join(columnas_faltantes)}. Opcionales: {", ".join(columnas_opcionales)}'
                }, status=status.HTTP_400_BAD_REQUEST)

            print(f"✅ Columnas validadas para materiales no únicos")

            # Validar tamaño del archivo
            if len(df) > 100:
                return Response({
                    'success': False,
                    'error': 'Para materiales no únicos, el archivo no puede tener más de 100 filas'
                }, status=status.HTTP_400_BAD_REQUEST)

            # ✅ PROCESAR DATOS PARA MATERIALES NO ÚNICOS
            lotes_validos = []
            errores = []
            cantidad_total_calculada = 0

            for index, row in df.iterrows():
                fila_num = index + 2
                errores_fila = []

                # Extraer datos
                try:
                    cantidad = float(row['CANTIDAD']) if pd.notna(row['CANTIDAD']) else 0
                    item_equipo = str(row['ITEM_EQUIPO']).strip() if pd.notna(row['ITEM_EQUIPO']) else ''
                    observaciones = str(row.get('OBSERVACIONES', '')).strip() if pd.notna(
                        row.get('OBSERVACIONES', '')) else ''
                    lote_proveedor = str(row.get('LOTE_PROVEEDOR', '')).strip() if pd.notna(
                        row.get('LOTE_PROVEEDOR', '')) else ''
                except Exception as e:
                    errores_fila.append(f'Error procesando datos: {str(e)}')

                # Validaciones
                if cantidad <= 0:
                    errores_fila.append('CANTIDAD debe ser mayor a 0')
                elif cantidad > 10000:  # Límite razonable
                    errores_fila.append('CANTIDAD no puede ser mayor a 10,000')

                if not item_equipo:
                    errores_fila.append('ITEM_EQUIPO es requerido')
                elif not re.match(r'^\d{6,10}$', item_equipo):
                    errores_fila.append('ITEM_EQUIPO debe tener entre 6 y 10 dígitos numéricos')

                # Crear datos del lote de material
                if not errores_fila:
                    lote_data = {
                        'cantidad': cantidad,
                        'codigo_item_equipo': item_equipo,
                        'observaciones': observaciones,
                        'lote_proveedor': lote_proveedor,
                        'fila': fila_num
                    }
                    lotes_validos.append(lote_data)
                    cantidad_total_calculada += cantidad
                else:
                    errores.append({
                        'fila': fila_num,
                        'cantidad': cantidad if 'cantidad' in locals() else 'N/A',
                        'item_equipo': item_equipo if 'item_equipo' in locals() else 'N/A',
                        'errores': errores_fila
                    })

            # Preparar resultado
            resultado = {
                'total_filas': len(df),
                'validados': len(lotes_validos),
                'errores': len(errores),
                'cantidad_total': cantidad_total_calculada,
                'numero_entrega': numero_entrega,
                'tipo_material': 'NO_UNICO'
            }

            print(f"📊 Procesamiento completado:")
            print(f"   Total filas: {len(df)}")
            print(f"   Lotes válidos: {len(lotes_validos)}")
            print(f"   Cantidad total: {cantidad_total_calculada}")
            print(f"   Errores: {len(errores)}")

            # Si es solo validación, devolver preview
            if es_validacion:
                resultado.update({
                    'lotes_validos': lotes_validos[:5],  # Solo primeros 5 para preview
                    'detalles_errores': errores[:10]  # Solo primeros 10 errores
                })

                return Response({
                    'success': True,
                    'message': 'Validación completada',
                    'resultado': resultado
                })

            # Si no hay lotes válidos, devolver error
            if len(lotes_validos) == 0:
                return Response({
                    'success': False,
                    'error': 'No hay lotes de materiales válidos para importar',
                    'resultado': resultado,
                    'detalles_errores': errores[:20]
                }, status=status.HTTP_400_BAD_REQUEST)

            # ✅ PROCEDER CON LA IMPORTACIÓN REAL DE MATERIALES NO ÚNICOS
            with transaction.atomic():
                importados = 0
                cantidad_total_importada = 0
                errores_importacion = []

                print(f"🔍 Iniciando importación de {len(lotes_validos)} lotes de materiales")

                # Obtener referencias necesarias
                try:
                    # Usar el tipo de material del modelo directamente
                    tipo_material = modelo.tipo_material
                    estado_disponible = None

                    # Obtener estado apropiado según el tipo de material
                    if not tipo_material.es_unico:
                        try:
                            from ..models import EstadoMaterialGeneral
                            estado_disponible = EstadoMaterialGeneral.objects.get(codigo='DISPONIBLE', activo=True)
                        except ImportError:
                            print("⚠️ EstadoMaterialGeneral no disponible")
                        except:
                            print("⚠️ Estado DISPONIBLE no encontrado para materiales generales")

                    tipo_ingreso = lote.tipo_ingreso

                    print(f"✅ Referencias obtenidas:")
                    print(f"   Tipo Material: {tipo_material}")
                    print(f"   Estado disponible: {estado_disponible}")
                    print(f"   Tipo ingreso: {tipo_ingreso}")

                except Exception as e:
                    print(f"❌ Error obteniendo referencias: {e}")
                    return Response({
                        'success': False,
                        'error': f'Configuración incompleta: {str(e)}'
                    }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

                # ✅ CREAR CADA MATERIAL POR CANTIDAD
                for index, lote_material in enumerate(lotes_validos):
                    try:
                        print(
                            f"📦 Creando material {index + 1}/{len(lotes_validos)}: {lote_material['cantidad']} {modelo.unidad_medida.simbolo if modelo.unidad_medida else 'unidades'}")

                        # Preparar observaciones
                        observaciones_completas = f"Importación masiva - {lote_material['observaciones']}" if \
                        lote_material['observaciones'] else "Importación masiva"
                        if lote_material['lote_proveedor']:
                            observaciones_completas += f" | Lote proveedor: {lote_material['lote_proveedor']}"
                        if numero_entrega:
                            observaciones_completas += f" | Entrega #{numero_entrega}"

                        material = Material.objects.create(
                            # Relaciones básicas
                            tipo_material=tipo_material,
                            modelo=modelo,
                            lote=lote,

                            # ✅ DATOS PARA MATERIAL NO ÚNICO
                            codigo_item_equipo=lote_material['codigo_item_equipo'],
                            cantidad=lote_material['cantidad'],

                            # ✅ NÚMERO DE ENTREGA PARCIAL
                            numero_entrega_parcial=numero_entrega,

                            # Ubicación y estado
                            almacen_actual=lote.almacen_destino,
                            estado_general=estado_disponible,

                            # Control de origen
                            es_nuevo=lote.tipo_ingreso.codigo == 'NUEVO' if lote.tipo_ingreso else True,
                            tipo_origen=tipo_ingreso,

                            # Campos específicos para equipos únicos (vacíos para materiales no únicos)
                            mac_address=None,
                            gpon_serial=None,
                            serial_manufacturer=None,

                            # Observaciones
                            observaciones=observaciones_completas
                        )

                        print(
                            f"✅ Material creado: ID={material.id}, Código={material.codigo_interno}, Cantidad={material.cantidad}")
                        importados += 1
                        cantidad_total_importada += lote_material['cantidad']

                    except Exception as e:
                        error_msg = f"Error creando material cantidad {lote_material['cantidad']}: {str(e)}"
                        print(f"❌ {error_msg}")
                        errores_importacion.append({
                            'cantidad': lote_material['cantidad'],
                            'item_equipo': lote_material['codigo_item_equipo'],
                            'error': str(e)
                        })
                        continue

                print(
                    f"🎯 Importación completada: {importados} lotes de materiales creados, cantidad total: {cantidad_total_importada}")

                # ✅ CREAR O ACTUALIZAR ENTREGA PARCIAL PARA MATERIALES NO ÚNICOS
                if importados > 0:
                    try:
                        print(f"📦 Procesando entrega parcial para materiales no únicos...")

                        if numero_entrega:
                            # Caso: Se seleccionó una entrega específica
                            print(f"🔍 Actualizando entrega #{numero_entrega} seleccionada...")

                            try:
                                entrega_parcial = EntregaParcialLote.objects.get(
                                    lote=lote,
                                    numero_entrega=int(numero_entrega)
                                )

                                # Actualizar observaciones
                                nueva_observacion = f"Importados {importados} lotes de materiales (cantidad total: {cantidad_total_importada}) el {timezone.now().date()}"
                                if entrega_parcial.observaciones:
                                    entrega_parcial.observaciones += f" | {nueva_observacion}"
                                else:
                                    entrega_parcial.observaciones = nueva_observacion

                                entrega_parcial.save()

                                print(f"✅ Entrega #{numero_entrega} actualizada exitosamente")

                            except EntregaParcialLote.DoesNotExist:
                                return Response({
                                    'success': False,
                                    'error': f'La entrega #{numero_entrega} no existe'
                                }, status=status.HTTP_404_NOT_FOUND)

                        else:
                            # Caso: Crear nueva entrega automática
                            print(f"🆕 Creando nueva entrega automática...")

                            # Obtener el próximo número de entrega
                            ultima_entrega = EntregaParcialLote.objects.filter(
                                lote=lote
                            ).order_by('-numero_entrega').first()

                            siguiente_numero = (ultima_entrega.numero_entrega + 1) if ultima_entrega else 1

                            try:
                                estado_activo = EstadoLote.objects.get(codigo='ACTIVO', activo=True)
                            except EstadoLote.DoesNotExist:
                                estado_activo = EstadoLote.objects.filter(activo=True).first()

                            # Crear nueva entrega parcial con la cantidad total importada
                            nueva_entrega = EntregaParcialLote.objects.create(
                                lote=lote,
                                numero_entrega=siguiente_numero,
                                cantidad_entregada=int(cantidad_total_importada),  # ✅ Usar cantidad total
                                fecha_entrega=timezone.now().date(),
                                estado_entrega=estado_activo,
                                observaciones=f"Entrega automática - {importados} lotes de materiales (cantidad total: {cantidad_total_importada})"
                            )

                            # Actualizar los materiales con el número de entrega
                            Material.objects.filter(
                                lote=lote,
                                numero_entrega_parcial__isnull=True
                            ).update(numero_entrega_parcial=siguiente_numero)

                            print(
                                f"✅ Nueva entrega #{siguiente_numero} creada con cantidad total {cantidad_total_importada}")

                    except Exception as e:
                        print(f"⚠️ Error procesando entrega parcial: {e}")
                        return Response({
                            'success': False,
                            'error': f'Error procesando entrega parcial: {str(e)}'
                        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

                # ✅ ACTUALIZAR ESTADO DEL LOTE
                try:
                    print(f"📊 Actualizando estado del lote...")

                    # Calcular total entregado basado en entregas parciales
                    total_entregado_entregas = EntregaParcialLote.objects.filter(
                        lote=lote
                    ).aggregate(total=Sum('cantidad_entregada'))['total'] or 0

                    print(f"📊 Total en entregas parciales: {total_entregado_entregas}/{lote.cantidad_total}")

                    # Actualizar estado según el progreso real
                    if total_entregado_entregas >= lote.cantidad_total:
                        estado_completa = EstadoLote.objects.get(codigo='RECEPCION_COMPLETA', activo=True)
                        lote.estado = estado_completa
                        print(f"✅ Lote completado: {estado_completa.nombre}")
                    elif total_entregado_entregas > 0:
                        estado_parcial = EstadoLote.objects.get(codigo='RECEPCION_PARCIAL', activo=True)
                        lote.estado = estado_parcial
                        print(f"✅ Lote parcial: {estado_parcial.nombre}")

                    lote.save()
                    print(f"✅ Estado del lote actualizado: {lote.estado.nombre}")

                except EstadoLote.DoesNotExist as e:
                    print(f"⚠️ Estado de lote no encontrado: {e}")
                except Exception as e:
                    print(f"⚠️ Error actualizando estado del lote: {e}")

                # Actualizar estadísticas del resultado
                resultado['importados'] = importados
                resultado['cantidad_total_importada'] = cantidad_total_importada
                resultado['errores_importacion'] = errores_importacion

            # ✅ RESPUESTA EXITOSA PARA MATERIALES NO ÚNICOS
            return Response({
                'success': True,
                'message': f'Importación completada: {importados} lotes de materiales registrados (cantidad total: {cantidad_total_importada})' +
                           (f' en entrega #{numero_entrega}' if numero_entrega else ''),
                'resultado': resultado
            })

        except Exception as e:
            print(f"💥 ERROR EN MATERIALES NO ÚNICOS: {str(e)}")
            import traceback
            traceback.print_exc()
            return Response({
                'success': False,
                'error': f'Error procesando materiales no únicos: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def get(self, request, *args, **kwargs):
        """Obtener documentación y plantillas según tipo de material - MEJORADO"""
        return Response({
            'deteccion_automatica': {
                'descripcion': 'El sistema detecta automáticamente el tipo de material basado en el modelo seleccionado',
                'flujos': {
                    'materiales_unicos': 'ONUs y equipos con identificadores únicos (MAC, GPON, etc.)',
                    'materiales_no_unicos': 'Cables, conectores, materiales por cantidad'
                }
            },
            'materiales_unicos': {
                'descripcion': 'Para equipos únicos como ONUs',
                'deteccion': 'Modelo con tipo_material.es_unico = True',
                'plantilla': {
                    'columnas_requeridas': ['GPON_SN', 'MAC'],
                    'columnas_opcionales': ['D_SN'],
                    'formato_mac': 'XX:XX:XX:XX:XX:XX (mayúsculas, separado por :)',
                    'formato_gpon': 'Mínimo 8 caracteres (ej: HWTC12345678)',
                    'formato_d_sn': 'Mínimo 6 caracteres si se proporciona (OPCIONAL)',
                    'ejemplo': {
                        'GPON_SN': 'HWTC12345678',
                        'MAC': '00:11:22:33:44:55',
                        'D_SN': 'SN123456789 (OPCIONAL)'
                    }
                },
                'item_equipo_info': {
                    'descripcion': 'El código ITEM_EQUIPO se configura una vez para todo el lote',
                    'formato': '6-10 dígitos numéricos',
                    'ejemplo': '1234567890'
                },
                'limites': {
                    'max_filas': 1000,
                    'validaciones': 'MAC, GPON únicos en sistema y archivo'
                }
            },
            'materiales_no_unicos': {
                'descripción': 'Para cables, conectores, materiales por cantidad',
                'deteccion': 'Modelo con tipo_material.es_unico = False',
                'plantilla': {
                    'columnas_requeridas': ['CANTIDAD', 'ITEM_EQUIPO'],
                    'columnas_opcionales': ['OBSERVACIONES', 'LOTE_PROVEEDOR'],
                    'formato_cantidad': 'Número decimal positivo (ej: 100.5)',
                    'formato_item_equipo': '6-10 dígitos numéricos por fila',
                    'ejemplo': {
                        'CANTIDAD': 100,
                        'ITEM_EQUIPO': '1234567890',
                        'OBSERVACIONES': 'Cable fibra óptica monomodo SM',
                        'LOTE_PROVEEDOR': 'LOTE-2024-001'
                    }
                },
                'limites': {
                    'max_filas': 100,
                    'max_cantidad_por_fila': 10000,
                    'validaciones': 'Cantidad > 0, ITEM_EQUIPO numérico'
                }
            },
            'formatos_archivo_soportados': [
                {
                    'tipo': 'Excel',
                    'extension': '.xlsx',
                    'descripcion': 'Formato recomendado'
                },
                {
                    'tipo': 'CSV',
                    'extension': '.csv',
                    'descripcion': 'Separado por comas, codificación UTF-8'
                }
            ],
            'instrucciones_generales': [
                '1. El sistema detecta automáticamente si el modelo es único o no',
                '2. Usar la plantilla correcta según el tipo detectado',
                '3. No dejar filas vacías entre los datos',
                '4. Verificar que todos los valores sean únicos donde corresponde',
                '5. El ITEM_EQUIPO puede ser diferente por fila en materiales no únicos',
                '6. Las observaciones son opcionales pero recomendadas',
                '7. Validar siempre antes de importar usando validacion=true'
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