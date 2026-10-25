#!/usr/bin/env bash
# Tear down the NadiSaathi stack: empty the bucket, delete the stack, wait.
#   scripts/deploy/destroy.sh [-y] [--purge-pin]      (or: make destroy)
set -euo pipefail
STACK=${STACK_NAME:-nadisaathi}
export AWS_REGION=${AWS_REGION:-us-east-1}
export AWS_DEFAULT_REGION=$AWS_REGION
YES=0; PURGE_PIN=0
for a in "$@"; do
  case "$a" in -y|--yes) YES=1 ;; --purge-pin) PURGE_PIN=1 ;; *) echo "unknown arg $a" >&2; exit 2 ;; esac
done

if ! aws cloudformation describe-stacks --stack-name "$STACK" >/dev/null 2>&1; then
  echo "stack $STACK does not exist"
else
  if [ "$YES" != 1 ]; then
    read -r -p "Delete stack '$STACK' in $AWS_REGION (instance, CloudFront, bucket contents)? [y/N] " ans
    [[ "$ans" =~ ^[Yy]$ ]] || { echo "aborted"; exit 1; }
  fi
  bucket=$(aws cloudformation describe-stacks --stack-name "$STACK" \
    --query "Stacks[0].Outputs[?OutputKey=='BucketName'].OutputValue" --output text 2>/dev/null || true)
  if [ -n "$bucket" ] && [ "$bucket" != None ] && aws s3api head-bucket --bucket "$bucket" 2>/dev/null; then
    echo "emptying s3://$bucket"
    aws s3 rm "s3://$bucket" --recursive --only-show-errors
  fi
  echo "deleting stack $STACK (CloudFront teardown takes 5-15 min)"
  aws cloudformation delete-stack --stack-name "$STACK"
  aws cloudformation wait stack-delete-complete --stack-name "$STACK"
  echo "stack deleted"
fi

if [ "$PURGE_PIN" = 1 ]; then
  aws ssm delete-parameter --name /nadisaathi/operator_pin 2>/dev/null && echo "deleted /nadisaathi/operator_pin" || true
else
  echo "kept SSM parameter /nadisaathi/operator_pin (use --purge-pin to delete it)"
fi
