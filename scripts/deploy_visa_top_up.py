"""
Placeholder script for deploying the VisaTopUp.sol smart contract.

Prerequisites:
1. Python 3.7+ installed.
2. Web3.py library installed (`pip install web3`).
3. Solidity compiler (`solc`) accessible in your PATH or `solcx` Python library (`pip install py-solc-x`).
4. Access to an Ethereum node (e.g., a local Ganache instance, Infura, Alchemy).
   For local testing, Ganache (https://trufflesuite.com/ganache/) is recommended.

This script is a template and requires configuration of:
- Solidity compiler path/command (if not using solcx auto-detect).
- Ethereum node URL.
- Account private key for deployment (ensure it's funded on the target network).
"""

import json
import os
from web3 import Web3
from solcx import compile_source, install_solc, get_installed_solc_versions

# --- Configuration ---
# Ensure these are set according to your environment
SOLIDITY_CONTRACT_PATH = "../smart_contracts/VisaTopUp.sol" # Relative path to the contract
ETH_NODE_URL = "http://127.0.0.1:8545"  # Example: Ganache default, Infura, Alchemy
DEPLOYER_PRIVATE_KEY = "YOUR_PRIVATE_KEY_HERE" # Replace with your private key (with 0x prefix)
# Warning: Do not commit actual private keys to version control. Use environment variables or a secure wallet.

GAS_LIMIT = 2000000  # Adjust as needed
GAS_PRICE_GWEI = 20   # Adjust based on network conditions (for testnets/mainnet)

def compile_contract(contract_path):
    """
    Compiles the Solidity smart contract.
    """
    print(f"Attempting to compile {contract_path}...")
    try:
        # Check if solc is installed, if not, install a version (e.g., 0.8.18)
        if not get_installed_solc_versions():
            print("solc not found. Attempting to install solc 0.8.18...")
            install_solc("0.8.18")
            print("solc 0.8.18 installed.")

        with open(contract_path, 'r') as file:
            source_code = file.read()

        compiled_sol = compile_source(
            source_code,
            output_values=['abi', 'bin'],
            solc_version='0.8.18' # Specify the version used in your contract
        )
        contract_interface = compiled_sol[f'<stdin>:{os.path.basename(contract_path).split(".")[0]}'] # Adjust key based on actual output
        return contract_interface['abi'], contract_interface['bin']
    except Exception as e:
        print(f"Error compiling contract: {e}")
        print("Please ensure solc is installed and configured correctly, or use py-solc-x.")
        print("You might need to specify the contract name precisely if it's not auto-detected correctly.")
        # Example key: '<stdin>:VisaTopUp'
        # To see keys in compiled_sol: print(compiled_sol.keys())
        raise

def deploy_contract(w3, abi, bytecode, deployer_account):
    """
    Deploys the compiled contract to the connected Ethereum network.
    """
    print(f"Deploying contract from account: {deployer_account.address}")
    Contract = w3.eth.contract(abi=abi, bytecode=bytecode)

    # Estimate gas
    try:
        gas_estimate = Contract.constructor().estimate_gas({'from': deployer_account.address})
        print(f"Estimated gas for deployment: {gas_estimate}")
    except Exception as e:
        print(f"Could not estimate gas, using default: {GAS_LIMIT}. Error: {e}")
        gas_estimate = GAS_LIMIT


    # Build transaction
    tx_hash = Contract.constructor().transact({
        'from': deployer_account.address,
        'gas': gas_estimate + 50000, # Adding some buffer
        'gasPrice': w3.to_wei(GAS_PRICE_GWEI, 'gwei')
        # 'nonce': w3.eth.get_transaction_count(deployer_account.address) # Optional: manage nonce manually
    })

    print(f"Deployment transaction sent. Tx hash: {tx_hash.hex()}")

    # Wait for transaction receipt
    print("Waiting for transaction receipt...")
    tx_receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300) # 300s timeout

    print(f"Contract deployed successfully!")
    print(f"Contract Address: {tx_receipt.contractAddress}")
    return tx_receipt.contractAddress

def main():
    """
    Main deployment function.
    """
    print("--- VisaTopUp Contract Deployment Script ---")

    if DEPLOYER_PRIVATE_KEY == "YOUR_PRIVATE_KEY_HERE":
        print("\nERROR: Please replace 'YOUR_PRIVATE_KEY_HERE' with an actual deployer private key.")
        print("This script will not run without a valid private key.")
        return

    # 1. Compile the contract
    # This step is conceptual if using pre-compiled ABI/Bytecode from Hardhat/Truffle.
    # For this script, we use py-solc-x.
    print("\nStep 1: Compiling Contract...")
    try:
        abi, bytecode = compile_contract(SOLIDITY_CONTRACT_PATH)
        print("Contract compiled successfully.")
        # print("\nABI:", json.dumps(abi, indent=2))
        # print("\nBytecode:", bytecode)
    except Exception as e:
        print(f"Failed to compile contract: {e}")
        return

    # 2. Connect to Ethereum node
    print("\nStep 2: Connecting to Ethereum Node...")
    w3 = Web3(Web3.HTTPProvider(ETH_NODE_URL))
    if not w3.is_connected():
        print(f"Failed to connect to Ethereum node at {ETH_NODE_URL}")
        return
    print(f"Successfully connected to Ethereum node. Chain ID: {w3.eth.chain_id}")

    # 3. Set up deployer account
    print("\nStep 3: Setting up Deployer Account...")
    try:
        deployer_account = w3.eth.account.from_key(DEPLOYER_PRIVATE_KEY)
        print(f"Using deployer account: {deployer_account.address}")
        # Check balance (optional)
        balance = w3.eth.get_balance(deployer_account.address)
        print(f"Deployer balance: {w3.from_wei(balance, 'ether')} ETH")
        if balance == 0:
            print("Warning: Deployer account has no ETH. Deployment will likely fail.")
    except Exception as e:
        print(f"Error setting up deployer account: {e}. Ensure private key is correct and has '0x' prefix.")
        return

    # 4. Deploy the contract
    print("\nStep 4: Deploying Contract...")
    try:
        contract_address = deploy_contract(w3, abi, bytecode, deployer_account)
        if contract_address:
            print(f"\n--- Deployment Summary ---")
            print(f"VisaTopUp Contract Address: {contract_address}")
            print(f"Network: {ETH_NODE_URL} (Chain ID: {w3.eth.chain_id})")
            print(f"Deployed by: {deployer_account.address}")

            # Save contract address and ABI for interaction script
            deployment_info = {
                "contract_address": contract_address,
                "abi": abi,
                "network_url": ETH_NODE_URL,
                "chain_id": w3.eth.chain_id
            }
            with open("deployment_info.json", "w") as f:
                json.dump(deployment_info, f, indent=4)
            print("\nDeployment info saved to deployment_info.json")

    except Exception as e:
        print(f"Contract deployment failed: {e}")

if __name__ == "__main__":
    # This is a placeholder script.
    # To actually run it:
    # 1. Ensure Ganache or another Ethereum node is running at ETH_NODE_URL.
    # 2. Replace DEPLOYER_PRIVATE_KEY with a valid private key from your node (e.g., from Ganache).
    # 3. Make sure VisaTopUp.sol is at the correct SOLIDITY_CONTRACT_PATH.
    # 4. Run `python deploy_visa_top_up.py`
    main()
    print("\n--- Script Finished ---")
    print("Remember this is a placeholder; execution requires a configured environment.")
    print("If you encountered 'solc' errors, ensure it's installed or use a pre-compiled ABI/Bytecode approach.")
