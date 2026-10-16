# Permisos de cuadrillas y de la app de campo, y el rol Técnico.
#   cuadrillas : vehículos y cuadrillas (pantalla Cuadrillas)
#   campo      : trabajo en campo desde la app del técnico (PWA). Quien tiene campo:actualizar
#                puede integrar una cuadrilla.
# Si ya existe un rol "Técnico" (con o sin tilde) no se toca; si no, se crea como rol del sistema.
import unicodedata

from django.db import migrations

RECURSOS = {
    'cuadrillas': 'Cuadrillas y vehículos',
    'campo': 'Trabajo en campo (app del técnico)',
}
ACCIONES = ['leer', 'crear', 'actualizar', 'eliminar']
PERMISOS_TECNICO = [('campo', 'leer'), ('campo', 'actualizar')]


def _normal(texto):
    return ''.join(c for c in unicodedata.normalize('NFD', texto or '') if unicodedata.category(c) != 'Mn').strip().lower()


def crear(apps, schema_editor):
    Permission = apps.get_model('usuarios', 'Permission')
    Roles = apps.get_model('usuarios', 'Roles')
    for recurso, desc in RECURSOS.items():
        for accion in ACCIONES:
            if not Permission.objects.filter(recurso=recurso, accion=accion).exists():
                Permission.objects.create(recurso=recurso, accion=accion, descripcion=f'{desc}: {accion}', activo=True)

    if any(_normal(r.nombre) == 'tecnico' for r in Roles.objects.all()):
        return
    rol = Roles.objects.create(
        nombre='Técnico', activo=True, es_sistema=True,
        descripcion='Personal de planta externa que integra las cuadrillas y trabaja con la app de campo.',
    )
    rol.permisos.set(Permission.objects.filter(recurso='campo', accion__in=[a for _, a in PERMISOS_TECNICO]))


class Migration(migrations.Migration):
    dependencies = [('operaciones', '0006_cuadrillas')]
    operations = [migrations.RunPython(crear, migrations.RunPython.noop)]
