# ======================================================
# almacenes/views/choices_views.py - COMPLETO
# Views para modelos de choices y endpoint de opciones completas
# ======================================================

from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend
from django.utils import timezone

from usuarios.permissions import GenericRolePermission
from ..models import (
    TipoIngreso, EstadoLote, EstadoTraspaso, TipoMaterial, UnidadMedida,
    EstadoMaterialONU, EstadoMaterialGeneral, TipoAlmacen, EstadoDevolucion,
    RespuestaProveedor, Almacen, Proveedor, Marca, TipoEquipo
)
from ..serializers import (
    TipoIngresoSerializer, EstadoLoteSerializer, EstadoTraspasoSerializer,
    TipoMaterialSerializer, UnidadMedidaSerializer, EstadoMaterialONUSerializer,
    EstadoMaterialGeneralSerializer, TipoAlmacenSerializer, EstadoDevolucionSerializer,
    RespuestaProveedorSerializer, AlmacenSerializer, ProveedorSerializer,
    MarcaSerializer, TipoEquipoSerializer, ListaOpcionesSerializer
)


# ========== VIEWSETS PARA MODELOS DE CHOICES ==========

class TipoIngresoViewSet(viewsets.ModelViewSet):
    """ViewSet para tipos de ingreso"""
    queryset = TipoIngreso.objects.all().order_by('orden', 'nombre')
    serializer_class = TipoIngresoSerializer
    permission_classes = [IsAuthenticated, GenericRolePermission]
    basename = 'tipos-ingreso'

    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['codigo', 'nombre', 'descripcion']
    ordering_fields = ['codigo', 'nombre', 'orden']

    def get_queryset(self):
        queryset = super().get_queryset()
        incluir_inactivos = self.request.query_params.get('incluir_inactivos', 'false').lower() == 'true'

        if not incluir_inactivos:
            queryset = queryset.filter(activo=True)

        return queryset

    @action(detail=True, methods=['post'])
    def toggle_activo(self, request, pk=None):
        """Activar/desactivar tipo de ingreso"""
        tipo = self.get_object()
        tipo.activo = not tipo.activo
        tipo.save()

        return Response({
            'message': f'Tipo de ingreso {tipo.nombre} {"activado" if tipo.activo else "desactivado"}',
            'activo': tipo.activo
        })

    @action(detail=False, methods=['get'])
    def para_lotes_nuevos(self, request):
        """Tipos de ingreso válidos para lotes nuevos"""
        tipos = self.get_queryset().filter(codigo__in=['NUEVO', 'REINGRESO'])
        serializer = self.get_serializer(tipos, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def lotes_count(self, request, pk=None):
        """Contar lotes con este tipo de ingreso"""
        tipo = self.get_object()
        from ..models import Lote
        count = Lote.objects.filter(tipo_ingreso=tipo).count()
        return Response({
            'tipo_ingreso': tipo.nombre,
            'total_lotes': count
        })


class EstadoLoteViewSet(viewsets.ModelViewSet):
    """ViewSet para estados de lote"""
    queryset = EstadoLote.objects.all().order_by('orden', 'nombre')
    serializer_class = EstadoLoteSerializer
    permission_classes = [IsAuthenticated, GenericRolePermission]
    basename = 'estados-lote'

    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['es_final', 'activo']
    search_fields = ['codigo', 'nombre', 'descripcion']

    def get_queryset(self):
        queryset = super().get_queryset()
        incluir_inactivos = self.request.query_params.get('incluir_inactivos', 'false').lower() == 'true'

        if not incluir_inactivos:
            queryset = queryset.filter(activo=True)

        return queryset

    @action(detail=False, methods=['get'])
    def finales(self, request):
        """Obtener solo estados finales"""
        estados = self.get_queryset().filter(es_final=True)
        serializer = self.get_serializer(estados, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def activos(self, request):
        """Estados para lotes activos"""
        estados = self.get_queryset().filter(codigo__in=['ACTIVO', 'RECEPCION_PARCIAL', 'RECEPCION_COMPLETA'])
        serializer = self.get_serializer(estados, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def lotes_count(self, request, pk=None):
        """Contar lotes en este estado"""
        estado = self.get_object()
        from ..models import Lote
        count = Lote.objects.filter(estado=estado).count()
        return Response({
            'estado': estado.nombre,
            'total_lotes': count
        })


class EstadoTraspasoViewSet(viewsets.ModelViewSet):
    """ViewSet para estados de traspaso"""
    queryset = EstadoTraspaso.objects.all().order_by('orden', 'nombre')
    serializer_class = EstadoTraspasoSerializer
    permission_classes = [IsAuthenticated, GenericRolePermission]
    basename = 'estados-traspaso'

    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['es_final', 'activo']
    search_fields = ['codigo', 'nombre', 'descripcion']

    def get_queryset(self):
        queryset = super().get_queryset()
        incluir_inactivos = self.request.query_params.get('incluir_inactivos', 'false').lower() == 'true'

        if not incluir_inactivos:
            queryset = queryset.filter(activo=True)

        return queryset

    @action(detail=False, methods=['get'])
    def finales(self, request):
        """Obtener solo estados finales"""
        estados = self.get_queryset().filter(es_final=True)
        serializer = self.get_serializer(estados, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def en_proceso(self, request):
        """Estados para traspasos en proceso"""
        estados = self.get_queryset().filter(codigo__in=['PENDIENTE', 'EN_TRANSITO'])
        serializer = self.get_serializer(estados, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def traspasos_count(self, request, pk=None):
        """Contar traspasos en este estado"""
        estado = self.get_object()
        from ..models import TraspasoAlmacen
        count = TraspasoAlmacen.objects.filter(estado=estado).count()
        return Response({
            'estado': estado.nombre,
            'total_traspasos': count
        })


class TipoMaterialViewSet(viewsets.ModelViewSet):
    """ViewSet para tipos de material"""
    queryset = TipoMaterial.objects.all().select_related('unidad_medida_default', 'created_by').order_by('orden',
                                                                                                         'nombre')
    serializer_class = TipoMaterialSerializer
    permission_classes = [IsAuthenticated, GenericRolePermission]
    basename = 'tipos-material'

    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['es_unico', 'requiere_inspeccion_inicial', 'activo', 'unidad_medida_default']
    search_fields = ['codigo', 'nombre', 'descripcion']
    ordering_fields = ['codigo', 'nombre', 'orden']

    def get_queryset(self):
        queryset = super().get_queryset()
        incluir_inactivos = self.request.query_params.get('incluir_inactivos', 'false').lower() == 'true'

        if not incluir_inactivos:
            queryset = queryset.filter(activo=True)

        return queryset

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=['get'])
    def materiales(self, request, pk=None):
        """Obtener materiales de este tipo"""
        tipo = self.get_object()
        from ..serializers import MaterialListSerializer

        materiales = tipo.material_set.all()

        # Filtros opcionales
        almacen_id = request.query_params.get('almacen_id')
        if almacen_id:
            materiales = materiales.filter(almacen_actual_id=almacen_id)

        estado = request.query_params.get('estado')
        if estado:
            if tipo.es_unico:
                materiales = materiales.filter(estado_onu__codigo=estado)
            else:
                materiales = materiales.filter(estado_general__codigo=estado)

        serializer = MaterialListSerializer(materiales, many=True)
        return Response({
            'tipo_material': {
                'id': tipo.id,
                'codigo': tipo.codigo,
                'nombre': tipo.nombre,
                'es_unico': tipo.es_unico
            },
            'total_materiales': materiales.count(),
            'materiales': serializer.data
        })

    @action(detail=True, methods=['get'])
    def modelos(self, request, pk=None):
        """Obtener modelos que usan este tipo"""
        tipo = self.get_object()
        from ..serializers import ModeloSerializer

        modelos = tipo.modelo_set.filter(activo=True)
        serializer = ModeloSerializer(modelos, many=True)

        return Response({
            'tipo_material': tipo.nombre,
            'total_modelos': modelos.count(),
            'modelos': serializer.data
        })

    @action(detail=False, methods=['get'])
    def unicos(self, request):
        """Obtener solo tipos de materiales únicos (como ONUs)"""
        tipos = self.get_queryset().filter(es_unico=True)
        serializer = self.get_serializer(tipos, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def por_cantidad(self, request):
        """Obtener solo tipos de materiales por cantidad"""
        tipos = self.get_queryset().filter(es_unico=False)
        serializer = self.get_serializer(tipos, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def con_inspeccion(self, request):
        """Tipos que requieren inspección inicial"""
        tipos = self.get_queryset().filter(requiere_inspeccion_inicial=True)
        serializer = self.get_serializer(tipos, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def toggle_activo(self, request, pk=None):
        """Activar/desactivar tipo de material"""
        tipo = self.get_object()
        tipo.activo = not tipo.activo
        tipo.save()

        return Response({
            'message': f'Tipo de material {tipo.nombre} {"activado" if tipo.activo else "desactivado"}',
            'activo': tipo.activo
        })


class UnidadMedidaViewSet(viewsets.ModelViewSet):
    """ViewSet para unidades de medida"""
    queryset = UnidadMedida.objects.all().order_by('orden', 'nombre')
    serializer_class = UnidadMedidaSerializer
    permission_classes = [IsAuthenticated, GenericRolePermission]
    basename = 'unidades-medida'

    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['codigo', 'nombre', 'simbolo', 'descripcion']
    ordering_fields = ['codigo', 'nombre', 'orden']

    def get_queryset(self):
        queryset = super().get_queryset()
        incluir_inactivos = self.request.query_params.get('incluir_inactivos', 'false').lower() == 'true'

        if not incluir_inactivos:
            queryset = queryset.filter(activo=True)

        return queryset

    @action(detail=True, methods=['post'])
    def toggle_activo(self, request, pk=None):
        """Activar/desactivar unidad de medida"""
        unidad = self.get_object()
        unidad.activo = not unidad.activo
        unidad.save()

        return Response({
            'message': f'Unidad de medida {unidad.nombre} {"activada" if unidad.activo else "desactivada"}',
            'activo': unidad.activo
        })

    @action(detail=True, methods=['get'])
    def tipos_material_usando(self, request, pk=None):
        """Tipos de material que usan esta unidad"""
        unidad = self.get_object()
        tipos = TipoMaterial.objects.filter(unidad_medida_default=unidad, activo=True)
        serializer = TipoMaterialSerializer(tipos, many=True)
        return Response({
            'unidad_medida': unidad.nombre,
            'tipos_usando': serializer.data
        })

    @action(detail=False, methods=['get'])
    def mas_usadas(self, request):
        """Unidades de medida más utilizadas"""
        from django.db.models import Count
        unidades = self.get_queryset().annotate(
            usos=Count('tipomaterial')
        ).filter(usos__gt=0).order_by('-usos')[:10]

        data = []
        for unidad in unidades:
            data.append({
                'id': unidad.id,
                'codigo': unidad.codigo,
                'nombre': unidad.nombre,
                'simbolo': unidad.simbolo,
                'total_usos': unidad.usos
            })

        return Response(data)


class EstadoMaterialONUViewSet(viewsets.ModelViewSet):
    """ViewSet para estados de material ONU"""
    queryset = EstadoMaterialONU.objects.all().order_by('orden', 'nombre')
    serializer_class = EstadoMaterialONUSerializer
    permission_classes = [IsAuthenticated, GenericRolePermission]
    basename = 'estados-material-onu'

    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['permite_asignacion', 'permite_traspaso', 'activo']
    search_fields = ['codigo', 'nombre', 'descripcion']

    def get_queryset(self):
        queryset = super().get_queryset()
        incluir_inactivos = self.request.query_params.get('incluir_inactivos', 'false').lower() == 'true'

        if not incluir_inactivos:
            queryset = queryset.filter(activo=True)

        return queryset

    @action(detail=False, methods=['get'])
    def para_asignacion(self, request):
        """Estados que permiten asignación"""
        estados = self.get_queryset().filter(permite_asignacion=True)
        serializer = self.get_serializer(estados, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def para_traspaso(self, request):
        """Estados que permiten traspaso"""
        estados = self.get_queryset().filter(permite_traspaso=True)
        serializer = self.get_serializer(estados, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def operativos(self, request):
        """Estados operativos (disponible, reservado, asignado)"""
        estados = self.get_queryset().filter(codigo__in=['DISPONIBLE', 'RESERVADO', 'ASIGNADO'])
        serializer = self.get_serializer(estados, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def problematicos(self, request):
        """Estados que indican problemas"""
        estados = self.get_queryset().filter(codigo__in=['DEFECTUOSO', 'DADO_DE_BAJA'])
        serializer = self.get_serializer(estados, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def materiales_count(self, request, pk=None):
        """Contar materiales en este estado"""
        estado = self.get_object()
        from ..models import Material

        count = Material.objects.filter(estado_onu=estado).count()

        # Por almacén
        por_almacen = Material.objects.filter(estado_onu=estado).values(
            'almacen_actual__codigo', 'almacen_actual__nombre'
        ).annotate(
            total=Count('id')
        ).order_by('-total')

        return Response({
            'estado': estado.nombre,
            'total_materiales': count,
            'por_almacen': list(por_almacen)
        })

    @action(detail=True, methods=['post'])
    def toggle_activo(self, request, pk=None):
        """Activar/desactivar estado"""
        estado = self.get_object()
        estado.activo = not estado.activo
        estado.save()

        return Response({
            'message': f'Estado {estado.nombre} {"activado" if estado.activo else "desactivado"}',
            'activo': estado.activo
        })


class EstadoMaterialGeneralViewSet(viewsets.ModelViewSet):
    """ViewSet para estados de material general"""
    queryset = EstadoMaterialGeneral.objects.all().order_by('orden', 'nombre')
    serializer_class = EstadoMaterialGeneralSerializer
    permission_classes = [IsAuthenticated, GenericRolePermission]
    basename = 'estados-material-general'

    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['permite_consumo', 'permite_traspaso', 'activo']
    search_fields = ['codigo', 'nombre', 'descripcion']

    def get_queryset(self):
        queryset = super().get_queryset()
        incluir_inactivos = self.request.query_params.get('incluir_inactivos', 'false').lower() == 'true'

        if not incluir_inactivos:
            queryset = queryset.filter(activo=True)

        return queryset

    @action(detail=False, methods=['get'])
    def para_consumo(self, request):
        """Estados que permiten consumo"""
        estados = self.get_queryset().filter(permite_consumo=True)
        serializer = self.get_serializer(estados, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def para_traspaso(self, request):
        """Estados que permiten traspaso"""
        estados = self.get_queryset().filter(permite_traspaso=True)
        serializer = self.get_serializer(estados, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def operativos(self, request):
        """Estados operativos"""
        estados = self.get_queryset().filter(codigo__in=['DISPONIBLE', 'RESERVADO', 'ASIGNADO'])
        serializer = self.get_serializer(estados, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def materiales_count(self, request, pk=None):
        """Contar materiales en este estado"""
        estado = self.get_object()
        from ..models import Material
        from django.db.models import Count

        count = Material.objects.filter(estado_general=estado).count()

        # Por almacén
        por_almacen = Material.objects.filter(estado_general=estado).values(
            'almacen_actual__codigo', 'almacen_actual__nombre'
        ).annotate(
            total=Count('id')
        ).order_by('-total')

        return Response({
            'estado': estado.nombre,
            'total_materiales': count,
            'por_almacen': list(por_almacen)
        })

    @action(detail=True, methods=['post'])
    def toggle_activo(self, request, pk=None):
        """Activar/desactivar estado"""
        estado = self.get_object()
        estado.activo = not estado.activo
        estado.save()

        return Response({
            'message': f'Estado {estado.nombre} {"activado" if estado.activo else "desactivado"}',
            'activo': estado.activo
        })


class TipoAlmacenViewSet(viewsets.ModelViewSet):
    """ViewSet para tipos de almacén"""
    queryset = TipoAlmacen.objects.all().order_by('orden', 'nombre')
    serializer_class = TipoAlmacenSerializer
    permission_classes = [IsAuthenticated, GenericRolePermission]
    basename = 'tipos-almacen'

    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['codigo', 'nombre', 'descripcion']
    ordering_fields = ['codigo', 'nombre', 'orden']

    def get_queryset(self):
        queryset = super().get_queryset()
        incluir_inactivos = self.request.query_params.get('incluir_inactivos', 'false').lower() == 'true'

        if not incluir_inactivos:
            queryset = queryset.filter(activo=True)

        return queryset

    @action(detail=True, methods=['get'])
    def almacenes(self, request, pk=None):
        """Obtener almacenes de este tipo"""
        tipo = self.get_object()
        almacenes = Almacen.objects.filter(tipo=tipo, activo=True)
        serializer = AlmacenSerializer(almacenes, many=True)

        return Response({
            'tipo_almacen': tipo.nombre,
            'total_almacenes': almacenes.count(),
            'almacenes': serializer.data
        })

    @action(detail=True, methods=['post'])
    def toggle_activo(self, request, pk=None):
        """Activar/desactivar tipo de almacén"""
        tipo = self.get_object()
        tipo.activo = not tipo.activo
        tipo.save()

        return Response({
            'message': f'Tipo de almacén {tipo.nombre} {"activado" if tipo.activo else "desactivado"}',
            'activo': tipo.activo
        })

    @action(detail=False, methods=['get'])
    def con_almacenes(self, request):
        """Tipos que tienen almacenes activos"""
        from django.db.models import Count
        tipos = self.get_queryset().annotate(
            total_almacenes=Count('almacen', filter=Q(almacen__activo=True))
        ).filter(total_almacenes__gt=0)

        data = []
        for tipo in tipos:
            data.append({
                'id': tipo.id,
                'codigo': tipo.codigo,
                'nombre': tipo.nombre,
                'total_almacenes': tipo.total_almacenes
            })

        return Response(data)


class EstadoDevolucionViewSet(viewsets.ModelViewSet):
    """ViewSet para estados de devolución"""
    queryset = EstadoDevolucion.objects.all().order_by('orden', 'nombre')
    serializer_class = EstadoDevolucionSerializer
    permission_classes = [IsAuthenticated, GenericRolePermission]
    basename = 'estados-devolucion'

    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['es_final', 'activo']
    search_fields = ['codigo', 'nombre', 'descripcion']

    def get_queryset(self):
        queryset = super().get_queryset()
        incluir_inactivos = self.request.query_params.get('incluir_inactivos', 'false').lower() == 'true'

        if not incluir_inactivos:
            queryset = queryset.filter(activo=True)

        return queryset

    @action(detail=False, methods=['get'])
    def finales(self, request):
        """Obtener solo estados finales"""
        estados = self.get_queryset().filter(es_final=True)
        serializer = self.get_serializer(estados, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def en_proceso(self, request):
        """Estados para devoluciones en proceso"""
        estados = self.get_queryset().filter(codigo__in=['PENDIENTE', 'ENVIADO'])
        serializer = self.get_serializer(estados, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def devoluciones_count(self, request, pk=None):
        """Contar devoluciones en este estado"""
        estado = self.get_object()
        from ..models import DevolucionProveedor
        count = DevolucionProveedor.objects.filter(estado=estado).count()
        return Response({
            'estado': estado.nombre,
            'total_devoluciones': count
        })

    @action(detail=True, methods=['post'])
    def toggle_activo(self, request, pk=None):
        """Activar/desactivar estado"""
        estado = self.get_object()
        estado.activo = not estado.activo
        estado.save()

        return Response({
            'message': f'Estado {estado.nombre} {"activado" if estado.activo else "desactivado"}',
            'activo': estado.activo
        })


class RespuestaProveedorViewSet(viewsets.ModelViewSet):
    """ViewSet para respuestas de proveedor"""
    queryset = RespuestaProveedor.objects.all().order_by('orden', 'nombre')
    serializer_class = RespuestaProveedorSerializer
    permission_classes = [IsAuthenticated, GenericRolePermission]
    basename = 'respuestas-proveedor'

    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['codigo', 'nombre', 'descripcion']
    ordering_fields = ['codigo', 'nombre', 'orden']

    def get_queryset(self):
        queryset = super().get_queryset()
        incluir_inactivos = self.request.query_params.get('incluir_inactivos', 'false').lower() == 'true'

        if not incluir_inactivos:
            queryset = queryset.filter(activo=True)

        return queryset

    @action(detail=True, methods=['post'])
    def toggle_activo(self, request, pk=None):
        """Activar/desactivar respuesta de proveedor"""
        respuesta = self.get_object()
        respuesta.activo = not respuesta.activo
        respuesta.save()

        return Response({
            'message': f'Respuesta {respuesta.nombre} {"activada" if respuesta.activo else "desactivada"}',
            'activo': respuesta.activo
        })

    @action(detail=True, methods=['get'])
    def devoluciones_count(self, request, pk=None):
        """Contar devoluciones con esta respuesta"""
        respuesta = self.get_object()
        from ..models import DevolucionProveedor
        count = DevolucionProveedor.objects.filter(respuesta_proveedor=respuesta).count()
        return Response({
            'respuesta': respuesta.nombre,
            'total_devoluciones': count
        })

    @action(detail=False, methods=['get'])
    def mas_usadas(self, request):
        """Respuestas más utilizadas"""
        from django.db.models import Count
        respuestas = self.get_queryset().annotate(
            usos=Count('devolucionproveedor')
        ).filter(usos__gt=0).order_by('-usos')

        data = []
        for respuesta in respuestas:
            data.append({
                'id': respuesta.id,
                'codigo': respuesta.codigo,
                'nombre': respuesta.nombre,
                'total_usos': respuesta.usos
            })

        return Response(data)


# ========== VIEW ESPECIAL PARA OPCIONES COMPLETAS ==========

class OpcionesCompletasView(APIView):
    """
    View especial que devuelve TODAS las opciones necesarias para el frontend React.
    Esto evita múltiples llamadas HTTP y proporciona todos los datos para comboboxes.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Obtener todas las opciones para formularios React"""

        try:
            # Cache the serializer data to avoid re-serialization
            cache_data = {}

            # Tipos y configuraciones básicas
            cache_data['tipos_ingreso'] = TipoIngresoSerializer(
                TipoIngreso.objects.filter(activo=True).order_by('orden'), many=True
            ).data

            cache_data['tipos_material'] = TipoMaterialSerializer(
                TipoMaterial.objects.filter(activo=True).select_related('unidad_medida_default').order_by('orden'),
                many=True
            ).data

            cache_data['tipos_almacen'] = TipoAlmacenSerializer(
                TipoAlmacen.objects.filter(activo=True).order_by('orden'), many=True
            ).data

            cache_data['unidades_medida'] = UnidadMedidaSerializer(
                UnidadMedida.objects.filter(activo=True).order_by('orden'), many=True
            ).data

            # Estados de lotes y operaciones
            cache_data['estados_lote'] = EstadoLoteSerializer(
                EstadoLote.objects.filter(activo=True).order_by('orden'), many=True
            ).data

            cache_data['estados_traspaso'] = EstadoTraspasoSerializer(
                EstadoTraspaso.objects.filter(activo=True).order_by('orden'), many=True
            ).data

            cache_data['estados_devolucion'] = EstadoDevolucionSerializer(
                EstadoDevolucion.objects.filter(activo=True).order_by('orden'), many=True
            ).data

            # Estados de materiales
            cache_data['estados_material_onu'] = EstadoMaterialONUSerializer(
                EstadoMaterialONU.objects.filter(activo=True).order_by('orden'), many=True
            ).data

            cache_data['estados_material_general'] = EstadoMaterialGeneralSerializer(
                EstadoMaterialGeneral.objects.filter(activo=True).order_by('orden'), many=True
            ).data

            # Respuestas de proveedores
            cache_data['respuestas_proveedor'] = RespuestaProveedorSerializer(
                RespuestaProveedor.objects.filter(activo=True).order_by('orden'), many=True
            ).data

            # Entidades principales (con información completa)
            cache_data['almacenes'] = AlmacenSerializer(
                Almacen.objects.filter(activo=True).select_related('tipo', 'encargado').order_by('codigo'), many=True
            ).data

            cache_data['proveedores'] = ProveedorSerializer(
                Proveedor.objects.filter(activo=True).order_by('nombre_comercial'), many=True
            ).data

            cache_data['marcas'] = MarcaSerializer(
                Marca.objects.filter(activo=True).order_by('nombre'), many=True
            ).data

            cache_data['tipos_equipo'] = TipoEquipoSerializer(
                TipoEquipo.objects.filter(activo=True).order_by('nombre'), many=True
            ).data

            # Información del usuario actual para logs
            user_info = {
                'user_id': request.user.id,
                'username': request.user.username,
                'nombre_completo': getattr(request.user, 'nombre_completo', 'Usuario'),
                'timestamp': timezone.now().isoformat()
            }

            return Response({
                'success': True,
                'message': 'Opciones completas obtenidas exitosamente',
                'user_info': user_info,
                'data': cache_data,
                'metadata': {
                    'total_tipos_ingreso': len(cache_data['tipos_ingreso']),
                    'total_tipos_material': len(cache_data['tipos_material']),
                    'total_almacenes': len(cache_data['almacenes']),
                    'total_proveedores': len(cache_data['proveedores']),
                    'total_marcas': len(cache_data['marcas']),
                    'cache_timestamp': timezone.now().isoformat(),
                    'version': '2.0'  # Para control de versiones del API
                }
            })

        except Exception as e:
            return Response({
                'success': False,
                'error': f'Error obteniendo opciones: {str(e)}',
                'timestamp': timezone.now().isoformat()
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['get'])
    def solo_basicas(self, request):
        """Obtener solo opciones básicas más usadas"""
        try:
            data = {
                'tipos_material': TipoMaterialSerializer(
                    TipoMaterial.objects.filter(activo=True).order_by('orden')[:5], many=True
                ).data,
                'almacenes': AlmacenSerializer(
                    Almacen.objects.filter(activo=True).order_by('codigo')[:10], many=True
                ).data,
                'estados_onu': EstadoMaterialONUSerializer(
                    EstadoMaterialONU.objects.filter(activo=True, codigo__in=['DISPONIBLE', 'RESERVADO', 'ASIGNADO']),
                    many=True
                ).data
            }
            return Response(data)
        except Exception as e:
            return Response({'error': str(e)}, status=500)


# ========== VIEW PARA INICIALIZAR DATOS ==========

class InicializarDatosView(APIView):
    """
    View para inicializar todos los datos base del sistema.
    Solo para administradores en primera instalación.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """Crear todos los datos iniciales del sistema"""

        # Verificar permisos de administrador
        if not request.user.is_superuser:
            return Response(
                {'error': 'Solo administradores pueden inicializar datos'},
                status=status.HTTP_403_FORBIDDEN
            )

        try:
            from ..models import crear_datos_iniciales

            # Ejecutar función de creación de datos
            crear_datos_iniciales()

            return Response({
                'success': True,
                'message': 'Datos iniciales creados exitosamente',
                'datos_creados': {
                    'tipos_ingreso': TipoIngreso.objects.count(),
                    'tipos_material': TipoMaterial.objects.count(),
                    'unidades_medida': UnidadMedida.objects.count(),
                    'estados_lote': EstadoLote.objects.count(),
                    'estados_traspaso': EstadoTraspaso.objects.count(),
                    'estados_material_onu': EstadoMaterialONU.objects.count(),
                    'estados_material_general': EstadoMaterialGeneral.objects.count(),
                    'tipos_almacen': TipoAlmacen.objects.count(),
                    'estados_devolucion': EstadoDevolucion.objects.count(),
                    'respuestas_proveedor': RespuestaProveedor.objects.count()
                },
                'usuario': request.user.username,
                'timestamp': timezone.now().isoformat()
            })

        except Exception as e:
            return Response(
                {
                    'success': False,
                    'error': f'Error al crear datos iniciales: {str(e)}'
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def get(self, request):
        """Verificar estado de los datos iniciales"""
        datos_estado = {
            'tipos_ingreso': TipoIngreso.objects.count(),
            'tipos_material': TipoMaterial.objects.count(),
            'unidades_medida': UnidadMedida.objects.count(),
            'estados_lote': EstadoLote.objects.count(),
            'estados_traspaso': EstadoTraspaso.objects.count(),
            'estados_material_onu': EstadoMaterialONU.objects.count(),
            'estados_material_general': EstadoMaterialGeneral.objects.count(),
            'tipos_almacen': TipoAlmacen.objects.count(),
            'estados_devolucion': EstadoDevolucion.objects.count(),
            'respuestas_proveedor': RespuestaProveedor.objects.count()
        }

        datos_faltantes = [k for k, v in datos_estado.items() if v == 0]

        return Response({
            'datos_actuales': datos_estado,
            'datos_faltantes': datos_faltantes,
            'inicializacion_requerida': len(datos_faltantes) > 0,
            'porcentaje_completado': round(
                ((len(datos_estado) - len(datos_faltantes)) / len(datos_estado)) * 100, 2
            )
        })


# ========== VIEW PARA ESTADÍSTICAS DE CHOICES ==========

class EstadisticasChoicesView(APIView):
    """Estadísticas de uso de los modelos de choices"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Estadísticas de uso de cada tipo de choice"""
        from django.db.models import Count

        estadisticas = {}

        # Uso de tipos de material
        estadisticas['tipos_material'] = list(
            TipoMaterial.objects.annotate(
                materiales_count=Count('material')
            ).values('codigo', 'nombre', 'materiales_count').order_by('-materiales_count')
        )

        # Uso de estados ONU
        estadisticas['estados_onu'] = list(
            EstadoMaterialONU.objects.annotate(
                materiales_count=Count('material_estado_onu')
            ).values('codigo', 'nombre', 'materiales_count').order_by('-materiales_count')
        )

        # Uso de tipos de ingreso
        estadisticas['tipos_ingreso'] = list(
            TipoIngreso.objects.annotate(
                lotes_count=Count('lote')
            ).values('codigo', 'nombre', 'lotes_count').order_by('-lotes_count')
        )

        # Estados más usados
        estadisticas['resumen'] = {
            'tipo_material_mas_usado': TipoMaterial.objects.annotate(
                count=Count('material')
            ).order_by('-count').first(),
            'estado_onu_mas_usado': EstadoMaterialONU.objects.annotate(
                count=Count('material_estado_onu')
            ).order_by('-count').first(),
        }

        return Response(estadisticas)