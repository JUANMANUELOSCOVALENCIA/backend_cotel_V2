# Permisos de los módulos de operación.
# (Antes creaba tipos de servicio combinados; ya no: el plan es de internet y
#  telefonía / TV cable se marcan en la solicitud. La 0004 limpia los que existan.)
from django.db import migrations

RECURSOS = {
    'solicitudes': 'Solicitudes de clientes',
    'ordenes': 'Órdenes de trabajo',
    'cobertura': 'Zonas de cobertura',
    'planes': 'Planes comerciales',
}
ACCIONES = ['leer', 'crear', 'actualizar', 'eliminar']



def crear(apps, schema_editor):
    Permission = apps.get_model('usuarios', 'Permission')
    for recurso, desc in RECURSOS.items():
        for accion in ACCIONES:
            if not Permission.objects.filter(recurso=recurso, accion=accion).exists():
                Permission.objects.create(recurso=recurso, accion=accion, descripcion=f'{desc}: {accion}', activo=True)


class Migration(migrations.Migration):
    dependencies = [
        ('operaciones', '0001_initial'),
        ('usuarios', '0009_remove_constraint'),
        ('contratos', '0007_alter_servicio_plan_comercial'),
    ]
    operations = [migrations.RunPython(crear, migrations.RunPython.noop)]
