# Pruebas de cuadrillas y programación de OT.
#   python manage.py test operaciones
# (el usuario de la base necesita permiso para crear la base de pruebas: ALTER USER ... CREATEDB)
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from decimal import Decimal

from almacenes.models import (Almacen, EstadoLote, EstadoMaterialGeneral, EstadoMaterialONU, HistorialMaterial, Lote, Marca,
                              Material, Modelo, Proveedor, TipoAlmacen, TipoIngreso, TipoMaterial, UnidadMedida)
from contratos.models import Cliente
from usuarios.models import Permission, Roles, Usuario

from . import programacion as prog
from . import despacho as desp
from .models import Cuadrilla, Despacho, HistorialOT, IntegranteCuadrilla, OrdenTrabajo, Solicitud, Vehiculo, ZonaCobertura
from .programacion import ErrorProgramacion
from .serializers import crear_orden

E = OrdenTrabajo.Estado
HOY = timezone.localdate()
MANANA = HOY + timedelta(days=1)
CUADRADO = {'type': 'Polygon', 'coordinates': [[[-68.2, -16.6], [-68.0, -16.6], [-68.0, -16.4], [-68.2, -16.4], [-68.2, -16.6]]]}


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        tipo = TipoAlmacen.objects.create(codigo='REG', nombre='Regional')
        cls.almacen = Almacen.objects.create(codigo='LPZ', nombre='La Paz', ciudad='La Paz', tipo=tipo)
        cls.zona = ZonaCobertura.objects.create(nombre='Sopocachi', geometria=CUADRADO, almacen=cls.almacen)
        cls.otra_zona = ZonaCobertura.objects.create(nombre='Miraflores', geometria=CUADRADO, almacen=cls.almacen)
        # El rol Técnico lo crea la migración 0007 con campo:leer y campo:actualizar
        cls.rol_tecnico = Roles.objects.get(nombre='Técnico')
        cls.rol_oficina = Roles.objects.create(nombre='Operaciones')
        cls.rol_oficina.permisos.set(Permission.objects.filter(recurso__in=['ordenes', 'cuadrillas', 'despachos']))
        cls.tecnicos = [cls._usuario(9100 + i, f'Tecnico{i}', cls.rol_tecnico) for i in range(5)]
        cls.oficina = cls._usuario(9200, 'Programador', cls.rol_oficina)
        cls.cliente = Cliente.objects.create(ci='1234567', nombres='Ana', apellidos='Quispe', telefono='71234567')
        cls.vehiculo = Vehiculo.objects.create(placa='2345abc', descripcion='Camioneta blanca')

    @staticmethod
    def _usuario(codigo, nombre, rol):
        u = Usuario.objects.create_user(codigocotel=codigo, password='x', nombres=nombre, apellidopaterno='P',
                                        apellidomaterno='M', rol=rol, password_changed=True)
        return u

    def cuadrilla(self, nombre='Cuadrilla 1', tecnicos=2, zonas=None, **kw):
        c = Cuadrilla.objects.create(nombre=nombre, almacen=self.almacen, **kw)
        if zonas:
            c.zonas.set(zonas)
        libres = [t for t in self.tecnicos if not IntegranteCuadrilla.objects.filter(usuario=t, hasta__isnull=True).exists()]
        for i, t in enumerate(libres[:tecnicos]):
            prog.agregar_integrante(c, t, es_jefe=(i == 0))
        return c

    def orden(self, prioridad='NORMAL', zona=None):
        s = Solicitud.objects.create(tipo='REPARACION', cliente=self.cliente, direccion='Calle 1 #23', latitud=-16.5,
                                     longitud=-68.1, zona_cobertura=zona or self.zona, prioridad=prioridad)
        return crear_orden(s, self.oficina)


