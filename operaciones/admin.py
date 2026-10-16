from django.contrib import admin

from .models import Cuadrilla, HistorialOT, IntegranteCuadrilla, OrdenTrabajo, Solicitud, Vehiculo, VehiculoEquipo, ZonaCobertura


@admin.register(ZonaCobertura)
class ZonaCoberturaAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'almacen', 'activo')
    list_filter = ('activo',)


@admin.register(Solicitud)
class SolicitudAdmin(admin.ModelAdmin):
    list_display = ('numero', 'tipo', 'estado', 'cliente', 'zona_cobertura', 'created_at')
    list_filter = ('estado', 'tipo')
    search_fields = ('numero', 'cliente__ci', 'cliente__nombres', 'cliente__apellidos')


class HistorialInline(admin.TabularInline):
    model = HistorialOT
    extra = 0


@admin.register(OrdenTrabajo)
class OrdenTrabajoAdmin(admin.ModelAdmin):
    list_display = ('numero', 'tipo', 'estado', 'prioridad', 'cuadrilla', 'fecha_programada', 'created_at')
    list_filter = ('estado', 'tipo', 'prioridad')
    search_fields = ('numero', 'solicitud__numero')
    inlines = [HistorialInline]


class VehiculoEquipoInline(admin.TabularInline):
    model = VehiculoEquipo
    extra = 0


@admin.register(Vehiculo)
class VehiculoAdmin(admin.ModelAdmin):
    list_display = ('placa', 'descripcion', 'activo')
    list_filter = ('activo',)
    search_fields = ('placa', 'descripcion')
    inlines = [VehiculoEquipoInline]


class IntegranteInline(admin.TabularInline):
    model = IntegranteCuadrilla
    extra = 0
    raw_id_fields = ('usuario',)


@admin.register(Cuadrilla)
class CuadrillaAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'almacen', 'vehiculo', 'capacidad_diaria', 'activo')
    list_filter = ('activo', 'almacen')
    inlines = [IntegranteInline]
