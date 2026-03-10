#!/usr/bin/env python3
"""Analyze VPC Flow Logs to discover clients connecting to MSK brokers.

Queries CloudWatch Logs for flow log data on broker ENIs, then reports
unique source IPs, TCP connections per broker, and cluster totals.

Usage:
  python3 analyze-flow-logs.py --cluster <cluster-name> [--region <region>] [--minutes <N>]

Prerequisites:
  - VPC Flow Logs enabled on MSK broker ENIs → CloudWatch log group /aws/vpc-flow-logs/<cluster-name>
  - Custom format: version account-id interface-id srcaddr dstaddr srcport dstport protocol packets bytes start end action log-status tcp-flags
"""
import argparse
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import boto3

KAFKA_PORTS = {"9092", "9094", "9096", "9098"}
SEP = "=" * 80


def run_query(logs, log_group, query, start, end):
    resp = logs.start_query(
        logGroupName=log_group, startTime=int(start.timestamp()),
        endTime=int(end.timestamp()), queryString=query, limit=10000,
    )
    while True:
        result = logs.get_query_results(queryId=resp["queryId"])
        if result["status"] in ("Complete", "Failed", "Cancelled"):
            break
        time.sleep(1)
    if result["status"] != "Complete":
        print(f"  Query {result['status']}", file=sys.stderr)
        return []
    return result.get("results", [])


def get_broker_enis(ec2, cluster_arn_fragment):
    enis = ec2.describe_network_interfaces(
        Filters=[{"Name": "description", "Values": [f"*Amazon MSK*{cluster_arn_fragment}*"]}]
    )["NetworkInterfaces"]
    return {e["NetworkInterfaceId"]: e["PrivateIpAddress"] for e in enis}


def parse_flow_log(msg):
    """Parse: ver acct eni src dst sp dp proto pkts bytes start end action status flags"""
    parts = msg.split()
    if len(parts) < 13:
        return None
    return {"src": parts[3], "dst": parts[4], "sp": parts[5], "dp": parts[6],
            "proto": parts[7], "pkts": parts[8], "bytes": parts[9], "action": parts[12]}


