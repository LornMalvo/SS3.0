-- StockScanner — migración 002 (sesión 4): Gestión de Cartera y Paper Trading.
-- Ejecutar en el editor SQL de Supabase después de la 001. Idempotente.

-- Capital nominal del plan simulado (se fija al ejecutar el primer nivel).
alter table paper_planes add column if not exists capital_eur numeric;

-- El libro guarda EUR (divisa base), pero se conserva lo que se tecleó:
-- precio en su divisa y tipo de cambio aplicado, para poder auditar.
alter table cartera_operaciones add column if not exists divisa text;
alter table cartera_operaciones add column if not exists precio_origen numeric;
alter table cartera_operaciones add column if not exists fx_aplicado numeric;

-- Las ejecuciones de Paper Trading crean operaciones con origen 'paper' y
-- el id del plan: al borrar el plan hay que poder localizarlas rápido.
create index if not exists idx_operaciones_plan on cartera_operaciones (plan_id) where plan_id is not null;
create index if not exists idx_paper_ejecuciones_plan on paper_ejecuciones (plan_id);
