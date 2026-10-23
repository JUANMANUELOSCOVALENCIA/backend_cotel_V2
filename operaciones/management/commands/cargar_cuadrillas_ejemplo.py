# ======================================================
# python manage.py cargar_cuadrillas_ejemplo [--ordenes 10]
#
# Crea datos de ejemplo para cuadrillas y programación (solo para desarrollo; dentro del sistema
# no se distinguen de los demás datos, decisión del 22/10/2026):
#   - 3 vehículos con su equipamiento fijo
#   - técnicos (rol Técnico) hasta tener 7 habilitados para campo. Su contraseña inicial es su
#     código COTEL (igual que los usuarios creados a mano) y deben cambiarla al entrar.
#   - hasta 3 cuadrillas activas (CUA-01…), cada una con vehículo, almacén, sus zonas y técnicos
#   - con --ordenes N: N solicitudes (con su OT pendiente) dentro de las zonas de cobertura
#
# Se puede ejecutar varias veces: no duplica (vehículos por placa, cuadrillas hasta 3 activas)
# y no modifica lo registrado a mano.
# ======================================================
import random

from django.core.management.base import BaseCommand
from django.db import transaction

from almacenes.models import Almacen, Material
from contratos.models import Cliente, PlanComercial
from operaciones import geo, programacion
from operaciones.models import Cuadrilla, IntegranteCuadrilla, Solicitud, Vehiculo, VehiculoEquipo, ZonaCobertura
from operaciones.serializers import crear_orden
from usuarios.models import Roles, Usuario

VEHICULOS = [
    ('2345ABC', 'Camioneta Toyota Hilux blanca'),
    ('3456BCD', 'Camioneta Nissan Frontier gris'),
    ('4567CDE', 'Furgoneta Suzuki APV blanca'),
]
EQUIPAMIENTO = [('Escalera telescópica 8 m', 1), ('Empalmadora de fusión', 1), ('Medidor de potencia óptica', 1),
                ('Cortadora de fibra (cleaver)', 1), ('Kit de herramientas', 1), ('Conos de seguridad', 4)]
TECNICOS = [('Juan Carlos', 'Mamani', 'Torrez'), ('Luis Alberto', 'Quispe', 'Gutiérrez'), ('Carlos', 'Choque', 'Laura'),
            ('Pedro', 'Condori', 'Rojas'), ('Mario', 'Flores', 'Aruquipa'), ('Raúl', 'Apaza', 'Mendoza'),
            ('Edwin', 'Limachi', 'Paco'), ('Freddy', 'Huanca', 'Callisaya')]
CLIENTES = [('Rosa', 'Ticona Alanoca'), ('Jorge', 'Calle Chura'), ('Carmen', 'Poma Yujra'), ('Miguel', 'Alanoca Tarqui'),
            ('Lucía', 'Copa Huarachi'), ('Hugo', 'Nina Sirpa'), ('Silvia', 'Ramos Ajata'), ('Diego', 'Cruz Colque'),
            ('Paola', 'Villca Mamani'), ('Iván', 'Machaca Quispe')]
CALLES = ['Av. 6 de Agosto', 'Calle Murillo', 'Av. Buenos Aires', 'Calle Landaeta', 'Av. Saavedra', 'Calle Potosí']
REFERENCIAS = ['Casa de dos pisos, puerta café', 'Frente a la tienda de barrio', 'Edificio azul, 3er piso',
               'Portón negro junto a la farmacia', '']


def _punto_en(zona):
    """Un punto dentro del polígono de la zona (promedio de vértices y, si cae fuera, cerca de cada vértice)."""
    g = zona.geometria or {}
    anillos = [g['coordinates'][0]] if g.get('type') == 'Polygon' else [p[0] for p in g.get('coordinates', [])]
    for anillo in anillos:
        if not anillo:
            continue
        lng = sum(p[0] for p in anillo) / len(anillo)
        lat = sum(p[1] for p in anillo) / len(anillo)
        candidatos = [(lat, lng)] + [(lat + (p[1] - lat) * 0.5, lng + (p[0] - lng) * 0.5) for p in anillo]
        for la, lo in candidatos:
            if geo.contiene(g, la, lo):
                return round(la, 6), round(lo, 6)
    return None


