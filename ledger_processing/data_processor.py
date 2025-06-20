import json
import logging
import psycopg2
from cryptography.fernet import Fernet
import os # For generating fernet key, will be replaced by proper key management
import hashlib
from datetime import datetime, timezone

# Configure basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Database Connection (Placeholders) ---
DB_HOST = "your_db_host"
DB_NAME = "ledger_db"
DB_USER = "ledger_user"
DB_PASSWORD = "ledger_password"
DB_PORT = "5432"

# --- Encryption (Placeholder) ---
FERNET_KEY_FILE = "secret.key"

def generate_or_load_fernet_key():
    if os.path.exists(FERNET_KEY_FILE):
        with open(FERNET_KEY_FILE, "rb") as key_file:
            key = key_file.read()
        logging.info(f"Loaded Fernet key from {FERNET_KEY_FILE}")
    else:
        key = Fernet.generate_key()
        with open(FERNET_KEY_FILE, "wb") as key_file:
            key_file.write(key)
        logging.info(f"Generated and saved new Fernet key to {FERNET_KEY_FILE}")
    return key

ENCRYPTION_KEY = generate_or_load_fernet_key()
cipher_suite = Fernet(ENCRYPTION_KEY)

def get_db_connection():
    try:
        conn = psycopg2.connect(
            host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD, port=DB_PORT
        )
        logging.info("Database connection established.")
        return conn
    except psycopg2.Error as e:
        logging.error(f"Error connecting to database: {e}")
        raise

def decrypt_data(encrypted_data_str: str) -> dict | None:
    try:
        decrypted_bytes = cipher_suite.decrypt(encrypted_data_str.encode('utf-8'))
        decrypted_json_str = decrypted_bytes.decode('utf-8')
        data = json.loads(decrypted_json_str)
        logging.info("Data decrypted successfully.")
        return data
    except Exception as e:
        logging.error(f"Decryption failed: {e}")
        return None

def validate_data(data: dict) -> bool:
    if not isinstance(data, dict):
        logging.warning("Validation failed: Data is not a dictionary.")
        return False
    required_keys = ["transaction_id_external", "amount", "currency", "timestamp", "account_holder_name", "email"]
    for key in required_keys:
        if key not in data:
            logging.warning(f"Validation failed: Missing key '{key}'.")
            return False
    if not isinstance(data["amount"], (int, float)) or data["amount"] <= 0:
        logging.warning("Validation failed: Invalid amount.")
        return False
    logging.info("Data validated successfully.")
    return True

def parse_data(data: dict) -> dict | None:
    try:
        parsed = {
            "account_holder_name": data.get("account_holder_name"),
            "email": data.get("email"),
            "transaction_details": {
                "amount": data.get("amount"),
                "currency": data.get("currency", "USD"),
                "transaction_type": data.get("transaction_type", "deposit"),
                "description": data.get("description", f"Transaction {data.get('transaction_id_external')} processed on {data.get('timestamp')}"),
                "external_id": data.get("transaction_id_external"),
                # Assuming sender_account_id is null for deposits from external, set in store_data
                "sender_account_id": None,
                # receiver_account_id will be the 'account_id' determined in store_data
            },
            "banknote_serials": data.get("banknote_serials", [])
        }
        parsed["hashed_password"] = "temporary_placeholder_hash"
        logging.info("Data parsed successfully.")
        return parsed
    except Exception as e:
        logging.error(f"Data parsing failed: {e}")
        return None

