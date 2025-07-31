import json

import pulumi
import pulumi_command as command
import pulumi_ovh as ovh

from data.configuration import get_storage_raw_file_name, get_storage_raw_file_minified_name, \
    get_storage_watermark_doc_name, get_storage_full_pdf_name, get_storage_filigrane_name, get_user_api_tenant_name, \
    get_user_pdf_generator_name, get_user_process_file_name, get_user_bo_name, get_user_task_scheduler_name, \
    get_user_file_analysis_name, get_user_filigranefacile_name
from data.data_stack_output import S3UserOutputData, DataStackOutput
from lib.stack_output_util import stack_data_name

env = pulumi.get_stack()
config = pulumi.Config()
project_id = config.get("project_id")

print()

storage_names = [
    get_storage_raw_file_name(env),
    get_storage_raw_file_minified_name(env),
    get_storage_watermark_doc_name(env),
    get_storage_full_pdf_name(env),
    get_storage_filigrane_name(env)
]

storages = {}
for name in storage_names:
    storages[name] = ovh.cloudproject.Storage(
        name,
        service_name=project_id,
        region_name="EU-WEST-PAR",
        name=name,
        encryption=ovh.cloudproject.StorageEncryptionArgs(sse_algorithm="AES256"),
    )

user_names = [
    get_user_api_tenant_name(env),
    get_user_pdf_generator_name(env),
    get_user_process_file_name(env),
    get_user_bo_name(env),
    get_user_task_scheduler_name(env),
    get_user_file_analysis_name(env),
    get_user_filigranefacile_name(env)
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
    get_user_api_tenant_name(env): {
        get_storage_raw_file_name(env): ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"],
        get_storage_raw_file_minified_name(env): ["s3:GetObject", "s3:ListBucket"],
        get_storage_watermark_doc_name(env): ["s3:GetObject", "s3:ListBucket"],
        get_storage_full_pdf_name(env): ["s3:GetObject", "s3:ListBucket"]
    },
    get_user_pdf_generator_name(env): {
        get_storage_raw_file_name(env): ["s3:GetObject", "s3:ListBucket"],
        get_storage_watermark_doc_name(env): ["s3:PutObject", "s3:ListBucket"],
        get_storage_full_pdf_name(env): ["s3:PutObject", "s3:ListBucket"],
        get_storage_filigrane_name(env): ["s3:GetObject", "s3:PutObject", "s3:ListBucket"]
    },
    get_user_process_file_name(env): {
        get_storage_raw_file_name(env): ["s3:GetObject", "s3:ListBucket"],
        get_storage_raw_file_minified_name(env): ["s3:PutObject", "s3:ListBucket"]
    },
    get_user_bo_name(env): {
        get_storage_raw_file_name(env): ["s3:GetObject", "s3:ListBucket"],
        get_storage_watermark_doc_name(env): ["s3:GetObject", "s3:ListBucket"]
    },
    get_user_task_scheduler_name(env): {
        get_storage_raw_file_name(env): ["s3:DeleteObject", "s3:ListBucket"],
        get_storage_raw_file_minified_name(env): ["s3:DeleteObject", "s3:ListBucket"],
        get_storage_watermark_doc_name(env): ["s3:DeleteObject", "s3:ListBucket"],
        get_storage_full_pdf_name(env): ["s3:DeleteObject", "s3:ListBucket"],
        get_storage_filigrane_name(env): ["s3:DeleteObject", "s3:ListBucket"]
    },
    get_user_file_analysis_name(env): {
        get_storage_raw_file_name(env): ["s3:GetObject", "s3:ListBucket"],
    },
    get_user_filigranefacile_name(env): {
        get_storage_filigrane_name(env): ["s3:PutObject", "s3:ListBucket", "s3:GetLifecycleConfiguration",
                                             "s3:PutLifecycleConfiguration", "s3:GetObject"]
    }
}


def build_policy(bucket_user: str, rules: dict) -> str:
    statements = []
    for bucket_name, actions in rules.items():
        statements.append({
            "Sid": f"{bucket_user}-{bucket_name}",
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
lifecycle_endpoint_url = "https://s3.eu-west-par.io.cloud.ovh.net"

filigrane_creds = creds[get_user_filigranefacile_name(env)]

cmd = pulumi.Output.all(
    filigrane_creds.access_key_id,
    filigrane_creds.secret_access_key
).apply(lambda keys:
    f"AWS_ACCESS_KEY_ID={keys[0]} "
    f"AWS_SECRET_ACCESS_KEY={keys[1]} "
    f"aws s3api put-bucket-lifecycle-configuration "
    f"--bucket {get_storage_filigrane_name(env)} "
    f"--lifecycle-configuration file://filigrane_lifecycle.json "
    f"--endpoint-url {lifecycle_endpoint_url} "
    f"--region eu-west-par"
)

# Commande Pulumi qui applique la policy
apply_lifecycle = command.local.Command(
    f"clp{get_storage_filigrane_name(env)}",
    create=cmd
)

storage_name_outputs: list[pulumi.Output[str]] = list()
for storage in storages:
    storage_name_outputs.append(storages[storage].name)

s3_users: list[S3UserOutputData] = list()
for user in creds:
    s3_users.append(S3UserOutputData(user, creds[user].access_key_id, creds[user].secret_access_key))

pulumi.export(stack_data_name, DataStackOutput(storage_name_outputs, s3_users))
