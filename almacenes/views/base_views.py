# ======================================================
# apps/almacenes/views.py - PASO 1: Views de Almacenes
# ======================================================

from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404
from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend

from usuarios.permissions import GenericRolePermission
from ..models import (
    Almacen, Proveedor, Material, TipoMaterialChoices,
    EstadoMaterialONUChoices, EstadoMaterialGeneralChoices
)
from ..serializers import AlmacenSerializer, ProveedorSerializer, MaterialListSerializer


# ========== VIEWSET DE ALMACENES ==========

class AlmacenViewSet(viewsets.ModelViewSet):
    """ViewSet para gestión de almacenes regionales"""
    queryset = Almacen.objects.all().order_by('codigo')
    serializer_class = AlmacenSerializer
    permission_classes = [IsAuthenticated, GenericRolePermission]
    basename = 'almacenes'

    # Configuración de filtros y búsqueda
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['tipo', 'es_principal', 'activo', 'ciudad']
    search_fields = ['codigo', 'nombre', 'ciudad']
    ordering_fields = ['codigo', 'nombre', 'created_at']
    ordering = ['codigo']

    def perform_create(self, serializer):
        """Asignar usuario creador al crear almacén"""
        serializer.save(created_by=self.request.user)

    def perform_update(self, serializer):
        """Validaciones adicionales al actualizar"""
        serializer.save()

    @action(detail=True, methods=['get'])
    def materiales(self, request, pk=None):
        """Obtener todos los materiales de un almacén específico"""
        almacen = self.get_object()
        materiales = almacen.material_set.all()

        # Filtros opcionales
        tipo_material = request.query_params.get('tipo_material')
        estado = request.query_params.get('estado')
        marca_id = request.query_params.get('marca_id')
        modelo_id = request.query_params.get('modelo_id')

        if tipo_material:
            materiales = materiales.filter(tipo_material=tipo_material)

        if estado:
            # Aplicar filtro de estado según el tipo de material
            if tipo_material == TipoMaterialChoices.ONU or not tipo_material:
                materiales = materiales.filter(
                    Q(tipo_material=TipoMaterialChoices.ONU, estado_onu=estado) |
                    Q(estado_general=estado)
                )
            else:
                materiales = materiales.filter(estado_general=estado)

        if marca_id:
            materiales = materiales.filter(modelo__marca_id=marca_id)

        if modelo_id:
            materiales = materiales.filter(modelo_id=modelo_id)

        # Paginación
        page = self.paginate_queryset(materiales)
        if page is not None:
            serializer = MaterialListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = MaterialListSerializer(materiales, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def materiales_disponibles(self, request, pk=None):
        """Obtener solo materiales disponibles para asignación o traspaso"""
        almacen = self.get_object()

        # Filtrar materiales disponibles
        materiales = almacen.material_set.filter(
            Q(tipo_material=TipoMaterialChoices.ONU, estado_onu=EstadoMaterialONUChoices.DISPONIBLE) |
            Q(estado_general=EstadoMaterialGeneralChoices.DISPONIBLE)
        )

        # Filtros opcionales
        tipo_material = request.query_params.get('tipo_material')
        if tipo_material:
            materiales = materiales.filter(tipo_material=tipo_material)

        serializer = MaterialListSerializer(materiales, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def estadisticas(self, request, pk=None):
        """Estadísticas detalladas del almacén"""
        almacen = self.get_object()

        # Estadísticas básicas
        total_materiales = almacen.material_set.count()

        # Materiales por tipo
        por_tipo = {}
        for tipo_choice in TipoMaterialChoices.choices:
            tipo_codigo, tipo_nombre = tipo_choice
            count = almacen.material_set.filter(tipo_material=tipo_codigo).count()
            por_tipo[tipo_nombre] = count

        # Estados de equipos ONU
        por_estado_onu = {}
        for estado_choice in EstadoMaterialONUChoices.choices:
            estado_codigo, estado_nombre = estado_choice
            count = almacen.material_set.filter(
                tipo_material=TipoMaterialChoices.ONU,
                estado_onu=estado_codigo
            ).count()
            por_estado_onu[estado_nombre] = count

        # Estados de otros materiales
        por_estado_general = {}
        for estado_choice in EstadoMaterialGeneralChoices.choices:
            estado_codigo, estado_nombre = estado_choice
            count = almacen.material_set.exclude(
                tipo_material=TipoMaterialChoices.ONU
            ).filter(estado_general=estado_codigo).count()
            por_estado_general[estado_nombre] = count

        # Top 10 materiales más antiguos
        materiales_antiguos = almacen.material_set.order_by('created_at')[:10]

        # Materiales por marca (solo top 5)
        por_marca = almacen.material_set.values(
            'modelo__marca__nombre'
        ).annotate(
            cantidad=Count('id')
        ).order_by('-cantidad')[:5]

        return Response({
            'almacen': {
                'id': almacen.id,
                'codigo': almacen.codigo,
                'nombre': almacen.nombre,
                'tipo': almacen.get_tipo_display(),
                'es_principal': almacen.es_principal
            },
            'totales': {
                'total_materiales': total_materiales,
                'materiales_disponibles': almacen.materiales_disponibles,
                'por_tipo_material': por_tipo,
                'por_estado_onu': por_estado_onu,
                'por_estado_general': por_estado_general,
                'por_marca': list(por_marca)
            },
            'detalles': {
                'materiales_antiguos': MaterialListSerializer(materiales_antiguos, many=True).data
            }
        })

    @action(detail=True, methods=['get'])
    def movimientos(self, request, pk=None):
        """Historial de movimientos del almacén (entradas y salidas)"""
        almacen = self.get_object()

        # Obtener traspasos de entrada y salida
        traspasos_entrada = almacen.traspasos_entrada.all().order_by('-created_at')[:20]
        traspasos_salida = almacen.traspasos_salida.all().order_by('-created_at')[:20]

        # Serializar (cuando tengamos el serializer de traspasos)
        movimientos = []

        for traspaso in traspasos_entrada:
            movimientos.append({
                'tipo': 'ENTRADA',
                'numero_traspaso': traspaso.numero_traspaso,
                'almacen_origen': traspaso.almacen_origen.nombre,
                'cantidad': traspaso.cantidad_recibida or traspaso.cantidad_enviada,
                'fecha': traspaso.fecha_recepcion or traspaso.fecha_envio,
                'estado': traspaso.estado
            })

        for traspaso in traspasos_salida:
            movimientos.append({
                'tipo': 'SALIDA',
                'numero_traspaso': traspaso.numero_traspaso,
                'almacen_destino': traspaso.almacen_destino.nombre,
                'cantidad': traspaso.cantidad_enviada,
                'fecha': traspaso.fecha_envio,
                'estado': traspaso.estado
            })

        # Ordenar por fecha
        movimientos.sort(key=lambda x: x['fecha'], reverse=True)

        return Response({
            'almacen_id': almacen.id,
            'movimientos': movimientos[:20]  # Solo los 20 más recientes
        })

    @action(detail=False, methods=['get'])
    def principal(self, request):
        """Obtener el almacén principal"""
        try:
            almacen_principal = Almacen.objects.get(es_principal=True)
            serializer = self.get_serializer(almacen_principal)
            return Response(serializer.data)
        except Almacen.DoesNotExist:
            return Response(
                {'error': 'No hay almacén principal configurado'},
                status=status.HTTP_404_NOT_FOUND
            )

    @action(detail=False, methods=['get'])
    def regionales(self, request):
        """Obtener todos los almacenes regionales activos"""
        almacenes = Almacen.objects.filter(
            tipo='REGIONAL',
            activo=True
        ).order_by('nombre')

        serializer = self.get_serializer(almacenes, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def resumen_general(self, request):
        """Resumen general de todos los almacenes"""
        almacenes = Almacen.objects.filter(activo=True)

        resumen = []
        totales_sistema = {
            'total_almacenes': almacenes.count(),
            'total_materiales': 0,
            'total_disponibles': 0
        }

        for almacen in almacenes:
            total_materiales = almacen.material_set.count()
            total_disponibles = almacen.materiales_disponibles

            resumen.append({
                'id': almacen.id,
                'codigo': almacen.codigo,
                'nombre': almacen.nombre,
                'tipo': almacen.get_tipo_display(),
                'es_principal': almacen.es_principal,
                'total_materiales': total_materiales,
                'materiales_disponibles': total_disponibles,
                'porcentaje_ocupacion': round(
                    (total_materiales / 1000 * 100), 2  # Asumiendo capacidad de 1000
                ) if total_materiales > 0 else 0
            })

            totales_sistema['total_materiales'] += total_materiales
            totales_sistema['total_disponibles'] += total_disponibles

        return Response({
            'totales_sistema': totales_sistema,
            'almacenes': resumen
        })

    def destroy(self, request, *args, **kwargs):
        """Validar antes de eliminar almacén"""
        almacen = self.get_object()

        # Validar que no tenga materiales
        if not almacen.puede_eliminar():
            return Response(
                {
                    'error': 'No se puede eliminar el almacén porque tiene materiales asignados',
                    'total_materiales': almacen.total_materiales
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        # Validar que no sea el almacén principal
        if almacen.es_principal:
            return Response(
                {'error': 'No se puede eliminar el almacén principal'},
                status=status.HTTP_400_BAD_REQUEST
            )

        return super().destroy(request, *args, **kwargs)


# ========== VIEWSET DE PROVEEDORES ==========

class ProveedorViewSet(viewsets.ModelViewSet):
    """ViewSet para gestión de proveedores"""
    queryset = Proveedor.objects.all().order_by('nombre_comercial')
    serializer_class = ProveedorSerializer
    permission_classes = [IsAuthenticated, GenericRolePermission]
    basename = 'proveedores'

    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['activo']
    search_fields = ['codigo', 'nombre_comercial', 'razon_social', 'contacto_principal']
    ordering_fields = ['nombre_comercial', 'created_at']
    ordering = ['nombre_comercial']

    def perform_create(self, serializer):
        """Asignar usuario creador al crear proveedor"""
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=['get'])
    def lotes(self, request, pk=None):
        """Obtener todos los lotes de un proveedor"""
        proveedor = self.get_object()
        lotes = proveedor.lote_set.all().order_by('-created_at')

        # Filtros opcionales
        estado = request.query_params.get('estado')
        tipo_ingreso = request.query_params.get('tipo_ingreso')

        if estado:
            lotes = lotes.filter(estado=estado)
        if tipo_ingreso:
            lotes = lotes.filter(tipo_ingreso=tipo_ingreso)

        # Cuando tengamos LoteSerializer, usar:
        # serializer = LoteSerializer(lotes, many=True)
        # return Response(serializer.data)

        # Por ahora, respuesta básica:
        lotes_data = []
        for lote in lotes:
            lotes_data.append({
                'id': lote.id,
                'numero_lote': lote.numero_lote,
                'tipo_ingreso': lote.tipo_ingreso,
                'estado': lote.estado,
                'fecha_recepcion': lote.fecha_recepcion,
                'cantidad_total': lote.cantidad_total,
                'cantidad_recibida': lote.cantidad_recibida
            })

        return Response(lotes_data)

    @action(detail=True, methods=['get'])
    def estadisticas(self, request, pk=None):
        """Estadísticas del proveedor"""
        proveedor = self.get_object()

        # Estadísticas de lotes
        lotes = proveedor.lote_set.all()
        total_lotes = lotes.count()

        # Lotes por estado
        from ..models import EstadoLoteChoices
        lotes_por_estado = {}
        for estado_choice in EstadoLoteChoices.choices:
            estado_codigo, estado_nombre = estado_choice
            count = lotes.filter(estado=estado_codigo).count()
            lotes_por_estado[estado_nombre] = count

        # Materiales totales suministrados
        total_materiales = Material.objects.filter(lote__proveedor=proveedor).count()

        # Materiales por tipo
        materiales_por_tipo = {}
        for tipo_choice in TipoMaterialChoices.choices:
            tipo_codigo, tipo_nombre = tipo_choice
            count = Material.objects.filter(
                lote__proveedor=proveedor,
                tipo_material=tipo_codigo
            ).count()
            materiales_por_tipo[tipo_nombre] = count

        # Lotes recientes (últimos 5)
        lotes_recientes = lotes.order_by('-created_at')[:5]

        return Response({
            'proveedor': {
                'id': proveedor.id,
                'nombre_comercial': proveedor.nombre_comercial,
                'codigo': proveedor.codigo
            },
            'estadisticas': {
                'total_lotes': total_lotes,
                'total_materiales': total_materiales,
                'lotes_por_estado': lotes_por_estado,
                'materiales_por_tipo': materiales_por_tipo
            },
            'lotes_recientes': [
                {
                    'id': lote.id,
                    'numero_lote': lote.numero_lote,
                    'estado': lote.get_estado_display(),
                    'fecha_recepcion': lote.fecha_recepcion,
                    'cantidad_total': lote.cantidad_total
                } for lote in lotes_recientes
            ]
        })

    @action(detail=False, methods=['get'])
    def activos(self, request):
        """Obtener solo proveedores activos"""
        proveedores = Proveedor.objects.filter(activo=True).order_by('nombre_comercial')
        serializer = self.get_serializer(proveedores, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def top_proveedores(self, request):
        """Top 10 proveedores por cantidad de materiales suministrados"""
        proveedores = Proveedor.objects.annotate(
            total_materiales=Count('lote__material')
        ).filter(
            total_materiales__gt=0
        ).order_by('-total_materiales')[:10]

        top_data = []
        for proveedor in proveedores:
            top_data.append({
                'id': proveedor.id,
                'nombre_comercial': proveedor.nombre_comercial,
                'total_lotes': proveedor.lote_set.count(),
                'total_materiales': proveedor.total_materiales
            })

        return Response(top_data)