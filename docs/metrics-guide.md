# Prometheus Metrics Guide

This guide explains how to use and configure Prometheus metrics for monitoring SP-Base-Relay.

## Overview

SP-Base-Relay exports comprehensive metrics via Prometheus for monitoring connection health, data throughput, errors, and system performance. The metrics system integrates seamlessly with existing Prometheus + Grafana monitoring stacks.

## Configuration

Metrics are configured in the `config.yaml` file:

```yaml
metrics:
  enabled: true          # Enable/disable metrics collection
  host: "0.0.0.0"       # Host to bind metrics server to
  port: 8080            # Port for metrics HTTP endpoint
  path: "/metrics"      # Metrics endpoint path
```

## Available Metrics

### Connection Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `sp_base_relay_rtcm_connection_status` | Gauge | RTCM server connection status (1=connected, 0=disconnected) |
| `sp_base_relay_input_connection_status` | Gauge | Input source connection status (1=connected, 0=disconnected) |
| `sp_base_relay_rtcm_connection_attempts_total` | Counter | Total RTCM server connection attempts |
| `sp_base_relay_rtcm_successful_connections_total` | Counter | Total successful RTCM server connections |
| `sp_base_relay_rtcm_authentication_failures_total` | Counter | Total RTCM authentication failures |
| `sp_base_relay_rtcm_heartbeat_timeouts_total` | Counter | Total RTCM heartbeat timeout events |

### Data Flow Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `sp_base_relay_rtcm_messages_sent_total` | Counter | Total RTCM messages sent to server |
| `sp_base_relay_rtcm_bytes_sent_total` | Counter | Total bytes sent to RTCM server |
| `sp_base_relay_pipeline_messages_processed_total` | Counter | Total messages processed through pipeline |
| `sp_base_relay_pipeline_bytes_processed_total` | Counter | Total bytes processed through pipeline |
| `sp_base_relay_input_bytes_read_total` | Counter | Total bytes read from input source |

### Pipeline Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `sp_base_relay_pipeline_running_status` | Gauge | Pipeline running status (1=running, 0=stopped) |
| `sp_base_relay_pipeline_restarts_total` | Counter | Total pipeline restart attempts |
| `sp_base_relay_pipeline_errors_total{error_type}` | Counter | Total pipeline errors by type (input, rtcm, coordination) |

### Health Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `sp_base_relay_rtcm_heartbeat_last_received_timestamp` | Gauge | Unix timestamp of last RTCM heartbeat received |
| `sp_base_relay_service_uptime_seconds` | Gauge | Service uptime in seconds |
| `sp_base_relay_pipeline_uptime_seconds` | Gauge | Current pipeline session uptime in seconds |

## Prometheus Configuration

Add SP-Base-Relay as a scrape target in your Prometheus configuration:

```yaml
scrape_configs:
  - job_name: 'sp-base-relay'
    static_configs:
      - targets: ['localhost:8080']
    scrape_interval: 5s
```

## Grafana Dashboard

A pre-built Grafana dashboard is available in `templates/grafana_dashboard.json`. The dashboard includes:

- **Connection Status** - Real-time connection state for RTCM server and input source
- **Pipeline Status** - Pipeline running state
- **Service & Pipeline Uptime** - Uptime tracking
- **Data Throughput** - Bytes per second graphs for input, pipeline, and RTCM
- **Message Rate** - Messages per second processing rate
- **Connection Attempts** - Success vs failure rates
- **Error Rates** - Error tracking by type
- **Pipeline Restarts** - Restart frequency monitoring
- **Last Heartbeat** - Time since last heartbeat with color-coded alerts
- **Cumulative Statistics** - Total messages and bytes processed

### Importing the Dashboard

1. Open Grafana web interface
2. Click '+' → 'Import'
3. Upload `templates/grafana_dashboard.json`
4. Select your Prometheus data source
5. Click 'Import'

## Common Prometheus Queries

### Data Throughput Rate
```promql
rate(sp_base_relay_rtcm_bytes_sent_total[1m])
```

### Error Rate (errors per minute)
```promql
rate(sp_base_relay_pipeline_errors_total[5m]) * 60
```

