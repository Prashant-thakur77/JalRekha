# Deploying NadiSaathi to AWS

One command builds the PWA, bundles the working tree, creates or updates a single
CloudFormation stack and rolls the code out to one Graviton (arm64) EC2 instance
behind CloudFront HTTPS.

```
make deploy     # create or update, then verify through CloudFront
make status     # outputs, instance, alarms, endpoint latency
make logs       # recent app logs (SINCE=2h, FOLLOW=1)
make destroy    # empty the bucket and delete the stack (YES=1 skips the prompt)
```

## Architecture

```
viewer --HTTPS--> CloudFront --HTTP :8000--> EC2 c8g.xlarge (Ubuntu 24.04 arm64)
                  (no caching,               uvicorn jalrekha.main:app
                   all methods,              serves /api/* and the built PWA at /
                   compression)              |- S3 bucket   (cap/ files, deploy/ bundle, bench/ results; 30-day expiry rule on frames/, traces/ prefixes, unused today)
                                             |- SNS topic   (operator notifications + alarms)
                                             |- Bedrock / Polly / SSM / CloudWatch
EventBridge (5 min) -> keep-warm Lambda -> GET <PublicUrl>/api/health -> NadiSaathi/HealthOk

While the account is not CloudFront-verified, an API Gateway HTTP API takes the place of
CloudFront: viewer -HTTPS-> API Gateway -> VPC link -> instance:8000 (private).
```

| Piece | Where |
| --- | --- |
| Stack template | `infra/nadisaathi.yaml` |
| Instance provisioner (first boot and every update) | `infra/userdata.sh` |
| Deploy / destroy / status / logs | `scripts/deploy/*.sh`, wrapped by the root `Makefile` |

The security group opens port 8000 only to the CloudFront origin-facing managed prefix
list (`pl-3b927c52` in us-east-1) and, when API Gateway is enabled, to the VPC link's
security group. There is no SSH; use Session Manager:
`aws ssm start-session --target <InstanceId>`.

The origin is the public DNS name of an Elastic IP, so stop/start, auto-recovery or a
replaced instance never changes the CloudFront origin.

## Public endpoint: CloudFront or API Gateway

Two HTTPS front doors are available. Each one has its own switch, and you can run both:

| Parameter (env var) | Default | What it creates |
| --- | --- | --- |
| `EnableCloudFront` (`ENABLE_CLOUDFRONT`) | `true` | CloudFront distribution to `http://<EIP DNS>:8000`, with no caching and all methods |
| `EnableApiGateway` (`ENABLE_APIGW`) | `false` | API Gateway HTTP API with a `$default` route to a VPC link, then Cloud Map, then the instance's private IP on port 8000 |

The stack output `PublicUrl` is the CloudFront URL when CloudFront is on, otherwise the
API Gateway URL. The keep-warm probe and `deploy.sh` both use `PublicUrl`.

**This account (<account-id>) cannot create CloudFront resources yet.** CloudFormation
returned: *"Your account must be verified before you can add new CloudFront
resources"*. Until AWS Support verifies the account, deploy with API Gateway:

```
ENABLE_CLOUDFRONT=false ENABLE_APIGW=true make deploy    # first time only; later runs keep these
```

After verification, add CloudFront and keep the API Gateway URL working, since it may
already have been shared:

```
ENABLE_CLOUDFRONT=true make deploy
```

API Gateway HTTP API limits: 30 s integration timeout, 10 MB request payload, and no
response compression. The integration is private: the instance's port 8000 is not open
to the internet.

## Prerequisites

- AWS CLI v2 with credentials for the target account. The default region is us-east-1;
  override it with `AWS_REGION`, but the prefix-list mapping in the template covers only
  us-east-1.
- Node 20+ and npm (to build the PWA), plus bash, rsync, curl, tar and python3.
- IAM rights to create CloudFormation, EC2, IAM roles, S3, SNS, CloudFront, Lambda,
  EventBridge, CloudWatch, Budgets and SSM parameters.
- At least 4 free on-demand standard vCPUs (c8g.xlarge).

