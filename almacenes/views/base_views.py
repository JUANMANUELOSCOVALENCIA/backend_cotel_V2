# ======================================================
# almacenes/views/base_views.py
# SOLO AlmacenViewSet y ProveedorViewSet
# ======================================================

from rest_framework import viewsets, filters
from rest_framework.permissions import IsAuthenticated
from ..permisos import PermisoPorRol, LECTURA_ALMACENES
from ..borrado import BorradoSeguroMixin
from django_filters.rest_framework import DjangoFilterBackend

from ..models import Almacen, Proveedor
from ..serializers import AlmacenSerializer, ProveedorSerializer
from ..optimizaciones import optimizar_almacenes, optimizar_proveedores


class AlmacenViewSet(BorradoSeguroMixin, viewsets.ModelViewSet):
    """ViewSet para gestión de almacenes"""
    queryset = Almacen.objects.all()
    serializer_class = AlmacenSerializer
    permission_classes = [PermisoPorRol]
    lectura_alternativa = LECTURA_ALMACENES

    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['tipo', 'ciudad', 'activo']
    search_fields = ['codigo', 'nombre', 'ciudad']
    ordering = ['codigo']

    def get_queryset(self):
        qs = super().get_queryset()
        return optimizar_almacenes(qs) if self.action == 'list' else qs

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class ProveedorViewSet(BorradoSeguroMixin, viewsets.ModelViewSet):
    """ViewSet para gestión de proveedores"""
    queryset = Proveedor.objects.all()
    serializer_class = ProveedorSerializer
    permission_classes = [PermisoPorRol]
    lectura_alternativa = LECTURA_ALMACENES

    filter_backends = [filters.SearchFilter]
    search_fields = ['codigo', 'nombre_comercial']
    ordering = ['nombre_comercial']

    def get_queryset(self):
        qs = super().get_queryset()
        return optimizar_proveedores(qs) if self.action == 'list' else qs

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)