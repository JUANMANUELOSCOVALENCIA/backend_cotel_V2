# ======================================================
# operaciones/geo.py
# Utilidades geográficas sin dependencias externas.
# Las zonas se guardan como geometría GeoJSON (Polygon o MultiPolygon);
# en GeoJSON cada coordenada es [longitud, latitud].
# ======================================================
import math

TIPOS_VALIDOS = ('Polygon', 'MultiPolygon')


def _en_anillo(lng, lat, anillo):
    """Ray casting: ¿el punto está dentro del anillo (lista de [lng, lat])?"""
    dentro = False
    n = len(anillo)
    j = n - 1
    for i in range(n):
        xi, yi = anillo[i][0], anillo[i][1]
        xj, yj = anillo[j][0], anillo[j][1]
        if (yi > lat) != (yj > lat):
            x_corte = (xj - xi) * (lat - yi) / (yj - yi) + xi
            if lng < x_corte:
                dentro = not dentro
        j = i
    return dentro


def _en_poligono(lng, lat, poligono):
    """poligono = [anillo_exterior, hueco1, hueco2…]"""
    if not poligono or not _en_anillo(lng, lat, poligono[0]):
        return False
    return not any(_en_anillo(lng, lat, hueco) for hueco in poligono[1:])


def contiene(geometria, lat, lng):
    if not geometria:
        return False
    tipo = geometria.get('type')
    coords = geometria.get('coordinates') or []
    if tipo == 'Polygon':
        return _en_poligono(lng, lat, coords)
    if tipo == 'MultiPolygon':
        return any(_en_poligono(lng, lat, p) for p in coords)
    return False


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def validar_geometria(valor):
    """
    Acepta una geometría, un Feature o una FeatureCollection de un solo polígono.
    Devuelve (geometria_normalizada, error). Cierra los anillos abiertos.
    """
    if not isinstance(valor, dict):
        return None, 'La zona debe ser un polígono GeoJSON.'
    if valor.get('type') == 'FeatureCollection':
        feats = valor.get('features') or []
        if len(feats) != 1:
            return None, 'El archivo tiene varias zonas; impórtalas una por una.'
        valor = feats[0]
    if valor.get('type') == 'Feature':
        valor = valor.get('geometry') or {}
    tipo = valor.get('type')
    if tipo not in TIPOS_VALIDOS:
        return None, 'La zona debe ser un polígono (Polygon o MultiPolygon).'

    poligonos = [valor.get('coordinates')] if tipo == 'Polygon' else (valor.get('coordinates') or [])
    if not poligonos:
        return None, 'El polígono no tiene puntos.'
    limpios = []
    for poligono in poligonos:
        if not isinstance(poligono, list) or not poligono:
            return None, 'El polígono no tiene puntos.'
        anillos = []
        for anillo in poligono:
            if not isinstance(anillo, list):
                return None, 'Coordenadas no válidas.'
            pts = []
            for p in anillo:
                if not (isinstance(p, (list, tuple)) and len(p) >= 2 and _num(p[0]) and _num(p[1])):
                    return None, 'Coordenadas no válidas.'
                lng, lat = float(p[0]), float(p[1])
                if not (-180 <= lng <= 180 and -90 <= lat <= 90):
                    return None, 'Hay coordenadas fuera de rango (¿latitud y longitud invertidas?).'
                pts.append([round(lng, 7), round(lat, 7)])
            if pts and pts[0] != pts[-1]:
                pts.append(pts[0])
            if len(pts) < 4:
                return None, 'Cada polígono necesita al menos 3 puntos.'
            anillos.append(pts)
        limpios.append(anillos)
    geom = {'type': 'Polygon', 'coordinates': limpios[0]} if tipo == 'Polygon' else {'type': 'MultiPolygon', 'coordinates': limpios}
    return geom, None


def area_km2(geometria):
    """Área aproximada (proyección equirectangular local), suficiente para mostrar."""
    if not geometria:
        return 0
    poligonos = [geometria['coordinates']] if geometria['type'] == 'Polygon' else geometria['coordinates']
    total = 0.0
    for poligono in poligonos:
        for k, anillo in enumerate(poligono):
            lat0 = math.radians(sum(p[1] for p in anillo) / len(anillo))
            kx = 111.32 * math.cos(lat0)
            ky = 110.57
            s = 0.0
            for i in range(len(anillo) - 1):
                x1, y1 = anillo[i][0] * kx, anillo[i][1] * ky
                x2, y2 = anillo[i + 1][0] * kx, anillo[i + 1][1] * ky
                s += x1 * y2 - x2 * y1
            total += abs(s) / 2 * (1 if k == 0 else -1)
    return round(max(total, 0), 2)


def distancia_m(lat1, lng1, lat2, lng2):
    """Distancia en metros entre dos puntos (fórmula de Haversine, radio terrestre 6 371 km)."""
    from math import asin, cos, radians, sin, sqrt
    p1, p2 = radians(float(lat1)), radians(float(lat2))
    dp, dl = p2 - p1, radians(float(lng2) - float(lng1))
    a = sin(dp / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2
    return 2 * 6371000 * asin(sqrt(a))
