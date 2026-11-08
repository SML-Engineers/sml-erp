from django.db import migrations

# P3-06: a production order is never deleted, keeps its number and division, changes its
# part, quantity, purpose and due dates only while a draft, and moves only forward
# (draft → released → completed → closed; draft or released → cancelled). The BOM copied on
# release never changes. Plus the "MO" number series.

SQL = """
CREATE OR REPLACE FUNCTION production_order_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'Production order % is never deleted; cancel it', OLD.number
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW IS NOT DISTINCT FROM OLD THEN
    RETURN NEW;
  END IF;
  IF OLD.status IN ('closed', 'cancelled') THEN
    RAISE EXCEPTION 'Production order % is %: it never changes', OLD.number, OLD.status
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW.number <> OLD.number OR NEW.division_id <> OLD.division_id THEN
    RAISE EXCEPTION 'A production order keeps its number and division'
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF OLD.status <> 'draft' AND (
       NEW.item_id <> OLD.item_id OR NEW.quantity <> OLD.quantity
       OR NEW.purpose <> OLD.purpose
       OR NEW.sales_line_id IS DISTINCT FROM OLD.sales_line_id
       OR NEW.bom_id IS DISTINCT FROM OLD.bom_id
       OR NEW.mould_id IS DISTINCT FROM OLD.mould_id) THEN
    RAISE EXCEPTION 'Production order % is released: its part, quantity and BOM never change',
      OLD.number USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW.status <> OLD.status AND NOT (
       (OLD.status = 'draft' AND NEW.status IN ('released', 'cancelled'))
       OR (OLD.status = 'released' AND NEW.status IN ('completed', 'cancelled'))
       OR (OLD.status = 'completed' AND NEW.status = 'closed')) THEN
    RAISE EXCEPTION 'A production order cannot go from % to %', OLD.status, NEW.status
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER production_order_guard
BEFORE UPDATE OR DELETE ON production_productionorder
FOR EACH ROW EXECUTE FUNCTION production_order_guard();

CREATE OR REPLACE FUNCTION production_order_due_guard() RETURNS trigger AS $$
DECLARE
  state text;
BEGIN
  IF TG_OP = 'UPDATE' AND NEW IS NOT DISTINCT FROM OLD THEN
    RETURN NEW;
  END IF;
  SELECT status INTO state FROM production_productionorder
    WHERE id = CASE WHEN TG_OP = 'DELETE' THEN OLD.order_id ELSE NEW.order_id END;
  IF state IS NOT NULL AND state <> 'draft' THEN
    RAISE EXCEPTION 'The due dates of a released production order never change'
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER production_order_due_guard
BEFORE INSERT OR UPDATE OR DELETE ON production_productionorderdue
FOR EACH ROW EXECUTE FUNCTION production_order_due_guard();

CREATE OR REPLACE FUNCTION production_order_bom_guard() RETURNS trigger AS $$
DECLARE
  state text;
BEGIN
  IF TG_OP = 'UPDATE' AND NEW IS NOT DISTINCT FROM OLD THEN
    RETURN NEW;
  END IF;
  IF TG_OP <> 'INSERT' THEN
    RAISE EXCEPTION 'The BOM copied to a production order never changes'
      USING ERRCODE = 'restrict_violation';
  END IF;
  SELECT status INTO state FROM production_productionorder WHERE id = NEW.order_id;
  IF state IS DISTINCT FROM 'released' THEN
    RAISE EXCEPTION 'The BOM is copied to a production order when it is released'
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER production_order_bom_guard
BEFORE INSERT OR UPDATE OR DELETE ON production_orderbomline
FOR EACH ROW EXECUTE FUNCTION production_order_bom_guard();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS production_order_bom_guard ON production_orderbomline;
DROP FUNCTION IF EXISTS production_order_bom_guard();
DROP TRIGGER IF EXISTS production_order_due_guard ON production_productionorderdue;
DROP FUNCTION IF EXISTS production_order_due_guard();
DROP TRIGGER IF EXISTS production_order_guard ON production_productionorder;
DROP FUNCTION IF EXISTS production_order_guard();
"""

SERIES = ("production_order", "Production orders", "MO{YY}{MM}{NNNN}", "monthly", "grow")


def seed(apps, schema_editor):
    NumberSeries = apps.get_model("core", "NumberSeries")
    document_type, name, number_format, reset, when_full = SERIES
    NumberSeries.objects.get_or_create(
        document_type=document_type,
        defaults={
            "name": name,
            "format": number_format,
            "reset_period": reset,
            "when_full": when_full,
        },
    )


def unseed(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("production", "0012_production_orders"),
        ("core", "0027_company_epf_etf"),
    ]

    operations = [migrations.RunSQL(SQL, BACKWARD), migrations.RunPython(seed, unseed)]
