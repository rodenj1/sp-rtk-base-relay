# Prometheus Metrics Guide — SP-Base-Relay v2.0

## Overview

SP-Base-Relay v2.0 exports **per-destination** Prometheus metrics using `{destination="..."}` labels, plus global metrics for input health and service status. This is a **breaking change** from v1.x — all metric names have changed.

## Configuration

```yaml
metrics:
  enabled: true
  host: "0.0.0.0"
  port: 8080
  path: "/metrics"
```

Access: `http://localhost:8080/metrics`

---

## Available Metrics

### Per-Destination Metrics

All per-destination metrics carry a `{destination="<name>"}` label matching the destination name in your config.

| Metric | Type | Description |
|--------|------|-------------|
| `sp_base_relay_dest_bytes_sent_total` | Counter | Total bytes sent to destination |
| `sp_base_relay_dest_messages_sent_total` | Counter | Total messages sent to destination |
| `sp_base_relay_dest_messages_dropped_total` | Counter | Messages dropped due to queue overflow |
| `sp_base_relay_dest_messages_filtered_total` | Counter | Messages filtered out by allowlist/blocklist |
| `sp_base_relay_dest_connection_status` | Gauge | Connection state (1=connected, 0=disconnected) |
| `sp_base_relay_dest_connection_attempts_total` | Counter | Total connection attempts |
| `sp_base_relay_dest_errors_total` | Counter | Total errors |
| `sp_base_relay_dest_queue_depth` | Gauge | Current queue depth (0–100) |
| `sp_base_relay_tcp_server_connected_clients` | Gauge | TCP server client count (tcp_server type only) |

### Global Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `sp_base_relay_input_connection_status` | Gauge | Input source connection (1=connected, 0=disconnected) |
| `sp_base_relay_input_seconds_since_last_data` | Gauge | Seconds since last data from GPS source (DR-7 watchdog; -1 if no data yet) |
| `sp_base_relay_service_uptime_seconds` | Gauge | Service uptime in seconds |
| `sp_base_relay_active_destinations_count` | Gauge | Number of currently connected destinations |
| `sp_base_relay_hub_running_status` | Gauge | Broadcast hub running (1=running, 0=stopped) |

---

## How Metrics Work

The `MetricsCollector` uses a **pull model**: the main loop calls `update_all()` every ~1 second, which reads `DestinationStats` from each destination and `BroadcastHub` state.

Counter metrics use **delta-based increments** — the collector tracks previous values and only increments by the difference, so Prometheus sees monotonically increasing counters.

---

## Prometheus Configuration

```yaml
scrape_configs:
  - job_name: 'sp-base-relay'
    static_configs:
      - targets: ['localhost:8080']
    scrape_interval: 5s
```

---

## Grafana Dashboard

A pre-built v2 dashboard is available at `templates/grafana_dashboard.json`.

### Features
- **`$destination` template variable** — filter all panels by destination
- **Per-destination throughput** — bytes/sec and messages/sec per destination
- **Queue depth** — per-destination queue utilization
- **Connection status** — per-destination connection state over time
- **Drops & errors** — per-destination drop and error rates
- **Input watchdog** — seconds since last data from GPS source (DR-7)
- **Active destinations** — count of connected destinations
- **Service uptime** — total service uptime

### Importing
1. Open Grafana → **+** → **Import**
2. Upload `templates/grafana_dashboard.json`
3. Select your Prometheus data source
4. Click **Import**

---

## Common PromQL Queries

### Per-Destination Throughput (bytes/sec)
```promql
rate(sp_base_relay_dest_bytes_sent_total{destination="rtk2go"}[1m])
```

### All Destinations Throughput
```promql
rate(sp_base_relay_dest_bytes_sent_total[1m])
```

### Message Drop Rate (per minute)
```promql
rate(sp_base_relay_dest_messages_dropped_total[5m]) * 60
```

### Error Rate by Destination
```promql
rate(sp_base_relay_dest_errors_total[5m]) * 60
```

### Seconds Since Last GPS Data
```promql
sp_base_relay_input_seconds_since_last_data
```

### Destination Connection Status
```promql
sp_base_relay_dest_connection_status
```

### Queue Utilization (% of max 100)
```promql
sp_base_relay_dest_queue_depth / 100 * 100
```

### TCP Server Client Count
```promql
sp_base_relay_tcp_server_connected_clients{destination="local_tcp"}
```

