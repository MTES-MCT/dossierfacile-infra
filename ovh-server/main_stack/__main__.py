import pulumi
import pulumi_ovh as ovh

from lib.stack_output_util import stack_data_name
from main_stack import MainStackOutput

env = pulumi.get_stack()
project_resource = ovh.cloudproject.Project(
    f"P-DossierFacile-{env}",
    description=f"Pulumi managed project for env : {env}",
    ovh_subsidiary="FR",
    plan=ovh.cloudproject.ProjectPlanArgs(
        plan_code="project.2018",  # Code du plan (Public Cloud project EU)
        pricing_mode="default",  # Mode de facturation par défaut (pay-as-you-go)
        duration="P1M"  # Durée de facturation (mensuelle, P1M = 1 mois)
    )
)

pulumi.export(stack_data_name, MainStackOutput(project_resource.id))


