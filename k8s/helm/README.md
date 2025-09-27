# Helm Charts

This directory contains Helm charts for the k3s observability stack.

## Chart Organization

### `grafana-operator/`
**Purpose:** Deploys the main Grafana instance
- Uses the official Grafana Helm chart as a dependency
- Contains configuration in `values.yaml` for:
  - TimescaleDB datasource setup
  - Admin credentials
  - Ingress configuration
  - Dashboard provisioning

**Deployment:**
```bash
cd grafana-operator
helm dependency update
helm upgrade --install grafana . --namespace observability
```

### `grafana-dashboards/`
**Purpose:** Manages custom dashboard ConfigMaps
- Contains dashboard definitions as SQL + JSON
- SQL queries are externalized to `sql/` directory
- Uses Helm templating with `Files.Get` for clean organization

**Deployment:**
```bash
cd grafana-dashboards
helm upgrade --install grafana-dashboards . --namespace observability
```

## Architecture

```
Grafana Stack:
├── grafana-operator (Helm chart)
│   ├── Main Grafana deployment
│   ├── TimescaleDB datasource config
│   └── Dashboard provisioning setup
└── grafana-dashboards (Helm chart)
    ├── OpenAI probe dashboard
    ├── SQL queries (external files)
    └── Dashboard JSON templates
```

## Dependencies

1. Deploy TimescaleDB first
2. Deploy grafana-operator
3. Deploy grafana-dashboards

The main Grafana deployment will automatically pick up dashboard ConfigMaps created by the grafana-dashboards chart.