# augur budget planner

A new augur tab (`Budget`) and the supporting API for "what does my monthly
spending actually look like, and how much can I afford to change it?"
Pulls live data from the Plaid mirror DB, classifies transactions into named
buckets, nets reimbursable expenses (e.g. medical bills) against their paired
reimbursement deposits, and surfaces lumpy one-offs separately.

## Architecture

| Layer              | What it does                                                                             |
| ------------------ | ---------------------------------------------------------------------------------------- |
| `db.py`            | Async loader over `plaid_utils.schema` — pulls posted (non-pending, non-removed) tx      |
| `schema.py`        | `BudgetConfig` Pydantic: bucket taxonomy + categorization rules (loaded from augur YAML) |
| `default_rules.py` | Generic public-chain rules (DoorDash, Anthropic, Lyft, …). User rules pre-empt these.    |
| `categorize.py`    | Apply rules; unmatched → `default_bucket_id`                                             |
| `aggregate.py`     | Monthly per-bucket totals, rolling-window reimbursement netting, lumpy detection         |
| `service.py`       | Orchestrates: load → classify → aggregate → wire types                                   |
| `wire.py`          | HTTP wire schemas (drive frontend Zod codegen via `export_schema`)                       |

## What lives in ducktape vs gaffer-private

**ducktape (public):** The framework — schemas, rule kinds, the categorizer,
the aggregator, the API endpoints, the frontend tab, the public default-rules
library (major-chain merchants only).

**gaffer-private (private):** The actual `budget:` config block in the
deployment's `Config` YAML, listing the user's specific merchants (medical
providers, therapist, landlord), Plaid account IDs to include, and bucket
overrides. Augur loads this at startup; the framework knows nothing about it
until the YAML is read.

## Adding a `budget:` section to your augur config

```yaml
budget:
  source:
    # ENV var that holds the postgres URL for the plaid mirror DB. In-cluster the
    # secret `plaid-mcp-db-readonly` is reflected to namespace `augur`; mount its
    # DATABASE_URL key as this env var on the augur API Deployment.
    database_url_env: AUGUR_PLAID_DATABASE_URL
    # Optional: subset of plaid_utils.accounts.account_id values to include.
    # Empty = every account the connection sees.
    plaid_account_ids: []

  buckets:
    - { id: rent, label: Rent, kind: expense }
    - { id: utilities, label: Utilities, kind: expense }
    - { id: groceries, label: Groceries, kind: expense }
    - { id: doordash, label: DoorDash, kind: expense }
    - { id: restaurants_in_person, label: Restaurants (in person), kind: expense }
    - { id: ai_subscription, label: AI subscriptions, kind: expense }
    - { id: transportation, label: Transportation, kind: expense }
    - { id: utilities, label: Utilities, kind: expense }
    - { id: insurance, label: Health insurance, kind: expense }
    - { id: taxes, label: Taxes, kind: expense }
    - { id: travel, label: Travel, kind: expense }
    - { id: general_merchandise, label: General merchandise, kind: expense }
    - { id: electronics, label: Electronics, kind: expense }
    - { id: entertainment, label: Entertainment, kind: expense }
    - { id: personal_care, label: Personal care, kind: expense }
    - { id: bank_fees, label: Bank fees, kind: expense }
    - { id: government, label: Government, kind: expense }
    - { id: medical_reimbursement, label: Anthem reimbursements, kind: reimbursement }
    # `kind: reimbursable` buckets net against `reimbursed_by` on a rolling window.
    - { id: esketamine, label: Esketamine (net of Anthem), kind: reimbursable, reimbursed_by: medical_reimbursement }
    - { id: therapy, label: Therapy (net of Anthem), kind: reimbursable, reimbursed_by: medical_reimbursement }
    - { id: medical_other, label: Other medical, kind: expense }
    # Transfers are split by direction so each bucket stays single-sided (the categorizer
    # asserts a transfer bucket never mixes inflow and outflow).
    - { id: transfers_out, label: Transfers out (internal), kind: transfer }
    - { id: transfers_in, label: Transfers in (internal), kind: transfer }
    - { id: income, label: Income, kind: income }
    - { id: other, label: Uncategorized, kind: expense }

  default_bucket_id: other

  # User rules apply BEFORE the public defaults — list private merchants here.
  rules:
    # Example shapes (replace patterns with your actual merchants — these belong
    # in the gaffer-private copy of this YAML, not in ducktape):
    # - { kind: merchant_substring, pattern: <your landlord>, bucket_id: rent }
    # - { kind: merchant_substring, pattern: <esketamine provider>, bucket_id: esketamine }
    # - { kind: merchant_substring, pattern: <therapist>, bucket_id: therapy }
    # - { kind: merchant_substring, pattern: <health insurance broker>, bucket_id: insurance }

  include_default_rules: true
  reimbursement_window_months: 3
  lumpy_threshold_usd: 500
```

## Running the dev server against your live cluster data

The dev script lives in **gaffer-private**, not ducktape, because the real
budget config and trained model artifacts live there. From the gaffer-private
repo root (inside the nix devshell):

```bash
./gaffer_augur/dev_against_prod.sh
```

The script:

1. Reads creds from Secret `plaid-mcp/plaid-mcp-db-readonly`
2. Port-forwards `svc/plaid-mcp-db-rw` → `localhost:15432`
3. Exports `AUGUR_PLAID_DATABASE_URL` pointing at the forward
4. Runs `bazelisk run //gaffer_augur:backend_dev` (which has the trained PE
   artifacts and the private `config.yaml` already wired as data deps)

When the active `Config` has no `budget:` section, `/api/budget/*` returns
400 and the Budget tab shows that error.
