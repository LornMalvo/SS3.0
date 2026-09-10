-- StockScanner — migración 001: esquema inicial completo.
-- Ejecutar en el editor SQL de Supabase. Idempotente (IF NOT EXISTS).

create table if not exists favoritos (
  ticker      text primary key,
  creado_en   timestamptz not null default now()
);

create table if not exists anotaciones (
  ticker         text primary key,
  texto          text not null default '',
  actualizado_en timestamptz not null default now()
);

-- Histórico de análisis: una fila por (ticker, día, versión de motor).
-- `entradas` guarda el JSON de datos crudos con los que se calculó cada
-- nota, lo que hace el resultado reconstruible para backtesting.
create table if not exists analisis_historico (
  id              bigserial primary key,
  ticker          text not null,
  fecha_analisis  date not null,
  motor_version   text not null,
  precio          numeric,
  divisa          text,
  calidad         numeric,
  fair_value      numeric,
  upside_pct      numeric,
  timing          numeric,
  senal_timing    text,
  veredicto       text,
  perfil          text,
  cobertura       jsonb,
  entradas        jsonb,
  plan            jsonb,
  creado_en       timestamptz not null default now(),
  unique (ticker, fecha_analisis, motor_version)
);
create index if not exists idx_analisis_ticker_fecha on analisis_historico (ticker, fecha_analisis desc);

-- Libro de operaciones. Todo lo numérico de una posición (coste medio, FIFO,
-- realizado) se DERIVA de aquí; no se guarda estado redundante.
create table if not exists cartera_operaciones (
  id            bigserial primary key,
  ticker        text not null,
  tipo          text not null check (tipo in ('compra', 'venta')),
  fecha         date not null,
  acciones      numeric not null check (acciones > 0),
  precio_eur    numeric not null check (precio_eur >= 0),
  comision_eur  numeric not null default 0 check (comision_eur >= 0),
  origen        text not null default 'real' check (origen in ('real', 'paper')),
  plan_id       bigint,
  nota          text,
  creado_en     timestamptz not null default now()
);
create index if not exists idx_operaciones_ticker on cartera_operaciones (origen, ticker, fecha);

-- Paper Trading: el plan guardado desde Análisis Individual.
create table if not exists paper_planes (
  id             bigserial primary key,
  ticker         text not null,
  estado         text not null default 'vigilancia'
                 check (estado in ('vigilancia','parcial_entrada','abierta','parcial_salida','cerrada','descartada')),
  motor_version  text not null,
  precio_ref     numeric,
  divisa         text,
  entradas       jsonb not null,   -- [{nivel, precio, peso, motivos}]
  salidas        jsonb not null,
  stop           numeric,
  veredicto      text,
  narrativa      text,
  invalidacion   jsonb,            -- condiciones de invalidación de tesis
  creado_en      timestamptz not null default now(),
  actualizado_en timestamptz not null default now()
);

create table if not exists paper_ejecuciones (
  id            bigserial primary key,
  plan_id       bigint not null references paper_planes(id) on delete cascade,
  nivel         text not null,     -- 'E1','E2','E3','S1','S2','S3','STOP'
  fecha         date not null,
  precio        numeric not null,
  acciones      numeric not null,
  operacion_id  bigint references cartera_operaciones(id) on delete set null,
  creado_en     timestamptz not null default now()
);

create table if not exists tesis_invalidacion (
  id            bigserial primary key,
  ticker        text not null,
  plan_id       bigint references paper_planes(id) on delete cascade,
  condicion     text not null,     -- 'calidad_degradada','earnings_debiles','ruptura_soporte'
  umbral        jsonb not null,
  activa        boolean not null default true,
  disparada_en  timestamptz,
  creado_en     timestamptz not null default now()
);

create table if not exists backtest_resultados (
  id             bigserial primary key,
  ejecutado_en   timestamptz not null default now(),
  motor_version  text not null,
  ticker         text not null,
  fecha_senal    date not null,
  senal          text not null,
  precio         numeric,
  retorno_3m     numeric,
  retorno_6m     numeric,
  retorno_12m    numeric,
  bench_3m       numeric,
  bench_6m       numeric,
  bench_12m      numeric,
  parametros     jsonb,
  unique (motor_version, ticker, fecha_senal)
);

create table if not exists diario_decisiones (
  id         bigserial primary key,
  ticker     text not null,
  plan_id    bigint,
  accion     text not null,        -- 'guardar_plan','ejecutar_nivel','descartar','invalidar'
  motivo     text,
  creado_en  timestamptz not null default now()
);

-- Caché L2: sobrevive a los reinicios del contenedor de Streamlit Cloud.
create table if not exists cache_l2 (
  clave        text primary key,
  valor        jsonb not null,
  obtenido_en  timestamptz not null default now(),
  ttl_seg      integer not null
);

-- Deduplicación de alertas Telegram (una por evento).
create table if not exists alertas_enviadas (
  id          bigserial primary key,
  tipo        text not null,
  ticker      text not null,
  clave_dedup text not null unique,
  enviada_en  timestamptz not null default now()
);
