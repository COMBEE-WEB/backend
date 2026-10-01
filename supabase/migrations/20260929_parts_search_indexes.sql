-- Supports active category pagination and case-insensitive manufacturer filters.
-- No records are changed or deleted.
CREATE INDEX IF NOT EXISTS idx_parts_active_category_id
  ON public.parts (category, id) WHERE is_active = true;
CREATE INDEX IF NOT EXISTS idx_parts_active_category_manufacturer_id
  ON public.parts (category, lower(manufacturer), id) WHERE is_active = true;

-- Refresh statistics after importing 48,327 rows so PostgreSQL can choose
-- category indexes rather than scanning the primary key in ID order.
ANALYZE public.parts;
