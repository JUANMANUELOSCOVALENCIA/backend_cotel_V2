# ======================================================
# operaciones/despacho.py
# Despacho diario a una cuadrilla y su rendición (trazabilidad de equipos y consumo de material).
#
# Al salir (despacho):
#   - ONU: el almacén escanea cada equipo que entrega. Queda EN_CUADRILLA, a cargo de la cuadrilla,
#     SIN atarse a una OT (como en el procedimiento de COTEL: la ONU se asocia al instalarla).
#     Se compara con lo que necesitan las OT del día: cada instalación requiere una ONU cuyo modelo
#     tenga los servicios del plan (TV cable → puerto CATV, telefonía → puerto POTS).
#   - Material por cantidad: sale de los registros del almacén; se sugiere con los kits por tipo de trabajo.
#
# Al volver (rendición):
#   - Cada ONU: INSTALADA en una OT ejecutada y compatible, DEVUELTA (vuelve a DISPONIBLE) o FALTANTE.
#   - Material: lo usado en cada OT ejecutada (consumo real → EOQ) y lo devuelto. La diferencia es faltante.
#   - Equipos recuperados de clientes (retiro / cambio): vuelven al almacén como REINGRESADO (→ laboratorio).
#   Lo faltante queda a cargo de la cuadrilla y exige explicación.
#
# Cada movimiento queda en el historial del equipo o material (almacenes.HistorialMaterial).
# ======================================================
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from almacenes.models import EstadoMaterialONU, HistorialMaterial, Material

from .models import (ConsumoOT, Despacho, DespachoEquipo, DespachoMaterial, EquipoRecuperado, KitMaterial, OrdenTrabajo,
                     Solicitud)
from .programacion import OCUPAN, ErrorProgramacion as ErrorDespacho

E = OrdenTrabajo.Estado
T = Solicitud.Tipo
R = DespachoEquipo.Resultado
# Trabajos que instalan una ONU (en reparación solo si se cambia el equipo)
TIPOS_CON_ONU = (T.INSTALACION, T.REPARACION)
# Trabajos de los que se puede recuperar un equipo del cliente
TIPOS_RECUPERAN = (T.RETIRO, T.REPARACION, T.TRASLADO)
EJECUTADAS = (E.EJECUTADA, E.VERIFICADA, E.CERRADA)


def _n(d):
    d = Decimal(d)
    return f'{d.normalize():f}' if d == d.to_integral() else f'{d:f}'


def _estado_onu(codigo):
    estado = EstadoMaterialONU.objects.filter(codigo=codigo).first()
    if not estado:
        raise ErrorDespacho(f'No existe el estado de ONU "{codigo}". Ejecuta las migraciones de operaciones.')
    return estado


def _historial(material, usuario, motivo, anterior='', nuevo='', obs='', almacen_anterior=None):
    HistorialMaterial.objects.create(
        material=material, estado_anterior=anterior[:25], estado_nuevo=nuevo[:25],
        almacen_anterior=almacen_anterior or material.almacen_actual, almacen_nuevo=material.almacen_actual,
        motivo=motivo[:100], observaciones=obs, usuario_responsable=usuario,
    )


def _decimal(valor, campo):
    try:
        d = Decimal(str(valor if valor not in (None, '') else 0))
    except (InvalidOperation, TypeError, ValueError):
        raise ErrorDespacho(f'{campo}: cantidad no válida.')
    if d < 0:
        raise ErrorDespacho(f'{campo}: la cantidad no puede ser negativa.')
    return d


def _modelo_txt(modelo):
    return f'{modelo.marca.nombre} {modelo.nombre}' if modelo.marca_id else modelo.nombre


# ---------------- Servicios y compatibilidad ----------------

def servicios_ot(orden):
    """Servicios que debe dar la ONU de esta OT: {'tv': bool, 'telefonia': bool}."""
    s = orden.solicitud
    if orden.tipo != T.INSTALACION:
        return {'tv': False, 'telefonia': False}
    return {'tv': bool(s.plan_tv_id), 'telefonia': bool(s.plan_telefonia_id)}


