# ======================================================
# almacenes/views/compatibility_views.py
# Views para compatibilidad con modelos existentes
# ======================================================
from django.db import transaction
from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend

from usuarios.permissions import GenericRolePermission
from ..models import (
    EquipoONU, EquipoServicio, Marca, TipoEquipo, Modelo,
    EstadoEquipo, Componente, ModeloComponente
)
from ..serializers import (
    EquipoONUSerializer, EquipoServicioSerializer,
    MarcaSerializer, TipoEquipoSerializer, ModeloSerializer,
    EstadoEquipoSerializer, ComponenteSerializer, ModeloComponenteSerializer, ModeloCreateUpdateSerializer,
    ComponenteCreateUpdateSerializer
)


# ========== VIEWSETS DE COMPATIBILIDAD ==========

class EquipoONUViewSet(viewsets.ModelViewSet):
    """ViewSet para compatibilidad con el modelo EquipoONU existente"""
    queryset = EquipoONU.objects.all().select_related(
        'modelo__marca', 'tipo_equipo', 'estado', 'lote'
    )
    serializer_class = EquipoONUSerializer
    permission_classes = [IsAuthenticated, GenericRolePermission]
    basename = 'equipos-onu'

    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['modelo', 'modelo__marca', 'tipo_equipo', 'estado', 'lote']
    search_fields = ['codigo_interno', 'mac_address', 'gpon_serial', 'serial_manufacturer']
    ordering_fields = ['codigo_interno', 'fecha_ingreso']
    ordering = ['-fecha_ingreso']

    @action(detail=True, methods=['get'])
    def historial_servicios(self, request, pk=None):
        """Obtener historial de servicios del equipo"""
        equipo = self.get_object()
        servicios = equipo.equiposervicio_set.all().order_by('-fecha_asignacion')

        serializer = EquipoServicioSerializer(servicios, many=True)
        return Response({
            'equipo': {
                'id': equipo.id,
                'codigo_interno': equipo.codigo_interno,
                'mac_address': equipo.mac_address
            },
            'servicios': serializer.data
        })

    @action(detail=True, methods=['post'])
    def cambiar_estado_legacy(self, request, pk=None):
        """Cambiar estado usando el modelo EstadoEquipo legacy"""
        equipo = self.get_object()
        estado_id = request.data.get('estado_id')
        observaciones = request.data.get('observaciones', '')

        try:
            estado = EstadoEquipo.objects.get(id=estado_id, activo=True)
            equipo.estado = estado

            if observaciones:
                from django.utils import timezone
                timestamp = timezone.now().strftime('%Y-%m-%d %H:%M')
                nueva_obs = f"[{timestamp}] {observaciones}"
                if equipo.observaciones:
                    equipo.observaciones = f"{equipo.observaciones}\n{nueva_obs}"
                else:
                    equipo.observaciones = nueva_obs

            equipo.save()

            return Response({
                'message': f'Estado del equipo {equipo.codigo_interno} actualizado',
                'nuevo_estado': estado.nombre
            })

        except EstadoEquipo.DoesNotExist:
            return Response(
                {'error': 'Estado no encontrado o inactivo'},
                status=status.HTTP_400_BAD_REQUEST
            )

    @action(detail=False, methods=['get'])
    def disponibles_legacy(self, request):
        """Equipos disponibles usando estados legacy"""
        # Buscar equipos con estados que indiquen disponibilidad
        equipos = self.queryset.filter(
            estado__nombre__icontains='DISPONIBLE'
        )

        # Filtros opcionales
        modelo_id = request.query_params.get('modelo_id')
        marca_id = request.query_params.get('marca_id')

        if modelo_id:
            equipos = equipos.filter(modelo_id=modelo_id)
        if marca_id:
            equipos = equipos.filter(modelo__marca_id=marca_id)

        serializer = self.get_serializer(equipos, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def estadisticas_legacy(self, request):
        """Estadísticas usando el modelo legacy"""
        total_equipos = self.queryset.count()

        # Por estado legacy
        por_estado = {}
        for estado in EstadoEquipo.objects.filter(activo=True):
            count = self.queryset.filter(estado=estado).count()
            if count > 0:
                por_estado[estado.nombre] = count

        # Por modelo
        from django.db.models import Count
        por_modelo = self.queryset.values(
            'modelo__marca__nombre', 'modelo__nombre'
        ).annotate(
            cantidad=Count('id')
        ).order_by('-cantidad')[:10]

        return Response({
            'total_equipos': total_equipos,
            'por_estado': por_estado,
            'top_modelos': list(por_modelo)
        })


class EquipoServicioViewSet(viewsets.ModelViewSet):
    """ViewSet para relaciones equipo-servicio"""
    queryset = EquipoServicio.objects.all().select_related(
        'equipo_onu', 'contrato', 'servicio'
    )
    serializer_class = EquipoServicioSerializer
    permission_classes = [IsAuthenticated, GenericRolePermission]
    basename = 'equipo-servicios'

    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['estado_asignacion', 'contrato', 'servicio', 'equipo_onu']
    ordering_fields = ['fecha_asignacion', 'fecha_desasignacion']
    ordering = ['-fecha_asignacion']

    @action(detail=True, methods=['post'])
    def desasignar(self, request, pk=None):
        """Desasignar equipo del servicio"""
        asignacion = self.get_object()

        if asignacion.estado_asignacion != 'ACTIVO':
            return Response(
                {'error': 'Solo se pueden desasignar servicios activos'},
                status=status.HTTP_400_BAD_REQUEST
            )

        from django.utils import timezone
        asignacion.fecha_desasignacion = timezone.now().date()
        asignacion.estado_asignacion = 'CANCELADO'
        asignacion.observaciones += f"\nDesasignado el {timezone.now().strftime('%Y-%m-%d %H:%M')}"
        asignacion.save()

        return Response({
            'message': f'Equipo {asignacion.equipo_onu.codigo_interno} desasignado del servicio',
            'fecha_desasignacion': asignacion.fecha_desasignacion
        })

    @action(detail=False, methods=['get'])
    def por_contrato(self, request):
        """Equipos asignados por contrato"""
        contrato_id = request.query_params.get('contrato_id')

        if not contrato_id:
            return Response(
                {'error': 'ID de contrato requerido'},
                status=status.HTTP_400_BAD_REQUEST
            )

        asignaciones = self.queryset.filter(contrato_id=contrato_id)
        serializer = self.get_serializer(asignaciones, many=True)

        return Response({
            'contrato_id': contrato_id,
            'total_equipos': asignaciones.count(),
            'equipos_activos': asignaciones.filter(estado_asignacion='ACTIVO').count(),
            'asignaciones': serializer.data
        })


# ========== VIEWSETS ACTUALIZADOS DE MODELOS BÁSICOS ==========

class MarcaViewSet(viewsets.ModelViewSet):
    """ViewSet actualizado para marcas"""
    queryset = Marca.objects.all()
    serializer_class = MarcaSerializer
    permission_classes = [IsAuthenticated, GenericRolePermission]
    basename = 'marcas'

    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['nombre', 'descripcion']
    ordering_fields = ['nombre', 'created_at']
    ordering = ['nombre']

    # ✅ CORRECCIÓN
    def get_queryset(self):
        queryset = super().get_queryset()
        incluir_inactivos = self.request.query_params.get('incluir_inactivos', 'false').lower() == 'true'

        if not incluir_inactivos:
            queryset = queryset.filter(activo=True)

        return queryset

    @action(detail=True, methods=['post'])
    def toggle_activo(self, request, pk=None):
        """Activar/desactivar marca"""
        marca = self.get_object()
        marca.activo = not marca.activo
        marca.save()

        return Response({
            'message': f'Marca {marca.nombre} {"activada" if marca.activo else "desactivada"}',
            'activo': marca.activo
        })

    @action(detail=True, methods=['get'])
    def modelos_activos(self, request, pk=None):
        """Obtener solo modelos activos de la marca"""
        marca = self.get_object()
        modelos = marca.modelo_set.filter(activo=True)
        serializer = ModeloSerializer(modelos, many=True)
        return Response(serializer.data)


class TipoEquipoViewSet(viewsets.ModelViewSet):
    """ViewSet actualizado para tipos de equipo"""
    queryset = TipoEquipo.objects.all()
    serializer_class = TipoEquipoSerializer
    permission_classes = [IsAuthenticated, GenericRolePermission]
    basename = 'tipos-equipo'

    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['nombre', 'descripcion']
    ordering = ['nombre']

    def get_queryset(self):
        queryset = super().get_queryset()
        incluir_inactivos = self.request.query_params.get('incluir_inactivos', 'false').lower() == 'true'

        if not incluir_inactivos:
            queryset = queryset.filter(activo=True)

        return queryset

    @action(detail=True, methods=['post'])
    def toggle_activo(self, request, pk=None):
        """Activar/desactivar componente"""
        componente = self.get_object()
        componente.activo = not componente.activo
        componente.save()

        return Response({
            'message': f'Componente {componente.nombre} {"activado" if componente.activo else "desactivado"}',
            'activo': componente.activo
        })

    @action(detail=True, methods=['get'])
    def modelos_usando(self, request, pk=None):
        """Modelos que usan este componente"""
        componente = self.get_object()
        relaciones = componente.modelocomponente_set.filter(
            modelo__activo=True
        ).select_related('modelo__marca')

        modelos_info = []
        for relacion in relaciones:
            modelos_info.append({
                'modelo_id': relacion.modelo.id,
                'modelo_nombre': f"{relacion.modelo.marca.nombre} {relacion.modelo.nombre}",
                'cantidad_usado': relacion.cantidad,
                'tipo_material': relacion.modelo.get_tipo_material_display()
            })

        return Response({
            'componente': componente.nombre,
            'total_modelos_usando': len(modelos_info),
            'modelos': modelos_info
        })
        incluir_inactivos = self.request.query_params.get('incluir_inactivos', 'false').lower() == 'true'

        if not incluir_inactivos:
            queryset = queryset.filter(activo=True)

        return queryset

    @action(detail=True, methods=['post'])
    def toggle_activo(self, request, pk=None):
        """Activar/desactivar tipo de equipo"""
        tipo = self.get_object()
        tipo.activo = not tipo.activo
        tipo.save()

        return Response({
            'message': f'Tipo de equipo {tipo.nombre} {"activado" if tipo.activo else "desactivado"}',
            'activo': tipo.activo
        })


class ModeloViewSet(viewsets.ModelViewSet):
    """ViewSet actualizado para modelos con soporte de materiales múltiples"""
    queryset = Modelo.objects.all().select_related('marca', 'tipo_equipo')
    serializer_class = ModeloSerializer
    permission_classes = [IsAuthenticated, GenericRolePermission]
    basename = 'modelos'

    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['nombre', 'marca__nombre', 'codigo_modelo']
    ordering_fields = ['nombre', 'codigo_modelo', 'created_at']
    ordering = ['marca__nombre', 'nombre']
    filterset_fields = ['marca', 'tipo_equipo', 'tipo_material', 'activo']

    def get_queryset(self):
        queryset = super().get_queryset()
        incluir_inactivos = self.request.query_params.get('incluir_inactivos', 'false').lower() == 'true'

        if not incluir_inactivos:
            queryset = queryset.filter(activo=True)

        return queryset

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return ModeloSerializer  # Detalle completo
        elif self.action in ['create', 'update', 'partial_update']:
            return ModeloCreateUpdateSerializer  # Para crear/actualizar
        return ModeloSerializer  # Para lista

    @action(detail=True, methods=['get'])
    def materiales_nuevos(self, request, pk=None):
        """Materiales del nuevo sistema unificado por modelo"""
        modelo = self.get_object()
        from .material_views import MaterialListSerializer
        from ..models import Material

        materiales = Material.objects.filter(modelo=modelo)

        # Filtros opcionales
        estado = request.query_params.get('estado')
        almacen_id = request.query_params.get('almacen_id')

        if estado:
            if modelo.tipo_material == 'ONU':
                materiales = materiales.filter(estado_onu=estado)
            else:
                materiales = materiales.filter(estado_general=estado)

        if almacen_id:
            materiales = materiales.filter(almacen_actual_id=almacen_id)

        serializer = MaterialListSerializer(materiales, many=True)
        return Response({
            'modelo': f"{modelo.marca.nombre} {modelo.nombre}",
            'tipo_material': modelo.get_tipo_material_display(),
            'total_materiales': materiales.count(),
            'materiales': serializer.data
        })

    @action(detail=True, methods=['get'])
    def equipos_legacy(self, request, pk=None):
        """Equipos del sistema legacy por modelo"""
        modelo = self.get_object()
        equipos = modelo.equipoonu_set.all()

        # Filtros opcionales
        estado = request.query_params.get('estado')
        if estado:
            equipos = equipos.filter(estado__nombre__icontains=estado)

        serializer = EquipoONUSerializer(equipos, many=True)
        return Response({
            'modelo': f"{modelo.marca.nombre} {modelo.nombre}",
            'total_equipos_legacy': equipos.count(),
            'equipos': serializer.data
        })

    @action(detail=True, methods=['post'])
    def toggle_activo(self, request, pk=None):
        """Activar/desactivar modelo"""
        modelo = self.get_object()
        modelo.activo = not modelo.activo
        modelo.save()

        return Response({
            'message': f'Modelo {modelo.nombre} {"activado" if modelo.activo else "desactivado"}',
            'activo': modelo.activo
        })

    @action(detail=True, methods=['post'])
    def agregar_componente(self, request, pk=None):
        """Agregar componente a un modelo"""
        modelo = self.get_object()
        componente_id = request.data.get('componente_id')
        cantidad = request.data.get('cantidad', 1)

        if not componente_id:
            return Response(
                {'error': 'componente_id es requerido'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            componente = Componente.objects.get(id=componente_id, activo=True)

            # Verificar si ya existe la relación
            relacion, created = ModeloComponente.objects.get_or_create(
                modelo=modelo,
                componente=componente,
                defaults={'cantidad': cantidad}
            )

            if not created:
                relacion.cantidad = cantidad
                relacion.save()
                mensaje = f'Cantidad del componente {componente.nombre} actualizada'
            else:
                mensaje = f'Componente {componente.nombre} agregado al modelo {modelo.nombre}'

            return Response({
                'message': mensaje,
                'componente': {
                    'id': componente.id,
                    'nombre': componente.nombre,
                    'cantidad': cantidad
                }
            })
        except Componente.DoesNotExist:
            return Response(
                {'error': 'Componente no encontrado'},
                status=status.HTTP_404_NOT_FOUND
            )

    @action(detail=True, methods=['delete'])
    def remover_componente(self, request, pk=None):
        """Remover componente de un modelo"""
        modelo = self.get_object()
        componente_id = request.data.get('componente_id')

        if not componente_id:
            return Response(
                {'error': 'componente_id es requerido'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            relacion = ModeloComponente.objects.get(
                modelo=modelo,
                componente_id=componente_id
            )
            componente_nombre = relacion.componente.nombre
            relacion.delete()

            return Response({
                'message': f'Componente {componente_nombre} removido del modelo {modelo.nombre}'
            })
        except ModeloComponente.DoesNotExist:
            return Response(
                {'error': 'El componente no está asignado a este modelo'},
                status=status.HTTP_404_NOT_FOUND
            )

    @action(detail=False, methods=['post'])
    def agregar_masivo(self, request):
        """Agregar múltiples componentes a un modelo"""
        modelo_id = request.data.get('modelo_id')
        componentes_data = request.data.get('componentes', [])  # [{'componente_id': 1, 'cantidad': 2}]

        if not modelo_id or not componentes_data:
            return Response(
                {'error': 'modelo_id y componentes son requeridos'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            modelo = Modelo.objects.get(id=modelo_id, activo=True)
        except Modelo.DoesNotExist:
            return Response(
                {'error': 'Modelo no encontrado'},
                status=status.HTTP_404_NOT_FOUND
            )

        with transaction.atomic():
            # Eliminar componentes existentes
            ModeloComponente.objects.filter(modelo=modelo).delete()

            # Agregar nuevos componentes
            for comp_data in componentes_data:
                ModeloComponente.objects.create(
                    modelo=modelo,
                    componente_id=comp_data['componente_id'],
                    cantidad=comp_data.get('cantidad', 1)
                )

        return Response({
            'message': f'Componentes actualizados para modelo {modelo.nombre}',
            'total_componentes': len(componentes_data)
        })


class EstadoEquipoViewSet(viewsets.ModelViewSet):
    """ViewSet para estados legacy - solo para compatibilidad"""
    queryset = EstadoEquipo.objects.all()
    serializer_class = EstadoEquipoSerializer
    permission_classes = [IsAuthenticated, GenericRolePermission]
    basename = 'estados-equipo'

    filter_backends = [filters.OrderingFilter]
    ordering = ['nombre']

    def get_queryset(self):
        queryset = super().get_queryset()
        incluir_inactivos = self.request.query_params.get('incluir_inactivos', 'false').lower() == 'true'

        if not incluir_inactivos:
            queryset = queryset.filter(activo=True)

        return queryset

    @action(detail=False, methods=['get'])
    def distribucion_legacy(self, request):
        """Distribución de equipos legacy por estado"""
        distribucion = []

        for estado in self.get_queryset():
            cantidad = estado.equipoonu_set.count()
            if cantidad > 0:
                distribucion.append({
                    'estado': estado.nombre,
                    'cantidad': cantidad
                })

        return Response({
            'distribucion_legacy': distribucion,
            'nota': 'Esta es la distribución del sistema legacy. Use el endpoint de materiales para el nuevo sistema.'
        })


class ComponenteViewSet(viewsets.ModelViewSet):
    """ViewSet actualizado para componentes"""
    queryset = Componente.objects.all()
    serializer_class = ComponenteSerializer
    permission_classes = [IsAuthenticated, GenericRolePermission]
    basename = 'componentes'

    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['nombre', 'descripcion']
    ordering = ['nombre']

    def get_queryset(self):
        queryset = super().get_queryset()
        incluir_inactivos = self.request.query_params.get('incluir_inactivos', 'false').lower() == 'true'

        if not incluir_inactivos:
            queryset = queryset.filter(activo=True)

        return queryset

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return ComponenteCreateUpdateSerializer
        return ComponenteSerializer

    @action(detail=True, methods=['post'])
    def toggle_activo(self, request, pk=None):
        """Activar/desactivar componente"""
        componente = self.get_object()
        componente.activo = not componente.activo
        componente.save()

        return Response({
            'message': f'Componente {componente.nombre} {"activado" if componente.activo else "desactivado"}',
            'activo': componente.activo
        })

    @action(detail=True, methods=['get'])
    def modelos_usando(self, request, pk=None):
        """Modelos que usan este componente"""
        componente = self.get_object()
        relaciones = componente.modelocomponente_set.filter(
            modelo__activo=True
        ).select_related('modelo__marca')

        modelos_info = []
        for relacion in relaciones:
            modelos_info.append({
                'modelo_id': relacion.modelo.id,
                'modelo_nombre': f"{relacion.modelo.marca.nombre} {relacion.modelo.nombre}",
                'cantidad_usado': relacion.cantidad,
                'tipo_material': relacion.modelo.tipo_material.nombre if relacion.modelo.tipo_material else 'Sin tipo'
            })

        return Response({
            'componente': componente.nombre,
            'total_modelos_usando': len(modelos_info),
            'modelos': modelos_info
        })

    @action(detail=False, methods=['get'])
    def disponibles_para_modelo(self, request):
        """Componentes disponibles para asignar a un modelo"""
        modelo_id = request.query_params.get('modelo_id')
        componentes = self.get_queryset()

        if modelo_id:
            # Excluir componentes ya asignados al modelo
            componentes = componentes.exclude(modelocomponente__modelo_id=modelo_id)

        serializer = self.get_serializer(componentes, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def estadisticas(self, request):
        """Estadísticas de componentes"""
        queryset = self.get_queryset()

        stats = {
            'total': queryset.count(),
            'activos': queryset.filter(activo=True).count(),
            'inactivos': queryset.filter(activo=False).count(),
            'sin_modelos': queryset.filter(modelocomponente__isnull=True).count(),
            'con_modelos': queryset.filter(modelocomponente__isnull=False).distinct().count(),
        }

        return Response(stats)

    @action(detail=False, methods=['get'])
    def mas_usados(self, request):
        """Componentes más utilizados"""
        from django.db.models import Count

        componentes = self.get_queryset().annotate(
            total_usos=Count('modelocomponente')
        ).filter(total_usos__gt=0).order_by('-total_usos')[:10]

        serializer = self.get_serializer(componentes, many=True)
        return Response(serializer.data)
# En compatibility_views.py

class ModeloComponenteViewSet(viewsets.ModelViewSet):
    """ViewSet para gestión de relaciones modelo-componente"""
    queryset = ModeloComponente.objects.all().select_related('modelo__marca', 'componente')
    serializer_class = ModeloComponenteSerializer
    permission_classes = [IsAuthenticated, GenericRolePermission]
    basename = 'modelo-componentes'

    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['modelo', 'componente']
    search_fields = ['modelo__nombre', 'componente__nombre']

    @action(detail=False, methods=['post'])
    def agregar_masivo(self, request):
        """Agregar múltiples componentes a un modelo"""
        modelo_id = request.data.get('modelo_id')
        componentes_data = request.data.get('componentes', [])  # [{'componente_id': 1, 'cantidad': 2}]

        if not modelo_id or not componentes_data:
            return Response(
                {'error': 'modelo_id y componentes son requeridos'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            modelo = Modelo.objects.get(id=modelo_id, activo=True)
        except Modelo.DoesNotExist:
            return Response(
                {'error': 'Modelo no encontrado'},
                status=status.HTTP_404_NOT_FOUND
            )

        with transaction.atomic():
            # Eliminar componentes existentes
            ModeloComponente.objects.filter(modelo=modelo).delete()

            # Agregar nuevos componentes
            for comp_data in componentes_data:
                ModeloComponente.objects.create(
                    modelo=modelo,
                    componente_id=comp_data['componente_id'],
                    cantidad=comp_data.get('cantidad', 1)
                )

        return Response({
            'message': f'Componentes actualizados para modelo {modelo.nombre}',
            'total_componentes': len(componentes_data)
        })