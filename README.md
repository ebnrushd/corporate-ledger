# Ledger and Visa Top-Up Integration System

## Project Overview

This project is a prototype system demonstrating the integration of a local ledger, a smart contract for Visa top-up operations, and an API service that orchestrates interactions between them. It includes placeholder modules for ERP integration and Visa API client interactions, along with a basic frontend UI for initiating top-ups and viewing transaction history. The primary goal is to showcase a potential architecture for managing financial transactions with on-chain components.

**Disclaimer:** This is a prototype system and is **NOT production-ready**. It lacks many security features, comprehensive error handling, and real integrations necessary for a live environment.

## Components

The project is structured into several key components:

1.  **Database Schema (`schema.sql`)**:
    *   Defines the PostgreSQL database schema for the ledger system.
    *   Includes tables for `accounts`, `transactions`, `balances`, and `serial_boxes`.
    *   **Advanced Features Implemented:**
        *   **Transaction Chaining:** The `transactions` table includes `previous_transaction_hash` and `current_transaction_hash` columns to create a verifiable chain of transactions, enhancing data integrity and auditability. The `ledger_processing/data_processor.py` module implements the hash calculation and linking. Integrity can be checked using `scripts/verify_chain_integrity.py`.
        *   **System Versioning (Temporal Tables):** The `accounts` and `balances` tables are system-versioned. Historical versions of rows are stored in corresponding `accounts_history` and `balances_history` tables, using `sys_period_start` and `sys_period_end` columns to track the validity period of each version. This allows for point-in-time queries and auditing of state changes over time.
        *   **Audit Logging:** A generic audit logging mechanism is in place. The `ledger_audit_log` table stores a record of all `INSERT`, `UPDATE`, and `DELETE` operations performed on the `accounts`, `balances`, and `transactions` tables, captured by the `log_ledger_changes()` trigger function.
        *   **Role-Based Access Control (RBAC):** Defines database roles (`ledger_reader_role`, `ledger_writer_role`, `ledger_admin_service_role`) to manage permissions according to the principle of least privilege.

2.  **Ledger Processing (`ledger_processing/`)**:
    *   `data_processor.py`: Contains Python modules for processing (simulated) encrypted bank raw data. This includes decryption, validation, parsing, and storing data into the PostgreSQL database, including the calculation and storage of transaction hashes for chaining.
    *   `erp_connector.py`: A placeholder module that **simulates a generic REST API client** for potential ERP (e.g., Oracle) integration. It uses the `requests` library for making simulated HTTP calls and includes placeholders for an API base URL, token-based authentication, and example endpoints for syncing transactions, fetching account balances, and reconciliation. The actual API endpoints, data formats, and authentication mechanisms would need to be configured based on the specific ERP system.
    *   `requirements.txt`: Specifies Python libraries for this component, including `psycopg2-binary`, `cryptography`, and `requests`.

3.  **Smart Contracts (`smart_contracts/`)**:
    *   `VisaTopUp.sol`: A Solidity smart contract for initiating and confirming Visa top-up requests on an Ethereum-compatible blockchain. It uses events to communicate with off-chain services.

4.  **Integration Service (`integration_service/`)**:
    *   `app.py`: A Flask-based API service that acts as the central hub.
        *   Exposes endpoints for initiating top-ups, receiving (simulated) Visa confirmations, and viewing transactions.
        *   Interacts with the PostgreSQL ledger database.
        *   Interacts with the `VisaTopUp.sol` smart contract via Web3.py.
    *   `visa_api_client.py`: A placeholder client for simulating interactions with a Visa API for card top-ups.
    *   `.env_example`: Template for environment variables required by the service.
    *   `requirements.txt`: Specifies Python libraries for this API service.

5.  **Frontend (UI) (`frontend/`)**:
    *   `login.html`: A placeholder login page (simulated login).
    *   `initiate_topup.html`: A basic HTML form to initiate a Visa top-up via the integration service.
    *   `transaction_history.html`: A basic HTML page to display transaction history fetched from the integration service.
    *   `scripts/main.js`: JavaScript to handle form submissions, API calls to the integration service, and dynamic content updates on the frontend pages.

