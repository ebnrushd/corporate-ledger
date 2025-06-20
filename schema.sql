-- Enable UUID extension if not already enabled
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- === Main Tables ===

-- Accounts Table (System-Versioned)
CREATE TABLE accounts (
    account_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    account_holder_name VARCHAR(255) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL, -- Should be encrypted at rest
    hashed_password VARCHAR(255) NOT NULL, -- Store hashed passwords only
    status VARCHAR(50) DEFAULT 'active', -- e.g., active, inactive, suspended
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP, -- Creation of the account entity itself
    sys_period_start TIMESTAMPTZ NOT NULL DEFAULT transaction_timestamp() -- Start of the current version's validity
);

COMMENT ON TABLE accounts IS 'Stores current account information. This table is system-versioned, with historical versions stored in accounts_history.';
COMMENT ON COLUMN accounts.created_at IS 'Timestamp of when the account entity was originally created.';
COMMENT ON COLUMN accounts.sys_period_start IS 'Timestamp indicating when this version of the account row became current (valid from).';

-- Accounts History Table (for System Versioning)
CREATE TABLE accounts_history (
    account_id UUID NOT NULL,
    account_holder_name VARCHAR(255) NOT NULL,
    email VARCHAR(255) NOT NULL,
    hashed_password VARCHAR(255) NOT NULL,
    status VARCHAR(50),
    created_at TIMESTAMP WITH TIME ZONE,
    sys_period_start TIMESTAMPTZ NOT NULL,
    sys_period_end TIMESTAMPTZ NOT NULL
);

COMMENT ON TABLE accounts_history IS 'Stores historical versions of rows from the "accounts" table for system versioning (transaction-time temporal).';
COMMENT ON COLUMN accounts_history.sys_period_start IS 'Timestamp when this historical version of the row was valid from.';
COMMENT ON COLUMN accounts_history.sys_period_end IS 'Timestamp when this historical version of the row was valid until (superseded or deleted).';

CREATE INDEX idx_accounts_history_account_id ON accounts_history(account_id);
CREATE INDEX idx_accounts_history_sys_period_start ON accounts_history(sys_period_start);
CREATE INDEX idx_accounts_history_sys_period_end ON accounts_history(sys_period_end);


-- Transactions Table
CREATE TABLE transactions (
    transaction_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    sender_account_id UUID REFERENCES accounts(account_id),
    receiver_account_id UUID REFERENCES accounts(account_id),
    amount DECIMAL(18, 2) NOT NULL,
    currency VARCHAR(3) NOT NULL,
    transaction_type VARCHAR(50) NOT NULL,
    description TEXT,
    status VARCHAR(50) DEFAULT 'pending',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP, -- Standard updated_at for non-versioned mutable fields
    previous_transaction_hash TEXT DEFAULT NULL,
    current_transaction_hash TEXT UNIQUE,
    CONSTRAINT chk_amount CHECK (amount > 0)
);

COMMENT ON COLUMN transactions.previous_transaction_hash IS 'Stores the hash of the preceding transaction in a logical chain.';
COMMENT ON COLUMN transactions.current_transaction_hash IS 'Stores a unique hash of the current transaction''s key data fields.';
COMMENT ON COLUMN transactions.updated_at IS 'Timestamp of the last update to this transaction record (e.g., status change).';


-- Balances Table (System-Versioned)
CREATE TABLE balances (
    balance_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    account_id UUID NOT NULL, -- Changed from UNIQUE NOT NULL to just NOT NULL for composite key
    balance DECIMAL(18, 2) NOT NULL DEFAULT 0.00,
    currency VARCHAR(3) NOT NULL,
    sys_period_start TIMESTAMPTZ NOT NULL DEFAULT transaction_timestamp() -- Start of the current version's validity
);
-- Composite unique constraint for account_id and currency pair for current balances
ALTER TABLE balances ADD CONSTRAINT unique_account_currency_current_balance UNIQUE (account_id, currency);

