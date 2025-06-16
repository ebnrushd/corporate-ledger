import json
import logging
import psycopg2
from cryptography.fernet import Fernet
import os # For generating fernet key, will be replaced by proper key management

# Configure basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Database Connection (Placeholders) ---
DB_HOST = "your_db_host"
DB_NAME = "ledger_db"
DB_USER = "ledger_user"
DB_PASSWORD = "ledger_password"
DB_PORT = "5432"

# --- Encryption (Placeholder) ---
# In a real application, this key would be securely managed (e.g., environment variable, KMS)
# For demonstration, we'll generate one if it doesn't exist, but this is NOT secure for production.
FERNET_KEY_FILE = "secret.key"

def generate_or_load_fernet_key():
    """
    Generates a Fernet key if one doesn't exist, or loads it.
    WARNING: This is for demonstration. Key management is critical in production.
    """
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

# Initialize Fernet cipher.
# In a real app, the key would come from a secure configuration or vault.
ENCRYPTION_KEY = generate_or_load_fernet_key() # This should be loaded securely
cipher_suite = Fernet(ENCRYPTION_KEY)

def get_db_connection():
    """Establishes a connection to the PostgreSQL database."""
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            port=DB_PORT
        )
        logging.info("Database connection established.")
        return conn
    except psycopg2.Error as e:
        logging.error(f"Error connecting to database: {e}")
        raise

def decrypt_data(encrypted_data_str: str) -> dict | None:
    """
    Decrypts bank raw data.
    Assumes encrypted_data_str is a string representation of bytes.
    """
    try:
        # Assuming the input string is the Fernet token itself
        decrypted_bytes = cipher_suite.decrypt(encrypted_data_str.encode('utf-8'))
        decrypted_json_str = decrypted_bytes.decode('utf-8')
        data = json.loads(decrypted_json_str)
        logging.info("Data decrypted successfully.")
        return data
    except json.JSONDecodeError as e:
        logging.error(f"JSON decoding failed after decryption: {e}")
        return None
    except Exception as e:
        logging.error(f"Decryption failed: {e}")
        return None

def validate_data(data: dict) -> bool:
    """
    Validates the decrypted data.
    (e.g., checking data integrity, format).
    This is a basic example; real validation would be more comprehensive.
    """
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

    # Add more specific checks, e.g., email format, date format, currency codes
    logging.info("Data validated successfully.")
    return True

def parse_data(data: dict) -> dict | None:
    """
    Parses the validated data to extract relevant information.
    This function maps raw data fields to database schema fields.
    """
    try:
        parsed = {
            "account_holder_name": data.get("account_holder_name"),
            "email": data.get("email"), # This should be encrypted before storing if not already
            "transaction_details": {
                "amount": data.get("amount"),
                "currency": data.get("currency", "USD"),
                "transaction_type": data.get("transaction_type", "deposit"), # Default type
                "description": data.get("description", f"Transaction {data.get('transaction_id_external')} processed on {data.get('timestamp')}"),
                "external_id": data.get("transaction_id_external"), # For idempotency or reference
            },
            "banknote_serials": data.get("banknote_serials", []) # List of serial numbers
        }
        # Placeholder for password - in a real scenario, this would be handled during user registration
        parsed["hashed_password"] = "temporary_placeholder_hash"
        logging.info("Data parsed successfully.")
        return parsed
    except Exception as e:
        logging.error(f"Data parsing failed: {e}")
        return None

