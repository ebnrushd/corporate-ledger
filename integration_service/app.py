import os
import json
import uuid
import logging
from flask import Flask, request, jsonify
from web3 import Web3
import psycopg2
from psycopg2.extras import DictCursor # For dictionary-like cursor
from dotenv import load_dotenv

from visa_api_client import VisaApiClient # Import the new client

# --- Initialization and Configuration ---
load_dotenv() # Load environment variables from .env file

app = Flask(__name__)

# Enhanced Logging Configuration
# Consider structured logging (e.g., using python-json-logger) in production for better parsing.
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(module)s - %(funcName)s - %(message)s'
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(), format=LOG_FORMAT)
logger = logging.getLogger(__name__) # Use a specific logger for the app

# Database Configuration (from .env)
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_NAME = os.getenv("DB_NAME", "ledger_db")
DB_USER = os.getenv("DB_USER", "ledger_user")
DB_PASSWORD = os.getenv("DB_PASSWORD") # No default for password
DB_PORT = os.getenv("DB_PORT", "5432")

# Ethereum Node and Smart Contract Configuration (from .env)
ETH_NODE_URL = os.getenv("ETH_NODE_URL", "http://127.0.0.1:8545")
CONTRACT_DEPLOYMENT_INFO_PATH = os.getenv("CONTRACT_DEPLOYMENT_INFO_PATH", "../scripts/deployment_info.json")
API_SERVICE_PRIVATE_KEY = os.getenv("API_SERVICE_PRIVATE_KEY") # Ensure this is kept secure

# Web3 Setup
w3 = Web3(Web3.HTTPProvider(ETH_NODE_URL))
contract_address = None
contract_abi = None
visa_top_up_contract = None

# API Service account (acting as authorized backend for the smart contract)
api_service_account = None
if API_SERVICE_PRIVATE_KEY:
    try:
        api_service_account = w3.eth.account.from_key(API_SERVICE_PRIVATE_KEY)
        logger.info(f"API Service Account (Smart Contract Backend) loaded: {api_service_account.address}")
    except Exception as e:
        logger.error(f"Invalid API_SERVICE_PRIVATE_KEY: {e}", exc_info=True)
        # Critical failure if private key is invalid, service might not function for SC interactions.
else:
    logger.warning("API_SERVICE_PRIVATE_KEY not set. Smart contract interactions will be disabled.")


# Load Contract ABI and Address
try:
    with open(CONTRACT_DEPLOYMENT_INFO_PATH, 'r') as f:
        deployment_info = json.load(f)
    contract_address = deployment_info.get('contract_address')
    contract_abi = deployment_info.get('abi')
    if contract_address and contract_abi and w3.is_connected():
        visa_top_up_contract = w3.eth.contract(address=contract_address, abi=contract_abi)
        logger.info(f"VisaTopUp Smart Contract loaded at address: {contract_address}")
        # Conceptual: Verify API service account is authorized backend in SC (read-only call)
        # if api_service_account and visa_top_up_contract:
        #     try:
        #         sc_auth_backend = visa_top_up_contract.functions.authorizedBackendAddress().call()
        #         if sc_auth_backend == api_service_account.address:
        #             logger.info(f"API service account {api_service_account.address} IS correctly set as authorized backend in SC.")
        #         else:
        #             logger.critical(f"CRITICAL MISCONFIGURATION: API service account {api_service_account.address} is NOT the authorized backend in SC. Current SC backend: {sc_auth_backend}")
        #     except Exception as e_sc_read:
        #         logger.error(f"Failed to read authorizedBackendAddress from smart contract: {e_sc_read}", exc_info=True)
    else:
        if not w3.is_connected():
            logger.error("Failed to connect to Ethereum node for smart contract loading.")
        if not contract_address or not contract_abi:
            logger.error("Smart contract address or ABI is missing in deployment_info.json.")
except FileNotFoundError:
    logger.error(f"Contract deployment info file not found at {CONTRACT_DEPLOYMENT_INFO_PATH}. Smart contract features disabled.")
except Exception as e:
    logger.error(f"Error loading smart contract: {e}", exc_info=True)