def servicios_onu(material):
    m = material.modelo
    return {'tv': m.soporta_tv, 'telefonia': m.soporta_telefonia}


def compatible(onu_servicios, ot_servicios):
    return all(onu_servicios[k] for k, necesita in ot_servicios.items() if necesita)


def cobertura(ots, onus):
    """
    ¿Las ONU alcanzan para las instalaciones? Asigna a cada OT (las más exigentes primero) la ONU
    compatible más sencilla, para no gastar equipos completos en planes solo internet.
    ots:  [(id, servicios)]   onus: [(id, servicios)]
    Devuelve (asignacion {ot_id: onu_id}, ots_sin_onu [ids], onus_sobrantes [ids]).
    """
    def peso(sv):
        return int(sv['tv']) + int(sv['telefonia'])
    libres = sorted(onus, key=lambda x: peso(x[1]))
    asignacion, sin = {}, []
    for ot_id, sv in sorted(ots, key=lambda x: -peso(x[1])):
        elegida = next((o for o in libres if compatible(o[1], sv)), None)
        if elegida:
            asignacion[ot_id] = elegida[0]
            libres.remove(elegida)
        else:
            sin.append(ot_id)
    return asignacion, sin, [o[0] for o in libres]


# ---------------- Consultas ----------------

def onus_disponibles(almacen):
    """ONU que el almacén puede entregar, en orden FIFO (lote más antiguo primero: corre su garantía)."""
    return (Material.objects.filter(almacen_actual=almacen, tipo_material__es_unico=True, estado_onu__codigo='DISPONIBLE',
                                    traspaso_actual__isnull=True)
            .select_related('modelo__marca', 'lote').order_by('lote__fecha_recepcion', 'id'))


def modelos_disponibles(almacen):
    """Modelos de ONU con stock disponible en el almacén: [(modelo, cantidad)], con sus servicios."""
    from django.db.models import Count
    from almacenes.models import Modelo
    n = dict(onus_disponibles(almacen).order_by().values_list('modelo_id').annotate(c=Count('id')))
    return [(m, n[m.id]) for m in Modelo.objects.filter(id__in=n).select_related('marca').order_by('nombre')]


def buscar_disponibles(almacen, texto='', modelo_id=None, servicios=None):
    """
    Buscador de ONU para el despacho (como el de Equipos ONU): GPON SN, MAC, D-SN, código interno o lote.
    servicios: {'tv': bool, 'telefonia': bool} → solo modelos que los tengan.
    """
    qs = onus_disponibles(almacen)
    t = (texto or '').strip()
    if t:
        qs = qs.filter(Q(gpon_serial__icontains=t) | Q(mac_address__icontains=t.replace('-', ':')) | Q(codigo_interno__icontains=t)
                       | Q(serial_manufacturer__icontains=t) | Q(lote__numero_lote__icontains=t))
    if modelo_id:
        qs = qs.filter(modelo_id=modelo_id)
    if servicios and any(servicios.values()):
        qs = qs.filter(modelo_id__in=[m.id for m, _ in modelos_disponibles(almacen)
                                      if compatible({'tv': m.soporta_tv, 'telefonia': m.soporta_telefonia}, servicios)])
    return qs