def analyze(cluster_name, region, minutes, log_group_override=None):
    logs = boto3.client("logs", region_name=region)
    ec2 = boto3.client("ec2", region_name=region)
    kafka = boto3.client("kafka", region_name=region)

    log_group = log_group_override or f"/aws/vpc-flow-logs/{cluster_name}"
    end = datetime.now(timezone.utc)
    start = end - timedelta(minutes=minutes)

    clusters = kafka.list_clusters_v2()["ClusterInfoList"]
    cluster = next((c for c in clusters if c["ClusterName"] == cluster_name), None)
    if not cluster:
        print(f"Error: cluster '{cluster_name}' not found", file=sys.stderr)
        sys.exit(1)

    eni_map = get_broker_enis(ec2, cluster["ClusterArn"].split("/")[1])
    broker_ips = set(eni_map.values())

    print(f"{SEP}")
    print(f"VPC FLOW LOG ANALYSIS - {cluster_name}")
    print(f"Region: {region}  |  Window: {minutes} min  |  Brokers: {len(broker_ips)} IPs, {len(eni_map)} ENIs")
    print(f"Broker IPs: {', '.join(sorted(broker_ips))}")
    print(f"{SEP}")

    results = run_query(logs, log_group,
        "filter @message like /ACCEPT/ and @message not like /NODATA/ | fields @message | sort @timestamp desc",
        start, end)

    if not results:
        print("\n  No flow log entries found. Flow logs may take 5-10 min to appear after creation.")
        return

    # Track distinct TCP connections: (src, src_port, dst, dst_port)
    # and aggregate stats per connection
    conn_stats = defaultdict(lambda: {"packets": 0, "bytes": 0})
    # Per broker: src_ip -> set of connections + totals
    per_broker = defaultdict(lambda: defaultdict(lambda: {"conns": set(), "packets": 0, "bytes": 0, "ports": set()}))
    per_source = defaultdict(lambda: {"conns": set(), "packets": 0, "bytes": 0, "brokers": set(), "ports": set()})

    for row in results:
        msg = next((f["value"] for f in row if f["field"] == "@message"), "")
        rec = parse_flow_log(msg)
        if not rec or rec["action"] != "ACCEPT" or rec["proto"] != "6":
            continue
        if rec["dp"] not in KAFKA_PORTS or rec["dst"] not in broker_ips or rec["src"] in broker_ips:
            continue

        src, dst, sp, dp = rec["src"], rec["dst"], rec["sp"], rec["dp"]
        pkts, bts = int(rec["pkts"]), int(rec["bytes"])
        conn_key = (src, sp, dst, dp)

        conn_stats[conn_key]["packets"] += pkts
        conn_stats[conn_key]["bytes"] += bts

        per_broker[dst][src]["conns"].add(conn_key)
        per_broker[dst][src]["packets"] += pkts
        per_broker[dst][src]["bytes"] += bts
        per_broker[dst][src]["ports"].add(dp)

        per_source[src]["conns"].add(conn_key)
        per_source[src]["packets"] += pkts
        per_source[src]["bytes"] += bts
        per_source[src]["brokers"].add(dst)
        per_source[src]["ports"].add(dp)

    if not per_source:
        print("\n  Flow log entries found but none matched Kafka ports to broker IPs.")
        return

    # --- Per broker ---
    print(f"\n{SEP}")
    print("CONNECTIONS PER BROKER")
    print(SEP)
    for broker_ip in sorted(per_broker.keys()):
        clients = per_broker[broker_ip]
        total_conns = sum(len(c["conns"]) for c in clients.values())
        total_bytes = sum(c["bytes"] for c in clients.values())
        print(f"\n  Broker {broker_ip} ({len(clients)} unique IPs, {total_conns} TCP connections, {total_bytes:,} bytes)")
        print(f"  {'Source IP':<20s} {'Conns':>6s} {'Packets':>10s} {'Bytes':>12s} {'Ports'}")
        print("  " + "-" * 65)
        for src, data in sorted(clients.items(), key=lambda x: -len(x[1]["conns"])):
            ports = ",".join(sorted(data["ports"]))
            print(f"  {src:<20s} {len(data['conns']):>6d} {data['packets']:>10d} {data['bytes']:>12,d} {ports}")

    # --- Per source IP ---
    print(f"\n{SEP}")
    print("CONNECTIONS PER SOURCE IP (cluster-wide)")
    print(SEP)
    print(f"  {'Source IP':<20s} {'Conns':>6s} {'Packets':>10s} {'Bytes':>12s} {'Brokers':>8s} {'Ports'}")
    print("  " + "-" * 75)
    for src, data in sorted(per_source.items(), key=lambda x: -len(x[1]["conns"])):
        ports = ",".join(sorted(data["ports"]))
        print(f"  {src:<20s} {len(data['conns']):>6d} {data['packets']:>10d} {data['bytes']:>12,d} {len(data['brokers']):>8d} {ports}")

    # --- Summary ---
    print(f"\n{SEP}")
    print("SUMMARY")
    print(SEP)
    all_conns = set()
    total_bytes = 0
    for d in per_source.values():
        all_conns.update(d["conns"])
        total_bytes += d["bytes"]
    print(f"  Unique source IPs:    {len(per_source)}")
    print(f"  TCP connections:      {len(all_conns)}")
    print(f"  Total bytes:          {total_bytes:,}")
    print(f"  Brokers with traffic: {len(per_broker)}")
    print(f"  Time window:          {minutes} min")
    print(SEP)


def main():
    p = argparse.ArgumentParser(description="Analyze VPC Flow Logs for MSK client connections")
    p.add_argument("--cluster", required=True, help="MSK cluster name")
    p.add_argument("--region", default="us-east-1", help="AWS region (default: us-east-1)")
    p.add_argument("--minutes", type=int, default=10, help="Time window in minutes (default: 10)")
    p.add_argument("--log-group", default=None, help="CloudWatch log group (default: /aws/vpc-flow-logs/<cluster>)")
    args = p.parse_args()
    analyze(args.cluster, args.region, args.minutes, args.log_group)


if __name__ == "__main__":
    main()
