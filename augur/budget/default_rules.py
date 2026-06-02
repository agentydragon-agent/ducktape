"""Public, generic categorization rules for the budget planner.

Only major public-chain merchants and Plaid `personal_finance_category` mappings -- no
user-specific names. Deployments add their own rules in YAML; those take precedence
because they're applied before this list."""

from __future__ import annotations

from augur.budget.schema import MerchantSubstringRule, NameSubstringRule, PfcRule, Rule

# Public bucket ids these rules assume the user's BudgetConfig defines. Deployments that
# rename buckets must either match these ids or set `include_default_rules=False`.
DEFAULT_BUCKET_IDS = frozenset(
    {
        "doordash",
        "ai_subscription",
        "cloud_infra",
        "transportation",
        "utilities",
        "entertainment",
        "general_merchandise",
        "electronics",
        "groceries",
        "restaurants_in_person",
        "medical",
        "medical_reimbursement",
        "supplements",
        "insurance",
        "taxes",
        "travel",
        "government",
        "transfers",
        "income",
        "bank_fees",
        "personal_care",
        "rent",
        "postage",
        "donations",
        "home_improvement",
    }
)


# Order matters: merchant/name patterns first (they pre-empt the broad PFC fallbacks),
# then PFC-based defaults. First match wins.
DEFAULT_RULES: tuple[Rule, ...] = (
    # --- Health-insurance reimbursements (must precede generic INCOME PFC rule) ---
    NameSubstringRule(pattern="HCCLAIMPMT", bucket_id="medical_reimbursement"),
    # --- DoorDash sub-merchant pass-through. Plaid's `merchant_name` is the sub-restaurant,
    # but `name` always begins with "DD *DOORDASH". Matching by name aggregates them all.
    NameSubstringRule(pattern="DD *DOORDASH", bucket_id="doordash"),
    # --- AI / LLM subscriptions ---
    MerchantSubstringRule(pattern="Anthropic", bucket_id="ai_subscription"),
    MerchantSubstringRule(pattern="OpenAI", bucket_id="ai_subscription"),
    MerchantSubstringRule(pattern="Claude", bucket_id="ai_subscription"),
    # Stripe is the billing layer for many AI services; "Stripe-z.ai" is the chat.z.ai
    # subscription line item. Also captures any other Stripe-billed AI vendor labelled
    # with its product name after the dash.
    MerchantSubstringRule(pattern="Stripe-z.ai", bucket_id="ai_subscription"),
    # --- Cloud / infra / dev tooling (recurring subscriptions to ops chains) ---
    MerchantSubstringRule(pattern="Hetzner", bucket_id="cloud_infra"),
    MerchantSubstringRule(pattern="Linode", bucket_id="cloud_infra"),
    # Plaid frequently mistags OVH as MEDICAL_PRIMARY_CARE; the merchant_substring rule
    # fires before the PFC fallback, so it lands in cloud_infra anyway.
    MerchantSubstringRule(pattern="OVH", bucket_id="cloud_infra"),
    MerchantSubstringRule(pattern="GitHub", bucket_id="cloud_infra"),
    MerchantSubstringRule(pattern="Cloudflare", bucket_id="cloud_infra"),
    MerchantSubstringRule(pattern="DigitalOcean", bucket_id="cloud_infra"),
    # --- Transportation ---
    MerchantSubstringRule(pattern="Lyft", bucket_id="transportation"),
    MerchantSubstringRule(pattern="Uber", bucket_id="transportation"),
    MerchantSubstringRule(pattern="Waymo", bucket_id="transportation"),
    # --- Utilities / telephony (major chains; specific local utilities go in user rules) ---
    MerchantSubstringRule(pattern="PG&E", bucket_id="utilities"),
    MerchantSubstringRule(pattern="Google Fi", bucket_id="utilities"),
    MerchantSubstringRule(pattern="Comcast", bucket_id="utilities"),
    MerchantSubstringRule(pattern="Xfinity", bucket_id="utilities"),
    # --- Entertainment / digital ---
    MerchantSubstringRule(pattern="Steam", bucket_id="entertainment"),
    MerchantSubstringRule(pattern="Patreon", bucket_id="entertainment"),
    MerchantSubstringRule(pattern="Spotify", bucket_id="entertainment"),
    MerchantSubstringRule(pattern="Netflix", bucket_id="entertainment"),
    MerchantSubstringRule(pattern="Substack", bucket_id="entertainment"),
    # --- Marketplaces / electronics ---
    MerchantSubstringRule(pattern="Amazon", bucket_id="general_merchandise"),
    MerchantSubstringRule(pattern="Target", bucket_id="general_merchandise"),
    MerchantSubstringRule(pattern="Costco", bucket_id="general_merchandise"),
    MerchantSubstringRule(pattern="Dell", bucket_id="electronics"),
    MerchantSubstringRule(pattern="Newegg", bucket_id="electronics"),
    MerchantSubstringRule(pattern="Apple", bucket_id="electronics"),
    MerchantSubstringRule(pattern="B&H Photo", bucket_id="electronics"),
    # --- Pharmacy chains (supplements / OTC) ---
    MerchantSubstringRule(pattern="CVS", bucket_id="supplements"),
    MerchantSubstringRule(pattern="Walgreens", bucket_id="supplements"),
    # --- Postage / shipping ---
    MerchantSubstringRule(pattern="FedEx", bucket_id="postage"),
    MerchantSubstringRule(pattern="UPS", bucket_id="postage"),
    MerchantSubstringRule(pattern="U.S. Post Office", bucket_id="postage"),
    MerchantSubstringRule(pattern="Mailform", bucket_id="postage"),
    # --- Donations / civic ---
    MerchantSubstringRule(pattern="Internet Archive", bucket_id="donations"),
    MerchantSubstringRule(pattern="Open Source Collective", bucket_id="donations"),
    MerchantSubstringRule(pattern="ACLU", bucket_id="donations"),
    MerchantSubstringRule(pattern="Wikimedia", bucket_id="donations"),
    # --- Home improvement / hardware chains ---
    MerchantSubstringRule(pattern="Home Depot", bucket_id="home_improvement"),
    MerchantSubstringRule(pattern="Lowe", bucket_id="home_improvement"),
    MerchantSubstringRule(pattern="Discount Builders Supply", bucket_id="home_improvement"),
    # --- Government / taxes (US) ---
    # Plaid populates `merchant_name` cleanly ("Internal Revenue Service", "Franchise Tax
    # Board") but stamps the raw `name` field with the ACH descriptor ("IRS DES:USATAXPYMT..."
    # / "FRANCHISE TAX BO DES:PAYMENTS..."), so merchant_substring matches and name_substring
    # does not.
    MerchantSubstringRule(pattern="Internal Revenue Service", bucket_id="taxes"),
    MerchantSubstringRule(pattern="Franchise Tax Board", bucket_id="taxes"),
    MerchantSubstringRule(pattern="Uscis", bucket_id="government"),
    # --- Travel ---
    PfcRule(primary="TRAVEL", detailed="TRAVEL_FLIGHTS", bucket_id="travel"),
    PfcRule(primary="TRAVEL", detailed="TRAVEL_LODGING", bucket_id="travel"),
    # --- Plaid-PFC fallbacks (broad) ---
    PfcRule(primary="RENT_AND_UTILITIES", detailed="RENT_AND_UTILITIES_RENT", bucket_id="rent"),
    PfcRule(primary="RENT_AND_UTILITIES", bucket_id="utilities"),
    PfcRule(primary="FOOD_AND_DRINK", detailed="FOOD_AND_DRINK_GROCERIES", bucket_id="groceries"),
    PfcRule(primary="FOOD_AND_DRINK", bucket_id="restaurants_in_person"),
    PfcRule(primary="MEDICAL", detailed="MEDICAL_PHARMACIES_AND_SUPPLEMENTS", bucket_id="supplements"),
    PfcRule(primary="MEDICAL", bucket_id="medical"),
    PfcRule(primary="GENERAL_SERVICES", detailed="GENERAL_SERVICES_INSURANCE", bucket_id="insurance"),
    PfcRule(primary="GENERAL_SERVICES", detailed="GENERAL_SERVICES_POSTAGE_AND_SHIPPING", bucket_id="postage"),
    PfcRule(primary="HOME_IMPROVEMENT", bucket_id="home_improvement"),
    PfcRule(primary="TRANSPORTATION", bucket_id="transportation"),
    PfcRule(primary="GENERAL_MERCHANDISE", detailed="GENERAL_MERCHANDISE_ELECTRONICS", bucket_id="electronics"),
    PfcRule(primary="GENERAL_MERCHANDISE", bucket_id="general_merchandise"),
    PfcRule(primary="ENTERTAINMENT", bucket_id="entertainment"),
    PfcRule(primary="BANK_FEES", bucket_id="bank_fees"),
    PfcRule(primary="PERSONAL_CARE", bucket_id="personal_care"),
    # Donations land under GOVERNMENT_AND_NON_PROFIT_DONATIONS in Plaid's taxonomy; route them
    # to `donations` before the catch-all GOVERNMENT_AND_NON_PROFIT rule below (which is for
    # actual government payments like USCIS / IRS via the merchant rules above).
    PfcRule(primary="GOVERNMENT_AND_NON_PROFIT", detailed="GOVERNMENT_AND_NON_PROFIT_DONATIONS", bucket_id="donations"),
    PfcRule(primary="GOVERNMENT_AND_NON_PROFIT", bucket_id="government"),
    PfcRule(primary="TRAVEL", bucket_id="travel"),
    # Transfers / loan payments are internal-account movements, not spending. They get their
    # own bucket so they show in the snapshot but are excluded from net-spend rollups.
    PfcRule(primary="TRANSFER_OUT", bucket_id="transfers"),
    PfcRule(primary="TRANSFER_IN", bucket_id="transfers"),
    PfcRule(primary="LOAN_PAYMENTS", bucket_id="transfers"),
    PfcRule(primary="LOAN_DISBURSEMENTS", bucket_id="transfers"),
    # Tax refunds aren't "income" -- they're a return of taxes the user already paid, and
    # augur's tax model accounts for the actual burden separately. Route to `taxes` (transfer
    # kind) so the refund doesn't double-count against income / inflate spendable monthly avg.
    PfcRule(primary="INCOME", detailed="INCOME_TAX_REFUND", bucket_id="taxes"),
    # True income (paychecks) goes last so that more-specific rules (HCCLAIMPMT, brokerage
    # transfers that Plaid mis-tags as INCOME_CONTRACTOR) get the chance to override it.
    PfcRule(primary="INCOME", bucket_id="income"),
)
