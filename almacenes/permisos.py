# ======================================================
# almacenes/permisos.py
# Configuración común de permisos para las vistas de almacenes.
# La lógica está en usuarios/permissions.py (PermisoPorRol).
# ======================================================
from usuarios.permissions import PermisoPorRol  # noqa: F401  (se importa desde aquí en las vistas)

# Cualquiera que trabaje en almacenes (ver al menos una de estas pantallas) puede
# LEER los catálogos que se usan en los formularios: marcas, modelos, tipos, estados, etc.
LECTURA_ALMACENES = [
    ('almacenes', 'leer'),
    ('lotes', 'leer'),
    ('materiales', 'leer'),
    ('traspasos', 'leer'),
    ('laboratorio', 'leer'),
    ('proveedores', 'leer'),
    ('marcas', 'leer'),
    ('modelos', 'leer'),
]
