from django.db import migrations


def solo_disponibles(apps, schema_editor):
    """Solo los equipos Disponibles (ya probados en laboratorio) se traspasan entre almacenes."""
    Estado = apps.get_model('almacenes', 'EstadoMaterialONU')
    Estado.objects.exclude(codigo='DISPONIBLE').update(permite_traspaso=False)
    Estado.objects.filter(codigo='DISPONIBLE').update(permite_traspaso=True)


def revertir(apps, schema_editor):
    Estado = apps.get_model('almacenes', 'EstadoMaterialONU')
    Estado.objects.filter(codigo__in=['NUEVO', 'REINGRESADO']).update(permite_traspaso=True)


class Migration(migrations.Migration):

    dependencies = [
        ('almacenes', '0016_traspasos'),
    ]

    operations = [
        migrations.RunPython(solo_disponibles, revertir),
    ]
