# Table Partitioning Investigation and Plan

## 1. Introduction

### Purpose of Partitioning

As the ledger system grows, certain tables are expected to accumulate a large volume of data. Table partitioning is a database design technique that involves dividing large tables into smaller, more manageable pieces called partitions, while still allowing the table to be queried as a single entity. The primary benefits of partitioning for this system would be:

*   **Improved Query Performance:** Queries that access only a subset of the data (e.g., transactions within a specific date range) can benefit from partition pruning, where the database query planner only scans the relevant partitions instead of the entire table.
*   **Enhanced Manageability:** Maintenance operations such as backups, index rebuilding, and data archiving/purging can be performed on individual partitions, reducing the impact on the overall system and often completing faster.
*   **Data Lifecycle Management:** Older data can be easily archived or dropped by detaching or dropping entire partitions, which is much more efficient than large-scale DELETE operations.

### Disclaimer

This document outlines an initial investigation and plan for implementing table partitioning. The actual implementation requires careful planning, thorough testing in a staging environment, consideration of data migration strategies for existing data, and a robust backup and rollback plan. The DDL examples provided are illustrative and may need adjustments based on the specific PostgreSQL version and further detailed analysis.

## 2. Candidate Tables for Partitioning

Based on expected data growth and access patterns, the following tables are primary candidates for partitioning:

1.  **`transactions`**: This table is expected to grow indefinitely as new transactions are recorded. Queries are often time-based (e.g., transactions for a specific month).
2.  **`ledger_audit_log`**: Audit logs can grow very large over time. Access is often based on the `action_timestamp`.
3.  **`accounts_history`**: Stores historical versions of account data. As accounts are updated, this table will grow. Queries might involve looking at changes within certain periods.
4.  **`balances_history`**: Stores historical versions of balance data. Similar to `accounts_history`, this will grow with updates to balances.

## 3. Proposed Strategy for `transactions` Table

*   **Partitioning Method:** Range Partitioning.
*   **Partition Key:** `created_at` (TIMESTAMPTZ). This is a natural key for time-series data and aligns with common query patterns.
*   **Proposed Partition Scheme:** Monthly partitions. This provides a good balance between the number of partitions and the size of each partition.
    *   Example partition names: `transactions_y2023m01`, `transactions_y2023m02`, etc.

*   **Example DDL for Redefining `transactions` (Illustrative):**

    ```sql
    -- Note: This requires migrating existing data and careful handling of constraints and indexes.
    -- The original 'transactions' table would be renamed or dropped and recreated as a partitioned table.

    -- 1. Create the partitioned (parent) table
    CREATE TABLE transactions (
        transaction_id UUID NOT NULL, -- No longer PRIMARY KEY directly on parent
        sender_account_id UUID REFERENCES accounts(account_id),
        receiver_account_id UUID REFERENCES accounts(account_id),
        amount DECIMAL(18, 2) NOT NULL,
        currency VARCHAR(3) NOT NULL,
        transaction_type VARCHAR(50) NOT NULL,
        description TEXT,
        status VARCHAR(50) DEFAULT 'pending',
        created_at TIMESTAMP WITH TIME ZONE NOT NULL, -- Partition key, must be NOT NULL
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT transaction_timestamp(),
        previous_transaction_hash TEXT DEFAULT NULL,
        current_transaction_hash TEXT, -- Uniqueness needs to be handled per partition or globally with partition key
        CONSTRAINT chk_amount CHECK (amount > 0)
    ) PARTITION BY RANGE (created_at);

    COMMENT ON TABLE transactions IS 'Stores all financial transactions; partitioned by created_at range (monthly).';

    -- 2. Create a partition for a specific month (example)
    CREATE TABLE transactions_y2023m01 PARTITION OF transactions
        FOR VALUES FROM ('2023-01-01 00:00:00+00') TO ('2023-02-01 00:00:00+00');

    -- Create another partition
    CREATE TABLE transactions_y2023m02 PARTITION OF transactions
        FOR VALUES FROM ('2023-02-01 00:00:00+00') TO ('2023-03-01 00:00:00+00');

    -- (Repeat for other months as needed, and automate creation for future months)
    ```

*   **Constraint Considerations:**
    *   **Primary Key:** The `transaction_id UUID PRIMARY KEY` constraint on the original table needs to be adapted. In PostgreSQL, a primary key on a partitioned table *must* include all partitioning columns.
        *   Option 1 (Recommended): Make `(transaction_id, created_at)` the primary key for the partitioned `transactions` table. This ensures global uniqueness across partitions for `transaction_id` if `created_at` is also considered. Individual partitions will inherit this PK.
        *   Option 2: Define `transaction_id` as `PRIMARY KEY` on each partition individually. This allows `transaction_id` to be unique *within* a partition but not necessarily globally (unless the application ensures UUIDs are globally unique, which they should be). The parent table would not have a PK in this case, only individual partitions. This is generally less preferred.
    *   **Unique Constraints:** Similarly, `current_transaction_hash TEXT UNIQUE` must also include the partition key if it's to be a unique constraint on the parent table: `UNIQUE (current_transaction_hash, created_at)`. If `current_transaction_hash` needs to be globally unique by itself, partitioning makes this harder directly. Application-level checks or alternative methods might be needed, or uniqueness can be enforced per partition.
    *   **Indexes:** Indexes (like `idx_transactions_status`, `idx_transactions_previous_hash`) should generally be created on the parent partitioned table, and they will be automatically created on each partition. The partition key column (`created_at`) is automatically indexed.

