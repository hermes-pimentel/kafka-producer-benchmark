# MSK CloudWatch Dashboards

Scripts to deploy CloudWatch dashboards for monitoring Amazon MSK clusters. Each script auto-discovers all active MSK clusters in the account, separates them by type (Standard vs Express), and creates dashboards with a dropdown to switch between clusters.

All metrics used are from the DEFAULT and PER_BROKER monitoring levels. DEFAULT metrics are free; PER_BROKER metrics are paid (see [CloudWatch pricing](https://aws.amazon.com/cloudwatch/pricing/)).

## Dashboards

| Script | Dashboards Created | Purpose |
|---|---|---|
| `deploy-dashboard.py` | MSK-Producer-Standard, MSK-Producer-Express | Produce latency, throughput, replication, throttling, broker health |
| `deploy-consumer-dashboard.py` | MSK-Consumer-Standard, MSK-Consumer-Express | Fetch latency breakdown, consumer lag, fetch throttling |
| `deploy-health-dashboard.py` | MSK-Health-Standard, MSK-Health-Express | CPU, memory, disk, network, partitions, replication, traffic shaping, IAM |

## What's Included

### Producer Dashboard

| Section | Standard | Express |
|---|---|---|
| Produce Latency | ProduceTotalTimeMsMean, ProduceResponseSendTimeMsMean | same |
| Latency Breakdown | ProduceRequestQueueTimeMsMean, ProduceLocalTimeMsMean, ProduceResponseQueueTimeMsMean | N/A |
| Throughput | BytesInPerSec, BytesOutPerSec, MessagesInPerSec, RequestBytesMean | same |
| Replication | ReplicationBytesIn/OutPerSec, UnderReplicatedPartitions, UnderMinIsrPartitionCount | ReplicationBytesIn/OutPerSec only |
| Throttling | ProduceThrottleTime, RequestHandlerAvgIdlePercent | same + ProduceThrottleByteRate, ProduceThrottleQueueSize |
| Broker Health | CPUCreditBalance, BurstBalance, VolumeQueueLength, VolumeTotalWriteTime, TrafficShaping | CpuIdle, MemoryUsed, TrafficBytes, TcpConnections |

### Consumer Dashboard

| Section | Standard | Express |
|---|---|---|
| Consumer Lag | MaxOffsetLag, SumOffsetLag, EstimatedMaxTimeLag, RollingEstimatedTimeLagMax | same |
| Fetch Latency | FetchConsumerTotalTimeMsMean, FetchConsumerResponseSendTimeMsMean | same |
| Latency Breakdown | FetchConsumerRequestQueueTimeMsMean, LocalTimeMsMean, ResponseQueueTimeMsMean | same (without section header) |
| Follower Fetch | FetchFollowerTotalTimeMsMean + full breakdown | N/A |
| Throughput | BytesOutPerSec | same |
| Fetch Throttling | FetchThrottleTime, FetchThrottleByteRate, FetchThrottleQueueSize | same |

### Health Dashboard

| Section | Standard | Express |
|---|---|---|
| CPU | CpuIdle, CpuUser, CpuSystem, CpuIoWait, CPUCreditBalance | CpuIdle, CpuUser, CpuSystem |
| Memory | MemoryUsed, MemoryFree, MemoryBuffered, MemoryCached, HeapMemoryAfterGC, SwapUsed | MemoryUsed, MemoryFree, MemoryBuffered, MemoryCached |
| Disk & Storage | KafkaDataLogsDiskUsed, KafkaAppLogsDiskUsed, RootDiskUsed, BurstBalance, Volume* | StorageUsed |
| Network | BytesIn/OutPerSec, ConnectionCount, Rx/Tx Errors, Rx/Tx Dropped | BytesIn/OutPerSec, ConnectionCount, Rx/Tx Errors, TrafficBytes, TcpConnections |
| Partitions | GlobalPartitionCount, GlobalTopicCount, PartitionCount, LeaderCount, OfflinePartitionsCount, UnderReplicated*, UnderMinIsr* | GlobalPartitionCount, GlobalTopicCount, PartitionCount, LeaderCount |
| Replication | ReplicationBytesIn/OutPerSec | same |
| Throttling | RequestHandlerAvgIdlePercent, NetworkProcessorAvgIdlePercent, RequestThrottleTime/QueueSize | same |
| Traffic Shaping | TrafficShaping, BwIn/OutAllowanceExceeded, ConntrackAllowanceExceeded | N/A |
| IAM | IAMNumberOfConnectionRequests, IAMTooManyConnections | same |

## Deploy

```bash
# Deploy all dashboards (us-east-1)
python3 deploy-dashboard.py
python3 deploy-consumer-dashboard.py
python3 deploy-health-dashboard.py

# Different region
AWS_REGION=eu-west-1 python3 deploy-dashboard.py
```

## Delete

```bash
aws cloudwatch delete-dashboards --dashboard-names \
  MSK-Producer-Standard MSK-Producer-Express \
  MSK-Consumer-Standard MSK-Consumer-Express \
  MSK-Health-Standard MSK-Health-Express
```

## Prerequisites

- Python 3
- AWS CLI configured with credentials
- IAM permissions: `cloudwatch:PutDashboard`, `kafka:ListClustersV2`
- Cluster monitoring level set to `PER_BROKER` for full metrics (DEFAULT metrics are always available)

## How It Works

1. Each script calls `aws kafka list-clusters-v2` to discover active clusters
2. Clusters are classified as Standard or Express based on instance type prefix (`express.*` vs `kafka.*`)
3. The maximum broker count across clusters of the same type determines how many per-broker metric lines are generated
4. Dashboards use CloudWatch variables for the cluster dropdown, so a single dashboard serves multiple clusters
5. `cloudwatch:PutDashboard` creates or updates the dashboard (idempotent)

## Consumer Dashboard Note

The consumer dashboard includes input fields for Consumer Group and Topic at the top. Type your consumer group name and topic to see lag metrics. These metrics use different CloudWatch dimensions (Consumer Group + Topic) than the per-broker metrics (Cluster Name + Broker ID).
