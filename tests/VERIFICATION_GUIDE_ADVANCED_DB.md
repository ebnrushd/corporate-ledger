# Verification Guide for Advanced Database Features

## 0. Introduction

This document provides guidance and example SQL statements for verifying the advanced database features implemented in `schema.sql`. These features include:

*   Audit Logging (`ledger_audit_log` and generic trigger)
*   Temporal Tables / System Versioning (for `accounts` and `balances` tables)
*   Role-Based Access Control (RBAC)
*   Transaction Chaining (in `transactions` table)

This guide is intended for manual verification or as a basis for developing more automated database tests. Ensure you are connected to your PostgreSQL database instance where the `schema.sql` has been applied.

**Note:** Some DML operations will trigger others (e.g., updating `accounts` will also trigger the generic audit log). The verification steps focus on the primary outcome of each feature.

## 1. Audit Log Verification

The `ledger_audit_log` table, populated by the `log_ledger_changes()` trigger, should record all INSERT, UPDATE, and DELETE operations on `accounts`, `balances`, and `transactions`.

### Setup: Ensure some data exists

```sql
-- Assuming you have an account_id from previous operations, or insert a new one:
INSERT INTO accounts (account_holder_name, email, hashed_password, status)
VALUES ('Audit Test User', 'audit@example.com', 'some_hash', 'active') RETURNING account_id;
-- Let's say the above returned account_id '...'; use it below.
-- For simplicity, we'll use a placeholder UUID. Replace with an actual one from your DB.
-- DEFINE test_account_id UUID = 'your-actual-account-id-here';
```
**Replace `'your-actual-account-id-here'` with an actual `account_id` in the following examples.**

### a. Verify INSERT Logging

**Action:**
```sql
-- Example for 'accounts' table
INSERT INTO accounts (account_holder_name, email, hashed_password, status)
VALUES ('New Audit User', 'newaudit@example.com', 'new_hash', 'pending');

-- Example for 'balances' table (assuming 'your-actual-account-id-here' exists and doesn't have a USD balance yet)
-- If unique_account_currency_balance constraint is hit, this INSERT might fail.
-- Ensure the (account_id, currency) pair is unique for the 'balances' table for new inserts.
-- Or, use an account_id that doesn't have a USD balance yet.
INSERT INTO balances (account_id, balance, currency)
VALUES ('your-actual-account-id-here', 100.00, 'USD');

-- Example for 'transactions' table
INSERT INTO transactions (receiver_account_id, amount, currency, transaction_type, description, status)
VALUES ('your-actual-account-id-here', 50.00, 'USD', 'deposit', 'Audit test deposit', 'completed');
```

**Verification:**
```sql
SELECT audit_id, schema_name, table_name, user_name, action_timestamp, action, original_data, changed_data, query
FROM ledger_audit_log
WHERE table_name IN ('accounts', 'balances', 'transactions')
  AND action = 'INSERT'
ORDER BY action_timestamp DESC LIMIT 3;

-- Expected: For each INSERT, an audit log entry where:
-- - table_name matches the table operated on.
-- - action = 'INSERT'.
-- - original_data IS NULL.
-- - changed_data contains the JSONB representation of the newly inserted row.
-- - user_name is your current PostgreSQL user.
-- - query contains the INSERT statement.
```

### b. Verify UPDATE Logging

**Action:**
```sql
-- Example for 'accounts' table
UPDATE accounts SET status = 'active' WHERE email = 'newaudit@example.com';

-- Example for 'balances' table
UPDATE balances SET balance = 150.00 WHERE account_id = 'your-actual-account-id-here' AND currency = 'USD';

-- Example for 'transactions' table
UPDATE transactions SET status = 'audited_complete' WHERE description = 'Audit test deposit';
```

**Verification:**
```sql
SELECT audit_id, schema_name, table_name, user_name, action, original_data, changed_data, query
FROM ledger_audit_log
WHERE table_name IN ('accounts', 'balances', 'transactions')
  AND action = 'UPDATE'
ORDER BY action_timestamp DESC LIMIT 3;

-- Expected: For each UPDATE, an audit log entry where:
-- - action = 'UPDATE'.
-- - original_data contains the JSONB representation of the row *before* the update.
-- - changed_data contains the JSONB representation of the row *after* the update.
```

### c. Verify DELETE Logging

**Action:**
```sql
-- Example for 'transactions' table (safer to delete transactions than accounts/balances for a quick test)
DELETE FROM transactions WHERE description = 'Audit test deposit';
```
**Caution:** Deleting from `accounts` or `balances` will also trigger their respective history table mechanisms.

**Verification:**
```sql
SELECT audit_id, schema_name, table_name, user_name, action, original_data, changed_data, query
FROM ledger_audit_log
WHERE table_name = 'transactions' AND action = 'DELETE'
ORDER BY action_timestamp DESC LIMIT 1;

-- Expected: For the DELETE, an audit log entry where:
-- - action = 'DELETE'.
-- - original_data contains the JSONB representation of the deleted row.
-- - changed_data IS NULL.
```