def _calculate_transaction_hash(transaction_data: dict) -> str:
    """
    Calculates a SHA256 hash for a transaction based on its key data fields.
    Ensures a canonical representation by sorting keys.
    """
    # Define the fields that contribute to the transaction's identity for hashing
    # previous_transaction_hash is crucial for chaining
    # created_at (as string) ensures timestamp is part of the hash
    # Explicitly convert amount to a fixed string format to avoid float representation issues.
    hash_payload = {
        "sender_account_id": str(transaction_data.get("sender_account_id", "")), # Ensure consistent type
        "receiver_account_id": str(transaction_data.get("receiver_account_id", "")),
        "amount": "{:.2f}".format(transaction_data.get("amount", 0.00)), # Format to 2 decimal places
        "currency": str(transaction_data.get("currency", "")),
        "transaction_type": str(transaction_data.get("transaction_type", "")),
        "description": str(transaction_data.get("description", "")),
        "status": str(transaction_data.get("status", "")), # Status at the time of hashing
        "created_at": str(transaction_data.get("created_at", "")), # ISO format string
        "previous_transaction_hash": str(transaction_data.get("previous_transaction_hash", ""))
    }

    # Create a canonical string representation by sorting keys
    canonical_string = "|".join(f"{k}:{hash_payload[k]}" for k in sorted(hash_payload.keys()))

    return hashlib.sha256(canonical_string.encode('utf-8')).hexdigest()

def store_data(parsed_data: dict):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # 1. Get or Create Account
        account_id = None # This will be the receiver_account_id for the deposit transaction
        cursor.execute("SELECT account_id FROM accounts WHERE email = %s;", (parsed_data["email"],))
        row = cursor.fetchone()
        if row:
            account_id = row[0]
            logging.info(f"Account found for email {parsed_data['email']}: {account_id}")
        else:
            cursor.execute(
                "INSERT INTO accounts (account_holder_name, email, hashed_password) VALUES (%s, %s, %s) RETURNING account_id;",
                (parsed_data["account_holder_name"], parsed_data["email"], parsed_data["hashed_password"])
            )
            account_id = cursor.fetchone()[0]
            logging.info(f"Created new account for email {parsed_data['email']}: {account_id}")
            cursor.execute(
                "INSERT INTO balances (account_id, currency, balance) VALUES (%s, %s, %s);",
                (account_id, parsed_data["transaction_details"]["currency"], 0.00)
            )
            logging.info(f"Initialized balance for account {account_id}.")

        # 2. Prepare and Store Transaction with Hashing
        tx_details = parsed_data["transaction_details"]

        # Determine created_at timestamp (Python-generated for hashing consistency)
        # This will override the DB default if provided in INSERT
        tx_created_at_utc = datetime.now(timezone.utc)
        tx_created_at_iso = tx_created_at_utc.isoformat()

        # Fetch previous transaction hash (for chaining)
        cursor.execute("SELECT current_transaction_hash FROM transactions ORDER BY created_at DESC, transaction_id DESC LIMIT 1")
        prev_hash_row = cursor.fetchone()
        previous_transaction_hash = prev_hash_row[0] if prev_hash_row else None
        logging.info(f"Previous transaction hash: {previous_transaction_hash}")

        # Data for current transaction hash calculation
        # For a deposit, sender_account_id is typically NULL (external source)
        # receiver_account_id is the 'account_id' of the user being processed.
        current_tx_data_for_hashing = {
            "sender_account_id": tx_details.get("sender_account_id"), # Should be None for this deposit case
            "receiver_account_id": account_id,
            "amount": tx_details["amount"],
            "currency": tx_details["currency"],
            "transaction_type": tx_details["transaction_type"],
            "description": tx_details["description"],
            "status": 'completed', # Assuming status is 'completed' for this data processor
            "created_at": tx_created_at_iso, # Use the Python-generated ISO string
            "previous_transaction_hash": previous_transaction_hash
        }
        current_transaction_hash = _calculate_transaction_hash(current_tx_data_for_hashing)
        logging.info(f"Calculated current transaction hash: {current_transaction_hash}")

        # Insert the transaction with hash values and Python-generated created_at
        cursor.execute(
            """
            INSERT INTO transactions (
                receiver_account_id, amount, currency, transaction_type,
                description, status, created_at,
                previous_transaction_hash, current_transaction_hash,
                sender_account_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING transaction_id;
            """,
            (
                account_id, tx_details["amount"], tx_details["currency"],
                tx_details["transaction_type"], tx_details["description"], 'completed',
                tx_created_at_utc, # Pass datetime object, psycopg2 handles conversion
                previous_transaction_hash, current_transaction_hash,
                tx_details.get("sender_account_id") # Explicitly None for typical deposits here
            )
        )
        transaction_id = cursor.fetchone()[0]
        logging.info(f"Transaction {transaction_id} stored for account {account_id} with hashes.")

        # 3. Update Balance
        cursor.execute(
            "UPDATE balances SET balance = balance + %s WHERE account_id = %s AND currency = %s;",
            (tx_details["amount"], account_id, tx_details["currency"])
        )
        logging.info(f"Balance updated for account {account_id}.")

        # 4. Store Banknote Serials
        for serial_number in parsed_data.get("banknote_serials", []):
            cursor.execute(
                "INSERT INTO serial_boxes (serial_number, assigned_account_id, status, product_id) VALUES (%s, %s, %s, %s);",
                (serial_number, account_id, 'assigned', tx_details.get("product_id", "banknote"))
            )
            logging.info(f"Stored serial number {serial_number} for account {account_id}.")

        conn.commit()
        logging.info("All data stored successfully and transaction committed.")

    except psycopg2.Error as e:
        if conn: conn.rollback()
        logging.error(f"Database error during data storage: {e}", exc_info=True)
    except Exception as e:
        if conn: conn.rollback()
        logging.error(f"An unexpected error occurred during data storage: {e}", exc_info=True)
    finally:
        if conn:
            if 'cursor' in locals() and cursor: # Check if cursor was defined
                 cursor.close()
            conn.close()
            logging.info("Database connection closed.")

