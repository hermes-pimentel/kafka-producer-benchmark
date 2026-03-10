#!/bin/bash
# Generate test connections to MSK with different client IDs (IAM auth).
#
# Usage: ./generate-connections.sh <bootstrap-server> <topic> [count]
# Example: ./generate-connections.sh b-1.mycluster.kafka.us-east-1.amazonaws.com:9098 my-topic 20
#
# Prerequisites:
#   - Kafka CLI tools (set KAFKA_HOME or have them in PATH)
#   - aws-msk-iam-auth jar in CLASSPATH (for IAM auth)

BOOTSTRAP="${1:?Usage: $0 <bootstrap-server> <topic> [count]}"
TOPIC="${2:?Usage: $0 <bootstrap-server> <topic> [count]}"
COUNT="${3:-20}"

if [ -n "$KAFKA_HOME" ]; then
  KAFKA="$KAFKA_HOME/bin"
elif command -v kafka-console-producer.sh &>/dev/null; then
  KAFKA="$(dirname $(command -v kafka-console-producer.sh))"
else
  echo "Error: Kafka CLI tools not found. Set KAFKA_HOME or add them to PATH." >&2
  exit 1
fi

APPS=("order-service" "payment-processor" "inventory-manager" "notification-service" "analytics-pipeline" "fraud-detector")

for i in $(seq 1 "$COUNT"); do
  APP=${APPS[$((RANDOM % ${#APPS[@]}))]}
  CLIENT_ID="${APP}-${i}"

  TMPFILE=$(mktemp)
  cat > "$TMPFILE" <<EOF
security.protocol=SASL_SSL
sasl.mechanism=AWS_MSK_IAM
sasl.jaas.config=software.amazon.msk.auth.iam.IAMLoginModule required;
sasl.client.callback.handler.class=software.amazon.msk.auth.iam.IAMClientCallbackHandler
client.id=${CLIENT_ID}
EOF

  echo "[$(date +%H:%M:%S)] Producing as: $CLIENT_ID"
  echo "hello from ${CLIENT_ID}" | timeout 5 $KAFKA/kafka-console-producer.sh \
    --bootstrap-server "$BOOTSTRAP" \
    --topic "$TOPIC" \
    --producer.config "$TMPFILE" \
    2>/dev/null
  rm -f "$TMPFILE"
  sleep 1
done

echo "Done. $COUNT IAM connections generated."
