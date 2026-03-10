#!/usr/bin/env python3
"""Query Prometheus for MSK connection metrics from JMX.
Shows connections by client software, listener, and broker.

Usage:
  python3 prometheus-report.py <cluster-name> [--prometheus URL]

Example:
  python3 prometheus-report.py my-cluster
  python3 prometheus-report.py my-cluster --prometheus http://localhost:9090

Prerequisites:
  - Prometheus scraping MSK JMX exporter (Open Monitoring enabled on cluster)
"""
import argparse
import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta

SEP = "=" * 90


def query(prom_url, expr):
    url = f'{prom_url}/api/v1/query?query={urllib.parse.quote(expr)}'
    return json.loads(urllib.request.urlopen(url).read())["data"]["result"]


def query_range(prom_url, expr, start, end, step="30s"):
    url = f'{prom_url}/api/v1/query_range?query={urllib.parse.quote(expr)}&start={start}&end={end}&step={step}'
    return json.loads(urllib.request.urlopen(url).read())["data"]["result"]


def report(prom_url, cluster):
    now = datetime.now(timezone.utc)
    end_ts = int(now.timestamp())
    start_1h = int((now - timedelta(hours=1)).timestamp())

    print(SEP)
    print(f"MSK CONNECTION REPORT - {cluster}")
    print(f"Prometheus: {prom_url}")
    print(f"Time: {now.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(SEP)

    # --- Connections by client software ---
    results = query(prom_url, f'kafka_server_socket_server_metrics_connections{{ClusterName="{cluster}"}}')
    print(f"\n{SEP}")
    print("ACTIVE CONNECTIONS BY CLIENT SOFTWARE")
    print(SEP)
    rows = []
    for r in results:
        m = r["metric"]
        val = float(r["value"][1])
        if val > 0:
            rows.append({
                "broker": m["instance"].split(".")[0],
                "listener": m.get("listener", ""),
                "software": m.get("clientSoftwareName", "unknown"),
                "version": m.get("clientSoftwareVersion", ""),
                "conns": val,
            })
    if rows:
        agg = {}
        for row in rows:
            key = (row["software"], row["version"], row["listener"])
            agg[key] = agg.get(key, 0) + row["conns"]
        print(f"  {'Software':<30s} {'Version':<20s} {'Listener':<15s} {'Conns':>6s}")
        print("  " + "-" * 75)
        for (sw, ver, listener), conns in sorted(agg.items(), key=lambda x: -x[1]):
            print(f"  {sw:<30s} {ver:<20s} {listener:<15s} {conns:>6.0f}")

        print(f"\n  Per broker:")
        print(f"  {'Broker':<6s} {'Listener':<15s} {'Software':<30s} {'Version':<15s} {'Conns':>6s}")
        print("  " + "-" * 75)
        for row in sorted(rows, key=lambda x: (x["broker"], x["listener"])):
            print(f"  {row['broker']:<6s} {row['listener']:<15s} {row['software']:<30s} {row['version']:<15s} {row['conns']:>6.0f}")
    else:
        print("  No active connections found")

    # --- Connection count per listener ---
    results = query(prom_url, f'sum by (instance, listener) (kafka_server_socket_server_metrics_connection_count{{ClusterName="{cluster}"}})')
    print(f"\n{SEP}")
    print("CONNECTION COUNT PER LISTENER")
    print(SEP)
    print(f"  {'Broker':<6s} {'Listener':<15s} {'Count':>8s}")
    print("  " + "-" * 32)
    for r in sorted(results, key=lambda x: (x["metric"].get("instance",""), x["metric"].get("listener",""))):
        m = r["metric"]
        print(f"  {m.get('instance','').split('.')[0]:<6s} {m.get('listener',''):<15s} {float(r['value'][1]):>8.0f}")

    # --- Connection rates ---
    results = query(prom_url, f'kafka_server_socket_server_metrics_connection_accept_rate{{ClusterName="{cluster}"}}')
    close_results = query(prom_url, f'kafka_server_socket_server_metrics_connection_close_rate{{ClusterName="{cluster}"}}')
    print(f"\n{SEP}")
    print("CONNECTION RATES (per second)")
    print(SEP)
    print(f"  {'Broker':<6s} {'Listener':<15s} {'Accept/s':>10s} {'Close/s':>10s}")
    print("  " + "-" * 45)
    close_map = {}
    for r in close_results:
        m = r["metric"]
        key = (m["instance"].split(".")[0], m.get("listener",""))
        close_map[key] = float(r["value"][1])
    for r in sorted(results, key=lambda x: (x["metric"]["instance"], x["metric"].get("listener",""))):
        m = r["metric"]
        broker = m["instance"].split(".")[0]
        listener = m.get("listener","")
        accept = float(r["value"][1])
        close = close_map.get((broker, listener), 0)
        print(f"  {broker:<6s} {listener:<15s} {accept:>10.4f} {close:>10.4f}")

    # --- Request rates by type ---
    results = query(prom_url, f'kafka_network_RequestMetrics_OneMinuteRate{{ClusterName="{cluster}",name="RequestsPerSec"}}')
    print(f"\n{SEP}")
    print("REQUEST RATE BY TYPE (1min avg, req/s)")
    print(SEP)
    agg = {}
    for r in results:
        req = r["metric"].get("request","")
        agg[req] = agg.get(req, 0) + float(r["value"][1])
    print(f"  {'Request Type':<25s} {'Rate (all brokers)':>20s}")
    print("  " + "-" * 48)
    for req, rate in sorted(agg.items(), key=lambda x: -x[1]):
        if rate > 0.001:
            print(f"  {req:<25s} {rate:>20.2f}")

    # --- Topic throughput ---
    results = query(prom_url, f'kafka_server_BrokerTopicMetrics_OneMinuteRate{{ClusterName="{cluster}",name="MessagesInPerSec",topic!=""}}')
    print(f"\n{SEP}")
    print("TOPIC THROUGHPUT (messages in/sec, 1min avg)")
    print(SEP)
    agg = {}
    for r in results:
        topic = r["metric"].get("topic","")
        if topic.startswith("__"):
            continue
        agg[topic] = agg.get(topic, 0) + float(r["value"][1])
    print(f"  {'Topic':<40s} {'Msg/s (all brokers)':>20s}")
    print("  " + "-" * 63)
    for topic, rate in sorted(agg.items(), key=lambda x: -x[1]):
        print(f"  {topic:<40s} {rate:>20.2f}")

    # --- Connection count trend ---
    results = query_range(
        prom_url,
        f'sum by (listener) (kafka_server_socket_server_metrics_connection_count{{ClusterName="{cluster}"}})',
        start_1h, end_ts, "60s"
    )
    print(f"\n{SEP}")
    print("CONNECTION COUNT TREND (last 1h, per listener)")
    print(SEP)
    for r in results:
        listener = r["metric"].get("listener","total")
        vals = [float(v[1]) for v in r["values"]]
        if vals:
            print(f"  {listener:<15s}  min={min(vals):.0f}  max={max(vals):.0f}  current={vals[-1]:.0f}")

    print(f"\n{SEP}")


def main():
    parser = argparse.ArgumentParser(description="MSK connection report from Prometheus/JMX metrics")
    parser.add_argument("cluster", help="MSK cluster name (as seen in ClusterName label)")
    parser.add_argument("--prometheus", default="http://localhost:9090", help="Prometheus URL (default: http://localhost:9090)")
    args = parser.parse_args()
    report(args.prometheus, args.cluster)


if __name__ == "__main__":
    main()
