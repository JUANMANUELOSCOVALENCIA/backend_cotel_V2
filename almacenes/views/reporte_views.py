# ======================================================
# almacenes/views/reporte_views.py - CORREGIDO
# Views para estadísticas, reportes y dashboards
# ======================================================

from datetime import datetime, timedelta
from django.db.models import Count, Sum, Avg, Q
from django.http import HttpResponse
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
import json

from usuarios.permissions import GenericRolePermission
from ..models import (
    Almacen, Proveedor, Lote, Material, TraspasoAlmacen, DevolucionProveedor,
    TipoMaterial, EstadoMaterialONU, EstadoMaterialGeneral,
    EstadoLote, EstadoTraspaso, EstadoDevolucion
)
# EstadisticasGeneralesSerializer se usa solo para documentación
# Las estadísticas se construyen directamente en las views


class EstadisticasGeneralesView(APIView):
    """Vista para estadísticas generales del sistema completo"""
    permission_classes = [IsAuthenticated, GenericRolePermission]
    basename = 'almacenes'

    def get(self, request):
        """Dashboard ejecutivo con todas las métricas importantes"""

        # ===== ESTADÍSTICAS GENERALES =====
        total_almacenes = Almacen.objects.filter(activo=True).count()
        total_proveedores = Proveedor.objects.filter(activo=True).count()
        total_lotes = Lote.objects.count()
        total_materiales = Material.objects.count()

        # ===== ESTADO DE LOTES =====
        lotes_activos = Lote.objects.filter(
            estado__codigo__in=['ACTIVO', 'RECEPCION_PARCIAL']
        ).count()

        lotes_por_estado = {}
        for estado in EstadoLote.objects.filter(activo=True):
            count = Lote.objects.filter(estado=estado).count()
            lotes_por_estado[estado.nombre] = count

        # ===== OPERACIONES ACTIVAS =====
        traspasos_pendientes = TraspasoAlmacen.objects.filter(
            estado__codigo__in=['PENDIENTE', 'EN_TRANSITO']
        ).count()

        devoluciones_pendientes = DevolucionProveedor.objects.filter(
            estado__codigo__in=['PENDIENTE', 'ENVIADO']
        ).count()

        # ===== MATERIALES EN LABORATORIO =====
        # Obtener tipo de material ONU
        try:
            tipo_onu = TipoMaterial.objects.get(codigo='ONU', activo=True)
            materiales_laboratorio = Material.objects.filter(
                tipo_material=tipo_onu,
                estado_onu__codigo='EN_LABORATORIO'
            ).count()
        except TipoMaterial.DoesNotExist:
            materiales_laboratorio = 0

        # ===== ESTADÍSTICAS POR ALMACÉN =====
        almacenes_stats = []
        for almacen in Almacen.objects.filter(activo=True):
            total = almacen.material_set.count()

            # Materiales disponibles (tanto ONU como generales)
            disponibles = almacen.material_set.filter(
                Q(estado_onu__codigo='DISPONIBLE', estado_onu__activo=True) |
                Q(estado_general__codigo='DISPONIBLE', estado_general__activo=True)
            ).count()

            reservados = almacen.material_set.filter(
                Q(estado_onu__codigo='RESERVADO', estado_onu__activo=True) |
                Q(estado_general__codigo='RESERVADO', estado_general__activo=True)
            ).count()

            en_transito = almacen.material_set.filter(
                traspaso_actual__isnull=False
            ).count()

            defectuosos = almacen.material_set.filter(
                Q(estado_onu__codigo='DEFECTUOSO', estado_onu__activo=True) |
                Q(estado_general__codigo='DEFECTUOSO', estado_general__activo=True)
            ).count()

            # Por tipo de material
            por_tipo = {}
            for tipo in TipoMaterial.objects.filter(activo=True):
                count = almacen.material_set.filter(tipo_material=tipo).count()
                por_tipo[tipo.nombre] = count

            almacenes_stats.append({
                'almacen_id': almacen.id,
                'almacen_nombre': almacen.nombre,
                'almacen_codigo': almacen.codigo,
                'es_principal': almacen.es_principal,
                'total_materiales': total,
                'materiales_disponibles': disponibles,
                'materiales_reservados': reservados,
                'materiales_en_transito': en_transito,
                'materiales_defectuosos': defectuosos,
                'por_tipo_material': por_tipo
            })

        # ===== TOP PROVEEDORES =====
        top_proveedores = []
        for proveedor in Proveedor.objects.filter(activo=True):
            total_lotes = proveedor.lote_set.count()
            total_materiales = Material.objects.filter(lote__proveedor=proveedor).count()

            if total_materiales > 0:
                top_proveedores.append({
                    'proveedor': proveedor.nombre_comercial,
                    'total_lotes': total_lotes,
                    'total_materiales': total_materiales
                })

        top_proveedores.sort(key=lambda x: x['total_materiales'], reverse=True)
        top_proveedores = top_proveedores[:10]

        # ===== MATERIALES PRÓXIMOS A VENCER GARANTÍA =====
        fecha_limite = datetime.now().date() + timedelta(days=30)
        proximos_vencer = Lote.objects.filter(
            fecha_fin_garantia__lte=fecha_limite,
            fecha_fin_garantia__gte=datetime.now().date()
        ).count()

        # ===== RESPUESTA FINAL =====
        data = {
            'totales_sistema': {
                'total_almacenes': total_almacenes,
                'total_proveedores': total_proveedores,
                'total_lotes': total_lotes,
                'total_materiales': total_materiales,
                'lotes_activos': lotes_activos,
                'lotes_por_estado': lotes_por_estado
            },
            'operaciones_activas': {
                'traspasos_pendientes': traspasos_pendientes,
                'devoluciones_pendientes': devoluciones_pendientes,
                'materiales_en_laboratorio': materiales_laboratorio
            },
            'por_almacen': almacenes_stats,
            'top_proveedores': top_proveedores,
            'alertas': {
                'materiales_proximos_vencer': proximos_vencer,
                'traspasos_pendientes': traspasos_pendientes > 0,
                'devoluciones_sin_respuesta': devoluciones_pendientes > 0,
                'materiales_laboratorio_excesivo': materiales_laboratorio > 50
            }
        }

        return Response(data)


