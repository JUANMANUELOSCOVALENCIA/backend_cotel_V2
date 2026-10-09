# ======================================================
# python manage.py cargar_clientes --padron clientes.csv --facturacion facturacion.csv --corte 2025-10-31
#
# Pasa clientes, contratos y su deuda a las tablas del sistema
# (contratos.Cliente, contratos.Contrato, contratos.Servicio).
#
#   --padron       CSV con: ci, contrato   (opcionales: telefono, zona, ciudad, fecha_retiro,
#                  tipo_personeria y, si son datos oficiales: nombres, apellidos, direccion)
#   --facturacion  CSV con: contrato, facturas_pendientes, monto_deuda
#   --corte        fecha del dato de deuda (AAAA-MM-DD)
#   --desde AAAA   solo contratos instalados desde ese año (por defecto 2000)
#   --limpiar      borra los datos de prueba cargados antes que quedaron fuera del rango
#                  (nunca borra clientes con solicitudes ni lo registrado a mano)
#   --limite N     cargar solo los primeros N clientes (para pruebas rápidas)
#
# Estos datos sirven para VERIFICAR DEUDA al registrar solicitudes (no se les hace
# seguimiento). Los contratos nuevos del sistema son GPON y nacen de las solicitudes.
#
# Lo que el archivo no trae (nombres, dirección) se INVENTA y el cliente queda marcado
# en observaciones como DATOS DE PRUEBA. Se puede volver a ejecutar las veces que haga
# falta: actualiza por CI y por número de contrato. Cuando lleguen los datos oficiales
# (con nombres y dirección) se ejecuta lo mismo y reemplaza lo inventado.
# ======================================================
import csv
import hashlib
from collections import OrderedDict
from datetime import date
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from contratos.models import Cliente, Contrato, PlanComercial, Servicio, TipoServicio

MARCA = 'DATOS DE PRUEBA: nombre y dirección inventados'
CIUDADES = {'LPZ': 'La Paz', 'EAL': 'El Alto', 'SLP': 'La Paz', 'SEA': 'El Alto', 'VCH': 'Viacha'}
NOMBRES = ['Juan', 'María', 'Carlos', 'Ana', 'Luis', 'Rosa', 'Jorge', 'Carmen', 'Pedro', 'Lucía', 'Miguel', 'Elena',
           'José', 'Patricia', 'Fernando', 'Sonia', 'Ricardo', 'Gabriela', 'Marco', 'Silvia', 'Diego', 'Verónica',
           'Andrés', 'Daniela', 'Raúl', 'Paola', 'Hugo', 'Claudia', 'Óscar', 'Mónica', 'Freddy', 'Wilma', 'Germán',
           'Ruth', 'Edwin', 'Norma', 'Iván', 'Lidia', 'Javier', 'Gladys']
APELLIDOS = ['Mamani', 'Quispe', 'Condori', 'Choque', 'Flores', 'Gutiérrez', 'Rojas', 'Vargas', 'Torrez', 'Apaza',
             'Limachi', 'Huanca', 'Ticona', 'Chura', 'Calle', 'Poma', 'Rodríguez', 'López', 'Pérez', 'Fernández',
             'Alanoca', 'Copa', 'Laura', 'Nina', 'Ramos', 'Cruz', 'Aliaga', 'Villca', 'Machaca', 'Yujra']
EMPRESAS = ['Comercial', 'Importadora', 'Distribuidora', 'Servicios', 'Inversiones', 'Constructora', 'Farmacia', 'Librería']
RUBROS = ['Andina', 'del Sur', 'Illimani', 'Altiplano', 'Murillo', 'Los Andes', 'Pacífico', 'Central']
ZONAS = ['Sopocachi', 'Miraflores', 'San Pedro', 'Villa Fátima', 'Obrajes', 'Calacoto', 'Achumani', 'Irpavi',
         'Villa Copacabana', 'Tembladerani', 'Pura Pura', 'Achachicala', 'Cota Cota', 'Següencoma', 'Villa Armonía']
CALLES = ['Av. 6 de Agosto', 'Av. Arce', 'Calle Murillo', 'Av. Buenos Aires', 'Calle Sagárnaga', 'Av. Busch',
          'Calle Landaeta', 'Av. Ballivián', 'Calle Jaimes Freyre', 'Av. Saavedra', 'Calle Potosí', 'Av. Montes']


