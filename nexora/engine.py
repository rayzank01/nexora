import fnmatch
import hashlib
import html
import io
import json
import re
import secrets
import time
from collections import deque
from datetime import datetime
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from .config import DEFAULTS, LOCKS, CAPS, PERMISSIONS
from .transport import RemoteError, request_json
from .health import WorkerHealth
from .broadcasts import SuperAdminBroadcasts


def duration(value):
    m = re.fullmatch(r'(\d+)([smhd]?)', str(value))
    if not m:
        raise ValueError('Use a duration such as 60s, 10m, 2h or 7d')
    return int(m[1]) * {'': 1, 's': 1, 'm': 60, 'h': 3600, 'd': 86400}[m[2]]


def scheduled_time(value, zone):
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        z = ZoneInfo(zone)
        first, second = dt.replace(tzinfo=z, fold=0), dt.replace(tzinfo=z, fold=1)
        if first.utcoffset() != second.utcoffset():
            raise ValueError('Ambiguous/nonexistent local time: supply an explicit UTC offset')
        dt = first
    return dt.timestamp()


def render(text, user, chat):
    values = {'first_name': user.get('first_name', 'member'),
              'username': '@' + user['username'] if user.get('username') else str(user['id']),
              'user_id': user['id'], 'chat_title': chat.get('title', 'Nexora'), 'chat_id': chat['id']}
    # Literal substitution, never Python format/eval; escape untrusted profile strings for HTML.
    for k, v in values.items():
        text = text.replace('{' + k + '}', html.escape(str(v)))
    return text


def content_types(m):
    found = {k for k in LOCKS if k in m}
    if found & {'photo','sticker','animation','video','audio','voice','document','video_note','live_photo','paid_media'}:
        found.add('media')
    if 'forward_origin' in m:
        found.add('forward')
    if m.get('from', {}).get('is_bot'):
        found.add('bot')
    if any(e['type'] in ('url', 'text_link') for e in m.get('entities', []) + m.get('caption_entities', [])):
        found.add('links')
    if re.search(r'(?:https?://|www\.|t\.me/|\b[\w-]+\.(?:com|org|net|io|me)\b)', m.get('text', '') + m.get('caption', ''), re.I):
        found.add('links')
    if any(e['type'] in ('mention','text_mention') for e in m.get('entities', []) + m.get('caption_entities', [])):
        found.add('mention')
    return found


def matches(rule, m):
    text = (m.get('text') or m.get('caption') or '').casefold()[:8192]
    value = rule['match'].casefold()
    kind = rule['type']
    if kind == 'word':
        return bool(re.search(r'(?<!\w)' + re.escape(value) + r'(?!\w)', text))
    if kind == 'phrase':
        return value in text
    if kind == 'pattern':
        return fnmatch.fnmatchcase(text, value)
    if kind == 'user':
        u = m.get('from', {})
        return value.lstrip('@') in {str(u.get('id')), u.get('username', '').casefold()}
    if kind == 'domain':
        candidates = re.findall(r'(?:https?://|www\.)[^\s<>]+|\b[\w.-]+\.[a-z]{2,}(?:/[^\s<>]*)?', text)
        candidates += [e['url'] for e in m.get('entities', []) + m.get('caption_entities', []) if e.get('url')]
        for url in candidates:
            host = (urlparse(url if '://' in url else 'https://' + url).hostname or '').lower().rstrip('.')
            if host == value or host.endswith('.' + value):
                return True
    return False


