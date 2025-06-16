-- Enable UUID extension if not already enabled
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Accounts Table
CREATE TABLE accounts (
    account_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    account_holder_name VARCHAR(255) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL, -- Should be encrypted at rest
    hashed_password VARCHAR(255) NOT NULL, -- Store hashed passwords only
    status VARCHAR(50) DEFAULT 'active', -- e.g., active, inactive, suspended
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Transactions Table
CREATE TABLE transactions (
    transaction_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    sender_account_id UUID REFERENCES accounts(account_id),
    receiver_account_id UUID REFERENCES accounts(account_id),
    amount DECIMAL(18, 2) NOT NULL,
    currency VARCHAR(3) NOT NULL, -- e.g., 'USD'
    transaction_type VARCHAR(50) NOT NULL, -- e.g., transfer, deposit, withdrawal, fee
    description TEXT,
    status VARCHAR(50) DEFAULT 'pending', -- e.g., pending, completed, failed, cancelled
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_amount CHECK (amount > 0) -- Ensure transaction amount is positive
);

-- Balances Table
CREATE TABLE balances (
    balance_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    account_id UUID UNIQUE NOT NULL REFERENCES accounts(account_id),
    balance DECIMAL(18, 2) NOT NULL DEFAULT 0.00,
    currency VARCHAR(3) NOT NULL, -- e.g., 'USD'
    last_updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Serial Boxes Table
CREATE TABLE serial_boxes (
    serial_box_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    serial_number VARCHAR(255) UNIQUE NOT NULL, -- Should be encrypted at rest
    product_id VARCHAR(100),
    assigned_account_id UUID REFERENCES accounts(account_id),
    status VARCHAR(50) DEFAULT 'unassigned', -- e.g., unassigned, assigned, activated, voided
    metadata JSONB, -- For flexible storage of additional data, consider encrypting sensitive fields
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for performance
CREATE INDEX idx_transactions_sender_account_id ON transactions(sender_account_id);
CREATE INDEX idx_transactions_receiver_account_id ON transactions(receiver_account_id);
CREATE INDEX idx_transactions_status ON transactions(status);
CREATE INDEX idx_balances_account_id ON balances(account_id);
CREATE INDEX idx_serial_boxes_serial_number ON serial_boxes(serial_number);
CREATE INDEX idx_serial_boxes_assigned_account_id ON serial_boxes(assigned_account_id);
CREATE INDEX idx_serial_boxes_status ON serial_boxes(status);
CREATE INDEX idx_accounts_email ON accounts(email);

-- Trigger function to update 'updated_at' columns
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Triggers for 'accounts' table
CREATE TRIGGER trigger_accounts_updated_at
BEFORE UPDATE ON accounts
FOR EACH ROW
EXECUTE FUNCTION update_updated_at_column();

-- Triggers for 'transactions' table
CREATE TRIGGER trigger_transactions_updated_at
BEFORE UPDATE ON transactions
FOR EACH ROW
EXECUTE FUNCTION update_updated_at_column();

-- Triggers for 'serial_boxes' table
CREATE TRIGGER trigger_serial_boxes_updated_at
BEFORE UPDATE ON serial_boxes
FOR EACH ROW
EXECUTE FUNCTION update_updated_at_column();

-- Trigger for 'balances' table (for last_updated_at)
CREATE OR REPLACE FUNCTION update_balances_last_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.last_updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_balances_last_updated_at
BEFORE UPDATE ON balances
FOR EACH ROW
EXECUTE FUNCTION update_balances_last_updated_at_column();

COMMENT ON COLUMN accounts.email IS 'Should be encrypted at rest.';
COMMENT ON COLUMN accounts.hashed_password IS 'Store hashed passwords only using a strong hashing algorithm like bcrypt or Argon2.';
COMMENT ON COLUMN serial_boxes.serial_number IS 'Should be encrypted at rest.';
COMMENT ON COLUMN serial_boxes.metadata IS 'For flexible storage of additional data. Consider encrypting sensitive fields within the JSON structure if necessary.';
COMMENT ON TABLE transactions IS 'Stores all financial transactions. sender_account_id can be NULL for initial deposits from external systems, and receiver_account_id can be NULL for withdrawals to external systems.';
COMMENT ON TABLE balances IS 'Stores the current aggregated balance for each account and currency pair.';

-- Note on Encryption:
-- The comments indicate fields that should be encrypted at rest.
-- This typically involves application-level encryption before data insertion/retrieval
-- or using database-specific encryption features (e.g., pgcrypto for PostgreSQL if direct DB encryption is chosen).
-- Hashing for passwords is a one-way process.
-- Ensure appropriate key management practices if application-level encryption is used.
-- Always use TLS/SSL for data in transit.
-- Implement strict access controls and audit logging.