6.  **Documentation (`docs/`)**:
    *   `TABLE_PARTITIONING_PLAN.md`: An investigation and plan for implementing table partitioning on high-volume tables.

7.  **Scripts (`scripts/`)**:
    *   `deploy_visa_top_up.py`: A Python script using Web3.py to deploy the `VisaTopUp.sol` smart contract.
    *   `interact_visa_top_up.py`: A Python script to interact with the deployed smart contract.
    *   `verify_chain_integrity.py`: A Python script to verify the integrity of the transaction chain in the `transactions` table.
    *   `deployment_info.json` (generated by `deploy_visa_top_up.py`): Stores the deployed contract address and ABI.

8.  **Tests (`tests/`)**:
    *   `tests/ledger_processing/test_data_processor.py`: Unit tests for the `data_processor.py` module.
    *   `tests/VERIFICATION_GUIDE_ADVANCED_DB.md`: A Markdown document providing SQL examples and conceptual steps for manually verifying advanced database features like audit logs, temporal tables, RBAC, and transaction chaining.

## Setup and Installation Instructions

### Prerequisites

*   **Python:** Version 3.8+
*   **PostgreSQL:** Version 12+ (due to features like system versioning and advanced trigger logic if fully implemented).
*   **Solidity Compiler (`solc`):** Required by `py-solc-x`. Version `^0.8.18` is used.
*   **Ethereum Node:** Ganache (recommended for local testing) or other.
*   **Git.**

### 1. Clone the Repository
```bash
git clone <repository_url>
cd <repository_name>
```

### 2. Python Environment Setup
```bash
python3 -m venv venv
source venv/bin/activate  # On macOS/Linux
# venv\Scripts\activate  # On Windows

# Install project-wide Python dependencies (if a root requirements.txt is provided and maintained)
# pip install -r requirements.txt

# Alternatively, install dependencies for each component as needed:
pip install -r ledger_processing/requirements.txt
pip install -r integration_service/requirements.txt
pip install web3 py-solc-x # For scripts, if not covered by above
```
*Note: This project uses component-specific `requirements.txt` files. Ensure all necessary packages like `Flask`, `psycopg2-binary`, `Web3py`, `python-dotenv`, `cryptography`, `requests`, and `py-solc-x` are installed based on the components you intend to use.*

### 3. Database Setup

1.  **Ensure PostgreSQL server is running.**
2.  **Create Database and User:**
    *   Connect to PostgreSQL as a superuser (e.g., `postgres`).
    *   Create a dedicated user and database for the application.
    ```sql
    -- Example psql commands:
    CREATE USER your_app_db_user WITH PASSWORD 'your_secure_password';
    CREATE DATABASE ledger_db OWNER your_app_db_user;
    -- Optional: If your app user is not a superuser, grant connect explicitly (usually default for public)
    -- GRANT CONNECT ON DATABASE ledger_db TO your_app_db_user;
    ```
3.  **Apply Schema:**
    *   Connect to the `ledger_db` as the database owner (`your_app_db_user` or a superuser).
    *   Run the `schema.sql` script. This script creates tables, functions, triggers, and roles.
    ```bash
    psql -U your_app_db_user -d ledger_db -h localhost -f schema.sql
    ```
    You might be prompted for the password.

#### 3.1. Database Security and Roles (RBAC)

The `schema.sql` script implements a basic Role-Based Access Control (RBAC) strategy based on the principle of least privilege. This is crucial for database security.

*   **Defined Roles:**
    *   `ledger_reader_role`: For read-only access to all ledger data tables, including history and audit logs.
    *   `ledger_writer_role`: For limited write access, primarily for processes that record new operational data like transactions or serial box updates, but do not manage accounts or balances directly. Includes necessary read access.
    *   `ledger_admin_service_role`: A comprehensive role intended for the main `integration_service`. It inherits privileges from reader/writer roles and has broader DML permissions (SELECT, INSERT, UPDATE, DELETE) on core operational tables.