### Connection Success Rate
```promql
sp_base_relay_rtcm_successful_connections_total / sp_base_relay_rtcm_connection_attempts_total
```

### Time Since Last Heartbeat
```promql
time() - sp_base_relay_rtcm_heartbeat_last_received_timestamp
```

### Pipeline Restart Rate (per hour)
```promql
rate(sp_base_relay_pipeline_restarts_total[1h]) * 3600
```

## Alerting Rules

Example Prometheus alerting rules for SP-Base-Relay:

```yaml
groups:
  - name: sp_base_relay
    rules:
      - alert: RTCMConnectionDown
        expr: sp_base_relay_rtcm_connection_status == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "RTCM server connection is down"
          description: "SP-Base-Relay has lost connection to RTCM server"
      
      - alert: InputSourceDisconnected
        expr: sp_base_relay_input_connection_status == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Input source disconnected"
          description: "SP-Base-Relay input source is not connected"
      
      - alert: HeartbeatTimeout
        expr: time() - sp_base_relay_rtcm_heartbeat_last_received_timestamp > 30
        for: 30s
        labels:
          severity: warning
        annotations:
          summary: "RTCM heartbeat timeout"
          description: "No heartbeat received from RTCM server for {{ $value }}s"
      
      - alert: HighErrorRate
        expr: rate(sp_base_relay_pipeline_errors_total[5m]) > 1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High error rate detected"
          description: "Pipeline error rate is {{ $value }} errors/sec"
      
      - alert: FrequentPipelineRestarts
        expr: rate(sp_base_relay_pipeline_restarts_total[1h]) > 2
        for: 30m
        labels:
          severity: warning
        annotations:
          summary: "Frequent pipeline restarts"
          description: "Pipeline is restarting {{ $value }} times per hour"
```

## Integration Example

See `examples/metrics_integration.py` for a complete example of integrating metrics collection into a service.

## Troubleshooting

### Metrics Not Available

1. Check metrics are enabled in config:
   ```yaml
   metrics:
     enabled: true
   ```

2. Verify metrics server is running:
   ```bash
   curl http://localhost:8080/metrics
   ```

3. Check service logs for metrics server startup messages

### High Error Rates

Use metrics to diagnose issues:
- Check `pipeline_errors_total{error_type}` to identify error source
- Monitor `rtcm_heartbeat_last_received_timestamp` for connection health
- Review `rtcm_connection_attempts_total` vs `rtcm_successful_connections_total` for connection reliability

### Performance Impact

Metrics collection has minimal performance impact:
- Metrics updates use delta calculations (efficient)
- HTTP server runs in separate thread
- No blocking operations in metric collection
- Typical overhead: < 1% CPU, < 10MB memory

## Best Practices

1. **Scrape Interval**: Use 5-15 second intervals for real-time monitoring
2. **Retention**: Keep metrics for at least 30 days for trend analysis
3. **Alerting**: Set up critical alerts for connection status
4. **Dashboards**: Use the provided Grafana dashboard as a starting point
5. **Aggregation**: Use rate() for counter metrics to get per-second rates
6. **Labels**: The `error_type` label allows filtering pipeline errors by category

## Advanced Configuration

### Custom Namespace

The default metric namespace is `sp_base_relay`. This can be customized in code:

```python
from sp_base_relay.metrics import MetricsCollector

metrics = MetricsCollector(namespace="my_custom_prefix")
```

### Metric Collection Frequency

Metrics are updated continuously as events occur. For periodic bulk updates:

```python
import time

prev_stats = (None, None, None)
while running:
    # Collect all metrics with delta tracking
    prev_stats = metrics.collect_all_metrics(
        rtcm_client,
        pipeline_coordinator,
        input_source,
        *prev_stats
    )
    time.sleep(5)  # Update every 5 seconds
```

## Additional Resources

- [Prometheus Documentation](https://prometheus.io/docs/)
- [Grafana Documentation](https://grafana.com/docs/)
- [PromQL Basics](https://prometheus.io/docs/prometheus/latest/querying/basics/)
- [Alerting Rules](https://prometheus.io/docs/prometheus/latest/configuration/alerting_rules/)
