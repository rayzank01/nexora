import os
from pathlib import Path
from urllib.parse import urlparse


def load_env(path='.env'):
    if Path(path).exists():
        for raw in Path(path).read_text(encoding='utf-8-sig').splitlines():
            line = raw.strip()
            if line and not line.startswith('#') and '=' in line:
                key, val = line.split('=', 1)
                os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


class Config:
    def __init__(self):
        self.token = os.getenv('BOT_TOKEN', '')
        self.db = os.getenv('DATABASE_PATH', 'data/nexora.sqlite3')
        on_render = os.getenv('RENDER', '').lower() == 'true'
        self.host = os.getenv('HTTP_HOST', '0.0.0.0' if on_render else '127.0.0.1')
        self.port = int(os.getenv('HTTP_PORT') or os.getenv('PORT') or ('10000' if on_render else '8080'))
        self.public_url = os.getenv('PUBLIC_URL', '').rstrip('/')
        self.support_chat = int(os.getenv('SUPPORT_CHAT_ID', '0'))
        self.support_admins = {int(x) for x in os.getenv('SUPPORT_ADMIN_IDS', '').split(',') if x.strip()}
        self.super_admins = {int(x) for x in os.getenv('SUPER_ADMIN_IDS', '').split(',') if x.strip()}
        self.turnstile_secret = os.getenv('TURNSTILE_SECRET', '')
        self.turnstile_sitekey = os.getenv('TURNSTILE_SITE_KEY', '')
        self.turnstile_hostname = os.getenv('TURNSTILE_HOSTNAME', '')
        self.retention_days = int(os.getenv('RETENTION_DAYS', '90'))


DEFAULTS = dict(language='en', rules='Please be respectful. No spam.', help='',
    welcome='Welcome {first_name} to {chat_title}!', goodbye='Goodbye {first_name}.',
    cleanup_service=True, greeting_ttl=120, locks=[], warn_limit=3, warn_ttl=86400,
    warn_action='mute', action_seconds=3600, flood_count=8, flood_window=10,
    repeat_count=4, captcha='off', captcha_seconds=120, captcha_text='Verify to join {chat_title}.',
    strict=True, new_user_seconds=300, new_user_locks=['links', 'media'], cas=False,
    timezone='UTC', log_chat=0, xp=True)

LOCKS = {'links','media','photo','sticker','animation','video','audio','voice','document',
         'contact','location','venue','poll','forward','video_note','dice','game',
         'text','mention','bot','story','paid_media','live_photo'}
CAPS = {'moderate','delete','pin','invite','config','publish','reports'}
PERMISSIONS = {'can_send_messages','can_send_audios','can_send_documents','can_send_photos',
    'can_send_videos','can_send_video_notes','can_send_voice_notes','can_send_polls',
    'can_send_other_messages','can_add_web_page_previews','can_change_info',
    'can_invite_users','can_pin_messages','can_manage_topics','can_react_to_messages'}