class DashboardView(APIView):
    """Dashboard operativo con métricas en tiempo real"""
    permission_classes = [IsAuthenticated, GenericRolePermission]
    basename = 'almacenes'

    def get(self, request):
        """Métricas operativas del día/semana"""

        # Fechas para filtros
        hoy = datetime.now().date()
        hace_7_dias = hoy - timedelta(days=7)
        hace_30_dias = hoy - timedelta(days=30)

        # ===== ACTIVIDAD DEL DÍA =====
        lotes_hoy = Lote.objects.filter(created_at__date=hoy).count()
        materiales_hoy = Material.objects.filter(created_at__date=hoy).count()
        traspasos_hoy = TraspasoAlmacen.objects.filter(created_at__date=hoy).count()

        # ===== ACTIVIDAD DE LA SEMANA =====
        lotes_semana = Lote.objects.filter(created_at__date__gte=hace_7_dias).count()
        materiales_semana = Material.objects.filter(created_at__date__gte=hace_7_dias).count()
        traspasos_semana = TraspasoAlmacen.objects.filter(created_at__date__gte=hace_7_dias).count()

        # ===== LABORATORIO - ACTIVIDAD =====
        laboratorio_retornos_semana = Material.objects.filter(
            fecha_retorno_laboratorio__date__gte=hace_7_dias
        ).count()

        laboratorio_envios_semana = Material.objects.filter(
            fecha_envio_laboratorio__date__gte=hace_7_dias
        ).count()

        # ===== EFICIENCIA DE TRASPASOS =====
        traspasos_completados = TraspasoAlmacen.objects.filter(
            estado__codigo='RECIBIDO',
            fecha_recepcion__date__gte=hace_30_dias
        )

        tiempo_promedio_traspasos = 0
        if traspasos_completados.exists():
            tiempos = []
            for traspaso in traspasos_completados:
                if traspaso.fecha_envio and traspaso.fecha_recepcion:
                    tiempo = (traspaso.fecha_recepcion - traspaso.fecha_envio).days
                    tiempos.append(tiempo)

            if tiempos:
                tiempo_promedio_traspasos = sum(tiempos) / len(tiempos)

        # ===== TENDENCIAS (COMPARACIÓN CON PERÍODO ANTERIOR) =====
        hace_14_dias = hoy - timedelta(days=14)

        lotes_semana_anterior = Lote.objects.filter(
            created_at__date__gte=hace_14_dias,
            created_at__date__lt=hace_7_dias
        ).count()

        tendencia_lotes = 'subida' if lotes_semana > lotes_semana_anterior else 'bajada' if lotes_semana < lotes_semana_anterior else 'estable'

        # ===== TAREAS PENDIENTES =====
        try:
            tipo_onu = TipoMaterial.objects.get(codigo='ONU', activo=True)
            estado_nuevo = EstadoMaterialONU.objects.get(codigo='NUEVO', activo=True)
            estado_en_laboratorio = EstadoMaterialONU.objects.get(codigo='EN_LABORATORIO', activo=True)
            estado_en_transito = EstadoTraspaso.objects.get(codigo='EN_TRANSITO', activo=True)
            estado_pendiente_dev = EstadoDevolucion.objects.get(codigo='PENDIENTE', activo=True)

            tareas_pendientes = {
                'materiales_nuevos_sin_inspeccionar': Material.objects.filter(
                    tipo_material=tipo_onu,
                    es_nuevo=True,
                    estado_onu=estado_nuevo
                ).count(),

                'traspasos_por_confirmar': TraspasoAlmacen.objects.filter(
                    estado=estado_en_transito
                ).count(),

                'devoluciones_por_enviar': DevolucionProveedor.objects.filter(
                    estado=estado_pendiente_dev
                ).count(),

                'materiales_laboratorio_mas_15_dias': Material.objects.filter(
                    tipo_material=tipo_onu,
                    estado_onu=estado_en_laboratorio,
                    fecha_envio_laboratorio__date__lt=hoy - timedelta(days=15)
                ).count()
            }
        except (TipoMaterial.DoesNotExist, EstadoMaterialONU.DoesNotExist,
                EstadoTraspaso.DoesNotExist, EstadoDevolucion.DoesNotExist):
            tareas_pendientes = {
                'materiales_nuevos_sin_inspeccionar': 0,
                'traspasos_por_confirmar': 0,
                'devoluciones_por_enviar': 0,
                'materiales_laboratorio_mas_15_dias': 0
            }

        return Response({
            'actividad_hoy': {
                'lotes_creados': lotes_hoy,
                'materiales_ingresados': materiales_hoy,
                'traspasos_iniciados': traspasos_hoy
            },
            'actividad_semana': {
                'lotes_creados': lotes_semana,
                'materiales_ingresados': materiales_semana,
                'traspasos_realizados': traspasos_semana,
                'laboratorio_envios': laboratorio_envios_semana,
                'laboratorio_retornos': laboratorio_retornos_semana
            },
            'eficiencia': {
                'tiempo_promedio_traspasos_dias': round(tiempo_promedio_traspasos, 1),
                'traspasos_completados_mes': traspasos_completados.count()
            },
            'tendencias': {
                'lotes': {
                    'direccion': tendencia_lotes,
                    'semana_actual': lotes_semana,
                    'semana_anterior': lotes_semana_anterior
                }
            },
            'tareas_pendientes': tareas_pendientes,
            'resumen_alertas': {
                'total_tareas': sum(tareas_pendientes.values()),
                'prioridad_alta': tareas_pendientes['materiales_laboratorio_mas_15_dias'] +
                                  tareas_pendientes['materiales_nuevos_sin_inspeccionar']
            }
        })


