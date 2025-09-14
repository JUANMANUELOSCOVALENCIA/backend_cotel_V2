# ======================================================
# almacenes/views/lote_views.py - ACTUALIZADO SIN TEXTCHOICES
# Views para gestión de lotes y importación masiva
# ======================================================
import pandas as pd
import re
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
from django_filters.rest_framework import DjangoFilterBackend

from usuarios.permissions import GenericRolePermission
from ..models import (
    Lote, LoteDetalle, EntregaParcialLote, Material, Almacen,
    # CAMBIADO: Importar los modelos en lugar de TextChoices
    TipoIngreso, EstadoLote, TipoMaterial, EstadoMaterialONU, Modelo
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
        'tipo_ingreso', 'estado'  # AGREGADO: incluir las relaciones FK
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
            if detalle.modelo.tipo_material.es_unico:  # CAMBIADO: usar .es_unico
                # Obtener estados ONU y contar materiales en cada estado
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

    @action(detail=True, methods=['post'])
    def agregar_entrega_parcial(self, request, pk=None):
        """Agregar una nueva entrega parcial al lote"""
        lote = self.get_object()

        # CAMBIADO: Verificar usando el modelo EstadoLote
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

        # Verificar permisos especiales (puedes personalizar esto)
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
            # Filtrar por estado según el tipo de material
            if tipo_material_codigo:
                try:
                    tipo_material = TipoMaterial.objects.get(codigo=tipo_material_codigo, activo=True)
                    if tipo_material.es_unico:
                        # Es equipo único (ONU), filtrar por estado_onu
                        try:
                            estado_obj = EstadoMaterialONU.objects.get(codigo=estado, activo=True)
                            materiales = materiales.filter(estado_onu=estado_obj)
                        except EstadoMaterialONU.DoesNotExist:
                            pass
                    else:
                        # Es material general, filtrar por estado_general
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
        # Lotes por estado usando el modelo EstadoLote
        por_estado = {}
        estados = EstadoLote.objects.filter(activo=True)
        for estado in estados:
            count = Lote.objects.filter(estado=estado).count()
            por_estado[estado.nombre] = count

        # Lotes por tipo de ingreso usando el modelo TipoIngreso
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

        # Lotes activos (usando los estados correspondientes)
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


# En almacenes/views/lote_views.py

class ImportacionMasivaView(APIView):
    """View para importación masiva de materiales desde Excel/CSV"""
    permission_classes = [IsAuthenticated, GenericRolePermission]
    parser_classes = [MultiPartParser, FormParser]
    basename = 'lotes'

    def post(self, request, *args, **kwargs):
        """Procesar archivo de importación masiva"""
        print("🔍 === INICIO IMPORTACION MASIVA ===")
        try:
            # Obtener parámetros
            lote_id = request.data.get('lote_id')
            modelo_id = request.data.get('modelo_id')
            item_equipo = request.data.get('item_equipo')
            archivo = request.FILES.get('archivo')
            numero_entrega = request.data.get('numero_entrega')  # ✅ NUEVO PARÁMETRO
            es_validacion = request.data.get('validacion', 'false').lower() == 'true'

            # DEBUGGING INMEDIATO
            print(f"🔍 DEBUG PARAMETROS RECIBIDOS:")
            print(f"   lote_id: '{lote_id}' (tipo: {type(lote_id)})")
            print(f"   modelo_id: '{modelo_id}' (tipo: {type(modelo_id)})")
            print(f"   item_equipo: '{item_equipo}' (tipo: {type(item_equipo)})")
            print(f"   numero_entrega: '{numero_entrega}' (tipo: {type(numero_entrega)})")
            print(f"   archivo: {archivo.name if archivo else 'None'}")
            print(f"   es_validacion: {es_validacion}")

            # Validar parámetros requeridos
            if not all([lote_id, modelo_id, item_equipo, archivo]):
                print(f"❌ Faltan parámetros:")
                print(f"   lote_id presente: {bool(lote_id)}")
                print(f"   modelo_id presente: {bool(modelo_id)}")
                print(f"   item_equipo presente: {bool(item_equipo)}")
                print(f"   archivo presente: {bool(archivo)}")
                return Response({
                    'success': False,
                    'error': 'Faltan parámetros requeridos: lote_id, modelo_id, item_equipo, archivo'
                }, status=status.HTTP_400_BAD_REQUEST)

            # Limpiar y validar ITEM_EQUIPO
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

            # Verificar modelo Material
            print("🔍 Verificando modelo Material...")
            try:
                total_materiales_antes = Material.objects.count()
                materiales_lote_antes = Material.objects.filter(lote_id=lote_id).count()
                print(f"📊 Materiales en sistema: {total_materiales_antes}")
                print(f"📊 Materiales en lote {lote_id}: {materiales_lote_antes}")
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
                fila_num = index + 2  # +2 porque pandas inicia en 0 y hay header
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
                'columna_d_sn_presente': 'D_SN' in df.columns
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

                # ✅ ACTUALIZAR ESTADÍSTICAS DEL LOTE
                try:
                    if lote.cantidad_recibida >= lote.cantidad_total:
                        estado_completa = EstadoLote.objects.get(codigo='RECEPCION_COMPLETA', activo=True)
                        lote.estado = estado_completa
                    else:
                        estado_parcial = EstadoLote.objects.get(codigo='RECEPCION_PARCIAL', activo=True)
                        lote.estado = estado_parcial
                    lote.save()
                    print(f"✅ Estado del lote actualizado: {lote.estado.nombre}")
                except EstadoLote.DoesNotExist:
                    print("⚠️ No se pudo actualizar estado del lote")

                # Actualizar estadísticas del resultado
                resultado['importados'] = importados
                resultado['errores_importacion'] = errores_importacion

            # Verificar resultados finales
            total_materiales_despues = Material.objects.count()
            materiales_lote_despues = Material.objects.filter(lote_id=lote_id).count()
            print(f"📊 Materiales en sistema después: {total_materiales_despues}")
            print(f"📊 Materiales en lote después: {materiales_lote_despues}")
            print(f"🎯 Diferencia: +{materiales_lote_despues - materiales_lote_antes}")

            # ✅ RESPUESTA EXITOSA
            return Response({
                'success': True,
                'message': f'Importación completada: {importados} equipos registrados' +
                           (f' en entrega #{numero_entrega}' if numero_entrega else ''),
                'resultado': resultado
            })

        except Exception as e:
            print(f"💥 ERROR GENERAL: {str(e)}")
            import traceback
            traceback.print_exc()
            return Response({
                'success': False,
                'error': f'Error interno: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        finally:
            print("🔍 === FIN IMPORTACION MASIVA ===")

    def get(self, request, *args, **kwargs):
        """Obtener plantilla de importación y instrucciones"""
        return Response({
            'plantilla': {
                'columnas_requeridas': ['GPON_SN', 'MAC'],
                'columnas_opcionales': ['D_SN'],  # ✅ NUEVO
                'formato_mac': 'XX:XX:XX:XX:XX:XX (mayúsculas, separado por :)',
                'formato_gpon': 'Mínimo 8 caracteres (ej: HWTC12345678)',
                'formato_d_sn': 'Mínimo 6 caracteres si se proporciona (OPCIONAL)',
                'ejemplo': {
                    'GPON_SN': 'HWTC12345678',
                    'MAC': '00:11:22:33:44:55',
                    'D_SN': 'SN123456789 (OPCIONAL)'
                },
                'item_equipo_info': {
                    'descripcion': 'El código ITEM_EQUIPO se configura una vez para todo el lote',
                    'formato': '6-10 dígitos numéricos',
                    'ejemplo': '1234567890'
                }
            },
            'formatos_archivo_soportados': [
                {
                    'descripcion': 'Archivo completo con D_SN',
                    'columnas': 'GPON_SN,MAC,D_SN',
                    'ejemplo': 'HWTC12345678,00:11:22:33:44:55,SN123456789'
                },
                {
                    'descripcion': 'Archivo sin D_SN',
                    'columnas': 'GPON_SN,MAC',
                    'ejemplo': 'HWTC12345678,00:11:22:33:44:55'
                },
                {
                    'descripcion': 'Archivo con D_SN parcial',
                    'columnas': 'GPON_SN,MAC,D_SN',
                    'ejemplo': 'HWTC12345678,00:11:22:33:44:55, (D_SN vacío permitido)'
                }
            ],
            'instrucciones': [
                '1. Usar formato Excel (.xlsx) o CSV',
                '2. Columnas obligatorias: GPON_SN, MAC',
                '3. Columna opcional: D_SN (puede omitirse o estar vacía)',
                '4. GPON_SN: mínimo 8 caracteres',
                '5. MAC: formato XX:XX:XX:XX:XX:XX',
                '6. D_SN: mínimo 6 caracteres si se proporciona',
                '7. No dejar filas vacías entre los datos',
                '8. Verificar que todos los valores sean únicos',
                '9. Máximo 1000 equipos por importación'
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