# Initialize Visa API Client (Placeholder)
# Ensure API keys themselves are not logged by the client or here.
VISA_API_KEY = os.getenv("VISA_API_KEY", "sk_test_placeholder_visa_key") # PCI DSS: Securely manage API keys.
VISA_API_SECRET = os.getenv("VISA_API_SECRET", "placeholder_visa_secret") # PCI DSS: Securely manage API keys.
visa_client = VisaApiClient(api_key=VISA_API_KEY, api_secret=VISA_API_SECRET)
# The VisaApiClient's __init__ logs its own initialization.

# --- Database Helper Functions ---
def get_db_connection():
    """Establishes a connection to the PostgreSQL database."""
    try:
        conn = psycopg2.connect(
            host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD, port=DB_PORT
        )
        return conn
    except psycopg2.Error as e:
        logger.error(f"Database connection error: {e}", exc_info=True)
        raise # Re-raise to be caught by endpoint error handlers

# --- Smart Contract Helper Functions ---
def send_sc_transaction(contract_function, sender_account):
    """Helper to build, sign, and send a transaction to the smart contract."""
    if not sender_account:
        logger.critical("CRITICAL: Sender account (API service account) for SC interaction is not configured.")
        raise ValueError("Sender account (API service account) not configured.")
    if not w3.is_connected():
        logger.error("Ethereum node connection error during SC transaction preparation.")
        raise ConnectionError("Not connected to Ethereum node.")

    try:
        tx_params = {
            'from': sender_account.address,
            'gas': int(os.getenv("GAS_LIMIT_INTERACTION", 500000)),
            'gasPrice': w3.to_wei(os.getenv("GAS_PRICE_GWEI_INTERACTION", 10), 'gwei'),
            'nonce': w3.eth.get_transaction_count(sender_account.address),
        }
        logger.debug(f"Building SC transaction. From: {tx_params['from']}, To: {contract_function.address}, Function: {contract_function.fn_name}, Nonce: {tx_params['nonce']}")
        transaction = contract_function.build_transaction(tx_params)
        signed_tx = w3.eth.account.sign_transaction(transaction, private_key=sender_account.key)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
        logger.info(f"Smart contract transaction sent. TxHash: {tx_hash.hex()}, Function: {contract_function.fn_name}")
        return tx_hash.hex()
    except Exception as e:
        logger.error(f"Failed to build or send smart contract transaction for function {contract_function.fn_name}: {e}", exc_info=True)
        raise # Re-raise to be caught by endpoint error handlers


# --- API Endpoints ---

@app.route('/health', methods=['GET'])
def health_check():
    # PCI DSS: Health check should not expose sensitive configuration details.
    db_ok = False
    web3_ok = False
    contract_ok = False
    try:
        conn = get_db_connection()
        conn.close()
        db_ok = True
    except Exception as e:
        logger.error(f"Health check: DB connection failed: {e}", exc_info=True)

    web3_ok = w3.is_connected()
    if not web3_ok:
        logger.warning("Health check: Ethereum node not connected.")

    contract_ok = visa_top_up_contract is not None and contract_address is not None
    if not contract_ok:
        logger.warning("Health check: Smart contract not loaded (address or ABI missing, or Web3 not connected).")

    return jsonify({
        "status": "ok" if db_ok and web3_ok and contract_ok else "issues_detected",
        "database_connected": db_ok,
        "ethereum_node_connected": web3_ok,
        "smart_contract_loaded": contract_ok,
        "api_service_account_loaded": api_service_account is not None
    }), 200