class ReporteInventarioView(APIView):
    """Reporte detallado de inventario"""
    permission_classes = [IsAuthenticated, GenericRolePermission]
    basename = 'almacenes'

    def get(self, request):
        """Reporte completo de inventario por almacén y tipo"""

        formato = request.query_params.get('formato', 'json')  # json, csv, excel
        almacen_id = request.query_params.get('almacen_id')
        tipo_material_id = request.query_params.get('tipo_material')

        # Filtrar materiales según criterios
        materiales = Material.objects.all()

        if almacen_id:
            materiales = materiales.filter(almacen_actual_id=almacen_id)

        if tipo_material_id:
            materiales = materiales.filter(tipo_material_id=tipo_material_id)

        # Agrupar por almacén y tipo
        reporte_data = {}

        for almacen in Almacen.objects.filter(activo=True):
            if almacen_id and str(almacen.id) != almacen_id:
                continue

            almacen_materiales = materiales.filter(almacen_actual=almacen)

            if almacen_materiales.exists():
                por_tipo = {}

                for tipo_material in TipoMaterial.objects.filter(activo=True):
                    if tipo_material_id and str(tipo_material.id) != tipo_material_id:
                        continue

                    tipo_materiales = almacen_materiales.filter(tipo_material=tipo_material)

                    if tipo_materiales.exists():
                        # Estados según tipo de material
                        estados_info = {}

                        if tipo_material.es_unico:
                            for estado in EstadoMaterialONU.objects.filter(activo=True):
                                count = tipo_materiales.filter(estado_onu=estado).count()
                                if count > 0:
                                    estados_info[estado.nombre] = count
                        else:
                            for estado in EstadoMaterialGeneral.objects.filter(activo=True):
                                count = tipo_materiales.filter(estado_general=estado).count()
                                if count > 0:
                                    estados_info[estado.nombre] = count

                        por_tipo[tipo_material.nombre] = {
                            'total': tipo_materiales.count(),
                            'por_estado': estados_info,
                            'por_modelo': list(tipo_materiales.values(
                                'modelo__marca__nombre',
                                'modelo__nombre'
                            ).annotate(
                                cantidad=Count('id')
                            ).order_by('-cantidad'))
                        }

                if por_tipo:
                    reporte_data[almacen.nombre] = {
                        'codigo_almacen': almacen.codigo,
                        'total_materiales': almacen_materiales.count(),
                        'por_tipo_material': por_tipo
                    }

        if formato == 'json':
            return Response({
                'fecha_reporte': datetime.now().isoformat(),
                'criterios': {
                    'almacen_id': almacen_id,
                    'tipo_material': tipo_material_id
                },
                'inventario': reporte_data
            })
        elif formato == 'csv':
            return self._generar_csv(reporte_data)
        else:
            return Response({'error': 'Formato no soportado'}, status=400)

    def _generar_csv(self, data):
        """Generar archivo CSV del reporte"""
        import csv
        from io import StringIO

        output = StringIO()
        writer = csv.writer(output)

        # Encabezados
        writer.writerow(['Almacén', 'Código', 'Tipo Material', 'Estado', 'Cantidad'])

        # Datos
        for almacen_nombre, almacen_data in data.items():
            codigo = almacen_data['codigo_almacen']

            for tipo_nombre, tipo_data in almacen_data['por_tipo_material'].items():
                for estado_nombre, cantidad in tipo_data['por_estado'].items():
                    writer.writerow([almacen_nombre, codigo, tipo_nombre, estado_nombre, cantidad])

        # Crear respuesta HTTP
        response = HttpResponse(output.getvalue(), content_type='text/csv')
        response[
            'Content-Disposition'] = f'attachment; filename="inventario_almacenes_{datetime.now().strftime("%Y%m%d")}.csv"'
        return response


