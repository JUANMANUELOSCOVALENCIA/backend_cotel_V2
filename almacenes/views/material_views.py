from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from ..permisos import PermisoPorRol, LECTURA_ALMACENES
from django_filters.rest_framework import DjangoFilterBackend
from django_filters import rest_framework as django_filters
from rest_framework.views import APIView

from .. import models
from ..models import Material, TipoMaterial, EstadoMaterialONU, Lote, Almacen, Modelo, InspeccionLaboratorio, \
    HistorialMaterial, TipoIngreso
from ..pagination import CustomPageNumberPagination
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

    # ✅ NUEVOS FILTROS PARA TIPOS DE MATERIAL
    tipo_material_codigo = django_filters.CharFilter(method='filter_tipo_material')
    solo_unicos = django_filters.BooleanFilter(method='filter_solo_unicos')
    solo_no_unicos = django_filters.BooleanFilter(method='filter_solo_no_unicos')

    def filter_tipo_material(self, queryset, name, value):
        """Filtro personalizado para tipo_material por código"""
        if value:
            try:
                tipo = TipoMaterial.objects.get(codigo=value, activo=True)
                return queryset.filter(tipo_material=tipo)
            except TipoMaterial.DoesNotExist:
                return queryset.none()
        return queryset

    # ✅ NUEVO: Filtro para materiales únicos solamente
    def filter_solo_unicos(self, queryset, name, value):
        """Filtro para obtener solo materiales únicos (ONUs)"""
        if value is True:
            return queryset.filter(tipo_material__es_unico=True)
        elif value is False:
            return queryset.filter(tipo_material__es_unico=False)
        return queryset

    # ✅ NUEVO: Filtro para materiales no únicos solamente
    def filter_solo_no_unicos(self, queryset, name, value):
        """Filtro para obtener solo materiales no únicos (cables, etc.)"""
        if value is True:
            return queryset.filter(tipo_material__es_unico=False)
        elif value is False:
            return queryset.filter(tipo_material__es_unico=True)
        return queryset

    class Meta:
        model = Material
        fields = {
            'lote': ['exact'],
            'almacen_actual': ['exact'],
            'modelo': ['exact'],
            'estado_onu': ['exact'],
            'estado_general': ['exact'],
            'tipo_origen': ['exact'],
            # ✅ AGREGAR: Filtro directo por es_unico
            'tipo_material__es_unico': ['exact'],
        }


