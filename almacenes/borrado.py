# ======================================================
# almacenes/borrado.py
# Evita borrados en cascada accidentales.
#
# Varias relaciones usan on_delete=CASCADE: borrar un proveedor borraba también
# TODOS sus lotes y materiales, borrar una marca borraba sus modelos y equipos, etc.
# Con este mixin, si el registro está en uso se responde 400 con un mensaje claro
# y se sugiere desactivarlo en lugar de borrarlo.
# ======================================================
from django.db import router
from django.db.models import ProtectedError, RestrictedError
from django.db.models.deletion import Collector
from rest_framework import status
from rest_framework.response import Response

NOMBRES = {
    'almacenes.Modelo': 'modelo(s)',
    'almacenes.Lote': 'lote(s)',
    'almacenes.LoteDetalle': 'detalle(s) de lote',
    'almacenes.EntregaParcialLote': 'entrega(s) parcial(es)',
    'almacenes.Material': 'material(es)/equipo(s)',
    'almacenes.TraspasoAlmacen': 'traspaso(s)',
    'almacenes.TraspasoMaterial': 'material(es) en traspasos',
    'almacenes.HistorialMaterial': 'registro(s) de historial',
    'almacenes.InspeccionLaboratorio': 'inspección(es) de laboratorio',
    'almacenes.Almacen': 'almacén(es)',
}

# Lo que se menciona en el mensaje (lo demás va en 'dependencias')
PRINCIPALES = {'modelo(s)', 'lote(s)', 'material(es)/equipo(s)', 'traspaso(s)', 'inspección(es) de laboratorio'}


def dependencias(obj, permitidos=()):
    """Devuelve {nombre legible: cantidad} de lo que se borraría junto con obj."""
    collector = Collector(using=router.db_for_write(type(obj), instance=obj))
    try:
        collector.collect([obj])
    except (ProtectedError, RestrictedError) as e:
        return {'registros protegidos': len(e.protected_objects if hasattr(e, 'protected_objects') else e.restricted_objects)}

    encontrados = {}
    def sumar(modelo, cantidad):
        label = modelo._meta.label
        if modelo is type(obj) or label in permitidos or not cantidad:
            return
        nombre = NOMBRES.get(label, str(modelo._meta.verbose_name_plural))
        encontrados[nombre] = encontrados.get(nombre, 0) + cantidad

    for modelo, instancias in collector.data.items():
        sumar(modelo, len(instancias))
    for qs in collector.fast_deletes:
        sumar(qs.model, qs.count())
    return encontrados


class BorradoSeguroMixin:
    """Usar en ModelViewSet: bloquea destroy si el registro arrastraría otros datos."""
    borrado_permitido = ()  # labels de modelos que sí pueden borrarse junto (p. ej. tablas intermedias)
    sugerencia_borrado = 'Puedes desactivarlo para que no se use más.'

    def destroy(self, request, *args, **kwargs):
        obj = self.get_object()
        deps = dependencias(obj, self.borrado_permitido)
        if deps:
            principales = [(nombre, n) for nombre, n in deps.items() if nombre in PRINCIPALES] or list(deps.items())
            detalle = ', '.join(f'{n} {nombre}' for nombre, n in principales[:3])
            return Response(
                {'error': f'No se puede eliminar "{obj}" porque tiene {detalle} asociados. {self.sugerencia_borrado}',
                 'dependencias': deps},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return super().destroy(request, *args, **kwargs)
