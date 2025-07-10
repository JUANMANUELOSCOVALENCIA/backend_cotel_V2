from decimal import Decimal
from django.contrib.auth import authenticate
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework import status
from django.db.models import Q
from django.db import transaction
from .models import Empleado_fdw, Usuario, Permission, Roles
from .serializers import (
    ChangePasswordSerializer, PermissionSerializer, RolesSerializer,
    UsuarioManualSerializer, UsuarioListSerializer, EmpleadoDisponibleSerializer,
    MigrarEmpleadoSerializer
)
from .permissions import GenericRolePermission


# ========== VIEWS EXISTENTES (MANTENER) ==========

class MigrarUsuarioView(APIView):
    def post(self, request, *args, **kwargs):
        # Obtener el código COTEL enviado desde el frontend
        codigocotel = request.data.get('codigocotel')

        if not codigocotel:
            return Response({"error": "El código COTEL es obligatorio."},
                            status=status.HTTP_400_BAD_REQUEST)

        # Convertir a Decimal (que es como está en la BD)
        try:
            codigocotel_decimal = Decimal(str(codigocotel).strip())
            print(f"🔍 Buscando código COTEL: {codigocotel_decimal} (tipo: {type(codigocotel_decimal)})")
        except (ValueError, TypeError, Exception):
            return Response({"error": "El código COTEL debe ser un número válido."},
                            status=status.HTTP_400_BAD_REQUEST)

        # Debug: Verificar conexión a la tabla FDW
        try:
            total_empleados = Empleado_fdw.objects.count()
            print(f"📊 Total empleados en FDW: {total_empleados}")
        except Exception as e:
            print(f"❌ Error al acceder a la tabla FDW: {str(e)}")
            return Response({"error": "Error de conexión con la base de datos de empleados."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # Buscar el empleado en la tabla FDW usando Decimal
        try:
            empleado = Empleado_fdw.objects.get(codigocotel=codigocotel_decimal)
            print(f"✅ Empleado encontrado: {empleado.nombres} - Estado: {empleado.estadoempleado}")
        except Empleado_fdw.DoesNotExist:
            print(f"❌ Código COTEL {codigocotel_decimal} no encontrado en empleados_activos_fdw")
            # Debug adicional: verificar qué códigos existen
            try:
                todos_codigos = list(Empleado_fdw.objects.values_list('codigocotel', flat=True)[:10])
                print(f"📊 Primeros 10 códigos en la tabla: {todos_codigos}")
            except Exception as e:
                print(f"❌ Error al consultar códigos: {str(e)}")
            return Response({"error": "Código COTEL no encontrado en los empleados."},
                            status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            print(f"❌ Error inesperado al buscar empleado: {str(e)}")
            return Response({"error": "Error interno al buscar el empleado."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # Verificar que el empleado esté activo (estadoempleado == 0)
        if empleado.estadoempleado != 0:
            print(f"❌ Empleado inactivo. Estado actual: {empleado.estadoempleado}")
            return Response({"error": "Empleado inactivo."},
                            status=status.HTTP_400_BAD_REQUEST)

        # Verificar si el usuario ya se ha registrado en la tabla Usuario
        # Aquí usamos int porque en la tabla Usuario es IntegerField
        codigocotel_int = int(codigocotel_decimal)
        if Usuario.objects.filter(codigocotel=codigocotel_int).exists():
            print(f"ℹ️ Usuario {codigocotel_int} ya está registrado")
            return Response({"message": "El usuario ya está registrado."},
                            status=status.HTTP_400_BAD_REQUEST)

        # Crear el usuario
        try:
            usuario = Usuario(
                codigocotel=codigocotel_int,  # Convertir a int para Usuario
                persona=empleado.persona,
                apellidopaterno=empleado.apellidopaterno,
                apellidomaterno=empleado.apellidomaterno,
                nombres=empleado.nombres,
                estadoempleado=empleado.estadoempleado,
                fechaingreso=empleado.fechaingreso,
                rol_id=2  # Asignar rol por defecto con ID 2
            )

            # Usar set_password para encriptar la contraseña correctamente
            usuario.set_password(str(codigocotel_int))
            usuario.save()

            print(f"✅ Usuario {codigocotel_int} creado exitosamente con rol por defecto (ID: 2)")
            return Response({"message": "Usuario creado exitosamente con permisos básicos."},
                            status=status.HTTP_201_CREATED)

        except Exception as e:
            print(f"❌ Error al crear usuario: {str(e)}")
            return Response({"error": "Error interno al crear el usuario."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class LoginJWTView(APIView):
    def post(self, request, *args, **kwargs):
        codigocotel = request.data.get("codigocotel")
        password = request.data.get("password")

        if not codigocotel or not password:
            return Response(
                {"error": "Código COTEL y contraseña son obligatorios."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            # Verificar si el usuario existe
            usuario = Usuario.objects.get(codigocotel=codigocotel)
        except Usuario.DoesNotExist:
            return Response(
                {"error": "Usuario no migrado. Diríjase al módulo de migración."},
                status=status.HTTP_404_NOT_FOUND
            )

        # Autenticación
        user = authenticate(request, username=codigocotel, password=password)
        if not user:
            return Response(
                {"error": "Credenciales inválidas."},
                status=status.HTTP_401_UNAUTHORIZED
            )

        # Generar tokens
        refresh = RefreshToken.for_user(user)
        access_token = str(refresh.access_token)

        # Verificar si debe cambiar contraseña
        if not user.password_changed:
            return Response({
                "redirect_to_password_change": True,
                "access": access_token,
                "user_data": {
                    "nombres": user.nombres,
                    "codigocotel": user.codigocotel,
                    "password_changed": user.password_changed,
                    "rol": user.rol.nombre if user.rol else None,
                    "permisos": list(user.rol.permisos.values("recurso", "accion")) if user.rol else []
                }
            }, status=status.HTTP_200_OK)

        return Response({
            "refresh": str(refresh),
            "access": access_token,
            "user_data": {
                "nombres": user.nombres,
                "codigocotel": user.codigocotel,
                "password_changed": user.password_changed,
                "rol": user.rol.nombre if user.rol else None,
                "permisos": list(user.rol.permisos.values("recurso", "accion")) if user.rol else []
            }
        }, status=status.HTTP_200_OK)


class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        serializer = ChangePasswordSerializer(data=request.data)
        if serializer.is_valid():
            user = request.user
            old_password = serializer.validated_data['old_password']
            new_password = serializer.validated_data['new_password']

            if not user.check_password(old_password):
                return Response(
                    {"error": "La contraseña actual es incorrecta"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            user.set_password(new_password)
            user.password_changed = True
            user.save()

            # Generar nuevos tokens
            refresh = RefreshToken.for_user(user)
            return Response({
                "message": "Contraseña actualizada exitosamente",
                "refresh": str(refresh),
                "access": str(refresh.access_token),
                "password_changed": user.password_changed
            }, status=status.HTTP_200_OK)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# ========== NUEVOS VIEWSETS PARA CRUDs ==========

class PermissionViewSet(ModelViewSet):
    """
    ViewSet para gestión completa de permisos
    """
    queryset = Permission.objects.all().order_by('recurso', 'accion')
    serializer_class = PermissionSerializer
    permission_classes = [IsAuthenticated, GenericRolePermission]
    basename = 'permisos'

    def get_queryset(self):
        """Filtros opcionales para búsqueda"""
        queryset = super().get_queryset()

        # Filtro por recurso
        recurso = self.request.query_params.get('recurso', None)
        if recurso:
            queryset = queryset.filter(recurso__icontains=recurso)

        # Filtro por acción
        accion = self.request.query_params.get('accion', None)
        if accion:
            queryset = queryset.filter(accion=accion)

        # Filtro por uso (si está siendo usado por roles)
        en_uso = self.request.query_params.get('en_uso', None)
        if en_uso is not None:
            if en_uso.lower() == 'true':
                queryset = queryset.filter(roles__isnull=False).distinct()
            elif en_uso.lower() == 'false':
                queryset = queryset.filter(roles__isnull=True)

        return queryset

    def destroy(self, request, *args, **kwargs):
        """Prevenir eliminación si el permiso está en uso"""
        permission = self.get_object()

        if permission.esta_en_uso():
            return Response(
                {"error": f"No se puede eliminar el permiso '{permission}' porque está asignado a uno o más roles."},
                status=status.HTTP_400_BAD_REQUEST
            )

        return super().destroy(request, *args, **kwargs)

    @action(detail=False, methods=['get'])
    def recursos_disponibles(self, request):
        """Listar todos los recursos únicos disponibles"""
        recursos = Permission.objects.values_list('recurso', flat=True).distinct().order_by('recurso')
        return Response(list(recursos))

    @action(detail=False, methods=['get'])
    def acciones_disponibles(self, request):
        """Listar todas las acciones disponibles"""
        acciones = ['crear', 'leer', 'actualizar', 'eliminar']
        return Response(acciones)


class RolesViewSet(ModelViewSet):
    """
    ViewSet para gestión completa de roles
    """
    queryset = Roles.objects.all().order_by('nombre')
    serializer_class = RolesSerializer
    permission_classes = [IsAuthenticated, GenericRolePermission]
    basename = 'roles'

    def get_queryset(self):
        """Filtros opcionales para búsqueda"""
        queryset = super().get_queryset()

        # Filtro por nombre
        nombre = self.request.query_params.get('nombre', None)
        if nombre:
            queryset = queryset.filter(nombre__icontains=nombre)

        # Filtro por estado activo
        activo = self.request.query_params.get('activo', None)
        if activo is not None:
            queryset = queryset.filter(activo=activo.lower() == 'true')

        # Filtro por roles con/sin usuarios
        con_usuarios = self.request.query_params.get('con_usuarios', None)
        if con_usuarios is not None:
            if con_usuarios.lower() == 'true':
                queryset = queryset.filter(usuario__isnull=False).distinct()
            elif con_usuarios.lower() == 'false':
                queryset = queryset.filter(usuario__isnull=True)

        return queryset

    def destroy(self, request, *args, **kwargs):
        """Prevenir eliminación si el rol tiene usuarios asignados"""
        rol = self.get_object()

        if rol.tiene_usuarios():
            return Response(
                {
                    "error": f"No se puede eliminar el rol '{rol.nombre}' porque tiene {rol.cantidad_usuarios()} usuario(s) asignado(s)."},
                status=status.HTTP_400_BAD_REQUEST
            )

        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=['get'])
    def usuarios(self, request, pk=None):
        """Listar usuarios que tienen este rol"""
        rol = self.get_object()
        usuarios = rol.usuario_set.all()
        serializer = UsuarioListSerializer(usuarios, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def clonar(self, request, pk=None):
        """Crear un nuevo rol basado en este rol"""
        rol_original = self.get_object()
        nuevo_nombre = request.data.get('nombre')

        if not nuevo_nombre:
            return Response(
                {"error": "El nombre del nuevo rol es obligatorio"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Verificar que el nombre no exista
        if Roles.objects.filter(nombre=nuevo_nombre).exists():
            return Response(
                {"error": f"Ya existe un rol con el nombre '{nuevo_nombre}'"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Clonar rol
        with transaction.atomic():
            nuevo_rol = Roles.objects.create(
                nombre=nuevo_nombre,
                activo=True
            )
            nuevo_rol.permisos.set(rol_original.permisos.all())

        serializer = self.get_serializer(nuevo_rol)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class UsuarioManualViewSet(ModelViewSet):
    """
    ViewSet para gestión de usuarios manuales
    """
    permission_classes = [IsAuthenticated, GenericRolePermission]
    basename = 'usuarios'

    def get_queryset(self):
        """Queryset que incluye todos los usuarios con filtros"""
        queryset = Usuario.objects.all().select_related('rol').order_by('-fecha_creacion')

        # Filtro por tipo de usuario
        tipo = self.request.query_params.get('tipo', None)
        if tipo == 'manual':
            queryset = queryset.filter(codigocotel__gte=9000, persona__isnull=True)
        elif tipo == 'migrado':
            queryset = queryset.filter(Q(codigocotel__lt=9000) | Q(persona__isnull=False))

        # Filtro por estado activo
        activo = self.request.query_params.get('activo', None)
        if activo is not None:
            queryset = queryset.filter(is_active=activo.lower() == 'true')

        # Filtro por rol
        rol_id = self.request.query_params.get('rol', None)
        if rol_id:
            queryset = queryset.filter(rol_id=rol_id)

        # Filtro por búsqueda en nombres
        search = self.request.query_params.get('search', None)
        if search:
            queryset = queryset.filter(
                Q(nombres__icontains=search) |
                Q(apellidopaterno__icontains=search) |
                Q(apellidomaterno__icontains=search) |
                Q(codigocotel__icontains=search)
            )

        return queryset

    def get_serializer_class(self):
        """Usar serializer apropiado según la acción"""
        if self.action == 'list':
            return UsuarioListSerializer
        return UsuarioManualSerializer

    def destroy(self, request, *args, **kwargs):
        """Soft delete - desactivar en lugar de eliminar"""
        usuario = self.get_object()
        usuario.is_active = False
        usuario.save()

        return Response(
            {"message": f"Usuario {usuario.nombre_completo()} desactivado correctamente"},
            status=status.HTTP_200_OK
        )

    @action(detail=True, methods=['post'])
    def activar(self, request, pk=None):
        """Activar usuario desactivado"""
        usuario = self.get_object()
        usuario.is_active = True
        usuario.save()

        return Response(
            {"message": f"Usuario {usuario.nombre_completo()} activado correctamente"},
            status=status.HTTP_200_OK
        )

    @action(detail=True, methods=['post'])
    def resetear_password(self, request, pk=None):
        """Resetear contraseña al código COTEL"""
        usuario = self.get_object()
        usuario.resetear_password()

        return Response(
            {"message": f"Contraseña del usuario {usuario.nombre_completo()} reseteada correctamente"},
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
            nuevo_rol = Roles.objects.get(id=rol_id, activo=True)
        except Roles.DoesNotExist:
            return Response(
                {"error": "El rol no existe o no está activo"},
                status=status.HTTP_400_BAD_REQUEST
            )

        usuario.rol = nuevo_rol
        usuario.save()

        return Response(
            {"message": f"Rol del usuario {usuario.nombre_completo()} cambiado a '{nuevo_rol.nombre}'"},
            status=status.HTTP_200_OK
        )


class EmpleadosDisponiblesViewSet(ModelViewSet):
    """
    ViewSet para gestión de empleados FDW disponibles para migración
    """
    serializer_class = EmpleadoDisponibleSerializer
    permission_classes = [IsAuthenticated, GenericRolePermission]
    basename = 'empleados-disponibles'
    http_method_names = ['get', 'post']  # Solo lectura y migración

    def get_queryset(self):
        """Solo empleados activos no migrados"""
        try:
            # Obtener códigos ya migrados
            codigos_migrados = Usuario.objects.values_list('codigocotel', flat=True)

            # Empleados activos no migrados
            queryset = Empleado_fdw.objects.filter(
                estadoempleado=0
            ).exclude(
                codigocotel__in=codigos_migrados
            ).order_by('apellidopaterno', 'apellidomaterno', 'nombres')

            # Filtro por búsqueda
            search = self.request.query_params.get('search', None)
            if search:
                queryset = queryset.filter(
                    Q(nombres__icontains=search) |
                    Q(apellidopaterno__icontains=search) |
                    Q(apellidomaterno__icontains=search) |
                    Q(codigocotel__icontains=search)
                )

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
                    "message": f"Empleado {usuario.nombre_completo()} migrado correctamente",
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
            total_migrados = Usuario.objects.filter(persona__isnull=False).count()
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

