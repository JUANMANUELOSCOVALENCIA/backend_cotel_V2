from decimal import Decimal
from django.contrib.auth import authenticate
from django.utils import timezone
from django.db.models import Q
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters

from .models import (
    Empleado_fdw, Usuario, Permission, Roles, AuditLog,
    crear_log_auditoria
)
from .serializers import (
    ChangePasswordSerializer, PermissionSerializer, RolesSerializer,
    UsuarioManualSerializer, UsuarioListSerializer, UsuarioDetailSerializer,
    EmpleadoDisponibleSerializer, MigrarEmpleadoSerializer, ResetPasswordSerializer,
    AuditLogSerializer
)
from .permissions import GenericRolePermission


class StandardPagination(PageNumberPagination):
    """Paginación estándar"""
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


def get_client_ip(request):
    """Obtener IP del cliente"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def get_user_agent(request):
    """Obtener User Agent del cliente"""
    return request.META.get('HTTP_USER_AGENT', '')


# ========== VIEWS EXISTENTES MEJORADAS ==========

class MigrarUsuarioView(APIView):
    """Vista para migrar usuario desde FDW - SIN AUTENTICACIÓN porque el usuario aún no existe"""
    permission_classes = []  # Sin autenticación - el usuario no puede loguearse aún

    def post(self, request, *args, **kwargs):
        codigocotel = request.data.get('codigocotel')

        if not codigocotel:
            return Response(
                {"error": "El código COTEL es obligatorio."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            codigocotel_decimal = Decimal(str(codigocotel).strip())
        except (ValueError, TypeError):
            return Response(
                {"error": "El código COTEL debe ser un número válido."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            empleado = Empleado_fdw.objects.get(codigocotel=codigocotel_decimal)
        except Empleado_fdw.DoesNotExist:
            return Response(
                {"error": "Código COTEL no encontrado en los empleados."},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception:
            return Response(
                {"error": "Error de conexión con la base de datos de empleados."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        if empleado.estadoempleado != 0:
            return Response(
                {"error": "Empleado inactivo."},
                status=status.HTTP_400_BAD_REQUEST
            )

        codigocotel_int = int(codigocotel_decimal)
        if Usuario.objects.filter(codigocotel=codigocotel_int).exists():
            return Response(
                {"message": "El usuario ya está registrado. Puede hacer login con su código COTEL."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            with transaction.atomic():
                # Obtener rol por defecto
                rol_defecto = Roles.objects.filter(
                    nombre='Usuario Básico',
                    activo=True,
                    eliminado=False
                ).first()

                usuario = Usuario(
                    codigocotel=codigocotel_int,
                    persona=empleado.persona,
                    apellidopaterno=empleado.apellidopaterno,
                    apellidomaterno=empleado.apellidomaterno,
                    nombres=empleado.nombres,
                    estadoempleado=empleado.estadoempleado,
                    fechaingreso=empleado.fechaingreso,
                    rol=rol_defecto,
                    password_changed=False,  # DEBE cambiar password en primer login
                    password_reset_required=False
                )

                # CONTRASEÑA INICIAL = CÓDIGO COTEL
                usuario.set_password(str(codigocotel_int))
                usuario.save()

                # Log de auditoría (sin usuario autenticado)
                crear_log_auditoria(
                    usuario=usuario,  # El usuario recién creado
                    accion='MIGRATE_USER',
                    objeto=usuario,
                    detalles={
                        'codigocotel': codigocotel_int,
                        'metodo': 'auto_migration',
                        'rol_asignado': rol_defecto.nombre if rol_defecto else None,
                        'password_inicial': 'codigo_cotel'
                    },
                    ip_address=get_client_ip(request),
                    user_agent=get_user_agent(request)
                )

                return Response({
                    "message": "Usuario migrado exitosamente.",
                    "instrucciones": "Ahora puede hacer login con:",
                    "usuario": str(codigocotel_int),
                    "password": str(codigocotel_int),
                    "nota": "Deberá cambiar su contraseña en el primer login"
                }, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response(
                {"error": f"Error interno al crear el usuario: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class LoginJWTView(APIView):
    """Vista de login con auditoría y control de intentos"""

    def post(self, request, *args, **kwargs):
        codigocotel = request.data.get("codigocotel")
        password = request.data.get("password")

        if not codigocotel or not password:
            return Response(
                {"error": "Código COTEL y contraseña son obligatorios."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            usuario = Usuario.objects.get(codigocotel=codigocotel)
        except Usuario.DoesNotExist:
            return Response(
                {"error": "Usuario no migrado. Diríjase al módulo de migración."},
                status=status.HTTP_404_NOT_FOUND
            )

        # Verificar si está bloqueado
        if usuario.esta_bloqueado:
            return Response(
                {"error": "Usuario bloqueado temporalmente por múltiples intentos fallidos."},
                status=status.HTTP_423_LOCKED
            )

        # Verificar si está eliminado
        if usuario.eliminado:
            return Response(
                {"error": "Usuario inactivo. Contacte al administrador."},
                status=status.HTTP_403_FORBIDDEN
            )

        # Autenticación
        user = authenticate(request, username=codigocotel, password=password)

        if not user:
            # Incrementar intentos fallidos
            usuario.incrementar_intentos_fallidos()

            # Log de intento fallido
            crear_log_auditoria(
                usuario=usuario,
                accion='LOGIN',
                objeto=usuario,
                detalles={
                    'exitoso': False,
                    'intento_numero': usuario.intentos_login_fallidos,
                    'razon': 'credenciales_invalidas'
                },
                ip_address=get_client_ip(request),
                user_agent=get_user_agent(request)
            )

            return Response(
                {"error": "Credenciales inválidas."},
                status=status.HTTP_401_UNAUTHORIZED
            )

        # Login exitoso
        usuario.reset_intentos_fallidos()
        usuario.ultimo_login_ip = get_client_ip(request)
        usuario.save()

        # Generar tokens
        refresh = RefreshToken.for_user(user)
        access_token = str(refresh.access_token)

        # Log de login exitoso
        crear_log_auditoria(
            usuario=user,
            accion='LOGIN',
            objeto=user,
            detalles={
                'exitoso': True,
                'requiere_cambio_password': user.requiere_cambio_password
            },
            ip_address=get_client_ip(request),
            user_agent=get_user_agent(request)
        )

        # Verificar si debe cambiar contraseña
        if user.requiere_cambio_password:
            return Response({
                "redirect_to_password_change": True,
                "access": access_token,
                "user_data": {
                    "nombres": user.nombres,
                    "apellidopaterno": user.apellidopaterno,
                    "apellidomaterno": user.apellidomaterno,
                    "codigocotel": user.codigocotel,
                    "password_changed": user.password_changed,
                    "password_reset_required": user.password_reset_required,
                    "rol": user.rol.nombre if user.rol else None,
                    "permisos": list(user.rol.permisos.filter(
                        activo=True, eliminado=False
                    ).values("recurso", "accion")) if user.rol else []
                }
            }, status=status.HTTP_200_OK)

        return Response({
            "refresh": str(refresh),
            "access": access_token,
            "user_data": {
                "nombres": user.nombres,
                "apellidopaterno": user.apellidopaterno,
                "apellidomaterno": user.apellidomaterno,
                "codigocotel": user.codigocotel,
                "password_changed": user.password_changed,
                "password_reset_required": user.password_reset_required,
                "rol": user.rol.nombre if user.rol else None,
                "permisos": list(user.rol.permisos.filter(
                    activo=True, eliminado=False
                ).values("recurso", "accion")) if user.rol else []
            }
        }, status=status.HTTP_200_OK)


class ChangePasswordView(APIView):
    """Vista para cambio de contraseña"""
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        serializer = ChangePasswordSerializer(
            data=request.data,
            context={'request': request}
        )

        if serializer.is_valid():
            user = request.user
            old_password = serializer.validated_data['old_password']

            if not user.check_password(old_password):
                return Response(
                    {"error": "La contraseña actual es incorrecta"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Cambiar contraseña
            serializer.save(user)

            # Generar nuevos tokens
            refresh = RefreshToken.for_user(user)

            return Response({
                "message": "Contraseña actualizada exitosamente",
                "refresh": str(refresh),
                "access": str(refresh.access_token),
                "password_changed": user.password_changed,
                "password_reset_required": user.password_reset_required
            }, status=status.HTTP_200_OK)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class LogoutView(APIView):
    """Vista para logout con auditoría"""
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        try:
            # Log de auditoría
            crear_log_auditoria(
                usuario=request.user,
                accion='LOGOUT',
                objeto=request.user,
                detalles={'logout_exitoso': True},
                ip_address=get_client_ip(request),
                user_agent=get_user_agent(request)
            )

            return Response(
                {"message": "Logout exitoso"},
                status=status.HTTP_200_OK
            )

        except Exception as e:
            return Response(
                {"error": f"Error durante logout: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


# ========== VIEWSETS PRINCIPALES ==========

class AuditLogViewSet(ModelViewSet):
    """ViewSet para consulta de logs de auditoría"""
    queryset = AuditLog.objects.all().select_related('usuario')
    serializer_class = AuditLogSerializer
    permission_classes = [IsAuthenticated, GenericRolePermission]
    pagination_class = StandardPagination
    basename = 'logs'
    http_method_names = ['get']  # Solo lectura
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['accion', 'app_label', 'model_name', 'usuario']
    search_fields = ['objeto_representacion', 'detalles']
    ordering_fields = ['fecha_hora']
    ordering = ['-fecha_hora']

    def get_queryset(self):
        """Filtros adicionales"""
        queryset = super().get_queryset()

        # Filtro por rango de fechas
        fecha_desde = self.request.query_params.get('fecha_desde', None)
        fecha_hasta = self.request.query_params.get('fecha_hasta', None)

        if fecha_desde:
            queryset = queryset.filter(fecha_hora__gte=fecha_desde)
        if fecha_hasta:
            queryset = queryset.filter(fecha_hora__lte=fecha_hasta)

        # Filtro por IP
        ip = self.request.query_params.get('ip', None)
        if ip:
            queryset = queryset.filter(ip_address=ip)

        return queryset

    @action(detail=False, methods=['get'])
    def estadisticas(self, request):
        """Estadísticas de logs"""
        from django.db.models import Count
        from datetime import timedelta

        total_logs = self.get_queryset().count()

        # Por acción
        por_accion = dict(self.get_queryset().values_list('accion').annotate(
            count=Count('accion')
        ))

        # Últimas 24 horas
        hace_24h = timezone.now() - timedelta(hours=24)
        logs_24h = self.get_queryset().filter(fecha_hora__gte=hace_24h).count()

        return Response({
            'total_logs': total_logs,
            'logs_24h': logs_24h,
            'por_accion': por_accion
        })


class PermissionViewSet(ModelViewSet):
    """ViewSet para gestión de permisos"""
    queryset = Permission.objects.all().order_by('recurso', 'accion')
    serializer_class = PermissionSerializer
    permission_classes = [IsAuthenticated, GenericRolePermission]
    pagination_class = StandardPagination
    basename = 'permisos'
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['recurso', 'accion', 'activo']
    search_fields = ['recurso', 'descripcion']

    def destroy(self, request, *args, **kwargs):
        """Soft delete para permisos"""
        permission = self.get_object()

        if not permission.esta_en_uso():
            permission.delete(user=request.user)

            # Log de auditoría
            crear_log_auditoria(
                usuario=request.user,
                accion='DELETE',
                objeto=permission,
                detalles={'tipo_eliminacion': 'soft_delete'},
                ip_address=get_client_ip(request),
                user_agent=get_user_agent(request)
            )

            return Response(
                {"message": f"Permiso '{permission}' eliminado correctamente"},
                status=status.HTTP_200_OK
            )
        else:
            return Response(
                {"error": f"No se puede eliminar el permiso '{permission}' porque está en uso."},
                status=status.HTTP_400_BAD_REQUEST
            )

    @action(detail=True, methods=['post'])
    def restaurar(self, request, pk=None):
        """Restaurar permiso eliminado"""
        permission = get_object_or_404(Permission.all_objects, pk=pk)

        if not permission.eliminado:
            return Response(
                {"error": "El permiso no está eliminado"},
                status=status.HTTP_400_BAD_REQUEST
            )

        permission.restore()

        # Log de auditoría
        crear_log_auditoria(
            usuario=request.user,
            accion='RESTORE',
            objeto=permission,
            detalles={'accion': 'restaurar'},
            ip_address=get_client_ip(request),
            user_agent=get_user_agent(request)
        )

        return Response(
            {"message": f"Permiso '{permission}' restaurado correctamente"},
            status=status.HTTP_200_OK
        )

    @action(detail=False, methods=['get'])
    def recursos_disponibles(self, request):
        """Listar recursos únicos"""
        recursos = Permission.objects.values_list('recurso', flat=True).distinct().order_by('recurso')
        return Response(list(recursos))

    @action(detail=False, methods=['get'])
    def acciones_disponibles(self, request):
        """Listar acciones válidas"""
        return Response(['crear', 'leer', 'actualizar', 'eliminar'])


class RolesViewSet(ModelViewSet):
    """ViewSet para gestión de roles"""
    queryset = Roles.objects.all().select_related('creado_por').prefetch_related('permisos')
    serializer_class = RolesSerializer
    permission_classes = [IsAuthenticated, GenericRolePermission]
    pagination_class = StandardPagination
    basename = 'roles'
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['activo', 'es_sistema']
    search_fields = ['nombre', 'descripcion']
    ordering = ['nombre']

    def get_queryset(self):
        """Filtros adicionales"""
        queryset = super().get_queryset()

        # Filtro por roles con/sin usuarios
        con_usuarios = self.request.query_params.get('con_usuarios', None)
        if con_usuarios is not None:
            if con_usuarios.lower() == 'true':
                queryset = queryset.filter(usuario__eliminado=False).distinct()
            elif con_usuarios.lower() == 'false':
                queryset = queryset.filter(usuario__isnull=True)

        return queryset

    def destroy(self, request, *args, **kwargs):
        """Soft delete para roles"""
        rol = self.get_object()

        if rol.puede_eliminar():
            rol.delete(user=request.user)

            # Log de auditoría
            crear_log_auditoria(
                usuario=request.user,
                accion='DELETE',
                objeto=rol,
                detalles={'tipo_eliminacion': 'soft_delete'},
                ip_address=get_client_ip(request),
                user_agent=get_user_agent(request)
            )

            return Response(
                {"message": f"Rol '{rol.nombre}' eliminado correctamente"},
                status=status.HTTP_200_OK
            )
        else:
            if rol.es_sistema:
                mensaje = f"No se puede eliminar el rol '{rol.nombre}' porque es un rol del sistema."
            else:
                mensaje = f"No se puede eliminar el rol '{rol.nombre}' porque tiene usuarios asignados."

            return Response(
                {"error": mensaje},
                status=status.HTTP_400_BAD_REQUEST
            )

    @action(detail=True, methods=['post'])
    def restaurar(self, request, pk=None):
        """Restaurar rol eliminado"""
        rol = get_object_or_404(Roles.all_objects, pk=pk)

        if not rol.eliminado:
            return Response(
                {"error": "El rol no está eliminado"},
                status=status.HTTP_400_BAD_REQUEST
            )

        rol.restore()

        # Log de auditoría
        crear_log_auditoria(
            usuario=request.user,
            accion='RESTORE',
            objeto=rol,
            detalles={'accion': 'restaurar'},
            ip_address=get_client_ip(request),
            user_agent=get_user_agent(request)
        )

        return Response(
            {"message": f"Rol '{rol.nombre}' restaurado correctamente"},
            status=status.HTTP_200_OK
        )

    @action(detail=True, methods=['get'])
    def usuarios(self, request, pk=None):
        """Usuarios con este rol"""
        rol = self.get_object()
        usuarios = rol.usuario_set.activos()
        serializer = UsuarioListSerializer(usuarios, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def clonar(self, request, pk=None):
        """Clonar rol"""
        rol_original = self.get_object()
        nuevo_nombre = request.data.get('nombre')
        nueva_descripcion = request.data.get('descripcion', '')

        if not nuevo_nombre:
            return Response(
                {"error": "El nombre del nuevo rol es obligatorio"},
                status=status.HTTP_400_BAD_REQUEST
            )

        if Roles.objects.filter(nombre__iexact=nuevo_nombre).exists():
            return Response(
                {"error": f"Ya existe un rol con el nombre '{nuevo_nombre}'"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            with transaction.atomic():
                nuevo_rol = Roles.objects.create(
                    nombre=nuevo_nombre,
                    descripcion=nueva_descripcion,
                    activo=True,
                    creado_por=request.user
                )
                nuevo_rol.permisos.set(rol_original.permisos.filter(
                    activo=True, eliminado=False
                ))

                # Log de auditoría
                crear_log_auditoria(
                    usuario=request.user,
                    accion='CREATE',
                    objeto=nuevo_rol,
                    detalles={
                        'clonado_desde': str(rol_original),
                        'permisos_copiados': nuevo_rol.permisos.count()
                    },
                    ip_address=get_client_ip(request),
                    user_agent=get_user_agent(request)
                )

        except Exception as e:
            return Response(
                {"error": f"Error al clonar el rol: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        serializer = self.get_serializer(nuevo_rol)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class UsuarioViewSet(ModelViewSet):
    """ViewSet para gestión de usuarios"""
    permission_classes = [IsAuthenticated, GenericRolePermission]
    pagination_class = StandardPagination
    basename = 'usuarios'
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['is_active', 'rol', 'estadoempleado']
    search_fields = ['nombres', 'apellidopaterno', 'apellidomaterno', 'codigocotel']
    ordering = ['-fecha_creacion']

    def get_queryset(self):
        """Queryset con filtros"""
        queryset = Usuario.objects.all().select_related('rol', 'creado_por')

        # Filtro por tipo de usuario
        tipo = self.request.query_params.get('tipo', None)
        if tipo == 'manual':
            queryset = queryset.manuales()
        elif tipo == 'migrado':
            queryset = queryset.migrados()

        # Filtro por estado de contraseña
        password_status = self.request.query_params.get('password_status', None)
        if password_status == 'reset_required':
            queryset = queryset.filter(password_reset_required=True)
        elif password_status == 'change_required':
            queryset = queryset.filter(password_changed=False, password_reset_required=False)

        # Filtro por usuarios bloqueados
        bloqueado = self.request.query_params.get('bloqueado', None)
        if bloqueado == 'true':
            queryset = queryset.bloqueados()

        return queryset

    def get_serializer_class(self):
        """Serializer según la acción"""
        if self.action == 'list':
            return UsuarioListSerializer
        elif self.action == 'retrieve':
            return UsuarioDetailSerializer
        return UsuarioManualSerializer

    def destroy(self, request, *args, **kwargs):
        """Soft delete para usuarios"""
        usuario = self.get_object()

        if usuario.puede_eliminar():
            usuario.delete(user=request.user)

            # Log de auditoría
            crear_log_auditoria(
                usuario=request.user,
                accion='DELETE',
                objeto=usuario,
                detalles={'tipo_eliminacion': 'soft_delete'},
                ip_address=get_client_ip(request),
                user_agent=get_user_agent(request)
            )

            return Response(
                {"message": f"Usuario {usuario.nombre_completo} eliminado correctamente"},
                status=status.HTTP_200_OK
            )
        else:
            return Response(
                {"error": "No se puede eliminar este usuario"},
                status=status.HTTP_400_BAD_REQUEST
            )

    @action(detail=True, methods=['post'])
    def restaurar(self, request, pk=None):
        """Restaurar usuario eliminado"""
        usuario = get_object_or_404(Usuario.all_objects, pk=pk)

        if not usuario.eliminado:
            return Response(
                {"error": "El usuario no está eliminado"},
                status=status.HTTP_400_BAD_REQUEST
            )

        usuario.restore()

        # Log de auditoría
        crear_log_auditoria(
            usuario=request.user,
            accion='RESTORE',
            objeto=usuario,
            detalles={'accion': 'restaurar'},
            ip_address=get_client_ip(request),
            user_agent=get_user_agent(request)
        )

        return Response(
            {"message": f"Usuario {usuario.nombre_completo} restaurado correctamente"},
            status=status.HTTP_200_OK
        )

    @action(detail=True, methods=['post'])
    def activar(self, request, pk=None):
        """Activar usuario"""
        usuario = self.get_object()

        if usuario.is_active:
            return Response(
                {"error": "El usuario ya está activo"},
                status=status.HTTP_400_BAD_REQUEST
            )

        usuario.is_active = True
        usuario.save()

        # Log de auditoría
        crear_log_auditoria(
            usuario=request.user,
            accion='ACTIVATE_USER',
            objeto=usuario,
            detalles={'estado_anterior': 'inactivo'},
            ip_address=get_client_ip(request),
            user_agent=get_user_agent(request)
        )

        return Response(
            {"message": f"Usuario {usuario.nombre_completo} activado correctamente"},
            status=status.HTTP_200_OK
        )

    @action(detail=True, methods=['post'])
    def desactivar(self, request, pk=None):
        """Desactivar usuario"""
        usuario = self.get_object()

        if not usuario.is_active:
            return Response(
                {"error": "El usuario ya está desactivado"},
                status=status.HTTP_400_BAD_REQUEST
            )

        if usuario.is_superuser:
            return Response(
                {"error": "No se puede desactivar un superusuario"},
                status=status.HTTP_400_BAD_REQUEST
            )

        usuario.is_active = False
        usuario.save()

        # Log de auditoría
        crear_log_auditoria(
            usuario=request.user,
            accion='DEACTIVATE_USER',
            objeto=usuario,
            detalles={'estado_anterior': 'activo'},
            ip_address=get_client_ip(request),
            user_agent=get_user_agent(request)
        )

        return Response(
            {"message": f"Usuario {usuario.nombre_completo} desactivado correctamente"},
            status=status.HTTP_200_OK
        )

    @action(detail=True, methods=['post'])
    def resetear_password(self, request, pk=None):
        """Resetear contraseña"""
        usuario = self.get_object()

        # Verificar permisos
        if not request.user.tiene_permiso('usuarios', 'actualizar'):
            return Response(
                {"error": "No tiene permisos para resetear contraseñas"},
                status=status.HTTP_403_FORBIDDEN
            )

        motivo = request.data.get('motivo', '')

        if usuario.is_superuser:
            return Response(
                {"error": "No se puede resetear la contraseña de un superusuario"},
                status=status.HTTP_400_BAD_REQUEST
            )

        usuario.resetear_password(admin_user=request.user)

        # Log de auditoría
        crear_log_auditoria(
            usuario=request.user,
            accion='RESET_PASSWORD',
            objeto=usuario,
            detalles={'motivo': motivo},
            ip_address=get_client_ip(request),
            user_agent=get_user_agent(request)
        )

        return Response(
            {"message": f"Contraseña del usuario {usuario.nombre_completo} reseteada correctamente"},
            status=status.HTTP_200_OK
        )

    @action(detail=True, methods=['post'])
    def cambiar_rol(self, request, pk=None):
        """Cambiar rol del usuario"""
        usuario = self.get_object()
        rol_id = request.data.get('rol_id')

        if not rol_id:
            return Response(
                {"error": "El ID del rol es obligatorio"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            nuevo_rol = Roles.objects.get(id=rol_id, activo=True, eliminado=False)
        except Roles.DoesNotExist:
            return Response(
                {"error": "El rol no existe o no está activo"},
                status=status.HTTP_400_BAD_REQUEST
            )

        rol_anterior = usuario.rol.nombre if usuario.rol else None
        usuario.rol = nuevo_rol
        usuario.save()

        # Log de auditoría
        crear_log_auditoria(
            usuario=request.user,
            accion='ASSIGN_ROLE',
            objeto=usuario,
            detalles={
                'rol_anterior': rol_anterior,
                'rol_nuevo': nuevo_rol.nombre
            },
            ip_address=get_client_ip(request),
            user_agent=get_user_agent(request)
        )

        return Response(
            {"message": f"Rol del usuario {usuario.nombre_completo} cambiado a '{nuevo_rol.nombre}'"},
            status=status.HTTP_200_OK
        )

    @action(detail=True, methods=['post'])
    def desbloquear(self, request, pk=None):
        """Desbloquear usuario bloqueado"""
        usuario = self.get_object()

        if not usuario.esta_bloqueado:
            return Response(
                {"error": "El usuario no está bloqueado"},
                status=status.HTTP_400_BAD_REQUEST
            )

        usuario.reset_intentos_fallidos()

        # Log de auditoría
        crear_log_auditoria(
            usuario=request.user,
            accion='UPDATE',
            objeto=usuario,
            detalles={'accion': 'desbloquear_usuario'},
            ip_address=get_client_ip(request),
            user_agent=get_user_agent(request)
        )

        return Response(
            {"message": f"Usuario {usuario.nombre_completo} desbloqueado correctamente"},
            status=status.HTTP_200_OK
        )


class EmpleadosDisponiblesViewSet(ModelViewSet):
    """ViewSet para empleados FDW disponibles para migración - SIN AUTENTICACIÓN"""
    serializer_class = EmpleadoDisponibleSerializer
    permission_classes = []  # Sin autenticación - usuarios nuevos no pueden loguearse
    pagination_class = StandardPagination
    basename = 'empleados-disponibles'
    http_method_names = ['get', 'post']  # Solo lectura y migración
    filter_backends = [filters.SearchFilter]
    search_fields = ['nombres', 'apellidopaterno', 'apellidomaterno', 'codigocotel']

    def get_queryset(self):
        """Solo empleados activos no migrados"""
        try:
            # Obtener códigos ya migrados
            codigos_migrados = Usuario.objects.with_deleted().values_list('codigocotel', flat=True)

            # Empleados activos no migrados
            queryset = Empleado_fdw.objects.filter(
                estadoempleado=0
            ).exclude(
                codigocotel__in=codigos_migrados
            ).order_by('apellidopaterno', 'apellidomaterno', 'nombres')

            return queryset

        except Exception as e:
            print(f"Error al obtener empleados disponibles: {e}")
            return Empleado_fdw.objects.none()

    def create(self, request, *args, **kwargs):
        """Migrar empleado seleccionado"""
        serializer = MigrarEmpleadoSerializer(
            data=request.data,
            context={'request': request}
        )

        if serializer.is_valid():
            usuario = serializer.save()
            response_serializer = UsuarioListSerializer(usuario)
            return Response(
                {
                    "message": f"Empleado {usuario.nombre_completo} migrado correctamente",
                    "usuario": response_serializer.data
                },
                status=status.HTTP_201_CREATED
            )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['get'])
    def estadisticas(self, request):
        """Estadísticas de migración"""
        try:
            total_empleados_fdw = Empleado_fdw.objects.filter(estadoempleado=0).count()
            total_migrados = Usuario.objects.migrados().count()
            total_disponibles = self.get_queryset().count()

            return Response({
                "total_empleados_fdw": total_empleados_fdw,
                "total_migrados": total_migrados,
                "total_disponibles": total_disponibles,
                "porcentaje_migrado": round((total_migrados / total_empleados_fdw * 100),
                                            2) if total_empleados_fdw > 0 else 0
            })
        except Exception as e:
            return Response(
                {"error": "Error al obtener estadísticas"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


# ========== VISTAS ADICIONALES ==========

class ResetPasswordAdminView(APIView):
    """Vista para resetear contraseñas por administrador"""
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        """Resetear contraseña de un usuario por ID"""

        # Verificar permisos específicos
        if not request.user.tiene_permiso('usuarios', 'actualizar'):
            return Response(
                {"error": "No tiene permisos para resetear contraseñas"},
                status=status.HTTP_403_FORBIDDEN
            )

        serializer = ResetPasswordSerializer(
            data=request.data,
            context={'request': request}
        )

        if serializer.is_valid():
            usuario = serializer.save()
            return Response(
                {
                    "message": f"Contraseña del usuario {usuario.nombre_completo} reseteada correctamente",
                    "nuevo_password": "Código COTEL del usuario",
                    "usuario_debe_cambiar": True
                },
                status=status.HTTP_200_OK
            )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class UsuarioPerfilView(APIView):
    """Vista para que el usuario vea y edite su propio perfil"""
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        """Obtener perfil del usuario autenticado"""
        serializer = UsuarioDetailSerializer(request.user)
        return Response(serializer.data)

    def patch(self, request, *args, **kwargs):
        """Actualizar datos básicos del perfil (solo usuarios manuales)"""
        usuario = request.user

        # Solo usuarios manuales pueden editar su información
        if not usuario.es_usuario_manual:
            return Response(
                {"error": "Los usuarios migrados no pueden editar su información personal"},
                status=status.HTTP_403_FORBIDDEN
            )

        # Validar campos permitidos
        campos_permitidos = ['nombres', 'apellidopaterno', 'apellidomaterno']
        datos_actualizacion = {}

        for campo in campos_permitidos:
            if campo in request.data:
                datos_actualizacion[campo] = request.data[campo]

        if not datos_actualizacion:
            return Response(
                {"error": "No se proporcionaron campos válidos para actualizar"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Usar el serializer para validaciones
        serializer = UsuarioManualSerializer(
            usuario,
            data=datos_actualizacion,
            partial=True,
            context={'request': request}
        )

        if serializer.is_valid():
            serializer.save()

            return Response(
                {
                    "message": "Perfil actualizado correctamente",
                    "usuario": UsuarioDetailSerializer(usuario).data
                },
                status=status.HTTP_200_OK
            )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class EstadisticasUsuariosView(APIView):
    """Vista para estadísticas generales del sistema"""
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        """Obtener estadísticas del sistema"""
        try:
            # Estadísticas de usuarios
            total_usuarios = Usuario.objects.count()
            usuarios_activos = Usuario.objects.activos().count()
            usuarios_manuales = Usuario.objects.manuales().count()
            usuarios_migrados = Usuario.objects.migrados().count()
            usuarios_bloqueados = Usuario.objects.bloqueados().count()
            usuarios_password_pendiente = Usuario.objects.password_pendiente().count()

            # Estadísticas de roles
            total_roles = Roles.objects.count()
            roles_activos = Roles.objects.filter(activo=True).count()

            # Estadísticas de permisos
            total_permisos = Permission.objects.count()
            permisos_activos = Permission.objects.filter(activo=True).count()

            # Estadísticas de logs (últimos 30 días)
            hace_30_dias = timezone.now() - timezone.timedelta(days=30)
            logs_30_dias = AuditLog.objects.filter(fecha_hora__gte=hace_30_dias).count()

            return Response({
                "usuarios": {
                    "total": total_usuarios,
                    "activos": usuarios_activos,
                    "inactivos": total_usuarios - usuarios_activos,
                    "manuales": usuarios_manuales,
                    "migrados": usuarios_migrados,
                    "bloqueados": usuarios_bloqueados,
                    "password_pendiente": usuarios_password_pendiente
                },
                "roles": {
                    "total": total_roles,
                    "activos": roles_activos,
                    "inactivos": total_roles - roles_activos
                },
                "permisos": {
                    "total": total_permisos,
                    "activos": permisos_activos,
                    "inactivos": total_permisos - permisos_activos
                },
                "actividad": {
                    "logs_30_dias": logs_30_dias
                }
            })

        except Exception as e:
            return Response(
                {"error": f"Error al obtener estadísticas: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ValidarCodigoCotelView(APIView):
    """Vista para validar disponibilidad de código COTEL"""
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        """Validar si un código COTEL está disponible"""
        codigocotel = request.data.get('codigocotel')

        if not codigocotel:
            return Response(
                {"error": "El código COTEL es obligatorio"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            codigocotel = int(codigocotel)
        except (ValueError, TypeError):
            return Response(
                {"error": "El código COTEL debe ser un número válido"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Verificar en tabla Usuario (incluyendo eliminados)
        if Usuario.objects.with_deleted().filter(codigocotel=codigocotel).exists():
            return Response(
                {"disponible": False, "motivo": "Código ya está en uso"},
                status=status.HTTP_200_OK
            )

        # Verificar en tabla FDW
        try:
            if Empleado_fdw.objects.filter(codigocotel=codigocotel).exists():
                return Response(
                    {"disponible": False, "motivo": "Código existe en sistema de empleados"},
                    status=status.HTTP_200_OK
                )
        except:
            pass

        return Response(
            {"disponible": True, "motivo": "Código disponible"},
            status=status.HTTP_200_OK
        )


class GenerarCodigoCotelView(APIView):
    """Vista para generar código COTEL disponible"""
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        """Generar un código COTEL disponible"""

        # Verificar permisos
        if not request.user.tiene_permiso('usuarios', 'crear'):
            return Response(
                {"error": "No tiene permisos para generar códigos COTEL"},
                status=status.HTTP_403_FORBIDDEN
            )

        try:
            codigo_generado = Usuario.objects.generar_codigo_cotel_disponible()

            return Response(
                {
                    "codigocotel": codigo_generado,
                    "mensaje": f"Código COTEL {codigo_generado} generado y disponible"
                },
                status=status.HTTP_200_OK
            )

        except Exception as e:
            return Response(
                {"error": f"Error al generar código COTEL: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
