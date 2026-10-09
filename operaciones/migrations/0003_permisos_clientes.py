# Permisos de la pantalla Clientes (ficha, contratos y deuda).
from django.db import migrations


def crear(apps, schema_editor):
    Permission = apps.get_model('usuarios', 'Permission')
    for accion in ('leer', 'crear', 'actualizar', 'eliminar'):
        if not Permission.objects.filter(recurso='clientes', accion=accion).exists():
            Permission.objects.create(recurso='clientes', accion=accion, descripcion=f'Clientes: {accion}', activo=True)


class Migration(migrations.Migration):
    dependencies = [('operaciones', '0002_permisos_y_tipos_servicio')]
    operations = [migrations.RunPython(crear, migrations.RunPython.noop)]