## 4. Proposed Strategy for `ledger_audit_log` Table

*   **Partitioning Method:** Range Partitioning.
*   **Partition Key:** `action_timestamp` (TIMESTAMPTZ).
*   **Proposed Partition Scheme:** Monthly partitions.
    *   Example partition names: `ledger_audit_log_y2023m01`, `ledger_audit_log_y2023m02`, etc.
*   **Example DDL Snippet (Parent Table):**
    ```sql
    CREATE TABLE ledger_audit_log (
        audit_id BIGINT NOT NULL, -- No longer BIGSERIAL directly on parent
        schema_name TEXT NOT NULL,
        table_name TEXT NOT NULL,
        user_name TEXT,
        action_timestamp TIMESTAMPTZ NOT NULL DEFAULT transaction_timestamp(), -- Partition key
        action TEXT NOT NULL CHECK (action IN ('INSERT', 'UPDATE', 'DELETE', 'TRUNCATE')),
        original_data JSONB,
        changed_data JSONB,
        query TEXT
    ) PARTITION BY RANGE (action_timestamp);

    -- Partitions would be created similarly to the transactions example.
    -- CREATE TABLE ledger_audit_log_y2023m01 PARTITION OF ledger_audit_log
    --     FOR VALUES FROM ('2023-01-01 00:00:00+00') TO ('2023-02-01 00:00:00+00');
    ```
*   **Constraint Considerations:**
    *   **Primary Key (`audit_id BIGSERIAL PRIMARY KEY`):**
        *   The `BIGSERIAL` behavior (auto-incrementing sequence) needs careful handling.
        *   Option 1: Define `(audit_id, action_timestamp)` as the primary key on the parent. The sequence for `audit_id` would still be global. Each partition would inherit this PK.
        *   Option 2: Do not use `BIGSERIAL` on the parent. Instead, manage `audit_id` generation (perhaps still from a single sequence) and set it explicitly during insert, then define `PRIMARY KEY (audit_id, action_timestamp)` on the parent.
        *   Option 3 (Common for partitions): Define the PK on each partition: `PRIMARY KEY (audit_id)`. The `audit_id` values would still come from a single shared sequence, ensuring global uniqueness. The parent table would not have a PK.
        *   For `BIGSERIAL`-like behavior with partitioning, it's often simpler to use a default value from a sequence (e.g., `audit_id BIGINT NOT NULL DEFAULT nextval('ledger_audit_log_audit_id_seq')`) and then include `action_timestamp` in the PK on the parent: `PRIMARY KEY (audit_id, action_timestamp)`. The sequence `ledger_audit_log_audit_id_seq` would need to be created explicitly.

## 5. Proposed Strategy for History Tables (`accounts_history`, `balances_history`)

These tables store historical versions of rows and are good candidates for partitioning as they grow over time.

*   **Partitioning Method:** Range Partitioning.
*   **Partition Key:** `sys_period_end` (TIMESTAMPTZ). This column indicates when a version ceased to be the current one, effectively marking the end of its validity. Partitioning by this key allows for easy management of older historical data.
*   **Proposed Partition Scheme:** Quarterly or Yearly, depending on the rate of changes. For example, if changes are frequent, quarterly might be better. If less frequent, yearly could suffice.
    *   Example partition names: `accounts_history_y2023q1`, `balances_history_y2023_ended`.

*   **Example DDL Snippet (Parent Table `accounts_history`):**
    ```sql
    CREATE TABLE accounts_history (
        account_id UUID NOT NULL,
        account_holder_name VARCHAR(255) NOT NULL,
        email VARCHAR(255) NOT NULL,
        hashed_password VARCHAR(255) NOT NULL,
        status VARCHAR(50),
        created_at TIMESTAMP WITH TIME ZONE,
        sys_period_start TIMESTAMPTZ NOT NULL,
        sys_period_end TIMESTAMPTZ NOT NULL -- Partition key
    ) PARTITION BY RANGE (sys_period_end);

    -- Partitions example (quarterly):
    -- CREATE TABLE accounts_history_y2023q1 PARTITION OF accounts_history
    --    FOR VALUES FROM ('2023-01-01 00:00:00+00') TO ('2023-04-01 00:00:00+00');
    ```
