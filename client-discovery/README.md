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

<details>
<summary>Example output</summary>

```
================================================================================
MSK CLIENT DISCOVERY
Bootstrap: b-1.my-cluster.kafka.us-east-1.amazonaws.com:9098
Time: 2026-03-10 18:30:00 UTC
================================================================================

================================================================================
TOPICS
================================================================================
orders
payments
inventory-events

================================================================================
CONSUMER GROUPS
================================================================================
order-processor-group
payment-service-group
analytics-consumer

================================================================================
ACTIVE CONSUMERS (real IPs, client IDs, assignments)
================================================================================
GROUP                    CONSUMER-ID                          HOST           CLIENT-ID                  #PARTITIONS
order-processor-group    order-processor-1-abc123             /10.0.1.45     order-processor-1          6
order-processor-group    order-processor-2-def456             /10.0.2.78     order-processor-2          6
payment-service-group    payment-consumer-ghi789              /10.0.1.45     payment-consumer           6
analytics-consumer       analytics-reader-jkl012              /10.0.3.112    analytics-reader           6

================================================================================
CONSUMER GROUP LAG
================================================================================
GROUP                    TOPIC           PARTITION  CURRENT-OFFSET  LOG-END-OFFSET  LAG
order-processor-group    orders          0          145230          145235          5
order-processor-group    orders          1          138900          138900          0
order-processor-group    orders          2          141050          141052          2
payment-service-group    payments        0          89200           89200           0
payment-service-group    payments        1          91340           91345           5
```
</details>

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

<details>
<summary>Example output — setup-flow-logs.py</summary>

```
Cluster: my-cluster (6 ENIs)
  Created log group: /aws/vpc-flow-logs/my-cluster (7-day retention)
  IAM role exists: arn:aws:iam::123456789012:role/VPCFlowLogsRole
  Created fl-0a1b2c3d4e5f6a7b8 on eni-0aaa1111bbb22222 (10.0.1.50)
  Created fl-0b2c3d4e5f6a7b8c9 on eni-0bbb2222ccc33333 (10.0.1.85)
  Created fl-0c3d4e5f6a7b8c9d0 on eni-0ccc3333ddd44444 (10.0.2.120)
  Created fl-0d4e5f6a7b8c9d0e1 on eni-0ddd4444eee55555 (10.0.2.200)
  Created fl-0e5f6a7b8c9d0e1f2 on eni-0eee5555fff66666 (10.0.3.75)
  Created fl-0f6a7b8c9d0e1f2a3 on eni-0fff6666aaa77777 (10.0.3.140)

Done. 6 flow logs created, 0 already existed.
Logs will appear in ~2-5 min at: /aws/vpc-flow-logs/my-cluster
```
</details>

<details>
<summary>Example output — analyze-flow-logs.py</summary>

```
================================================================================
VPC FLOW LOG ANALYSIS - my-cluster
Region: us-east-1  |  Window: 30 min  |  Brokers: 6 IPs, 6 ENIs
Broker IPs: 10.0.1.50, 10.0.1.85, 10.0.2.120, 10.0.2.200, 10.0.3.75, 10.0.3.140
================================================================================

================================================================================
CONNECTIONS PER BROKER
================================================================================

  Broker 10.0.1.85 (2 unique IPs, 8 TCP connections, 52,340,120 bytes)
  Source IP             Conns    Packets        Bytes Ports
  -----------------------------------------------------------------
  10.0.0.45                 5      62340   41,200,300 9098
  10.0.4.22                 3      18450   11,139,820 9098

  Broker 10.0.2.200 (2 unique IPs, 12 TCP connections, 128,500,000 bytes)
  Source IP             Conns    Packets        Bytes Ports
  -----------------------------------------------------------------
  10.0.0.45                 8     185200  102,300,500 9098
  10.0.4.22                 4      42100   26,199,500 9098

  Broker 10.0.3.140 (2 unique IPs, 6 TCP connections, 38,700,000 bytes)
  Source IP             Conns    Packets        Bytes Ports
  -----------------------------------------------------------------
  10.0.0.45                 4      35600   28,100,000 9098
  10.0.4.22                 2      12300   10,600,000 9098

================================================================================
CONNECTIONS PER SOURCE IP (cluster-wide)
================================================================================
  Source IP             Conns    Packets        Bytes  Brokers Ports
  ---------------------------------------------------------------------------
  10.0.0.45                17     283140  171,600,800        3 9098
  10.0.4.22                 9      72850   47,939,320        3 9098

================================================================================
SUMMARY
================================================================================
  Unique source IPs:    2
  TCP connections:      26
  Total bytes:          219,540,120
  Brokers with traffic: 3
  Time window:          30 min
================================================================================
```
</details>

