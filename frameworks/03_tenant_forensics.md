# Tenant forensics: both sides of the ledger
Read the tenant's and its parent's filed accounts: turnover trend, related-party sales, what net worth is made of, cash paid to owners.
Find the counterparty to the biggest balance and read its accounts from the other side: losses, which secured debt ranks ahead of the tenant, and maturity dates.
Compare lease cost in the accounts with headline rent to get true net rent.
Track filing history: director changes, new charges, share issues, late accounts.
Output: credit view, probability of renewing at lease end, and dated watch-list triggers.

If a "CH dossier" document is in the data room, treat it as the primary source: read the accounts text for related-party notes, amounts owed by/to connected companies, dividends, loans, and the operating-lease note; read the charges register for who ranks ahead; read officers/PSCs for changes. Name every connected company you find and its company number if shown, and list the ones that still need a dossier pulled (put them in "data_room_requests" as "Pull Companies House dossier for <name>").

Mandatory steps when accounts text is available:
1. COUNTERPARTY TIE-OUT. For the largest "owed by connected companies" balance, identify which company owes it. Then compare, in a small table: the tenant's receivable, that company's own payable to "connected companies", the dates of each balance sheet, and the year-on-year movement of both. State plainly if they reconcile, do not reconcile, or cannot be matched. If the receivable grew while turnover fell, say so: the tenant is lending to its affiliates.
2. DEBT MATURITY WALL. For the tenant and every connected company whose accounts you can read, list each borrowing: lender, amount, interest rate, security, and the date it must be repaid. Put the earliest maturity date first. A repayment date that falls before the lease ends is a key finding. If a connected company's accounts are not in the data room, say so and put "Pull Companies House dossier for <name>" in data_room_requests.
3. RELATED-PARTY NOTE. Quote the note: sales to, purchases from, rent contributions, recharges, loans. Separate what the note literally says from what you infer it means. For "contributions towards rent", consider both readings (a subsidy, or connected companies paying for space they occupy in the building) and say which sub-letting or group-occupation questions follow for a landlord (licence to share occupation, who is really in the building).
4. DIVIDENDS vs RESERVES. Compare dividends with profit AND with distributable reserves. Do not call a dividend above one year's profit alarming unless reserves or cash are also thin.
