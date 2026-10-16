# Estados de ONU para el despacho a cuadrillas y permisos de la pantalla de despacho.
#   EN_CUADRILLA : entregada a una cuadrilla para una OT (no se puede traspasar ni volver a despachar)
#   INSTALADO    : instalada en el domicilio de la OT
#   FALTANTE     : la cuadrilla no la devolvió ni la instaló (queda a su cargo)
# Los roles que ya modifican órdenes de trabajo reciben los permisos de despachos.
from django.db import migrations

ESTADOS = [
    ('EN_CUADRILLA', 'En cuadrilla', 'Entregada a una cuadrilla para una orden de trabajo', '#7C3AED', 20),
    ('INSTALADO', 'Instalado', 'Instalado en el domicilio del cliente', '#059669', 21),
    ('FALTANTE', 'Faltante', 'No devuelto por la cuadrilla: queda a su cargo', '#DC2626', 22),
]


def crear(apps, schema_editor):
    Estado = apps.get_model('almacenes', 'EstadoMaterialONU')
    Permission = apps.get_model('usuarios', 'Permission')
    Roles = apps.get_model('usuarios', 'Roles')
    for codigo, nombre, desc, color, orden in ESTADOS:
        Estado.objects.get_or_create(codigo=codigo, defaults={
            'nombre': nombre, 'descripcion': desc, 'color': color, 'orden': orden, 'activo': True,
            'permite_asignacion': False, 'permite_traspaso': False,
        })
    permisos = []
    for accion in ('leer', 'crear', 'actualizar', 'eliminar'):
        p = Permission.objects.filter(recurso='despachos', accion=accion).first()
        if not p:
            p = Permission.objects.create(recurso='despachos', accion=accion, descripcion=f'Despacho y rendición de cuadrillas: {accion}', activo=True)
        permisos.append(p)
    for rol in Roles.objects.filter(permisos__recurso='ordenes', permisos__accion='actualizar').distinct():
        rol.permisos.add(*permisos)


class Migration(migrations.Migration):
    dependencies = [('operaciones', '0009_despachos'), ('almacenes', '0017_traspaso_solo_disponibles')]
    operations = [migrations.RunPython(crear, migrations.RunPython.noop)]
