#!/usr/bin/env python3
"""Enable or disable VPC Flow Logs on MSK broker ENIs.

Creates per-ENI flow logs to CloudWatch, capturing only broker traffic.

Usage:
  python3 setup-flow-logs.py --cluster <name> --action enable [--region <r>] [--log-group <lg>] [--role-arn <arn>]
  python3 setup-flow-logs.py --cluster <name> --action disable [--region <r>] [--log-group <lg>]

Enable:
  1. Creates CloudWatch log group (if missing) with 7-day retention
  2. Creates IAM role VPCFlowLogsRole (if missing)
  3. Creates flow logs on each broker ENI

Disable:
  1. Deletes flow logs from broker ENIs
  2. Optionally deletes the log group (--delete-log-group)
"""
import argparse
import json
import sys
import time

import boto3
from botocore.exceptions import ClientError

FLOW_LOG_FORMAT = "${version} ${account-id} ${interface-id} ${srcaddr} ${dstaddr} ${srcport} ${dstport} ${protocol} ${packets} ${bytes} ${start} ${end} ${action} ${log-status} ${tcp-flags}"
ROLE_NAME = "VPCFlowLogsRole"


def get_broker_enis(ec2, cluster_arn_fragment):
    enis = ec2.describe_network_interfaces(
        Filters=[{"Name": "description", "Values": [f"*Amazon MSK*{cluster_arn_fragment}*"]}]
    )["NetworkInterfaces"]
    return {e["NetworkInterfaceId"]: e["PrivateIpAddress"] for e in enis}


def ensure_log_group(logs, log_group):
    try:
        logs.create_log_group(logGroupName=log_group)
        logs.put_retention_policy(logGroupName=log_group, retentionInDays=7)
        print(f"  Created log group: {log_group} (7-day retention)")
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceAlreadyExistsException":
            print(f"  Log group exists: {log_group}")
        else:
            raise


def ensure_role(iam):
    trust = json.dumps({"Version": "2012-10-17", "Statement": [
        {"Effect": "Allow", "Principal": {"Service": "vpc-flow-logs.amazonaws.com"}, "Action": "sts:AssumeRole"}
    ]})
    try:
        resp = iam.create_role(RoleName=ROLE_NAME, AssumeRolePolicyDocument=trust)
        iam.put_role_policy(RoleName=ROLE_NAME, PolicyName="VPCFlowLogsToCloudWatch",
            PolicyDocument=json.dumps({"Version": "2012-10-17", "Statement": [
                {"Effect": "Allow", "Resource": "*",
                 "Action": ["logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogGroups", "logs:DescribeLogStreams"]}
            ]}))
        arn = resp["Role"]["Arn"]
        print(f"  Created IAM role: {arn}")
        print("  Waiting 10s for IAM propagation...")
        time.sleep(10)
        return arn
    except ClientError as e:
        if e.response["Error"]["Code"] == "EntityAlreadyExists":
            arn = iam.get_role(RoleName=ROLE_NAME)["Role"]["Arn"]
            print(f"  IAM role exists: {arn}")
            return arn
        raise


def enable(cluster_name, region, log_group, role_arn):
    ec2 = boto3.client("ec2", region_name=region)
    kafka = boto3.client("kafka", region_name=region)
    logs = boto3.client("logs", region_name=region)
    iam = boto3.client("iam")

    cluster = next((c for c in kafka.list_clusters_v2()["ClusterInfoList"] if c["ClusterName"] == cluster_name), None)
    if not cluster:
        print(f"Error: cluster '{cluster_name}' not found"); sys.exit(1)

    eni_map = get_broker_enis(ec2, cluster["ClusterArn"].split("/")[1])
    if not eni_map:
        print("Error: no broker ENIs found"); sys.exit(1)

    print(f"Cluster: {cluster_name} ({len(eni_map)} ENIs)")
    ensure_log_group(logs, log_group)
    if not role_arn:
        role_arn = ensure_role(iam)

    # Check existing flow logs on these ENIs
    existing = ec2.describe_flow_logs(Filters=[
        {"Name": "resource-id", "Values": list(eni_map.keys())}
    ])["FlowLogs"]
    existing_enis = {fl["ResourceId"] for fl in existing}

    created = 0
    for eni, ip in sorted(eni_map.items(), key=lambda x: x[1]):
        if eni in existing_enis:
            print(f"  Skip {eni} ({ip}) — flow log already exists")
            continue
        resp = ec2.create_flow_logs(
            ResourceType="NetworkInterface", ResourceIds=[eni], TrafficType="ALL",
            LogDestinationType="cloud-watch-logs", LogGroupName=log_group,
            DeliverLogsPermissionArn=role_arn, MaxAggregationInterval=60,
            LogFormat=FLOW_LOG_FORMAT,
        )
        fl_id = resp["FlowLogIds"][0] if resp["FlowLogIds"] else "?"
        print(f"  Created {fl_id} on {eni} ({ip})")
        created += 1

    print(f"\nDone. {created} flow logs created, {len(existing_enis)} already existed.")
    print(f"Logs will appear in ~2-5 min at: {log_group}")


def disable(cluster_name, region, log_group, delete_log_group):
    ec2 = boto3.client("ec2", region_name=region)
    kafka = boto3.client("kafka", region_name=region)
    logs = boto3.client("logs", region_name=region)

    cluster = next((c for c in kafka.list_clusters_v2()["ClusterInfoList"] if c["ClusterName"] == cluster_name), None)
    if not cluster:
        print(f"Error: cluster '{cluster_name}' not found"); sys.exit(1)

    eni_map = get_broker_enis(ec2, cluster["ClusterArn"].split("/")[1])
    if not eni_map:
        print("No broker ENIs found"); return

    existing = ec2.describe_flow_logs(Filters=[
        {"Name": "resource-id", "Values": list(eni_map.keys())}
    ])["FlowLogs"]

    if not existing:
        print("No flow logs found on broker ENIs.")
        return

    fl_ids = [fl["FlowLogId"] for fl in existing]
    ec2.delete_flow_logs(FlowLogIds=fl_ids)
    print(f"Deleted {len(fl_ids)} flow logs from {len(eni_map)} broker ENIs")

    if delete_log_group:
        try:
            logs.delete_log_group(logGroupName=log_group)
            print(f"Deleted log group: {log_group}")
        except ClientError:
            print(f"Log group not found: {log_group}")


def main():
    p = argparse.ArgumentParser(description="Enable/disable VPC Flow Logs on MSK broker ENIs")
    p.add_argument("--cluster", required=True, help="MSK cluster name")
    p.add_argument("--action", required=True, choices=["enable", "disable"])
    p.add_argument("--region", default="us-east-1")
    p.add_argument("--log-group", default=None, help="CloudWatch log group (default: /aws/vpc-flow-logs/<cluster>)")
    p.add_argument("--role-arn", default=None, help="IAM role ARN for flow logs (auto-created if omitted)")
    p.add_argument("--delete-log-group", action="store_true", help="Also delete log group on disable")
    args = p.parse_args()

    lg = args.log_group or f"/aws/vpc-flow-logs/{args.cluster}"
    if args.action == "enable":
        enable(args.cluster, args.region, lg, args.role_arn)
    else:
        disable(args.cluster, args.region, lg, args.delete_log_group)


if __name__ == "__main__":
    main()