### 3. Prometheus/JMX — client software and connection metrics

Queries Prometheus scraping MSK JMX exporters. Must run from a machine that can reach the Prometheus endpoint (requires Open Monitoring enabled on the cluster).

```bash
python3 prometheus-report.py <cluster-name>
python3 prometheus-report.py <cluster-name> --prometheus http://localhost:9090
```

Best for: identifying client software (e.g. apache-kafka-java 3.8.0), connection counts per listener, request rates, topic throughput trends.

<details>
<summary>Example output</summary>

```
==========================================================================================
MSK CONNECTION REPORT - my-cluster
Prometheus: http://localhost:9090
Time: 2026-03-10 18:30:00 UTC
==========================================================================================

==========================================================================================
ACTIVE CONNECTIONS BY CLIENT SOFTWARE
==========================================================================================
  Software                       Version              Listener        Conns
  ---------------------------------------------------------------------------
  apache-kafka-java              3.8.0                CLIENT_SECURE       4
  apache-kafka-java              3.7.1                CLIENT_SECURE       2

  Per broker:
  Broker Listener        Software                       Version          Conns
  ---------------------------------------------------------------------------
  b-1    CLIENT_SECURE   apache-kafka-java              3.8.0                2
  b-2    CLIENT_SECURE   apache-kafka-java              3.8.0                1
  b-2    CLIENT_SECURE   apache-kafka-java              3.7.1                2
  b-3    CLIENT_SECURE   apache-kafka-java              3.8.0                1

==========================================================================================
CONNECTION COUNT PER LISTENER
==========================================================================================
  Broker Listener           Count
  --------------------------------
  b-1    CLIENT_SECURE          4
  b-2    CLIENT_SECURE          5
  b-3    CLIENT_SECURE          3

==========================================================================================
REQUEST RATE BY TYPE (1min avg, req/s)
==========================================================================================
  Request Type              Rate (all brokers)
  ------------------------------------------------
  Produce                              124.50
  Fetch                                 98.30
  Metadata                              12.10
  FindCoordinator                        3.40
  JoinGroup                              1.20

==========================================================================================
TOPIC THROUGHPUT (messages in/sec, 1min avg)
==========================================================================================
  Topic                                    Msg/s (all brokers)
  ---------------------------------------------------------------
  orders                                                  85.40
  payments                                                42.10
  inventory-events                                        12.30
```
</details>

### 4. CloudWatch Broker Logs — consumer group activity

Queries CloudWatch Logs Insights. Runs from anywhere with AWS credentials (no broker connectivity needed). Requires broker logging enabled on the cluster.

```bash
python3 analyze-connections.py --cluster <cluster-name> --region <region> --minutes 30
```

Best for: consumer group membership changes, TCP connection events per broker, topic write activity (segment rolls).

<details>
<summary>Example output</summary>

```
Cluster: my-cluster
Log group: /aws/msk/my-cluster/broker-logs
Window: 18:00:00 - 18:30:00 UTC (30 min)

================================================================================
TCP CONNECTIONS
================================================================================
  Broker 1: 12 new connections
  Broker 2: 18 new connections
  Broker 3: 9 new connections
  Total: 39 new connections in 30 min

================================================================================
CONSUMER GROUPS
================================================================================
Group                                          Clients    Events  Client IDs
--------------------------------------------------------------------------------
order-processor-group                                2        28  order-processor-1, order-processor-2
payment-service-group                                1        14  payment-consumer
analytics-consumer                                   1        12  analytics-reader

================================================================================
TOPICS WITH WRITE ACTIVITY
================================================================================
Topic                                    Partitions   Segments  Snapshots
------------------------------------------------------------------------
orders                                            6          8         12
payments                                          6          3          6
inventory-events                                  6          1          3

================================================================================
SUMMARY
================================================================================
  TCP connections:    39
  Consumer groups:    3
  Active topics:      3
  DEBUG log entries:  0
================================================================================
```
</details>

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
