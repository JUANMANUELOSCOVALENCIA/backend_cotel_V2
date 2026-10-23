# Los datos de prueba no se distinguen en el sistema (decisión del 22/10/2026): se quitan las marcas
# visibles que dejaron los comandos de carga (apellido "PRUEBA", "(prueba)", "DATOS DE PRUEBA",
# "Proveedor de prueba", lote "PRUEBA-MAT-…"). Solo toca registros con esas marcas exactas;
# en una base sin datos de prueba no hace nada.
from django.db import migrations

MATERNOS = {'Mamani': 'Torrez', 'Quispe': 'Gutiérrez', 'Choque': 'Laura', 'Condori': 'Rojas', 'Flores': 'Aruquipa',
            'Apaza': 'Mendoza', 'Limachi': 'Paco', 'Huanca': 'Callisaya'}
OTROS = ['Alanoca', 'Chura', 'Yujra', 'Tarqui', 'Huarachi', 'Sirpa', 'Ajata', 'Colque']
MARCA = 'DATOS DE PRUEBA'


def limpiar(apps, schema_editor):
    Usuario = apps.get_model('usuarios', 'Usuario')
    for i, u in enumerate(Usuario.objects.filter(apellidomaterno='PRUEBA').order_by('id')):
        u.apellidomaterno = MATERNOS.get(u.apellidopaterno, OTROS[i % len(OTROS)])
        u.save(update_fields=['apellidomaterno'])

    Cliente = apps.get_model('contratos', 'Cliente')
    for i, c in enumerate(Cliente.objects.filter(apellidos__endswith=' (prueba)').order_by('id')):
        c.apellidos = f'{c.apellidos[:-len(" (prueba)")]} {OTROS[i % len(OTROS)]}'
        if c.observaciones == MARCA:
            c.observaciones = ''
        c.save(update_fields=['apellidos', 'observaciones'])

    for app, modelo in (('operaciones', 'Vehiculo'), ('operaciones', 'Cuadrilla'), ('operaciones', 'Solicitud'),
                        ('almacenes', 'Material')):
        apps.get_model(app, modelo).objects.filter(observaciones=MARCA).update(observaciones='')

    Proveedor = apps.get_model('almacenes', 'Proveedor')
    p = Proveedor.objects.filter(nombre_comercial='Proveedor de prueba').first()
    if p and not Proveedor.objects.filter(nombre_comercial='Distribuidora FTTH').exists():
        p.nombre_comercial = p.razon_social = 'Distribuidora FTTH'
        p.save(update_fields=['nombre_comercial', 'razon_social'])

    Lote = apps.get_model('almacenes', 'Lote')
    for lote in Lote.objects.filter(numero_lote__startswith='PRUEBA-MAT-'):
        nuevo = f'MAT-{lote.numero_lote[len("PRUEBA-MAT-"):]}-001'
        if not Lote.objects.filter(numero_lote=nuevo).exists():
            lote.numero_lote = nuevo
        if (lote.observaciones or '').startswith(MARCA):
            lote.observaciones = 'Stock inicial de materiales de instalación'
        lote.save(update_fields=['numero_lote', 'observaciones'])


class Migration(migrations.Migration):
    dependencies = [
        ('operaciones', '0013_deshacer_cierre_automatico'),
        ('usuarios', '0009_remove_constraint'),
        ('contratos', '0008_contrato_estado_cuenta'),
        ('almacenes', '0017_traspaso_solo_disponibles'),
    ]
    operations = [migrations.RunPython(limpiar, migrations.RunPython.noop)]
