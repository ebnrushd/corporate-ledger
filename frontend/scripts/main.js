/**
 * Main JavaScript for handling the Visa Top-Up initiation form.
 */
document.addEventListener('DOMContentLoaded', () => {
    const topUpForm = document.getElementById('topUpForm');
    const responseMessageDiv = document.getElementById('responseMessage');

    const topUpForm = document.getElementById('topUpForm');
    const responseMessageDiv = document.getElementById('responseMessage');

    // === Logic for initiate_topup.html ===
    if (topUpForm) {
        topUpForm.addEventListener('submit', async (event) => {
            event.preventDefault(); // Prevent default HTML form submission

            // Clear previous messages
            responseMessageDiv.textContent = '';
            responseMessageDiv.className = ''; // Clear existing success/error classes

            // Get form data
            const userId = document.getElementById('userId').value;
            const amount = parseFloat(document.getElementById('amount').value);
            // PCI DSS: Handling visaCardLastFour. Ensure secure transmission (HTTPS) by the fetch call.
            // Avoid logging this value here unless for debug purposes in a secure, controlled environment.
            const visaCardLastFour = document.getElementById('visaCardLastFour').value;

            // Basic client-side validation (though server-side is crucial)
            if (!userId || isNaN(amount) || amount <= 0 || !visaCardLastFour || !/^\d{4}$/.test(visaCardLastFour)) {
                responseMessageDiv.textContent = 'Error: Please fill in all fields correctly. Visa last four must be 4 digits.';
                responseMessageDiv.className = 'error';
                return;
            }

            // Construct JSON payload
            const payload = {
                user_id: userId, // Ensure this key matches what the API expects
                amount: amount,
                visa_card_last_four: visaCardLastFour
            };

            // API endpoint URL (assuming integration_service is running on localhost:5000)
            const apiUrl = 'http://localhost:5000/topup/initiate';

            try {
                responseMessageDiv.textContent = 'Processing...';
                responseMessageDiv.className = '';

                const response = await fetch(apiUrl, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify(payload),
                });

                const responseData = await response.json(); // Try to parse JSON regardless of response.ok

                if (response.ok) {
                    // Handle successful API response (e.g., 200, 201, 202)
                    let successMsg = `Success: ${responseData.message || 'Request accepted.'}\n`;
                    successMsg += `Internal Transaction ID: ${responseData.internal_transaction_id}\n`;
                    successMsg += `Smart Contract Top-Up ID: ${responseData.smart_contract_top_up_id}\n`;
                    if (responseData.smart_contract_tx_hash) {
                        successMsg += `Smart Contract Tx Hash: ${responseData.smart_contract_tx_hash}\n`;
                    }
                    if (responseData.visa_api_status) {
                        successMsg += `Visa API Status: ${responseData.visa_api_status}\n`;
                    }
                    if (responseData.visa_transaction_id) {
                        successMsg += `Visa Transaction ID: ${responseData.visa_transaction_id}\n`;
                    }
                    responseMessageDiv.textContent = successMsg.trim();
                    responseMessageDiv.className = 'success';
                    topUpForm.reset(); // Optionally reset the form on success
                } else {
                    // Handle error responses from the API (e.g., 400, 404, 500)
                    responseMessageDiv.textContent = `Error: ${responseData.error || response.statusText || 'Unknown error occurred.'}`;
                    responseMessageDiv.className = 'error';
                }
            } catch (error) {
                // Handle network errors or issues with the fetch call itself
                console.error('Fetch error:', error);
                responseMessageDiv.textContent = 'Network error or server is unreachable. Please try again.';
                responseMessageDiv.className = 'error';
            }
        });
    } else {
        // console.warn('Top-up form not found on this page.'); // It's okay if not on history page
    }

    // === Logic for transaction_history.html ===
    const fetchHistoryButton = document.getElementById('fetchHistoryButton');
    const transactionHistoryTableBody = document.getElementById('transactionHistoryTableBody');
    const historyResponseMessageDiv = document.getElementById('historyResponseMessage');
    const filterUserIdInput = document.getElementById('filterUserId');

    if (fetchHistoryButton) {
        fetchHistoryButton.addEventListener('click', async () => {
            historyResponseMessageDiv.textContent = 'Loading transaction history...';
            historyResponseMessageDiv.className = 'info';
            transactionHistoryTableBody.innerHTML = ''; // Clear previous results

            let apiUrl = 'http://localhost:5000/transactions';
            const userId = filterUserIdInput.value.trim();
            if (userId) {
                apiUrl += `?user_id=${encodeURIComponent(userId)}`;
            }

            try {
                const response = await fetch(apiUrl);
                const responseData = await response.json(); // Expecting JSON from the new endpoint

                if (response.ok) {
                    if (responseData && responseData.length > 0) {
                        historyResponseMessageDiv.textContent = `Successfully fetched ${responseData.length} transactions.`;
                        historyResponseMessageDiv.className = 'success';

                        responseData.forEach(tx => {
                            const row = transactionHistoryTableBody.insertRow();

                            row.insertCell().textContent = tx.transaction_id || 'N/A';
                            row.insertCell().textContent = tx.sender_account_id || 'N/A';
                            row.insertCell().textContent = tx.receiver_account_id || 'N/A';
                            row.insertCell().textContent = tx.amount !== null ? parseFloat(tx.amount).toFixed(2) : 'N/A';
                            row.insertCell().textContent = tx.currency || 'N/A';
                            row.insertCell().textContent = tx.transaction_type || 'N/A';
                            row.insertCell().textContent = tx.status || 'N/A';

                            const descriptionCell = row.insertCell();
                            descriptionCell.textContent = tx.description || 'N/A';
                            descriptionCell.title = tx.description || 'N/A'; // Show full on hover
                            descriptionCell.classList.add('description-cell');


                            row.insertCell().textContent = tx.created_at ? new Date(tx.created_at).toLocaleString() : 'N/A';
                            row.insertCell().textContent = tx.updated_at ? new Date(tx.updated_at).toLocaleString() : 'N/A';
                        });
                    } else {
                        historyResponseMessageDiv.textContent = 'No transactions found for the given criteria.';
                        historyResponseMessageDiv.className = 'info';
                    }
                } else {
                    historyResponseMessageDiv.textContent = `Error fetching history: ${responseData.error || response.statusText || 'Unknown server error.'}`;
                    historyResponseMessageDiv.className = 'error';
                }
            } catch (error) {
                console.error('Fetch error for transaction history:', error);
                historyResponseMessageDiv.textContent = 'Network error or server is unreachable while fetching history.';
                historyResponseMessageDiv.className = 'error';
            }
        });
    } else {
        // console.warn('Fetch history button not found on this page.'); // It's okay if not on topup page
    }

    // === Logic for login.html ===
    const loginForm = document.getElementById('loginForm');
    const loginResponseMessageDiv = document.getElementById('loginResponseMessage');

    if (loginForm) {
        loginForm.addEventListener('submit', (event) => {
            event.preventDefault(); // Prevent default HTML form submission

            const username = document.getElementById('username').value;
            // const password = document.getElementById('password').value; // Password not used in simulation

            loginResponseMessageDiv.className = 'info';
            loginResponseMessageDiv.textContent = `Login attempt for '${username}'. Simulating successful login...`;

            // Simulate successful login by redirecting after a short delay
            // In a real application, this would involve:
            // 1. Sending credentials to a backend authentication endpoint.
            // 2. Receiving a token (e.g., JWT) or session cookie upon successful authentication.
            // 3. Storing the token/session info securely.
            // 4. Redirecting to a protected page.

            setTimeout(() => {
                // Redirect to the top-up initiation page as a placeholder for a logged-in area
                window.location.href = 'initiate_topup.html';
            }, 1500); // Delay for 1.5 seconds to show the message
        });
    } else {
        // console.warn('Login form not found on this page.');
    }
});
