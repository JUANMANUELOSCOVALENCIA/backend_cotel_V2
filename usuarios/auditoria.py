# ======================================================
# usuarios/auditoria.py
# Auditoría automática para las vistas de la API.
#
# Cualquier vista que herede AuditoriaMixin registra en AuditLog cada operación
# de escritura que termina bien (POST, PUT, PATCH, DELETE con respuesta 2xx):
#   - create          → CREATE  (objeto creado)
#   - update / patch  → UPDATE  (con los campos que cambiaron: antes → después)
#   - destroy         → DELETE  (lo que se borró)
#   - otras acciones  → CUSTOM  ("Lote: Cerrar lote", "Envío a laboratorio"…)
#
# Las lecturas (GET) no se registran. Si algo falla al auditar, la operación
# principal NO se ve afectada.
#
# Atributos opcionales en la vista:
#   auditoria_modelo    = modelo a usar cuando la vista no tiene queryset (APIView)
#   auditoria_acciones  = {'cerrar_lote': 'Cerrar lote', 'POST': 'Envío a laboratorio'}
#   auditoria_excluir   = {'busqueda_avanzada'}   # POST que en realidad solo consultan
# ======================================================
import logging
from decimal import Decimal
from datetime import date, datetime

from django.contrib.contenttypes.models import ContentType
from django.db.models import Model
from django.forms.models import model_to_dict

from .models import AuditLog

logger = logging.getLogger(__name__)

METODOS_ESCRITURA = {'POST', 'PUT', 'PATCH', 'DELETE'}
CAMPOS_SENSIBLES = {'password', 'old_password', 'new_password', 'confirm_password', 'token', 'refresh', 'access'}
CAMPOS_IGNORADOS = {'updated_at', 'created_at', 'fecha_actualizacion', 'last_login'}


def _ip(request):
    xff = request.META.get('HTTP_X_FORWARDED_FOR')
    return (xff.split(',')[0].strip() if xff else request.META.get('REMOTE_ADDR')) or None


def _simple(valor, profundidad=0):
    """Convierte valores a algo guardable en JSON y corto."""
    if valor is None or isinstance(valor, (bool, int, float)):
        return valor
    if isinstance(valor, str):
        return valor[:200]
    if isinstance(valor, Decimal):
        return float(valor)
    if isinstance(valor, (date, datetime)):
        return valor.isoformat()
    if isinstance(valor, Model):
        return str(valor)[:100]
    if profundidad > 2:
        return str(valor)[:200]
    if isinstance(valor, dict):
        return {str(k): _simple(v, profundidad + 1) for k, v in list(valor.items())[:30]
                if str(k).lower() not in CAMPOS_SENSIBLES}
    if isinstance(valor, (list, tuple, set)):
        valor = list(valor)
        corto = [_simple(v, profundidad + 1) for v in valor[:20]]
        if len(valor) > 20:
            corto.append(f'… y {len(valor) - 20} más')
        return corto
    if hasattr(valor, 'name') and hasattr(valor, 'size'):  # archivo subido
        return f'archivo {valor.name}'
    return str(valor)[:200]


def _foto(obj):
    """Valores simples de los campos de un objeto (para comparar antes/después)."""
    if obj is None:
        return {}
    try:
        datos = model_to_dict(obj)
    except Exception:
        return {}
    return {k: _simple(v) for k, v in datos.items() if k not in CAMPOS_IGNORADOS and k.lower() not in CAMPOS_SENSIBLES}


def _humanizar(nombre):
    return nombre.replace('_', ' ').strip().capitalize()