def process_bank_data_file_entry(encrypted_entry_str: str):
    logging.info("Starting processing of a new bank data entry.")
    decrypted_content = decrypt_data(encrypted_entry_str)
    if not decrypted_content:
        logging.error("Halting processing for entry due to decryption failure.")
        return

    if not validate_data(decrypted_content):
        logging.error("Halting processing for entry due to validation failure.")
        return

    parsed_content = parse_data(decrypted_content)
    if not parsed_content:
        logging.error("Halting processing for entry due to parsing failure.")
        return

    store_data(parsed_content)
    logging.info("Successfully processed bank data entry.")


if __name__ == '__main__':
    sample_raw_data = {
        "transaction_id_external": "TXN_HASH_TEST_001",
        "amount": 77.77,
        "currency": "USD",
        "timestamp": "2023-11-01T12:00:00Z",
        "account_holder_name": "Hash User",
        "email": "hash.user@example.com",
        "description": "Test transaction for hashing logic.",
        "banknote_serials": ["SN_HASH001"],
        "transaction_type": "deposit"
    }
    json_string_data = json.dumps(sample_raw_data)
    encrypted_payload_str = cipher_suite.encrypt(json_string_data.encode('utf-8')).decode('utf-8')

    logging.info(f"Sample Encrypted Payload for Hashing Test: {encrypted_payload_str}")

    logging.info("\n--- SIMULATING BANK DATA PROCESSING (WITH HASHING) ---")
    logging.warning("Ensure your PostgreSQL database is running, schema.sql (with hash columns) is applied.")
    logging.warning(f"Using placeholder DB connection to: {DB_HOST}, DB: {DB_NAME}, User: {DB_USER}")

    # Uncomment to run the example processing.
    # process_bank_data_file_entry(encrypted_payload_str)
    # To test multiple chained transactions, call this multiple times.
    # process_bank_data_file_entry(cipher_suite.encrypt(json.dumps({
    #     "transaction_id_external": "TXN_HASH_TEST_002", "amount": 22.22, "currency": "USD",
    #     "timestamp": "2023-11-01T12:05:00Z", "account_holder_name": "Hash User",
    #     "email": "hash.user@example.com", "description": "Second transaction for hashing."
    # }).encode('utf-8')).decode('utf-8'))

    logging.info("Data processor script finished example run.")
    logging.info(f"Fernet key used (from/to {FERNET_KEY_FILE}). In production, manage this key securely and externally.")