def sugerir_onus(cuadrilla, fecha, ya=()):
    """
    Propone las ONU que faltan para cubrir las instalaciones del día, considerando las ya entregadas
    y las ya elegidas (`ya`: ids). A cada instalación sin cubrir le toca el modelo compatible más sencillo
    y, dentro de él, la ONU del lote más antiguo (FIFO).
    Devuelve (onus, cuántas instalaciones quedan sin ONU porque no hay stock compatible).
    """
    ots, _ = requerimiento(cuadrilla, fecha)
    instalaciones = [(o.id, servicios_ot(o)) for o in ots if o.tipo == T.INSTALACION]
    entregadas = list(DespachoEquipo.objects.filter(despacho__cuadrilla=cuadrilla, despacho__fecha=fecha,
                                                    despacho__estado=Despacho.Estado.ENTREGADO, resultado=R.PENDIENTE)
                      .values_list('material_id', flat=True))
    elegidas = list(Material.objects.filter(pk__in=list(entregadas) + list(ya)).select_related('modelo'))
    _, sin, _ = cobertura(instalaciones, [(m.id, servicios_onu(m)) for m in elegidas])
    if not sin:
        return [], 0
    necesitan = sorted((dict(instalaciones)[i] for i in sin), key=lambda sv: -(int(sv['tv']) + int(sv['telefonia'])))
    stock = {}
    for m in onus_disponibles(cuadrilla.almacen).exclude(pk__in=ya):
        stock.setdefault(m.modelo_id, []).append(m)
    modelos = sorted(({'id': mid, 'sv': servicios_onu(lista[0])} for mid, lista in stock.items()),
                     key=lambda x: int(x['sv']['tv']) + int(x['sv']['telefonia']))
    sugeridas, sin_stock = [], 0
    for sv in necesitan:
        modelo = next((x for x in modelos if stock[x['id']] and compatible(x['sv'], sv)), None)
        if modelo:
            sugeridas.append(stock[modelo['id']].pop(0))
        else:
            sin_stock += 1
    return sugeridas, sin_stock


def granel_disponible(almacen):
    return (Material.objects.filter(almacen_actual=almacen, tipo_material__es_unico=False, estado_general__codigo='DISPONIBLE',
                                    cantidad__gt=0)
            .select_related('modelo__unidad_medida', 'lote').order_by('modelo__nombre', 'lote__fecha_recepcion', 'id'))


def ordenes_del_dia(cuadrilla, fecha):
    return (OrdenTrabajo.objects.filter(cuadrilla=cuadrilla, fecha_programada=fecha, estado__in=OCUPAN + (E.NO_EJECUTADA,) + EJECUTADAS)
            .select_related('solicitud__cliente', 'solicitud__plan_tv', 'solicitud__plan_telefonia').order_by('orden_visita', 'id'))


def requerimiento(cuadrilla, fecha):
    """Lo que necesitan las OT programadas del día: ONU por servicios y material según los kits."""
    ots = [o for o in ordenes_del_dia(cuadrilla, fecha) if o.estado in (E.PROGRAMADA, E.EN_CAMPO)]
    kits = list(KitMaterial.objects.select_related('modelo__unidad_medida'))
    material = {}
    for o in ots:
        sv = servicios_ot(o)
        for k in kits:
            aplica = k.tipo == o.tipo and (k.condicion == KitMaterial.Condicion.SIEMPRE
                                           or (k.condicion == KitMaterial.Condicion.TV and sv['tv'])
                                           or (k.condicion == KitMaterial.Condicion.TELEFONIA and sv['telefonia']))
            if aplica:
                fila = material.setdefault(k.modelo_id, {'modelo': k.modelo, 'cantidad': Decimal(0)})
                fila['cantidad'] += k.cantidad
    return ots, list(material.values())


def pendiente_de_rendir(cuadrilla, excluir_fecha=None):
    qs = Despacho.objects.filter(cuadrilla=cuadrilla, estado=Despacho.Estado.ENTREGADO)
    if excluir_fecha:
        qs = qs.exclude(fecha=excluir_fecha)
    return qs.order_by('fecha').first()


def en_poder(cuadrilla):
    """Lo que la cuadrilla tiene ahora a su cargo (despachos sin rendir)."""
    equipos = (DespachoEquipo.objects.filter(despacho__cuadrilla=cuadrilla, despacho__estado=Despacho.Estado.ENTREGADO,
                                             resultado=R.PENDIENTE).select_related('material__modelo__marca', 'despacho'))
    materiales = (DespachoMaterial.objects.filter(despacho__cuadrilla=cuadrilla, despacho__estado=Despacho.Estado.ENTREGADO)
                  .select_related('material__modelo__unidad_medida', 'despacho'))
    return list(equipos), list(materiales)