class ReporteMovimientosView(APIView):
    """Reporte de movimientos y trazabilidad"""
    permission_classes = [IsAuthenticated, GenericRolePermission]
    basename = 'almacenes'

    def get(self, request):
        """Reporte de movimientos por período"""

        # Parámetros
        fecha_desde = request.query_params.get('fecha_desde')
        fecha_hasta = request.query_params.get('fecha_hasta')
        almacen_id = request.query_params.get('almacen_id')
        tipo_movimiento = request.query_params.get('tipo')  # traspaso, devolucion

        if not fecha_desde or not fecha_hasta:
            return Response(
                {'error': 'Fecha desde y fecha hasta son requeridas'},
                status=400
            )

        movimientos = []

        # ===== TRASPASOS =====
        if not tipo_movimiento or tipo_movimiento == 'traspaso':
            traspasos = TraspasoAlmacen.objects.filter(
                fecha_envio__date__gte=fecha_desde,
                fecha_envio__date__lte=fecha_hasta
            )

            if almacen_id:
                traspasos = traspasos.filter(
                    Q(almacen_origen_id=almacen_id) | Q(almacen_destino_id=almacen_id)
                )

            for traspaso in traspasos:
                movimientos.append({
                    'tipo': 'TRASPASO',
                    'id': traspaso.id,
                    'numero': traspaso.numero_traspaso,
                    'fecha': traspaso.fecha_envio.date(),
                    'origen': traspaso.almacen_origen.nombre,
                    'destino': traspaso.almacen_destino.nombre,
                    'cantidad': traspaso.cantidad_enviada,
                    'estado': traspaso.estado.nombre if traspaso.estado else 'Sin estado',
                    'motivo': traspaso.motivo
                })

        # ===== DEVOLUCIONES =====
        if not tipo_movimiento or tipo_movimiento == 'devolucion':
            devoluciones = DevolucionProveedor.objects.filter(
                fecha_creacion__date__gte=fecha_desde,
                fecha_creacion__date__lte=fecha_hasta
            )

            for devolucion in devoluciones:
                movimientos.append({
                    'tipo': 'DEVOLUCION',
                    'id': devolucion.id,
                    'numero': devolucion.numero_devolucion,
                    'fecha': devolucion.fecha_creacion.date(),
                    'origen': devolucion.lote_origen.almacen_destino.nombre,
                    'destino': devolucion.proveedor.nombre_comercial,
                    'cantidad': devolucion.cantidad_materiales,
                    'estado': devolucion.estado.nombre if devolucion.estado else 'Sin estado',
                    'motivo': devolucion.motivo[:100] + '...' if len(devolucion.motivo) > 100 else devolucion.motivo
                })

        # Ordenar por fecha
        movimientos.sort(key=lambda x: x['fecha'], reverse=True)

        # Estadísticas del período
        total_traspasos = len([m for m in movimientos if m['tipo'] == 'TRASPASO'])
        total_devoluciones = len([m for m in movimientos if m['tipo'] == 'DEVOLUCION'])
        total_materiales_movidos = sum(m['cantidad'] for m in movimientos)

        return Response({
            'periodo': {
                'fecha_desde': fecha_desde,
                'fecha_hasta': fecha_hasta
            },
            'resumen': {
                'total_movimientos': len(movimientos),
                'total_traspasos': total_traspasos,
                'total_devoluciones': total_devoluciones,
                'total_materiales_movidos': total_materiales_movidos
            },
            'movimientos': movimientos
        })