*   **Granting Roles to Application User:**
    After the schema is applied, the database user that the `integration_service` will use to connect to the database (configured in its `.env` file, e.g., `your_app_db_user`) **must be granted the `ledger_admin_service_role`**. This is done by a PostgreSQL superuser or a user with grant permissions:
    ```sql
    -- Connect to PostgreSQL as a superuser
    GRANT ledger_admin_service_role TO your_app_db_user;
    ```
*   **Default Privileges:**
    The `schema.sql` file includes commented-out examples of `ALTER DEFAULT PRIVILEGES`. It's good practice for the schema owner (the user running migrations or creating the initial schema) to set default privileges. This ensures that roles like `ledger_reader_role` automatically get `SELECT` permissions on new tables created by the schema owner in the future, reducing manual `GRANT` statements later. This requires knowing the schema owner's username. Example:
    ```sql
    -- Assuming 'your_app_db_user' owns and creates schema objects:
    -- ALTER DEFAULT PRIVILEGES FOR ROLE your_app_db_user IN SCHEMA public GRANT SELECT ON TABLES TO ledger_reader_role;
    -- ALTER DEFAULT PRIVILEGES FOR ROLE your_app_db_user IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO ledger_writer_role;
    -- ALTER DEFAULT PRIVILEGES FOR ROLE your_app_db_user IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO ledger_admin_service_role;
    ```

### 4. Smart Contract Deployment
*(Instructions as before)*
...

### 5. Integration Service Setup
*(Instructions as before, ensuring `DB_USER` in `.env` is `your_app_db_user` which was granted `ledger_admin_service_role`)*
...

### 6. Frontend UI
*(Instructions as before)*
...

## Running the Application (General Flow)
*(Instructions as before)*
...

## Running Tests and Verifications

### Unit Tests
Unit tests are provided for the `ledger_processing` module.
1.  Ensure your Python virtual environment is active and dependencies from `ledger_processing/requirements.txt` are installed.
2.  From the **project root directory**:
    ```bash
    python -m unittest discover -s tests -p "test_*.py"
    ```
    Or, to run a specific test file:
    ```bash
    python tests/ledger_processing/test_data_processor.py
    ```

### Advanced Database Feature Verification
A guide for manually verifying advanced database features (Transaction Chaining, Audit Logs, System Versioning, RBAC) is available:
*   **`tests/VERIFICATION_GUIDE_ADVANCED_DB.md`**: Contains SQL examples and conceptual steps for these verifications.
*   **Transaction Chaining Script:** For a specific check on transaction chain integrity:
    ```bash
    python scripts/verify_chain_integrity.py
    ```

## Key Configuration Points
*(Instructions as before, ensure `DB_USER` in `integration_service/.env` is highlighted as the one needing `ledger_admin_service_role`)*
...

## Security Notes
*   **Prototype System:** (As before)
*   **Key Management:** (As before)
*   **API Security:** (As before)
*   **Database Security:**
    *   Use strong, unique passwords for the database user (`your_app_db_user`).
    *   The RBAC roles (`ledger_reader_role`, `ledger_writer_role`, `ledger_admin_service_role`) are defined to limit application permissions. Ensure the application connects with a user granted only the necessary role (typically `ledger_admin_service_role`).
    *   The advanced features like audit logging and system versioning contribute to data integrity and traceability but must be complemented with robust access controls.
    *   Consider network restrictions for database access.
*   **Smart Contract Security:** (As before)
*   **PCI DSS:** (As before)
*   **Error Handling:** (As before)
*   **Dependency Management:** (As before)

## Future Enhancements / Roadmap
*(Instructions as before)*
...

---

This README aims to provide a comprehensive starting point for understanding and working with this project.
Remember to replace placeholder values and exercise caution with sensitive information like private keys.
