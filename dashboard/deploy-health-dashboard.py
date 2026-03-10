#!/usr/bin/env python3
"""Deploy CloudWatch dashboards for MSK cluster health monitoring with cluster dropdown."""

import json
import subprocess
import sys
import os

REGION = os.environ.get("AWS_REGION", "us-east-1")


def aws(service, op, **kwargs):
    cmd = ["aws", service, op, "--region", REGION, "--output", "json"]
    for k, v in kwargs.items():
        cmd += [f"--{k.replace('_', '-')}", v]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"ERROR: {r.stderr}", file=sys.stderr)
        sys.exit(1)
    return json.loads(r.stdout) if r.stdout.strip() else {}


def discover_clusters():
    data = aws("kafka", "list-clusters-v2")
    standard, express = [], []
    for c in data.get("ClusterInfoList", []):
        if c.get("State") != "ACTIVE":
            continue
        name = c["ClusterName"]
        prov = c.get("Provisioned", {})
        itype = prov.get("BrokerNodeGroupInfo", {}).get("InstanceType", "")
        brokers = prov.get("NumberOfBrokerNodes", 3)
        entry = {"name": name, "brokers": brokers}
        if itype.startswith("express."):
            express.append(entry)
        else:
            standard.append(entry)
    return standard, express


def broker_metrics(metric, max_brokers):
    metrics = []
    for i in range(1, max_brokers + 1):
        metrics.append([
            "AWS/Kafka", metric,
            "Cluster Name", "${cluster}",
            "Broker ID", str(i),
            {"label": f"Broker {i}"}
        ])
    return metrics


def cluster_metric(metric):
    """Metrics with only Cluster Name dimension (no Broker ID)."""
    return [["AWS/Kafka", metric, "Cluster Name", "${cluster}", {"label": metric}]]


def broker_widget(title, metric, max_brokers, w=12):
    return {
        "type": "metric", "width": w, "height": 6,
        "properties": {
            "title": title, "region": REGION, "period": 60,
            "stat": "Average", "view": "timeSeries", "stacked": False,
            "metrics": broker_metrics(metric, max_brokers)
        }
    }


def cluster_widget(title, metric, w=12, stat="Average"):
    return {
        "type": "metric", "width": w, "height": 6,
        "properties": {
            "title": title, "region": REGION, "period": 60,
            "stat": stat, "view": "timeSeries", "stacked": False,
            "metrics": cluster_metric(metric)
        }
    }


def text(md):
    return {"type": "text", "width": 24, "height": 2, "properties": {"markdown": md}}