class ReporteGarantiasView(APIView):
    """Reporte de garantías y vencimientos"""
    permission_classes = [IsAuthenticated, GenericRolePermission]
    basename = 'almacenes'

    def get(self, request):
        """Reporte de garantías próximas a vencer"""

        dias_anticipacion = int(request.query_params.get('dias', 30))
        fecha_limite = datetime.now().date() + timedelta(days=dias_anticipacion)

        # Lotes con garantías próximas a vencer
        lotes_vencimiento = Lote.objects.filter(
            fecha_fin_garantia__lte=fecha_limite,
            fecha_fin_garantia__gte=datetime.now().date()
        ).select_related('proveedor', 'almacen_destino')

        # Agrupar por proveedor
        por_proveedor = {}

        for lote in lotes_vencimiento:
            proveedor = lote.proveedor.nombre_comercial

            if proveedor not in por_proveedor:
                por_proveedor[proveedor] = []

            # Calcular días restantes
            dias_restantes = (lote.fecha_fin_garantia - datetime.now().date()).days

            # Materiales del lote por estado
            materiales_lote = lote.material_set.all()
            estados_materiales = {}

            if materiales_lote.exists():
                # Agrupar por estado según tipo de material
                for material in materiales_lote:
                    if material.tipo_material.es_unico:
                        estado = material.estado_onu.nombre if material.estado_onu else 'Sin estado'
                    else:
                        estado = material.estado_general.nombre if material.estado_general else 'Sin estado'

                    estados_materiales[estado] = estados_materiales.get(estado, 0) + 1

            por_proveedor[proveedor].append({
                'lote_id': lote.id,
                'numero_lote': lote.numero_lote,
                'fecha_inicio_garantia': lote.fecha_inicio_garantia,
                'fecha_fin_garantia': lote.fecha_fin_garantia,
                'dias_restantes': dias_restantes,
                'almacen': lote.almacen_destino.nombre,
                'total_materiales': materiales_lote.count(),
                'estados_materiales': estados_materiales,
                'alerta': 'CRITICA' if dias_restantes <= 7 else 'MEDIA' if dias_restantes <= 15 else 'BAJA'
            })

        # Estadísticas generales
        total_lotes = len(lotes_vencimiento)
        lotes_criticos = sum(1 for lote in lotes_vencimiento
                             if (lote.fecha_fin_garantia - datetime.now().date()).days <= 7)

        return Response({
            'criterios': {
                'dias_anticipacion': dias_anticipacion,
                'fecha_limite': fecha_limite
            },
            'resumen': {
                'total_lotes_proximos_vencer': total_lotes,
                'lotes_criticos_7_dias': lotes_criticos,
                'proveedores_afectados': len(por_proveedor)
            },
            'por_proveedor': por_proveedor
        })


