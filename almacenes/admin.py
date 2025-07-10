
# Register your models here.
from django.contrib import admin
from .models import (
    Marca, TipoEquipo, Componente, EstadoEquipo, Modelo,
    ModeloComponente, Lote, LoteDetalle, EquipoONU, EquipoServicio
)

@admin.register(Marca)
class MarcaAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'descripcion', 'created_at']
    search_fields = ['nombre']
    ordering = ['nombre']

@admin.register(TipoEquipo)
class TipoEquipoAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'descripcion', 'created_at']
    search_fields = ['nombre']
    ordering = ['nombre']

@admin.register(Componente)
class ComponenteAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'descripcion', 'created_at']
    search_fields = ['nombre']
    ordering = ['nombre']

@admin.register(EstadoEquipo)
class EstadoEquipoAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'descripcion', 'created_at']
    search_fields = ['nombre']
    ordering = ['nombre']

class ModeloComponenteInline(admin.TabularInline):
    model = ModeloComponente
    extra = 0

@admin.register(Modelo)
class ModeloAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'marca', 'tipo_equipo', 'codigo_modelo', 'created_at']
    list_filter = ['marca', 'tipo_equipo']
    search_fields = ['nombre', 'marca__nombre', 'codigo_modelo']
    inlines = [ModeloComponenteInline]
    ordering = ['marca__nombre', 'nombre']

class LoteDetalleInline(admin.TabularInline):
    model = LoteDetalle
    extra = 0

@admin.register(Lote)
class LoteAdmin(admin.ModelAdmin):
    list_display = ['numero_lote', 'proveedor', 'tipo_servicio', 'fecha_ingreso']
    list_filter = ['tipo_servicio', 'fecha_ingreso']
    search_fields = ['numero_lote', 'proveedor']
    inlines = [LoteDetalleInline]
    ordering = ['-fecha_ingreso']

@admin.register(EquipoONU)
class EquipoONUAdmin(admin.ModelAdmin):
    list_display = ['codigo_interno', 'modelo', 'mac_address', 'estado', 'fecha_ingreso']
    list_filter = ['modelo__marca', 'tipo_equipo', 'estado', 'fecha_ingreso']
    search_fields = ['codigo_interno', 'mac_address', 'gpon_serial', 'serial_manufacturer']
    ordering = ['-fecha_ingreso']

@admin.register(EquipoServicio)
class EquipoServicioAdmin(admin.ModelAdmin):
    list_display = ['equipo_onu', 'contrato', 'fecha_asignacion', 'estado_asignacion']
    list_filter = ['estado_asignacion', 'fecha_asignacion']
    search_fields = ['equipo_onu__codigo_interno', 'contrato__numero_contrato']
    ordering = ['-fecha_asignacion']