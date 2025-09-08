# ======================================================
# almacenes/views/base_views.py
# SOLO AlmacenViewSet y ProveedorViewSet
# ======================================================

from rest_framework import viewsets, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend

from usuarios.permissions import GenericRolePermission
from ..models import Almacen, Proveedor
from ..serializers import AlmacenSerializer, ProveedorSerializer


class AlmacenViewSet(viewsets.ModelViewSet):
    """ViewSet para gestión de almacenes"""
    queryset = Almacen.objects.all()
    serializer_class = AlmacenSerializer
    permission_classes = [IsAuthenticated, GenericRolePermission]
    basename = 'almacenes'

    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['tipo', 'ciudad', 'activo']
    search_fields = ['codigo', 'nombre', 'ciudad']
    ordering = ['codigo']

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class ProveedorViewSet(viewsets.ModelViewSet):
    """ViewSet para gestión de proveedores"""
    queryset = Proveedor.objects.all()
    serializer_class = ProveedorSerializer
    permission_classes = [IsAuthenticated, GenericRolePermission]
    basename = 'proveedores'

    filter_backends = [filters.SearchFilter]
    search_fields = ['codigo', 'nombre_comercial']
    ordering = ['nombre_comercial']

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)