def _buscar_onu(texto):
    t = (texto or '').strip().upper()
    if not t:
        return None
    return (Material.objects.filter(tipo_material__es_unico=True)
            .filter(Q(gpon_serial__iexact=t) | Q(mac_address__iexact=t.replace('-', ':')) | Q(codigo_interno__iexact=t))
            .select_related('estado_onu', 'modelo__marca').first())


# ---------------- Despachar ----------------

def despachar(cuadrilla, fecha, onus, materiales, usuario, observaciones=''):
    """
    onus:       [material_id]               ONU que salen (a cargo de la cuadrilla)
    materiales: [(material_id, cantidad)]    material por cantidad
    Si la cuadrilla ya tiene despacho ese día (sin rendir), se agrega a ese mismo.
    Devuelve (despacho, avisos).
    """
    if not onus and not materiales:
        raise ErrorDespacho('Escanea al menos una ONU o agrega material.')
    if fecha < timezone.localdate():
        raise ErrorDespacho('No se puede despachar para una fecha pasada.')
    if not cuadrilla.activo:
        raise ErrorDespacho(f'La cuadrilla {cuadrilla} está inactiva.')
    previo = pendiente_de_rendir(cuadrilla, excluir_fecha=fecha)
    if previo:
        raise ErrorDespacho(f'{cuadrilla} tiene sin rendir el despacho {previo.numero} del {previo.fecha:%d/%m/%Y}. '
                            'Registra primero su rendición.')
    almacen = cuadrilla.almacen

    with transaction.atomic():
        despacho = (Despacho.objects.select_for_update().filter(cuadrilla=cuadrilla, fecha=fecha)
                    .exclude(estado=Despacho.Estado.ANULADO).first())
        if despacho and despacho.estado != Despacho.Estado.ENTREGADO:
            raise ErrorDespacho(f'El despacho {despacho.numero} ya se rindió; no se le puede agregar nada.')
        if not despacho:
            despacho = Despacho.objects.create(cuadrilla=cuadrilla, fecha=fecha, almacen=almacen, entregado_por=usuario,
                                               observaciones=(observaciones or '').strip())
        elif (observaciones or '').strip():
            despacho.observaciones = '\n'.join(filter(None, [despacho.observaciones, observaciones.strip()]))
            despacho.save(update_fields=['observaciones', 'updated_at'])

        en_cuadrilla = _estado_onu('EN_CUADRILLA')
        if len(set(onus)) != len(onus):
            raise ErrorDespacho('Hay una ONU repetida en la lista.')
        for material_id in onus:
            m = (Material.objects.select_for_update(of=('self',)).select_related('estado_onu', 'tipo_material', 'modelo')
                 .filter(pk=material_id).first())
            if not m or not m.tipo_material.es_unico:
                raise ErrorDespacho('Equipo no válido.')
            nombre = m.gpon_serial or m.codigo_interno
            if m.almacen_actual_id != almacen.id:
                raise ErrorDespacho(f'La ONU {nombre} no está en {almacen.nombre}.')
            if m.traspaso_actual_id or not m.estado_onu_id or m.estado_onu.codigo != 'DISPONIBLE':
                estado = m.estado_onu.nombre if m.estado_onu_id else 'sin estado'
                raise ErrorDespacho(f'La ONU {nombre} está {estado.lower()}; solo se despachan ONU disponibles.')
            DespachoEquipo.objects.create(despacho=despacho, material=m)
            anterior = m.estado_onu.codigo
            m.estado_onu = en_cuadrilla
            m.save(update_fields=['estado_onu', 'updated_at'])
            _historial(m, usuario, f'Entregada a {cuadrilla} ({despacho.numero})', anterior, en_cuadrilla.codigo)

        for material_id, cantidad in materiales:
            cantidad = _decimal(cantidad, 'Material')
            m = (Material.objects.select_for_update(of=('self',)).select_related('estado_general', 'tipo_material', 'modelo')
                 .filter(pk=material_id).first())
            if not m or m.tipo_material.es_unico:
                raise ErrorDespacho('Material por cantidad no válido.')
            if m.almacen_actual_id != almacen.id or not m.estado_general_id or m.estado_general.codigo != 'DISPONIBLE':
                raise ErrorDespacho(f'{m.modelo.nombre} no está disponible en {almacen.nombre}.')
            if cantidad <= 0 or cantidad > m.cantidad:
                raise ErrorDespacho(f'{m.modelo.nombre}: la cantidad debe ser mayor a 0 y como máximo {_n(m.cantidad)}.')
            linea, _ = DespachoMaterial.objects.get_or_create(despacho=despacho, material=m, defaults={'cantidad': 0})
            linea.cantidad += cantidad
            linea.save(update_fields=['cantidad'])
            m.cantidad -= cantidad
            m.save(update_fields=['cantidad', 'updated_at'])
            _historial(m, usuario, f'Salen {_n(cantidad)} a {cuadrilla} ({despacho.numero})', obs=f'Quedan {_n(m.cantidad)}')

    return despacho, avisos_despacho(despacho)


