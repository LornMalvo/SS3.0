-- StockScanner — migración 003 (sesión 5). Ejecutar en el editor SQL de
-- Supabase DESPUÉS de la 002. Idempotente.

-- Marca de ejecución automática (E1 alcanzado) frente a manual.
alter table paper_ejecuciones add column if not exists automatica boolean not null default false;

-- Universo propio del Rastreador: tickers que se rastrean además de los de
-- Favoritos, Cartera y Paper Trading.
create table if not exists rastreador_universo (
  ticker     text primary key,
  creado_en  timestamptz not null default now()
);

-- Índice para la deduplicación de alertas por lote de claves.
create index if not exists idx_alertas_clave on alertas_enviadas (clave_dedup);