## 2. Temporal Table (System Versioning) Verification

System versioning is implemented for `accounts` and `balances` tables, with history stored in `accounts_history` and `balances_history`.

### a. Verify `accounts` Table Versioning

**Initial State:**
Assume an account exists. If not, create one:
```sql
INSERT INTO accounts (account_holder_name, email, hashed_password, status, created_at)
VALUES ('Version Test User', 'version@example.com', 'initial_hash', 'active', NOW())
RETURNING account_id, sys_period_start;
-- Note the account_id and initial sys_period_start. Let's call it 'version_test_account_id'.
```

**Action 1: UPDATE the account**
```sql
-- Wait a little to ensure transaction_timestamp() will be different
-- In psql, you can use \watch 1 or similar, or just execute sequentially.

UPDATE accounts
SET status = 'suspended', account_holder_name = 'Version Test User (Suspended)'
WHERE email = 'version@example.com';
```

**Verification 1:**
```sql
-- Check the current 'accounts' table
SELECT account_id, status, account_holder_name, sys_period_start
FROM accounts WHERE email = 'version@example.com';
-- Expected: Status is 'suspended', name is updated, sys_period_start is a NEW timestamp (more recent).

-- Check 'accounts_history' table
SELECT account_id, status, account_holder_name, sys_period_start, sys_period_end
FROM accounts_history
WHERE account_id = (SELECT account_id FROM accounts WHERE email = 'version@example.com')
ORDER BY sys_period_end DESC;
-- Expected: One row in history containing the *previous* state ('active', original name).
-- Its sys_period_start should be the initial sys_period_start.
-- Its sys_period_end should match the sys_period_start of the *new* current version in 'accounts'.
```

**Action 2: Another UPDATE**
```sql
UPDATE accounts
SET status = 'active', account_holder_name = 'Version Test User (Reactivated)'
WHERE email = 'version@example.com';
```

**Verification 2:**
```sql
SELECT account_id, status, account_holder_name, sys_period_start
FROM accounts WHERE email = 'version@example.com';
-- Expected: Status is 'active', name updated, sys_period_start is updated again.

SELECT account_id, status, account_holder_name, sys_period_start, sys_period_end
FROM accounts_history
WHERE account_id = (SELECT account_id FROM accounts WHERE email = 'version@example.com')
ORDER BY sys_period_end DESC;
-- Expected: Two rows in history now. The latest history row is the 'suspended' state.
```

**Action 3: DELETE the account**
```sql
DELETE FROM accounts WHERE email = 'version@example.com';
```

**Verification 3:**
```sql
SELECT * FROM accounts WHERE email = 'version@example.com';
-- Expected: 0 rows (account is deleted from current table).

SELECT account_id, status, account_holder_name, sys_period_start, sys_period_end
FROM accounts_history
WHERE account_id = 'version_test_account_id' -- Use the actual ID noted earlier
ORDER BY sys_period_end DESC;
-- Expected: Three rows in history. The latest one is the 'active' (Reactivated) state,
-- with its sys_period_end set to the timestamp of the DELETE operation.
```

### b. Verify `balances` Table Versioning
(Similar steps as for `accounts`: INSERT a balance, UPDATE it multiple times, DELETE it, and check `balances_history` and `balances` table at each step.)

### c. Point-in-Time Query (Conceptual)

To reconstruct the state of an account at a specific point in time (`target_timestamp`):
```sql
-- For 'version_test_account_id' and a 'target_timestamp'
SELECT *
FROM accounts
WHERE account_id = 'version_test_account_id'
  AND sys_period_start <= target_timestamp
UNION ALL
SELECT *
FROM accounts_history
WHERE account_id = 'version_test_account_id'
  AND sys_period_start <= target_timestamp
  AND sys_period_end > target_timestamp
ORDER BY sys_period_start DESC LIMIT 1; -- Might need adjustment based on exact temporal query needs.

-- A more standard way for transaction-time tables (as implemented):
-- To find the version of the row that was current at target_timestamp:
SELECT * FROM accounts_history
WHERE account_id = 'version_test_account_id'
  AND sys_period_start <= target_timestamp
  AND sys_period_end > target_timestamp
UNION ALL
SELECT * FROM accounts -- Check current version if target_timestamp is after its sys_period_start
WHERE account_id = 'version_test_account_id'
  AND sys_period_start <= target_timestamp
  -- AND (SELECT sys_period_end FROM accounts_history WHERE account_id = 'version_test_account_id' ORDER BY sys_period_end DESC LIMIT 1) <= target_timestamp -- This logic is tricky.
  -- Simpler: if not found in history, and current version's sys_period_start <= target_timestamp, it's the current one.
ORDER BY sys_period_start DESC; -- This will give you all versions up to that point, the latest one is the one current.

-- PostgreSQL 13+ has built-in support for `FOR SYSTEM_TIME AS OF target_timestamp` if table defined with `WITH SYSTEM VERSIONING`,
-- but our manual implementation requires manual querying like above.
```
The query for point-in-time reconstruction needs to be carefully crafted. The goal is to find the row version where `target_timestamp` is between `sys_period_start` and `sys_period_end` (for historical versions) or `target_timestamp` is after `sys_period_start` (for the current version).

