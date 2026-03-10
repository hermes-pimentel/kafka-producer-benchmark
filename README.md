# kafka-producer-benchmark

Kafka producer benchmark tool built with Spring Boot. Sends JSON messages with per-message latency measurement and exports results to CSV. Designed for testing different producer configurations against local Kafka or Amazon MSK (Standard and Express).

Auto-creates the topic if it doesn't exist. Includes CloudWatch dashboard scripts for monitoring MSK clusters.

## Requirements

- Java 17+
- Maven (wrapper included)

## Quick Start

```bash
# Local Kafka (localhost:9092), runs for 10 minutes
./mvnw spring-boot:run

# MSK with IAM auth
./mvnw spring-boot:run -Dspring-boot.run.profiles=iam \
  -Dspring-boot.run.arguments="--spring.kafka.bootstrap-servers=<broker>:9098"

# MSK with TLS (no IAM)
./mvnw spring-boot:run \
  -Dspring-boot.run.arguments="--spring.kafka.bootstrap-servers=<broker>:9094 --spring.kafka.properties.security.protocol=SSL"
```

## Parameters

All parameters can be passed via `--spring-boot.run.arguments="--param=value"`.

### Application Parameters

| Property | Default | Description |
|---|---|---|
| `app.topic` | producer-test-topic | Kafka topic (auto-created if missing) |
| `app.duration-minutes` | 10 | Run duration in minutes (used when message-count=0) |
| `app.message-count` | 0 | Number of messages to send (0 = use duration instead) |
| `app.message-size-bytes` | 512 | Approximate JSON payload size in bytes |
| `app.batch-size` | 1 | 1 = synchronous send per message, >1 = async batch send |

### Kafka Producer Properties

| Property | Default | Description |
|---|---|---|
| `spring.kafka.producer.acks` | all | Acknowledgment mode: `all`, `1`, or `0` |
| `spring.kafka.producer.properties.linger.ms` | 0 | Time to wait before sending a batch (ms) |
| `spring.kafka.producer.batch-size` | 16384 | Kafka internal batch size in bytes |
| `spring.kafka.producer.compression-type` | none | Compression: `none`, `gzip`, `snappy`, `lz4`, `zstd` |
| `spring.kafka.producer.buffer-memory` | 33554432 | Total memory for buffering records (bytes) |
| `spring.kafka.producer.retries` | 2147483647 | Number of retries on transient errors |
| `spring.kafka.producer.properties.max.in.flight.requests.per.connection` | 5 | Max unacknowledged requests per connection |
| `spring.kafka.producer.properties.delivery.timeout.ms` | 120000 | Upper bound on time to report success or failure (ms) |

## Run Modes

- `message-count=0` (default): runs for `duration-minutes` then stops
- `message-count=500`: sends exactly 500 messages then stops
- `message-count=500 duration-minutes=5`: sends up to 500 messages or stops at 5 minutes, whichever comes first

## Testing Scenarios

Below are examples of common producer configurations to benchmark. Each scenario changes one or more variables to isolate the impact on latency and throughput.

### Baseline: synchronous, acks=all, no batching

Default configuration. Each message is sent synchronously and waits for all replicas to acknowledge. This gives the highest latency but strongest durability guarantee.

```bash
./mvnw spring-boot:run \
  -Dspring-boot.run.arguments="--app.message-count=1000"
```

### Effect of acks

Compare `acks=all` (wait for all replicas), `acks=1` (wait for leader only), and `acks=0` (fire and forget). Lower acks reduce latency but weaken durability.

```bash
# acks=1 (leader only)
./mvnw spring-boot:run \
  -Dspring-boot.run.arguments="--app.message-count=1000 --spring.kafka.producer.acks=1"

# acks=0 (no acknowledgment)
./mvnw spring-boot:run \
  -Dspring-boot.run.arguments="--app.message-count=1000 --spring.kafka.producer.acks=0"
```

### Effect of batching (application-level)

The `app.batch-size` parameter controls how many messages are sent asynchronously before waiting for all futures to complete. Higher values increase throughput but the latency reported is per-batch, not per-message.

```bash
# Batch of 10 messages
./mvnw spring-boot:run \
  -Dspring-boot.run.arguments="--app.message-count=1000 --app.batch-size=10"

# Batch of 100 messages
./mvnw spring-boot:run \
  -Dspring-boot.run.arguments="--app.message-count=1000 --app.batch-size=100"
```

### Effect of linger.ms

`linger.ms` makes the producer wait before sending a batch, allowing more records to accumulate. This trades latency for throughput. Combined with `app.batch-size` > 1 for best effect.