@app.route('/topup/initiate', methods=['POST'])
def initiate_topup_route():
    """
    Endpoint to initiate a Visa top-up.
    Records intent, calls SC `initiateTopUp`, then requests Visa processing via API client.
    """
    # PCI DSS: This endpoint handles card_last_four. Ensure HTTPS. All data handling must be PCI DSS compliant.
    data = request.get_json()
    if not data:
        logger.warning("Initiate top-up: Invalid or empty JSON payload received.")
        return jsonify({"error": "Invalid JSON payload"}), 400

    user_id_from_request = data.get('user_id')
    amount_str = data.get('amount')
    visa_card_last_four = data.get('visa_card_last_four') # PCI DSS: Sensitive data.

    # --- Input Validation ---
    validation_errors = []
    if not user_id_from_request or not isinstance(user_id_from_request, str):
        validation_errors.append("user_id is required and must be a string.")

    amount = None
    if amount_str is None:
        validation_errors.append("amount is required.")
    else:
        try:
            amount = float(amount_str)
            if amount <= 0:
                validation_errors.append("amount must be a positive number.")
        except ValueError:
            validation_errors.append("amount must be a valid numeric value.")

    # PCI DSS: card_last_four is sensitive. Log carefully.
    if not (isinstance(visa_card_last_four, str) and len(visa_card_last_four) == 4 and visa_card_last_four.isdigit()):
        validation_errors.append("visa_card_last_four must be a string of 4 digits.")

    if validation_errors:
        logger.warning(f"Initiate top-up: Validation failed. UserID: {user_id_from_request}, Amount: {amount_str}, VisaLastFour: {visa_card_last_four}. Errors: {validation_errors}")
        return jsonify({"error": "Validation failed", "messages": validation_errors}), 400

    logger.info(f"Initiate top-up: Request validated. UserID: {user_id_from_request}, Amount: {amount}, VisaLastFour: ****") # PCI DSS: Mask card data in logs.

    conn = None
    internal_tx_id = None # UUID of our database transaction record
    top_up_id_bytes32 = os.urandom(32) # Unique ID for this top-up operation (used for SC and potentially Visa)
    top_up_id_hex = top_up_id_bytes32.hex()

    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=DictCursor)

        # 1. Fetch user account (maps user_id_from_request to internal account_id and ETH address)
        # This logic assumes user_id_from_request is the UUID account_id for DB lookup.
        # And that the 'accounts' table has an 'ethereum_address' field for the SC.
        db_user_id_for_query = None
        try:
            uuid.UUID(user_id_from_request) # Validate format if expecting UUID for DB
            db_user_id_for_query = user_id_from_request
        except ValueError:
            # If user_id_from_request is not UUID, it might be an email or other identifier.
            # This example assumes direct UUID or an ETH address that might also be a UUID.
            # A real system needs robust user identity resolution.
            logger.warning(f"Initiate top-up: user_id '{user_id_from_request}' is not a valid UUID. Attempting ETH address check for SC.")
            if not Web3.is_address(user_id_from_request):
                 logger.error(f"Initiate top-up: user_id '{user_id_from_request}' is not a valid UUID for DB lookup nor a valid Ethereum address for SC.")
                 return jsonify({"error": "Invalid user_id format."}), 400
            # If it's an ETH address but not UUID, DB lookup by this ID might fail unless 'accounts.account_id' can also be an ETH address.
            # This part needs to align with your User model. For now, assume user_id_from_request IS the DB account_id.
            db_user_id_for_query = user_id_from_request # Tentatively use for DB.

        cursor.execute("SELECT account_id, email, ethereum_address FROM accounts WHERE account_id = %s;", (db_user_id_for_query,))
        account = cursor.fetchone()
        if not account:
            logger.warning(f"Initiate top-up: User with account_id {db_user_id_for_query} not found in database.")
            return jsonify({"error": f"User with account_id {db_user_id_for_query} not found"}), 404

        logger.info(f"Initiate top-up: User account {account['account_id']} found. ETH Address for SC: {account.get('ethereum_address')}")

        # Determine SC user address
        sc_user_address = account.get('ethereum_address')
        if not sc_user_address or not Web3.is_address(sc_user_address):
            logger.warning(f"Initiate top-up: User {account['account_id']} lacks a valid ethereum_address. Using API service address as SC user placeholder.")
            sc_user_address = api_service_account.address # Fallback placeholder - review if this is desired.

        # Placeholder: Balance/limit checks for user {account['account_id']}
        # logger.info(f"Performing balance/limit checks for UserID: {account['account_id']}")

        # 2. Create initial transaction record in the ledger
        # PCI DSS: Storing visa_card_last_four (even masked) in description is sensitive. Ensure DB encryption for this field if it must be stored.
        # Better: store a non-sensitive reference if possible, or only the SC_TopUpID.
        initial_description = f"VisaTopUp Init: Card ****{visa_card_last_four[-4:]}. SC_TopUpID: {top_up_id_hex}"

        cursor.execute(
            """
            INSERT INTO transactions (receiver_account_id, amount, currency, transaction_type, description, status)
            VALUES (%s, %s, %s, %s, %s, %s) RETURNING transaction_id;
            """,
            (account['account_id'], amount, "USD", "TOPUP_INITIATED", initial_description, "PENDING_SC_CALL")
        )
        internal_tx_id = cursor.fetchone()['transaction_id']
        logger.info(f"Initiate top-up: Ledger transaction {internal_tx_id} created (uncommitted) for UserID: {account['account_id']}, SC_TopUpID: {top_up_id_hex}.")

        # 3. Smart Contract Interaction: initiateTopUp
        if not visa_top_up_contract or not api_service_account:
            logger.critical("Initiate top-up: Smart contract or API service account not configured at SC interaction point.")
            raise SystemError("Smart contract or API service account not configured.")

        sc_amount = int(amount * 100) # Example: Convert dollars to cents for SC
        logger.info(f"Initiate top-up: Preparing SC call `initiateTopUp`. UserEthAddr: {sc_user_address}, SC_Amount(cents): {sc_amount}, SC_TopUpID: {top_up_id_hex}")
        # PCI DSS: Sending visa_card_last_four to SC. Evaluate on-chain data privacy implications.
        initiate_func = visa_top_up_contract.functions.initiateTopUp(
            top_up_id_bytes32, w3.to_checksum_address(sc_user_address), sc_amount, str(visa_card_last_four)
        )
        sc_tx_hash = send_sc_transaction(initiate_func, api_service_account) # send_sc_transaction logs its own success/failure

        # Update ledger transaction status after successful SC call
        cursor.execute(
            "UPDATE transactions SET status = %s, description = description || %s WHERE transaction_id = %s;",
            ("PENDING_VISA_API_CALL", f" | SC_InitiateTx: {sc_tx_hash}", internal_tx_id)
        )
        logger.info(f"Initiate top-up: Ledger tx {internal_tx_id} updated to PENDING_VISA_API_CALL after SC success.")

        # 4. Call Visa API Client to request the actual top-up
        # PCI DSS: Passing card_last_four to Visa client.
        logger.info(f"Initiate top-up: Requesting card top-up via Visa API client. InternalTxID: {internal_tx_id}, SC_TopUpID: {top_up_id_hex}")
        visa_response = visa_client.request_card_top_up(
            top_up_id=top_up_id_hex, card_last_four=visa_card_last_four, amount=float(amount), currency="USD"
        )
        visa_status = visa_response.get("status") # Expected: PENDING, SUCCESS, ERROR
        visa_tx_id = visa_response.get("visa_transaction_id")
        visa_message = visa_response.get("message", "")
        logger.info(f"Initiate top-up: Visa API client response. InternalTxID: {internal_tx_id}, VisaStatus: {visa_status}, VisaTxID: {visa_tx_id}, VisaMsg: {visa_message}")

        ledger_status_after_visa_call = "PENDING_VISA_WEBHOOK" # Default for Visa PENDING/SUCCESS
        extra_desc_after_visa_call = f" | VisaAPIStatus: {visa_status}, VisaTxID: {visa_tx_id}"

        if visa_status == "ERROR":
            ledger_status_after_visa_call = "FAILED_VISA_API_CALL"
            logger.error(f"Initiate top-up: Visa API call failed for InternalTxID: {internal_tx_id}. Error: {visa_message}")
        elif visa_status == "SUCCESS":
            logger.info(f"Initiate top-up: Visa API call reported immediate SUCCESS for InternalTxID: {internal_tx_id}. VisaTxID: {visa_tx_id}. Awaiting webhook for final SC confirmation.")

        cursor.execute(
            "UPDATE transactions SET status = %s, description = description || %s WHERE transaction_id = %s;",
            (ledger_status_after_visa_call, extra_desc_after_visa_call, internal_tx_id)
        )

        conn.commit() # Commit all DB changes (initial insert + two updates)
        logger.info(f"Initiate top-up: DB transaction {internal_tx_id} committed with status {ledger_status_after_visa_call}.")

        return jsonify({
            "message": "Top-up initiation accepted and processing with Visa.",
            "internal_transaction_id": str(internal_tx_id),
            "smart_contract_top_up_id": top_up_id_hex,
            "smart_contract_tx_hash": sc_tx_hash,
            "visa_api_status": visa_status,
            "visa_transaction_id": visa_tx_id
        }), 202

    except psycopg2.Error as db_err:
        if conn: conn.rollback()
        logger.error(f"Initiate top-up: Database error. UserID: {user_id_from_request}. Error: {db_err}", exc_info=True)
        return jsonify({"error": "Database operation failed during top-up initiation."}), 500
    except (ValueError, ConnectionError, SystemError) as processing_err: # Errors from SC or Visa client
        if conn: conn.rollback()
        logger.error(f"Initiate top-up: Processing error (SC or Visa Client). UserID: {user_id_from_request}. Error: {processing_err}", exc_info=True)
        if internal_tx_id: # If ledger tx was created, mark as failed
            try:
                if conn.closed: conn = get_db_connection() # Reopen if necessary
                with conn.cursor() as cursor_fail: # Use new cursor
                    cursor_fail.execute("UPDATE transactions SET status = %s, description = description || %s WHERE transaction_id = %s;",
                                   ("FAILED_PRE_COMMIT_PROCESSING_ERROR", f" | Error: {str(processing_err)[:100]}", internal_tx_id))
                    conn.commit()
            except Exception as e_conn_update:
                logger.critical(f"Initiate top-up: CRITICAL - Failed to update transaction {internal_tx_id} to error state. Error: {e_conn_update}", exc_info=True)
        return jsonify({"error": f"Processing error during top-up initiation: {processing_err}"}), 500
    except Exception as e:
        if conn: conn.rollback()
        logger.error(f"Initiate top-up: An unexpected error occurred. UserID: {user_id_from_request}. Error: {e}", exc_info=True)
        if internal_tx_id: # If ledger tx was created, mark as failed
             try:
                if conn.closed: conn = get_db_connection()
                with conn.cursor() as cursor_fail:
                    cursor_fail.execute("UPDATE transactions SET status = %s, description = description || %s WHERE transaction_id = %s;",
                                   ("FAILED_UNEXPECTED_ERROR", f" | Error: {str(e)[:100]}", internal_tx_id))
                    conn.commit()
             except Exception as e_conn_update:
                logger.critical(f"Initiate top-up: CRITICAL - Failed to update transaction {internal_tx_id} to error state. Error: {e_conn_update}", exc_info=True)
        return jsonify({"error": "An unexpected error occurred during top-up initiation."}), 500
    finally:
        if conn and not conn.closed:
            # cursor might be None if conn failed at get_db_connection itself
            # if 'cursor' in locals() and cursor: cursor.close() # cursor is function-scoped
            conn.close()

