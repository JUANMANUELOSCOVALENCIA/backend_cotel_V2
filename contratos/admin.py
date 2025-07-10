# ======================================================
# apps/contratos/admin.py
# ======================================================

from django.contrib import admin
from .models import (
    Cliente, TipoTramite, FormaPago, TipoServicio, PlanComercial,
    Contrato, Servicio, OrdenTrabajo
)

@admin.register(TipoServicio)
class TipoServicioAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'descripcion', 'created_at']
    search_fields = ['nombre']
    ordering = ['nombre']

@admin.register(TipoTramite)
class TipoTramiteAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'descripcion', 'activo', 'created_at']
    list_filter = ['activo']
    search_fields = ['nombre']
    ordering = ['nombre']

@admin.register(FormaPago)
class FormaPagoAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'descripcion', 'activo', 'created_at']
    list_filter = ['activo']
    search_fields = ['nombre']
    ordering = ['nombre']

@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = ['ci', 'nombres', 'apellidos', 'telefono', 'zona', 'estado', 'fecha_registro']
    list_filter = ['estado', 'zona', 'ciudad', 'fecha_registro']
    search_fields = ['ci', 'nombres', 'apellidos', 'telefono']
    ordering = ['-fecha_registro']

@admin.register(PlanComercial)
class PlanComercialAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'tipo_servicio', 'codigo_plan', 'precio_mensual', 'activo']
    list_filter = ['tipo_servicio', 'activo']
    search_fields = ['nombre', 'codigo_plan']
    ordering = ['tipo_servicio__nombre', 'precio_mensual']

class ServicioInline(admin.TabularInline):
    model = Servicio
    extra = 0

@admin.register(Contrato)
class ContratoAdmin(admin.ModelAdmin):
    list_display = ['numero_contrato', 'cliente', 'estado_contrato', 'fecha_firma']
    list_filter = ['estado_contrato', 'tipo_tramite', 'forma_pago', 'fecha_firma']
    search_fields = ['numero_contrato', 'cliente__nombres', 'cliente__apellidos', 'cliente__ci']
    inlines = [ServicioInline]
    ordering = ['-fecha_firma']

@admin.register(Servicio)
class ServicioAdmin(admin.ModelAdmin):
    list_display = ['contrato', 'plan_comercial', 'estado_servicio', 'fecha_activacion']
    list_filter = ['estado_servicio', 'plan_comercial__tipo_servicio', 'fecha_activacion']
    search_fields = ['contrato__numero_contrato', 'contrato__cliente__nombres']
    ordering = ['-fecha_activacion']

@admin.register(OrdenTrabajo)
class OrdenTrabajoAdmin(admin.ModelAdmin):
    list_display = ['numero_ot', 'contrato', 'tecnico_asignado', 'estado_ot', 'fecha_programada']
    list_filter = ['estado_ot', 'tipo_trabajo', 'fecha_programada']
    search_fields = ['numero_ot', 'contrato__numero_contrato', 'tecnico_asignado']
    ordering = ['-fecha_programada']