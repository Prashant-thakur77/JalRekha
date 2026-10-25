#!/usr/bin/env bash
# Show stack, instance, alarm and endpoint status.   (make status)
set -uo pipefail
STACK=${STACK_NAME:-nadisaathi}
export AWS_REGION=${AWS_REGION:-us-east-1}
export AWS_DEFAULT_REGION=$AWS_REGION

st=$(aws cloudformation describe-stacks --stack-name "$STACK" --query 'Stacks[0].StackStatus' --output text 2>/dev/null) \
  || { echo "stack $STACK: not deployed"; exit 0; }
out() { aws cloudformation describe-stacks --stack-name "$STACK" --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text; }
url=$(out PublicUrl); iid=$(out InstanceId)

echo "stack      $STACK: $st"
aws cloudformation describe-stacks --stack-name "$STACK" --query 'Stacks[0].Outputs[].[OutputKey,OutputValue]' --output text | sed 's/^/  /'
echo "instance   $(aws ec2 describe-instances --instance-ids "$iid" --query 'Reservations[0].Instances[0].[InstanceType,State.Name,ImageId,Placement.AvailabilityZone]' --output text)"
echo "ssm agent  $(aws ssm describe-instance-information --filters Key=InstanceIds,Values="$iid" --query 'InstanceInformationList[0].PingStatus' --output text)"
echo "alarms"
aws cloudwatch describe-alarms --alarm-name-prefix "$STACK-" --query 'MetricAlarms[].[AlarmName,StateValue]' --output text | sed 's/^/  /'
echo "endpoint"
for p in /api/health /api/sites /; do
  curl -s -o /dev/null -m 15 -w "  %{http_code}  %{time_total}s  $p\n" "$url$p"
done
echo "health     $(curl -s -m 10 "$url/api/health")"