def avisos_despacho(despacho):
    """Compara las ONU entregadas (sin instalar) con las instalaciones del día."""
    ots, _ = requerimiento(despacho.cuadrilla, despacho.fecha)
    instalaciones = [(o.id, servicios_ot(o)) for o in ots if o.tipo == T.INSTALACION]
    onus = [(e.material_id, servicios_onu(e.material))
            for e in despacho.equipos.filter(resultado=R.PENDIENTE).select_related('material__modelo')]
    _, sin, _ = cobertura(instalaciones, onus)
    avisos = []
    if sin:
        numeros = {o.id: o for o in ots}
        detalle = ', '.join(f'{numeros[i].numero} ({_txt_servicios(servicios_ot(numeros[i]))})' for i in sin)
        avisos.append(f'Faltan ONU compatibles para: {detalle}.')
    return avisos


def _txt_servicios(sv):
    return ' + '.join(['Internet'] + (['TV'] if sv['tv'] else []) + (['Telefonía'] if sv['telefonia'] else []))


# ---------------- Rendición ----------------

def rendir(despacho, equipos, consumos, devoluciones, recuperados, usuario, observaciones=''):
    """
    equipos:      {despacho_equipo_id: (resultado, orden_id|None)}   todas las ONU entregadas
    consumos:     {despacho_material_id: {orden_id: cantidad}}       lo usado en cada OT ejecutada
    devoluciones: {despacho_material_id: cantidad}                   lo que vuelve al almacén
    recuperados:  [(orden_id, serial, observacion)]                  equipos traídos de clientes
    """
    obs = (observaciones or '').strip()
    with transaction.atomic():
        despacho = Despacho.objects.select_for_update().select_related('cuadrilla', 'almacen').get(pk=despacho.pk)
        if despacho.estado != Despacho.Estado.ENTREGADO:
            raise ErrorDespacho(f'El despacho {despacho.numero} está {despacho.get_estado_display().lower()}.')
        cuadrilla = despacho.cuadrilla
        del_dia = {o.id: o for o in ordenes_del_dia(cuadrilla, despacho.fecha)}
        ejecutadas = {i: o for i, o in del_dia.items() if o.estado in EJECUTADAS}
        faltan = False

        # --- ONU ---
        estados = {c: _estado_onu(c) for c in ('INSTALADO', 'DISPONIBLE', 'FALTANTE')}
        usadas_en = {}
        for eq in despacho.equipos.select_related('material__estado_onu', 'material__modelo'):
            res, orden_id = equipos.get(eq.id, (None, None))
            serie = eq.material.gpon_serial or eq.material.codigo_interno
            if res not in (R.INSTALADO, R.DEVUELTO, R.FALTANTE):
                raise ErrorDespacho(f'Indica qué pasó con la ONU {serie}.')
            m = Material.objects.select_for_update(of=('self',)).select_related('estado_onu', 'modelo').get(pk=eq.material_id)
            anterior = m.estado_onu.codigo if m.estado_onu_id else ''
            eq.orden = None
            if res == R.INSTALADO:
                orden = ejecutadas.get(orden_id)
                if not orden:
                    raise ErrorDespacho(f'ONU {serie}: indica en qué OT ejecutada de {cuadrilla} se instaló '
                                        '(si la OT no está ejecutada, la ONU vuelve como devuelta).')
                if orden.tipo not in TIPOS_CON_ONU:
                    raise ErrorDespacho(f'La {orden.numero} es {orden.get_tipo_display().lower()}: no lleva ONU nueva.')
                if orden.id in usadas_en:
                    raise ErrorDespacho(f'La {orden.numero} ya tiene la ONU {usadas_en[orden.id]}.')
                if not compatible(servicios_onu(m), servicios_ot(orden)):
                    raise ErrorDespacho(f'La ONU {serie} ({_modelo_txt(m.modelo)}) no tiene los servicios de la {orden.numero} '
                                        f'({_txt_servicios(servicios_ot(orden))}).')
                usadas_en[orden.id] = serie
                eq.orden = orden
                m.estado_onu, m.orden_trabajo = estados['INSTALADO'], orden.numero
                motivo = f'Instalada en {orden.numero} ({despacho.numero})'
            elif res == R.DEVUELTO:
                m.estado_onu, m.orden_trabajo = estados['DISPONIBLE'], ''
                motivo = f'Devuelta por {cuadrilla} ({despacho.numero})'
            else:
                m.estado_onu = estados['FALTANTE']
                motivo = f'Faltante: a cargo de {cuadrilla} ({despacho.numero})'
                faltan = True
            m.save(update_fields=['estado_onu', 'orden_trabajo', 'updated_at'])
            _historial(m, usuario, motivo, anterior, m.estado_onu.codigo, obs)
            eq.resultado = res
            eq.save(update_fields=['resultado', 'orden'])

        # --- Material por cantidad ---
        for linea in despacho.materiales.select_related('material__modelo'):
            nombre = linea.material.modelo.nombre
            por_ot = consumos.get(linea.id) or {}
            usada = Decimal(0)
            for orden_id, cant in por_ot.items():
                cant = _decimal(cant, nombre)
                if not cant:
                    continue
                orden = ejecutadas.get(orden_id)
                if not orden:
                    raise ErrorDespacho(f'{nombre}: solo se registra consumo en OT ejecutadas de {cuadrilla}.')
                ConsumoOT.objects.create(despacho_material=linea, orden=orden, cantidad=cant)
                usada += cant
            devuelta = _decimal(devoluciones.get(linea.id), nombre)
            if usada + devuelta > linea.cantidad:
                raise ErrorDespacho(f'{nombre}: lo usado ({_n(usada)}) más lo devuelto ({_n(devuelta)}) '
                                    f'supera lo entregado ({_n(linea.cantidad)}).')
            linea.usada, linea.devuelta = usada, devuelta
            linea.save(update_fields=['usada', 'devuelta'])
            m = Material.objects.select_for_update(of=('self',)).get(pk=linea.material_id)
            if devuelta:
                m.cantidad += devuelta
                m.save(update_fields=['cantidad', 'updated_at'])
            falta = linea.faltante
            faltan = faltan or falta > 0
            _historial(m, usuario, f'Rendición {despacho.numero}: usado {_n(usada)}, devuelto {_n(devuelta)}',
                       obs='\n'.join(filter(None, [f'Faltante a cargo de {cuadrilla}: {_n(falta)}' if falta else '', obs])))

        # --- Equipos recuperados de clientes ---
        reingresado = None
        for orden_id, serial, nota in recuperados:
            serial = (serial or '').strip().upper()
            if not serial:
                continue
            orden = ejecutadas.get(orden_id)
            if not orden or orden.tipo not in TIPOS_RECUPERAN:
                raise ErrorDespacho(f'Equipo {serial}: indica la OT ejecutada de retiro, reparación o traslado de donde se recuperó.')
            m = _buscar_onu(serial)
            if m:
                m = Material.objects.select_for_update(of=('self',)).select_related('estado_onu').get(pk=m.pk)
                if m.estado_onu_id and m.estado_onu.codigo in ('DISPONIBLE', 'EN_CUADRILLA', 'EN_LABORATORIO'):
                    raise ErrorDespacho(f'El equipo {serial} figura {m.estado_onu.nombre.lower()}: no puede venir de un cliente.')
                reingresado = reingresado or _estado_onu('REINGRESADO')
                anterior, almacen_anterior = (m.estado_onu.codigo if m.estado_onu_id else ''), m.almacen_actual
                m.estado_onu, m.almacen_actual, m.orden_trabajo = reingresado, despacho.almacen, ''
                m.save(update_fields=['estado_onu', 'almacen_actual', 'orden_trabajo', 'updated_at'])
                _historial(m, usuario, f'Recuperado de {orden.numero} por {cuadrilla} ({despacho.numero})', anterior,
                           reingresado.codigo, nota or '', almacen_anterior=almacen_anterior)
            EquipoRecuperado.objects.create(despacho=despacho, orden=orden, serial=serial, material=m,
                                            observacion=(nota or '')[:200])

        if faltan and len(obs) < 5:
            raise ErrorDespacho('Hay faltantes: explica en las observaciones qué pasó (mínimo 5 caracteres).')
        despacho.estado = Despacho.Estado.RENDIDO
        despacho.rendido_por, despacho.rendido_at, despacho.observaciones_rendicion = usuario, timezone.now(), obs
        despacho.save()
    return despacho