class AuditoriaMixin:
    auditoria_modelo = None
    auditoria_acciones = {}
    auditoria_excluir = set()

    def auditoria_omitir(self, request):
        """Devuelve True para no registrar esta petición (p. ej. una validación previa)."""
        return False

    # ---------- ganchos de DRF ----------
    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        self._aud_obj = None
        self._aud_antes = {}
        if request.method not in METODOS_ESCRITURA:
            return
        lookup = getattr(self, 'lookup_url_kwarg', None) or getattr(self, 'lookup_field', 'pk')
        pk = kwargs.get(lookup) or kwargs.get('pk')
        modelo = self._aud_modelo()
        if pk is not None and modelo is not None:
            try:
                self._aud_obj = modelo._default_manager.filter(pk=pk).first()
                self._aud_antes = _foto(self._aud_obj)
            except Exception:
                self._aud_obj = None

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        try:
            if (request.method in METODOS_ESCRITURA and 200 <= response.status_code < 300
                    and getattr(request.user, 'is_authenticated', False)):
                self._aud_registrar(request, response)
        except Exception:  # la auditoría nunca rompe la operación
            logger.exception('No se pudo registrar la auditoría')
        return response

    # ---------- detalles ----------
    def _aud_modelo(self):
        if self.auditoria_modelo is not None:
            return self.auditoria_modelo
        qs = getattr(self, 'queryset', None)
        if qs is not None:
            return qs.model
        sc = getattr(self, 'serializer_class', None)
        meta = getattr(sc, 'Meta', None)
        return getattr(meta, 'model', None)

    def _aud_registrar(self, request, response):
        accion_vista = getattr(self, 'action', None)
        if accion_vista in self.auditoria_excluir or self.auditoria_omitir(request):
            return
        modelo = self._aud_modelo()
        if modelo is None:
            return
        data = response.data if isinstance(getattr(response, 'data', None), dict) else {}
        obj = self._aud_obj
        detalles = {}

        if accion_vista == 'create':
            accion, personalizada = AuditLog.AccionChoices.CREATE, ''
            nuevo_id = data.get('id')
            if nuevo_id is not None:
                obj = modelo._default_manager.filter(pk=nuevo_id).first()
            detalles['datos'] = _simple({k: v for k, v in request.data.items()}) if hasattr(request.data, 'items') else {}
        elif accion_vista in ('update', 'partial_update'):
            accion, personalizada = AuditLog.AccionChoices.UPDATE, ''
            if obj is not None:
                obj = modelo._default_manager.filter(pk=obj.pk).first() or obj
                despues = _foto(obj)
                cambios = {k: {'antes': self._aud_antes.get(k), 'despues': v}
                           for k, v in despues.items() if self._aud_antes.get(k) != v}
                if not cambios:
                    return  # se guardó sin cambiar nada: no hace falta registrarlo
                detalles['cambios'] = cambios
        elif accion_vista == 'destroy' or (accion_vista is None and request.method == 'DELETE' and obj is not None):
            accion, personalizada = AuditLog.AccionChoices.DELETE, ''
            detalles['eliminado'] = self._aud_antes
        else:
            accion = AuditLog.AccionChoices.CUSTOM
            clave = accion_vista or request.method
            etiqueta = self.auditoria_acciones.get(clave) or (_humanizar(accion_vista) if accion_vista else _humanizar(self.__class__.__name__.replace('View', '')))
            personalizada = f'{modelo._meta.verbose_name.capitalize()}: {etiqueta}' if accion_vista else etiqueta
            if hasattr(request.data, 'items'):
                detalles['datos'] = _simple({k: v for k, v in request.data.items()})
            if data.get('message'):
                detalles['resultado'] = _simple(data['message'])

        # Equipos involucrados por id → sus series, para que el registro se lea sin buscar ids
        equipos = self._aud_equipos(request) if obj is None else []
        if equipos:
            detalles['equipos'] = equipos
        if obj is not None:
            representacion = str(obj)[:200]
        elif equipos:
            representacion = (', '.join(equipos[:3]) + (f' y {len(equipos) - 3} más' if len(equipos) > 3 else ''))[:200]
        else:
            representacion = (personalizada or modelo._meta.verbose_name)[:200]
        AuditLog.objects.create(
            usuario=request.user,
            accion=accion,
            accion_personalizada=personalizada[:100],
            content_type=ContentType.objects.get_for_model(modelo),
            object_id=str(obj.pk) if obj is not None and obj.pk is not None else (str(self._aud_obj.pk) if self._aud_obj else '-'),
            objeto_representacion=representacion,
            app_label=modelo._meta.app_label,
            model_name=modelo._meta.model_name,
            detalles=detalles,
            ip_address=_ip(request),
            user_agent=(request.META.get('HTTP_USER_AGENT') or '')[:500] or None,
        )

    @staticmethod
    def _aud_equipos(request):
        """GPON (o código) de los equipos indicados por id en la petición, máx. 50."""
        if not hasattr(request.data, 'get'):
            return []
        ids = []
        for clave in ('materiales_ids', 'materiales_originales_ids'):
            valor = request.data.get(clave)
            if isinstance(valor, (list, tuple)):
                ids += list(valor)
        for clave in ('material_id', 'material'):
            if request.data.get(clave) not in (None, ''):
                ids.append(request.data.get(clave))
        try:
            ids = [int(i) for i in ids][:50]
        except (TypeError, ValueError):
            return []
        if not ids:
            return []
        from django.apps import apps
        Material = apps.get_model('almacenes', 'Material')
        filas = Material.objects.filter(id__in=ids).values_list('gpon_serial', 'codigo_interno')
        return [g or c for g, c in filas]
