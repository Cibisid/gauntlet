# Gauntlet observability

Prometheus scrapes the Gauntlet data-plane proxy and evaluates alert rules; Grafana shows one dashboard.

```
prometheus/prometheus.yml                    scrape gauntlet-proxy:8080 every 5s, load alerts.yml
prometheus/alerts.yml                        alert rules
grafana/provisioning/datasources/prometheus.yml   Prometheus datasource (uid "prometheus", http://prometheus:9090)
grafana/provisioning/dashboards/dashboards.yml    file provider reading /var/lib/grafana/dashboards
grafana/dashboards/gauntlet.json             the dashboard
runbooks.md                                  one runbook per alert
```

## Running

These are wired into `docker-compose.yml` as two services on the same network as `gauntlet-proxy`. The mounts they need:

```yaml
  prometheus:
    image: prom/prometheus:v2.53.0
    ports: ["127.0.0.1:9090:9090"]
    volumes:
      - ./deploy/observability/prometheus:/etc/prometheus:ro
    command: ["--config.file=/etc/prometheus/prometheus.yml"]

  grafana:
    image: grafana/grafana:11.1.0
    ports: ["127.0.0.1:3000:3000"]
    depends_on: [prometheus]
    volumes:
      - ./deploy/observability/grafana/provisioning:/etc/grafana/provisioning:ro
      - ./deploy/observability/grafana/dashboards:/var/lib/grafana/dashboards:ro
```

Then `docker compose up`, open Prometheus at http://localhost:9090 (Status > Targets should show `gauntlet-proxy` UP; Alerts lists the rules) and Grafana at http://localhost:3000 (default login admin/admin) under Dashboards > Gauntlet > "Gauntlet proxy".

No Alertmanager is configured, so alerts show in the Prometheus UI only. Add an `alerting:` block to `prometheus.yml` to route them.

Validate after editing:

```
promtool check config prometheus/prometheus.yml   # also checks alerts.yml
promtool check rules prometheus/alerts.yml
```

## Dashboard panels

A `Release` dropdown at the top filters every per-release panel. Rollbacks are also drawn as red annotations on all time series.

| Panel | Shows |
|---|---|
| Request rate by release | Requests/s per release, all statuses |
| Error rate by release | `status="error"` share of requests; red line at 2% |
| Latency p50 / p95 by release | Histogram quantiles; red line at the 1.5s SLO |
| Traffic weight by release | Canary traffic share per release (0..1) |
| Online score by release | Rolling online quality score; line at 0.9 |
| Guardrail blocks by check | Blocks/s stacked by check |
| Tokens per second | Input and output tokens/s per release |
| Cost per request | USD cost rate divided by request rate |
| Rollbacks / Rollback events | Count in range, and when they happened |

Error rate counts only `status="error"`. Blocked requests (`status="blocked"`) are a guardrail working as intended and appear on the guardrail panel instead.

## Alerts

Each alert has a `severity` label, `summary` and `description` annotations, and a `runbook_url` pointing at its section in [runbooks.md](runbooks.md).

| Alert | Severity | Fires when |
|---|---|---|
| GauntletProxyDown | critical | Proxy scrape fails for 1m |
| GauntletHighErrorRate | warning | Error share > 2% over 5m, per release |
| GauntletLatencySLOBreach | warning | p95 latency > 1.5s over 5m, per release |
| GauntletCanaryLeak | critical | Any `canary_leak` block in 5m |
| GauntletOnlineScoreDrop | warning | Score < 0.9 for 10m on a release with weight > 0 |
| GauntletRollbackHappened | info | Rollback counter rose in the last 10m |
| GauntletCostBurnRate | warning | Total spend > $5/hour for 15m |

The cost budget is the number at the end of the `GauntletCostBurnRate` expression; a comment above it explains how to change it or split it per release.