COMMENT ON TABLE balances IS 'Stores current account balances per currency. This table is system-versioned, with historical versions stored in balances_history.';
COMMENT ON COLUMN balances.sys_period_start IS 'Timestamp indicating when this version of the balance row became current (valid from).';


-- Balances History Table (for System Versioning)
CREATE TABLE balances_history (
    balance_id UUID NOT NULL,
    account_id UUID NOT NULL,
    balance DECIMAL(18, 2) NOT NULL,
    currency VARCHAR(3) NOT NULL,
    sys_period_start TIMESTAMPTZ NOT NULL,
    sys_period_end TIMESTAMPTZ NOT NULL
);

COMMENT ON TABLE balances_history IS 'Stores historical versions of rows from the "balances" table for system versioning.';
COMMENT ON COLUMN balances_history.sys_period_start IS 'Timestamp when this historical version of the row was valid from.';
COMMENT ON COLUMN balances_history.sys_period_end IS 'Timestamp when this historical version of the row was valid until (superseded or deleted).';

CREATE INDEX idx_balances_history_balance_id ON balances_history(balance_id);
CREATE INDEX idx_balances_history_account_id_currency ON balances_history(account_id, currency);
CREATE INDEX idx_balances_history_sys_period_start ON balances_history(sys_period_start);
CREATE INDEX idx_balances_history_sys_period_end ON balances_history(sys_period_end);


-- Serial Boxes Table
CREATE TABLE serial_boxes (
    serial_box_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    serial_number VARCHAR(255) UNIQUE NOT NULL,
    product_id VARCHAR(100),
    assigned_account_id UUID REFERENCES accounts(account_id),
    status VARCHAR(50) DEFAULT 'unassigned',
    metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP -- Standard updated_at
);

-- === Indexes for Performance ===
CREATE INDEX idx_transactions_sender_account_id ON transactions(sender_account_id);
CREATE INDEX idx_transactions_receiver_account_id ON transactions(receiver_account_id);
CREATE INDEX idx_transactions_status ON transactions(status);
CREATE INDEX idx_transactions_previous_hash ON transactions(previous_transaction_hash);
CREATE INDEX idx_transactions_current_hash ON transactions(current_transaction_hash);

CREATE INDEX idx_balances_account_id_currency ON balances(account_id, currency);
CREATE INDEX idx_serial_boxes_serial_number ON serial_boxes(serial_number);
CREATE INDEX idx_serial_boxes_assigned_account_id ON serial_boxes(assigned_account_id);
CREATE INDEX idx_serial_boxes_status ON serial_boxes(status);
CREATE INDEX idx_accounts_email ON accounts(email);

-- === Trigger Functions for Standard Columns (e.g., updated_at on non-versioned tables) ===

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = transaction_timestamp();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
COMMENT ON FUNCTION update_updated_at_column() IS 'Updates the "updated_at" column to the current transaction timestamp.';

CREATE TRIGGER trigger_transactions_updated_at
BEFORE UPDATE ON transactions
FOR EACH ROW
WHEN (OLD.* IS DISTINCT FROM NEW.*)
EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER trigger_serial_boxes_updated_at
BEFORE UPDATE ON serial_boxes
FOR EACH ROW
WHEN (OLD.* IS DISTINCT FROM NEW.*)
EXECUTE FUNCTION update_updated_at_column();

DROP FUNCTION IF EXISTS update_balances_last_updated_at_column() CASCADE;


-- === System Versioning for 'accounts' table ===
CREATE OR REPLACE FUNCTION version_accounts_history()
RETURNS TRIGGER AS $$
BEGIN
    IF (TG_OP = 'UPDATE') THEN
        INSERT INTO accounts_history (
            account_id, account_holder_name, email, hashed_password, status,
            created_at, sys_period_start, sys_period_end
        ) VALUES (
            OLD.account_id, OLD.account_holder_name, OLD.email, OLD.hashed_password, OLD.status,
            OLD.created_at, OLD.sys_period_start, transaction_timestamp()
        );
        RETURN NEW;
    ELSIF (TG_OP = 'DELETE') THEN
        INSERT INTO accounts_history (
            account_id, account_holder_name, email, hashed_password, status,
            created_at, sys_period_start, sys_period_end
        ) VALUES (
            OLD.account_id, OLD.account_holder_name, OLD.email, OLD.hashed_password, OLD.status,
            OLD.created_at, OLD.sys_period_start, transaction_timestamp()
        );
        RETURN OLD;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;
