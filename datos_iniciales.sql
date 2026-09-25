-- =====================================================================
-- DATOS INICIALES - backend_cotel_V2
-- Se puede ejecutar varias veces: no duplica nada (ON CONFLICT).
-- Ejecutar como SCRIPT COMPLETO (DBeaver: Alt+X / pgAdmin: F5)
-- =====================================================================


-- =====================================================================
-- 1. CATÁLOGOS DE ALMACENES
--    Los CÓDIGOS están usados directamente en el backend: NO cambiarlos.
--    Nombres, descripciones y colores sí se pueden editar.
-- =====================================================================

-- 1.1 Unidades de medida
INSERT INTO almacenes_unidad_medida (codigo, nombre, simbolo, descripcion, activo, orden, created_at, updated_at) VALUES
('PIEZA',  'Pieza',  'pza', 'Unidad individual', TRUE, 1, NOW(), NOW()),
('METRO',  'Metro',  'm',   'Longitud en metros', TRUE, 2, NOW(), NOW()),
('ROLLO',  'Rollo',  'rll', 'Rollo de cable',     TRUE, 3, NOW(), NOW()),
('CAJA',   'Caja',   'cja', 'Caja',               TRUE, 4, NOW(), NOW()),
('PAQUETE','Paquete','paq', 'Paquete',            TRUE, 5, NOW(), NOW())
ON CONFLICT (codigo) DO NOTHING;

-- 1.2 Tipos de material  (ONU es obligatorio)
INSERT INTO almacenes_tipo_material (codigo, nombre, descripcion, unidad_medida_default_id, requiere_inspeccion_inicial, es_unico, activo, orden, created_at, updated_at)
SELECT v.codigo, v.nombre, v.descripcion, u.id, v.insp, v.unico, TRUE, v.orden, NOW(), NOW()
FROM (VALUES
    ('ONU',       'Equipo ONU',        'Equipo terminal óptico (único, con MAC/serie)', 'PIEZA', TRUE,  TRUE,  1),
    ('CABLE',     'Cable',             'Cable de fibra / drop',                         'METRO', FALSE, FALSE, 2),
    ('CONECTOR',  'Conector',          'Conectores y accesorios',                       'PIEZA', FALSE, FALSE, 3),
    ('ACCESORIO', 'Accesorio',         'Accesorios varios de instalación',              'PIEZA', FALSE, FALSE, 4)
) AS v(codigo, nombre, descripcion, unidad, insp, unico, orden)
JOIN almacenes_unidad_medida u ON u.codigo = v.unidad
ON CONFLICT (codigo) DO NOTHING;

-- 1.3 Tipos de ingreso
INSERT INTO almacenes_tipo_ingreso (codigo, nombre, descripcion, activo, orden, created_at, updated_at) VALUES
('NUEVO',     'Ingreso nuevo', 'Material nuevo recibido de proveedor',   TRUE, 1, NOW(), NOW()),
('REINGRESO', 'Reingreso',     'Material que vuelve a ingresar',         TRUE, 2, NOW(), NOW()),
('DEVOLUCION','Devolución',    'Material devuelto desde campo/sector',   TRUE, 3, NOW(), NOW())
ON CONFLICT (codigo) DO NOTHING;

-- 1.4 Estados de lote
INSERT INTO almacenes_estado_lote (codigo, nombre, descripcion, color, es_final, activo, orden, created_at, updated_at) VALUES
('REGISTRADO',         'Registrado',         'Lote registrado, sin recepción',  '#6B7280', FALSE, TRUE, 1, NOW(), NOW()),
('ACTIVO',             'Activo',             'Lote activo',                     '#3B82F6', FALSE, TRUE, 2, NOW(), NOW()),
('RECEPCION_PARCIAL',  'Recepción parcial',  'Se recibió parte del lote',       '#F59E0B', FALSE, TRUE, 3, NOW(), NOW()),
('RECEPCION_COMPLETA', 'Recepción completa', 'Se recibió todo el lote',         '#10B981', FALSE, TRUE, 4, NOW(), NOW()),
('CERRADO',            'Cerrado',            'Lote cerrado',                    '#374151', TRUE,  TRUE, 5, NOW(), NOW())
ON CONFLICT (codigo) DO NOTHING;

-- 1.5 Estados de traspaso
INSERT INTO almacenes_estado_traspaso (codigo, nombre, descripcion, color, es_final, activo, orden, created_at, updated_at) VALUES
('PENDIENTE',   'Pendiente',   'Traspaso creado, sin enviar', '#6B7280', FALSE, TRUE, 1, NOW(), NOW()),
('EN_TRANSITO', 'En tránsito', 'Material enviado',            '#F59E0B', FALSE, TRUE, 2, NOW(), NOW()),
('RECIBIDO',    'Recibido',    'Material recibido en destino','#10B981', TRUE,  TRUE, 3, NOW(), NOW()),
('CANCELADO',   'Cancelado',   'Traspaso cancelado',          '#EF4444', TRUE,  TRUE, 4, NOW(), NOW())
ON CONFLICT (codigo) DO NOTHING;

