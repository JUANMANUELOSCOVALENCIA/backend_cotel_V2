# Los roles que ya gestionan órdenes de trabajo (ordenes:actualizar) reciben
# los permisos de cuadrillas, para que la pantalla aparezca sin configurar nada.
from django.db import migrations


def asignar(apps, schema_editor):
    Permission = apps.get_model('usuarios', 'Permission')
    Roles = apps.get_model('usuarios', 'Roles')
    cuadrillas = list(Permission.objects.filter(recurso='cuadrillas'))
    for rol in Roles.objects.filter(permisos__recurso='ordenes', permisos__accion='actualizar').distinct():
        rol.permisos.add(*cuadrillas)


class Migration(migrations.Migration):
    dependencies = [('operaciones', '0007_permisos_cuadrillas_rol_tecnico')]
    operations = [migrations.RunPython(asignar, migrations.RunPython.noop)]
