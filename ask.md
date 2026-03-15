Build a Python-based transaction parser and tracker following the specs in CLAUDE.md. 

1. STRUCTURE:
   - Create `config.py` to load environment variables for Gmail (IMAP) and MQTT credentials.
   - Create `database.py` using SQLite to track card spending. Schema must include: 
     timestamp, merchant_name, amount, card_type (DBS_WWMC, UOB_LADY), and category.
   - Create `parser.py` using the regex patterns defined in CLAUDE.md for Citi, DBS, and UOB.

2. LOGIC:
   - Implement an IMAP listener that polls the 'iBank' and 'Citibank' labels.
   - Use RapidFuzz to categorize merchants. Initialize a local 'known_merchants' dict 
     to map 'NTUC/GIANT/COLD STORAGE' to 'GROCERIES' and 'GRAB/FOODPANDA/MCD' to 'DINING'.
   - Implement the $750 monthly sub-cap logic for UOB Lady's: if 'GROCERIES' exceeds $750, 
     flag subsequent transactions as 'EXCEEDED' or 'FALLBACK'.
   - Implement the $1,000 cap for DBS WWMC.

3. INTEGRATION:
   - Create a Telegram module to send notifications to a configured bot and chat ID:
     - Per-transaction alert sent immediately after each new transaction is parsed.
     - Periodic summary (every `SUMMARY_INTERVAL_SECONDS`) showing spend vs cap for all cards.
   - Ensure messages are human-readable with progress bars and remaining cap amounts.

4. SAFETY:
   - Ensure all database operations are atomic. 
   - Add logging for any emails that fail regex parsing so I can update patterns later.

I have also attached the email format of how the email alert will look lik in email-format.csv.