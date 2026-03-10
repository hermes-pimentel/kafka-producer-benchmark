#!/usr/bin/env python3
"""Deploy CloudWatch dashboards for MSK producer monitoring with cluster dropdown."""

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


def widget(title, metric, max_brokers, w=12):
    return {
        "type": "metric", "width": w, "height": 6,
        "properties": {
            "title": title, "region": REGION, "period": 60,
            "stat": "Average", "view": "timeSeries", "stacked": False,
            "metrics": broker_metrics(metric, max_brokers)
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
    w = lambda title, metric: widget(title, metric, max_brokers)

    widgets = [
        text("## Produce Latency"),
        w("ProduceTotalTimeMsMean", "ProduceTotalTimeMsMean"),
        w("ProduceResponseSendTimeMsMean", "ProduceResponseSendTimeMsMean"),
    ]

    if is_std:
        widgets += [
            text("## Produce Latency Breakdown (queue > local/replication > response)"),
            w("ProduceRequestQueueTimeMsMean", "ProduceRequestQueueTimeMsMean"),
            w("ProduceLocalTimeMsMean (includes replication wait for ack=all)", "ProduceLocalTimeMsMean"),
            w("ProduceResponseQueueTimeMsMean", "ProduceResponseQueueTimeMsMean"),
        ]

    widgets += [
        text("## Throughput"),
        w("BytesInPerSec", "BytesInPerSec"),
        w("BytesOutPerSec", "BytesOutPerSec"),
        w("MessagesInPerSec", "MessagesInPerSec"),
        w("RequestBytesMean", "RequestBytesMean"),
        text("## Replication"),
        w("ReplicationBytesInPerSec", "ReplicationBytesInPerSec"),
        w("ReplicationBytesOutPerSec", "ReplicationBytesOutPerSec"),
    ]

    if is_std:
        widgets += [
            w("UnderReplicatedPartitions", "UnderReplicatedPartitions"),
            w("UnderMinIsrPartitionCount", "UnderMinIsrPartitionCount"),
        ]

    widgets += [
        text("## Throttling"),
        w("ProduceThrottleTime", "ProduceThrottleTime"),
        w("RequestHandlerAvgIdlePercent", "RequestHandlerAvgIdlePercent"),
    ]

    if not is_std:
        widgets += [
            w("ProduceThrottleByteRate", "ProduceThrottleByteRate"),
            w("ProduceThrottleQueueSize", "ProduceThrottleQueueSize"),
        ]

    widgets += [text("## Broker Health")]

    if is_std:
        widgets += [
            w("CPUCreditBalance", "CPUCreditBalance"),
            w("BurstBalance", "BurstBalance"),
            w("VolumeQueueLength", "VolumeQueueLength"),
            w("VolumeTotalWriteTime", "VolumeTotalWriteTime"),
            w("TrafficShaping", "TrafficShaping"),
        ]
    else:
        widgets += [
            w("CpuIdle", "CpuIdle"),
            w("MemoryUsed", "MemoryUsed"),
            text("## Network"),
            w("TrafficBytes", "TrafficBytes"),
            w("TcpConnections", "TcpConnections"),
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
        deploy("MSK-Producer-Standard", build_dashboard("standard", standard, max_b))
    if express:
        max_b = max(c["brokers"] for c in express)
        deploy("MSK-Producer-Express", build_dashboard("express", express, max_b))

    print("\nDone. Use the cluster dropdown at the top of each dashboard.")


if __name__ == "__main__":
    main()
