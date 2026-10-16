# Deshace el cierre automático del día (versión retirada): el sistema había marcado NO EJECUTADA, sin
# usuario ni evidencia, OT programadas de días pasados. El estado de una OT solo lo cambia el técnico
# (PWA) o un usuario con motivo. Se devuelven a PROGRAMADA las OT cuyo último cambio fue ese cierre,
# y se borra ese registro del historial (no lo hizo nadie).
from django.db import migrations


def deshacer(apps, schema_editor):
    Historial = apps.get_model('operaciones', 'HistorialOT')
    Orden = apps.get_model('operaciones', 'OrdenTrabajo')
    for h in Historial.objects.filter(usuario__isnull=True, estado_nuevo='NO_EJECUTADA', observacion__startswith='Cierre del día:'):
        ultimo = Historial.objects.filter(orden_id=h.orden_id).order_by('-fecha', '-id').first()
        orden = Orden.objects.get(pk=h.orden_id)
        if ultimo and ultimo.pk == h.pk and orden.estado == 'NO_EJECUTADA':
            Orden.objects.filter(pk=orden.pk).update(estado=h.estado_anterior or 'PROGRAMADA')
            h.delete()


class Migration(migrations.Migration):
    dependencies = [('operaciones', '0012_estado_reingresado')]
    operations = [migrations.RunPython(deshacer, migrations.RunPython.noop)]