## What `make deploy` does

1. Builds the PWA with `VITE_API_BASE=/api` in a private copy of `frontend/` under
   `~/.cache/nadisaathi/frontend-build`. `npm ci --legacy-peer-deps` runs only when
   `package.json` or `package-lock.json` changed. Your own `frontend/node_modules` and
   any running dev server are left alone. The build runs on every deploy.
   - If the build fails, the deploy goes on with the last good build
     (`~/.cache/nadisaathi/web-dist`). If there is no previous build, it ships API-only.
     Either way the script prints `WARN` and records the reason in `web/BUILD_STATUS`
     inside the bundle.
2. Bundles the working tree into `bundle.tar.gz` (about 45 MB), leaving out `.git`, `node_modules`,
   `.venv`, `android/`, `demo-artifacts/`, the `frontend/` sources (the built PWA ships
   as `web/dist`), local DBs and models, the planning notes and
   anything that looks like a secret (`.env*`, `*.pem`, `*.key`, ...). It keeps
   `datasets/usgs_hivis_stage/images` while that folder stays under 40 MB.
3. Creates SSM SecureString `/nadisaathi/operator_pin` with a random 6-digit value, but
   only if it does not exist yet.
4. Runs `aws cloudformation deploy` for stack `nadisaathi`. On first create it picks a
   default-VPC subnet in an AZ that offers the instance type.
5. Uploads the bundle to `s3://<bucket>/deploy/bundle.tar.gz`. The previous bundle is
   kept as `bundle.prev.tar.gz`.
6. On an update, runs `/usr/local/bin/nadisaathi-deploy` on the instance through SSM Run
   Command. That script pulls the bundle, `uv sync --frozen`, rewrites
   `/etc/nadisaathi.env`, fetches the OpenCV ONNX models
   (`python -m jalrekha.vision.models`: YuNet face and plate, ALIKED, LightGlue; about
   55 MB, SHA-1 checked, into `/var/lib/nadisaathi/models/opencv`) and restarts
   `nadisaathi.service`. On first create, the
   instance's UserData waits for the bundle and runs the same script.
7. Checks `<PublicUrl>/api/health`, `/api/sites` and `/` and prints the URL and the
   timings.

Optional variables: `INSTANCE_TYPE`, `USE_COOL_AMI=true|false`, `ALERT_EMAIL` (SNS
e-mail subscription), `BUDGET_EMAIL` (80% budget alert), `BUDGET_LIMIT_USD`
(default 60), `SKIP_WEB=1` (API-only), `STACK_NAME`. Variables you leave unset keep the
stack's current values.

```
ALERT_EMAIL=ops@example.org BUDGET_EMAIL=ops@example.org make deploy
```

Timing, measured 2026-10-25: the first create with API Gateway took 5 min 4 s, of which
the stack took 4 min and the instance install 45 s. CloudFront adds roughly 5-10 min.
A code-only redeploy (`make deploy` on an existing stack) took 50-65 s.

## On the instance

| Path | Purpose |
| --- | --- |
| `/opt/nadisaathi/app` | code from the bundle (replaced on every deploy) |
| `/opt/nadisaathi/venv` | Python env synced from `backend/uv.lock` |
| `/opt/nadisaathi/app/web/dist` | built PWA (`JALREKHA_WEB_DIST`) |
| `/var/lib/nadisaathi` | data dir: SQLite DBs, uploads, model caches |
| `/etc/nadisaathi.env` | service environment (mode 0640) |
| `/etc/nadisaathi/stack.env` | bucket, topic, log group and region, written by UserData |

The service writes to journald under the identifier `nadisaathi`. rsyslog copies those
lines to `/var/log/nadisaathi/app.log`, and the CloudWatch agent ships that file to the
log group `/nadisaathi/app` (stream `<instance-id>/app`; 14-day retention). Boot and
provisioning output goes to the streams `<instance-id>/bootstrap` and
`<instance-id>/cloud-init`.

Environment set for the backend:

