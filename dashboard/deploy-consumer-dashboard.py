#!/usr/bin/env python3
"""Deploy CloudWatch dashboards for MSK consumer monitoring with cluster dropdown."""

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


def consumer_lag_metrics(metric):
    """Consumer lag metrics use Consumer Group + Topic dimensions (no Broker ID)."""
    return [[
        "AWS/Kafka", metric,
        "Consumer Group", "${consumer_group}",
        "Topic", "${topic}",
        {"label": metric}
    ]]


def broker_widget(title, metric, max_brokers, w=12):
    return {
        "type": "metric", "width": w, "height": 6,
        "properties": {
            "title": title, "region": REGION, "period": 60,
            "stat": "Average", "view": "timeSeries", "stacked": False,
            "metrics": broker_metrics(metric, max_brokers)
        }
    }


def lag_widget(title, metric, w=12):
    return {
        "type": "metric", "width": w, "height": 6,
        "properties": {
            "title": title, "region": REGION, "period": 60,
            "stat": "Maximum", "view": "timeSeries", "stacked": False,
            "metrics": consumer_lag_metrics(metric)
        }
    }


def text(md):
    return {"type": "text", "width": 24, "height": 2, "properties": {"markdown": md}}


def build_dashboard(cluster_type, clusters, max_brokers):
    variables = [
        {
            "id": "cluster", "type": "property", "property": "Cluster Name",
            "inputType": "select", "defaultValue": clusters[0]["name"], "visible": True,
            "values": [{"value": c["name"], "label": c["name"]} for c in clusters]
        },
        {
            "id": "consumer_group", "type": "property", "property": "Consumer Group",
            "inputType": "input", "defaultValue": " ", "visible": True,
        },
        {
            "id": "topic", "type": "property", "property": "Topic",
            "inputType": "input", "defaultValue": " ", "visible": True,
        },
    ]

    is_std = cluster_type == "standard"
    bw = lambda title, metric: broker_widget(title, metric, max_brokers)
    lw = lambda title, metric: lag_widget(title, metric)

    widgets = [
        text("## 📉 Consumer Lag (type consumer group and topic above)"),
        lw("MaxOffsetLag", "MaxOffsetLag"),
        lw("SumOffsetLag", "SumOffsetLag"),
        lw("EstimatedMaxTimeLag (seconds)", "EstimatedMaxTimeLag"),
        lw("RollingEstimatedTimeLagMax (seconds)", "RollingEstimatedTimeLagMax"),
    ]

    # Fetch consumer latency (PER_BROKER)
    widgets += [
        text("## ⏱️ Fetch Consumer Latency"),
        bw("FetchConsumerTotalTimeMsMean", "FetchConsumerTotalTimeMsMean"),
        bw("FetchConsumerResponseSendTimeMsMean", "FetchConsumerResponseSendTimeMsMean"),
    ]

    if is_std:
        widgets += [
            text("## 🔬 Fetch Consumer Latency Breakdown (queue → local → response)"),
            bw("FetchConsumerRequestQueueTimeMsMean", "FetchConsumerRequestQueueTimeMsMean"),
            bw("FetchConsumerLocalTimeMsMean", "FetchConsumerLocalTimeMsMean"),
            bw("FetchConsumerResponseQueueTimeMsMean", "FetchConsumerResponseQueueTimeMsMean"),
        ]
    else:
        widgets += [
            bw("FetchConsumerRequestQueueTimeMsMean", "FetchConsumerRequestQueueTimeMsMean"),
            bw("FetchConsumerLocalTimeMsMean", "FetchConsumerLocalTimeMsMean"),
            bw("FetchConsumerResponseQueueTimeMsMean", "FetchConsumerResponseQueueTimeMsMean"),
        ]

    # Follower fetch (PER_BROKER, Standard only)
    if is_std:
        widgets += [
            text("## 🔄 Fetch Follower Latency"),
            bw("FetchFollowerTotalTimeMsMean", "FetchFollowerTotalTimeMsMean"),
            bw("FetchFollowerLocalTimeMsMean", "FetchFollowerLocalTimeMsMean"),
            bw("FetchFollowerRequestQueueTimeMsMean", "FetchFollowerRequestQueueTimeMsMean"),
            bw("FetchFollowerResponseQueueTimeMsMean", "FetchFollowerResponseQueueTimeMsMean"),
            bw("FetchFollowerResponseSendTimeMsMean", "FetchFollowerResponseSendTimeMsMean"),
        ]

    # Throughput
    widgets += [
        text("## 📊 Consumer Throughput"),
        bw("BytesOutPerSec", "BytesOutPerSec"),
    ]

    # Fetch throttling (PER_BROKER)
    widgets += [
        text("## 🚦 Fetch Throttling"),
        bw("FetchThrottleTime", "FetchThrottleTime"),
        bw("FetchThrottleByteRate", "FetchThrottleByteRate"),
        bw("FetchThrottleQueueSize", "FetchThrottleQueueSize"),
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
        deploy("MSK-Consumer-Standard", build_dashboard("standard", standard, max_b))
    if express:
        max_b = max(c["brokers"] for c in express)
        deploy("MSK-Consumer-Express", build_dashboard("express", express, max_b))

    print("\nDone. Use the dropdowns at the top of each dashboard.")
    print("💡 Type your consumer group name and topic in the input fields to see lag metrics.")


if __name__ == "__main__":
    main()
