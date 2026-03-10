# MSK Client Discovery

Discover which applications connect to your MSK clusters from the broker side — useful when clients lack instrumentation (APM, OpenTelemetry, custom metrics).

## Approaches

### 1. Kafka Admin API — client IDs, IPs, consumer groups

The most detailed broker-side method. Shows real client IPs, client IDs, consumer group assignments, and lag. Must run from a machine with network access to the brokers (e.g. an EC2 in the same VPC).

```bash
./discover-clients.sh <bootstrap-server>:<port> client.properties
```

The `client.properties` file contains the Kafka client authentication config. For IAM auth:

```properties
security.protocol=SASL_SSL
sasl.mechanism=AWS_MSK_IAM
sasl.jaas.config=software.amazon.msk.auth.iam.IAMLoginModule required;
sasl.client.callback.handler.class=software.amazon.msk.auth.iam.IAMClientCallbackHandler
```

For TLS (no IAM):

```properties
security.protocol=SSL
```

Best for: identifying active consumers, their IPs, assigned partitions, and lag.

### 2. VPC Flow Logs — all client IPs (producers + consumers)

Network-level visibility into every IP connecting to broker ENIs, including producers. Runs from anywhere with AWS credentials (no broker connectivity needed).

```bash
# Enable flow logs on broker ENIs (one-time setup)
python3 setup-flow-logs.py --cluster <cluster-name> --action enable

# Analyze connections
python3 analyze-flow-logs.py --cluster <cluster-name> --minutes 60

# Disable when done
python3 setup-flow-logs.py --cluster <cluster-name> --action disable
```

Best for: identifying all source IPs (including producers), connection counts per broker, traffic volume per client IP.

### 3. Prometheus/JMX — client software and connection metrics

Queries Prometheus scraping MSK JMX exporters. Must run from a machine that can reach the Prometheus endpoint (requires Open Monitoring enabled on the cluster).

```bash
python3 prometheus-report.py <cluster-name>
python3 prometheus-report.py <cluster-name> --prometheus http://localhost:9090
```

Best for: identifying client software (e.g. apache-kafka-java 3.8.0), connection counts per listener, request rates, topic throughput trends.

### 4. CloudWatch Broker Logs — consumer group activity

Queries CloudWatch Logs Insights. Runs from anywhere with AWS credentials (no broker connectivity needed). Requires broker logging enabled on the cluster.

```bash
python3 analyze-connections.py --cluster <cluster-name> --region <region> --minutes 30
```

Best for: consumer group membership changes, TCP connection events per broker, topic write activity (segment rolls).

## What each approach reveals

| Data | Admin API | Flow Logs | JMX/Prometheus | Broker Logs |
|---|---|---|---|---|
| Client IP | ✅ consumers | ✅ all | — | — |
| Client ID | ✅ consumers | — | — | ✅ consumers |
| Client software/version | — | — | ✅ | — |
| Producer connections | — | ✅ | ✅ (count) | — |
| Consumer group lag | ✅ | — | — | — |
| Topic assignments | ✅ consumers | — | — | — |
| Traffic volume per IP | — | ✅ | — | — |
| Connection count per broker | — | ✅ | ✅ | ✅ |
| Request rates by type | — | — | ✅ | — |

## Where to run each script

| Script | Needs broker connectivity | Needs AWS credentials | Can run locally |
|---|---|---|---|
| `discover-clients.sh` | ✅ | ✅ (IAM) | ❌ (must be in VPC) |
| `prometheus-report.py` | ✅ (Prometheus) | — | ❌ (must reach Prometheus) |
| `analyze-flow-logs.py` | — | ✅ | ✅ |
| `analyze-connections.py` | — | ✅ | ✅ |
| `setup-flow-logs.py` | — | ✅ | ✅ |

## Scripts

| Script | Purpose |
|---|---|
| `discover-clients.sh` | Kafka Admin API: active consumers, groups, topics, IPs |
| `setup-flow-logs.py` | Enable/disable VPC Flow Logs on MSK broker ENIs |
| `analyze-flow-logs.py` | Analyze VPC Flow Logs for client IPs and connection counts |
| `prometheus-report.py` | Prometheus/JMX: connection metrics, throughput, client software |
| `analyze-connections.py` | CloudWatch Logs: consumer groups, TCP events, topic activity |
| `generate-connections.sh` | Test helper: generate IAM connections with different client IDs |
| `generate-connections-tls.sh` | Test helper: generate TLS connections with different client IDs |

## Prerequisites

- Kafka CLI tools (set `KAFKA_HOME` or add to `PATH`) — for Admin API and test scripts
- `aws-msk-iam-auth` jar in `CLASSPATH` — for IAM auth
- Python 3 + boto3 — for AWS-based scripts
- Prometheus scraping MSK JMX exporters — for JMX report (requires Open Monitoring)
