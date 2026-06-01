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
        "transportation",
        "utilities",
        "entertainment",
        "general_merchandise",
        "electronics",
        "groceries",
        "restaurants_in_person",
        "medical",
        "medical_reimbursement",
        "insurance",
        "taxes",
        "travel",
        "government",
        "transfers",
        "income",
        "bank_fees",
        "personal_care",
        "rent",
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
    # --- Marketplaces / electronics ---
    MerchantSubstringRule(pattern="Amazon", bucket_id="general_merchandise"),
    MerchantSubstringRule(pattern="Target", bucket_id="general_merchandise"),
    MerchantSubstringRule(pattern="Costco", bucket_id="general_merchandise"),
    MerchantSubstringRule(pattern="Dell", bucket_id="electronics"),
    MerchantSubstringRule(pattern="Newegg", bucket_id="electronics"),
    MerchantSubstringRule(pattern="Apple", bucket_id="electronics"),
    MerchantSubstringRule(pattern="B&H Photo", bucket_id="electronics"),
    # --- Government / taxes (US) ---
    NameSubstringRule(pattern="Internal Revenue Service", bucket_id="taxes"),
    NameSubstringRule(pattern="Franchise Tax Board", bucket_id="taxes"),
    MerchantSubstringRule(pattern="Uscis", bucket_id="government"),
    # --- Travel ---
    PfcRule(primary="TRAVEL", detailed="TRAVEL_FLIGHTS", bucket_id="travel"),
    PfcRule(primary="TRAVEL", detailed="TRAVEL_LODGING", bucket_id="travel"),
    # --- Plaid-PFC fallbacks (broad) ---
    PfcRule(primary="RENT_AND_UTILITIES", detailed="RENT_AND_UTILITIES_RENT", bucket_id="rent"),
    PfcRule(primary="RENT_AND_UTILITIES", bucket_id="utilities"),
    PfcRule(primary="FOOD_AND_DRINK", detailed="FOOD_AND_DRINK_GROCERIES", bucket_id="groceries"),
    PfcRule(primary="FOOD_AND_DRINK", bucket_id="restaurants_in_person"),
    PfcRule(primary="MEDICAL", bucket_id="medical"),
    PfcRule(primary="GENERAL_SERVICES", detailed="GENERAL_SERVICES_INSURANCE", bucket_id="insurance"),
    PfcRule(primary="TRANSPORTATION", bucket_id="transportation"),
    PfcRule(primary="GENERAL_MERCHANDISE", detailed="GENERAL_MERCHANDISE_ELECTRONICS", bucket_id="electronics"),
    PfcRule(primary="GENERAL_MERCHANDISE", bucket_id="general_merchandise"),
    PfcRule(primary="ENTERTAINMENT", bucket_id="entertainment"),
    PfcRule(primary="BANK_FEES", bucket_id="bank_fees"),
    PfcRule(primary="PERSONAL_CARE", bucket_id="personal_care"),
    PfcRule(primary="GOVERNMENT_AND_NON_PROFIT", bucket_id="government"),
    PfcRule(primary="TRAVEL", bucket_id="travel"),
    # Transfers / loan payments are internal-account movements, not spending. They get their
    # own bucket so they show in the snapshot but are excluded from net-spend rollups.
    PfcRule(primary="TRANSFER_OUT", bucket_id="transfers"),
    PfcRule(primary="TRANSFER_IN", bucket_id="transfers"),
    PfcRule(primary="LOAN_PAYMENTS", bucket_id="transfers"),
    PfcRule(primary="LOAN_DISBURSEMENTS", bucket_id="transfers"),
    # True income (paychecks) goes last so that more-specific rules (HCCLAIMPMT, brokerage
    # transfers that Plaid mis-tags as INCOME_CONTRACTOR) get the chance to override it.
    PfcRule(primary="INCOME", bucket_id="income"),
)
