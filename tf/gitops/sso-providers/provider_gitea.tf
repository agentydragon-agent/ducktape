# ============================================================================
# Gitea — OIDC login for the git server (suspended)
# ============================================================================

resource "authentik_provider_oauth2" "gitea" {
  name               = "gitea-oauth2"
  client_id          = "gitea"
  client_type        = "confidential"
  authorization_flow = data.authentik_flow.implicit_consent.id
  invalidation_flow  = data.authentik_flow.invalidation.id
  signing_key        = data.authentik_certificate_key_pair.self_signed.id

  issuer_mode                = "per_provider"
  include_claims_in_id_token = true

  property_mappings = [
    data.authentik_property_mapping_provider_scope.openid.id,
    data.authentik_property_mapping_provider_scope.email.id,
    data.authentik_property_mapping_provider_scope.profile.id,
  ]

  allowed_redirect_uris = [
    {
      matching_mode = "strict"
      url           = "https://git.allegedly.works/user/oauth2/authentik/callback"
    },
  ]
}

resource "authentik_application" "gitea" {
  name              = "Gitea"
  slug              = "gitea"
  protocol_provider = authentik_provider_oauth2.gitea.id
  meta_description  = "Gitea Git Repository Management"
  meta_publisher    = "Gitea"
  meta_icon         = "https://cdn.simpleicons.org/gitea"
  open_in_new_tab   = true
}

resource "authentik_policy_binding" "gitea_admins" {
  target = authentik_application.gitea.uuid
  group  = data.authentik_group.admins.id
  order  = 0
}

# Gitea helm chart expects keys named "key" (client_id) and "secret" (client_secret).
resource "kubernetes_secret" "gitea_oauth" {
  metadata {
    name      = "gitea-oauth-client-secret"
    namespace = "authentik"
    annotations = {
      "reflector.v1.k8s.emberstack.com/reflection-allowed"            = "true"
      "reflector.v1.k8s.emberstack.com/reflection-allowed-namespaces" = "gitea,flux-system"
      "reflector.v1.k8s.emberstack.com/reflection-auto-enabled"       = "true"
      "reflector.v1.k8s.emberstack.com/reflection-auto-namespaces"    = "gitea,flux-system"
    }
  }

  data = {
    key    = authentik_provider_oauth2.gitea.client_id
    secret = authentik_provider_oauth2.gitea.client_secret
  }
}
