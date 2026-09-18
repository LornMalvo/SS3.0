-- StockScanner — migración 004 (sesión 6). Ejecutar en el editor SQL de
-- Supabase DESPUÉS de la 003. Idempotente.

-- 1. Anotaciones con fecha: una fila por nota (antes, un único texto por
--    ticker). Las notas existentes pasan a la nueva tabla con su fecha.
create table if not exists anotaciones_entradas (
  id         bigserial primary key,
  ticker     text not null,
  texto      text not null,
  creado_en  timestamptz not null default now()
);
create index if not exists idx_anotaciones_entradas_ticker on anotaciones_entradas (ticker, creado_en desc);
insert into anotaciones_entradas (ticker, texto, creado_en)
select a.ticker, a.texto, a.actualizado_en
from anotaciones a
where coalesce(a.texto, '') <> ''
  and not exists (select 1 from anotaciones_entradas e where e.ticker = a.ticker);

-- 2. Comparables (peer to peer). origen: 'finnhub' (sugerido), 'manual'
--    (validado por el usuario; se guarda en AMBAS direcciones), 'rechazado'
--    (sugerencia descartada: se conserva para no volver a sembrarla).
create table if not exists comparables (
  ticker     text not null,
  peer       text not null,
  origen     text not null default 'manual' check (origen in ('finnhub', 'manual', 'rechazado')),
  creado_en  timestamptz not null default now(),
  primary key (ticker, peer)
);

-- 3. Múltiplos y márgenes de cada ticker analizado (propio, comparable o
--    rastreado por el cron): de aquí salen las medianas de comparables
--    reales y las medianas reales por sector.
create table if not exists multiplos (
  ticker          text primary key,
  nombre          text,
  sector          text,
  industria       text,
  divisa          text,
  valores         jsonb not null,
  actualizado_en  timestamptz not null default now()
);
create index if not exists idx_multiplos_sector on multiplos (sector);

-- 4. Medianas reales por sector, recalculadas por el rastreo nocturno
--    sobre todo `multiplos`. Sustituyen a la tabla semilla de
--    config_sectores cuando hay muestra suficiente.
create table if not exists sector_referencias (
  sector          text primary key,
  referencias     jsonb not null,    -- {clave: {"mediana": x, "n": n}}
  n               integer not null,
  actualizado_en  timestamptz not null default now()
);

-- 5. Rastreo nocturno de índices enteros.
create table if not exists rastreador_indices (
  nombre          text primary key,
  activo          boolean not null default false,
  tickers         jsonb not null default '[]'::jsonb,
  n               integer not null default 0,
  actualizado_en  timestamptz
);
create table if not exists rastreo_pases (
  id        bigserial primary key,
  indice    text not null,
  inicio    timestamptz not null default now(),
  fin       timestamptz,
  estado    text not null default 'en_curso' check (estado in ('en_curso', 'completado', 'abortado')),
  n_total   integer not null default 0,
  n_ok      integer not null default 0,
  n_error   integer not null default 0,
  detalle   jsonb
);

-- 6. analisis_historico: origen del análisis (screener = origen 'cron'),
--    nombre y sector como columnas (filtros SQL sin abrir el JSON), timing
--    bruto sin gate de calidad y banda de valoración.
alter table analisis_historico add column if not exists origen text not null default 'individual';
alter table analisis_historico add column if not exists nombre text;
alter table analisis_historico add column if not exists sector text;
alter table analisis_historico add column if not exists timing_bruto numeric;
alter table analisis_historico add column if not exists banda text;
create index if not exists idx_analisis_origen_fecha on analisis_historico (origen, fecha_analisis desc);
