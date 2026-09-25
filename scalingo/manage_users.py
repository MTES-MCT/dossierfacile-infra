import logging
import os
from scalingo_client import ScalingoConfig, ScalingoClient

class ScalingoUsersManager:
    def __init__(self, config: ScalingoConfig):
        self.config = config
        self.clients = {
            region: ScalingoClient(config, region)
            for region in config.regions
        }

    def audit_users(self, project_name: str, apply: bool = False) -> None:
        for region, client in self.clients.items():
            logging.info(f"Auditing users in region: {region}")
            apps = client.list_apps_in_project(project_name)

            for app in apps:
                logging.info(f"Checking app: '{app['name']}' in project: '{app['project']['name']}'")
                users = client.list_users(app['name'])

                current_emails = [{'email': user['email'], 'id': user['id']} for user in users]
                unauthorized = [user for user in current_emails if user['email'] not in self.config.allowed_users]
                missing = [user for user in self.config.allowed_users if user not in [user['email'] for user in current_emails]]

                if len(missing) > 0:
                    logging.warning(f"Missing users: {missing}")
                    if apply:
                        for user in missing:
                            try:
                                logging.info(f"Inviting {user} to app: '{app['name']}'")
                                client.invite_user(app['name'], user)
                            except Exception as e:
                                logging.error(f"Failed to invite {user} to '{app['name']}': {e}")

                if len(unauthorized) > 0:
                    logging.warning(f"Unauthorized users: {unauthorized}")
                    if apply:
                        for user in unauthorized:
                            try:
                                logging.info(f"Removing {user['email']} from app: '{app['name']}'")
                                client.delete_user(app['name'], user['id'])
                            except Exception as e:
                                logging.error(f"Failed to remove {user['email']} from '{app['name']}': {e}")

    def add_user(self, project_name: str, email: str) -> None:
        for region, client in self.clients.items():
            logging.info(f"Adding user in region: {region}")
            for app in client.list_apps_in_project(project_name):
                try:
                    logging.info(f"Inviting {email} to app: '{app['name']}'")
                    client.invite_user(app['name'], email)
                except Exception as e:
                    logging.error(f"Failed to invite {email} to '{app['name']}': {e}")

    def remove_user(self, project_name: str, user_id: str) -> None:
        for region, client in self.clients.items():
            logging.info(f"Removing user in region: {region}")
            for app in client.list_apps_in_project(project_name):
                try:
                    logging.info(f"Removing user {user_id} from app: '{app['name']}'")
                    client.delete_user(app['name'], user_id)
                except Exception as e:
                    logging.error(f"Failed to remove {user_id} from '{app['name']}': {e}")

    def update_scm_links(self, project_name: str, linker_id: str) -> None:
        for region, client in self.clients.items():
            logging.info(f"Updating SCM links in region: {region}")
            for app in client.list_apps_in_project(project_name):
                logging.info(f"Updating SCM link for app: '{app['name']}'")
                client.update_scm_repo_link(app['name'], linker_id)

def main():
    logging.basicConfig(level=logging.INFO)
    try:
        config = ScalingoConfig.from_env()
        manager = ScalingoUsersManager(config)
        
        manager.audit_users(project_name='dossierfacile', apply=False)
        # Uncomment to perform other operations:
        # manager.remove_user(project_name='dossierfacile', user_id='66f13384fb0de6001fa65ec3')
        # manager.add_user(project_name='dossierfacile', email='nicolas.sagon@beta.gouv.fr')
        # manager.update_scm_links(project_name='dossierfacile', linker_id=os.getenv('SCALINGO_SCM_LINK_ID'))
        
    except Exception as e:
        logging.error(f"An error occurred: {str(e)}")

if __name__ == '__main__':
    main()