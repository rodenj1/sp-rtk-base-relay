# Prometheus Metrics Guide — SP-Base-Relay v2.1

## Overview

SP-Base-Relay v2.1 exports **per-destination** Prometheus metrics using `{destination="..."}` labels, plus global metrics for input source, broadcast hub, event bus, and service lifecycle. v2.1 adds ~20 new metrics over v2.0 without removing any; all v2.0 dashboards continue to work.

> **Upgrading from v1.x?** All metric names changed in v2.0 — see the [v1→v2 migration notes](#v1-to-v2-migration) at the bottom.
>
> **Upgrading from v2.0?** All new v2.1 metrics are additive. Import `templates/grafana_dashboard.json` (the v2.1 dashboard) to see them.

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
| `sp_rtk_base_relay_dest_bytes_sent_total` | Counter | Total bytes sent to destination |
| `sp_rtk_base_relay_dest_messages_sent_total` | Counter | Total messages sent to destination |
| `sp_rtk_base_relay_dest_messages_dropped_total` | Counter | Messages dropped due to queue overflow |
| `sp_rtk_base_relay_dest_messages_filtered_total` | Counter | Messages filtered out by allowlist/blocklist |
| `sp_rtk_base_relay_dest_connection_status` | Gauge | Connection state (1=connected, 0=disconnected) |
| `sp_rtk_base_relay_dest_connection_attempts_total` | Counter | Total connection attempts |
| `sp_rtk_base_relay_dest_errors_total` | Counter | Total errors |
| `sp_rtk_base_relay_dest_queue_depth` | Gauge | Current queue depth (0–100) |
| `sp_rtk_base_relay_tcp_server_connected_clients` | Gauge | TCP server client count (tcp_server type only) |

### Global Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `sp_rtk_base_relay_input_connection_status` | Gauge | Input source connection (1=connected, 0=disconnected) |
| `sp_rtk_base_relay_input_seconds_since_last_data` | Gauge | Seconds since last data from GPS source (DR-7 watchdog; -1 if no data yet) |
| `sp_rtk_base_relay_service_uptime_seconds` | Gauge | Service uptime in seconds |
| `sp_rtk_base_relay_active_destinations_count` | Gauge | Number of currently connected destinations |
| `sp_rtk_base_relay_hub_running_status` | Gauge | Broadcast hub running (1=running, 0=stopped) |
| `sp_rtk_base_relay_engine_running_status` | Gauge | **[v2.1]** RelayEngine running (1=running, 0=stopped) |

### Destination Metadata (v2.1)

Stable descriptor gauges (always value `1`) whose **labels** identify each destination. Use them in Grafana `label_values(...)` variables or to add `type` / `filter_mode` columns to tables.

| Metric | Labels | Description |
|--------|--------|-------------|
| `sp_rtk_base_relay_dest_info` | `destination, type, filter_mode` | Per-destination static descriptor |
| `sp_rtk_base_relay_dest_enabled` | `destination` | 1 if destination is enabled in config |
| `sp_rtk_base_relay_dest_running` | `destination` | 1 if destination worker thread is running |
| `sp_rtk_base_relay_dest_connected_since_timestamp` | `destination` | Unix ts of current connection start (0 = not connected) |
| `sp_rtk_base_relay_dest_last_send_timestamp` | `destination` | Unix ts of last successful send |
| `sp_rtk_base_relay_dest_connection_failures_total` | `destination` | Connect attempts that **failed** (counter) |

### Input-Source Metrics (v2.1)

Driven directly by the active `InputSource` (replaces relying on the broadcast hub for input stats).

| Metric | Type | Description |
|--------|------|-------------|
| `sp_rtk_base_relay_input_info` | Gauge | Descriptor carrying `source_type` label (tcp, serial, bluetooth, …) |
| `sp_rtk_base_relay_input_connected_since_timestamp` | Gauge | Unix ts when the current input connection was established (0 = disconnected) |
| `sp_rtk_base_relay_input_bytes_received_total` | Counter | Total bytes read from the input source |
| `sp_rtk_base_relay_input_messages_received_total` | Counter | Total RTCM messages parsed from the input source |
| `sp_rtk_base_relay_input_reconnect_attempts_total` | Counter | Reconnect attempts against the input source |
| `sp_rtk_base_relay_input_reconnect_successes_total` | Counter | Successful reconnects |

### Broadcast-Hub Metrics (v2.1)

Internal throughput of the fan-out stage, separate from per-destination counters.

| Metric | Type | Description |
|--------|------|-------------|
| `sp_rtk_base_relay_hub_bytes_received_total` | Counter | Bytes the hub has ingested from the input source |
| `sp_rtk_base_relay_hub_chunks_received_total` | Counter | Raw byte-chunks received from the input source |
| `sp_rtk_base_relay_hub_chunks_distributed_total` | Counter | Chunk × destination fan-out events (roughly `chunks_received × registered_destinations`) |
| `sp_rtk_base_relay_hub_frames_parsed_total` | Counter | Fully-framed RTCM3 messages reassembled |
| `sp_rtk_base_relay_hub_no_data_warnings_total` | Counter | DR-7 watchdog warnings logged |
| `sp_rtk_base_relay_hub_registered_destinations_count` | Gauge | Number of destinations currently registered with the hub |

### Event-Bus Metrics (v2.1)

Observability for the internal pub/sub `EventBus` used by the RelayEngine.

| Metric | Type | Description |
|--------|------|-------------|
| `sp_rtk_base_relay_events_emitted_total` | Counter | Events published, label `event_type` (e.g. `engine.started`, `destination.connected`) |
| `sp_rtk_base_relay_events_dropped_total` | Counter | Events dropped because a subscriber queue was full |
| `sp_rtk_base_relay_event_subscribers_count` | Gauge | Current active subscriber count |
| `sp_rtk_base_relay_event_ring_buffer_depth` | Gauge | Current depth of the "recent events" ring buffer |

---

## How Metrics Work

The `MetricsCollector` uses a **pull model**: the main loop calls `update_all()` every ~1 second, which reads `DestinationStats` from each destination and `BroadcastHub` state.

Counter metrics use **delta-based increments** — the collector tracks previous values and only increments by the difference, so Prometheus sees monotonically increasing counters.

---

## Prometheus Configuration

```yaml
scrape_configs:
  - job_name: 'sp-rtk-base-relay'
    static_configs:
      - targets: ['localhost:8080']
    scrape_interval: 5s
```

---

## Grafana Dashboard

A pre-built **v2.1 dashboard** is shipped at `templates/grafana_dashboard.json`
(schemaVersion 41 — Grafana 11.x). The previous v2.0 dashboard is archived at
`templates/archive/grafana_dashboard_v1.json` for reference.

### Layout (8 rows, 27 panels)

1. **Service Overview** — 6 stat tiles (Engine, Hub, Input, Destinations, Input Watchdog, Uptime)
2. **Hub Throughput** — ingress bytes/sec + chunks/frames/sec
3. **Per-Destination Health** — joined status table (connected / enabled / running / queue / type / filter)
4. **Per-Destination Throughput** — bytes/sec + messages/sec, filtered by `$destination`
5. **Drops, Filters & Queues** — queue-overflow drops, filter rejections, live queue depth
6. **Connection Reliability** — destination connect attempts/failures + input reconnect stats + hub no-data warnings
7. **TCP-Server Destinations** — connected-clients time series per tcp_server destination
8. **Event Bus (v2.1)** — events/sec by type, subscriber count, ring-buffer depth, dropped events

### Template variables

| Name | Purpose |
|------|---------|
| `DS_PROMETHEUS` | Prometheus datasource selector |
| `destination` | Multi-select list populated from `label_values(sp_rtk_base_relay_dest_info, destination)` |
| `dest_type` | Multi-select populated from `label_values(sp_rtk_base_relay_dest_info, type)` |

### Importing
1. Open Grafana → **Dashboards** → **New** → **Import**
2. Upload `templates/grafana_dashboard.json`
3. Pick your Prometheus datasource (the `DS_PROMETHEUS` variable is auto-bound)
4. Click **Import** — dashboard UID is `sp-rtk-base-relay-v2-1`

---

## Common PromQL Queries

### Per-Destination Throughput (bytes/sec)
```promql
rate(sp_rtk_base_relay_dest_bytes_sent_total{destination="rtk2go"}[1m])
```

### All Destinations Throughput
```promql
rate(sp_rtk_base_relay_dest_bytes_sent_total[1m])
```

### Message Drop Rate (per minute)
```promql
rate(sp_rtk_base_relay_dest_messages_dropped_total[5m]) * 60
```

### Error Rate by Destination
```promql
rate(sp_rtk_base_relay_dest_errors_total[5m]) * 60
```

### Seconds Since Last GPS Data
```promql
sp_rtk_base_relay_input_seconds_since_last_data
```

### Destination Connection Status
```promql
sp_rtk_base_relay_dest_connection_status
```

### Queue Utilization (% of max 100)
```promql
sp_rtk_base_relay_dest_queue_depth / 100 * 100
```

### TCP Server Client Count
```promql
sp_rtk_base_relay_tcp_server_connected_clients{destination="local_tcp"}
```

---

## Alerting Rules

Example Prometheus alerting rules for SP-Base-Relay v2:

```yaml
groups:
  - name: sp_rtk_base_relay
    rules:
      # Any destination disconnected for >1 minute
      - alert: DestinationDown
        expr: sp_rtk_base_relay_dest_connection_status == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Destination {{ $labels.destination }} is disconnected"
          description: "SP-Base-Relay destination {{ $labels.destination }} has been disconnected for more than 1 minute."

      # Input source disconnected
      - alert: InputSourceDisconnected
        expr: sp_rtk_base_relay_input_connection_status == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "GPS input source disconnected"
          description: "SP-Base-Relay input source has been disconnected for more than 1 minute."

      # No GPS data for >30 seconds (DR-7 watchdog)
      - alert: NoGPSData
        expr: sp_rtk_base_relay_input_seconds_since_last_data > 30
        for: 30s
        labels:
          severity: warning
        annotations:
          summary: "No GPS data for {{ $value | humanize }}s"
          description: "SP-Base-Relay has not received GPS data for {{ $value | humanize }} seconds."

      # High drop rate on any destination
      - alert: HighDropRate
        expr: rate(sp_rtk_base_relay_dest_messages_dropped_total[5m]) > 1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High drop rate on {{ $labels.destination }}"
          description: "Destination {{ $labels.destination }} is dropping {{ $value }} messages/sec."

      # High error rate on any destination
      - alert: HighErrorRate
        expr: rate(sp_rtk_base_relay_dest_errors_total[5m]) > 1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High error rate on {{ $labels.destination }}"
          description: "Destination {{ $labels.destination }} has {{ $value }} errors/sec."

      # Broadcast hub stopped
      - alert: HubStopped
        expr: sp_rtk_base_relay_hub_running_status == 0
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
| `sp_rtk_base_relay_rtcm_connection_status` | `sp_rtk_base_relay_dest_connection_status{destination="surepath"}` |
| `sp_rtk_base_relay_rtcm_messages_sent_total` | `sp_rtk_base_relay_dest_messages_sent_total{destination="..."}` |
| `sp_rtk_base_relay_rtcm_bytes_sent_total` | `sp_rtk_base_relay_dest_bytes_sent_total{destination="..."}` |
| `sp_rtk_base_relay_rtcm_connection_attempts_total` | `sp_rtk_base_relay_dest_connection_attempts_total{destination="..."}` |
| `sp_rtk_base_relay_pipeline_running_status` | `sp_rtk_base_relay_hub_running_status` |
| `sp_rtk_base_relay_pipeline_errors_total` | `sp_rtk_base_relay_dest_errors_total{destination="..."}` |
| `sp_rtk_base_relay_rtcm_heartbeat_last_received_timestamp` | Removed (Sure-Path internal) |
| `sp_rtk_base_relay_pipeline_restarts_total` | Removed (hub manages automatically) |

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