-- 1.6 Estados de material ONU
INSERT INTO almacenes_estado_material_onu (codigo, nombre, descripcion, color, permite_asignacion, permite_traspaso, activo, orden, created_at, updated_at) VALUES
('NUEVO',                       'Nuevo',                    'Recién ingresado, pendiente de inspección', '#3B82F6', FALSE, TRUE,  TRUE, 1, NOW(), NOW()),
('EN_LABORATORIO',              'En laboratorio',           'En inspección de laboratorio',              '#8B5CF6', FALSE, FALSE, TRUE, 2, NOW(), NOW()),
('DISPONIBLE',                  'Disponible',               'Aprobado y listo para asignar',             '#10B981', TRUE,  TRUE,  TRUE, 3, NOW(), NOW()),
('RESERVADO',                   'Reservado',                'Reservado para un servicio',                '#F59E0B', FALSE, FALSE, TRUE, 4, NOW(), NOW()),
('DEFECTUOSO',                  'Defectuoso',               'Falló la inspección',                       '#EF4444', FALSE, FALSE, TRUE, 5, NOW(), NOW()),
('DEVUELTO_SECTOR_SOLICITANTE', 'Devuelto a sector',        'Devuelto al sector solicitante',            '#F97316', FALSE, FALSE, TRUE, 6, NOW(), NOW()),
('DEVUELTO_PROVEEDOR',          'Devuelto a proveedor',     'Devuelto al proveedor',                     '#DC2626', FALSE, FALSE, TRUE, 7, NOW(), NOW()),
('REINGRESADO',                 'Reingresado',              'Equipo reingresado',                        '#06B6D4', FALSE, TRUE,  TRUE, 8, NOW(), NOW()),
('REEMPLAZADO',                 'Reemplazado',              'Equipo reemplazado por otro',               '#6B7280', FALSE, FALSE, TRUE, 9, NOW(), NOW())
ON CONFLICT (codigo) DO NOTHING;

-- 1.7 Estados de material general
INSERT INTO almacenes_estado_material_general (codigo, nombre, descripcion, color, permite_consumo, permite_traspaso, activo, orden, created_at, updated_at) VALUES
('DISPONIBLE', 'Disponible', 'Listo para usar',          '#10B981', TRUE,  TRUE,  TRUE, 1, NOW(), NOW()),
('RESERVADO',  'Reservado',  'Reservado para un trabajo', '#F59E0B', FALSE, FALSE, TRUE, 2, NOW(), NOW()),
('DEFECTUOSO', 'Defectuoso', 'Material dañado',          '#EF4444', FALSE, FALSE, TRUE, 3, NOW(), NOW()),
('CONSUMIDO',  'Consumido',  'Material ya utilizado',    '#6B7280', FALSE, FALSE, TRUE, 4, NOW(), NOW())
ON CONFLICT (codigo) DO NOTHING;

-- 1.8 Tipos de almacén
INSERT INTO almacenes_tipo_almacen (codigo, nombre, descripcion, activo, orden, created_at, updated_at) VALUES
('CENTRAL',  'Central',  'Almacén central / principal', TRUE, 1, NOW(), NOW()),
('REGIONAL', 'Regional', 'Almacén regional',            TRUE, 2, NOW(), NOW()),
('TEMPORAL', 'Temporal', 'Almacén temporal o de obra',  TRUE, 3, NOW(), NOW())
ON CONFLICT (codigo) DO NOTHING;


-- =====================================================================
-- 2. CATÁLOGOS DE CONTRATOS  (ejemplos: editar a gusto)
--    Tipo de servicio es OBLIGATORIO para crear lotes.
-- =====================================================================

INSERT INTO contratos_tipo_servicio (nombre, descripcion, created_at, updated_at) VALUES
('Internet',   'Servicio de internet por fibra', NOW(), NOW()),
('Televisión', 'Servicio de TV',                 NOW(), NOW()),
('Telefonía',  'Servicio de telefonía',          NOW(), NOW())
ON CONFLICT (nombre) DO NOTHING;

INSERT INTO contratos_tipo_tramite (nombre, descripcion, activo, created_at, updated_at) VALUES
('Nueva instalación', 'Alta de servicio nuevo', TRUE, NOW(), NOW()),
('Traslado',          'Cambio de domicilio',    TRUE, NOW(), NOW()),
('Cambio de plan',    'Cambio de plan',         TRUE, NOW(), NOW()),
('Baja',              'Baja del servicio',      TRUE, NOW(), NOW())
ON CONFLICT (nombre) DO NOTHING;