```bash
# 50ms linger with batch of 10
./mvnw spring-boot:run \
  -Dspring-boot.run.arguments="--app.message-count=1000 --app.batch-size=10 --spring.kafka.producer.properties.linger.ms=50"

# 200ms linger with batch of 50
./mvnw spring-boot:run \
  -Dspring-boot.run.arguments="--app.message-count=1000 --app.batch-size=50 --spring.kafka.producer.properties.linger.ms=200"
```

### Effect of message size

Larger messages increase network and disk I/O per record. Compare small vs large payloads to understand throughput limits.

```bash
# Small messages (256 bytes)
./mvnw spring-boot:run \
  -Dspring-boot.run.arguments="--app.message-count=1000 --app.message-size-bytes=256"

# Large messages (10 KB)
./mvnw spring-boot:run \
  -Dspring-boot.run.arguments="--app.message-count=1000 --app.message-size-bytes=10240"

# Very large messages (100 KB)
./mvnw spring-boot:run \
  -Dspring-boot.run.arguments="--app.message-count=1000 --app.message-size-bytes=102400"
```

### Effect of compression

Compression reduces network bandwidth at the cost of CPU. Useful when messages are large or network is the bottleneck.

```bash
# Snappy (fast, moderate compression)
./mvnw spring-boot:run \
  -Dspring-boot.run.arguments="--app.message-count=1000 --spring.kafka.producer.compression-type=snappy"

# LZ4 (fast, good compression)
./mvnw spring-boot:run \
  -Dspring-boot.run.arguments="--app.message-count=1000 --spring.kafka.producer.compression-type=lz4"

# Zstd (slower, best compression)
./mvnw spring-boot:run \
  -Dspring-boot.run.arguments="--app.message-count=1000 --spring.kafka.producer.compression-type=zstd"
```

### High throughput configuration

Combines batching, linger, and compression to maximize throughput. Expect higher per-message latency but significantly more messages per second.

```bash
./mvnw spring-boot:run \
  -Dspring-boot.run.arguments="--app.message-count=5000 --app.batch-size=100 --spring.kafka.producer.properties.linger.ms=100 --spring.kafka.producer.compression-type=lz4 --spring.kafka.producer.acks=1"
```

### Low latency configuration

Synchronous sends with no linger and acks=1. Minimizes latency at the cost of throughput and durability.

```bash
./mvnw spring-boot:run \
  -Dspring-boot.run.arguments="--app.message-count=1000 --app.batch-size=1 --spring.kafka.producer.properties.linger.ms=0 --spring.kafka.producer.acks=1"
```

### Duration-based sustained load

Run for a fixed duration to observe broker behavior under sustained load. Useful for monitoring dashboards.

```bash
# 30 minutes of sustained traffic with batching
./mvnw spring-boot:run \
  -Dspring-boot.run.arguments="--app.duration-minutes=30 --app.batch-size=10 --spring.kafka.producer.properties.linger.ms=50"
```

### Full MSK example with IAM

```bash
./mvnw spring-boot:run -Dspring-boot.run.profiles=iam \
  -Dspring-boot.run.arguments="--spring.kafka.bootstrap-servers=<broker>:9098 --app.topic=my-topic --app.message-count=5000 --app.message-size-bytes=1024 --app.batch-size=10 --spring.kafka.producer.properties.linger.ms=50 --spring.kafka.producer.acks=all"
```

## Topic Auto-Creation

If the topic doesn't exist, it is created with:
- 6 partitions
- Replication factor: 3
- min.insync.replicas: 2 (omitted for MSK Express if not supported)

## Output

Each run produces:
- Per-message log with partition, offset, and latency (every 100 messages in sync mode, per batch in batch mode)
- Summary statistics: avg, min, max, p50, p95, p99 latency and throughput (msg/s)
- CSV file: `latency-YYYYMMDD-HHmmss.csv` with columns: seq, latency_ms, partition, offset, timestamp

## CloudWatch Dashboards

The `dashboard/` directory contains scripts to deploy CloudWatch dashboards for monitoring MSK clusters. See [dashboard/README.md](dashboard/README.md) for details.

| Script | Dashboards | Purpose |
|---|---|---|
| `deploy-dashboard.py` | MSK-Producer-Standard, MSK-Producer-Express | Produce latency, throughput, replication, throttling |
| `deploy-consumer-dashboard.py` | MSK-Consumer-Standard, MSK-Consumer-Express | Fetch latency, consumer lag, fetch throttling |
| `deploy-health-dashboard.py` | MSK-Health-Standard, MSK-Health-Express | CPU, memory, disk, network, partitions, IAM |

## License

MIT
