#!/usr/bin/env bash
# Tail the app log group in CloudWatch.   (make logs; SINCE=2h make logs)
set -euo pipefail
STACK=${STACK_NAME:-nadisaathi}
export AWS_REGION=${AWS_REGION:-us-east-1}
export AWS_DEFAULT_REGION=$AWS_REGION
group=$(aws cloudformation describe-stacks --stack-name "$STACK" \
  --query "Stacks[0].Outputs[?OutputKey=='LogGroupName'].OutputValue" --output text)
exec aws logs tail "$group" --since "${SINCE:-30m}" ${FOLLOW:+--follow} --format short
