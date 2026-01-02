# No outputs needed
#
# All per-application OIDC client secrets are now managed by individual blueprints
# in terraform/authentik-blueprint/{app}/main.tf and stored directly in Vault at
# kv/sso/{app}. The authentik_api_token is stored in Vault and consumed by
# authentik-blueprint terraform resources via data sources, not via outputs.
