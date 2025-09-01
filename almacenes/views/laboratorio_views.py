# ======================================================
# almacenes/views/laboratorio_views.py
# Views para operaciones de laboratorio
# ======================================================

from datetime import datetime, timedelta
from django.db.models import Count, Q
from django.db import transaction
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import action

from usuarios.permissions import GenericRolePermission
from ..models import (
    Material, Lote, TipoMaterialChoices, EstadoMaterialONUChoices,
    TipoIngresoChoices, EstadoLoteChoices, HistorialMaterial
)
from ..serializers import (
    LaboratorioOperacionSerializer, MaterialListSerializer
)


class LaboratorioView(APIView):
    """View principal para operaciones de laboratorio"""
    permission_classes = [IsAuthenticated, GenericRolePermission]

    def get(self, request):
        """Dashboard de laboratorio con estadísticas"""
        # Materiales actualmente en laboratorio
        en_laboratorio = Material.objects.filter(
            tipo_material=TipoMaterialChoices.ONU,
            estado_onu=EstadoMaterialONUChoices.EN_LABORATORIO
        )

        # Materiales nuevos pendientes de inspección
        pendientes_inspeccion = Material.objects.filter(
            tipo_material=TipoMaterialChoices.ONU,
            es_nuevo=True,
            estado_onu=EstadoMaterialONUChoices.NUEVO
        )

        # Materiales con mucho tiempo en laboratorio (>15 días)
        hace_15_dias = datetime.now() - timedelta(days=15)
        tiempo_excesivo = en_laboratorio.filter(
            fecha_envio_laboratorio__lt=hace_15_dias
        )

        # Estadísticas por período
        hace_30_dias = datetime.now() - timedelta(days=30)
        hace_7_dias = datetime.now() - timedelta(days=7)

        procesados_30_dias = Material.objects.filter(
            fecha_retorno_laboratorio__gte=hace_30_dias
        ).count()

        procesados_7_dias = Material.objects.filter(
            fecha_retorno_laboratorio__gte=hace_7_dias
        ).count()

        # Resultados de inspecciones recientes
        resultados_recientes = Material.objects.filter(
            fecha_retorno_laboratorio__gte=hace_7_dias
        ).aggregate(
            total=Count('id'),
            exitosos=Count('id', filter=Q(estado_onu=EstadoMaterialONUChoices.DISPONIBLE)),
            defectuosos=Count('id', filter=Q(estado_onu=EstadoMaterialONUChoices.DEFECTUOSO))
        )

        return Response({
            'resumen': {
                'en_laboratorio_actual': en_laboratorio.count(),
                'pendientes_inspeccion': pendientes_inspeccion.count(),
                'tiempo_excesivo': tiempo_excesivo.count(),
                'procesados_ultima_semana': procesados_7_dias,
                'procesados_ultimo_mes': procesados_30_dias
            },
            'resultados_recientes': resultados_recientes,
            'alertas': [
                f"{tiempo_excesivo.count()} materiales llevan más de 15 días en laboratorio"
                if tiempo_excesivo.count() > 0 else None,
                f"{pendientes_inspeccion.count()} materiales nuevos requieren inspección inicial"
                if pendientes_inspeccion.count() > 0 else None
            ]
        })

    def post(self, request):
        """Operación individual de laboratorio"""
        serializer = LaboratorioOperacionSerializer(data=request.data)

        if serializer.is_valid():
            material = serializer.ejecutar_operacion()

            accion = serializer.validated_data['accion']
            mensaje = {
                'enviar': f'Material {material.codigo_interno} enviado a laboratorio',
                'retornar': f'Material {material.codigo_interno} retornado de laboratorio'
            }

            return Response({
                'success': True,
                'message': mensaje[accion],
                'material': {
                    'id': material.id,
                    'codigo_interno': material.codigo_interno,
                    'estado_actual': material.get_estado_display()
                }
            })

        return Response({
            'success': False,
            'errors': serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)


class LaboratorioMasivoView(APIView):
    """View para operaciones masivas de laboratorio"""
    permission_classes = [IsAuthenticated, GenericRolePermission]

    def post(self, request):
        """Operaciones masivas en laboratorio"""
        accion = request.data.get('accion')
        criterios = request.data.get('criterios', {})

        if accion == 'enviar_lote_completo':
            return self._enviar_lote_completo(request, criterios)
        elif accion == 'retornar_masivo':
            return self._retornar_masivo(request, criterios)
        elif accion == 'enviar_pendientes':
            return self._enviar_pendientes_inspeccion(request)
        else:
            return Response(
                {'error': 'Acción no válida'},
                status=status.HTTP_400_BAD_REQUEST
            )

    def _enviar_lote_completo(self, request, criterios):
        """Enviar todos los materiales de un lote a laboratorio"""
        lote_id = criterios.get('lote_id')

        if not lote_id:
            return Response(
                {'error': 'ID de lote requerido'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            lote = Lote.objects.get(id=lote_id)
        except Lote.DoesNotExist:
            return Response(
                {'error': 'Lote no encontrado'},
                status=status.HTTP_404_NOT_FOUND
            )

        # Solo lotes nuevos pueden enviarse masivamente
        if lote.tipo_ingreso != TipoIngresoChoices.NUEVO:
            return Response(
                {'error': 'Solo lotes nuevos pueden enviarse masivamente a laboratorio'},
                status=status.HTTP_400_BAD_REQUEST
            )

        materiales_nuevos = Material.objects.filter(
            lote=lote,
            tipo_material=TipoMaterialChoices.ONU,
            es_nuevo=True,
            estado_onu=EstadoMaterialONUChoices.NUEVO
        )

        if not materiales_nuevos.exists():
            return Response(
                {'message': 'No hay materiales nuevos en este lote que requieran laboratorio'},
                status=status.HTTP_200_OK
            )

        with transaction.atomic():
            count = 0
            for material in materiales_nuevos:
                material.enviar_a_laboratorio(usuario=request.user)
                count += 1

        return Response({
            'success': True,
            'message': f'{count} materiales del lote {lote.numero_lote} enviados a laboratorio',
            'materiales_enviados': count,
            'lote': lote.numero_lote
        })

    def _retornar_masivo(self, request, criterios):
        """Retornar materiales masivamente con el mismo resultado"""
        materiales_ids = criterios.get('materiales_ids', [])
        resultado_exitoso = criterios.get('resultado_exitoso', True)
        numero_informe = criterios.get('numero_informe', '')
        detalles_informe = criterios.get('detalles_informe', '')

        if not materiales_ids:
            return Response(
                {'error': 'Lista de materiales requerida'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not numero_informe:
            return Response(
                {'error': 'Número de informe requerido'},
                status=status.HTTP_400_BAD_REQUEST
            )

        materiales = Material.objects.filter(
            id__in=materiales_ids,
            tipo_material=TipoMaterialChoices.ONU,
            estado_onu=EstadoMaterialONUChoices.EN_LABORATORIO
        )

        if not materiales.exists():
            return Response(
                {'error': 'No se encontraron materiales válidos en laboratorio'},
                status=status.HTTP_400_BAD_REQUEST
            )

        with transaction.atomic():
            count_exitosos = 0
            count_defectuosos = 0

            for material in materiales:
                material.retornar_de_laboratorio(
                    resultado_exitoso=resultado_exitoso,
                    informe_numero=numero_informe,
                    detalles=detalles_informe
                )

                if resultado_exitoso:
                    count_exitosos += 1
                else:
                    count_defectuosos += 1

        return Response({
            'success': True,
            'message': f'Retorno masivo completado - Informe: {numero_informe}',
            'resultados': {
                'exitosos': count_exitosos,
                'defectuosos': count_defectuosos,
                'total_procesados': count_exitosos + count_defectuosos
            },
            'informe': numero_informe
        })

    def _enviar_pendientes_inspeccion(self, request):
        """Enviar todos los materiales pendientes de inspección inicial"""
        materiales_pendientes = Material.objects.filter(
            tipo_material=TipoMaterialChoices.ONU,
            es_nuevo=True,
            estado_onu=EstadoMaterialONUChoices.NUEVO
        )

        if not materiales_pendientes.exists():
            return Response(
                {'message': 'No hay materiales pendientes de inspección inicial'},
                status=status.HTTP_200_OK
            )

        with transaction.atomic():
            count = 0
            for material in materiales_pendientes:
                material.enviar_a_laboratorio(usuario=request.user)
                count += 1

        return Response({
            'success': True,
            'message': f'{count} materiales enviados para inspección inicial',
            'materiales_enviados': count
        })


class LaboratorioConsultaView(APIView):
    """View para consultas específicas de laboratorio"""
    permission_classes = [IsAuthenticated, GenericRolePermission]

    def get(self, request):
        """Diferentes tipos de consultas de laboratorio"""
        tipo_consulta = request.query_params.get('tipo', 'en_laboratorio')

        if tipo_consulta == 'en_laboratorio':
            return self._materiales_en_laboratorio(request)
        elif tipo_consulta == 'pendientes_inspeccion':
            return self._pendientes_inspeccion(request)
        elif tipo_consulta == 'tiempo_excesivo':
            return self._tiempo_excesivo(request)
        elif tipo_consulta == 'historial_laboratorio':
            return self._historial_laboratorio(request)
        else:
            return Response(
                {'error': 'Tipo de consulta no válido'},
                status=status.HTTP_400_BAD_REQUEST
            )

    def _materiales_en_laboratorio(self, request):
        """Materiales actualmente en laboratorio"""
        materiales = Material.objects.filter(
            tipo_material=TipoMaterialChoices.ONU,
            estado_onu=EstadoMaterialONUChoices.EN_LABORATORIO
        ).order_by('fecha_envio_laboratorio')

        # Calcular días en laboratorio para cada material
        materiales_data = []
        for material in materiales:
            dias_en_laboratorio = material.dias_en_laboratorio
            materiales_data.append({
                'id': material.id,
                'codigo_interno': material.codigo_interno,
                'mac_address': material.mac_address,
                'modelo': f"{material.modelo.marca.nombre} {material.modelo.nombre}",
                'lote': material.lote.numero_lote,
                'almacen': material.almacen_actual.nombre,
                'fecha_envio': material.fecha_envio_laboratorio,
                'dias_en_laboratorio': dias_en_laboratorio,
                'alerta_tiempo': dias_en_laboratorio > 15
            })

        return Response({
            'total': len(materiales_data),
            'materiales': materiales_data,
            'alertas_tiempo': sum(1 for m in materiales_data if m['alerta_tiempo'])
        })

    def _pendientes_inspeccion(self, request):
        """Materiales nuevos pendientes de inspección inicial"""
        materiales = Material.objects.filter(
            tipo_material=TipoMaterialChoices.ONU,
            es_nuevo=True,
            estado_onu=EstadoMaterialONUChoices.NUEVO
        ).select_related('modelo__marca', 'lote', 'almacen_actual')

        serializer = MaterialListSerializer(materiales, many=True)
        return Response({
            'total': materiales.count(),
            'materiales': serializer.data,
            'mensaje': 'Estos materiales requieren inspección inicial obligatoria'
        })

    def _tiempo_excesivo(self, request):
        """Materiales con tiempo excesivo en laboratorio"""
        dias_limite = int(request.query_params.get('dias_limite', 15))
        fecha_limite = datetime.now() - timedelta(days=dias_limite)

        materiales = Material.objects.filter(
            tipo_material=TipoMaterialChoices.ONU,
            estado_onu=EstadoMaterialONUChoices.EN_LABORATORIO,
            fecha_envio_laboratorio__lt=fecha_limite
        ).select_related('modelo__marca', 'lote', 'almacen_actual')

        materiales_data = []
        for material in materiales:
            materiales_data.append({
                'id': material.id,
                'codigo_interno': material.codigo_interno,
                'mac_address': material.mac_address,
                'modelo': f"{material.modelo.marca.nombre} {material.modelo.nombre}",
                'lote': material.lote.numero_lote,
                'fecha_envio': material.fecha_envio_laboratorio,
                'dias_en_laboratorio': material.dias_en_laboratorio
            })

        return Response({
            'criterio': f'Más de {dias_limite} días en laboratorio',
            'total': len(materiales_data),
            'materiales': materiales_data
        })

    def _historial_laboratorio(self, request):
        """Historial de materiales procesados en laboratorio"""
        dias_historial = int(request.query_params.get('dias', 30))
        fecha_desde = datetime.now() - timedelta(days=dias_historial)

        materiales = Material.objects.filter(
            fecha_retorno_laboratorio__gte=fecha_desde
        ).select_related('modelo__marca', 'lote').order_by('-fecha_retorno_laboratorio')

        historial_data = []
        for material in materiales:
            dias_en_lab = 0
            if material.fecha_envio_laboratorio and material.fecha_retorno_laboratorio:
                dias_en_lab = (material.fecha_retorno_laboratorio - material.fecha_envio_laboratorio).days

            historial_data.append({
                'id': material.id,
                'codigo_interno': material.codigo_interno,
                'mac_address': material.mac_address,
                'modelo': f"{material.modelo.marca.nombre} {material.modelo.nombre}",
                'lote': material.lote.numero_lote,
                'fecha_envio': material.fecha_envio_laboratorio,
                'fecha_retorno': material.fecha_retorno_laboratorio,
                'dias_procesamiento': dias_en_lab,
                'resultado': material.get_estado_display(),
                'exitoso': material.estado_onu == EstadoMaterialONUChoices.DISPONIBLE
            })

        # Estadísticas del período
        total_procesados = len(historial_data)
        exitosos = sum(1 for m in historial_data if m['exitoso'])
        defectuosos = total_procesados - exitosos

        tiempo_promedio = sum(
            m['dias_procesamiento'] for m in historial_data) / total_procesados if total_procesados > 0 else 0

        return Response({
            'periodo': f'Últimos {dias_historial} días',
            'estadisticas': {
                'total_procesados': total_procesados,
                'exitosos': exitosos,
                'defectuosos': defectuosos,
                'porcentaje_exito': round((exitosos / total_procesados * 100), 2) if total_procesados > 0 else 0,
                'tiempo_promedio_dias': round(tiempo_promedio, 1)
            },
            'historial': historial_data
        })