*   **Constraint Considerations:**
    *   History tables typically do not have primary keys in the same way their parent "current" tables do, as they store multiple versions for the same entity.
    *   Indexes on `account_id`, `sys_period_start`, and `sys_period_end` (the partition key) are important for querying specific historical records or ranges.

## 6. Impact Analysis

*   **Data Insertion:**
    *   For partitioned tables, PostgreSQL automatically routes rows to the correct partition based on the partition key value. This is largely transparent to the application performing `INSERT` statements, provided the partition for the given key value exists.
    *   If a row's partition key value does not fall into any existing partition's range, the `INSERT` will fail. This necessitates proactive creation of future partitions.
*   **Data Queries:**
    *   **Benefits:** Queries that include a filter on the partition key (e.g., `WHERE created_at >= '2023-01-01' AND created_at < '2023-02-01'`) can benefit significantly from "partition pruning." The query planner will only scan the relevant partition(s), leading to faster query execution on large datasets.
    *   **Potential Issues:** Queries that do not filter by the partition key will have to scan all (or multiple) partitions, which might not show performance improvement or could even be slightly slower due to the overhead of managing partitions if not planned well. Global unique constraints (not including the partition key) are not directly enforceable on the parent table, which might require application-level logic or careful design.
*   **Foreign Keys:**
    *   Foreign key constraints referencing a partitioned table are possible but have limitations. Typically, a foreign key from another table can reference the parent partitioned table.
    *   Foreign keys from a partitioned table to another table (partitioned or not) are also possible.
    *   Care must be taken during partition maintenance (e.g., `DETACH` operations) if foreign keys are involved.
*   **Application Code:**
    *   Basic `INSERT`, `SELECT`, `UPDATE`, `DELETE` statements should largely remain unchanged, as the partitioned table is addressed by its parent name.
    *   The application needs to be aware of the partition key and potentially use it in `WHERE` clauses to gain performance benefits.
    *   Error handling for inserts might need to account for failures due to missing partitions if partition creation is not perfectly managed.

## 7. Maintenance

*   **Automated Creation of New Partitions:**
    *   New partitions for future ranges (e.g., the next month/quarter/year) must be created proactively. This typically requires a scheduled script (e.g., using cron and psql, or a database job scheduler if available like pg_cron) that runs periodically to create upcoming partitions.
    *   Failure to create a needed partition will result in errors when inserting data that falls into that range.
*   **Archiving or Dropping Old Partitions:**
    *   One of the main benefits of partitioning is the ability to manage old data efficiently.
    *   **Detaching a partition:** `ALTER TABLE parent_table DETACH PARTITION partition_name;` This makes the partition a standalone table, which can then be archived, backed up, or dropped. This is very fast compared to `DELETE`ing rows.
    *   **Dropping a partition:** `DROP TABLE partition_name;` (after detaching, or directly if allowed and desired).
    *   This process also needs to be scripted and scheduled as part of data lifecycle management.

## 8. Implementation Steps (High-Level for Future)

Implementing partitioning on existing, populated tables is a significant operation.

1.  **Detailed Design and Testing:**
    *   Finalize partition keys and ranges for each table.
    *   Test DDL for creating partitioned tables and partitions in a non-production (staging) environment.
    *   Benchmark query performance with and without partitioning.
    *   Test application behavior with the partitioned table structure.
2.  **Data Migration Strategy (for existing data):**
    *   **Option A (Downtime):**
        1.  Rename the existing table (e.g., `transactions_old`).
        2.  Create the new partitioned `transactions` table structure.
        3.  Create necessary partitions.
        4.  Copy data from `transactions_old` to the new partitioned table (e.g., using `INSERT INTO transactions SELECT * FROM transactions_old;`). This can be slow for large tables.
        5.  Recreate indexes, constraints, and triggers on the new partitioned table.
        6.  Drop `transactions_old` after verification.
    *   **Option B (Minimal Downtime - More Complex):**
        1.  Create the new partitioned table structure alongside the existing table.
        2.  Set up triggers on the existing table to copy new/updated/deleted rows to the new partitioned table (and potentially a temporary staging area).
        3.  Bulk copy existing historical data into the appropriate partitions of the new table. This can be done in chunks.
        4.  Once in sync, perform a carefully managed switch where the application starts writing to the new partitioned table. This often involves a short downtime window or read-only period.
    *   Tools like `pg_partman` can help manage partition creation and data migration for some scenarios but require careful setup.
3.  **Backup and Rollback Plan:**
    *   Ensure full database backups are taken before starting the partitioning process.
    *   Have a clear rollback plan in case issues arise during migration.
4.  **Develop and Test Maintenance Scripts:**
    *   Scripts for creating new partitions.
    *   Scripts for archiving/dropping old partitions.
5.  **Monitoring:**
    *   Monitor database performance (query times, disk I/O, storage) and application behavior closely after implementation.
    *   Monitor the partition creation process to ensure it runs correctly.

This plan provides a foundational strategy. Each step, especially data migration, needs to be meticulously planned and tested.
