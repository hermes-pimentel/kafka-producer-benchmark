# msk-test-spring

Kafka producer for latency testing with Spring Boot. Sends JSON messages with per-message latency measurement and exports results to CSV. Auto-creates topic if it doesn't exist.

## Requirements

- Java 17+
- Maven

## Usage

```bash
# Local (no auth) - runs for 10 minutes by default
./mvnw spring-boot:run

# MSK with TLS
./mvnw spring-boot:run \
  -Dspring-boot.run.arguments="--spring.kafka.bootstrap-servers=<broker>:9094 --spring.kafka.properties.security.protocol=SSL"

# MSK with IAM auth
./mvnw spring-boot:run -Dspring-boot.run.profiles=iam \
  -Dspring-boot.run.arguments="--spring.kafka.bootstrap-servers=<broker>:9098"
```

## Parameters

| Property | Default | Description |
|---|---|---|
| `app.topic` | producer-test-topic | Kafka topic (auto-created if missing) |
| `app.duration-minutes` | 10 | Run duration in minutes (used when message-count=0) |
| `app.message-count` | 0 | Number of messages (0 = use duration instead) |
| `app.message-size-bytes` | 512 | Approximate JSON payload size |
| `app.batch-size` | 1 | 1 = synchronous per message, >1 = async batch |
| `spring.kafka.producer.properties.linger.ms` | 0 | Producer linger |

## Run Modes

- `message-count=0` (default): runs for `duration-minutes` (default 10 min)
- `message-count=500`: sends exactly 500 messages then stops
- `message-count=500 duration-minutes=5`: sends up to 500 messages or stops at 5 min

Example with batch of 10 and 50ms linger:

```bash
./mvnw spring-boot:run -Dspring-boot.run.arguments="--app.batch-size=10 --spring.kafka.producer.properties.linger.ms=50"
```

Example with multiple parameters including bootstrap servers:

```bash
./mvnw spring-boot:run -Dspring-boot.run.profiles=iam \
  -Dspring-boot.run.arguments="--spring.kafka.bootstrap-servers=b-1.mycluster.xxx.kafka.us-east-1.amazonaws.com:9098 --app.topic=my-topic --app.message-count=500 --app.message-size-bytes=1024 --app.batch-size=10 --spring.kafka.producer.properties.linger.ms=50"
```

## Topic Auto-Creation

If the topic doesn't exist, it's created with:
- 6 partitions
- Replication factor: 3
- min.insync.replicas: 2

## Output

- Per-message log with partition, offset, and latency
- Statistics: avg, min, max, p50, p95, p99, throughput
- CSV file: `latency-YYYYMMDD-HHmmss.csv`
