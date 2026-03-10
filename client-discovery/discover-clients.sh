#!/bin/bash
# MSK Client Discovery - uses Kafka Admin API to discover active clients, topics, and connections.
# Shows real IPs (not masked like in CloudWatch/S3 logs).
#
# Usage: ./discover-clients.sh <bootstrap-server> <client-properties-file>
# Example: ./discover-clients.sh b-1.mycluster.kafka.us-east-1.amazonaws.com:9098 client.properties
#
# Prerequisites:
#   - Kafka CLI tools (set KAFKA_HOME or have them in PATH)
#   - aws-msk-iam-auth jar in CLASSPATH (for IAM auth)

set -e
BOOTSTRAP="${1:?Usage: $0 <bootstrap-server> <client.properties>}"
CONF="${2:?Usage: $0 <bootstrap-server> <client.properties>}"

if [ -n "$KAFKA_HOME" ]; then
  KAFKA="$KAFKA_HOME/bin"
elif command -v kafka-topics.sh &>/dev/null; then
  KAFKA="$(dirname $(command -v kafka-topics.sh))"
else
  echo "Error: Kafka CLI tools not found. Set KAFKA_HOME or add them to PATH." >&2
  exit 1
fi

SEP="================================================================================"

echo "$SEP"
echo "MSK CLIENT DISCOVERY"
echo "Bootstrap: $BOOTSTRAP"
echo "Time: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "$SEP"

echo ""
echo "$SEP"
echo "TOPICS"
echo "$SEP"
$KAFKA/kafka-topics.sh --bootstrap-server "$BOOTSTRAP" --command-config "$CONF" --list 2>/dev/null | grep -v "^__"

echo ""
echo "$SEP"
echo "TOPIC DETAILS (non-internal)"
echo "$SEP"
TOPICS=$($KAFKA/kafka-topics.sh --bootstrap-server "$BOOTSTRAP" --command-config "$CONF" --list 2>/dev/null | grep -v "^__")
for T in $TOPICS; do
  $KAFKA/kafka-topics.sh --bootstrap-server "$BOOTSTRAP" --command-config "$CONF" --describe --topic "$T" 2>/dev/null
done

echo ""
echo "$SEP"
echo "CONSUMER GROUPS"
echo "$SEP"
GROUPS=$($KAFKA/kafka-consumer-groups.sh --bootstrap-server "$BOOTSTRAP" --command-config "$CONF" --list 2>/dev/null)
echo "$GROUPS"

echo ""
echo "$SEP"
echo "ACTIVE CONSUMERS (real IPs, client IDs, assignments)"
echo "$SEP"
for G in $GROUPS; do
  MEMBERS=$($KAFKA/kafka-consumer-groups.sh --bootstrap-server "$BOOTSTRAP" --command-config "$CONF" --describe --group "$G" --members --verbose 2>/dev/null | grep -v "^$")
  if echo "$MEMBERS" | grep -q "/[0-9]"; then
    echo "$MEMBERS"
    echo ""
  fi
done

echo "$SEP"
echo "CONSUMER GROUP LAG"
echo "$SEP"
for G in $GROUPS; do
  $KAFKA/kafka-consumer-groups.sh --bootstrap-server "$BOOTSTRAP" --command-config "$CONF" --describe --group "$G" 2>/dev/null | grep -v "^$"
  echo ""
done

echo "$SEP"
echo "NOTE: Only consumers in active consumer groups are visible."
echo "Producers are not tracked by Kafka Admin API."
echo "$SEP"
