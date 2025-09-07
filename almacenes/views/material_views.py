# ======================================================
# almacenes/views/material_views.py - ACTUALIZADO SIN TEXTCHOICES
# Views para gestión del modelo Material unificado
# ======================================================

from django.db.models import Q, Count
from django.db import transaction
from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend

from usuarios.permissions import GenericRolePermission
from ..models import (
    Material, HistorialMaterial,
    # Modelos de choices (antes TextChoices)
    TipoMaterial, EstadoMaterialONU, EstadoMaterialGeneral, TipoIngreso
)
from ..serializers import (
    MaterialSerializer, MaterialListSerializer, HistorialMaterialSerializer,
    CambioEstadoMaterialSerializer, LaboratorioOperacionSerializer
)


class MaterialViewSet(viewsets.ModelViewSet):
    """ViewSet para gestión completa del modelo Material unificado (ONU + otros)"""
    queryset = Material.objects.all().select_related(
        'modelo__marca', 'tipo_equipo', 'lote__proveedor',
        'almacen_actual', 'traspaso_actual', 'tipo_material',
        'estado_onu', 'estado_general', 'tipo_origen'
    )
    permission_classes = [IsAuthenticated, GenericRolePermission]
    basename = 'materiales'

    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = [
        'tipo_material', 'modelo', 'modelo__marca', 'modelo__tipo_equipo',
        'lote', 'almacen_actual', 'estado_onu', 'estado_general',
        'es_nuevo', 'tipo_origen'
    ]
    search_fields = [
        'codigo_interno', 'mac_address', 'gpon_serial', 'serial_manufacturer',
        'codigo_item_equipo'
    ]
    ordering_fields = ['codigo_interno', 'created_at']
    ordering = ['-created_at']

    def get_serializer_class(self):
        if self.action == 'list':
            return MaterialListSerializer
        return MaterialSerializer

    def get_queryset(self):
        """Filtros adicionales dinámicos"""
        queryset = super().get_queryset()

        # Filtro por disponibilidad
        disponible = self.request.query_params.get('disponible')
        if disponible == 'true':
            queryset = queryset.filter(
                Q(tipo_material__es_unico=True, estado_onu__permite_asignacion=True) |
                Q(tipo_material__es_unico=False, estado_general__permite_consumo=True)
            )

        # Filtro por materiales en laboratorio
        en_laboratorio = self.request.query_params.get('en_laboratorio')
        if en_laboratorio == 'true':
            try:
                estado_lab = EstadoMaterialONU.objects.get(codigo='EN_LABORATORIO', activo=True)
                queryset = queryset.filter(
                    tipo_material__es_unico=True,
                    estado_onu=estado_lab
                )
            except EstadoMaterialONU.DoesNotExist:
                queryset = queryset.none()

        # Filtro por materiales defectuosos
        defectuoso = self.request.query_params.get('defectuoso')
        if defectuoso == 'true':
            try:
                estado_def_onu = EstadoMaterialONU.objects.get(codigo='DEFECTUOSO', activo=True)
                estado_def_gen = EstadoMaterialGeneral.objects.get(codigo='DEFECTUOSO', activo=True)
                queryset = queryset.filter(
                    Q(tipo_material__es_unico=True, estado_onu=estado_def_onu) |
                    Q(tipo_material__es_unico=False, estado_general=estado_def_gen)
                )
            except (EstadoMaterialONU.DoesNotExist, EstadoMaterialGeneral.DoesNotExist):
                queryset = queryset.none()

        # Filtro por materiales nuevos que requieren laboratorio
        requiere_laboratorio = self.request.query_params.get('requiere_laboratorio')
        if requiere_laboratorio == 'true':
            try:
                tipo_nuevo = TipoIngreso.objects.get(codigo='NUEVO', activo=True)
                estado_nuevo = EstadoMaterialONU.objects.get(codigo='NUEVO', activo=True)
                queryset = queryset.filter(
                    tipo_material__es_unico=True,
                    es_nuevo=True,
                    tipo_origen=tipo_nuevo,
                    estado_onu=estado_nuevo
                )
            except (TipoIngreso.DoesNotExist, EstadoMaterialONU.DoesNotExist):
                queryset = queryset.none()

        return queryset

    @action(detail=True, methods=['get'])
    def historial(self, request, pk=None):
        """Obtener historial completo de cambios del material"""
        material = self.get_object()
        historial = material.historial.all().order_by('-fecha_cambio')

        serializer = HistorialMaterialSerializer(historial, many=True)
        return Response({
            'material': {
                'id': material.id,
                'codigo_interno': material.codigo_interno,
                'tipo_material': material.tipo_material.nombre if material.tipo_material else 'Sin tipo',
                'modelo': f"{material.modelo.marca.nombre} {material.modelo.nombre}"
            },
            'historial': serializer.data
        })

    @action(detail=True, methods=['post'])
    def cambiar_estado(self, request, pk=None):
        """Cambiar estado del material con registro en historial"""
        material = self.get_object()

        data = request.data.copy()
        data['material_id'] = material.id

        serializer = CambioEstadoMaterialSerializer(
            data=data,
            context={'request': request}
        )

        if serializer.is_valid():
            material_actualizado = serializer.ejecutar_cambio()

            return Response({
                'message': 'Estado cambiado correctamente',
                'material': MaterialSerializer(material_actualizado).data
            })

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def enviar_laboratorio(self, request, pk=None):
        """Enviar material específico a laboratorio"""
        material = self.get_object()

        if not material.tipo_material.es_unico:
            return Response(
                {'error': 'Solo los equipos únicos pueden enviarse a laboratorio'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            estado_lab = EstadoMaterialONU.objects.get(codigo='EN_LABORATORIO', activo=True)
            if material.estado_onu == estado_lab:
                return Response(
                    {'error': 'El material ya está en laboratorio'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        except EstadoMaterialONU.DoesNotExist:
            return Response(
                {'error': 'Estado de laboratorio no configurado'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        data = {
            'material_id': material.id,
            'accion': 'enviar',
            'observaciones': request.data.get('observaciones', '')
        }

        serializer = LaboratorioOperacionSerializer(data=data)
        if serializer.is_valid():
            material_actualizado = serializer.ejecutar_operacion()

            return Response({
                'message': f'Material {material.codigo_interno} enviado a laboratorio',
                'material': MaterialSerializer(material_actualizado).data
            })

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def retornar_laboratorio(self, request, pk=None):
        """Retornar material de laboratorio con informe"""
        material = self.get_object()

        try:
            estado_lab = EstadoMaterialONU.objects.get(codigo='EN_LABORATORIO', activo=True)
            if material.estado_onu != estado_lab:
                return Response(
                    {'error': 'El material no está en laboratorio'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        except EstadoMaterialONU.DoesNotExist:
            return Response(
                {'error': 'Estado de laboratorio no configurado'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        data = request.data.copy()
        data['material_id'] = material.id
        data['accion'] = 'retornar'

        serializer = LaboratorioOperacionSerializer(data=data)
        if serializer.is_valid():
            material_actualizado = serializer.ejecutar_operacion()

            return Response({
                'message': f'Material {material.codigo_interno} retornado de laboratorio',
                'resultado': 'Exitoso' if serializer.validated_data['resultado_exitoso'] else 'Defectuoso',
                'material': MaterialSerializer(material_actualizado).data
            })

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['post'])
    def busqueda_avanzada(self, request):
        """Búsqueda avanzada con múltiples criterios"""
        criterios = request.data
        queryset = self.get_queryset()

        # Filtros de búsqueda avanzada
        if criterios.get('mac_contains'):
            queryset = queryset.filter(mac_address__icontains=criterios['mac_contains'])

        if criterios.get('serial_contains'):
            queryset = queryset.filter(
                Q(gpon_serial__icontains=criterios['serial_contains']) |
                Q(serial_manufacturer__icontains=criterios['serial_contains'])
            )

        if criterios.get('fecha_desde'):
            queryset = queryset.filter(created_at__gte=criterios['fecha_desde'])

        if criterios.get('fecha_hasta'):
            queryset = queryset.filter(created_at__lte=criterios['fecha_hasta'])

        if criterios.get('solo_defectuosos'):
            try:
                estado_def_onu = EstadoMaterialONU.objects.get(codigo='DEFECTUOSO', activo=True)
                estado_def_gen = EstadoMaterialGeneral.objects.get(codigo='DEFECTUOSO', activo=True)
                queryset = queryset.filter(
                    Q(estado_onu=estado_def_onu) |
                    Q(estado_general=estado_def_gen)
                )
            except (EstadoMaterialONU.DoesNotExist, EstadoMaterialGeneral.DoesNotExist):
                queryset = queryset.none()

        # Paginación
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = MaterialListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = MaterialListSerializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def estadisticas(self, request):
        """Estadísticas generales de materiales"""
        total_materiales = Material.objects.count()

        # Por tipo de material usando el nuevo modelo
        por_tipo = {}
        tipos = TipoMaterial.objects.filter(activo=True)
        for tipo in tipos:
            count = Material.objects.filter(tipo_material=tipo).count()
            por_tipo[tipo.nombre] = count

        # Estados de equipos únicos
        estados_onu = {}
        estados_onu_obj = EstadoMaterialONU.objects.filter(activo=True)
        for estado in estados_onu_obj:
            count = Material.objects.filter(
                tipo_material__es_unico=True,
                estado_onu=estado
            ).count()
            estados_onu[estado.nombre] = count

        # Estados de materiales generales
        estados_general = {}
        estados_general_obj = EstadoMaterialGeneral.objects.filter(activo=True)
        for estado in estados_general_obj:
            count = Material.objects.filter(
                tipo_material__es_unico=False,
                estado_general=estado
            ).count()
            estados_general[estado.nombre] = count

        # Por almacén
        por_almacen = Material.objects.values(
            'almacen_actual__codigo', 'almacen_actual__nombre'
        ).annotate(
            total=Count('id')
        ).order_by('-total')

        # Materiales más antiguos
        antiguos = Material.objects.order_by('created_at')[:10]

        # Materiales en laboratorio hace más de 30 días
        from datetime import datetime, timedelta
        hace_30_dias = datetime.now() - timedelta(days=30)

        try:
            estado_lab = EstadoMaterialONU.objects.get(codigo='EN_LABORATORIO', activo=True)
            laboratorio_antiguos = Material.objects.filter(
                estado_onu=estado_lab,
                fecha_envio_laboratorio__lt=hace_30_dias
            ).count()
        except EstadoMaterialONU.DoesNotExist:
            laboratorio_antiguos = 0

        return Response({
            'totales': {
                'total_materiales': total_materiales,
                'por_tipo': por_tipo,
                'estados_onu': estados_onu,
                'estados_general': estados_general
            },
            'distribucion': {
                'por_almacen': list(por_almacen)
            },
            'alertas': {
                'materiales_antiguos': MaterialListSerializer(antiguos, many=True).data,
                'en_laboratorio_mas_30_dias': laboratorio_antiguos
            }
        })

    @action(detail=False, methods=['get'])
    def disponibles_para_asignacion(self, request):
        """Materiales disponibles para asignación a órdenes de trabajo"""
        # Filtrar solo materiales disponibles usando los nuevos modelos
        try:
            estado_disp_onu = EstadoMaterialONU.objects.get(codigo='DISPONIBLE', activo=True)
            estado_disp_gen = EstadoMaterialGeneral.objects.get(codigo='DISPONIBLE', activo=True)

            materiales = Material.objects.filter(
                Q(tipo_material__es_unico=True, estado_onu=estado_disp_onu) |
                Q(tipo_material__es_unico=False, estado_general=estado_disp_gen)
            )
        except (EstadoMaterialONU.DoesNotExist, EstadoMaterialGeneral.DoesNotExist):
            materiales = Material.objects.none()

        # Filtros opcionales
        tipo_material_id = request.query_params.get('tipo_material_id')
        almacen_id = request.query_params.get('almacen_id')
        marca_id = request.query_params.get('marca_id')
        modelo_id = request.query_params.get('modelo_id')

        if tipo_material_id:
            materiales = materiales.filter(tipo_material_id=tipo_material_id)

        if almacen_id:
            materiales = materiales.filter(almacen_actual_id=almacen_id)

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

    @action(detail=False, methods=['get'])
    def validar_unicidad(self, request):
        """Validar que MAC, GPON Serial y D-SN sean únicos"""
        mac = request.query_params.get('mac')
        gpon_serial = request.query_params.get('gpon_serial')
        d_sn = request.query_params.get('d_sn')
        material_id = request.query_params.get('material_id')  # Para excluir en edición

        errores = []

        if mac:
            query = Material.objects.filter(mac_address=mac.upper())
            if material_id:
                query = query.exclude(id=material_id)
            if query.exists():
                errores.append(f"MAC Address {mac} ya existe")

        if gpon_serial:
            query = Material.objects.filter(gpon_serial=gpon_serial)
            if material_id:
                query = query.exclude(id=material_id)
            if query.exists():
                errores.append(f"GPON Serial {gpon_serial} ya existe")

        if d_sn:
            query = Material.objects.filter(serial_manufacturer=d_sn)
            if material_id:
                query = query.exclude(id=material_id)
            if query.exists():
                errores.append(f"D-SN {d_sn} ya existe")

        return Response({
            'valido': len(errores) == 0,
            'errores': errores
        })

    @action(detail=False, methods=['post'])
    def operacion_masiva(self, request):
        """Operaciones masivas en materiales seleccionados"""
        materiales_ids = request.data.get('materiales_ids', [])
        operacion = request.data.get('operacion')
        parametros = request.data.get('parametros', {})

        if not materiales_ids:
            return Response(
                {'error': 'Debe seleccionar al menos un material'},
                status=status.HTTP_400_BAD_REQUEST
            )

        materiales = Material.objects.filter(id__in=materiales_ids)
        if not materiales.exists():
            return Response(
                {'error': 'No se encontraron materiales válidos'},
                status=status.HTTP_400_BAD_REQUEST
            )

        resultados = {'exitosos': 0, 'fallidos': 0, 'errores': []}

        with transaction.atomic():
            if operacion == 'enviar_laboratorio':
                try:
                    estado_lab = EstadoMaterialONU.objects.get(codigo='EN_LABORATORIO', activo=True)
                except EstadoMaterialONU.DoesNotExist:
                    return Response(
                        {'error': 'Estado de laboratorio no configurado'},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR
                    )

                for material in materiales:
                    try:
                        if (material.tipo_material.es_unico and
                                material.estado_onu != estado_lab):
                            material.enviar_a_laboratorio(usuario=request.user)
                            resultados['exitosos'] += 1
                        else:
                            resultados['errores'].append(
                                f'{material.codigo_interno}: No puede enviarse a laboratorio'
                            )
                            resultados['fallidos'] += 1
                    except Exception as e:
                        resultados['errores'].append(
                            f'{material.codigo_interno}: {str(e)}'
                        )
                        resultados['fallidos'] += 1

            elif operacion == 'cambiar_estado':
                nuevo_estado_id = parametros.get('nuevo_estado_id')
                if not nuevo_estado_id:
                    return Response(
                        {'error': 'Debe especificar el nuevo estado'},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                for material in materiales:
                    try:
                        # Determinar si es estado ONU o general
                        if material.tipo_material.es_unico:
                            try:
                                nuevo_estado = EstadoMaterialONU.objects.get(id=nuevo_estado_id, activo=True)
                                estado_anterior = material.estado_onu.nombre if material.estado_onu else 'Sin estado'
                                material.estado_onu = nuevo_estado
                                estado_nuevo = nuevo_estado.nombre
                            except EstadoMaterialONU.DoesNotExist:
                                resultados['errores'].append(
                                    f'{material.codigo_interno}: Estado inválido para equipo único'
                                )
                                resultados['fallidos'] += 1
                                continue
                        else:
                            try:
                                nuevo_estado = EstadoMaterialGeneral.objects.get(id=nuevo_estado_id, activo=True)
                                estado_anterior = material.estado_general.nombre if material.estado_general else 'Sin estado'
                                material.estado_general = nuevo_estado
                                estado_nuevo = nuevo_estado.nombre
                            except EstadoMaterialGeneral.DoesNotExist:
                                resultados['errores'].append(
                                    f'{material.codigo_interno}: Estado inválido para material general'
                                )
                                resultados['fallidos'] += 1
                                continue

                        material.save()

                        # Crear historial
                        HistorialMaterial.objects.create(
                            material=material,
                            estado_anterior=estado_anterior,
                            estado_nuevo=estado_nuevo,
                            almacen_anterior=material.almacen_actual,
                            almacen_nuevo=material.almacen_actual,
                            motivo='Operación masiva',
                            observaciones=parametros.get('observaciones', ''),
                            usuario_responsable=request.user
                        )

                        resultados['exitosos'] += 1
                    except Exception as e:
                        resultados['errores'].append(
                            f'{material.codigo_interno}: {str(e)}'
                        )
                        resultados['fallidos'] += 1

            else:
                return Response(
                    {'error': f'Operación {operacion} no válida'},
                    status=status.HTTP_400_BAD_REQUEST
                )

        return Response({
            'message': f'Operación masiva {operacion} completada',
            'resultados': resultados
        })