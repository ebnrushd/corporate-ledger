import os
import sys
import psycopg2
from psycopg2.extras import DictCursor
import hashlib # Though _calculate_transaction_hash uses it internally
import json
from datetime import timezone
from decimal import Decimal # For handling database decimal types

# Adjust sys.path to allow importing from ledger_processing
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..'))
sys.path.insert(0, PROJECT_ROOT)

try:
    from ledger_processing.data_processor import _calculate_transaction_hash
except ImportError:
    print("Error: Could not import _calculate_transaction_hash from ledger_processing.data_processor.")
    print("Ensure the script is run from the project root or PYTHONPATH is set correctly.")
    sys.exit(1)

# --- Database Connection (Placeholders - use environment variables in a real setup) ---
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_NAME = os.getenv("DB_NAME", "ledger_db")
DB_USER = os.getenv("DB_USER", "ledger_user")
DB_PASSWORD = os.getenv("DB_PASSWORD", "ledger_password") # Ensure this is configured
DB_PORT = os.getenv("DB_PORT", "5432")

def get_db_connection():
    """Establishes a connection to the PostgreSQL database."""
    try:
        conn = psycopg2.connect(
            host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD, port=DB_PORT
        )
        print("Database connection established.")
        return conn
    except psycopg2.Error as e:
        print(f"Error connecting to database: {e}")
        raise

def fetch_all_transactions_ordered(conn):
    """Fetches all transactions ordered by creation time to verify chain."""
    try:
        with conn.cursor(cursor_factory=DictCursor) as cursor:
            # Order by created_at, then by transaction_id as a tie-breaker (though UUIDs are less prone to exact ties)
            # This ensures we process in the exact order they were intended to be chained if created_at is identical.
            cursor.execute(
                """
                SELECT
                    transaction_id, sender_account_id, receiver_account_id,
                    amount, currency, transaction_type, description, status,
                    created_at, previous_transaction_hash, current_transaction_hash
                FROM transactions
                ORDER BY created_at ASC, transaction_id ASC
                """
            )
            transactions = cursor.fetchall()
            print(f"Fetched {len(transactions)} transactions from the database.")
            return transactions
    except psycopg2.Error as e:
        print(f"Error fetching transactions: {e}")
        return []

def verify_chain(transactions):
    """
    Verifies the integrity of the transaction chain.
    - Recalculates current_transaction_hash for each transaction.
    - Checks if previous_transaction_hash matches the hash of the actual previous transaction.
    """
    errors_found = 0
    actual_previous_hash_in_chain = None # Stores current_transaction_hash of the previously iterated transaction

    if not transactions:
        print("No transactions to verify.")
        return 0

    print("\nStarting chain verification...")

    for i, tx in enumerate(transactions):
        print(f"\nVerifying transaction ID: {tx['transaction_id']} (Created at: {tx['created_at']})")

        # 1. Reconstruct the data payload for hashing current_transaction_hash
        # This MUST match the structure and data types used in data_processor._calculate_transaction_hash
        tx_data_for_hashing = {
            "sender_account_id": str(tx.get("sender_account_id", "")),
            "receiver_account_id": str(tx.get("receiver_account_id", "")),
            "amount": "{:.2f}".format(tx.get("amount", Decimal('0.00'))), # Ensure Decimal is formatted
            "currency": str(tx.get("currency", "")),
            "transaction_type": str(tx.get("transaction_type", "")),
            "description": str(tx.get("description", "")),
            "status": str(tx.get("status", "")),
            # Ensure created_at is in UTC and ISO format string, matching data_processor
            "created_at": tx['created_at'].astimezone(timezone.utc).isoformat() if tx['created_at'] else "",
            "previous_transaction_hash": str(tx.get("previous_transaction_hash", "")) # Use stored prev hash for recalc
        }

        recalculated_hash = _calculate_transaction_hash(tx_data_for_hashing)

        # Verify current_transaction_hash
        if recalculated_hash != tx['current_transaction_hash']:
            errors_found += 1
            print(f"  [ERROR] Current hash mismatch for transaction ID: {tx['transaction_id']}")
            print(f"    Stored:   {tx['current_transaction_hash']}")
            print(f"    Recalc:   {recalculated_hash}")
            # For debugging, print the data used for hashing:
            # print(f"    Data used for recalc: {json.dumps(tx_data_for_hashing, indent=2)}")
        else:
            print(f"  [OK] Current hash matches for transaction ID: {tx['transaction_id']}")

        # Verify previous_transaction_hash link (except for the very first transaction)
        if i == 0: # Genesis transaction (or first in the fetched list)
            if tx['previous_transaction_hash'] is not None:
                # This could be valid if the chain starts from a known hash, or an error if it should be NULL
                print(f"  [INFO] First transaction ({tx['transaction_id']}) has previous_hash: {tx['previous_transaction_hash']}. Assuming this is a genesis or known starting point.")
            else:
                print(f"  [INFO] First transaction ({tx['transaction_id']}) has no previous_hash (genesis transaction).")
        else: # Not the first transaction
            if tx['previous_transaction_hash'] != actual_previous_hash_in_chain:
                errors_found += 1
                print(f"  [ERROR] Previous hash link broken for transaction ID: {tx['transaction_id']}")
                print(f"    Stored prev_hash:   {tx['previous_transaction_hash']}")
                print(f"    Expected prev_hash: {actual_previous_hash_in_chain} (from previous transaction's current_hash)")
            else:
                print(f"  [OK] Previous hash link correct for transaction ID: {tx['transaction_id']}")

        # Update actual_previous_hash_in_chain for the next iteration
        actual_previous_hash_in_chain = tx['current_transaction_hash']

    print("\n--- Verification Summary ---")
    print(f"Total transactions checked: {len(transactions)}")
    print(f"Total errors found: {errors_found}")
    if errors_found == 0 and transactions:
        print("Chain integrity verified successfully!")
    elif not transactions:
        print("No transactions were available to verify.")
    else:
        print("Chain integrity check failed with errors.")

    return errors_found

def main():
    """Main function to run the chain verification."""
    if not DB_PASSWORD:
        print("Error: DB_PASSWORD environment variable not set (or script not configured). Cannot connect to database.")
        return

    conn = None
    try:
        conn = get_db_connection()
        transactions = fetch_all_transactions_ordered(conn)
        if transactions is not None: # Ensure fetch didn't fail critically
            verify_chain(transactions)
    except psycopg2.Error as e:
        print(f"A database error occurred during verification: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
    finally:
        if conn:
            conn.close()
            print("Database connection closed.")

if __name__ == "__main__":
    main()
