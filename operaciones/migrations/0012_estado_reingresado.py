# Equipos que la cuadrilla recupera de un cliente (retiro o cambio) vuelven al almacén como
# REINGRESADO, que es el estado con el que entran al laboratorio. Se crea solo si no existe.
# Además: desde ahora la ONU sale a cargo de la cuadrilla y se asocia a la OT solo al instalarla;
# en despachos anteriores se desliga la OT de las ONU que no quedaron instaladas.
from django.db import migrations


def crear(apps, schema_editor):
    Estado = apps.get_model('almacenes', 'EstadoMaterialONU')
    Estado.objects.get_or_create(codigo='REINGRESADO', defaults={
        'nombre': 'Reingresado', 'descripcion': 'Equipo recuperado de un cliente; pasa a laboratorio',
        'color': '#D97706', 'orden': 5, 'activo': True, 'permite_asignacion': False, 'permite_traspaso': False,
    })


def desligar(apps, schema_editor):
    apps.get_model('operaciones', 'DespachoEquipo').objects.exclude(resultado='INSTALADO').update(orden=None)


class Migration(migrations.Migration):
    dependencies = [('operaciones', '0011_onus_a_cargo_kits_consumo')]
    operations = [migrations.RunPython(crear, migrations.RunPython.noop), migrations.RunPython(desligar, migrations.RunPython.noop)]