```
JALREKHA_DATA_DIR=/var/lib/nadisaathi    JALREKHA_WEB_DIST=/opt/nadisaathi/app/web/dist
JALREKHA_LLM_ENABLED=0                   JALREKHA_MULTIMODAL_ENABLED=0   (no Ollama in the cloud)
JALREKHA_NODE_PROVIDER=ollama            JALREKHA_ASR_ENABLED=1 if faster-whisper imports, else 0
JALREKHA_VISION_MODE=inprocess           JALREKHA_OPERATOR_PIN=<from SSM /nadisaathi/operator_pin>
NADISAATHI_S3_BUCKET  NADISAATHI_SNS_TOPIC_ARN  AWS_REGION=us-east-1
NADISAATHI_BEDROCK_MODEL=us.amazon.nova-lite-v1:0   NADISAATHI_TTS_ENABLED=1
```

The instance also gets `ffmpeg` and `espeak-ng`, the latter as the offline TTS
fallback.

## IAM (least privilege)

The instance role has `AmazonSSMManagedInstanceCore` plus one inline policy:

- S3: list the stack bucket; get, put and delete objects in it.
- Bedrock: `InvokeModel` and `InvokeModelWithResponseStream`, which also authorise
  `Converse` and `ConverseStream`. They cover `amazon.nova-*` and `anthropic.*`
  foundation models in any region, and the account's `us.amazon.nova-*`,
  `us.anthropic.*` and `global.anthropic.*` inference profiles. Cross-region profiles
  route to other US regions, which is why the region is a wildcard.
- `polly:SynthesizeSpeech`.
- `sns:Publish` on the stack topic, plus `sns:Publish` with
  `NotResource: arn:aws:sns:*:*:*` for direct SMS. An SMS publish to a phone number has
  no resource ARN and IAM evaluates it against `*`. `NotResource` excludes every topic
  ARN, so that statement allows SMS only and grants nothing on other topics.
- `ssm:GetParameter*` on `parameter/nadisaathi/*`.
- `cloudwatch:PutMetricData` only where `cloudwatch:namespace` is `NadiSaathi` (app
  metrics) or `CWAgent` (host memory and disk).
- `logs:*` on the stack log group only (CloudWatch agent and Run Command output).

The CloudWatch agent's needs are folded into this scoped policy rather than attaching
the broad `CloudWatchAgentServerPolicy`. The keep-warm Lambda can only write its own log
group and put `NadiSaathi` metrics.

## Observability and alarms

- Dashboard `nadisaathi`: health probe and latency, CPU and memory, network, and the app
  metrics `FramesMeasured`, `StageMs`, `AgentCycles`, `ApprovalsPending` and
  `Escalations`. Search expressions pick up these metrics under any dimensions.
- `nadisaathi-system-status-recover`: EC2 system check fails, auto-recover and notify.
- `nadisaathi-instance-status-reboot`: instance check fails, reboot and notify.
- `nadisaathi-health`: `HealthOk < 1` for 3 consecutive 5-minute probes (missing data
  counts as failing), notify the SNS topic.
- Budget `nadisaathi-monthly`: a monthly cost budget with an 80% e-mail alert when
  `BUDGET_EMAIL` is set.

## Cost estimate

Price looked up with the AWS Price List API (`aws pricing get-products --region
us-east-1 --service-code AmazonEC2`) on **2026-10-25**. Price list publication date
2026-10-23, effective 2026-10-01:

- **c8g.xlarge, Linux on-demand, us-east-1: USD 0.15952 per hour** (4 vCPU, 8 GiB)
- gp3 storage, us-east-1: USD 0.08 per GB-month

| Item | Per month (730 h) | 27 Oct - 9 Nov (14 days) |
| --- | --- | --- |
| c8g.xlarge on-demand | 116.45 | 53.60 |
| 30 GB gp3 root volume | 2.40 | 1.10 |
| Public IPv4 / Elastic IP (USD 0.005/h) | 3.65 | 1.70 |
| CloudFront, Lambda, EventBridge, SNS (free-tier scale) | ~0 | ~0 |
| API Gateway HTTP API (USD 1.00 per million requests) + Cloud Map instance (USD 0.10) | ~0.1 | ~0.1 |
| CloudWatch: 1 dashboard, 3 alarms, ~10 custom metrics, logs | ~4 | ~2 |
| **Total (estimate)** | **~127** | **~58** |

