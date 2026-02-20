"""
GroundUp Toolkit - Shared Configuration Loader

Reads config.yaml and .env to provide a unified config interface
for all skills and scripts.

Usage:
    from lib.config import config
    # or if running from a skill/script subdirectory:
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    from lib.config import config

    config.assistant_name        # "Christina"
    config.assistant_email       # "christina@yourco.com"
    config.team_members          # list of member dicts
    config.get_member_by_email("alice@yourco.com")
    config.get_member_by_phone("+1234567890")
"""

import os
import yaml

_TOOLKIT_ROOT = os.environ.get(
    'TOOLKIT_ROOT',
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)


def _load_env():
    """Load .env file into os.environ if it exists."""
    env_path = os.path.join(_TOOLKIT_ROOT, '.env')
    if not os.path.exists(env_path):
        # Also check ~/.env for server deployments
        env_path = os.path.expanduser('~/.env')
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                line = line.replace('export ', '', 1)
                if '=' not in line:
                    continue
                key, val = line.split('=', 1)
                val = val.strip().strip('"').strip("'")
                if key not in os.environ:
                    os.environ[key] = val


def _load_yaml():
    """Load config from config.yaml, a custom path, or GROUNDUP_CONFIG_JSON env var.

    Resolution order:
      1. TOOLKIT_CONFIG env var (path to a yaml file)
      2. config.yaml in TOOLKIT_ROOT
      3. GROUNDUP_CONFIG_JSON env var (full config as a JSON string)
         — useful for container/cloud deployments where mounting a file is inconvenient

    Example for container deployments:
      GROUNDUP_CONFIG_JSON='{"assistant":{"name":"Aria","email":"aria@company.com"},"team":{"domain":"company.com","members":[...]}}'
    """
    config_path = os.environ.get(
        'TOOLKIT_CONFIG',
        os.path.join(_TOOLKIT_ROOT, 'config.yaml')
    )
    if os.path.exists(config_path):
        with open(config_path) as f:
            return yaml.safe_load(f)

    config_json = os.environ.get('GROUNDUP_CONFIG_JSON')
    if config_json:
        import json
        return json.loads(config_json)

    raise FileNotFoundError(
        f"Config not found. Options:\n"
        f"  1. Copy config.example.yaml to {config_path} and fill in your values.\n"
        f"  2. Set TOOLKIT_CONFIG to the path of your config yaml.\n"
        f"  3. Set GROUNDUP_CONFIG_JSON to the full config as a JSON string "
        f"(useful for container/cloud deployments)."
    )


class ToolkitConfig:
    def __init__(self):
        _load_env()
        self._data = _load_yaml()

    def reload(self):
        self._data = _load_yaml()

    # --- Assistant ---
    @property
    def assistant_name(self):
        return self._data['assistant']['name']

    @property
    def assistant_email(self):
        return self._data['assistant']['email']

    @property
    def whatsapp_account(self):
        return self._data['assistant'].get('whatsapp_account', 'main')

    # --- Team ---
    @property
    def team_domain(self):
        return self._data['team']['domain']

    @property
    def team_members(self):
        return self._data['team']['members']

    def get_member_by_email(self, email):
        for m in self.team_members:
            if m['email'].lower() == email.lower():
                return m
        return None

    def get_member_by_phone(self, phone):
        # Normalize: strip spaces, dashes
        phone = phone.replace(' ', '').replace('-', '')
        for m in self.team_members:
            if m['phone'].replace(' ', '').replace('-', '') == phone:
                return m
        return None

    def get_member_by_name(self, name):
        name_lower = name.lower()
        for m in self.team_members:
            if m['name'].lower() == name_lower:
                return m
            # Match first name
            if m['name'].split()[0].lower() == name_lower:
                return m
        return None

    @property
    def team_emails(self):
        return [m['email'] for m in self.team_members]

    @property
    def team_phones(self):
        return {m['phone']: m['email'] for m in self.team_members}

    @property
    def enabled_members(self):
        return [m for m in self.team_members if m.get('reminders_enabled', True)]

    # --- HubSpot ---
    @property
    def hubspot_api_gateway(self):
        return self._data['hubspot']['api_gateway']

    @property
    def hubspot_portal_id(self):
        return self._data['hubspot'].get('portal_id', '')

    @property
    def hubspot_pipelines(self):
        return self._data['hubspot'].get('pipelines', [])

    @property
    def hubspot_default_pipeline(self):
        """Return the first pipeline's ID (or 'default')."""
        pipelines = self.hubspot_pipelines
        if pipelines:
            return pipelines[0]['id']
        return 'default'

    @property
    def hubspot_deal_stage(self):
        """Return the first pipeline's default stage."""
        pipelines = self.hubspot_pipelines
        if pipelines:
            return pipelines[0].get('default_stage', 'presentationscheduled')
        return 'presentationscheduled'

    def get_pipeline_by_id(self, pipeline_id):
        for p in self.hubspot_pipelines:
            if p['id'] == pipeline_id:
                return p
        return None

    def get_pipeline_name(self, pipeline_id):
        p = self.get_pipeline_by_id(pipeline_id)
        return p['name'] if p else pipeline_id

    def get_stage_name(self, pipeline_id, stage_id):
        p = self.get_pipeline_by_id(pipeline_id)
        if p and 'stage_names' in p:
            return p['stage_names'].get(stage_id, stage_id)
        return stage_id

    def get_hubspot_owner_id(self, email):
        m = self.get_member_by_email(email)
        return m.get('hubspot_owner_id') if m else None

    # --- Scheduling ---
    @property
    def shabbat_aware(self):
        return self._data.get('scheduling', {}).get('shabbat_aware', False)

    @property
    def work_hours(self):
        sched = self._data.get('scheduling', {})
        return (sched.get('work_hours_start', 9), sched.get('work_hours_end', 18))

    # --- Notifications ---
    @property
    def alert_phone(self):
        return self._data.get('notifications', {}).get('alert_phone', '')

    @property
    def alert_email(self):
        return self._data.get('notifications', {}).get('alert_email', '')

    @property
    def watchdog_cooldown(self):
        return self._data.get('notifications', {}).get('watchdog_cooldown_minutes', 60) * 60

    # --- Meeting Bot ---
    @property
    def camofox_port(self):
        return self._data.get('meeting_bot', {}).get('camofox_port', 9377)

    @property
    def meeting_bot_account(self):
        return self._data.get('meeting_bot', {}).get('google_account', self.assistant_email)

    # --- Environment secrets (from .env) ---
    @property
    def anthropic_api_key(self):
        return os.environ.get('ANTHROPIC_API_KEY', '')

    @property
    def maton_api_key(self):
        return os.environ.get('MATON_API_KEY', '')

    @property
    def brave_search_api_key(self):
        return os.environ.get('BRAVE_SEARCH_API_KEY', '')

    @property
    def gog_keyring_password(self):
        return os.environ.get('GOG_KEYRING_PASSWORD', '')

    @property
    def twilio_account_sid(self):
        return os.environ.get('TWILIO_ACCOUNT_SID', '')

    @property
    def twilio_api_key_sid(self):
        return os.environ.get('TWILIO_API_KEY_SID', '')

    @property
    def twilio_api_key_secret(self):
        return os.environ.get('TWILIO_API_KEY_SECRET', '')

    @property
    def twilio_from_number(self):
        return os.environ.get('TWILIO_FROM_NUMBER', '')


# Singleton instance
config = ToolkitConfig()