COMMENT ON FUNCTION version_accounts_history() IS 'Handles system versioning for "accounts" by inserting old versions into "accounts_history".';

CREATE OR REPLACE FUNCTION accounts_set_sys_period_start()
RETURNS TRIGGER AS $$
BEGIN
    NEW.sys_period_start = transaction_timestamp();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
COMMENT ON FUNCTION accounts_set_sys_period_start() IS 'Sets sys_period_start for new versions in "accounts".';

DROP TRIGGER IF EXISTS trigger_accounts_updated_at ON accounts;
CREATE TRIGGER accounts_versioning_update_sys_period_trigger
BEFORE UPDATE ON accounts
FOR EACH ROW
WHEN (OLD.* IS DISTINCT FROM NEW.*)
EXECUTE FUNCTION accounts_set_sys_period_start();
COMMENT ON TRIGGER accounts_versioning_update_sys_period_trigger ON accounts IS 'Sets sys_period_start for new current row version before an UPDATE on accounts.';

CREATE TRIGGER accounts_history_trigger
AFTER UPDATE OR DELETE ON accounts
FOR EACH ROW
EXECUTE FUNCTION version_accounts_history();
COMMENT ON TRIGGER accounts_history_trigger ON accounts IS 'Moves old row version to accounts_history after UPDATE or DELETE on accounts.';


-- === System Versioning for 'balances' table ===

CREATE OR REPLACE FUNCTION version_balances_history()
RETURNS TRIGGER AS $$
BEGIN
    IF (TG_OP = 'UPDATE') THEN
        INSERT INTO balances_history (
            balance_id, account_id, balance, currency,
            sys_period_start, sys_period_end
        ) VALUES (
            OLD.balance_id, OLD.account_id, OLD.balance, OLD.currency,
            OLD.sys_period_start, transaction_timestamp()
        );
        RETURN NEW;
    ELSIF (TG_OP = 'DELETE') THEN
        INSERT INTO balances_history (
            balance_id, account_id, balance, currency,
            sys_period_start, sys_period_end
        ) VALUES (
            OLD.balance_id, OLD.account_id, OLD.balance, OLD.currency,
            OLD.sys_period_start, transaction_timestamp()
        );
        RETURN OLD;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;
COMMENT ON FUNCTION version_balances_history() IS 'Handles system versioning for "balances" by inserting old versions into "balances_history".';

CREATE OR REPLACE FUNCTION balances_set_sys_period_start()
RETURNS TRIGGER AS $$
BEGIN
    NEW.sys_period_start = transaction_timestamp();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
COMMENT ON FUNCTION balances_set_sys_period_start() IS 'Sets sys_period_start for new versions in "balances".';

DROP TRIGGER IF EXISTS trigger_balances_last_updated_at ON balances;

CREATE TRIGGER balances_versioning_update_sys_period_trigger
BEFORE UPDATE ON balances
FOR EACH ROW
WHEN (OLD.* IS DISTINCT FROM NEW.*)
EXECUTE FUNCTION balances_set_sys_period_start();
COMMENT ON TRIGGER balances_versioning_update_sys_period_trigger ON balances IS 'Sets sys_period_start for new current row version before an UPDATE on balances.';

CREATE TRIGGER balances_history_trigger
AFTER UPDATE OR DELETE ON balances
FOR EACH ROW
EXECUTE FUNCTION version_balances_history();
COMMENT ON TRIGGER balances_history_trigger ON balances IS 'Moves old row version to balances_history after UPDATE or DELETE on balances.';