INSERT INTO contratos_forma_pago (nombre, descripcion, activo, created_at, updated_at) VALUES
('Efectivo',      'Pago en efectivo',      TRUE, NOW(), NOW()),
('Transferencia', 'Transferencia bancaria',TRUE, NOW(), NOW()),
('QR',            'Pago por QR',           TRUE, NOW(), NOW())
ON CONFLICT (nombre) DO NOTHING;


-- =====================================================================
-- 3. ROLES ADICIONALES
-- =====================================================================

INSERT INTO usuarios_roles (nombre, descripcion, activo, es_sistema, eliminado, fecha_creacion, fecha_modificacion) VALUES
('Almacén',      'Gestión de almacenes, lotes, materiales y traspasos', TRUE, FALSE, FALSE, NOW(), NOW()),
('Laboratorio',  'Inspección de equipos en laboratorio',                 TRUE, FALSE, FALSE, NOW(), NOW()),
('Solo Lectura', 'Puede ver todo, no puede modificar nada',              TRUE, FALSE, FALSE, NOW(), NOW())
ON CONFLICT (nombre) DO NOTHING;

-- 3.1 Almacén: CRUD en módulos de almacén + leer catálogos
INSERT INTO usuarios_roles_permisos (roles_id, permission_id)
SELECT r.id, p.id
FROM usuarios_roles r
JOIN usuarios_permission p ON (
      p.recurso IN ('almacenes','proveedores','lotes','lote-detalles','materiales','traspasos',
                    'marcas','modelos','componentes','modelo-componentes','sectores-solicitantes')
   OR (p.recurso IN ('tipos-ingreso','estados-lote','estados-traspaso','tipos-material','unidades-medida',
                     'estados-material-onu','estados-material-general','tipos-almacen','laboratorio')
       AND p.accion = 'leer')
)
WHERE r.nombre = 'Almacén'
ON CONFLICT DO NOTHING;

-- 3.2 Laboratorio: CRUD laboratorio, leer/actualizar materiales, leer lo demás de almacén
INSERT INTO usuarios_roles_permisos (roles_id, permission_id)
SELECT r.id, p.id
FROM usuarios_roles r
JOIN usuarios_permission p ON (
      p.recurso = 'laboratorio'
   OR (p.recurso = 'materiales' AND p.accion IN ('leer','actualizar'))
   OR (p.recurso IN ('almacenes','lotes','lote-detalles','marcas','modelos','componentes',
                     'estados-material-onu','estados-material-general','tipos-material')
       AND p.accion = 'leer')
)
WHERE r.nombre = 'Laboratorio'
ON CONFLICT DO NOTHING;

-- 3.3 Solo Lectura: leer todo excepto administración de usuarios
INSERT INTO usuarios_roles_permisos (roles_id, permission_id)
SELECT r.id, p.id
FROM usuarios_roles r
JOIN usuarios_permission p ON p.accion = 'leer'
   AND p.recurso NOT IN ('usuarios','roles','permisos','logs','empleados-disponibles')
WHERE r.nombre = 'Solo Lectura'
ON CONFLICT DO NOTHING;


-- =====================================================================
-- 4. VERIFICACIÓN
-- =====================================================================
SELECT 'unidades_medida' AS tabla, COUNT(*) FROM almacenes_unidad_medida
UNION ALL SELECT 'tipos_material',          COUNT(*) FROM almacenes_tipo_material
UNION ALL SELECT 'tipos_ingreso',           COUNT(*) FROM almacenes_tipo_ingreso
UNION ALL SELECT 'estados_lote',            COUNT(*) FROM almacenes_estado_lote
UNION ALL SELECT 'estados_traspaso',        COUNT(*) FROM almacenes_estado_traspaso
UNION ALL SELECT 'estados_material_onu',    COUNT(*) FROM almacenes_estado_material_onu
UNION ALL SELECT 'estados_material_general',COUNT(*) FROM almacenes_estado_material_general
UNION ALL SELECT 'tipos_almacen',           COUNT(*) FROM almacenes_tipo_almacen
UNION ALL SELECT 'tipos_servicio',          COUNT(*) FROM contratos_tipo_servicio
UNION ALL SELECT 'tipos_tramite',           COUNT(*) FROM contratos_tipo_tramite
UNION ALL SELECT 'formas_pago',             COUNT(*) FROM contratos_forma_pago
UNION ALL SELECT 'rol: ' || r.nombre,       COUNT(rp.id)
          FROM usuarios_roles r LEFT JOIN usuarios_roles_permisos rp ON rp.roles_id = r.id
          GROUP BY r.nombre;
