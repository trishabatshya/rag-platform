-- Applied by AuditStore after SQLAlchemy creates audit tables.
-- The development schema owner can still disable/drop triggers; use a restricted
-- application role and a separate migration owner in production.
CREATE OR REPLACE FUNCTION reject_audit_changes() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'audit is append-only';
END;
$$;
-- STATEMENT
CREATE OR REPLACE TRIGGER audit_log_immutable
BEFORE UPDATE OR DELETE OR TRUNCATE ON audit_log
FOR EACH STATEMENT EXECUTE FUNCTION reject_audit_changes();
-- STATEMENT
CREATE OR REPLACE TRIGGER audit_doc_access_immutable
BEFORE UPDATE OR DELETE OR TRUNCATE ON audit_doc_access
FOR EACH STATEMENT EXECUTE FUNCTION reject_audit_changes();