-- === Audit Logging (Generic) ===
CREATE TABLE ledger_audit_log (
    audit_id BIGSERIAL PRIMARY KEY,
    schema_name TEXT NOT NULL,
    table_name TEXT NOT NULL,
    user_name TEXT,
    action_timestamp TIMESTAMPTZ DEFAULT NOW(),
    action TEXT NOT NULL CHECK (action IN ('INSERT', 'UPDATE', 'DELETE', 'TRUNCATE')),
    original_data JSONB,
    changed_data JSONB,
    query TEXT
);
COMMENT ON TABLE ledger_audit_log IS 'Table to log changes (INSERT, UPDATE, DELETE) to key ledger tables.';
CREATE INDEX idx_audit_log_table_name ON ledger_audit_log(table_name);
CREATE INDEX idx_audit_log_action_timestamp ON ledger_audit_log(action_timestamp);
CREATE INDEX idx_audit_log_user_name ON ledger_audit_log(user_name);

CREATE OR REPLACE FUNCTION log_ledger_changes()
RETURNS TRIGGER AS $$
DECLARE v_old_data JSONB; v_new_data JSONB;
BEGIN
    IF (TG_OP = 'UPDATE') THEN v_old_data := to_jsonb(OLD); v_new_data := to_jsonb(NEW);
    ELSIF (TG_OP = 'DELETE') THEN v_old_data := to_jsonb(OLD); v_new_data := NULL;
    ELSIF (TG_OP = 'INSERT') THEN v_old_data := NULL; v_new_data := to_jsonb(NEW);
    ELSE RAISE WARNING '[AUDIT.LOG] Unhandled TG_OP: "%"', TG_OP; RETURN NULL; END IF;
    INSERT INTO ledger_audit_log (schema_name, table_name, user_name, action, original_data, changed_data, query)
    VALUES (TG_TABLE_SCHEMA::TEXT, TG_TABLE_NAME::TEXT, session_user::TEXT, TG_OP::TEXT, v_old_data, v_new_data, current_query());
    IF (TG_OP = 'DELETE') THEN RETURN OLD; ELSE RETURN NEW; END IF;
EXCEPTION WHEN OTHERS THEN RAISE WARNING '[AUDIT.LOG] Error: %', SQLERRM; IF (TG_OP = 'DELETE') THEN RETURN OLD; ELSE RETURN NEW; END IF;
END;
$$ LANGUAGE plpgsql;
COMMENT ON FUNCTION log_ledger_changes() IS 'Generic trigger to log DML into ledger_audit_log.';

-- === Attaching Audit Triggers ===
CREATE TRIGGER audit_accounts_changes
AFTER INSERT OR UPDATE OR DELETE ON accounts FOR EACH ROW EXECUTE FUNCTION log_ledger_changes();
COMMENT ON TRIGGER audit_accounts_changes ON accounts IS 'Audits current "accounts" table changes.';

CREATE TRIGGER audit_balances_changes
AFTER INSERT OR UPDATE OR DELETE ON balances FOR EACH ROW EXECUTE FUNCTION log_ledger_changes();
COMMENT ON TRIGGER audit_balances_changes ON balances IS 'Audits "balances" table changes.';

CREATE TRIGGER audit_transactions_changes
AFTER INSERT OR UPDATE OR DELETE ON transactions FOR EACH ROW EXECUTE FUNCTION log_ledger_changes();
COMMENT ON TRIGGER audit_transactions_changes ON transactions IS 'Audits "transactions" table changes.';

-- === Role Based Access Control (RBAC) ===
COMMENT ON SCHEMA public IS 'Standard public schema.'; -- Assuming 'public' schema for now.

-- Define Roles
CREATE ROLE ledger_reader_role;
COMMENT ON ROLE ledger_reader_role IS 'Role for read-only access to ledger data.';