class Command(BaseCommand):
    help = 'Crea vehículos, técnicos y cuadrillas de ejemplo (y OT con --ordenes N).'

    def add_arguments(self, parser):
        parser.add_argument('--ordenes', type=int, default=0, help='Cantidad de solicitudes/OT a crear')

    @transaction.atomic
    def handle(self, *args, **opts):
        almacenes = list(Almacen.objects.filter(activo=True).order_by('-es_principal', 'nombre'))
        if not almacenes:
            self.stderr.write('No hay almacenes activos: regístralos primero en Almacenes.')
            return
        rol = next((r for r in Roles.objects.all() if r.nombre.lower().replace('é', 'e') == 'tecnico'), None)
        if not rol:
            self.stderr.write('No existe el rol Técnico: ejecuta "python manage.py migrate operaciones".')
            return

        # Vehículos
        vehiculos = []
        for placa, desc in VEHICULOS:
            v, nuevo = Vehiculo.objects.get_or_create(placa=placa, defaults={'descripcion': desc})
            if nuevo:
                VehiculoEquipo.objects.bulk_create([VehiculoEquipo(vehiculo=v, nombre=n, cantidad=c) for n, c in EQUIPAMIENTO])
            vehiculos.append(v)
        self.stdout.write(f'Vehículos: {len(vehiculos)}')

        # Técnicos hasta tener 7 habilitados para campo
        creados = 0
        for nombres, paterno, materno in TECNICOS:
            if programacion.tecnicos_disponibles().count() + IntegranteCuadrilla.objects.filter(hasta__isnull=True).count() >= 7:
                break
            if Usuario.objects.filter(nombres=nombres, apellidopaterno=paterno).exists():
                continue
            codigo = Usuario.objects.generar_codigo_cotel_disponible()
            u = Usuario(codigocotel=codigo, nombres=nombres, apellidopaterno=paterno, apellidomaterno=materno, rol=rol,
                        password_changed=False)
            u.set_password(str(codigo))
            u.save()
            creados += 1
        self.stdout.write(f'Técnicos creados: {creados} (contraseña inicial = su código COTEL)')

        # Hasta 3 cuadrillas activas
        nuevas = []
        while Cuadrilla.objects.filter(activo=True).count() < 3:
            libres = list(programacion.tecnicos_disponibles()[:3])
            vehiculo = next((v for v in vehiculos if v.activo and not v.cuadrillas.filter(activo=True).exists()), None)
            if len(libres) < 2 or not vehiculo:
                break
            almacen = almacenes[len(nuevas) % len(almacenes)]
            c = Cuadrilla.objects.create(almacen=almacen, vehiculo=vehiculo, capacidad_diaria=5)
            c.zonas.set(ZonaCobertura.objects.filter(activo=True, almacen=almacen))
            for i, t in enumerate(libres[:3 if len(nuevas) == 0 else 2]):
                programacion.agregar_integrante(c, t, es_jefe=(i == 0))
            nuevas.append(c)
        for c in nuevas:
            gente = ', '.join(i.usuario.nombre_completo + (' (jefe)' if i.es_jefe else '') for i in c.vigentes().select_related('usuario'))
            self.stdout.write(f'  {c.nombre} · {c.almacen.nombre} · {c.vehiculo.placa} · {gente}')
        self.stdout.write(f'Cuadrillas creadas: {len(nuevas)} (activas: {Cuadrilla.objects.filter(activo=True).count()})')

        # OT
        if opts['ordenes']:
            self._ordenes(opts['ordenes'])

        # Lo que hay para despachar
        for a in {c.almacen for c in Cuadrilla.objects.filter(activo=True).select_related('almacen')}:
            onus = Material.objects.filter(almacen_actual=a, tipo_material__es_unico=True, estado_onu__codigo='DISPONIBLE',
                                           traspaso_actual__isnull=True).count()
            granel = Material.objects.filter(almacen_actual=a, tipo_material__es_unico=False, estado_general__codigo='DISPONIBLE',
                                             cantidad__gt=0).count()
            self.stdout.write(f'{a.nombre}: {onus} ONU disponibles y {granel} registro(s) de material por cantidad para despachar.')

    def _ordenes(self, n):
        zonas = [(z, _punto_en(z)) for z in ZonaCobertura.objects.filter(activo=True)]
        zonas = [(z, p) for z, p in zonas if p]
        if not zonas:
            self.stderr.write('No hay zonas de cobertura activas con polígono: no se crearon OT.')
            return
        plan = PlanComercial.objects.filter(activo=True).exclude(codigo_plan='TEL-FIJA').order_by('precio_mensual').first()
        admin = Usuario.objects.filter(is_superuser=True).order_by('id').first()
        rnd = random.Random(2026)
        creadas = 0
        for i in range(n):
            nombres, apellido = CLIENTES[i % len(CLIENTES)]
            ci = f'{9900000 + i}'
            cliente, _ = Cliente.objects.get_or_create(ci=ci, defaults={
                'nombres': nombres, 'apellidos': apellido, 'telefono': f'7{rnd.randint(1000000, 9999999)}'})
            if Solicitud.objects.filter(cliente=cliente, estado=Solicitud.Estado.EN_CURSO).exists():
                continue
            zona, (lat, lng) = zonas[i % len(zonas)]
            tipo = Solicitud.Tipo.INSTALACION if (i % 3 != 2 and plan) else Solicitud.Tipo.REPARACION
            s = Solicitud.objects.create(
                tipo=tipo, cliente=cliente, plan=plan if tipo == Solicitud.Tipo.INSTALACION else None,
                prioridad='ALTA' if i % 5 == 0 else 'NORMAL', telefono_contacto=cliente.telefono,
                direccion=f'{rnd.choice(CALLES)} #{rnd.randint(100, 2500)}', zona_referencia=zona.nombre,
                referencia=rnd.choice(REFERENCIAS), latitud=lat, longitud=lng, zona_cobertura=zona,
                creado_por=admin,
            )
            crear_orden(s, admin)
            creadas += 1
        self.stdout.write(f'Solicitudes con su OT pendiente: {creadas}')