class ReporteEficienciaView(APIView):
    """Reporte de eficiencia y KPIs operativos"""
    permission_classes = [IsAuthenticated, GenericRolePermission]
    basename = 'almacenes'

    def get(self, request):
        """KPIs de eficiencia operativa"""

        periodo_dias = int(request.query_params.get('periodo_dias', 30))
        fecha_desde = datetime.now().date() - timedelta(days=periodo_dias)

        # ===== EFICIENCIA DE TRASPASOS =====
        traspasos_periodo = TraspasoAlmacen.objects.filter(
            created_at__date__gte=fecha_desde
        )

        traspasos_completados = traspasos_periodo.filter(
            estado__codigo='RECIBIDO'
        )

        # Tiempo promedio de traspasos
        tiempos_traspaso = []
        for traspaso in traspasos_completados:
            if traspaso.fecha_envio and traspaso.fecha_recepcion:
                tiempo = (traspaso.fecha_recepcion - traspaso.fecha_envio).total_seconds() / 86400  # días
                tiempos_traspaso.append(tiempo)

        tiempo_promedio_traspaso = sum(tiempos_traspaso) / len(tiempos_traspaso) if tiempos_traspaso else 0

        # ===== EFICIENCIA DE LABORATORIO =====
        materiales_laboratorio = Material.objects.filter(
            fecha_envio_laboratorio__date__gte=fecha_desde,
            fecha_retorno_laboratorio__isnull=False
        )

        # Tiempo promedio en laboratorio
        tiempos_laboratorio = []
        for material in materiales_laboratorio:
            if material.fecha_envio_laboratorio and material.fecha_retorno_laboratorio:
                tiempo = (material.fecha_retorno_laboratorio - material.fecha_envio_laboratorio).total_seconds() / 86400
                tiempos_laboratorio.append(tiempo)

        tiempo_promedio_laboratorio = sum(tiempos_laboratorio) / len(tiempos_laboratorio) if tiempos_laboratorio else 0

        # Tasa de éxito del laboratorio
        try:
            estado_disponible = EstadoMaterialONU.objects.get(codigo='DISPONIBLE', activo=True)
            exitosos = materiales_laboratorio.filter(estado_onu=estado_disponible).count()
        except EstadoMaterialONU.DoesNotExist:
            exitosos = 0

        tasa_exito_laboratorio = (
                exitosos / materiales_laboratorio.count() * 100) if materiales_laboratorio.count() > 0 else 0

        # ===== ROTACIÓN DE INVENTARIO =====
        materiales_salida = Material.objects.filter(
            created_at__date__gte=fecha_desde
        ).exclude(
            Q(estado_onu__codigo='DISPONIBLE') |
            Q(estado_general__codigo='DISPONIBLE')
        ).count()

        inventario_promedio = Material.objects.count()
        rotacion_inventario = (materiales_salida / inventario_promedio * 100) if inventario_promedio > 0 else 0

        # ===== EFICIENCIA POR ALMACÉN =====
        eficiencia_almacenes = []

        for almacen in Almacen.objects.filter(activo=True):
            # Traspasos originados desde este almacén
            traspasos_salida = TraspasoAlmacen.objects.filter(
                almacen_origen=almacen,
                created_at__date__gte=fecha_desde
            )

            traspasos_completados_almacen = traspasos_salida.filter(
                estado__codigo='RECIBIDO'
            )

            eficiencia_traspaso = (
                    traspasos_completados_almacen.count() / traspasos_salida.count() * 100
            ) if traspasos_salida.count() > 0 else 100

            eficiencia_almacenes.append({
                'almacen': almacen.nombre,
                'codigo': almacen.codigo,
                'traspasos_iniciados': traspasos_salida.count(),
                'traspasos_completados': traspasos_completados_almacen.count(),
                'eficiencia_traspaso_pct': round(eficiencia_traspaso, 1),
                'materiales_actuales': almacen.material_set.count()
            })

        return Response({
            'periodo_analizado': {
                'dias': periodo_dias,
                'fecha_desde': fecha_desde,
                'fecha_hasta': datetime.now().date()
            },
            'kpis_principales': {
                'tiempo_promedio_traspaso_dias': round(tiempo_promedio_traspaso, 1),
                'tiempo_promedio_laboratorio_dias': round(tiempo_promedio_laboratorio, 1),
                'tasa_exito_laboratorio_pct': round(tasa_exito_laboratorio, 1),
                'rotacion_inventario_pct': round(rotacion_inventario, 1)
            },
            'traspasos': {
                'total_iniciados': traspasos_periodo.count(),
                'total_completados': traspasos_completados.count(),
                'eficiencia_pct': round(
                    (traspasos_completados.count() / traspasos_periodo.count() * 100), 1
                ) if traspasos_periodo.count() > 0 else 100
            },
            'laboratorio': {
                'total_procesados': materiales_laboratorio.count(),
                'exitosos': exitosos,
                'defectuosos': materiales_laboratorio.count() - exitosos,
                'tasa_exito_pct': round(tasa_exito_laboratorio, 1)
            },
            'eficiencia_por_almacen': eficiencia_almacenes
        })