#!/usr/bin/env python3
"""Analyze MSK broker logs from CloudWatch to discover client connections, consumer groups, and topic activity.

Works with INFO-level broker logs (default MSK logging). No need for DEBUG/TRACE.
Extracts: TCP connections, consumer group membership, topic write activity.

Note: MSK masks internal IPs as 'INTERNAL_IP' in CloudWatch Logs.
For full request-level detail (clientId per request, topics per produce/fetch),
DEBUG on kafka.request.logger is needed but MSK throttles DEBUG logs to CloudWatch.
Use S3 as log destination for unthrottled DEBUG logs.
"""

import argparse
import json
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import boto3

REGION = "us-east-1"
LOG_GROUP_PREFIX = "/aws/msk"


def get_log_group(cluster_name):
    return f"{LOG_GROUP_PREFIX}/{cluster_name}/broker-logs"


def run_query(logs_client, log_group, query, start_time, end_time):
    resp = logs_client.start_query(
        logGroupName=log_group,
        startTime=int(start_time.timestamp()),
        endTime=int(end_time.timestamp()),
        queryString=query,
        limit=10000,
    )
    query_id = resp["queryId"]
    while True:
        result = logs_client.get_query_results(queryId=query_id)
        if result["status"] in ("Complete", "Failed", "Cancelled"):
            break
        time.sleep(1)
    if result["status"] != "Complete":
        print(f"Query {result['status']}", file=sys.stderr)
        return []
    return result.get("results", [])


def extract_field(results, field="@message"):
    return [next((f["value"] for f in row if f["field"] == field), "") for row in results]