These are estimates. Bedrock, Polly and SMS are billed per use and are not included.
The default 60 USD budget covers the two-week judging window but **not** a full month
of the instance running. Run `make destroy` after judging, or deploy with
`INSTANCE_TYPE=c8g.large` (2 vCPU, 4 GiB) to roughly halve the compute cost.

## Switching to the COOL Graviton4 AMI

The template boots Ubuntu 24.04 arm64 from the Canonical SSM public parameter by
default. To use the COOL Graviton4 v2 Marketplace AMI (`ami-01db31139bc5615d8`):

1. In the AWS Marketplace console, accept the product's subscription for this account.
2. Run `USE_COOL_AMI=true make deploy`.

Changing the image replaces the instance. The Elastic IP moves to the new instance, so
the CloudFront URL stays the same, and UserData provisions the new instance from the
latest bundle. The data dir on the old instance is not carried over; the seed data is
recreated. The provisioner assumes an apt-based (Ubuntu or Debian) image with root
device `/dev/sda1`. The COOL AMI's root device is `/dev/sda1`. To switch back, run
`USE_COOL_AMI=false make deploy`.

## Rotating the operator PIN

```
NEW=$(python3 -c 'import secrets; print(f"{secrets.randbelow(10**6):06d}")')
aws ssm put-parameter --name /nadisaathi/operator_pin --type SecureString --value "$NEW" --overwrite
make deploy        # or only roll the instance:
aws ssm send-command --document-name AWS-RunShellScript \
  --instance-ids "$(aws cloudformation describe-stacks --stack-name nadisaathi \
     --query "Stacks[0].Outputs[?OutputKey=='InstanceId'].OutputValue" --output text)" \
  --parameters 'commands=["/usr/local/bin/nadisaathi-deploy"]'
```

To read the current PIN, run
`aws ssm get-parameter --name /nadisaathi/operator_pin --with-decryption --query Parameter.Value --output text`.

## Destroy

`make destroy` empties the bucket, deletes the stack and waits; CloudFront takes
5-15 minutes. It keeps the PIN parameter. Use `scripts/deploy/destroy.sh -y --purge-pin`
to remove that as well.

## Troubleshooting

- `make logs`, or `SINCE=2h make logs`, for the app, bootstrap and Run Command output.
- On the box: `aws ssm start-session --target <id>`, then
  `sudo journalctl -u nadisaathi -f` and `sudo tail -f /var/log/nadisaathi-bootstrap.log`.
- Bedrock returns `ThrottlingException: Too many tokens per day` for Nova Lite. The
  account's Nova Lite quotas are 0 (Service Quotas, "Model invocation max tokens per day
  for Amazon Nova Lite"). IAM allows the call; raise the quota in Service Quotas or
  through Support. Anthropic models first need the Bedrock use-case form.
- A 502, 503 or 504 from the public URL usually means the service is restarting or the first boot
  is still installing. `make status` shows the instance and alarm state.

## Camera key and approval escalation

- Cameras and edge boxes post bursts to `POST /api/agent/cycle` with the header `X-Camera-Key`. The key is the SSM SecureString `/nadisaathi/camera_key` (create or rotate it with `aws ssm put-parameter --name /nadisaathi/camera_key --type SecureString --value <key> --overwrite`, then `make deploy`). Without a key configured (local development) the route is open.
- Five wrong operator PINs from one client within ten minutes return HTTP 429 for ten minutes.
- When the agent drafts a public alert, the backend starts the Step Functions state machine `<stack>-approval-escalation`: it waits 15 minutes, asks the API whether the approval is still pending and, if so, publishes a reminder to the operator SNS topic, up to three times. Subscribe an e-mail with `ALERT_EMAIL=you@example.org make deploy` to receive them.