class Engine:
    def __init__(self, db, tg, config):
        self.db, self.tg, self.config = db, tg, config
        self.me = {'id': 0, 'username': 'NexoraBot'}
        self.flood = {}
        self.health = WorkerHealth()
        self.superadmin = SuperAdminBroadcasts(self)

    def settings(self, chat):
        return {**DEFAULTS, **self.db.get(chat, 'config', 'settings', {})}

    def say(self, chat, text, **kwargs):
        return self.tg.call('sendMessage', chat_id=chat, text=str(text)[:4096], **kwargs)

    def member(self, chat, user):
        return self.tg.call('getChatMember', chat_id=chat, user_id=user)

    def admin(self, chat, user):
        return self.member(chat, user).get('status') in ('creator', 'administrator')

    def require(self, chat, user, cap='config', native=False):
        member = self.member(chat, user)
        if member.get('status') == 'creator':
            return
        if member.get('status') == 'administrator':
            right = {'moderate':'can_restrict_members','delete':'can_delete_messages',
                     'pin':'can_pin_messages','invite':'can_invite_users','publish':'can_post_messages'}.get(cap)
            if not right or member.get(right) or (cap == 'publish' and self.tg.call('getChat', chat_id=chat)['type'] != 'channel'):
                return
        if not native and member.get('status') not in ('left', 'kicked'):
            role = self.db.get(chat, 'roles', user, [])
            if cap in role:
                return
        raise PermissionError('You do not have permission for this action in this chat')

    def bot_right(self, chat, right):
        m = self.member(chat, self.me['id'])
        if m.get('status') != 'administrator' or not m.get(right):
            raise PermissionError('Give Nexora the Telegram permission: ' + right)

    def protect(self, chat, user):
        if user == self.me['id'] or self.admin(chat, user):
            raise PermissionError('Administrators and the bot are protected')

    def audit(self, chat, user, action, **data):
        self.db.event(chat, user, 'mod', {'action': action, **data})
        dest = self.settings(chat)['log_chat']
        if dest:
            try:
                self.say(dest, f'Nexora | chat {chat} | user {user} | {action}\n{json.dumps(data, ensure_ascii=False)}')
            except RemoteError:
                self.db.event(chat, 0, 'log_delivery_failed')

    def delete_message(self, chat, mid):
        self.bot_right(chat, 'can_delete_messages')
        self.tg.call('deleteMessage', chat_id=chat, message_id=mid)

    def moderate(self, chat, user, action, seconds=0, reason='', permissions=None):
        self.protect(chat, user)
        self.bot_right(chat, 'can_restrict_members')
        if seconds and not 60 <= seconds <= 365 * 86400:
            raise ValueError('Timed restrictions must be 60 seconds to 365 days')
        until = int(time.time()) + seconds if seconds else 0
        if action in ('ban', 'kick'):
            self.tg.call('banChatMember', chat_id=chat, user_id=user, until_date=until)
            if action == 'kick':
                self.tg.call('unbanChatMember', chat_id=chat, user_id=user, only_if_banned=True)
        elif action == 'unban':
            self.tg.call('unbanChatMember', chat_id=chat, user_id=user, only_if_banned=True)
        elif action in ('mute','restrict','unmute'):
            if self.tg.call('getChat', chat_id=chat)['type'] != 'supergroup':
                raise ValueError('Restrictions require a supergroup')
            if action == 'unmute':
                pending = self.db.get(chat, 'captcha', user)
                if pending and pending['status'] == 'pending':
                    raise ValueError('Use /verify first for a pending CAPTCHA')
                permissions = self.tg.call('getChat', chat_id=chat).get('permissions', {})
            elif action == 'mute':
                permissions = {p: False for p in PERMISSIONS}
            if not permissions or not set(permissions) <= PERMISSIONS or any(type(x) is not bool for x in permissions.values()):
                raise ValueError('Provide a JSON object of valid boolean ChatPermissions')
            self.tg.call('restrictChatMember', chat_id=chat, user_id=user, permissions=permissions,
                         use_independent_chat_permissions=True, until_date=until)
        else:
            raise ValueError('Unknown moderation action')
        self.audit(chat, user, action, seconds=seconds, reason=reason)
        self.db.delete(chat,'restore_revision',user)
        if action == 'ban':
            self.db.put(chat,'ban_source',user,'local')
        elif action in ('unban','kick'):
            self.db.delete(chat,'ban_source',user)
        pending = self.db.get(chat,'captcha',user)
        if pending and pending['status']=='pending' and reason not in ('Pending verification','Verification timeout'):
            # A new moderator decision supersedes verification; do not lift the newer restriction.
            pending['status']='cancelled'
            self.db.put(chat,'captcha',user,pending)

    def warn(self, chat, user, ttl=None, reason=''):
        self.protect(chat, user)
        s = self.settings(chat)
        now = time.time()
        warnings = [w for w in self.db.get(chat, 'warnings', user, []) if w['expires'] == 0 or w['expires'] > now]
        ttl = s['warn_ttl'] if ttl is None else ttl
        warnings.append({'expires': now + ttl if ttl else 0, 'reason': reason})
        self.db.put(chat, 'warnings', user, warnings)
        self.audit(chat, user, 'warn', count=len(warnings), reason=reason)
        if len(warnings) >= s['warn_limit']:
            self.moderate(chat, user, s['warn_action'], s['action_seconds'], 'Warning threshold')
            self.db.delete(chat, 'warnings', user)
        return len(warnings)

    def configure(self, chat, user, key, value):
        self.require(chat, user)
        if key not in DEFAULTS:
            raise ValueError('Unknown setting')
        expected = type(DEFAULTS[key])
        if type(value) is not expected:
            raise ValueError('Wrong value type; use JSON strings, numbers, true/false or lists')
        if key == 'language' and value not in ('en','ml'):
            raise ValueError('Supported languages: en, ml')
        if key in ('locks','new_user_locks') and (not all(isinstance(x,str) for x in value) or not set(value) <= LOCKS):
            raise ValueError('Unsupported lock; see docs/COMMANDS.md')
        if key == 'captcha' and value not in ('off','button','response','math','image','private','web','turnstile'):
            raise ValueError('Unsupported CAPTCHA')
        if key in ('captcha_seconds','action_seconds') and not 60 <= value <= 86400:
            raise ValueError('Use 60..86400 seconds')
        if key == 'warn_action' and value not in ('mute','ban','kick'):
            raise ValueError('Use mute, ban or kick')
        if key in ('warn_limit','flood_count','repeat_count','flood_window') and not 1 <= value <= 1000:
            raise ValueError('Use 1..1000')
        if key in ('warn_ttl','new_user_seconds','greeting_ttl') and not 0 <= value <= 31536000:
            raise ValueError('Use 0..31536000')
        if key == 'timezone':
            ZoneInfo(value)
        if key == 'log_chat' and value:
            self.require(value, user, native=True)
        if key == 'captcha' and value in ('web','turnstile'):
            if not self.config.public_url.startswith('https://'):
                raise ValueError('Configure PUBLIC_URL with HTTPS first')
            if value == 'turnstile' and not all((self.config.turnstile_secret, self.config.turnstile_sitekey, self.config.turnstile_hostname)):
                raise ValueError('Configure all Turnstile environment values first')
        if isinstance(value, str) and len(value) > 3500:
            raise ValueError('Text too long')
        s = self.settings(chat)
        s[key] = value
        self.db.put(chat, 'config', 'settings', s)
        self.audit(chat, user, 'setting', key=key)

    def capture(self, message, fallback=''):
        for kind in ('animation','photo','video','audio','voice','document','sticker','video_note'):
            if kind in message:
                obj = message[kind][-1] if kind == 'photo' else message[kind]
                return {'kind': kind, 'file_id': obj['file_id'], 'text': message.get('caption', ''),
                        'entities': message.get('caption_entities', [])}
        if message.get('text'):
            return {'kind':'text','text':message['text'], 'entities':message.get('entities', [])}
        if message:
            return {'kind':'copy','chat':message['chat']['id'],'message':message['message_id'], 'text':''}
        return {'kind':'text','text':fallback, 'entities':[], 'html':True}

    def send_content(self, dest, content, user=None, chat=None, silent=False):
        p = {'chat_id': dest, 'disable_notification': silent}
        text = content.get('text','')
        templated = user is not None and chat is not None and any('{' + key + '}' in text for key in
            ('first_name','username','user_id','chat_title','chat_id'))
        if templated:
            text = render(text, user, chat)
        markup = content.get('buttons')
        if markup:
            p['reply_markup'] = {'inline_keyboard': markup}
        kind = content['kind']
        if kind == 'copy':
            return self.tg.call('copyMessage', from_chat_id=content['chat'], message_id=content['message'], **p)
        if kind == 'text':
            p['text'] = text
            if templated or content.get('html'):
                p['parse_mode'] = 'HTML'
            elif content.get('entities'):
                p['entities'] = content['entities']
            return self.tg.call('sendMessage', **p)
        p[kind] = content['file_id']
        if kind not in ('sticker','video_note'):
            p['caption'] = text
            if templated or content.get('html'):
                p['parse_mode'] = 'HTML'
            elif content.get('entities'):
                p['caption_entities'] = content['entities']
        return self.tg.call('send' + {'video_note':'VideoNote'}.get(kind, kind.title()), **p)

    def add_rule(self, chat, user, name, rule):
        self.require(chat, user)
        if rule.get('type') not in ('word','phrase','domain','user','pattern') or not isinstance(rule.get('match'),str) or not 1 <= len(rule['match']) <= 256:
            raise ValueError('Rule needs type and match (1..256 characters)')
        if not set(rule.get('actions', [])) <= {'delete','warn','mute','ban','kick','reply'}:
            raise ValueError('Invalid rule action')
        if rule.get('audience', 'all') not in ('all','admin','user') or type(rule.get('bots', False)) is not bool:
            raise ValueError('Invalid audience/bots value')
        self.db.put(chat, 'rules', name[:40], rule)

    def apply_rules(self, m):
        chat, user = m['chat']['id'], m['from']['id']
        s = self.settings(chat)
        admin = self.admin(chat, user)
        exempt = admin or self.db.get(chat, 'trusted', user, False)
        if not exempt:
            types = content_types(m)
            joined = self.db.get(chat, 'members', user, {}).get('joined', 0)
            new = joined and time.time() - joined < s['new_user_seconds']
            if types.intersection(s['locks']) or (new and types.intersection(s['new_user_locks'])):
                self.delete_message(chat, m['message_id'])
                self.warn(chat, user, reason='Content lock')
                return True
            now = time.time()
            queue = self.flood.setdefault((chat,user), deque(maxlen=1001))
            digest = hashlib.sha256((m.get('text') or m.get('caption') or str(sorted(types))).encode()).hexdigest()
            queue.append((now,digest))
            while queue and queue[0][0] < now - s['flood_window']:
                queue.popleft()
            if len(queue) > s['flood_count'] or sum(x[1] == digest for x in queue) >= s['repeat_count']:
                self.delete_message(chat, m['message_id'])
                self.moderate(chat,user,'mute',s['action_seconds'],'Flood/repeated content')
                queue.clear()
                return True
        for name, r in self.db.items(chat,'rules').items():
            if m['from'].get('is_bot') and not r.get('bots', False):
                continue
            audience = r.get('audience', 'all')
            if (audience == 'admin' and not admin) or (audience == 'user' and admin) or not matches(r,m):
                continue
            deleted = False
            for action in r.get('actions', []):
                if action == 'reply':
                    saved = self.db.get(chat,'notes',r.get('note',''))
                    if saved:
                        self.send_content(chat,saved,m['from'],m['chat'])
                    elif r.get('reply'):
                        self.say(chat,render(r['reply'],m['from'],m['chat']),parse_mode='HTML')
                elif not exempt:
                    if action == 'delete':
                        self.delete_message(chat,m['message_id'])
                        deleted = True
                    elif action == 'warn':
                        self.warn(chat,user,reason='Rule: ' + name)
                    else:
                        self.moderate(chat,user,action,s['action_seconds'],'Rule: ' + name)
            if deleted:
                return True
        return False

    def greet(self, chat, user, key):
        s = self.settings(chat['id'])
        saved = self.db.get(chat['id'],'notes',key)
        if saved:
            sent = self.send_content(chat['id'],saved,user,chat)
        elif s[key]:
            sent = self.say(chat['id'],render(s[key],user,chat),parse_mode='HTML')
        else:
            return
        if s['greeting_ttl']:
            self.db.job(chat['id'],'delete',time.time()+s['greeting_ttl'],{'message_id':sent['message_id']})

    def start_captcha(self, chat, user, request=False, private_chat=None):
        cid, uid = chat['id'], user['id']
        s = self.settings(cid)
        if self.db.get(cid,'trusted',uid,False) or self.admin(cid,uid):
            if request:
                self.bot_right(cid,'can_invite_users')
                self.tg.call('approveChatJoinRequest',chat_id=cid,user_id=uid)
            else:
                self.greet(chat,user,'welcome')
            return
        for fid, fed in self.db.items('global','fed').items():
            if cid in fed['chats'] and str(uid) in fed['bans']:
                self.moderate(cid,uid,'ban',reason='Federation ' + fid)
                self.db.put(cid,'ban_source',uid,fid)
                return
        if s['cas']:
            try:
                cas = request_json('https://api.cas.chat/check?user_id=' + str(uid))
                if cas.get('ok') and isinstance(cas.get('result'),dict):
                    self.moderate(cid,uid,'ban',reason='Opt-in CAS reputation')
                    return
            except RemoteError:
                self.db.event(cid,uid,'cas_unavailable')
        mode = s['captcha']
        if mode == 'off':
            if request:
                self.bot_right(cid,'can_invite_users')
                self.tg.call('approveChatJoinRequest',chat_id=cid,user_id=uid)
            else:
                self.greet(chat,user,'welcome')
            return
        previous = self.member(cid,uid)
        if not request:
            self.moderate(cid,uid,'mute',reason='Pending verification')
        else:
            self.bot_right(cid,'can_invite_users')
        a,b = secrets.randbelow(8)+2, secrets.randbelow(8)+2
        answer = str(a+b) if mode == 'math' else ''.join(secrets.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(5))
        token = secrets.token_urlsafe(24)
        c = {'token':token,'answer':answer,'question':f'{a} + {b} = ?', 'expires':time.time()+s['captcha_seconds'],
             'mode':mode,'status':'pending','attempts':0,'request':request,'user':user,'chat':chat,
             'previous':previous, 'prompts':[]}
        self.db.put(cid,'captcha',uid,c)
        self.db.job(cid,'captcha_expire',c['expires'],{'user':uid,'token':token})
        private_mode = request or mode in ('private','web','turnstile','response','math','image')
        if private_mode and not private_chat:
            sent = self.say(cid,render(s['captcha_text'],user,chat),parse_mode='HTML',reply_markup={'inline_keyboard':[[
                {'text':'Verify privately / പരിശോധിക്കുക','url':f'https://t.me/{self.me["username"]}?start=verify_{cid}'}]]})
            c['prompts'].append([cid,sent['message_id']])
            self.db.put(cid,'captcha',uid,c)
        else:
            self.captcha_prompt(cid,uid,private_chat or cid)

    def captcha_prompt(self, cid, uid, dest):
        c = self.db.get(cid,'captcha',uid)
        if not c or c['status'] != 'pending' or c['expires'] < time.time():
            raise ValueError('No active verification; ask a group admin')
        mode = c['mode']
        if mode in ('web','turnstile'):
            sent = self.say(dest,'Open your private verification link. Do not share it.',reply_markup={'inline_keyboard':[[
                {'text':'Verify','url':self.config.public_url + '/verify?token=' + c['token']}]]})
        elif mode in ('response','math','image'):
            self.db.put(uid,'session','captcha',cid)
            if mode == 'image':
                from PIL import Image, ImageDraw
                im = Image.new('RGB',(280,90),'#182334')
                d = ImageDraw.Draw(im)
                for _ in range(18):
                    d.line((secrets.randbelow(280),secrets.randbelow(90),secrets.randbelow(280),secrets.randbelow(90)),fill='#426078')
                d.text((30,22),c['answer'],font_size=38,fill='#ffffff')
                buf = io.BytesIO()
                im.save(buf,format='PNG')
                sent = self.tg.photo(dest,buf.getvalue(),caption='Type the characters shown. / അക്ഷരങ്ങൾ നൽകുക.')
            else:
                sent = self.say(dest,c['question'] if mode == 'math' else 'Type: ' + c['answer'])
        else:
            sent = self.say(dest,'Tap to verify / പരിശോധിക്കുക',reply_markup={'inline_keyboard':[[
                {'text':'I am here / ഞാൻ ഇവിടെ ഉണ്ട്','callback_data':'v:' + c['token']}]]})
        c['prompts'].append([dest,sent['message_id']])
        self.db.put(cid,'captcha',uid,c)

    def find_captcha(self, token):
        for row in self.db.sql("SELECT scope,key,value FROM docs WHERE kind='captcha'"):
            c = json.loads(row['value'])
            if secrets.compare_digest(c['token'],token):
                return int(row['scope']),int(row['key']),c
        raise ValueError('Invalid verification')

    def complete_captcha(self, cid, uid):
        c = self.db.get(cid,'captcha',uid)
        if not c or c['status'] != 'pending' or c['expires'] <= time.time():
            raise ValueError('Verification expired or already used')
        if c['request']:
            self.bot_right(cid,'can_invite_users')
            self.tg.call('approveChatJoinRequest',chat_id=cid,user_id=uid)
        else:
            self.bot_right(cid,'can_restrict_members')
            prior = c['previous']
            defaults = self.tg.call('getChat',chat_id=cid).get('permissions',{})
            if prior.get('status') == 'restricted' and (not prior.get('until_date') or prior['until_date'] > time.time()):
                perms = {k: bool(prior.get(k,False) and defaults.get(k,False)) for k in PERMISSIONS}
                until = prior.get('until_date',0)
            else:
                perms,until = defaults,0
            self.tg.call('restrictChatMember',chat_id=cid,user_id=uid,permissions=perms,
                         until_date=0 if 0<until-time.time()<30 else until,use_independent_chat_permissions=True)
            if 0<until-time.time()<30:
                revision=secrets.token_hex(16)
                self.db.put(cid,'restore_revision',uid,revision)
                self.db.job(cid,'restore_permissions',until,{'user':uid,'revision':revision})
        c['status'] = 'verified'
        self.db.put(cid,'captcha',uid,c)
        self.db.delete(uid,'session','captcha')
        for chat, mid in c['prompts']:
            self.db.job(chat,'delete',time.time(),{'message_id':mid})
        self.audit(cid,uid,'verified')
        self.greet(c['chat'],c['user'],'welcome')

    def answer_captcha(self, cid, uid, answer):
        c = self.db.get(cid,'captcha',uid)
        if not c or c['status'] != 'pending' or c['expires'] <= time.time():
            raise ValueError('Verification expired')
        if c['attempts'] >= 5:
            raise ValueError('Too many attempts; contact an administrator')
        c['attempts'] += 1
        self.db.put(cid,'captcha',uid,c)
        if secrets.compare_digest(c['answer'],answer.strip().upper()):
            self.complete_captcha(cid,uid)
            return True
        return False

    def stats(self, chat):
        events = self.db.sql('SELECT user,kind,at,data FROM events WHERE chat=? ORDER BY at', (chat,))
        heatmap = [[0]*24 for _ in range(7)]
        days, people, logs = {}, {}, []
        zone = ZoneInfo(self.settings(chat)['timezone'])
        for e in events:
            dt = datetime.fromtimestamp(e['at'],zone)
            day = days.setdefault(dt.date().isoformat(),{'messages':0,'joins':0,'leaves':0})
            if e['kind'] == 'message':
                heatmap[dt.weekday()][dt.hour] += 1
                day['messages'] += 1
                people[str(e['user'])] = people.get(str(e['user']),0)+1
            elif e['kind'] in ('join','leave'):
                day['joins' if e['kind']=='join' else 'leaves'] += 1
            elif e['kind'] == 'mod':
                logs.append({'user':e['user'],'at':e['at'],**json.loads(e['data'])})
        return {'chat':chat,'timezone':str(zone),'messages':sum(people.values()),'active_users':len(people),
                'members':len(self.db.items(chat,'members')),'daily':days,'heatmap':heatmap,
                'users':people,'moderation':logs[-200:], 'retention_days':self.config.retention_days,
                'jobs':self.db.sql('SELECT id,kind,due,interval,status,error FROM jobs WHERE chat=? ORDER BY id DESC LIMIT 100',(chat,))}

    def target(self, m, args):
        replied = m.get('reply_to_message',{}).get('from',{})
        if replied:
            return replied['id'],args
        bits = args.split(maxsplit=1)
        if not bits or not bits[0].isdigit():
            raise ValueError('Reply to a member message or provide a numeric user ID')
        return int(bits[0]), bits[1] if len(bits)>1 else ''

    def dashboard_token(self, chat, user):
        self.require(chat,user,native=True)
        token = secrets.token_urlsafe(32)
        self.db.put('global','access',hashlib.sha256(token.encode()).hexdigest(),
                    {'chat':chat,'user':user,'expires':time.time()+3600})
        return token

    def command(self, m):
        cid,uid = m['chat']['id'],m['from']['id']
        raw = m['text'].split(maxsplit=1)
        addressed = raw[0].split('@')
        if len(addressed)>1 and addressed[1].lower() != self.me['username'].lower():
            return
        cmd = addressed[0][1:].lower()
        args = raw[1] if len(raw)>1 else ''
        private = m['chat']['type'] == 'private'
        if cmd in ('superadmin','announce','announce_send','announce_status','announce_cancel'):
            self.superadmin.command(m,cmd,args)
            return
        if cmd in ('start','help'):
            if private and args.startswith('verify_'):
                self.captcha_prompt(int(args[7:]),uid,cid)
                return
            self.say(cid,self.help_text(cid))
            if private and cmd == 'start':
                self.say(cid,'Bot operators may send service announcements here. /unsubscribe opts out; /subscribe opts in again.')
            return
        if private:
            if cmd == 'myid':
                self.say(cid, 'Your Telegram user ID: ' + str(uid))
                return
            if cmd == 'dashboard':
                chat = int(args)
                token = self.dashboard_token(chat,uid)
                url = (self.config.public_url or f'http://127.0.0.1:{self.config.port}') + '/#' + token
                self.say(cid,'Private dashboard link (expires in one hour):\n' + url)
                return
            if cmd in ('subscribe','unsubscribe','support','close','inbox','broadcast','blockuser'):
                self.support_command(m,cmd,args)
                return
            if cmd in ('channel','draft','draftedit','drafts','preview','publish','schedule','jobs','cancel','reschedule','buttons','posts','postedit','article','articles'):
                self.publisher(m,cmd,args)
                return
            raise ValueError('Use /help for private commands')
        if cmd in ('rules','settings','admins','info','stats','leaderboard','rep','warnings'):
            if cmd == 'rules':
                self.say(cid,self.settings(cid)['rules'],parse_mode='HTML')
            elif cmd == 'settings':
                self.require(cid,uid)
                self.say(cid,json.dumps(self.settings(cid),ensure_ascii=False,indent=2))
            elif cmd == 'admins':
                self.say(cid,'\n'.join(str(x['user']['id'])+' '+x['user'].get('first_name','') for x in self.tg.call('getChatAdministrators',chat_id=cid)))
            elif cmd == 'info':
                target,_ = self.target(m,args or str(uid))
                member = self.member(cid,target)
                self.say(cid,json.dumps({'id':target,'status':member['status'],**self.db.get(cid,'members',target,{})},ensure_ascii=False))
            elif cmd == 'warnings':
                target,_ = self.target(m,args or str(uid))
                warnings = [w for w in self.db.get(cid,'warnings',target,[]) if not w['expires'] or w['expires']>time.time()]
                self.say(cid,json.dumps(warnings,ensure_ascii=False))
            elif cmd == 'stats':
                st = self.stats(cid)
                self.say(cid,f"Messages: {st['messages']} | Active users: {st['active_users']}\nObserved members: {st['members']}\nPrivate /dashboard {cid} for charts (admins).")
            else:
                points = self.db.items(cid,'points')
                ranking = sorted(points.items(),key=lambda x:x[1]['xp' if cmd=='leaderboard' else 'rep'],reverse=True)[:20]
                self.say(cid,'\n'.join(f"{i+1}. {u}: XP {p['xp']} | reputation {p['rep']}" for i,(u,p) in enumerate(ranking)) or 'No activity yet.')
            return
        if cmd in ('upvote','report'):
            target,reason = self.target(m,args)
            if target == uid:
                raise ValueError('You cannot vote/report yourself')
            if self.member(cid,uid)['status'] in ('left','kicked') or self.member(cid,target)['status'] in ('left','kicked'):
                raise ValueError('Current members only')
            key = f'{cmd}:{uid}:{target}:{datetime.now().date()}'
            if self.db.get(cid,'limits',key):
                raise ValueError('Already submitted today for this member')
            self.db.put(cid,'limits',key,True)
            if cmd == 'upvote':
                p = self.db.get(cid,'points',target,{'xp':0,'rep':0,'last':0})
                p['rep'] += 1
                self.db.put(cid,'points',target,p)
                self.say(cid,'Reputation +1')
            else:
                rid = secrets.token_hex(4)
                self.db.put(cid,'reports',rid,{'from':uid,'target':target,'reason':reason[:500],
                    'message':m.get('reply_to_message',{}).get('message_id'), 'status':'open'})
                self.audit(cid,target,'report',report=rid,reporter=uid)
                self.say(cid,'Report recorded: ' + rid)
            return
        if cmd in ('warn','unwarn','resetwarns','mute','unmute','ban','unban','kick','restrict','verify','trust','untrust'):
            self.require(cid,uid,'moderate')
            target,rest = self.target(m,args)
            if cmd == 'warn':
                pieces = rest.split(maxsplit=1)
                ttl = duration(pieces[0]) if pieces and re.fullmatch(r'\d+[smhd]',pieces[0]) else None
                reason = pieces[1] if ttl is not None and len(pieces)>1 else ('' if ttl is not None else rest)
                n = self.warn(cid,target,ttl,reason)
                self.say(cid,f'Warning recorded ({n}).')
            elif cmd in ('unwarn','resetwarns'):
                warnings = self.db.get(cid,'warnings',target,[])
                self.db.put(cid,'warnings',target,warnings[:-1] if cmd=='unwarn' else [])
            elif cmd == 'verify':
                self.complete_captcha(cid,target)
            elif cmd in ('trust','untrust'):
                self.require(cid,uid,'config',native=True)
                self.db.put(cid,'trusted',target,cmd=='trust')
            elif cmd == 'restrict':
                seconds,rawperms = rest.split(maxsplit=1)
                self.moderate(cid,target,cmd,duration(seconds),permissions=json.loads(rawperms))
            else:
                bits = rest.split(maxsplit=1)
                seconds = duration(bits[0]) if bits and re.fullmatch(r'\d+[smhd]?',bits[0]) else 0
                self.moderate(cid,target,cmd,seconds,rest)
            return
        if cmd in ('set','lock','unlock','role','unrole','save','forget','rule','unrule','custom','uncustom'):
            self.require(cid,uid)
            if cmd == 'set':
                key,value = args.split(maxsplit=1)
                self.configure(cid,uid,key,json.loads(value))
            elif cmd in ('lock','unlock'):
                current = set(self.settings(cid)['locks'])
                names = set(args.split())
                self.configure(cid,uid,'locks',sorted(current|names if cmd=='lock' else current-names))
            elif cmd in ('role','unrole'):
                self.require(cid,uid,native=True)
                target,rest = self.target(m,args)
                caps = rest.split(',') if cmd=='role' else []
                if not set(caps) <= CAPS:
                    raise ValueError('Capabilities: ' + ','.join(sorted(CAPS)))
                self.db.put(cid,'roles',target,caps)
            elif cmd == 'save':
                bits = args.split(maxsplit=1)
                name = bits[0]
                content = self.capture(m.get('reply_to_message',{}), bits[1] if len(bits)>1 else '')
                if not content.get('text') and content['kind']=='text':
                    raise ValueError('Reply to content, or /save name text')
                self.db.put(cid,'notes',name,content)
            elif cmd in ('forget','unrule','uncustom'):
                self.db.delete(cid,{'forget':'notes','unrule':'rules','uncustom':'custom'}[cmd],args)
            elif cmd == 'rule':
                name,value = args.split(maxsplit=1)
                self.add_rule(cid,uid,name,json.loads(value))
            elif cmd == 'custom':
                name,note = args.split(maxsplit=1)
                if not re.fullmatch('[a-z][a-z0-9_]{0,31}',name):
                    raise ValueError('Invalid command name')
                if not self.db.get(cid,'notes',note):
                    raise ValueError('Save the note first')
                self.db.put(cid,'custom',name,note)
            self.say(cid,'Saved / സേവ് ചെയ്തു')
            return
        if cmd in ('get','notes'):
            if cmd == 'notes':
                self.say(cid,', '.join(self.db.items(cid,'notes')) or 'No notes')
            else:
                note = self.db.get(cid,'notes',args)
                if not note:
                    raise ValueError('Unknown note')
                self.send_content(cid,note,m['from'],m['chat'])
            return
        if cmd in ('delete','purge','pin','unpin','invite','revoke','reports','resolve'):
            cap = 'pin' if cmd in ('pin','unpin') else 'invite' if cmd in ('invite','revoke') else 'reports' if cmd in ('reports','resolve') else 'delete'
            self.require(cid,uid,cap)
            if cmd in ('delete','purge','pin','unpin'):
                mid = m.get('reply_to_message',{}).get('message_id')
                if not mid:
                    raise ValueError('Reply to the message')
                if cmd == 'delete':
                    self.delete_message(cid,mid)
                elif cmd == 'purge':
                    if not 0 <= m['message_id']-mid <= 99:
                        raise ValueError('Purge supports at most 100 messages per command')
                    self.bot_right(cid,'can_delete_messages')
                    self.tg.call('deleteMessages',chat_id=cid,message_ids=list(range(mid,m['message_id']+1)))
                else:
                    self.bot_right(cid,'can_pin_messages')
                    self.tg.call('pinChatMessage' if cmd=='pin' else 'unpinChatMessage',chat_id=cid,message_id=mid,**({'disable_notification':True} if cmd=='pin' else {}))
            elif cmd == 'invite':
                self.bot_right(cid,'can_invite_users')
                seconds = duration(args or '1d')
                result = self.tg.call('createChatInviteLink',chat_id=cid,expire_date=int(time.time()+seconds),creates_join_request=True)
                self.say(cid,result['invite_link'])
            elif cmd == 'revoke':
                self.bot_right(cid,'can_invite_users')
                self.tg.call('revokeChatInviteLink',chat_id=cid,invite_link=args)
            elif cmd == 'reports':
                self.say(cid,json.dumps(self.db.items(cid,'reports'),ensure_ascii=False))
            else:
                report = self.db.get(cid,'reports',args)
                if not report:
                    raise ValueError('Unknown report')
                report['status'] = 'resolved'
                self.db.put(cid,'reports',args,report)
            return
        if cmd.startswith('fed'):
            self.federation(m,cmd,args)
            return
        if cmd == 'setup':
            self.require(cid,uid,native=True)
            rights = self.member(cid,self.me['id'])
            self.say(cid,'Nexora setup / സജ്ജീകരണം\n' + '\n'.join(f'{k}: {bool(rights.get(k))}' for k in ('can_delete_messages','can_restrict_members','can_invite_users','can_pin_messages')) +
                '\n/set language "ml"\n/set captcha "button"\n/set rules "Your group rules"\n/lock links\n/settings\nPrivate: /dashboard ' + str(cid))
            return
        note = self.db.get(cid,'custom',cmd)
        if note and self.db.get(cid,'notes',note):
            self.send_content(cid,self.db.get(cid,'notes',note),m['from'],m['chat'])
        else:
            raise ValueError('Unknown command; /help')

    def help_text(self, cid):
        intro = 'Nexora — നിങ്ങളുടെ ഗ്രൂപ്പ്, പോസ്റ്റുകൾ, സപ്പോർട്ട് ഒരിടത്ത്.\n' if self.settings(cid)['language']=='ml' else 'Nexora — groups, publishing and support in one bot.\n'
        return intro + '''Group: /setup /rules /info /stats /leaderboard /rep /upvote /report
Moderation: /warn /warnings /unwarn /resetwarns /mute /unmute /ban /unban /kick /restrict /verify /trust /untrust
Config: /settings /set key JSON /lock /unlock /role /unrole
Content: /save name (reply) /get name /notes /forget /rule name JSON /unrule /custom command note /uncustom
Tools: /admins /delete /purge /pin /unpin /invite /revoke /reports /resolve
Federations: /fedcreate /fedjoin /fedleave /fedban /fedunban
Private: /dashboard CHAT_ID /support /subscribe /unsubscribe
Publishing (private): /channel CHAT_ID /draft /drafts /draftedit /preview /buttons /publish /schedule /jobs /cancel /reschedule /postedit /article /articles
Support admins: /inbox /close /blockuser /broadcast
Super admins (private): /superadmin /announce /announce_send /announce_status /announce_cancel
Private identity: /myid
See docs/COMMANDS.md for syntax and examples.''' + ('\n'+self.settings(cid)['help'] if self.settings(cid)['help'] else '')

    def federation(self,m,cmd,args):
        cid,uid = m['chat']['id'],m['from']['id']
        self.require(cid,uid,native=True)
        if cmd == 'fedcreate':
            fid = secrets.token_hex(6)
            self.db.put('global','fed',fid,{'owner':uid,'name':args[:100],'chats':[cid],'bans':{}})
            self.say(cid,'Federation ID: ' + fid)
            return
        bits = args.split(maxsplit=2)
        fed = self.db.get('global','fed',bits[0])
        if not fed:
            raise ValueError('Unknown federation')
        if cmd == 'fedjoin':
            if cid not in fed['chats']:
                fed['chats'].append(cid)
            for target, reason in fed['bans'].items():
                self.db.job(cid,'fedban',time.time(),{'user':int(target),'reason':reason,'fed':bits[0]})
        elif cmd == 'fedleave':
            fed['chats'] = [c for c in fed['chats'] if c != cid]
        elif cmd in ('fedban','fedunban'):
            if uid != fed['owner'] or cid not in fed['chats']:
                raise PermissionError('Only the federation owner, in a subscribed chat')
            target = int(bits[1])
            reason = bits[2] if len(bits)>2 else 'Federation moderation'
            if cmd == 'fedban':
                fed['bans'][str(target)] = reason
            else:
                fed['bans'].pop(str(target),None)
            for chat in fed['chats']:
                self.db.job(chat,cmd,time.time(),{'user':target,'reason':reason,'fed':bits[0]})
        else:
            raise ValueError('Unknown federation command')
        self.db.put('global','fed',bits[0],fed)
        self.say(cid,'Federation updated. Actions are queued; inspect /dashboard jobs for failures.')

    def support_allowed(self, m):
        return m['from']['id'] in self.config.support_admins and (
            m['chat']['id'] == self.config.support_chat or m['chat']['type'] == 'private')

    def support_command(self,m,cmd,args):
        uid,cid = m['from']['id'],m['chat']['id']
        if cmd in ('subscribe','unsubscribe'):
            self.db.put('support','subscribers',uid,cmd=='subscribe')
            self.say(cid,'Broadcast preference saved / അറിയിപ്പ് മുൻഗണന സേവ് ചെയ്തു')
        elif cmd == 'support':
            if not self.config.support_chat or not self.config.support_admins:
                raise ValueError('Support is not configured')
            self.db.put(uid,'session','support',True)
            self.say(cid,'Send your message or attachment. It will be shared with the configured support team. /close ends this conversation.')
        elif cmd == 'close' and not self.support_allowed(m):
            self.db.put(uid,'session','support',False)
            self.say(cid,'Support conversation closed.')
        else:
            if not self.support_allowed(m):
                raise PermissionError('Support admins only')
            if cmd == 'inbox':
                open_tickets = {k:v for k,v in self.db.items('support','tickets').items() if v['status']=='open'}
                self.say(cid,json.dumps(open_tickets,ensure_ascii=False))
            elif cmd == 'close':
                t = self.db.get('support','tickets',args)
                if not t:
                    raise ValueError('Unknown ticket')
                t['status'] = 'closed'
                self.db.put('support','tickets',args,t)
                self.db.put(t['user'],'session','support',False)
                self.say(cid,'Ticket closed')
            elif cmd == 'blockuser':
                who,state = args.split()
                if state not in ('on','off'):
                    raise ValueError('Use /blockuser USER_ID on|off')
                self.db.put('support','blocked',int(who),state=='on')
            elif cmd == 'broadcast':
                if not m.get('reply_to_message'):
                    raise ValueError('Reply to the broadcast content; recipients must use /subscribe first')
                content = self.capture(m['reply_to_message'])
                count = 0
                for target,opt in self.db.items('support','subscribers').items():
                    if opt and not self.db.get('support','blocked',target,False):
                        self.db.job(int(target),'broadcast',time.time()+count*2,{'content':content,'actor':uid})
                        count += 1
                self.say(cid,f'Queued for {count} opted-in users.')

    def relay(self,m):
        cid,uid = m['chat']['id'],m['from']['id']
        if cid == self.config.support_chat:
            if not self.support_allowed(m):
                return
            if m.get('text','').split(' ',1)[0] in ('/inbox','/close','/blockuser','/broadcast'):
                cmd,*args = m['text'].split(maxsplit=1)
                self.support_command(m,cmd[1:],args[0] if args else '')
                return
            reply = m.get('reply_to_message',{}).get('message_id')
            ticket_id = self.db.get('support','relay',reply) if reply else None
            if ticket_id:
                ticket = self.db.get('support','tickets',ticket_id)
                if ticket and ticket['status']=='open' and not self.db.get('support','blocked',ticket['user'],False):
                    self.tg.call('copyMessage',chat_id=ticket['user'],from_chat_id=cid,message_id=m['message_id'])
                    self.db.event(0,uid,'support_reply',{'ticket':ticket_id})
            return
        if m['chat']['type'] != 'private' or not self.db.get(uid,'session','support',False):
            return
        if not self.config.support_chat or self.db.get('support','blocked',uid,False):
            return
        last = self.db.get('support','last',uid,0)
        if time.time()-last<2:
            raise ValueError('Please wait before sending another support message')
        self.db.put('support','last',uid,time.time())
        tid = self.db.get('support','active',uid)
        ticket = self.db.get('support','tickets',tid) if tid else None
        if not ticket or ticket['status'] != 'open':
            tid = secrets.token_hex(5)
            ticket = {'user':uid,'status':'open','created':time.time()}
            self.db.put('support','tickets',tid,ticket)
            self.db.put('support','active',uid,tid)
        header = self.say(self.config.support_chat,f'Ticket {tid} | user {uid}\nReply to this header or the copied message.')
        self.db.put('support','relay',header['message_id'],tid)
        copied = self.tg.call('copyMessage',chat_id=self.config.support_chat,from_chat_id=cid,message_id=m['message_id'])
        self.db.put('support','relay',copied['message_id'],tid)
        self.say(cid,'Sent to support / സപ്പോർട്ടിലേക്ക് അയച്ചു')

    def publisher(self,m,cmd,args):
        uid,cid = m['from']['id'],m['chat']['id']
        if cmd == 'channel':
            target = int(args)
            self.require(target,uid,'publish',native=True)
            chat = self.tg.call('getChat',chat_id=target)
            self.bot_right(target,'can_post_messages' if chat['type']=='channel' else 'can_delete_messages')
            self.db.put(uid,'session','channel',target)
            self.db.put(uid,'channels',target,chat.get('title',str(target)))
            self.say(cid,'Selected destination: ' + str(target))
            return
        target = self.db.get(uid,'session','channel')
        if not target:
            raise ValueError('Select a destination first: /channel CHAT_ID')
        self.require(target,uid,'publish',native=True)
        scope = 'publisher:' + str(uid) + ':' + str(target)
        bits = args.split(maxsplit=1)
        name = bits[0] if bits else ''
        rest = bits[1] if len(bits)>1 else ''
        if cmd in ('draft','draftedit'):
            if not name:
                raise ValueError('/draft NAME text, or reply to content')
            content = self.capture(m.get('reply_to_message',{}),rest)
            if not content.get('text') and content['kind']=='text':
                raise ValueError('Supply content')
            # Snapshot content, never import executable settings from forwarded messages.
            self.db.put(scope,'drafts',name,content)
            self.say(cid,'Draft saved: ' + name)
        elif cmd == 'drafts':
            self.say(cid,', '.join(self.db.items(scope,'drafts')) or 'No drafts')
        elif cmd in ('preview','buttons','publish','schedule'):
            draft = self.db.get(scope,'drafts',name)
            if not draft:
                raise ValueError('Unknown draft')
            if cmd == 'buttons':
                buttons = json.loads(rest)
                if not isinstance(buttons,list) or len(buttons)>10:
                    raise ValueError('Use at most 10 rows of buttons')
                for row in buttons:
                    if not isinstance(row,list) or len(row)>8:
                        raise ValueError('At most 8 buttons per row')
                    for button in row:
                        if set(button) != {'text','url'} or not isinstance(button['text'],str) or not 1<=len(button['text'])<=64 or not isinstance(button['url'],str) or urlparse(button['url']).scheme not in ('https','http','tg'):
                            raise ValueError('Each button needs text and an http(s)/tg URL')
                draft['buttons'] = buttons
                self.db.put(scope,'drafts',name,draft)
            elif cmd == 'preview':
                self.send_content(cid,draft)
            else:
                options = rest.split()
                due = time.time()
                interval = 0
                silent = 'silent' in options
                if cmd == 'schedule':
                    if not options:
                        raise ValueError('/schedule NAME 2026-10-01T09:00:00+01:00 [every=1d] [silent]')
                    due = scheduled_time(options[0],self.settings(target)['timezone'])
                    if due <= time.time():
                        raise ValueError('Schedule must be in the future')
                    for option in options[1:]:
                        if option.startswith('every='):
                            interval = duration(option[6:])
                            if interval<60:
                                raise ValueError('Minimum recurrence is 60 seconds')
                job = self.db.job(target,'publish',due,{'actor':uid,'scope':scope,'draft':name,'content':draft,'silent':silent},interval)
                self.say(cid,f'Queued job {job}. Scheduled content is a snapshot; /reschedule refreshes it.')
        elif cmd == 'jobs':
            jobs = []
            for row in self.db.sql("SELECT * FROM jobs WHERE chat=? AND kind='publish' ORDER BY id DESC LIMIT 100",(target,)):
                if json.loads(row['payload']).get('actor')==uid:
                    jobs.append({k:row[k] for k in ('id','due','interval','status','error')})
            self.say(cid,json.dumps(jobs,indent=2))
        elif cmd in ('cancel','reschedule'):
            rows = self.db.sql('SELECT * FROM jobs WHERE id=? AND chat=?',(int(name),target))
            if not rows or json.loads(rows[0]['payload']).get('actor')!=uid:
                raise PermissionError('This is not your job')
            if cmd == 'cancel':
                self.db.sql("UPDATE jobs SET status='cancelled' WHERE id=? AND status='pending'",(int(name),))
            else:
                if rows[0]['status'] != 'pending':
                    raise ValueError('Only pending jobs can be rescheduled')
                due = scheduled_time(rest,self.settings(target)['timezone'])
                if due <= time.time():
                    raise ValueError('Schedule must be in the future')
                p = json.loads(rows[0]['payload'])
                draft = self.db.get(scope,'drafts',p['draft'])
                if not draft:
                    raise ValueError('Draft no longer exists')
                p['content'] = draft
                self.db.sql('UPDATE jobs SET due=?,payload=? WHERE id=?',(due,json.dumps(p),int(name)))
        elif cmd == 'posts':
            self.say(cid,json.dumps(self.db.items(scope,'posts'),ensure_ascii=False))
        elif cmd == 'postedit':
            post = self.db.get(scope,'posts',name)
            if not post:
                raise PermissionError('Unknown post in your selected destination')
            content = self.capture(m.get('reply_to_message',{}),rest)
            if content['kind']=='text':
                key = 'caption' if post['kind']!='text' else 'text'
                p = {key:content['text']}
                if content.get('entities'):
                    p['caption_entities' if key=='caption' else 'entities'] = content['entities']
                self.tg.call('editMessageCaption' if key=='caption' else 'editMessageText',chat_id=target,message_id=int(name),**p)
            elif content['kind'] in ('photo','video','animation','audio','document'):
                media = {'type':content['kind'],'media':content['file_id'],'caption':content.get('text',''),
                         'caption_entities':content.get('entities',[])}
                self.tg.call('editMessageMedia',chat_id=target,message_id=int(name),media=media)
            else:
                raise ValueError('This media type cannot be edited')
            self.say(cid,'Post edited')
        elif cmd in ('article','articles'):
            self.telegraph(scope,cmd,args,cid)

    def telegraph(self,scope,cmd,args,reply_chat):
        if cmd == 'articles':
            self.say(reply_chat,json.dumps(self.db.items(scope,'articles'),ensure_ascii=False))
            return
        # Format: /article NAME {"title":"...","content":[Telegraph nodes]}
        name,raw = args.split(maxsplit=1)
        value = json.loads(raw)
        if not isinstance(value.get('title'),str) or not 1<=len(value['title'])<=256 or not isinstance(value.get('content'),list):
            raise ValueError('Article needs title and a content node list')
        if len(json.dumps(value['content']).encode())>64000:
            raise ValueError('Article content is too large')
        token = self.db.get(scope,'telegraph','token')
        if not token:
            result = request_json('https://api.telegra.ph/createAccount',{'short_name':'Nexora','author_name':'Nexora'})
            if not result.get('ok'):
                raise RemoteError()
            token = result['result']['access_token']
            self.db.put(scope,'telegraph','token',token)
        old = self.db.get(scope,'articles',name)
        payload = {'access_token':token,'title':value['title'],'content':value['content'],'return_content':False}
        if old:
            payload['path'] = old['path']
        result = request_json('https://api.telegra.ph/' + ('editPage' if old else 'createPage'),payload)
        if not result.get('ok'):
            raise RemoteError()
        page = result['result']
        self.db.put(scope,'articles',name,{'path':page['path'],'url':page['url'],'title':page['title']})
        self.say(reply_chat,page['url'])

    def tick(self):
        """Persistent scheduler, serialized with updates/HTTP using db.lock by caller."""
        now = time.time()
        for j in self.db.sql("SELECT * FROM jobs WHERE status='pending' AND due<=? ORDER BY due LIMIT 10",(now,)):
            self.db.sql("UPDATE jobs SET status='running' WHERE id=? AND status='pending'",(j['id'],))
            p = json.loads(j['payload'])
            try:
                kind,cid = j['kind'],j['chat']
                if kind == 'delete':
                    self.tg.call('deleteMessage',chat_id=cid,message_id=p['message_id'])
                elif kind == 'captcha_expire':
                    c = self.db.get(cid,'captcha',p['user'])
                    if c and c['token']==p['token'] and c['status']=='pending':
                        if c['request']:
                            self.bot_right(cid,'can_invite_users')
                            self.tg.call('declineChatJoinRequest',chat_id=cid,user_id=p['user'])
                        else:
                            self.moderate(cid,p['user'],'kick',reason='Verification timeout')
                        c['status']='expired'
                        self.db.put(cid,'captcha',p['user'],c)
                        for dest,mid in c['prompts']:
                            self.db.job(dest,'delete',time.time(),{'message_id':mid})
                elif kind == 'restore_permissions':
                    if self.db.get(cid,'restore_revision',p['user'])==p['revision']:
                        self.moderate(cid,p['user'],'unmute',reason='Previous restriction expired')
                elif kind in ('fedban','fedunban'):
                    fed = self.db.get('global','fed',p['fed'])
                    active = fed and cid in fed['chats']
                    wanted = fed and str(p['user']) in fed['bans']
                    if active and (wanted if kind=='fedban' else not wanted):
                        if kind=='fedban':
                            if self.member(cid,p['user'])['status']!='kicked':
                                self.moderate(cid,p['user'],'ban',reason=p['reason'])
                                self.db.put(cid,'ban_source',p['user'],p['fed'])
                        elif self.db.get(cid,'ban_source',p['user'])==p['fed']:
                            others = [fid for fid,f in self.db.items('global','fed').items() if cid in f['chats'] and str(p['user']) in f['bans']]
                            if others:
                                self.db.put(cid,'ban_source',p['user'],others[0])
                            else:
                                self.moderate(cid,p['user'],'unban',reason=p['reason'])
                elif kind == 'publish':
                    self.require(cid,p['actor'],'publish',native=True)
                    chat = self.tg.call('getChat',chat_id=cid)
                    self.bot_right(cid,'can_post_messages' if chat['type']=='channel' else 'can_delete_messages')
                    sent = self.send_content(cid,p['content'],silent=p.get('silent',False))
                    self.db.put(p['scope'],'posts',sent['message_id'],{'kind':p['content']['kind'],'job':j['id']})
                    self.db.event(cid,p['actor'],'published',{'message':sent['message_id'],'job':j['id']})
                elif kind == 'broadcast':
                    if p['actor'] in self.config.support_admins and self.db.get('support','subscribers',cid,False) and not self.db.get('support','blocked',cid,False):
                        self.send_content(cid,p['content'])
                elif kind == 'super_broadcast':
                    self.superadmin.deliver(cid,p)
                else:
                    raise ValueError('Unknown job type')
                if j['interval']:
                    # Skip missed runs; recurrence is an elapsed UTC interval, not a local wall clock.
                    due = j['due'] + (int((time.time()-j['due'])//j['interval'])+1)*j['interval']
                    self.db.sql("UPDATE jobs SET status='pending',due=? WHERE id=?",(due,j['id']))
                else:
                    self.db.sql("UPDATE jobs SET status='done' WHERE id=?",(j['id'],))
            except RemoteError as exc:
                if exc.code==429 and exc.retry_after:
                    self.db.sql("UPDATE jobs SET status='pending',due=?,error='Rate limited' WHERE id=?",(time.time()+exc.retry_after+1,j['id']))
                else:
                    # A transport timeout may follow a successful send. Never blindly duplicate a post.
                    status = 'uncertain' if exc.code==0 else 'failed'
                    self.db.sql('UPDATE jobs SET status=?,error=? WHERE id=?',(status,str(exc),j['id']))
            except (ValueError,PermissionError,KeyError) as exc:
                self.db.sql("UPDATE jobs SET status='failed',error=? WHERE id=?",(str(exc)[:300],j['id']))

    def handle(self,update):
        if 'callback_query' in update:
            q = update['callback_query']
            try:
                if q.get('data','').startswith('v:'):
                    cid,uid,c = self.find_captcha(q['data'][2:])
                    if q['from']['id'] != uid or c['mode'] not in ('button','private'):
                        raise PermissionError('This challenge belongs to another member')
                    self.complete_captcha(cid,uid)
                self.tg.call('answerCallbackQuery',callback_query_id=q['id'],text='Verified')
            except (ValueError,PermissionError) as exc:
                self.tg.call('answerCallbackQuery',callback_query_id=q['id'],text=str(exc)[:180],show_alert=True)
            return
        if 'chat_join_request' in update:
            r = update['chat_join_request']
            self.start_captcha(r['chat'],r['from'],request=True,private_chat=r.get('user_chat_id'))
            return
        member_update = update.get('chat_member') or update.get('my_chat_member')
        if member_update:
            cid = member_update['chat']['id']
            self.superadmin.remember(member_update['chat'])
            old,new = member_update['old_chat_member'],member_update['new_chat_member']
            if member_update.get('from',{}).get('id')!=self.me['id'] and new['status'] in ('restricted','kicked'):
                self.db.delete(cid,'restore_revision',new['user']['id'])
                c=self.db.get(cid,'captcha',new['user']['id'])
                if c and c['status']=='pending':
                    c['status']='cancelled'
                    self.db.put(cid,'captcha',new['user']['id'],c)
            was_in = old['status'] in ('member','administrator','creator') or (old['status']=='restricted' and old.get('is_member'))
            is_in = new['status'] in ('member','administrator','creator') or (new['status']=='restricted' and new.get('is_member'))
            if was_in and not is_in:
                self.left(member_update['chat'],new['user'])
            elif is_in and not was_in:
                self.joined(member_update['chat'],new['user'])
            return
        m = update.get('message') or update.get('edited_message')
        if not m:
            return
        cid = m['chat']['id']
        if 'migrate_to_chat_id' in m:
            self.db.migrate(cid,m['migrate_to_chat_id'])
            return
        if 'migrate_from_chat_id' in m:
            # migrate_to is the authoritative event; avoid double migration.
            if self.db.items(m['migrate_from_chat_id'],'config'):
                self.db.migrate(m['migrate_from_chat_id'],cid)
            return
        if 'new_chat_members' in m:
            for user in m['new_chat_members']:
                self.joined(m['chat'],user)
            if self.settings(cid)['cleanup_service']:
                self.delete_message(cid,m['message_id'])
            return
        if 'left_chat_member' in m:
            self.left(m['chat'],m['left_chat_member'])
            if self.settings(cid)['cleanup_service']:
                self.delete_message(cid,m['message_id'])
            return
        # Anonymous sender_chat posts never inherit the anonymous admin placeholder's privileges.
        if not m.get('from') or m.get('sender_chat'):
            return
        self.superadmin.remember(m['chat'], m['from'])
        uid = m['from']['id']
        if cid == self.config.support_chat:
            if 'edited_message' not in update:
                self.relay(m)
            return
        if m['chat']['type']=='private':
            if 'edited_message' in update:
                return
            if m.get('text','').startswith('/'):
                self.command(m)
            else:
                verify_chat = self.db.get(uid,'session','captcha')
                if verify_chat:
                    ok = self.answer_captcha(verify_chat,uid,m.get('text',''))
                    self.say(cid,'Verified / പരിശോധിച്ചു' if ok else 'Try again / വീണ്ടും ശ്രമിക്കുക')
                else:
                    self.relay(m)
            return
        pending = self.db.get(cid,'captcha',uid)
        if pending and pending['status']=='pending' and self.settings(cid)['strict']:
            self.delete_message(cid,m['message_id'])
            return
        # Run locks/rules before dispatch, so commands and edited captions cannot bypass moderation.
        if self.apply_rules(m):
            return
        if 'edited_message' in update:
            return
        self.db.event(cid,uid,'message')
        member = self.db.get(cid,'members',uid,{})
        member.update({'name':m['from'].get('first_name',''),'last_seen':time.time()})
        self.db.put(cid,'members',uid,member)
        if self.settings(cid)['xp']:
            p = self.db.get(cid,'points',uid,{'xp':0,'rep':0,'last':0})
            if time.time()-p['last']>=60:
                p['xp'] += 1
                p['last'] = time.time()
                self.db.put(cid,'points',uid,p)
        if m.get('text','').startswith('/'):
            self.command(m)

    def joined(self,chat,user):
        cid,uid = chat['id'],user['id']
        if uid == self.me['id']:
            return
        old = self.db.get(cid,'members',uid,{})
        if old.get('joined',0)>time.time()-20:
            return
        self.db.put(cid,'members',uid,{'joined':time.time(),'name':user.get('first_name','')})
        self.db.event(cid,uid,'join')
        verified = self.db.get(cid,'captcha',uid)
        if verified and verified.get('request') and verified['status']=='verified' and verified['expires']>time.time()-120:
            return
        self.start_captcha(chat,user)

    def left(self,chat,user):
        cid,uid = chat['id'],user['id']
        if not self.db.get(cid,'members',uid):
            return
        self.db.delete(cid,'members',uid)
        self.db.event(cid,uid,'leave')
        self.greet(chat,user,'goodbye')

    def process(self,update):
        """Durable deduplication; failed/uncertain updates are visible and not auto-replayed."""
        uid = update['update_id']
        old = self.db.sql('SELECT status FROM updates WHERE id=?',(uid,))
        if old and old[0]['status']!='pending':
            return
        self.db.sql('INSERT OR IGNORE INTO updates(id,payload) VALUES(?,?)',(uid,json.dumps(update)))
        self.db.sql("UPDATE updates SET status='running' WHERE id=?",(uid,))
        try:
            self.handle(update)
        except (ValueError,PermissionError,KeyError,TypeError,IndexError) as exc:
            self.db.sql("UPDATE updates SET status='failed',error=? WHERE id=?",(type(exc).__name__,uid))
            m = update.get('message',{})
            if m and m.get('text','').startswith('/'):
                text = str(exc) if isinstance(exc,(ValueError,PermissionError)) else 'Invalid command syntax; see /help and docs/COMMANDS.md'
                try:
                    self.say(m['chat']['id'],text)
                except RemoteError:
                    pass
            return
        except RemoteError as exc:
            self.db.sql("UPDATE updates SET status='uncertain',error=? WHERE id=?",(str(exc),uid))
            return
        self.db.sql("UPDATE updates SET status='done',payload='{}' WHERE id=?",(uid,))