@app.route('/topup/webhook/visa_confirmation', methods=['POST'])
def visa_confirmation_webhook():
    # PCI DSS: This endpoint receives sensitive payment processing outcomes. Secure with HTTPS.
    # Consider additional security like HMAC signature validation of the webhook payload if supported by Visa.
    data = request.get_json()
    if not data:
        logger.warning("Webhook: Invalid or empty JSON payload received.")
        return jsonify({"error": "Invalid JSON payload"}), 400

    top_up_id_hex = data.get('topUpId')
    status_from_visa = data.get('status')
    message_from_visa = data.get('message', '')
    processor_tx_id = data.get('processor_transaction_id', 'N/A') # Visa's own transaction ID

    logger.info(f"Webhook: Received Visa confirmation. TopUpID_Hex: {top_up_id_hex}, Status: {status_from_visa}, ProcessorTxID: {processor_tx_id}") # PCI DSS: Avoid logging full message if sensitive.

    # --- Input Validation ---
    if not top_up_id_hex or not isinstance(top_up_id_hex, str):
        logger.warning(f"Webhook: topUpId missing or invalid format. Received: {top_up_id_hex}")
        return jsonify({"error": "topUpId is required and must be a string."}), 400
    if not status_from_visa or not isinstance(status_from_visa, str):
        logger.warning(f"Webhook: status missing or invalid format. TopUpID_Hex: {top_up_id_hex}, Received Status: {status_from_visa}")
        return jsonify({"error": "status is required and must be a string."}), 400

    is_success_from_visa = status_from_visa.upper() == 'SUCCESS'

    try:
        top_up_id_bytes32 = bytes.fromhex(top_up_id_hex)
    except ValueError:
        logger.warning(f"Webhook: Invalid topUpId hex format. TopUpID_Hex: {top_up_id_hex}")
        return jsonify({"error": "Invalid topUpId format (must be hex string for 32 bytes)."}), 400

    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=DictCursor) as cursor: # Use `with` statement for cursor

            # 1. Find original transaction. Using a dedicated indexed column for `sc_topup_id_hex` is highly recommended.
            # Querying `description LIKE %...%` is inefficient and error-prone.
            query_description_filter = f"%SC_TopUpID: {top_up_id_hex}%"
            # Expecting transaction to be in a state awaiting webhook.
            expected_statuses = ("PENDING_VISA_WEBHOOK", "FAILED_VISA_API_CALL") # May retry FAILED_VISA_API_CALL

            cursor.execute(
                f"SELECT transaction_id, receiver_account_id, amount, currency, status FROM transactions WHERE description LIKE %s AND status IN %s;",
                (query_description_filter, expected_statuses)
            )
            ledger_tx = cursor.fetchone()

            if not ledger_tx:
                logger.warning(f"Webhook: No matching transaction found for SC_TopUpID: {top_up_id_hex} in expected states {expected_statuses}. May have been processed or does not exist.")
                return jsonify({"error": "No matching pending transaction found or already processed."}), 404 # Or 200 OK if this is expected behavior.

            internal_tx_id = ledger_tx['transaction_id']
            user_account_id = ledger_tx['receiver_account_id']
            original_topup_amount = ledger_tx['amount']
            currency = ledger_tx['currency']
            current_ledger_tx_status = ledger_tx['status']
            logger.info(f"Webhook: Found ledger transaction {internal_tx_id} for SC_TopUpID {top_up_id_hex}. CurrentDBStatus: {current_ledger_tx_status}, VisaStatus: {status_from_visa}")

            # Idempotency check: If already in a final confirmed state.
            if current_ledger_tx_status in ["COMPLETED_TOPUP_CONFIRMED", "FAILED_TOPUP_CONFIRMED"]:
                logger.warning(f"Webhook: Transaction {internal_tx_id} already in final state {current_ledger_tx_status}. Ignoring duplicate for SC_TopUpID: {top_up_id_hex}.")
                return jsonify({"message": "Webhook already processed for this topUpId."}), 200

            # 2. Update Ledger Transaction based on Visa's final status
            new_ledger_status_pre_sc = "COMPLETED_TOPUP_PENDING_SC_CONFIRM" if is_success_from_visa else "FAILED_TOPUP_PENDING_SC_CONFIRM"
            description_update = f" | VisaWebhook: Status='{status_from_visa}', ProcessorTXID='{processor_tx_id}'" # PCI DSS: Ensure message_from_visa is not overly sensitive if appended.

            cursor.execute(
                "UPDATE transactions SET status = %s, description = description || %s WHERE transaction_id = %s;",
                (new_ledger_status_pre_sc, description_update, internal_tx_id)
            )
            logger.info(f"Webhook: Ledger transaction {internal_tx_id} updated to {new_ledger_status_pre_sc}.")

            # 3. Adjust User Balance in DB if Visa processing was successful
            if is_success_from_visa:
                logger.info(f"Webhook: Processing successful top-up for UserID: {user_account_id}, Amount: {original_topup_amount} {currency}.")
                cursor.execute(
                    "UPDATE balances SET balance = balance + %s WHERE account_id = %s AND currency = %s;",
                    (original_topup_amount, user_account_id, currency)
                )
                if cursor.rowcount == 0: # If no balance record existed
                    cursor.execute(
                        "INSERT INTO balances (account_id, balance, currency) VALUES (%s, %s, %s);", # Consider ON CONFLICT DO UPDATE if balance might be created by another process.
                        (user_account_id, original_topup_amount, currency)
                    )
                    logger.info(f"Webhook: Created new balance record for UserID: {user_account_id}, Amount: {original_topup_amount} {currency}.")
                logger.info(f"Webhook: User {user_account_id} balance updated by {original_topup_amount} {currency}.")
            else:
                logger.info(f"Webhook: Top-up failed as per Visa. UserID: {user_account_id}. No balance change made for tx {internal_tx_id}.")

            conn.commit()
            logger.info(f"Webhook: DB changes for transaction {internal_tx_id} (status, balance) committed before SC confirmTopUp call.")

            # 4. Smart Contract Interaction: Call confirmTopUp
            if not visa_top_up_contract or not api_service_account:
                logger.critical("Webhook: Smart contract or API service account not configured at SC confirmTopUp point. THIS IS A CRITICAL STATE REQUIRING MANUAL INTERVENTION.")
                raise SystemError("Smart contract or API service account not configured for webhook SC interaction.")

            sc_message_for_confirm = f"VisaStatus: {status_from_visa}, Msg: {message_from_visa[:100]}" # Truncate message for SC
            logger.info(f"Webhook: Calling SC `confirmTopUp` for SC_TopUpID: {top_up_id_hex}, Success: {is_success_from_visa}")
            confirm_func = visa_top_up_contract.functions.confirmTopUp(
                top_up_id_bytes32, is_success_from_visa, sc_message_for_confirm
            )
            sc_tx_hash = send_sc_transaction(confirm_func, api_service_account) # send_sc_transaction logs its own events
            logger.info(f"Webhook: Smart contract `confirmTopUp` call successful for SC_TopUpID: {top_up_id_hex}. SC_ConfirmTxHash: {sc_tx_hash}")

            # Update ledger tx again with SC confirmation hash and final status
            final_ledger_status = "COMPLETED_TOPUP_CONFIRMED" if is_success_from_visa else "FAILED_TOPUP_CONFIRMED"
            cursor.execute(
                "UPDATE transactions SET status = %s, description = description || %s WHERE transaction_id = %s;",
                (final_ledger_status, f" | SC_ConfirmTx: {sc_tx_hash}", internal_tx_id)
            )
            conn.commit()
            logger.info(f"Webhook: Transaction {internal_tx_id} final status set to {final_ledger_status} and SC_ConfirmTxHash recorded in DB.")

            return jsonify({
                "message": "Visa confirmation webhook processed successfully.",
                "internal_transaction_id": str(internal_tx_id),
                "smart_contract_confirm_tx_hash": sc_tx_hash,
                "final_ledger_status": final_ledger_status
            }), 200

    except psycopg2.Error as db_err:
        if conn: conn.rollback()
        logger.error(f"Webhook: Database error. TopUpID_Hex: {top_up_id_hex}. Error: {db_err}", exc_info=True)
        return jsonify({"error": "Database operation failed in webhook processing."}), 500
    except (ValueError, ConnectionError, SystemError) as processing_err:
        # If SC call fails, DB is already committed with pre-SC status. This indicates a state needing reconciliation.
        logger.error(f"Webhook: Processing error (likely SC). TopUpID_Hex: {top_up_id_hex}. Error: {processing_err}", exc_info=True)
        return jsonify({"error": f"Smart contract operation failed in webhook: {processing_err}"}), 500 # Or 202 if problem occurred post-DB commit but pre-final ack
    except Exception as e:
        if conn: conn.rollback()
        logger.error(f"Webhook: An unexpected error occurred. TopUpID_Hex: {top_up_id_hex}. Error: {e}", exc_info=True)
        return jsonify({"error": "An unexpected error occurred in webhook processing."}), 500
    finally:
        if conn and not conn.closed:
            # cursor is managed by 'with' statement if used, otherwise close manually
            # if 'cursor' in locals() and cursor and not cursor.closed: cursor.close()
            conn.close()