def anular(despacho, usuario, motivo):
    """Error al despachar: todo vuelve al almacén tal como salió."""
    motivo = (motivo or '').strip()
    if len(motivo) < 5:
        raise ErrorDespacho('Indica el motivo (mínimo 5 caracteres).')
    with transaction.atomic():
        despacho = Despacho.objects.select_for_update().get(pk=despacho.pk)
        if despacho.estado != Despacho.Estado.ENTREGADO:
            raise ErrorDespacho(f'El despacho {despacho.numero} está {despacho.get_estado_display().lower()}.')
        disponible = _estado_onu('DISPONIBLE')
        for eq in despacho.equipos.all():
            m = Material.objects.select_for_update(of=('self',)).select_related('estado_onu').get(pk=eq.material_id)
            anterior = m.estado_onu.codigo if m.estado_onu_id else ''
            m.estado_onu, m.orden_trabajo = disponible, ''
            m.save(update_fields=['estado_onu', 'orden_trabajo', 'updated_at'])
            _historial(m, usuario, f'Despacho {despacho.numero} anulado', anterior, disponible.codigo, motivo)
        for linea in despacho.materiales.all():
            m = Material.objects.select_for_update(of=('self',)).get(pk=linea.material_id)
            m.cantidad += linea.cantidad
            m.save(update_fields=['cantidad', 'updated_at'])
            _historial(m, usuario, f'Despacho {despacho.numero} anulado: vuelven {_n(linea.cantidad)}', obs=motivo)
        despacho.estado = Despacho.Estado.ANULADO
        despacho.observaciones_rendicion = f'Anulado: {motivo}'
        despacho.rendido_por, despacho.rendido_at = usuario, timezone.now()
        despacho.save()
    return despacho
