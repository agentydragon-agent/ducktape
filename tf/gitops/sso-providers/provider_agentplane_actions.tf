# Action-only JWT-bearer target. See x/agentplane/docs/operator_federation.md for
# the pinned Authentik/provider source proving the subject mapping and grant.
# Native provider federation preserves the AccessToken's database user. Keep
# the destination subject allowlist even though Authentik also checks policy.
resource "authentik_provider_oauth2" "agentplane_actions" {
  name                  = "agentplane-actions"
  client_id             = "agentplane-actions"
  client_type           = "confidential"
  authorization_flow    = data.authentik_flow.implicit_consent.id
  invalidation_flow     = data.authentik_flow.invalidation.id
  signing_key           = data.authentik_certificate_key_pair.self_signed.id
  access_token_validity = "minutes=1"
  issuer_mode           = "per_provider"
  sub_mode              = "user_uuid"

  jwt_federation_providers = [authentik_provider_oauth2.agentplane_staging.id]
  jwt_federation_sources   = []
  property_mappings        = [data.authentik_property_mapping_provider_scope.openid.id]
  # No interactive redirects. The generated client secret is never distributed.
}

resource "authentik_application" "agentplane_actions" {
  name              = "Agentplane Actions"
  slug              = "agentplane-actions"
  protocol_provider = authentik_provider_oauth2.agentplane_actions.id
  meta_description  = "Action decisions with the operator's own federated Authentik identity"
}

# Defense in depth: Authentik 2026.2.1's native client-credentials grant checks
# target policy with the source token's user. The service still independently
# authorizes the exact target issuer/sub; signature or login policy alone is not enough.
resource "authentik_policy_binding" "agentplane_actions_access" {
  target = authentik_application.agentplane_actions.uuid
  user   = tonumber(authentik_user.agentydragon.id)
  order  = 0
}

# Resolve the existing managed user by primary key, NEVER by display name or a
# newly provisioned identity. The provider's CoreUsersRetrieve response exposes
# uid and uuid; no token exchange, guessed UUID, or local hash derivation needed.
data "authentik_user" "agentplane_operator" {
  pk = tonumber(authentik_user.agentydragon.id)
}

locals {
  agentplane_actions_issuer = "https://auth.allegedly.works/application/o/${authentik_application.agentplane_actions.slug}/"
  agentplane_operator_oidc = {
    issuer   = local.agentplane_actions_issuer
    audience = authentik_provider_oauth2.agentplane_actions.client_id
    jwks_uri = "${local.agentplane_actions_issuer}jwks/"
    subjects = [
      data.authentik_user.agentplane_operator.uuid,
      data.authentik_user.agentplane_acceptance_operator.uuid,
    ]
  }
  agentplane_action_federation = {
    service_url    = "http://agentplane-actions.agentplane-staging.svc.cluster.local:8080"
    token_endpoint = "https://auth.allegedly.works/application/o/token/"
    login_jwks_uri = "https://auth.allegedly.works/application/o/${authentik_application.agentplane_staging.slug}/jwks/"
    target         = local.agentplane_operator_oidc
    subject_mapping = {
      # Authentik's hashed_user_id subject mode emits sha256(user.uid), not the raw uid.
      # Keep the source-provider hash and target-provider UUID explicit: neither token is
      # trusted to choose the destination subject, and the target allowlist remains separate.
      (sha256(data.authentik_user.agentplane_operator.uid))            = data.authentik_user.agentplane_operator.uuid
      (sha256(data.authentik_user.agentplane_acceptance_operator.uid)) = data.authentik_user.agentplane_acceptance_operator.uuid
    }
    scope = "openid"
  }
}

# The existing reflector/reloader path distributes configuration computed from
# Authentik, not a shared operator credential. Each process parses its JSON env
# field using its existing Settings source. One local object is both verifiers'
# pin set, including the destination's mandatory operator subject allowlist.
resource "kubernetes_secret" "agentplane_action_federation" {
  metadata {
    name      = "agentplane-action-federation"
    namespace = "authentik"
    annotations = {
      description                                                     = "Agentplane operator federation pins (no bearer or client secret)"
      "reflector.v1.k8s.emberstack.com/reflection-allowed"            = "true"
      "reflector.v1.k8s.emberstack.com/reflection-allowed-namespaces" = "agentplane-staging"
      "reflector.v1.k8s.emberstack.com/reflection-auto-enabled"       = "true"
      "reflector.v1.k8s.emberstack.com/reflection-auto-namespaces"    = "agentplane-staging"
    }
  }
  data = {
    action-federation = jsonencode(local.agentplane_action_federation)
    operator-oidc     = jsonencode(local.agentplane_operator_oidc)
  }
  lifecycle {
    precondition {
      condition     = data.authentik_user.agentplane_operator.uid != "" && data.authentik_user.agentplane_operator.uuid != ""
      error_message = "The managed operator must have authoritative Authentik uid and uuid values."
    }
  }
}
