from dataclasses import dataclass
from typing import List, Optional, Dict, Any
from dotenv import load_dotenv
import os
import requests
import logging

@dataclass
class ScalingoConfig:
    api_token: str
    allowed_users: List[str]
    auth_url: str = 'https://auth.scalingo.com/v1'
    regions: List[str] = ('osc-secnum-fr1', 'osc-fr1')

    @classmethod
    def from_env(cls) -> 'ScalingoConfig':
        load_dotenv()
        api_token = os.getenv('SCALINGO_API_TOKEN')
        if not api_token:
            raise ValueError("SCALINGO_API_TOKEN environment variable not found")
        
        allowed_users = os.getenv('SCALINGO_DOSSIER_FACILE_USERS', '').split()
        return cls(api_token=api_token, allowed_users=allowed_users)

# https://developers.scalingo.com/index#global-information
class ScalingoClient:
    def __init__(self, config: ScalingoConfig, region: str):
        self.config = config
        self.region = region
        self.api_url = f'https://api.{region}.scalingo.com/v1'
        self.bearer_token = self._get_bearer_token()

    def _get_bearer_token(self) -> str:
        response = self._make_request(
            'POST',
            f'{self.config.auth_url}/tokens/exchange',
            auth=('', self.config.api_token)
        )
        return response['token']

    def _make_request(
        self,
        method: str,
        url: str,
        json: Dict = None,
        auth: tuple = None
    ) -> Any:
        headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        }
        
        if not auth:
            headers['Authorization'] = f'Bearer {self.bearer_token}'

        response = requests.request(
            method=method,
            url=url,
            headers=headers,
            json=json,
            auth=auth
        )

        if response.status_code == 404:
            logging.warning(f"Resource not found: {response.json()}")
            return None
        
        if response.status_code == 422:
            logging.warning(f"Resource already exists or invalid: {response.json()}")
            return None

        if not 200 <= response.status_code < 300:
            raise Exception(f"API request failed: {response.status_code}, {response.json()}")

        return response.json() if response.content else None

    def list_apps_in_project(self, project_name: str) -> List[Dict]:
        response = self._make_request('GET', f'{self.api_url}/apps')
        apps = response['apps']
        
        filtered_apps = [app for app in apps if app['project']['name'] == project_name]
        return sorted(filtered_apps, key=lambda app: app['name'])

    def list_users(self, app_name: str) -> List[Dict]:
        response = self._make_request('GET', f'{self.api_url}/apps/{app_name}/collaborators')
        return response['collaborators']

    def invite_user(self, app_name: str, email: str, limited: bool = False) -> Optional[str]:
        # Scalingo defaults `is_limited` to true, which would grant a read-only
        # "Limited Collaborator" role. Send it explicitly so a full collaborator
        # is created unless `limited` is requested.
        response = self._make_request(
            'POST',
            f'{self.api_url}/apps/{app_name}/collaborators',
            json={'collaborator': {'email': email, 'is_limited': limited}}
        )
        if response:
            return response['collaborator']['invitation_link']
        return None

    def delete_user(self, app_name: str, user_id: str) -> None:
        self._make_request(
            'DELETE',
            f'{self.api_url}/apps/{app_name}/collaborators/{user_id}'
        )

    def update_scm_repo_link(self, app_name: str, linker_id: str) -> Optional[Dict]:
        response = self._make_request(
            'PATCH',
            f'{self.api_url}/apps/{app_name}/scm_repo_link',
            json={'scm_repo_link': {'linker_id': linker_id}}
        )
        return response.get('scm_repo_link') if response else None 
    
    
    
    def add_notifier(self, app_name: str, notifier_name: str, platform_id: str, selected_event_ids: List[str], webhook_url: str) -> Optional[Dict]:
        response = self._make_request(
            'POST',
            f'{self.api_url}/apps/{app_name}/notifiers',
            json={
                'notifier': {
                    'active': True,
                    'name': notifier_name,
                    'platform_id': platform_id,
                    'send_all_events': False,
                    'selected_event_ids': selected_event_ids,
                    'type_data': {
                        'webhook_url': webhook_url
                    }
                }
            }
        )
        return response.get('notifier') if response else None
    
    def list_notifiers(self, app_name: str) -> List[Dict]:
        response = self._make_request('GET', f'{self.api_url}/apps/{app_name}/notifiers')
        return response['notifiers']
    
    def delete_notifier(self, app_name: str, notifier_id: str) -> None:
        self._make_request(
            'DELETE',
            f'{self.api_url}/apps/{app_name}/notifiers/{notifier_id}'
        )

    def list_notification_platforms(self) -> List[Dict]:
        response = self._make_request('GET', f'{self.api_url}/notification_platforms')
        return response['notification_platforms']