CREATE ROLE ledger_writer_role;
COMMENT ON ROLE ledger_writer_role IS 'Role for write access to specific ledger tables (e.g., transactions, serial_boxes), typically for processes that record new operational data but do not manage accounts or balances directly.';

CREATE ROLE ledger_admin_service_role;
COMMENT ON ROLE ledger_admin_service_role IS 'Role for the main application service, granting comprehensive operational permissions on ledger tables.';

-- Grant Privileges to Roles (assuming 'public' schema)

-- ledger_reader_role: SELECT on all tables
GRANT USAGE ON SCHEMA public TO ledger_reader_role;
GRANT SELECT ON TABLE
    accounts, accounts_history,
    balances, balances_history,
    transactions,
    serial_boxes,
    ledger_audit_log
TO ledger_reader_role;
-- For future tables created by the schema owner (e.g., 'admin_user' or 'postgres')
-- ALTER DEFAULT PRIVILEGES FOR ROLE admin_user IN SCHEMA public GRANT SELECT ON TABLES TO ledger_reader_role;

-- ledger_writer_role: Specific write access, plus SELECT needed for operations
GRANT USAGE ON SCHEMA public TO ledger_writer_role;
GRANT SELECT ON TABLE accounts, balances, transactions, serial_boxes TO ledger_writer_role; -- Writers often need to read related data
GRANT INSERT, UPDATE ON TABLE transactions, serial_boxes TO ledger_writer_role;
-- Permissions for sequences used by tables this role inserts into (e.g., ledger_audit_log if it were to write there directly)
-- Our primary keys are mostly UUIDs generated by app, but ledger_audit_log.audit_id is BIGSERIAL.
-- Triggers handle audit log inserts, usually with definer rights, so direct grants on audit_id_seq might not be needed for this role.
-- However, if this role was responsible for any table with SERIAL/BIGSERIAL PKs it inserts into:
-- GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO ledger_writer_role; (Grant more selectively if possible)
GRANT USAGE, SELECT ON SEQUENCE ledger_audit_log_audit_id_seq TO ledger_writer_role;


-- ledger_admin_service_role: Broad permissions for the application service
GRANT USAGE ON SCHEMA public TO ledger_admin_service_role;
-- Inherit read and basic write capabilities
GRANT ledger_reader_role TO ledger_admin_service_role;
GRANT ledger_writer_role TO ledger_admin_service_role;

-- Grant more comprehensive DML permissions on operational tables
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE
    accounts,
    balances,
    transactions,
    serial_boxes
TO ledger_admin_service_role;

-- Permissions for all sequences, primarily for ledger_audit_log.audit_id if app makes direct inserts (though triggers do it)
-- and any other tables it might manage with serial PKs.
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO ledger_admin_service_role;
-- The audit triggers will run with the permissions of their definer (usually the user creating them/owning table),
-- so direct INSERT permission on ledger_audit_log for ledger_admin_service_role is typically not needed for trigger-based auditing.

-- Granting roles to actual database users:
-- Example (run by a superuser or user with appropriate grant permissions):
-- CREATE USER my_app_user WITH PASSWORD 'secure_password';
-- GRANT ledger_admin_service_role TO my_app_user;
--
-- CREATE USER readonly_user WITH PASSWORD 'secure_password';
-- GRANT ledger_reader_role TO readonly_user;


-- Final Comments
COMMENT ON COLUMN accounts.email IS 'Should be encrypted at rest.';
COMMENT ON COLUMN accounts.hashed_password IS 'Store hashed passwords only.';
COMMENT ON COLUMN serial_boxes.serial_number IS 'Should be encrypted at rest.';
COMMENT ON COLUMN serial_boxes.metadata IS 'Flexible JSONB storage; encrypt sensitive fields if any.';
COMMENT ON TABLE transactions IS 'Stores financial transactions; includes optional chaining hashes.';
COMMENT ON TABLE balances IS 'Stores current account balances per currency; system-versioned.';
-- Note on Encryption, TRUNCATE for audit logs, etc. (as before)
