#!/usr/bin/env python3
import aws_cdk as cdk

from stacks.storage_stack import SentinelStorageStack

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
SentinelStorageStack(app, "SentinelStorage-Dev")

app.synth()