## 3. Role-Based Access Control (RBAC) Verification

This requires creating test users and assigning them the defined roles. Then, connect as these users (or use `SET ROLE`) and attempt operations.

**Setup:**
(As a superuser or user with role creation/grant privileges)
```sql
-- Create test users (if they don't exist)
CREATE USER test_reader WITH PASSWORD 'readerpass';
CREATE USER test_writer WITH PASSWORD 'writerpass';
-- The application user (e.g., 'your_app_db_user') should already exist and be granted 'ledger_admin_service_role'.

-- Grant roles to test users
GRANT ledger_reader_role TO test_reader;
GRANT ledger_writer_role TO test_writer;
```

**Verification Steps (execute these by connecting as the respective user or using `SET ROLE`):**

### a. Test `ledger_reader_role` (e.g., as `test_reader`)

Connect to psql as `test_reader` or use `SET ROLE ledger_reader_role;` in a session started by a user who can impersonate.

**Allowed Operations:**
```sql
SELECT * FROM accounts LIMIT 1;
SELECT * FROM balances LIMIT 1;
SELECT * FROM transactions LIMIT 1;
SELECT * FROM serial_boxes LIMIT 1;
SELECT * FROM ledger_audit_log LIMIT 1;
SELECT * FROM accounts_history LIMIT 1;
SELECT * FROM balances_history LIMIT 1;
-- Expected: All SELECT queries should succeed.
```

**Disallowed Operations:**
```sql
INSERT INTO transactions (receiver_account_id, amount, currency, transaction_type, description, status)
VALUES ('some-uuid-account-id', 10.00, 'USD', 'test', 'Reader test', 'denied');
-- Expected: ERROR: permission denied for table transactions

UPDATE accounts SET status = 'test_update' WHERE email = 'audit@example.com';
-- Expected: ERROR: permission denied for table accounts

DELETE FROM transactions WHERE transaction_id = 'some-uuid-tx-id';
-- Expected: ERROR: permission denied for table transactions
```

### b. Test `ledger_writer_role` (e.g., as `test_writer`)

Connect as `test_writer` or use `SET ROLE ledger_writer_role;`.

**Allowed Operations:**
```sql
SELECT * FROM accounts LIMIT 1; -- Should be allowed (inherited or directly granted)

INSERT INTO transactions (receiver_account_id, amount, currency, transaction_type, description, status)
VALUES ('your-actual-account-id-here', 20.00, 'CAD', 'deposit', 'Writer test', 'pending_writer') RETURNING transaction_id;
-- Expected: Should succeed. Note the transaction_id.

UPDATE transactions SET status = 'writer_updated' WHERE description = 'Writer test';
-- Expected: Should succeed.

SELECT * FROM serial_boxes LIMIT 1; -- Should be allowed
-- INSERT/UPDATE on serial_boxes should also be allowed per grants.
```

**Disallowed Operations:**
```sql
UPDATE accounts SET status = 'writer_update_accounts' WHERE email = 'audit@example.com';
-- Expected: ERROR: permission denied for table accounts (writer role doesn't have UPDATE on accounts)

DELETE FROM transactions WHERE description = 'Writer test';
-- Expected: ERROR: permission denied for table transactions (writer role doesn't have DELETE)

INSERT INTO accounts (account_holder_name, email, hashed_password, status)
VALUES ('Writer Insert Acc', 'writeracc@example.com', 'hash', 'active');
-- Expected: ERROR: permission denied for table accounts
```

### c. Test `ledger_admin_service_role`
This role is intended for the application. If you have `your_app_db_user` granted this role, connect as that user.
This role should be able to perform all operations defined in its grants (SELECT, INSERT, UPDATE, DELETE on `accounts`, `balances`, `transactions`, `serial_boxes`, and those inherited from reader/writer).

```sql
-- Example as your_app_db_user (who has ledger_admin_service_role)
UPDATE accounts SET status = 'admin_service_update' WHERE email = 'audit@example.com';
-- Expected: Success

DELETE FROM transactions WHERE description = 'Writer test'; -- Assuming this was created by writer test
-- Expected: Success
```

**Cleanup (Optional):**
(As a superuser)
```sql
-- REVOKE ledger_reader_role FROM test_reader;
-- REVOKE ledger_writer_role FROM test_writer;
-- DROP USER test_reader;
-- DROP USER test_writer;
```

## 4. Transaction Chaining Verification

The integrity of the transaction chain (`previous_transaction_hash` and `current_transaction_hash` in the `transactions` table) is best verified using the dedicated script:

```bash
# From the project root directory
python scripts/verify_chain_integrity.py
```
Refer to the output of this script. It will report any mismatches in calculated vs. stored hashes or broken links in the chain.

---
This guide should help in manually verifying the advanced database features. For regular testing, these checks should be automated within a database testing framework.
