# MSK CloudWatch Dashboards

Auto-discovers all active MSK clusters and creates dashboards with a dropdown to select which cluster to view. Separate dashboards for Standard and Express clusters.

## Dashboards

| Script | Dashboards Created | Purpose |
|---|---|---|
| `deploy-dashboard.py` | MSK-Producer-Standard, MSK-Producer-Express | Produce latency, throughput, replication, throttling |
| `deploy-consumer-dashboard.py` | MSK-Consumer-Standard, MSK-Consumer-Express | Fetch latency, consumer lag, fetch throttling |
| `deploy-health-dashboard.py` | MSK-Health-Standard, MSK-Health-Express | CPU, memory, disk, network, partitions, replication, IAM |

## Deploy

```bash
# Default (us-east-1)
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
- AWS CLI with `cloudwatch:PutDashboard` and `kafka:ListClustersV2` permissions
- Cluster monitoring level set to `PER_BROKER` for full metrics

## Consumer Dashboard Note

The consumer dashboard has input fields for Consumer Group and Topic at the top. Type your consumer group name and topic to see lag metrics (MaxOffsetLag, SumOffsetLag, EstimatedMaxTimeLag, RollingEstimatedTimeLagMax).
