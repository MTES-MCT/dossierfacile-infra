import pulumi

from lib.stack_output_util import stack_data_name


class MainStackOutput:
    def __init__(self, project_id: pulumi.Output[str]):
        self.project_id = project_id

def get_main_stack_output(env: str) -> pulumi.Output[MainStackOutput]:
    """
    Returns the stack output for the current project.
    """
    stack_ref = pulumi.StackReference(f"organization/main/{env}")
    return stack_ref.require_output(stack_data_name)