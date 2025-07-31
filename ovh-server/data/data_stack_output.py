import pulumi

from lib.stack_output_util import stack_data_name


class S3UserOutputData:
    def __init__(
            self,
            user_name: str,
            access_key_id: pulumi.Output[str],
            secret_access_key: pulumi.Output[str],
    ):
        self.user_name = user_name
        self.access_key_id = access_key_id
        self.secret_access_key = secret_access_key


class DataStackOutput:
    def __init__(self, storage_names: list[pulumi.Output[str]], s3_users: list[S3UserOutputData]):
        self.s3_users = s3_users
        self.storage_names = storage_names


def get_data_stack_output(env: str) -> pulumi.Output[DataStackOutput]:
    """
    Returns the stack output for the current project.
    """
    stack_ref = pulumi.StackReference(f"organization/data/{env}")
    return stack_ref.require_output(stack_data_name)
