from scalingo_client import ScalingoConfig, ScalingoClient
import logging
import os

# Set your Slack webhook URL and platform_id here
SLACK_WEBHOOK_URL = os.getenv('SLACK_WEBHOOK_URL')
SCALINGO_SLACK_DEFAULT_NOTIFIER = 'mattermost-default-notifier'

def create_slack_notifier_for_all_apps():
    config = ScalingoConfig.from_env()
    for region in config.regions:
        client = ScalingoClient(config, region)

        platforms = client.list_notification_platforms()
        # get the platform id with name 'slack':
        slack_platform = next((platform for platform in platforms if platform['name'] == 'slack'), None)
        logging.info(f"Slack platform: {slack_platform['id']}")

        apps = client.list_apps()
        for app in apps:
            app_name = app['name']

            logging.info(f"Listing notifiers for app: {app_name} in region: {region}")

            notifiers = client.list_notifiers(app_name)
            if any(notifier['name'] == SCALINGO_SLACK_DEFAULT_NOTIFIER for notifier in notifiers):
                logging.info(f"Notifiers already exist for app: {app_name} in region: {region}, skipping creation")
                continue

            logging.info(f"Setting up Slack notifier for app: {app_name} in region: {region}")
            
            # workaround, event_ids are different between regions
            if region == 'osc-secnum-fr1':
                available_event_ids = [
                    "5e4a849d6763dd00afc96f96",
                    "5e4a849d6763dd00afc96fa6",
                    "5e4a849d6763dd00afc96fa1",
                    "5e4a849d6763dd00afc96fa2",
                    "5e4a849d6763dd00afc96fa3",
                    "5f0c28056c91430017089607",
                    "5e4a849d6763dd00afc96f98",
                    "5e4a849d6763dd00afc96f99",
                    "5e4a849d6763dd00afc96f9d",
                    "5f0c28056c91430017089606",
                    "5e4a849d6763dd00afc96f9f",
                    "5e4a849d6763dd00afc96f97",
                    "5e4a849d6763dd00afc96f9b",
                    "5e4a849d6763dd00afc96fa8",
                    "5e4a849d6763dd00afc96fa7",
                    "5e4a849d6763dd00afc96fa9",
                    "5e4a849d6763dd00afc96faa",
                    "5e4a849d6763dd00afc96fab",
                    "5e4a849d6763dd00afc96fac",
                    "5e4a849d6763dd00afc96faf",
                    "5e4a849d6763dd00afc96fae",
                    "5e4a849d6763dd00afc96fb0",
                    "5e4a849d6763dd00afc96fb2",
                    "5e4a849d6763dd00afc96fb1",
                    "5e4a849d6763dd00afc96fb3"
                ]
            else :
                available_event_ids = [
                    "5c90e9370dd6901c61e69217",
                    "5c90e9380dd6901c61e69226",
                    "5c90e9380dd6901c61e69227",
                    "5c90e9380dd6901c61e69222",
                    "5c90e9380dd6901c61e69223",
                    "5c90e9380dd6901c61e69224",
                    "5de653963e6b3b000e420973",
                    "5f0c27f8f6b5a80017cbbe58",
                    "5c90e9370dd6901c61e69219",
                    "5c90e9370dd6901c61e6921a",
                    "5c90e9380dd6901c61e6921e",
                    "5f0c27f8f6b5a80017cbbe56",
                    "5c90e9380dd6901c61e69220",
                    "5c90e9370dd6901c61e69218",
                    "5c90e9370dd6901c61e6921c",
                    "5c90e9380dd6901c61e6921f",
                    "5c90e9390dd6901c61e69229",
                    "5c90e9390dd6901c61e69228",
                    "5c90e9390dd6901c61e6922a",
                    "5c90e9390dd6901c61e6922b",
                    "5c90e9390dd6901c61e6922c",
                    "5c90e9390dd6901c61e6922d",
                    "5c90e9390dd6901c61e6922f",
                    "5c90e9390dd6901c61e69230",
                    "5c90e9390dd6901c61e69231",
                    "5c90e93a0dd6901c61e69233",
                    "5c90e93a0dd6901c61e69232",
                    "5c90e93a0dd6901c61e69234"
                ]
                
            try:
                client.add_notifier(
                    app_name,
                    SCALINGO_SLACK_DEFAULT_NOTIFIER,
                    slack_platform['id'],
                    available_event_ids,
                    SLACK_WEBHOOK_URL
                )
                logging.info(f"Notifier created for app: {app_name}")
            except Exception as e:
                logging.error(f"Failed to create notifier for app {app_name}: {e}")

def main():
    logging.basicConfig(level=logging.INFO)
    create_slack_notifier_for_all_apps()

if __name__ == '__main__':
    main()
