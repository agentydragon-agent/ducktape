# augur budget planner

A new augur tab (`Budget`) and the supporting API for "what does my monthly
spending actually look like, and how much can I afford to change it?"
Pulls live data from the Plaid mirror DB, classifies transactions into named
buckets, groups related buckets into families (e.g. medical: charges +
insurance reimbursements) that show inflows and outflows side by side instead
of force-netting, and surfaces lumpy one-offs separately.

## Architecture

| Layer               | What it does                                                                                                                          |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| `schema.py`         | `BudgetConfig` Pydantic: bucket taxonomy (kinds: expense / inflow / transfer / income) + categorization rules, loaded from augur YAML |
| `default_rules.py`  | Generic public-chain rules (DoorDash, Anthropic, Lyft, …). User rules pre-empt these.                                                 |
| `sql_read_model.py` | Reads Plaid transactions from Postgres, classifies with direction-gated rules, aggregates monthly totals, and returns drilldowns      |
| `service.py`        | Orchestrates request windows, database session reuse, CSV export, and wire types                                                      |
| `wire.py`           | HTTP wire schemas (drive frontend Zod codegen via `export_schema`)                                                                    |

## What lives in ducktape vs gaffer-private

**ducktape (public):** The framework — schemas, rule kinds, the SQL read model,
the API endpoints, the frontend tab, and the public default-rules library
(major-chain merchants only).

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
    - { id: rent, label: Rent, kind: expense, direction: outflow }
    - { id: utilities, label: Utilities, kind: expense, direction: outflow }
    - { id: groceries, label: Groceries, kind: expense, direction: outflow }
    - { id: doordash, label: DoorDash, kind: expense, direction: outflow }
    - { id: restaurants_in_person, label: Restaurants (in person), kind: expense, direction: outflow }
    - { id: ai_subscription, label: AI subscriptions, kind: expense, direction: outflow }
    - { id: transportation, label: Transportation, kind: expense, direction: outflow }
    - { id: insurance, label: Health insurance, kind: expense, direction: outflow }
    - { id: taxes, label: Taxes, kind: expense, direction: outflow }
    - { id: travel, label: Travel, kind: expense, direction: outflow }
    - { id: general_merchandise, label: General merchandise, kind: expense, direction: outflow }
    - { id: electronics, label: Electronics, kind: expense, direction: outflow }
    - { id: entertainment, label: Entertainment, kind: expense, direction: outflow }
    - { id: personal_care, label: Personal care, kind: expense, direction: outflow }
    - { id: bank_fees, label: Bank fees, kind: expense, direction: outflow }
    - { id: government, label: Government, kind: expense, direction: outflow }
    # Related buckets share a `family`; the UI renders them in one panel showing inflow and
    # outflow side by side (no auto-netting -- reimbursement timing is too lumpy to net safely).
    - { id: medical_reimbursement, label: Anthem reimbursements, kind: inflow, direction: inflow, family: medical }
    - { id: esketamine, label: Esketamine, kind: expense, direction: outflow, family: medical }
    - { id: therapy, label: Therapy, kind: expense, direction: outflow, family: medical }
    - { id: medical_other, label: Other medical, kind: expense, direction: outflow, family: medical }
    # Transfers are split by direction so each bucket stays single-sided.
    - { id: transfers_out, label: Transfers out (internal), kind: transfer, direction: outflow }
    - { id: transfers_in, label: Transfers in (internal), kind: transfer, direction: inflow }
    - { id: income, label: Income, kind: income, direction: inflow }
    - { id: other, label: Uncategorized, kind: expense, direction: outflow }
    - { id: other_in, label: Uncategorized inflow, kind: inflow, direction: inflow }

  default_outflow_bucket_id: other
  default_inflow_bucket_id: other_in

  # User rules apply BEFORE the public defaults — list private merchants here.
  rules:
    # Example shapes (replace patterns with your actual merchants — these belong
    # in the gaffer-private copy of this YAML, not in ducktape):
    # - { kind: merchant_substring, pattern: <your landlord>, bucket_id: rent }
    # - { kind: merchant_substring, pattern: <esketamine provider>, bucket_id: esketamine }
    # - { kind: merchant_substring, pattern: <therapist>, bucket_id: therapy }
    # - { kind: merchant_substring, pattern: <health insurance broker>, bucket_id: insurance }

  include_default_rules: true
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
