#!/usr/bin/env python3
import aws_cdk as cdk

from lambda_packaging import stage_all_lambda_packages
from stacks.compute_stack import SentinelComputeStack
from stacks.messaging_stack import SentinelMessagingStack
from stacks.storage_stack import SentinelStorageStack

# Stages each service's own code + a fresh copy of shared/ into
# infrastructure/.build/{service}/ BEFORE any stack is defined, so
# Code.from_asset() in compute_stack.py always has a clean,
# self-contained folder to bundle. See lambda_packaging.py.
stage_all_lambda_packages()

app = cdk.App()

# Environment-agnostic for now — this deploys to whatever account and
# region your AWS CLI is currently configured for. TAD Section 13.2
# calls for three separate accounts (sentinel-dev / sentinel-staging /
# sentinel-prod). Once those accounts actually exist, this becomes:
#
#   SentinelStorageStack(
#       app, "SentinelStorage-Dev",
#       env=cdk.Environment(account="111111111111", region="us-east-1"),
#   )
#
# For now, one account stands in for dev.
storage = SentinelStorageStack(app, "SentinelStorage-Dev")
messaging = SentinelMessagingStack(app, "SentinelMessaging-Dev")

compute = SentinelComputeStack(
    app,
    "SentinelCompute-Dev",
    runs_table=storage.runs_table,
    artefacts_bucket=storage.artefacts_bucket,
    stage2_queue=messaging.stage2_queue,
    stage3_queue=messaging.stage3_queue,
    dispatcher_dlq=messaging.dispatcher_dlq,
)
# CDK infers stack deployment order automatically from these
# references (storage/messaging must exist before compute can
# reference their resources) — no explicit add_dependency() needed.

app.synth()