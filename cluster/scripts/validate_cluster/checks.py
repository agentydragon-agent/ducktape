"""Constants for cluster validation checks."""

from __future__ import annotations

# Map CRD kinds to their operator Kustomization names
CRD_TO_OPERATOR: dict[str, str] = {
    # external-secrets-operator
    "ExternalSecret": "external-secrets-operator",
    "ClusterExternalSecret": "external-secrets-operator",
    "SecretStore": "external-secrets-operator",
    "ClusterSecretStore": "external-secrets-operator",
    "Password": "external-secrets-operator",
    "Fake": "external-secrets-operator",
    "VaultDynamicSecret": "external-secrets-operator",
    # cert-manager
    "Certificate": "cert-manager",
    "CertificateRequest": "cert-manager",
    "Issuer": "cert-manager",
    "ClusterIssuer": "cert-manager",
    # kyverno
    "ClusterPolicy": "kyverno",
    "Policy": "kyverno",
    # vault-operator
    "Vault": "vault-operator",
    # tofu-controller
    "Terraform": "tofu-controller",
    # powerdns-operator
    "ClusterZone": "powerdns-operator",
    "ClusterRRset": "powerdns-operator",
}

# These Kustomizations ARE the operators, so they don't need to depend on themselves
OPERATOR_KUSTOMIZATIONS = {
    "external-secrets-operator",
    "external-secrets",  # config kustomization
    "cert-manager",
    "cert-manager-config",
    "cert-manager-trust",
    "cert-manager-environment",
    "kyverno",
    "kyverno-policies",
    "vault-operator",
    "vault",
    "tofu-controller",
    "sealed-secrets",
    "powerdns-operator",
    "cluster-ca",  # Uses cert-manager CRDs but is part of cert-manager layer
}