# --- Helper for JSON serialization ---
def default_serializer(obj): # Keep this at the end or in a helpers module
    """JSON serializer for objects not serializable by default json code"""
    if isinstance(obj, uuid.UUID): # Handle UUID
        return str(obj) # Convert UUID to string
    if isinstance(obj, psycopg2.extras.Decimal):
        return float(obj) # Convert Decimal to float
    if hasattr(obj, 'isoformat'): # Handle datetime objects
        return obj.isoformat() # Convert datetime to ISO 8601 string
    raise TypeError(f"Type {type(obj)} not serializable for JSON")

@app.route('/transactions', methods=['GET'])
def get_transactions_route(): # Keep this after the serializer function
    """
    Fetches transaction history from the ledger.
    Optionally, can be filtered by user_id if provided as a query parameter.
    e.g., /transactions?user_id=<user_uuid_string>
    """
    user_id_filter_str = request.args.get('user_id')
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=DictCursor) as cursor: # Use DictCursor for dictionary-like rows

            base_query = """
                SELECT
                    transaction_id, sender_account_id, receiver_account_id,
                    amount, currency, transaction_type, description,
                    status, created_at, updated_at
                FROM transactions
            """
            params = []
            conditions = []

            if user_id_filter_str:
                try:
                    # Validate user_id_filter_str as UUID if that's the type in DB for account_id
                    user_id_as_uuid = uuid.UUID(user_id_filter_str)
                    conditions.append("(sender_account_id = %s OR receiver_account_id = %s)") # Ensure account_id columns are UUID type
                    params.extend([str(user_id_as_uuid), str(user_id_as_uuid)])
                    logger.info(f"Fetching transactions for UserID (UUID): {user_id_as_uuid}")
                except ValueError:
                    logger.warning(f"Invalid UserID format for filtering transactions: '{user_id_filter_str}'. Expected UUID. Fetching all transactions instead.")
                    # Decide: either return error, or fetch all. For now, fetching all if format is wrong.
                    # return jsonify({"error": "Invalid user_id format for filtering. Expected UUID string."}), 400

            if conditions:
                query = f"{base_query} WHERE {' AND '.join(conditions)} ORDER BY created_at DESC LIMIT 100;"
            else:
                query = f"{base_query} ORDER BY created_at DESC LIMIT 100;"
                logger.info("Fetching all transactions (limit 100) as no valid user_id filter was applied.")

            cursor.execute(query, tuple(params))
            transactions_raw = cursor.fetchall()

            transactions_list = [dict(row) for row in transactions_raw]

            return json.dumps(transactions_list, default=default_serializer), 200, {'Content-Type': 'application/json'}

    except psycopg2.Error as db_err:
        logger.error(f"Transactions Fetch: Database error. Filter: '{user_id_filter_str}'. Error: {db_err}", exc_info=True)
        return jsonify({"error": "Database operation failed while fetching transactions."}), 500
    except Exception as e:
        logger.error(f"Transactions Fetch: An unexpected error occurred. Filter: '{user_id_filter_str}'. Error: {e}", exc_info=True)
        return jsonify({"error": "An unexpected error occurred while fetching transactions."}), 500
    finally:
        if conn and not conn.closed:
            # cursor is managed by 'with' statement
            conn.close()