class CuadrillaTests(Base):
    def test_rol_tecnico_y_permisos_creados_por_migracion(self):
        self.assertTrue(Permission.objects.filter(recurso='cuadrillas', accion='crear').exists())
        self.assertTrue(self.rol_tecnico.es_sistema)
        self.assertTrue(prog.puede_ir_a_campo(self.tecnicos[0]))
        self.assertFalse(prog.puede_ir_a_campo(self.oficina))

    def test_solo_usuarios_habilitados_para_campo(self):
        c = self.cuadrilla(tecnicos=0)
        with self.assertRaisesMessage(ErrorProgramacion, 'no tiene un rol habilitado para campo'):
            prog.agregar_integrante(c, self.oficina)

    def test_tecnico_en_una_sola_cuadrilla(self):
        c1 = self.cuadrilla('C1', tecnicos=0)
        c2 = self.cuadrilla('C2', tecnicos=0)
        prog.agregar_integrante(c1, self.tecnicos[0])
        with self.assertRaisesMessage(ErrorProgramacion, 'ya está en la cuadrilla C1'):
            prog.agregar_integrante(c2, self.tecnicos[0])
        # La base de datos también lo impide
        with self.assertRaises(IntegrityError), transaction.atomic():
            IntegranteCuadrilla.objects.create(cuadrilla=c2, usuario=self.tecnicos[0])

    def test_maximo_tres_y_un_jefe(self):
        c = self.cuadrilla(tecnicos=3)
        with self.assertRaisesMessage(ErrorProgramacion, 'ya tiene 3 técnicos'):
            prog.agregar_integrante(c, self.tecnicos[3])
        prog.marcar_jefe(c, self.tecnicos[2])
        self.assertEqual(list(c.vigentes().filter(es_jefe=True).values_list('usuario', flat=True)), [self.tecnicos[2].id])

    def test_retirar_conserva_historia_y_libera_al_tecnico(self):
        c = self.cuadrilla(tecnicos=2)
        prog.retirar_integrante(c, self.tecnicos[1])
        i = IntegranteCuadrilla.objects.get(cuadrilla=c, usuario=self.tecnicos[1])
        self.assertEqual(i.hasta, HOY)
        self.assertIn(self.tecnicos[1], list(prog.tecnicos_disponibles()))
        self.assertEqual(c.integrantes_en(HOY).count(), 2)  # hoy todavía figuraba

    def test_vehiculo_en_una_sola_cuadrilla_activa(self):
        Cuadrilla.objects.create(nombre='C1', almacen=self.almacen, vehiculo=self.vehiculo)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Cuadrilla.objects.create(nombre='C2', almacen=self.almacen, vehiculo=self.vehiculo)
        self.assertEqual(self.vehiculo.placa, '2345ABC')

    def test_no_se_desactiva_con_ot_programadas(self):
        c = self.cuadrilla()
        prog.programar(self.orden(), c, MANANA, self.oficina)
        with self.assertRaisesMessage(ErrorProgramacion, 'programada(s) o en campo'):
            prog.desactivar_cuadrilla(c)