def build_dashboard(cluster_type, clusters, max_brokers):
    variables = [{
        "id": "cluster", "type": "property", "property": "Cluster Name",
        "inputType": "select", "defaultValue": clusters[0]["name"], "visible": True,
        "values": [{"value": c["name"], "label": c["name"]} for c in clusters]
    }]

    is_std = cluster_type == "standard"
    bw = lambda title, metric: broker_widget(title, metric, max_brokers)
    cw = lambda title, metric, **kw: cluster_widget(title, metric, **kw)

    # CPU
    widgets = [text("## 🖥️ CPU")]
    if is_std:
        widgets += [
            bw("CpuIdle (%)", "CpuIdle"),
            bw("CpuUser (%)", "CpuUser"),
            bw("CpuSystem (%)", "CpuSystem"),
            bw("CpuIoWait (%)", "CpuIoWait"),
        ]
    else:
        widgets += [
            bw("CpuIdle (%)", "CpuIdle"),
            bw("CpuUser (%)", "CpuUser"),
            bw("CpuSystem (%)", "CpuSystem"),
        ]

    if is_std:
        widgets += [
            bw("CPUCreditBalance", "CPUCreditBalance"),
        ]

    # Memory
    widgets += [text("## 🧠 Memory")]
    widgets += [
        bw("MemoryUsed (bytes)", "MemoryUsed"),
        bw("MemoryFree (bytes)", "MemoryFree"),
        bw("MemoryBuffered (bytes)", "MemoryBuffered"),
        bw("MemoryCached (bytes)", "MemoryCached"),
    ]
    if is_std:
        widgets += [
            bw("HeapMemoryAfterGC (%)", "HeapMemoryAfterGC"),
            bw("SwapUsed (bytes)", "SwapUsed"),
        ]

    # Disk / Storage
    widgets += [text("## 💾 Disk & Storage")]
    if is_std:
        widgets += [
            bw("KafkaDataLogsDiskUsed (%)", "KafkaDataLogsDiskUsed"),
            bw("KafkaAppLogsDiskUsed (%)", "KafkaAppLogsDiskUsed"),
            bw("RootDiskUsed (%)", "RootDiskUsed"),
            bw("BurstBalance", "BurstBalance"),
            bw("VolumeQueueLength", "VolumeQueueLength"),
            bw("VolumeTotalReadTime (s)", "VolumeTotalReadTime"),
            bw("VolumeTotalWriteTime (s)", "VolumeTotalWriteTime"),
            bw("VolumeReadOps", "VolumeReadOps"),
            bw("VolumeWriteOps", "VolumeWriteOps"),
        ]
    else:
        widgets += [
            cw("StorageUsed (bytes)", "StorageUsed"),
        ]

    # Network
    widgets += [text("## 🌐 Network")]
    widgets += [
        bw("BytesInPerSec", "BytesInPerSec"),
        bw("BytesOutPerSec", "BytesOutPerSec"),
        bw("ConnectionCount", "ConnectionCount"),
    ]
    if is_std:
        widgets += [
            bw("NetworkRxErrors", "NetworkRxErrors"),
            bw("NetworkTxErrors", "NetworkTxErrors"),
            bw("NetworkRxDropped", "NetworkRxDropped"),
            bw("NetworkTxDropped", "NetworkTxDropped"),
        ]
    else:
        widgets += [
            bw("NetworkRxErrors", "NetworkRxErrors"),
            bw("NetworkTxErrors", "NetworkTxErrors"),
            bw("TrafficBytes", "TrafficBytes"),
            bw("TcpConnections", "TcpConnections"),
        ]

    # Connection rates (PER_BROKER)
    widgets += [
        bw("ConnectionCreationRate", "ConnectionCreationRate"),
        bw("ConnectionCloseRate", "ConnectionCloseRate"),
    ]

    # Partitions & Leaders
    widgets += [text("## 📦 Partitions & Leaders")]
    widgets += [
        cw("GlobalPartitionCount", "GlobalPartitionCount"),
        cw("GlobalTopicCount", "GlobalTopicCount"),
        bw("PartitionCount (per broker)", "PartitionCount"),
        bw("LeaderCount (per broker)", "LeaderCount"),
    ]
    if is_std:
        widgets += [
            cw("OfflinePartitionsCount", "OfflinePartitionsCount"),
            bw("UnderReplicatedPartitions", "UnderReplicatedPartitions"),
            bw("UnderMinIsrPartitionCount", "UnderMinIsrPartitionCount"),
        ]

    # Replication
    widgets += [text("## 🔄 Replication")]
    widgets += [
        bw("ReplicationBytesInPerSec", "ReplicationBytesInPerSec"),
        bw("ReplicationBytesOutPerSec", "ReplicationBytesOutPerSec"),
    ]

    # Throttling & Request Handler
    widgets += [text("## 🚦 Throttling & Request Processing")]
    widgets += [
        bw("RequestHandlerAvgIdlePercent", "RequestHandlerAvgIdlePercent"),
    ]
    if is_std:
        widgets += [
            bw("NetworkProcessorAvgIdlePercent", "NetworkProcessorAvgIdlePercent"),
        ]
    else:
        widgets += [
            bw("NetworkProcessorAvgIdlePercent", "NetworkProcessorAvgIdlePercent"),
        ]

    widgets += [
        bw("RequestThrottleTime", "RequestThrottleTime"),
        bw("RequestThrottleQueueSize", "RequestThrottleQueueSize"),
    ]

    # Traffic shaping (Standard) / IAM (Express)
    if is_std:
        widgets += [
            text("## ⚠️ Traffic Shaping"),
            bw("TrafficShaping", "TrafficShaping"),
            bw("BwInAllowanceExceeded", "BwInAllowanceExceeded"),
            bw("BwOutAllowanceExceeded", "BwOutAllowanceExceeded"),
            bw("ConntrackAllowanceExceeded", "ConntrackAllowanceExceeded"),
        ]

    # IAM
    widgets += [
        text("## 🔐 IAM"),
        bw("IAMNumberOfConnectionRequests", "IAMNumberOfConnectionRequests"),
        bw("IAMTooManyConnections", "IAMTooManyConnections"),
    ]

    return {"variables": variables, "widgets": widgets}


def deploy(name, body):
    print(f"Deploying: {name}")
    aws("cloudwatch", "put-dashboard", dashboard_name=name, dashboard_body=json.dumps(body))
    print(f"✅ https://{REGION}.console.aws.amazon.com/cloudwatch/home?region={REGION}#dashboards/dashboard/{name}")


def main():
    standard, express = discover_clusters()
    print(f"Standard: {[c['name'] for c in standard]}")
    print(f"Express: {[c['name'] for c in express]}")

    if standard:
        max_b = max(c["brokers"] for c in standard)
        deploy("MSK-Health-Standard", build_dashboard("standard", standard, max_b))
    if express:
        max_b = max(c["brokers"] for c in express)
        deploy("MSK-Health-Express", build_dashboard("express", express, max_b))

    print("\nDone. Use the cluster dropdown at the top of each dashboard.")


if __name__ == "__main__":
    main()