class MaterialViewSet(viewsets.ModelViewSet):
    """ViewSet para gestión de materiales (ONUs y otros)"""
    queryset = Material.objects.select_related(
        'modelo__marca', 'modelo__tipo_material', 'modelo__unidad_medida', 'almacen_actual',
        'lote__proveedor', 'lote__almacen_destino',  # antes: 2 consultas extra por fila
        'estado_onu', 'estado_general', 'tipo_material', 'tipo_origen'
    ).order_by('-created_at')

    pagination_class = CustomPageNumberPagination
    permission_classes = [PermisoPorRol]
    acciones_permiso = {'busqueda_avanzada': 'leer', 'devolver_a_sector': 'actualizar'}

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

        # Filtro por tipo de material (solo ONUs por defecto, salvo que se pida
        # explícitamente por único/no único, p. ej. la pantalla de materiales no únicos)
        params = self.request.query_params
        por_defecto = None if 'tipo_material__es_unico' in params else 'ONU'
        tipo_material = params.get('tipo_material', por_defecto)
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

        # Estadísticas por estado (ONU + estados generales), en 2 consultas agrupadas
        from django.db.models import Count
        estados_stats = {e.nombre: 0 for e in EstadoMaterialONU.objects.filter(activo=True)}
        for nombre, n in queryset.filter(estado_onu__activo=True).order_by().values_list('estado_onu__nombre').annotate(n=Count('id')):
            estados_stats[nombre] = estados_stats.get(nombre, 0) + n
        for nombre, n in queryset.filter(estado_general__activo=True).order_by().values_list('estado_general__nombre').annotate(n=Count('id')):
            estados_stats[nombre] = estados_stats.get(nombre, 0) + n

        # Estadísticas por almacén (solo los que tienen materiales)
        por_almacen = dict(
            queryset.filter(almacen_actual__activo=True).order_by().values_list('almacen_actual_id').annotate(n=Count('id'))
        )
        almacenes_stats = {
            a.nombre: por_almacen[a.id]
            for a in Almacen.objects.filter(activo=True, id__in=por_almacen.keys())
        }

        # Estadísticas por lote
        lotes_stats = queryset.values(
            'lote__numero_lote'
        ).annotate(
            count=Count('id')
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
    def stock_granel(self, request):
        """
        Stock de materiales a granel (cable, conectores…) agrupado por modelo y almacén.
        Filtros: almacen, modelo, search (nombre del modelo o marca).
        """
        from django.db.models import Count, Sum
        qs = Material.objects.filter(tipo_material__es_unico=False)
        p = request.query_params
        if p.get('almacen'):
            qs = qs.filter(almacen_actual_id=p['almacen'])
        if p.get('modelo'):
            qs = qs.filter(modelo_id=p['modelo'])
        if p.get('search'):
            qs = qs.filter(Q(modelo__nombre__icontains=p['search']) | Q(modelo__marca__nombre__icontains=p['search']))

        filas = {}
        datos = qs.values(
            'modelo_id', 'modelo__nombre', 'modelo__marca__nombre', 'modelo__codigo_modelo',
            'modelo__unidad_medida__simbolo', 'tipo_material__nombre',
            'almacen_actual_id', 'almacen_actual__codigo', 'almacen_actual__nombre',
            'estado_general__codigo', 'estado_general__nombre', 'estado_general__permite_consumo',
        ).annotate(total=Sum('cantidad'), registros=Count('id')).order_by('modelo__nombre', 'almacen_actual__codigo')
        for d in datos:
            clave = (d['modelo_id'], d['almacen_actual_id'])
            fila = filas.setdefault(clave, {
                'modelo': {'id': d['modelo_id'], 'nombre': d['modelo__nombre'], 'marca': d['modelo__marca__nombre'],
                           'codigo_modelo': d['modelo__codigo_modelo'], 'tipo': d['tipo_material__nombre']},
                'unidad': d['modelo__unidad_medida__simbolo'],
                'almacen': {'id': d['almacen_actual_id'], 'codigo': d['almacen_actual__codigo'], 'nombre': d['almacen_actual__nombre']},
                'disponible': 0, 'total': 0, 'registros': 0, 'por_estado': {},
            })
            cant = float(d['total'] or 0)
            fila['total'] += cant
            fila['registros'] += d['registros']
            nombre = d['estado_general__nombre'] or 'Sin estado'
            fila['por_estado'][nombre] = fila['por_estado'].get(nombre, 0) + cant
            if d['estado_general__permite_consumo']:
                fila['disponible'] += cant
        return Response({'results': list(filas.values())})

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
        # Corrección manual de estado: exige motivo y queda en el historial.
        # Los pasos normales (laboratorio, traspasos, devoluciones) tienen su propio flujo.
        material = self.get_object()
        nuevo_estado_id = request.data.get('estado_id')
        motivo = (request.data.get('motivo') or '').strip()

        if not nuevo_estado_id:
            return Response({'error': 'Elige el nuevo estado'}, status=status.HTTP_400_BAD_REQUEST)
        if len(motivo) < 5:
            return Response({'error': 'Indica el motivo del cambio (mínimo 5 caracteres)'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            from ..models import EstadoMaterialGeneral, HistorialMaterial
            if material.tipo_material.es_unico:
                anterior = material.estado_onu
                if anterior and anterior.codigo == 'EN_LABORATORIO':
                    return Response({'error': 'El equipo está en laboratorio: registra el resultado desde Laboratorio.'}, status=status.HTTP_400_BAD_REQUEST)
                nuevo_estado = EstadoMaterialONU.objects.get(id=nuevo_estado_id, activo=True)
                if nuevo_estado.codigo == 'EN_LABORATORIO':
                    return Response({'error': 'Para enviar a laboratorio usa el envío desde el lote o el laboratorio.'}, status=status.HTTP_400_BAD_REQUEST)
                material.estado_onu = nuevo_estado
            else:
                anterior = material.estado_general
                nuevo_estado = EstadoMaterialGeneral.objects.get(id=nuevo_estado_id, activo=True)
                material.estado_general = nuevo_estado

            if anterior and anterior.id == nuevo_estado.id:
                return Response({'error': f'El material ya está en estado {nuevo_estado.nombre}'}, status=status.HTTP_400_BAD_REQUEST)

            with transaction.atomic():
                material.save()
                HistorialMaterial.objects.create(
                    material=material,
                    estado_anterior=(anterior.codigo if anterior else '')[:25],
                    estado_nuevo=nuevo_estado.codigo[:25],
                    almacen_anterior=material.almacen_actual,
                    almacen_nuevo=material.almacen_actual,
                    motivo='Corrección manual de estado',
                    observaciones=motivo,
                    usuario_responsable=request.user,
                )

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

    @action(detail=False, methods=['get'])
    def defectuosos(self, request):
        """Obtener equipos defectuosos para devolver al sector"""
        try:
            estado_defectuoso = EstadoMaterialONU.objects.get(codigo='DEFECTUOSO', activo=True)
            tipo_onu = TipoMaterial.objects.get(codigo='ONU', activo=True)

            materiales = self.get_queryset().filter(
                tipo_material=tipo_onu,
                estado_onu=estado_defectuoso
            ).select_related(
                'lote__sector_solicitante', 'modelo__marca', 'almacen_actual'
            )

            # Filtro opcional por sector
            sector_id = request.query_params.get('sector_id')
            if sector_id:
                materiales = materiales.filter(lote__sector_solicitante_id=sector_id)

            serializer = MaterialListSerializer(materiales, many=True)
            return Response({
                'total': materiales.count(),
                'materiales': serializer.data,
                'estado_filtrado': 'DEFECTUOSO'
            })

        except (EstadoMaterialONU.DoesNotExist, TipoMaterial.DoesNotExist):
            return Response({'error': 'Estados no configurados correctamente'}, status=500)

    @action(detail=False, methods=['post'])
    def devolver_a_sector(self, request):
        """Cambiar equipos defectuosos a DEVUELTO_SECTOR_SOLICITANTE"""
        materiales_ids = request.data.get('materiales_ids', [])
        motivo = request.data.get('motivo', 'Devuelto al sector solicitante para gestión de reposición')

        if not materiales_ids:
            return Response({'error': 'IDs de materiales requeridos'}, status=400)

        try:
            estado_defectuoso = EstadoMaterialONU.objects.get(codigo='DEFECTUOSO', activo=True)
            estado_devuelto = EstadoMaterialONU.objects.get(codigo='DEVUELTO_SECTOR_SOLICITANTE', activo=True)

            # Verificar que todos los materiales estén defectuosos
            materiales = Material.objects.filter(
                id__in=materiales_ids,
                estado_onu=estado_defectuoso,
                tipo_material__es_unico=True
            )

            if materiales.count() != len(materiales_ids):
                return Response({
                    'error': 'Algunos materiales no están en estado DEFECTUOSO o no existen'
                }, status=400)

            with transaction.atomic():
                count = 0
                sectores_afectados = set()

                for material in materiales:
                    # Cambiar estado
                    material.estado_onu = estado_devuelto
                    material.observaciones += f"\n[DEVUELTO SECTOR] {timezone.localdate()} - {motivo}"
                    material.save()

                    # Registrar sector afectado
                    if material.lote.sector_solicitante:
                        sectores_afectados.add(material.lote.sector_solicitante.nombre)

                    # Crear historial
                    HistorialMaterial.objects.create(
                        material=material,
                        estado_anterior='DEFECTUOSO',
                        estado_nuevo='DEVUELTO_SECTOR',
                        almacen_anterior=material.almacen_actual,
                        almacen_nuevo=material.almacen_actual,
                        motivo=f'Devuelto a sector: {material.lote.sector_solicitante.nombre if material.lote.sector_solicitante else "Sin sector"}',
                        observaciones=motivo,
                        usuario_responsable=request.user
                    )
                    count += 1

            return Response({
                'success': True,
                'message': f'{count} equipos devueltos al sector para gestión de reposición',
                'count': count,
                'sectores_afectados': list(sectores_afectados),
                'fecha_devolucion': timezone.localdate()
            })

        except (EstadoMaterialONU.DoesNotExist) as e:
            return Response({'error': f'Estado no configurado: {str(e)}'}, status=500)
        except Exception as e:
            return Response({'error': f'Error interno: {str(e)}'}, status=500)

    @action(detail=False, methods=['get'])
    def devueltos_sector(self, request):
        """Obtener equipos devueltos al sector"""
        try:
            estado_devuelto = EstadoMaterialONU.objects.get(codigo='DEVUELTO_SECTOR_SOLICITANTE', activo=True)
            tipo_onu = TipoMaterial.objects.get(codigo='ONU', activo=True)

            materiales = self.get_queryset().filter(
                tipo_material=tipo_onu,
                estado_onu=estado_devuelto
            ).select_related(
                'lote__sector_solicitante', 'modelo__marca', 'almacen_actual'
            )

            # Filtro opcional por sector
            sector_id = request.query_params.get('sector_id')
            if sector_id:
                materiales = materiales.filter(lote__sector_solicitante_id=sector_id)

            serializer = MaterialListSerializer(materiales, many=True)
            return Response({
                'total': materiales.count(),
                'materiales': serializer.data,
                'estado_filtrado': 'DEVUELTO_SECTOR_SOLICITANTE'
            })

        except (EstadoMaterialONU.DoesNotExist, TipoMaterial.DoesNotExist):
            return Response({'error': 'Estados no configurados correctamente'}, status=500)


# En almacenes/views/material_views.py

class ReingresoMaterialView(APIView):
    """View para manejar reingresos de materiales de reposición"""
    permission_classes = [PermisoPorRol]
    recurso_permiso = 'materiales'
    accion_permiso = 'actualizar'

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