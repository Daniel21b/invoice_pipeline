-- Additive: do not run the legacy destructive schema.sql against existing data.
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS extraction_id TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS invoices_extraction_id_key ON invoices(extraction_id);