# --- Security Headers (Conceptual Placeholder) ---
# In a production setup, configure these via a reverse proxy (e.g., Nginx, Caddy) or WSGI server (e.g., Gunicorn).
# Flask middleware can also be used.
# @app.after_request
# def add_security_headers(response):
#     # PCI DSS: Ensure appropriate security headers are set.
#     response.headers['X-Content-Type-Options'] = 'nosniff'
#     response.headers['X-Frame-Options'] = 'DENY' # Or 'SAMEORIGIN' depending on needs
#     # Content-Security-Policy is highly effective but needs careful configuration specific to your frontend.
#     # Example (very restrictive, likely needs adjustment):
#     # response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self';"
#     if request.is_secure: # Only send HSTS if served over HTTPS
#         response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
#     # response.headers['X-XSS-Protection'] = '1; mode=block' # Older header, CSP is generally preferred.
#     # Consider Referrer-Policy, Permissions-Policy as well.
#     return response

if __name__ == '__main__':
    if not DB_PASSWORD:
        logger.critical("CRITICAL: DB_PASSWORD environment variable not set.")
    if not API_SERVICE_PRIVATE_KEY:
        logger.critical("CRITICAL: API_SERVICE_PRIVATE_KEY environment variable not set. Smart contract features will be severely impaired or disabled.")
    if not visa_top_up_contract: # Check if contract object was successfully created
        logger.critical("CRITICAL: Smart contract not loaded. Check deployment_info.json path, Ethereum node connection, and contract address/ABI.")

    # PCI DSS: Ensure FLASK_DEBUG is False in production.
    app.run(
        debug=os.getenv('FLASK_DEBUG', 'True').lower() == 'true', # Should be False in prod
        host='0.0.0.0',
        port=int(os.getenv('API_PORT', 5000))
    )