def analyze(cluster_name, minutes):
    logs = boto3.client("logs", region_name=REGION)
    log_group = get_log_group(cluster_name)
    end = datetime.now(timezone.utc)
    start = end - timedelta(minutes=minutes)

    print(f"Cluster: {cluster_name}")
    print(f"Log group: {log_group}")
    print(f"Window: {start.strftime('%H:%M:%S')} - {end.strftime('%H:%M:%S')} UTC ({minutes} min)\n")

    # --- Query 1: TCP connections ---
    print("Querying TCP connections...")
    tcp_results = run_query(logs, log_group, """
        fields @message, @logStream
        | filter @message like /TCP CONNECTION INFO/
        | limit 10000
    """, start, end)

    tcp_count_by_broker = defaultdict(int)
    for row in tcp_results:
        stream = next((f["value"] for f in row if f["field"] == "@logStream"), "")
        m = re.search(r'Broker-(\d+)', stream)
        broker = m.group(1) if m else "?"
        tcp_count_by_broker[broker] += 1

    # --- Query 2: Consumer group activity ---
    print("Querying consumer groups...")
    group_msgs = extract_field(run_query(logs, log_group, """
        fields @message
        | filter @message like /GroupCoordinator/
        | filter @message like /clientId/
        | limit 10000
    """, start, end))

    consumer_groups = defaultdict(lambda: {"clients": set(), "events": 0})
    for msg in group_msgs:
        gm = re.search(r'group (\S+)', msg)
        cm = re.search(r'clientId=([^,)]+)', msg)
        if gm and cm:
            group = gm.group(1)
            client = cm.group(1)
            consumer_groups[group]["clients"].add(client)
            consumer_groups[group]["events"] += 1

    # --- Query 3: Topic write activity (ProducerStateManager + LocalLog) ---
    print("Querying topic activity...")
    topic_msgs = extract_field(run_query(logs, log_group, """
        fields @message
        | filter @message like /partition=/ and (@message like /ProducerStateManager/ or @message like /Rolled new log segment/)
        | limit 10000
    """, start, end))

    topic_activity = defaultdict(lambda: {"segments_rolled": 0, "snapshots": 0, "partitions": set()})
    for msg in topic_msgs:
        pm = re.search(r'partition=([^,\s\]]+)-(\d+)', msg)
        if pm:
            topic = pm.group(1)
            partition = pm.group(2)
            if topic.startswith("__"):
                continue
            topic_activity[topic]["partitions"].add(partition)
            if "Rolled new log segment" in msg:
                topic_activity[topic]["segments_rolled"] += 1
            if "producer snapshot" in msg:
                topic_activity[topic]["snapshots"] += 1

    # --- Query 4: Check for DEBUG request.logger (if available) ---
    print("Checking for request.logger DEBUG logs...")
    debug_msgs = extract_field(run_query(logs, log_group, """
        fields @message
        | filter @message like /kafka.request.logger/
        | filter @message like /requestApiKeyName/
        | limit 100
    """, start, end))

    request_clients = defaultdict(lambda: {"count": 0, "apis": set(), "topics": set()})
    for msg in debug_msgs:
        cid_m = re.search(r'"clientId":"([^"]*)"', msg)
        api_m = re.search(r'"requestApiKeyName":"([^"]*)"', msg)
        if cid_m and api_m:
            cid = cid_m.group(1)
            api = api_m.group(1)
            request_clients[cid]["count"] += 1
            request_clients[cid]["apis"].add(api)
            topics = re.findall(r'"topic":"([^"]*)"', msg)
            request_clients[cid]["topics"].update(t for t in topics if not t.startswith("__"))

    # === REPORT ===
    sep = "=" * 80

    print(f"\n{sep}")
    print("TCP CONNECTIONS")
    print(sep)
    total_tcp = sum(tcp_count_by_broker.values())
    if tcp_count_by_broker:
        for broker, count in sorted(tcp_count_by_broker.items()):
            print(f"  Broker {broker}: {count} new connections")
        print(f"  Total: {total_tcp} new connections in {minutes} min")
    else:
        print("  No TCP connection events found")

    print(f"\n{sep}")
    print("CONSUMER GROUPS")
    print(sep)
    if consumer_groups:
        print(f"{'Group':<45} {'Clients':>8}  {'Events':>8}  Client IDs")
        print("-" * 80)
        for group, data in sorted(consumer_groups.items(), key=lambda x: -x[1]["events"]):
            clients_str = ", ".join(sorted(data["clients"]))
            print(f"{group:<45} {len(data['clients']):>8}  {data['events']:>8}  {clients_str}")
    else:
        print("  No consumer group activity found")

    print(f"\n{sep}")
    print("TOPICS WITH WRITE ACTIVITY")
    print(sep)
    if topic_activity:
        print(f"{'Topic':<40} {'Partitions':>10} {'Segments':>10} {'Snapshots':>10}")
        print("-" * 72)
        for topic, data in sorted(topic_activity.items(), key=lambda x: -x[1]["segments_rolled"]):
            print(f"{topic:<40} {len(data['partitions']):>10} {data['segments_rolled']:>10} {data['snapshots']:>10}")
    else:
        print("  No topic write activity found")

    if request_clients:
        print(f"\n{sep}")
        print("REQUEST-LEVEL CLIENTS (from kafka.request.logger DEBUG)")
        print(sep)
        print(f"{'Client ID':<40} {'Requests':>8}  {'APIs':<20} Topics")
        print("-" * 80)
        for cid, data in sorted(request_clients.items(), key=lambda x: -x[1]["count"]):
            apis = ", ".join(sorted(data["apis"]))
            topics = ", ".join(sorted(data["topics"])) or "-"
            print(f"{cid:<40} {data['count']:>8}  {apis:<20} {topics}")
    else:
        print(f"\n  Note: No kafka.request.logger DEBUG entries found.")
        print("  MSK throttles DEBUG logs to CloudWatch. For full request-level detail,")
        print("  configure S3 as log destination and enable kafka.request.logger=DEBUG.")

    print(f"\n{sep}")
    print("SUMMARY")
    print(sep)
    print(f"  TCP connections:    {total_tcp}")
    print(f"  Consumer groups:    {len(consumer_groups)}")
    print(f"  Active topics:      {len(topic_activity)}")
    print(f"  DEBUG log entries:  {sum(d['count'] for d in request_clients.values())}")
    print(sep)


def main():
    parser = argparse.ArgumentParser(description="Analyze MSK client connections from broker logs")
    parser.add_argument("--cluster", required=True, help="MSK cluster name")
    parser.add_argument("--minutes", type=int, default=10, help="Time window in minutes (default: 10)")
    parser.add_argument("--region", default="us-east-1", help="AWS region (default: us-east-1)")
    args = parser.parse_args()

    global REGION
    REGION = args.region
    analyze(args.cluster, args.minutes)


if __name__ == "__main__":
    main()
