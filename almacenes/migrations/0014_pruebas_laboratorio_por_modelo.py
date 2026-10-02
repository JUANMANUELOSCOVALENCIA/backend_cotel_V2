from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('almacenes', '0013_lote_campos_opcionales'),
    ]

    operations = [
        migrations.AddField(
            model_name='modelo',
            name='pruebas_laboratorio',
            field=models.JSONField(blank=True, default=list, help_text='Pruebas que aplican a este modelo (campos de PRUEBAS_LABORATORIO). Vacío = todas.'),
        ),
        migrations.AddField(
            model_name='inspeccionlaboratorio',
            name='pruebas_aplicadas',
            field=models.JSONField(blank=True, default=list, help_text='Pruebas que se hicieron (según el modelo). Vacío = todas (registros anteriores).'),
        ),
    ]
