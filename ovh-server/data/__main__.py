import json

import pulumi
import pulumi_command as command
import pulumi_ovh as ovh

from data.data_stack_output import S3UserOutputData, DataStackOutput
from lib.stack_output_util import stack_data_name

env = pulumi.get_stack()
config = pulumi.Config()
project_id = config.get("project_id")

bucket_names = [
    f"s-dossierfacile-{env}-raw-file",
    f"s-dossierfacile-{env}-raw-minified",
    f"s-dossierfacile-{env}-watermark-doc",
    f"s-dossierfacile-{env}-full-pdf",
    f"s-dossierfacile-{env}-filigrane"
]

buckets = {}
for name in bucket_names:
    buckets[name] = ovh.cloudproject.Storage(
        name,
        service_name=project_id,
        region_name="EU-WEST-PAR",
        name=name,
        encryption=ovh.cloudproject.StorageEncryptionArgs(sse_algorithm="AES256"),
    )

user_names = [
    f"u_dossierfacile_{env}_ApiTenant",
    f"u_dossierfacile_{env}_PdfGenerator",
    f"u_dossierfacile_{env}_ProcessFile",
    f"u_dossierfacile_{env}_BO",
    f"u_dossierfacile_{env}_TaskScheduler",
    f"u_dossierfacile_{env}_FileAnalysis",
    f"u_dossierfacile_{env}_Filigrane"
]

users = {}
creds = {}

for name in user_names:
    users[name] = ovh.cloudproject.User(
        name,
        service_name=project_id,
        description=f"User {name}",
        role_names=["objectstore_operator"],
    )

    creds[name] = ovh.cloudproject.S3Credential(
        f"c{name}",
        service_name=project_id,
        user_id=users[name].id
    )

permissions = {
    f"u_dossierfacile_{env}_ApiTenant": {
        f"s-dossierfacile-{env}-raw-file": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"],
        f"s-dossierfacile-{env}-raw-minified": ["s3:GetObject", "s3:ListBucket"],
        f"s-dossierfacile-{env}-watermark-doc": ["s3:GetObject", "s3:ListBucket"],
        f"s-dossierfacile-{env}-full-pdf": ["s3:GetObject", "s3:ListBucket"]
    },
    f"u_dossierfacile_{env}_PdfGenerator": {
        f"s-dossierfacile-{env}-raw-file": ["s3:GetObject", "s3:ListBucket"],
        f"s-dossierfacile-{env}-watermark-doc": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"],
        f"s-dossierfacile-{env}-full-pdf": ["s3:PutObject", "s3:ListBucket"],
        f"s-dossierfacile-{env}-filigrane": ["s3:GetObject", "s3:PutObject", "s3:ListBucket"]
    },
    f"u_dossierfacile_{env}_ProcessFile": {
        f"s-dossierfacile-{env}-raw-file": ["s3:GetObject", "s3:ListBucket"],
        f"s-dossierfacile-{env}-raw-minified": ["s3:PutObject", "s3:ListBucket"]
    },
    f"u_dossierfacile_{env}_BO": {
        f"s-dossierfacile-{env}-raw-file": ["s3:GetObject", "s3:ListBucket"],
        f"s-dossierfacile-{env}-watermark-doc": ["s3:GetObject", "s3:ListBucket"]
    },
    f"u_dossierfacile_{env}_TaskScheduler": {
        f"s-dossierfacile-{env}-raw-file": ["s3:DeleteObject", "s3:ListBucket"],
        f"s-dossierfacile-{env}-raw-minified": ["s3:DeleteObject", "s3:ListBucket"],
        f"s-dossierfacile-{env}-watermark-doc": ["s3:DeleteObject", "s3:ListBucket"],
        f"s-dossierfacile-{env}-full-pdf": ["s3:DeleteObject", "s3:ListBucket"],
        f"s-dossierfacile-{env}-filigrane": ["s3:DeleteObject", "s3:ListBucket"]
    },
    f"u_dossierfacile_{env}_FileAnalysis": {
        f"s-dossierfacile-{env}-raw-file": ["s3:GetObject", "s3:ListBucket"],
    },
    f"u_dossierfacile_{env}_Filigrane": {
        f"s-dossierfacile-{env}-filigrane": ["s3:PutObject", "s3:ListBucket", "s3:GetLifecycleConfiguration",
                                             "s3:PutLifecycleConfiguration", "s3:GetObject"]
    }
}


def build_policy(bucket_user: str, rules: dict) -> str:
    statements = []
    for bucket_name, actions in rules.items():
        statements.append({
            "Sid": f"{bucket_user}_{bucket_name}",
            "Effect": "Allow",
            "Action": actions,
            "Resource": [
                f"arn:aws:s3:::{bucket_name}",
                f"arn:aws:s3:::{bucket_name}/*"
            ]
        })
    return json.dumps({
        "Version": "2012-10-17",
        "Statement": statements
    })


for user, rule in permissions.items():
    policy_json = build_policy(user, rule)

    ovh.cloudproject.S3Policy(
        f"p{user}",
        service_name=project_id,
        user_id=users[user].id,
        policy=policy_json
    )

# This is not possible for the moment with OVH terraform provider or pulumi provider to set lifecycle configuration
# directly on the bucket, so we use a command to apply the lifecycle configuration.
# The lifecycle configuration is stored in a file named filigrane_lifecycle.json in the same directory.
lifecycle_bucket_name = f"s-dossierfacile-{env}-filigrane"
lifecycle_endpoint_url = "https://s3.eu-west-par.io.cloud.ovh.net"

cmd = pulumi.Output.all(
    creds[f'u_dossierfacile_{env}_Filigrane'].access_key_id,
    creds[f'u_dossierfacile_{env}_Filigrane'].secret_access_key
).apply(lambda keys:
    f"AWS_ACCESS_KEY_ID={keys[0]} "
    f"AWS_SECRET_ACCESS_KEY={keys[1]} "
    f"aws s3api put-bucket-lifecycle-configuration "
    f"--bucket {lifecycle_bucket_name} "
    f"--lifecycle-configuration file://filigrane_lifecycle.json "
    f"--endpoint-url {lifecycle_endpoint_url} "
    f"--region eu-west-par"
)

# Commande Pulumi qui applique la policy
apply_lifecycle = command.local.Command(
    f"clp{lifecycle_bucket_name}",
    create=cmd
)

buckets_names_output: list[pulumi.Output[str]] = list()
for bucket in buckets:
    buckets_names_output.append(buckets[bucket].name)

s3_users: list[S3UserOutputData] = list()
for user in creds:
    s3_users.append(S3UserOutputData(user, creds[user].access_key_id, creds[user].secret_access_key))

pulumi.export(stack_data_name, DataStackOutput(buckets_names_output, s3_users))