def _leer(ruta):
    for enc in ('utf-8-sig', 'latin-1'):
        try:
            with open(ruta, newline='', encoding=enc) as f:
                return [{(k or '').strip().lower(): (v or '').strip() for k, v in fila.items()} for fila in csv.DictReader(f)]
        except UnicodeDecodeError:
            continue
        except FileNotFoundError:
            raise CommandError(f'No existe el archivo {ruta}')
    raise CommandError(f'No se pudo leer {ruta}')


def _ci(valor):
    ci = ''.join(str(valor or '').split()).upper()
    digitos = ''.join(ch for ch in ci if ch.isdigit())
    return ci if len(digitos.lstrip('0')) >= 5 and len(ci) <= 15 else None


def _fecha(v):
    """'2003-05-14 10:17:54' → date (None si no es válida)"""
    try:
        return date.fromisoformat(str(v).strip()[:10])
    except ValueError:
        return None


def _num(v, tipo=Decimal):
    try:
        return tipo(str(v).replace(',', '.')) if str(v).strip() not in ('', 'nan', 'None') else tipo(0)
    except (InvalidOperation, ValueError):
        return tipo(0)


def _azar(ci):
    """Generador fijo por CI: el mismo CI siempre recibe el mismo nombre inventado."""
    n = int(hashlib.md5(ci.encode()).hexdigest(), 16)

    def elegir(lista, salto):
        return lista[(n // salto) % len(lista)]
    return elegir


def _inventado(ci, juridica, zona):
    e = _azar(ci)
    if juridica:
        nombres, apellidos = f'{e(EMPRESAS, 1)} {e(RUBROS, 7)}', 'S.R.L.'
    else:
        n = int(hashlib.md5(ci.encode()).hexdigest(), 16)
        a1 = (n // 41) % len(APELLIDOS)
        a2 = (a1 + 1 + (n // 1301) % (len(APELLIDOS) - 1)) % len(APELLIDOS)  # nunca el mismo apellido dos veces
        nombres, apellidos = e(NOMBRES, 1), f'{APELLIDOS[a1]} {APELLIDOS[a2]}'
    zona = zona or e(ZONAS, 97)
    return nombres, apellidos, zona, f'{e(CALLES, 13)} Nº {(int(hashlib.md5(ci.encode()).hexdigest()[:6], 16) % 2400) + 1}, {zona}'


class Command(BaseCommand):
    help = 'Pasa clientes, contratos y deuda (CSV) a las tablas del sistema; inventa lo que falte.'

    def add_arguments(self, parser):
        parser.add_argument('--padron', required=True)
        parser.add_argument('--facturacion', required=True)
        parser.add_argument('--corte', required=True, help='Fecha del dato de deuda AAAA-MM-DD')
        parser.add_argument('--limite', type=int, default=0)
        parser.add_argument('--desde', type=int, default=2000, help='Año mínimo de instalación (por defecto 2000)')
        parser.add_argument('--limpiar', action='store_true', help='Borrar datos de prueba fuera del rango')

    def handle(self, *args, **o):
        corte = date.fromisoformat(o['corte'])
        self.stdout.write('Leyendo archivos…')
        padron, fact = _leer(o['padron']), _leer(o['facturacion'])
        if not padron or not {'ci', 'contrato'} <= set(padron[0]):
            raise CommandError('El padrón debe tener las columnas "ci" y "contrato".')
        if not fact or 'contrato' not in fact[0]:
            raise CommandError('La facturación debe tener la columna "contrato".')
        deuda = {f['contrato']: (_num(f.get('facturas_pendientes', 0), int), _num(f.get('monto_deuda', 0))) for f in fact}

        # Agrupar contratos por CI
        clientes, invalidos, antiguos = OrderedDict(), 0, 0
        for p in padron:
            ci, contrato = _ci(p.get('ci')), p.get('contrato', '')
            if not ci or not contrato or len(contrato) > 8:
                invalidos += 1
                continue
            p['_fecha'] = _fecha(p.get('fecha_instalacion'))
            if o['desde'] and (p['_fecha'] is None or p['_fecha'].year < o['desde']):
                antiguos += 1
                continue
            if ci not in clientes:
                if o['limite'] and len(clientes) >= o['limite']:
                    continue
                clientes[ci] = {'fila': p, 'contratos': []}
            clientes[ci]['contratos'].append(p)

        with transaction.atomic():
            res = self._guardar(clientes, deuda, corte)
            borrados = self._limpiar(clientes) if o['limpiar'] else None
        self.stdout.write(self.style.SUCCESS(
            f"Clientes: {res['cli_nuevos']:,} nuevos, {res['cli_act']:,} con cambios · "
            f"Contratos: {res['con_nuevos']:,} nuevos, {res['con_act']:,} con cambios · "
            f"con deuda: {res['con_deuda']:,} · descartados: {invalidos:,} por CI/contrato inválido"
            + (f", {antiguos:,} instalados antes de {o['desde']}" if o['desde'] else '')))
        if borrados:
            self.stdout.write(self.style.WARNING(
                f"Limpieza: {borrados['contratos']:,} contratos y {borrados['clientes']:,} clientes de prueba borrados"
                + (f" ({borrados['con_solicitudes']:,} clientes se conservan porque tienen solicitudes)" if borrados['con_solicitudes'] else '')))

    def _limpiar(self, clientes):
        """Borra lo cargado antes (datos de prueba) que ya no está en esta carga."""
        vigentes = {p['contrato'] for d in clientes.values() for p in d['contratos']}
        prueba = Cliente.objects.filter(observaciones__startswith=MARCA)
        # Los clientes de prueba solo tienen contratos que vinieron de la carga
        ids_viejos = list(Contrato.objects.filter(cliente__in=prueba).exclude(
            numero_contrato__in=vigentes).values_list('id', flat=True))
        for i in range(0, len(ids_viejos), 5000):
            lote = ids_viejos[i:i + 5000]
            Servicio.objects.filter(contrato_id__in=lote).delete()
            Contrato.objects.filter(id__in=lote).delete()
        n_contratos = len(ids_viejos)
        sobran = prueba.exclude(ci__in=list(clientes)).filter(contratos__isnull=True)
        con_solicitudes = sobran.filter(solicitudes__isnull=False).distinct().count()
        ids = list(sobran.filter(solicitudes__isnull=True).values_list('id', flat=True))
        for i in range(0, len(ids), 5000):
            Cliente.objects.filter(id__in=ids[i:i + 5000]).delete()
        return {'contratos': n_contratos, 'clientes': len(ids), 'con_solicitudes': con_solicitudes}

    def _guardar(self, clientes, deuda, corte):
        tipo, _ = TipoServicio.objects.get_or_create(nombre='Telefonía fija', defaults={'descripcion': 'Línea de telefonía fija'})
        plan, _ = PlanComercial.objects.get_or_create(
            codigo_plan='TEL-FIJA', defaults={'tipo_servicio': tipo, 'nombre': 'Línea fija', 'activo': False,
                                              'descripcion': 'Servicio existente; solo para verificar deuda (no se ofrece en solicitudes)'})

        # ---- Clientes ----
        existentes = {c.ci: c for c in Cliente.objects.filter(ci__in=list(clientes))}
        nuevos, actualizar, direcciones = [], [], {}
        for ci, datos in clientes.items():
            p = datos['fila']
            oficial = bool(p.get('nombres'))
            juridica = p.get('tipo_personeria', '').upper() == 'J'
            zona_csv = p.get('zona', '')
            zona_csv = '' if not zona_csv or any(ch.isdigit() for ch in zona_csv) else zona_csv.title()  # en el bigdata viene un código numérico
            nom, ape, zona, direccion = _inventado(ci, juridica, zona_csv)
            if oficial:
                nom, ape, direccion = p['nombres'], p.get('apellidos', ''), p.get('direccion') or direccion
            direcciones[ci] = direccion
            ciudad = CIUDADES.get(p.get('ciudad', '').upper(), 'La Paz')
            c = existentes.get(ci)
            if c is None:
                nuevos.append(Cliente(ci=ci, nombres=nom[:100], apellidos=ape[:100], telefono=p.get('telefono', '')[:20],
                                      direccion=direccion, zona=zona[:100], ciudad=ciudad,
                                      observaciones='' if oficial else MARCA))
            elif oficial or c.observaciones.startswith(MARCA):
                # Solo se reemplazan datos inventados (o con datos oficiales); lo registrado a mano no se toca
                antes = (c.nombres, c.apellidos, c.direccion, c.zona, c.ciudad, c.telefono, c.observaciones)
                c.nombres, c.apellidos, c.direccion, c.zona, c.ciudad = nom[:100], ape[:100], direccion, zona[:100], ciudad
                c.telefono = c.telefono or p.get('telefono', '')[:20]
                c.observaciones = '' if oficial else MARCA
                if antes != (c.nombres, c.apellidos, c.direccion, c.zona, c.ciudad, c.telefono, c.observaciones):
                    actualizar.append(c)
        Cliente.objects.bulk_create(nuevos, batch_size=2000)
        Cliente.objects.bulk_update(actualizar, ['nombres', 'apellidos', 'direccion', 'zona', 'ciudad', 'telefono', 'observaciones'], batch_size=2000)
        id_por_ci = dict(Cliente.objects.filter(ci__in=list(clientes)).values_list('ci', 'id'))

        # ---- Contratos ----
        numeros = [p['contrato'] for d in clientes.values() for p in d['contratos']]
        contratos_ex = {c.numero_contrato: c for c in Contrato.objects.filter(numero_contrato__in=numeros)}
        con_nuevos, con_act, con_deuda = [], [], 0
        for ci, datos in clientes.items():
            for p in datos['contratos']:
                facturas, monto = deuda.get(p['contrato'], (0, Decimal(0)))
                fecha = corte if p['contrato'] in deuda else None
                con_deuda += facturas > 0
                estado = 'CANCELADO' if p.get('fecha_retiro') else 'ACTIVO'
                c = contratos_ex.get(p['contrato'])
                if c is None:
                    c = Contrato(
                        numero_contrato=p['contrato'], cliente_id=id_por_ci[ci], estado_contrato=estado,
                        direccion_instalacion=direcciones[ci], facturas_pendientes=max(facturas, 0),
                        monto_deuda=max(monto, Decimal(0)), deuda_actualizada=fecha)
                    c.fecha_firma = p['_fecha']
                    con_nuevos.append(c)
                else:
                    nuevo = (max(facturas, 0), max(monto, Decimal(0)), fecha, estado, p['_fecha'] or c.fecha_firma)
                    if (c.facturas_pendientes, c.monto_deuda, c.deuda_actualizada, c.estado_contrato, c.fecha_firma) != nuevo:
                        (c.facturas_pendientes, c.monto_deuda, c.deuda_actualizada, c.estado_contrato, c.fecha_firma) = nuevo
                        con_act.append(c)
        fechas = {c.numero_contrato: c.fecha_firma for c in con_nuevos}
        Contrato.objects.bulk_create(con_nuevos, batch_size=2000)
        # fecha_firma es auto_now_add: al crear se pone "hoy"; se corrige con la fecha de instalación real
        creados = list(Contrato.objects.filter(numero_contrato__in=list(fechas)))
        for c in creados:
            c.fecha_firma = fechas[c.numero_contrato] or c.fecha_firma
        Contrato.objects.bulk_update(creados, ['fecha_firma'], batch_size=2000)
        Contrato.objects.bulk_update(con_act, ['facturas_pendientes', 'monto_deuda', 'deuda_actualizada', 'estado_contrato',
                                               'fecha_firma'], batch_size=2000)

        # Servicio de telefonía para los contratos nuevos
        ids = Contrato.objects.filter(numero_contrato__in=[c.numero_contrato for c in con_nuevos]).values_list('id', flat=True)
        Servicio.objects.bulk_create([Servicio(contrato_id=i, plan_comercial=plan) for i in ids], batch_size=2000, ignore_conflicts=True)
        Servicio.objects.filter(contrato__estado_contrato='CANCELADO', estado_servicio='ACTIVO').update(estado_servicio='CANCELADO')

        return {'cli_nuevos': len(nuevos), 'cli_act': len(actualizar), 'con_nuevos': len(con_nuevos),
                'con_act': len(con_act), 'con_deuda': con_deuda}