def store_data(parsed_data: dict):
    """
    Stores the parsed data into the PostgreSQL database.
    This function needs to handle account creation/lookup,
    transaction insertion, and serial box registration.
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # 1. Get or Create Account
        account_id = None
        cursor.execute("SELECT account_id FROM accounts WHERE email = %s;", (parsed_data["email"],))
        row = cursor.fetchone()
        if row:
            account_id = row[0]
            logging.info(f"Account found for email {parsed_data['email']}: {account_id}")
        else:
            # Encrypt email before storing (if not already done at a higher level)
            # For now, assuming email in parsed_data is ready for storage or schema handles encryption
            cursor.execute(
                """
                INSERT INTO accounts (account_holder_name, email, hashed_password)
                VALUES (%s, %s, %s) RETURNING account_id;
                """,
                (parsed_data["account_holder_name"], parsed_data["email"], parsed_data["hashed_password"])
            )
            account_id = cursor.fetchone()[0]
            logging.info(f"Created new account for email {parsed_data['email']}: {account_id}")

            # Initialize balance for the new account
            cursor.execute(
                """
                INSERT INTO balances (account_id, currency, balance)
                VALUES (%s, %s, %s);
                """,
                (account_id, parsed_data["transaction_details"]["currency"], 0.00) # Initial balance 0
            )
            logging.info(f"Initialized balance for account {account_id}.")

        # 2. Store Transaction
        tx_details = parsed_data["transaction_details"]
        # Assuming deposit, so receiver_account_id is our account, sender is null (external)
        cursor.execute(
            """
            INSERT INTO transactions (receiver_account_id, amount, currency, transaction_type, description, status)
            VALUES (%s, %s, %s, %s, %s, %s) RETURNING transaction_id;
            """,
            (account_id, tx_details["amount"], tx_details["currency"],
             tx_details["transaction_type"], tx_details["description"], 'completed')
        )
        transaction_id = cursor.fetchone()[0]
        logging.info(f"Transaction {transaction_id} stored successfully for account {account_id}.")

        # 3. Update Balance
        cursor.execute(
            """
            UPDATE balances SET balance = balance + %s
            WHERE account_id = %s AND currency = %s;
            """,
            (tx_details["amount"], account_id, tx_details["currency"])
        )
        logging.info(f"Balance updated for account {account_id}.")

        # 4. Store Banknote Serials (if any)
        # This assumes banknote serials are linked to the account and potentially this transaction
        # The exact logic might depend on how serials are tracked (e.g., per transaction, per deposit)
        for serial_number in parsed_data.get("banknote_serials", []):
            # Encrypt serial_number before storing
            # For now, assuming serial_number in parsed_data is ready for storage or schema handles encryption
            cursor.execute(
                """
                INSERT INTO serial_boxes (serial_number, assigned_account_id, status, product_id)
                VALUES (%s, %s, %s, %s);
                """,
                (serial_number, account_id, 'assigned', tx_details.get("product_id", "banknote"))
            )
            logging.info(f"Stored serial number {serial_number} for account {account_id}.")

        conn.commit()
        logging.info("All data stored successfully and transaction committed.")

    except psycopg2.Error as e:
        if conn:
            conn.rollback()
        logging.error(f"Database error during data storage: {e}")
        # Potentially re-raise or handle more gracefully
    except Exception as e:
        if conn:
            conn.rollback()
        logging.error(f"An unexpected error occurred during data storage: {e}")
    finally:
        if conn:
            cursor.close()
            conn.close()
            logging.info("Database connection closed.")


def process_bank_data_file_entry(encrypted_entry_str: str):
    """
    Processes a single encrypted entry from a bank data file.
    """
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
    # --- Example Usage (Illustrative) ---
    # This section demonstrates how the functions might be used.
    # In a real system, encrypted_data would come from a file, queue, or API.

    # 1. Generate a sample raw data payload (what would be encrypted)
    sample_raw_data = {
        "transaction_id_external": "TXN123456789",
        "amount": 100.50,
        "currency": "USD",
        "timestamp": "2023-10-26T10:00:00Z",
        "account_holder_name": "John Doe",
        "email": "john.doe@example.com", # Sensitive: will be part of encrypted payload
        "description": "Initial deposit from Bank XYZ.",
        "banknote_serials": ["SN123ABC", "SN456DEF", "SN789GHI"], # Sensitive
        "transaction_type": "deposit"
    }
    json_string_data = json.dumps(sample_raw_data)

    # 2. Encrypt it (as if it's coming from the bank)
    encrypted_payload_bytes = cipher_suite.encrypt(json_string_data.encode('utf-8'))
    encrypted_payload_str = encrypted_payload_bytes.decode('utf-8') # Convert bytes to string for simulation

    logging.info(f"Sample Encrypted Payload (string representation): {encrypted_payload_str}")

    # 3. Process this encrypted payload
    # Note: For this test to run against a DB, the DB details (DB_HOST etc.) must be valid
    # and the schema.sql must have been applied to the database.
    logging.info("\n--- SIMULATING BANK DATA PROCESSING ---")
    logging.warning("Ensure your PostgreSQL database is running and schema.sql is applied for this example.")
    logging.warning(f"Using placeholder DB connection: {DB_HOST}, {DB_NAME}, {DB_USER}")

    # Uncomment to run the example processing.
    # process_bank_data_file_entry(encrypted_payload_str)

    # Example of encrypting an email or serial number for storage (conceptual)
    # This would typically happen *before* calling store_data if the application handles field-level encryption
    # Or, the database itself might handle it (e.g. using pgcrypto functions directly in SQL INSERT/UPDATE)

    # sample_email_to_encrypt = "sensitive.email@example.com"
    # encrypted_email_bytes = cipher_suite.encrypt(sample_email_to_encrypt.encode('utf-8'))
    # encrypted_email_str = encrypted_email_bytes.decode('utf-8')
    # logging.info(f"Example encrypted email for storage: {encrypted_email_str}")

    # To decrypt it (e.g., if an admin needed to view it, with proper authorization)
    # decrypted_email_bytes = cipher_suite.decrypt(encrypted_email_str.encode('utf-8'))
    # logging.info(f"Decrypted email: {decrypted_email_bytes.decode('utf-8')}")

    logging.info("Data processor script finished example run.")
    logging.info(f"Fernet key used (from/to {FERNET_KEY_FILE}). In production, manage this key securely and externally.")
