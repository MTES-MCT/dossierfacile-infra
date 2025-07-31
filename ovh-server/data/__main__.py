import json

import pulumi
import pulumi_ovh as ovh

from data.data_stack_output import S3UserOutputData, DataStackOutput
from lib.stack_output_util import stack_data_name

env = pulumi.get_stack()
config = pulumi.Config()
project_id = config.get("project_id")

bucket_names = [
    f"s-dossierfacile-{env}-raw-file",
    # f"S_dossier_facile_{env}_raw_minified",
    # f"S_dossier_facile_{env}_watermark_doc",
    # f"S_dossier_facile_{env}_full_pdf",
    # f"S_dossier_facile_{env}_filigrane"
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
    f"u_dossier_facile_{env}_ApiTenant",
    # f"U_dossier_facile_{env}_PdfGenerator",
    # f"U_dossier_facile_{env}_ProcessFile",
    # f"U_dossier_facile_{env}_BO",
    # f"U_dossier_facile_{env}_Filigrane"
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
        f"C{name}",
        service_name=project_id,
        user_id=users[name].id
    )

permissions = {
    f"u_dossier_facile_{env}_ApiTenant": {
        f"s-dossierfacile-{env}-raw-file": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"],
        # f"S_dossier_facile_{env}_raw_minified": ["s3:GetObject", "s3:ListBucket"],
        # f"S_dossier_facile_{env}_watermark_doc": ["s3:GetObject", "s3:ListBucket"],
        # f"S_dossier_facile_{env}_full_pdf": ["s3:GetObject", "s3:ListBucket"]
    },
    # f"U_dossier_facile_{env}_PdfGenerator": {
    #     f"S_dossier_facile_{env}_raw_file": ["s3:GetObject", "s3:ListBucket"],
    #     f"S_dossier_facile_{env}_watermark_doc": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"],
    #     f"S_dossier_facile_{env}_full_pdf": ["s3:PutObject", "s3:ListBucket"]
    # },
    # f"U_dossier_facile_{env}_ProcessFile": {
    #     f"S_dossier_facile_{env}_raw_file": ["s3:GetObject", "s3:ListBucket"],
    #     f"S_dossier_facile_{env}_raw_minified": ["s3:PutObject", "s3:DeleteObject", "s3:ListBucket"]
    # },
    # f"U_dossier_facile_{env}_BO": {
    #     f"S_dossier_facile_{env}_raw_file": ["s3:GetObject", "s3:ListBucket"],
    #     f"S_dossier_facile_{env}_watermark_doc": ["s3:GetObject", "s3:ListBucket"]
    # },
    # f"U_dossier_facile_{env}_Filigrane": {
    #     f"S_dossier_facile_{env}_filigrane": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"]
    # }
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
    policy_json = pulumi.Output.all().apply(lambda _: build_policy(user, rule))

    ovh.cloudproject.S3Policy(
        f"P{user}",
        service_name=project_id,
        user_id=users[user].id,
        policy=policy_json
    )

buckets_names_output: list[pulumi.Output[str]] = list()
for bucket in buckets:
    buckets_names_output.append(buckets[bucket].name)

s3_users: list[S3UserOutputData] = list()
for user in creds:
    s3_users.append(S3UserOutputData(user, creds[user].access_key_id, creds[user].secret_access_key))

pulumi.export(stack_data_name, DataStackOutput(buckets_names_output, s3_users))
