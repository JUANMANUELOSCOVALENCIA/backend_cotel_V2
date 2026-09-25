-- =====================================================================
-- DATOS DE EJEMPLO: almacenes, proveedores, marcas, modelos, componentes
-- Requiere haber ejecutado antes: datos_iniciales.sql
-- Son datos DE EJEMPLO: cambia nombres, teléfonos, códigos, etc. por los reales.
-- Se puede ejecutar varias veces sin duplicar (ON CONFLICT).
-- Ejecutar como SCRIPT COMPLETO (DBeaver: Alt+X / pgAdmin: F5)
-- =====================================================================


-- 1. ALMACENES  (solo UNO puede ser principal)
INSERT INTO almacenes_almacen (codigo, nombre, ciudad, tipo_id, direccion, es_principal, activo, observaciones, created_at, updated_at)
SELECT v.codigo, v.nombre, v.ciudad, t.id, v.direccion, v.principal, TRUE, '', NOW(), NOW()
FROM (VALUES
    ('ALM-001', 'Almacén Central',  'La Paz',  'CENTRAL',  'Dirección del almacén central', TRUE),
    ('ALM-002', 'Almacén El Alto',  'El Alto', 'REGIONAL', 'Dirección del almacén El Alto', FALSE),
    ('ALM-003', 'Almacén Sur',      'La Paz',  'REGIONAL', 'Dirección del almacén Sur',     FALSE)
) AS v(codigo, nombre, ciudad, tipo, direccion, principal)
JOIN almacenes_tipo_almacen t ON t.codigo = v.tipo
ON CONFLICT (codigo) DO NOTHING;


-- 2. PROVEEDORES
INSERT INTO almacenes_proveedor (codigo, nombre_comercial, razon_social, contacto_principal, telefono, email, activo, created_at, updated_at) VALUES
('PROV-001', 'Huawei',          'Huawei Technologies',      'Contacto Huawei',   '00000000', 'contacto@proveedor1.com', TRUE, NOW(), NOW()),
('PROV-002', 'ZTE',             'ZTE Corporation',          'Contacto ZTE',      '00000000', 'contacto@proveedor2.com', TRUE, NOW(), NOW()),
('PROV-003', 'Distribuidora 1', 'Distribuidora Ejemplo SRL','Contacto Distrib.', '00000000', 'contacto@proveedor3.com', TRUE, NOW(), NOW())
ON CONFLICT (nombre_comercial) DO NOTHING;


-- 3. MARCAS
INSERT INTO almacenes_marca (nombre, descripcion, activo, created_at, updated_at) VALUES
('Huawei',    'Equipos ONU Huawei',    TRUE, NOW(), NOW()),
('ZTE',       'Equipos ONU ZTE',       TRUE, NOW(), NOW()),
('Nokia',     'Equipos ONU Nokia',     TRUE, NOW(), NOW()),
('FiberHome', 'Equipos ONU FiberHome', TRUE, NOW(), NOW()),
('Genérico',  'Materiales sin marca específica', TRUE, NOW(), NOW())
ON CONFLICT (nombre) DO NOTHING;


-- 4. COMPONENTES (lo que viene en la caja de cada equipo)
INSERT INTO almacenes_componente (nombre, descripcion, activo, created_at, updated_at) VALUES
('Fuente de poder', 'Adaptador de corriente', TRUE, NOW(), NOW()),
('Cable de red',    'Cable Ethernet RJ45',    TRUE, NOW(), NOW()),
('Patch cord',      'Patch cord de fibra',    TRUE, NOW(), NOW()),
('Manual',          'Manual de usuario',      TRUE, NOW(), NOW())
ON CONFLICT (nombre) DO NOTHING;


-- 5. MODELOS
--    codigo_modelo debe ser ÚNICO (número entero).
INSERT INTO almacenes_modelo (marca_id, nombre, codigo_modelo, descripcion, activo, tipo_material_id, unidad_medida_id, cantidad_por_unidad, requiere_inspeccion_inicial, created_at, updated_at)
SELECT m.id, v.nombre, v.codigo, v.descripcion, TRUE, tm.id, um.id, v.cant, v.insp, NOW(), NOW()
FROM (VALUES
    -- marca,      modelo,            código, descripción,                     tipo,        unidad,  cant/unidad, inspección
    ('Huawei',    'EG8145V5',          1001, 'ONU GPON WiFi doble banda',      'ONU',       'PIEZA',   1.00, TRUE),
    ('Huawei',    'HG8145X6',          1002, 'ONU GPON WiFi 6',                'ONU',       'PIEZA',   1.00, TRUE),
    ('ZTE',       'F670L',             2001, 'ONU GPON WiFi doble banda',      'ONU',       'PIEZA',   1.00, TRUE),
    ('ZTE',       'F680',              2002, 'ONU GPON WiFi doble banda',      'ONU',       'PIEZA',   1.00, TRUE),
    ('Nokia',     'G-140W-C',          3001, 'ONU GPON WiFi',                  'ONU',       'PIEZA',   1.00, TRUE),
    ('FiberHome', 'HG6145F',           4001, 'ONU GPON WiFi doble banda',      'ONU',       'PIEZA',   1.00, TRUE),
    ('Genérico',  'Cable drop 1 hilo', 9001, 'Cable drop de fibra, rollo 1km', 'CABLE',     'ROLLO', 1000.00, FALSE),
    ('Genérico',  'Conector SC/APC',   9002, 'Conector rápido SC/APC',         'CONECTOR',  'CAJA',   100.00, FALSE)
) AS v(marca, nombre, codigo, descripcion, tipo, unidad, cant, insp)
JOIN almacenes_marca m          ON m.nombre  = v.marca
JOIN almacenes_tipo_material tm ON tm.codigo = v.tipo
JOIN almacenes_unidad_medida um ON um.codigo = v.unidad
ON CONFLICT (codigo_modelo) DO NOTHING;


-- 6. COMPONENTES DE CADA ONU (fuente + cable de red en todos los modelos ONU)
INSERT INTO almacenes_modelo_componente (modelo_id, componente_id, cantidad)
SELECT mo.id, c.id, 1
FROM almacenes_modelo mo
JOIN almacenes_tipo_material tm ON tm.id = mo.tipo_material_id AND tm.codigo = 'ONU'
JOIN almacenes_componente c ON c.nombre IN ('Fuente de poder', 'Cable de red')
ON CONFLICT (modelo_id, componente_id) DO NOTHING;


-- 7. SECTORES SOLICITANTES
INSERT INTO almacenes_sector_solicitante (nombre, activo, orden, created_at, updated_at) VALUES
('Instalaciones',        TRUE, 1, NOW(), NOW()),
('Mantenimiento',        TRUE, 2, NOW(), NOW()),
('Atención al cliente',  TRUE, 3, NOW(), NOW())
ON CONFLICT (nombre) DO NOTHING;


-- 8. VERIFICACIÓN
SELECT 'almacenes'  AS tabla, COUNT(*) FROM almacenes_almacen
UNION ALL SELECT 'proveedores',          COUNT(*) FROM almacenes_proveedor
UNION ALL SELECT 'marcas',               COUNT(*) FROM almacenes_marca
UNION ALL SELECT 'componentes',          COUNT(*) FROM almacenes_componente
UNION ALL SELECT 'modelos',              COUNT(*) FROM almacenes_modelo
UNION ALL SELECT 'modelo_componentes',   COUNT(*) FROM almacenes_modelo_componente
UNION ALL SELECT 'sectores_solicitantes',COUNT(*) FROM almacenes_sector_solicitante;