class ProgramacionTests(Base):
    def setUp(self):
        self.c1 = self.cuadrilla('C1', zonas=[self.zona], capacidad_diaria=1)
        self.c2 = self.cuadrilla('C2')

    def test_programar_desde_pendiente(self):
        ot = self.orden()
        avisos = prog.programar(ot, self.c1, MANANA, self.oficina)
        ot.refresh_from_db()
        self.assertEqual((ot.estado, ot.cuadrilla, ot.fecha_programada, ot.orden_visita), (E.PROGRAMADA, self.c1, MANANA, 1))
        self.assertEqual(avisos, [])
        h = ot.historial.last()
        self.assertEqual((h.estado_anterior, h.estado_nuevo, h.cuadrilla_nueva, h.fecha_nueva), (E.PENDIENTE, E.PROGRAMADA, self.c1, MANANA))

    def test_cuadrilla_incompleta_no_se_programa(self):
        c = self.cuadrilla('C3', tecnicos=1)
        with self.assertRaisesMessage(ErrorProgramacion, 'al menos 2 técnicos'):
            prog.programar(self.orden(), c, MANANA, self.oficina)

    def test_fecha_pasada(self):
        with self.assertRaisesMessage(ErrorProgramacion, 'anterior a hoy'):
            prog.programar(self.orden(), self.c1, HOY - timedelta(days=1), self.oficina)

    def test_reprogramar_exige_motivo_y_registra_lo_anterior(self):
        ot = self.orden()
        prog.programar(ot, self.c1, MANANA, self.oficina)
        with self.assertRaisesMessage(ErrorProgramacion, 'motivo de la reprogramación'):
            prog.programar(ot, self.c2, MANANA, self.oficina)
        prog.programar(ot, self.c2, MANANA, self.oficina, 'El cliente pidió la tarde')
        h = ot.historial.last()
        self.assertEqual((h.cuadrilla_anterior, h.cuadrilla_nueva), (self.c1, self.c2))
        self.assertIn('El cliente pidió la tarde', h.observacion)

    def test_avisos_capacidad_y_zona(self):
        prog.programar(self.orden(), self.c1, MANANA, self.oficina)
        avisos = prog.programar(self.orden(zona=self.otra_zona), self.c1, MANANA, self.oficina)
        self.assertEqual(len(avisos), 2)  # pasa su capacidad (1) y está fuera de su zona

    def test_no_ejecutada_y_vuelta_a_programar(self):
        ot = self.orden()
        prog.programar(ot, self.c1, MANANA, self.oficina)
        with self.assertRaisesMessage(ErrorProgramacion, 'motivo'):
            prog.no_ejecutada(ot, self.oficina, '')
        prog.no_ejecutada(ot, self.oficina, 'Cliente ausente')
        ot.refresh_from_db()
        self.assertEqual((ot.estado, ot.cuadrilla), (E.NO_EJECUTADA, self.c1))
        prog.programar(ot, self.c2, MANANA, self.oficina)  # sin motivo: viene de no ejecutada
        ot.refresh_from_db()
        self.assertEqual((ot.estado, ot.cuadrilla), (E.PROGRAMADA, self.c2))

    def test_en_campo_no_se_reprograma_ni_desasigna(self):
        ot = self.orden()
        prog.programar(ot, self.c1, MANANA, self.oficina)
        OrdenTrabajo.objects.filter(pk=ot.pk).update(estado=E.EN_CAMPO)
        with self.assertRaisesMessage(ErrorProgramacion, 'no se puede programar'):
            prog.programar(ot, self.c2, MANANA, self.oficina, 'cambio de cuadrilla')
        with self.assertRaisesMessage(ErrorProgramacion, 'no se puede desasignar'):
            prog.desasignar(ot, self.oficina, 'ya no va')

    def test_desasignar_vuelve_a_pendiente(self):
        ot = self.orden()
        prog.programar(ot, self.c1, MANANA, self.oficina)
        prog.desasignar(ot, self.oficina, 'Falta material')
        ot.refresh_from_db()
        self.assertEqual((ot.estado, ot.cuadrilla, ot.fecha_programada), (E.PENDIENTE, None, None))
        self.assertEqual(ot.historial.last().cuadrilla_anterior, self.c1)

    def test_ordenar_visitas(self):
        a, b = self.orden(), self.orden()
        prog.programar(a, self.c2, MANANA, self.oficina)
        prog.programar(b, self.c2, MANANA, self.oficina)
        prog.ordenar_visitas(self.c2, MANANA, [b.id, a.id])
        self.assertEqual(OrdenTrabajo.objects.get(pk=b.pk).orden_visita, 1)
        with self.assertRaisesMessage(ErrorProgramacion, 'no coincide'):
            prog.ordenar_visitas(self.c2, MANANA, [a.id])


