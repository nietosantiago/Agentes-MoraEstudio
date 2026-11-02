-- Esquema portable SQLite / PostgreSQL (Supabase). Fechas ISO en TEXT, montos en ARS.
CREATE TABLE IF NOT EXISTS clientes (
  id TEXT PRIMARY KEY, nombre TEXT NOT NULL, email TEXT, telefono TEXT, ciudad TEXT,
  canal_preferido TEXT, cuit TEXT, condicion_iva TEXT DEFAULT 'consumidor_final');

CREATE TABLE IF NOT EXISTS leads (
  id TEXT PRIMARY KEY, nombre TEXT NOT NULL, canal TEXT, contacto TEXT, ciudad TEXT,
  tipo_proyecto TEXT, presupuesto_estimado DOUBLE PRECISION, mensaje TEXT,
  estado TEXT NOT NULL,            -- nuevo | contactado | calificado | presupuestado | ganado | perdido
  calificacion TEXT, creado TEXT, ultimo_contacto TEXT);

CREATE TABLE IF NOT EXISTS servicios (       -- lista de precios: tabla exacta, no vector store
  codigo TEXT PRIMARY KEY, nombre TEXT NOT NULL, unidad TEXT NOT NULL,  -- fijo | ambiente | m2 | unidad | mes
  precio DOUBLE PRECISION NOT NULL, minimo DOUBLE PRECISION DEFAULT 0, descripcion TEXT, vigencia TEXT);

CREATE TABLE IF NOT EXISTS presupuestos (
  id TEXT PRIMARY KEY, cliente_id TEXT, lead_id TEXT, fecha TEXT, items TEXT, total DOUBLE PRECISION,
  estado TEXT,                     -- borrador | enviado | aprobado | rechazado | vencido
  validez_dias INTEGER);

CREATE TABLE IF NOT EXISTS facturas (
  numero TEXT PRIMARY KEY, cliente_id TEXT, fecha TEXT, concepto TEXT, monto DOUBLE PRECISION,
  tipo TEXT, cae TEXT, proveedor TEXT, presupuesto_id TEXT);

CREATE TABLE IF NOT EXISTS cobros (
  id TEXT PRIMARY KEY, cliente_id TEXT, presupuesto_id TEXT, concepto TEXT, monto DOUBLE PRECISION,
  vencimiento TEXT, estado TEXT,   -- pendiente | cobrado
  factura_numero TEXT, cobrado_en TEXT, ultimo_recordatorio TEXT);

CREATE TABLE IF NOT EXISTS obras (
  id TEXT PRIMARY KEY, cliente_id TEXT, nombre TEXT, direccion TEXT,
  etapa TEXT,                      -- relevamiento | diseno | documentacion | ejecucion | finalizada
  inicio TEXT, entrega_prevista TEXT, publicable INTEGER DEFAULT 0, notas TEXT);

CREATE TABLE IF NOT EXISTS hitos (
  id TEXT PRIMARY KEY, obra_id TEXT, nombre TEXT, tipo TEXT,  -- hito | entregable
  fecha TEXT, estado TEXT,         -- pendiente | en_curso | cumplido | atrasado
  responsable TEXT, notas TEXT);

CREATE TABLE IF NOT EXISTS eventos (
  id TEXT PRIMARY KEY, fecha TEXT, hora TEXT, titulo TEXT, obra_id TEXT, invitado TEXT, origen TEXT);

CREATE TABLE IF NOT EXISTS posts (
  id TEXT PRIMARY KEY, fecha TEXT, red TEXT, formato TEXT, pilar TEXT, texto TEXT, hashtags TEXT,
  brief_visual TEXT, obra_id TEXT, estado TEXT);  -- borrador | programado | publicado

CREATE TABLE IF NOT EXISTS mensajes_salientes (  -- outbox: lo que efectivamente "sale" del estudio
  id TEXT PRIMARY KEY, destinatario TEXT, canal TEXT, asunto TEXT, cuerpo TEXT, motivo TEXT, enviado_en TEXT);

CREATE TABLE IF NOT EXISTS efectos (           -- ledger de idempotencia del ejecutor
  idempotency_key TEXT PRIMARY KEY, thread_id TEXT, tool TEXT, estado TEXT, resultado TEXT, creado TEXT);

CREATE TABLE IF NOT EXISTS conversaciones (
  thread_id TEXT PRIMARY KEY, cliente_id TEXT, titulo TEXT, creada TEXT, actualizada TEXT, estado TEXT);
