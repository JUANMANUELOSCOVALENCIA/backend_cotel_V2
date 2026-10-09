# ======================================================
# almacenes/views/sector_views.py
# ======================================================

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from ..permisos import PermisoPorRol, LECTURA_ALMACENES
from rest_framework import filters

from ..models import SectorSolicitante, Material, EstadoMaterialONU, TipoMaterial
from ..optimizaciones import optimizar_sectores
from ..serializers import (
    SectorSolicitanteSerializer, DevolucionSectorSerializer,
    ReingresoSectorSerializer, MaterialListSerializer
)
from usuarios.auditoria import AuditoriaMixin


class SectorSolicitanteViewSet(AuditoriaMixin, viewsets.ModelViewSet):
    """Gestión de sectores solicitantes"""
    queryset = SectorSolicitante.objects.all()
    serializer_class = SectorSolicitanteSerializer
    permission_classes = [PermisoPorRol]
    lectura_alternativa = LECTURA_ALMACENES

    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['nombre']
    ordering = ['orden', 'nombre']

    def get_queryset(self):
        if self.request.query_params.get('incluir_inactivos') == 'true':
            qs = SectorSolicitante.objects.all()
        else:
            qs = SectorSolicitante.objects.filter(activo=True)
        return optimizar_sectores(qs) if self.action == 'list' else qs

    @action(detail=True, methods=['get'])
    def materiales_por_estado(self, request, pk=None):
        """Materiales del sector por estado"""
        sector = self.get_object()

        materiales = Material.objects.filter(
            lote__sector_solicitante=sector,
            tipo_material__es_unico=True
        )

        resumen = {}
        for estado in EstadoMaterialONU.objects.filter(activo=True):
            count = materiales.filter(estado_onu=estado).count()
            if count > 0:
                resumen[estado.nombre] = count

        return Response({
            'sector': sector.nombre,
            'total_materiales': materiales.count(),
            'por_estado': resumen
        })


class DevolucionSectorView(AuditoriaMixin, APIView):
    """Devolver materiales defectuosos al sector solicitante"""
    auditoria_modelo = Material
    auditoria_acciones = {'POST': 'Devolución de equipos defectuosos'}
    permission_classes = [PermisoPorRol]
    recurso_permiso = 'materiales'
    accion_permiso = {'GET': 'leer', 'POST': 'actualizar'}

    def get(self, request):
        """Obtener materiales defectuosos para devolver"""
        estado_defectuoso = EstadoMaterialONU.objects.get(codigo='DEFECTUOSO', activo=True)
        tipo_onu = TipoMaterial.objects.get(codigo='ONU', activo=True)

        materiales = Material.objects.filter(
            tipo_material=tipo_onu,
            estado_onu=estado_defectuoso
        ).select_related('lote__sector_solicitante', 'modelo__marca', 'almacen_actual')

        serializer = MaterialListSerializer(materiales, many=True)
        return Response({
            'total': materiales.count(),
            'materiales': serializer.data
        })

    def post(self, request):
        """Ejecutar devolución al sector"""
        serializer = DevolucionSectorSerializer(data=request.data)

        if serializer.is_valid():
            count = serializer.ejecutar(request.user)
            return Response({
                'success': True,
                'message': f'{count} materiales devueltos al sector solicitante'
            })

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ReingresoSectorView(AuditoriaMixin, APIView):
    """Reingresar nuevos equipos desde sector solicitante"""
    auditoria_modelo = Material
    auditoria_acciones = {'POST': 'Reposición de equipo (reingreso)'}
    permission_classes = [PermisoPorRol]
    recurso_permiso = 'materiales'
    accion_permiso = {'GET': 'leer', 'POST': 'actualizar'}

    def get(self, request):
        """Obtener materiales devueltos al sector"""
        estado_devuelto = EstadoMaterialONU.objects.get(codigo='DEVUELTO_SECTOR_SOLICITANTE', activo=True)

        materiales = Material.objects.filter(
            estado_onu=estado_devuelto
        ).exclude(
            observaciones__icontains='[REEMPLAZADO]'  # Excluir los reemplazados
        ).select_related('lote__sector_solicitante', 'modelo__marca', 'almacen_actual')

        serializer = MaterialListSerializer(materiales, many=True)
        return Response({
            'total': materiales.count(),
            'materiales': serializer.data
        })

    def post(self, request):
        """Ejecutar reingreso desde sector"""
        serializer = ReingresoSectorSerializer(data=request.data)

        if serializer.is_valid():
            materiales = serializer.ejecutar(request.user)
            reparados = sum(1 for e in serializer.validated_data['nuevos_equipos'] if e.get('mismo_equipo'))
            nuevos = len(materiales) - reparados
            partes = []
            if nuevos:
                partes.append(f'{nuevos} equipo(s) de reposición registrados')
            if reparados:
                partes.append(f'{reparados} equipo(s) reparados reactivados')
            return Response({
                'success': True,
                'message': ' y '.join(partes) + '. Quedan como Nuevos, pendientes de laboratorio.',
                'nuevos': nuevos,
                'reparados': reparados,
            })

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)