class ApiTests(Base):
    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.oficina)
        self.c1 = self.cuadrilla('C1')

    def test_programar_varias_y_tablero(self):
        a, b = self.orden(), self.orden(prioridad='ALTA')
        r = self.api.post('/api/operaciones/ordenes/programar_varias/',
                          {'ordenes': [a.id, b.id], 'cuadrilla': self.c1.id, 'fecha': MANANA.isoformat()}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        r = self.api.get(f'/api/operaciones/ordenes/programacion/?fecha={MANANA.isoformat()}')
        self.assertEqual(r.status_code, 200)
        c = r.data['cuadrillas'][0]
        self.assertEqual(c['carga'], 2)
        self.assertEqual(c['ordenes'][0]['numero'], b.numero)  # la urgente va primero
        self.assertTrue(c['lista_para_programar'])

    def test_reprogramar_sin_motivo_responde_400(self):
        ot = self.orden()
        url = f'/api/operaciones/ordenes/{ot.id}/programar/'
        datos = {'cuadrilla': self.c1.id, 'fecha': MANANA.isoformat()}
        self.assertEqual(self.api.post(url, datos, format='json').status_code, 200)
        r = self.api.post(url, {**datos, 'fecha': (MANANA + timedelta(days=1)).isoformat()}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('motivo', r.data['error'])

    def test_crear_cuadrilla_con_tecnicos_en_un_paso(self):
        libres = self.api.get('/api/operaciones/cuadrillas/tecnicos/').data
        self.assertEqual(len(libres), 3)  # 5 técnicos, 2 ya están en C1
        ids = [t['id'] for t in libres[:2]]
        r = self.api.post('/api/operaciones/cuadrillas/', {'almacen': self.almacen.id, 'vehiculo': self.vehiculo.id,
                                                           'zonas': [self.zona.id], 'tecnicos': ids, 'jefe': ids[1]}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(r.data['nombre'].startswith('CUA-'))
        self.assertEqual(len(r.data['integrantes']), 2)
        self.assertEqual([i['usuario']['id'] for i in r.data['integrantes'] if i['es_jefe']], [ids[1]])

    def test_crear_cuadrilla_exige_dos_tecnicos(self):
        libres = self.api.get('/api/operaciones/cuadrillas/tecnicos/').data
        r = self.api.post('/api/operaciones/cuadrillas/', {'almacen': self.almacen.id, 'tecnicos': [libres[0]['id']]}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertFalse(Cuadrilla.objects.exclude(nombre='C1').exists())

    def test_codigo_automatico(self):
        a = Cuadrilla.objects.create(almacen=self.almacen)
        b = Cuadrilla.objects.create(almacen=self.almacen)
        self.assertEqual((a.nombre, b.nombre), ('CUA-01', 'CUA-02'))

    def test_sin_permiso_no_programa(self):
        self.api.force_authenticate(self.tecnicos[4])
        ot = self.orden()
        r = self.api.post(f'/api/operaciones/ordenes/{ot.id}/programar/', {'cuadrilla': self.c1.id, 'fecha': MANANA.isoformat()}, format='json')
        self.assertEqual(r.status_code, 403)

    def test_corregir_ubicacion_queda_en_historial_de_la_ot(self):
        ot = self.orden()
        r = self.api.patch(f'/api/operaciones/solicitudes/{ot.solicitud_id}/', {'latitud': '-16.510000'}, format='json')
        # El programador no tiene permiso de solicitudes en esta prueba: se usa un superusuario
        if r.status_code == 403:
            self.api.force_authenticate(Usuario.objects.create_superuser(codigocotel=9300, password='x', nombres='Admin',
                                                                         apellidopaterno='A', apellidomaterno='A', password_changed=True))
            r = self.api.patch(f'/api/operaciones/solicitudes/{ot.solicitud_id}/', {'latitud': '-16.510000'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(HistorialOT.objects.filter(orden=ot, observacion__startswith='Ubicación corregida').exists())


class DespachoTests(Base):
    """Despacho: ONU a cargo de la cuadrilla (sin atarse a una OT) y material; rendición con instalación por OT,
    consumo por OT, devoluciones, faltantes y equipos recuperados de clientes."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        for codigo in ('DISPONIBLE', 'NUEVO'):
            EstadoMaterialONU.objects.get_or_create(codigo=codigo, defaults={'nombre': codigo.title()})
        gen, _ = EstadoMaterialGeneral.objects.get_or_create(codigo='DISPONIBLE', defaults={'nombre': 'Disponible'})
        und = UnidadMedida.objects.create(codigo='PZA', nombre='Pieza', simbolo='pza')
        metro = UnidadMedida.objects.create(codigo='M', nombre='Metro', simbolo='m')
        t_onu = TipoMaterial.objects.create(codigo='ONU', nombre='ONU', unidad_medida_default=und, es_unico=True)
        t_drop = TipoMaterial.objects.create(codigo='DROP', nombre='Cable drop', unidad_medida_default=metro)
        marca = Marca.objects.create(nombre='Huawei')
        # Básica: sin CATV ni telefonía. Completa: todas las pruebas (vacío = todas)
        cls.m_basica = Modelo.objects.create(marca=marca, nombre='EG8010H', codigo_modelo=1, tipo_material=t_onu, unidad_medida=und,
                                             pruebas_laboratorio=['serie_logica_ok', 'puerto_ethernet_ok'])
        cls.m_completa = Modelo.objects.create(marca=marca, nombre='HG8247H', codigo_modelo=3, tipo_material=t_onu, unidad_medida=und)
        m_drop = Modelo.objects.create(marca=marca, nombre='Drop 1 hilo', codigo_modelo=2, tipo_material=t_drop, unidad_medida=metro)
        ingreso = TipoIngreso.objects.create(codigo='NUEVO', nombre='Compra')
        estado_lote, _ = EstadoLote.objects.get_or_create(codigo='REGISTRADO', defaults={'nombre': 'Registrado'})
        prov = Proveedor.objects.create(nombre_comercial='Proveedor X')
        lote = Lote.objects.create(numero_lote='L-1', tipo_ingreso=ingreso, proveedor=prov, almacen_destino=cls.almacen, estado=estado_lote,
                                   fecha_recepcion=HOY, fecha_inicio_garantia=HOY, fecha_fin_garantia=HOY, created_by=cls.oficina)
        disp = EstadoMaterialONU.objects.get(codigo='DISPONIBLE')

        def onu(i, modelo):
            return Material.objects.create(tipo_material=t_onu, modelo=modelo, lote=lote, tipo_origen=ingreso, codigo_item_equipo='123456',
                                           almacen_actual=cls.almacen, estado_onu=disp, mac_address=f'AA:BB:CC:DD:EE:0{i}',
                                           gpon_serial=f'HWTC0000000{i}')
        cls.basicas = [onu(i, cls.m_basica) for i in range(2)]
        cls.completas = [onu(i, cls.m_completa) for i in range(2, 4)]
        cls.drop = Material.objects.create(tipo_material=t_drop, modelo=m_drop, lote=lote, tipo_origen=ingreso, codigo_item_equipo='654321',
                                           almacen_actual=cls.almacen, estado_general=gen, cantidad=Decimal('500'))
        from .models import KitMaterial
        KitMaterial.objects.create(tipo='INSTALACION', condicion='SIEMPRE', modelo=m_drop, cantidad=Decimal('80'))

    def setUp(self):
        from contratos.models import PlanComercial, TipoServicio
        from .models import PlanAdicional
        self.c = self.cuadrilla('C1')
        ts, _ = TipoServicio.objects.get_or_create(nombre='Internet')
        plan = PlanComercial.objects.create(nombre='Fibra 40', codigo_plan='F40', velocidad_descarga=40, tipo_servicio=ts)
        tv = PlanAdicional.objects.create(tipo='TV', nombre='TV Básica')
        self.ot_internet = self.instalacion(plan)
        self.ot_tv = self.instalacion(plan, tv)
        for o in (self.ot_internet, self.ot_tv):
            prog.programar(o, self.c, MANANA, self.oficina)

    def instalacion(self, plan, tv=None):
        s = Solicitud.objects.create(tipo='INSTALACION', cliente=self.cliente, plan=plan, plan_tv=tv, cantidad_tv=1 if tv else 0,
                                     direccion='Calle 1 #23', latitud=-16.5, longitud=-68.1, zona_cobertura=self.zona)
        return crear_orden(s, self.oficina)

    def ejecutar(self, *ots):
        OrdenTrabajo.objects.filter(pk__in=[o.pk for o in ots]).update(estado=E.EJECUTADA)

    def test_servicios_del_modelo(self):
        self.assertEqual((self.m_basica.soporta_tv, self.m_basica.soporta_telefonia), (False, False))
        self.assertEqual((self.m_completa.soporta_tv, self.m_completa.soporta_telefonia), (True, True))

    def test_onu_sale_a_cargo_de_la_cuadrilla_y_avisa_si_falta_una_compatible(self):
        d, avisos = desp.despachar(self.c, MANANA, [self.basicas[0].id, self.basicas[1].id], [], self.oficina)
        self.assertEqual(Material.objects.get(pk=self.basicas[0].pk).estado_onu.codigo, 'EN_CUADRILLA')
        self.assertIsNone(d.equipos.first().orden)  # no se ata a una OT al salir
        self.assertEqual(len(avisos), 1)  # la OT con TV no tiene ONU con CATV
        self.assertIn(self.ot_tv.numero, avisos[0])
        _, avisos = desp.despachar(self.c, MANANA, [self.completas[0].id], [], self.oficina)  # se suma al mismo despacho
        self.assertEqual(avisos, [])

    def test_rendicion_completa(self):
        d, _ = desp.despachar(self.c, MANANA, [self.basicas[0].id, self.completas[0].id, self.basicas[1].id],
                              [(self.drop.id, '200')], self.oficina)
        self.ejecutar(self.ot_internet, self.ot_tv)
        eq = {e.material_id: e.id for e in d.equipos.all()}
        linea = d.materiales.get()
        # Una ONU básica no sirve para la OT con TV
        with self.assertRaisesMessage(ErrorProgramacion, 'no tiene los servicios'):
            desp.rendir(d, {eq[self.basicas[0].id]: ('INSTALADO', self.ot_tv.id), eq[self.completas[0].id]: ('DEVUELTO', None),
                            eq[self.basicas[1].id]: ('DEVUELTO', None)}, {}, {linea.id: '200'}, [], self.oficina)
        desp.rendir(d, {eq[self.basicas[0].id]: ('INSTALADO', self.ot_internet.id),
                        eq[self.completas[0].id]: ('INSTALADO', self.ot_tv.id),
                        eq[self.basicas[1].id]: ('DEVUELTO', None)},
                    {linea.id: {self.ot_internet.id: '70', self.ot_tv.id: '95'}}, {linea.id: '35'}, [], self.oficina)
        onu = Material.objects.get(pk=self.completas[0].pk)
        self.assertEqual((onu.estado_onu.codigo, onu.orden_trabajo), ('INSTALADO', self.ot_tv.numero))
        self.assertEqual(Material.objects.get(pk=self.basicas[1].pk).estado_onu.codigo, 'DISPONIBLE')
        self.assertEqual(Material.objects.get(pk=self.drop.pk).cantidad, Decimal('335'))  # 500 - 200 + 35
        from .models import ConsumoOT
        self.assertEqual(sorted(ConsumoOT.objects.values_list('cantidad', flat=True)), [Decimal('70'), Decimal('95')])

    def test_faltante_exige_explicacion_y_consumo_solo_en_ot_ejecutadas(self):
        d, _ = desp.despachar(self.c, MANANA, [self.basicas[0].id], [(self.drop.id, '100')], self.oficina)
        eq, linea = d.equipos.get(), d.materiales.get()
        with self.assertRaisesMessage(ErrorProgramacion, 'solo se registra consumo en OT ejecutadas'):
            desp.rendir(d, {eq.id: ('DEVUELTO', None)}, {linea.id: {self.ot_internet.id: '80'}}, {linea.id: '20'}, [], self.oficina)
        with self.assertRaisesMessage(ErrorProgramacion, 'faltantes'):
            desp.rendir(d, {eq.id: ('FALTANTE', None)}, {}, {linea.id: '100'}, [], self.oficina)
        desp.rendir(d, {eq.id: ('FALTANTE', None)}, {}, {linea.id: '100'}, [], self.oficina, 'Se perdió en el vehículo')
        self.assertEqual(Material.objects.get(pk=self.basicas[0].pk).estado_onu.codigo, 'FALTANTE')

    def test_no_despacha_si_hay_un_dia_anterior_sin_rendir(self):
        d, _ = desp.despachar(self.c, MANANA, [self.basicas[0].id], [], self.oficina)
        Despacho.objects.filter(pk=d.pk).update(fecha=HOY)
        with self.assertRaisesMessage(ErrorProgramacion, 'sin rendir'):
            desp.despachar(self.c, MANANA, [self.basicas[1].id], [], self.oficina)

    def test_equipo_recuperado_de_un_retiro_vuelve_como_reingresado(self):
        instalada = self.completas[1]
        Material.objects.filter(pk=instalada.pk).update(estado_onu=EstadoMaterialONU.objects.get(codigo='INSTALADO'))
        s = Solicitud.objects.create(tipo='RETIRO', cliente=self.cliente, direccion='Calle 1 #23', latitud=-16.5, longitud=-68.1,
                                     zona_cobertura=self.zona)
        retiro = crear_orden(s, self.oficina)
        prog.programar(retiro, self.c, MANANA, self.oficina)
        d, _ = desp.despachar(self.c, MANANA, [self.basicas[0].id], [], self.oficina)
        self.ejecutar(retiro)
        desp.rendir(d, {d.equipos.get().id: ('DEVUELTO', None)}, {}, {},
                    [(retiro.id, instalada.gpon_serial, ''), (retiro.id, 'ZTEG99999999', 'Equipo antiguo sin registro')], self.oficina)
        m = Material.objects.get(pk=instalada.pk)
        self.assertEqual(m.estado_onu.codigo, 'REINGRESADO')
        self.assertEqual(d.recuperados.filter(material__isnull=True).count(), 1)

    def test_api_requerimiento_buscar_despacho(self):
        api = APIClient()
        api.force_authenticate(self.oficina)
        r = api.get(f'/api/operaciones/despachos/requerimiento/?cuadrilla={self.c.id}&fecha={MANANA.isoformat()}')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(len(r.data['ordenes']), 2)
        self.assertEqual(r.data['material'][0]['sugerido'], 160.0)  # 2 instalaciones × 80 m
        r = api.get(f'/api/operaciones/despachos/buscar/?cuadrilla={self.c.id}&serie=hwtc00000002')
        self.assertEqual((r.status_code, r.data['tv']), (200, True))
        r = api.post('/api/operaciones/despachos/', {'cuadrilla': self.c.id, 'fecha': MANANA.isoformat(), 'onus': [self.completas[0].id],
                                                     'materiales': [{'material': self.drop.id, 'cantidad': 160}]}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data['estado']['codigo'], 'ENTREGADO')
        self.assertEqual(len(r.data['avisos']), 1)  # falta una ONU para la segunda instalación
        r = api.get(f'/api/operaciones/despachos/buscar/?cuadrilla={self.c.id}&serie=HWTC00000002')
        self.assertEqual(r.status_code, 400)  # ya salió
        t = api.get(f'/api/operaciones/ordenes/programacion/?fecha={MANANA.isoformat()}').data['cuadrillas'][0]
        self.assertEqual(t['despacho']['onus'], 1)
        r = api.get(f'/api/operaciones/cuadrillas/{self.c.id}/en_poder/')
        self.assertEqual(len(r.data['onus']), 1)

    def test_sugerir_onus_cubre_con_el_modelo_mas_sencillo(self):
        onus, sin_stock = desp.sugerir_onus(self.c, MANANA)
        self.assertEqual(sin_stock, 0)
        self.assertEqual(sorted(m.modelo_id for m in onus), sorted([self.m_basica.id, self.m_completa.id]))
        # Ya elegida la completa, solo falta una básica
        onus, _ = desp.sugerir_onus(self.c, MANANA, [self.completas[0].id])
        self.assertEqual([m.modelo_id for m in onus], [self.m_basica.id])

    def test_buscador_de_disponibles(self):
        api = APIClient()
        api.force_authenticate(self.oficina)
        url = f'/api/operaciones/despachos/disponibles/?cuadrilla={self.c.id}'
        self.assertEqual(api.get(url).data['count'], 4)
        self.assertEqual(api.get(url + '&search=0000002').data['count'], 1)
        self.assertEqual(api.get(url + '&tv=true').data['count'], 2)  # solo el modelo con CATV
        self.assertEqual(api.get(url + f'&modelo={self.m_basica.id}').data['count'], 2)
        r = api.get(f'/api/operaciones/despachos/sugerir/?cuadrilla={self.c.id}&fecha={MANANA.isoformat()}')
        self.assertEqual(len(r.data['onus']), 2)

    def test_aviso_al_programar_en_cuadrilla_ya_despachada(self):
        desp.despachar(self.c, MANANA, [self.basicas[0].id], [], self.oficina)
        avisos = prog.programar(self.orden(), self.c, MANANA, self.oficina)
        self.assertTrue(any('ya recibió su despacho' in a for a in avisos))


class AtrasadasTests(Base):
    def test_ot_de_dia_pasado_sigue_programada_y_se_informa(self):
        c = self.cuadrilla()
        vieja, nueva = self.orden(), self.orden()
        prog.programar(vieja, c, MANANA, self.oficina)
        prog.programar(nueva, c, MANANA, self.oficina)
        OrdenTrabajo.objects.filter(pk=vieja.pk).update(fecha_programada=HOY - timedelta(days=1))
        self.assertEqual([o.pk for o in prog.atrasadas()], [vieja.pk])
        api = APIClient()
        api.force_authenticate(self.oficina)
        r = api.get(f'/api/operaciones/ordenes/programacion/?fecha={HOY.isoformat()}')
        self.assertEqual([o['numero'] for o in r.data['atrasadas']], [vieja.numero])
        vieja.refresh_from_db()
        self.assertEqual(vieja.estado, E.PROGRAMADA)  # el sistema no le cambia el estado
        # Se reprograma con motivo
        prog.programar(vieja, c, MANANA, self.oficina, 'El cliente no estaba')


class PlazoAttTests(Base):
    """Plazo ATT (RAR 589/2025): instalación 7 días, reparación 24 h. Solo avisa; no cambia estados."""

    def _ot(self, tipo, hace):
        s = Solicitud.objects.create(tipo=tipo, cliente=self.cliente, direccion='Calle 1 #23', latitud=-16.5, longitud=-68.1,
                                     zona_cobertura=self.zona)
        Solicitud.objects.filter(pk=s.pk).update(created_at=timezone.now() - hace)
        return crear_orden(Solicitud.objects.get(pk=s.pk), self.oficina)

    def test_semaforo_y_filtros(self):
        from . import plazos
        from datetime import timedelta as td
        vencida = self._ot('INSTALACION', td(days=9))
        por_vencer = self._ot('INSTALACION', td(days=6))
        en_plazo = self._ot('INSTALACION', td(days=1))
        rep = self._ot('REPARACION', td(hours=20))
        retiro = self._ot('RETIRO', td(days=30))
        self.assertEqual(plazos.plazo(vencida)['estado'], 'VENCIDA')
        self.assertEqual(plazos.plazo(por_vencer)['estado'], 'POR_VENCER')
        self.assertEqual(plazos.plazo(en_plazo)['estado'], 'EN_PLAZO')
        self.assertEqual(plazos.plazo(rep)['estado'], 'POR_VENCER')
        self.assertIsNone(plazos.plazo(retiro))
        self.assertEqual(set(OrdenTrabajo.objects.filter(plazos.filtro('vencidas')).values_list('pk', flat=True)), {vencida.pk})
        self.assertEqual(set(OrdenTrabajo.objects.filter(plazos.filtro('por_vencer')).values_list('pk', flat=True)),
                         {por_vencer.pk, rep.pk})
        vencida.refresh_from_db()
        self.assertEqual(vencida.estado, E.PENDIENTE)  # el plazo no cambia el estado
        api = APIClient()
        api.force_authenticate(self.oficina)
        r = api.get('/api/operaciones/ordenes/?plazo=vencidas')
        self.assertEqual([o['numero'] for o in r.data['results']], [vencida.numero])
        self.assertEqual(r.data['results'][0]['plazo']['estado'], 'VENCIDA')
        r = api.get(f'/api/operaciones/ordenes/programacion/?fecha={HOY.isoformat()}')
        self.assertEqual(r.data['plazos'], {'vencidas': 1, 'por_vencer': 2})

    def test_cumplido_o_no_al_ejecutar(self):
        from . import plazos
        from datetime import timedelta as td
        ot = self._ot('INSTALACION', td(days=2))
        ot.cambiar_estado(E.EJECUTADA, self.oficina, 'prueba')
        self.assertEqual(plazos.plazo(plazos.con_ejecucion(OrdenTrabajo.objects.filter(pk=ot.pk)).get())['estado'], 'CUMPLIDO')
        tarde = self._ot('INSTALACION', td(days=10))
        tarde.cambiar_estado(E.EJECUTADA, self.oficina, 'prueba')
        self.assertEqual(plazos.plazo(tarde)['estado'], 'INCUMPLIDO')