---

## Alerting Rules

Example Prometheus alerting rules for SP-Base-Relay v2:

```yaml
groups:
  - name: sp_base_relay
    rules:
      # Any destination disconnected for >1 minute
      - alert: DestinationDown
        expr: sp_base_relay_dest_connection_status == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Destination {{ $labels.destination }} is disconnected"
          description: "SP-Base-Relay destination {{ $labels.destination }} has been disconnected for more than 1 minute."

      # Input source disconnected
      - alert: InputSourceDisconnected
        expr: sp_base_relay_input_connection_status == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "GPS input source disconnected"
          description: "SP-Base-Relay input source has been disconnected for more than 1 minute."

      # No GPS data for >30 seconds (DR-7 watchdog)
      - alert: NoGPSData
        expr: sp_base_relay_input_seconds_since_last_data > 30
        for: 30s
        labels:
          severity: warning
        annotations:
          summary: "No GPS data for {{ $value | humanize }}s"
          description: "SP-Base-Relay has not received GPS data for {{ $value | humanize }} seconds."

      # High drop rate on any destination
      - alert: HighDropRate
        expr: rate(sp_base_relay_dest_messages_dropped_total[5m]) > 1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High drop rate on {{ $labels.destination }}"
          description: "Destination {{ $labels.destination }} is dropping {{ $value }} messages/sec."

      # High error rate on any destination
      - alert: HighErrorRate
        expr: rate(sp_base_relay_dest_errors_total[5m]) > 1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High error rate on {{ $labels.destination }}"
          description: "Destination {{ $labels.destination }} has {{ $value }} errors/sec."

      # Broadcast hub stopped
      - alert: HubStopped
        expr: sp_base_relay_hub_running_status == 0
        for: 30s
        labels:
          severity: critical
        annotations:
          summary: "Broadcast hub stopped"
          description: "SP-Base-Relay broadcast hub is not running."
```

---

## Migration from v1.x Metrics

All v1.x metric names are **replaced** in v2.0:

| v1.x Metric | v2.0 Replacement |
|---|---|
| `sp_base_relay_rtcm_connection_status` | `sp_base_relay_dest_connection_status{destination="surepath"}` |
| `sp_base_relay_rtcm_messages_sent_total` | `sp_base_relay_dest_messages_sent_total{destination="..."}` |
| `sp_base_relay_rtcm_bytes_sent_total` | `sp_base_relay_dest_bytes_sent_total{destination="..."}` |
| `sp_base_relay_rtcm_connection_attempts_total` | `sp_base_relay_dest_connection_attempts_total{destination="..."}` |
| `sp_base_relay_pipeline_running_status` | `sp_base_relay_hub_running_status` |
| `sp_base_relay_pipeline_errors_total` | `sp_base_relay_dest_errors_total{destination="..."}` |
| `sp_base_relay_rtcm_heartbeat_last_received_timestamp` | Removed (Sure-Path internal) |
| `sp_base_relay_pipeline_restarts_total` | Removed (hub manages automatically) |

**Action required**: Update Grafana dashboards and Prometheus alerting rules. Use the v2 dashboard at `templates/grafana_dashboard.json`.

---

## Troubleshooting

### Metrics Not Available

1. Verify metrics are enabled:
   ```yaml
   metrics:
     enabled: true
   ```
2. Test the endpoint:
   ```bash
   curl http://localhost:8080/metrics
   ```
3. Check service logs for metrics server startup messages.

### No Per-Destination Labels Appearing

- Ensure destinations are configured and enabled in `config.yaml`
- Metrics only appear after the first `update_all()` cycle (~1 second after startup)

### Performance Impact

Minimal overhead:
- Pull model reads destination stats once per second
- Delta-based counter increments (no full recalculation)
- HTTP server runs in a separate thread
- Typical: < 1% CPU, < 10MB memory

---

## Best Practices

1. **Scrape interval**: 5–15 seconds for real-time monitoring
2. **Retention**: Keep metrics for at least 30 days for trend analysis
3. **Alerting**: Set up alerts for `DestinationDown` and `InputSourceDisconnected` at minimum
4. **Use `$destination` variable** in Grafana to filter per-destination panels
5. **Use `rate()`** for counter metrics — never graph raw counters
6. **Watch queue depth** — sustained values near 100 indicate a destination can't keep up
