from django.contrib import admin

from .models import HistorialOT, OrdenTrabajo, Solicitud, ZonaCobertura


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
    list_display = ('numero', 'tipo', 'estado', 'prioridad', 'fecha_programada', 'created_at')
    list_filter = ('estado', 'tipo', 'prioridad')
    search_fields = ('numero', 'solicitud__numero')
    inlines = [HistorialInline]
