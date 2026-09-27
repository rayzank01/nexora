"""Persisted publishing, community events, support and personal-data operations."""
from . import plans
import json
import secrets
import time
from .calendar import next_run, local_label


class Operations:
    def __init__(self, extension):
        self.x, self.e = extension, extension.e

    @property
    def db(self):
        return self.e.db

    def calendar(self, chat, user):
        self.e.require(chat, user, 'publish', native=True)
        zone = self.e.settings(chat)['timezone']
        result = []
        for row in self.db.sql("SELECT * FROM jobs WHERE chat=? AND kind='publish' ORDER BY due LIMIT 300", (chat,)):
            p = json.loads(row['payload'])
            if p.get('actor') == user:
                result.append({k: row[k] for k in ('id', 'status', 'due', 'interval')} | {
                    'local': local_label(row['due'], zone), 'draft': p.get('draft'), 'recurrence': p.get('wallclock')})
        return result

    def recurring(self, chat, user, draft, clock, days):
        self.e.require(chat, user, 'publish', native=True)
        scope = f'publisher:{user}:{chat}'
        content = self.db.get(scope, 'drafts', draft)
        if not content:
            raise ValueError('Unknown draft in this destination')
        plans.job(self.e,chat,True)
        spec = {'zone': self.e.settings(chat)['timezone'], 'time': clock, 'days': days}
        due = next_run(spec, time.time())
        return self.db.job(chat, 'publish', due, {'actor': user, 'scope': scope, 'draft': draft,
            'content': content, 'wallclock': spec})

    def edit_job(self, chat, user, job, action, due=None):
        self.e.require(chat, user, 'publish', native=True)
        rows = self.db.sql("SELECT * FROM jobs WHERE id=? AND chat=? AND kind='publish'", (job, chat))
        if not rows or json.loads(rows[0]['payload']).get('actor') != user:
            raise PermissionError('This is not your publishing job')
        if rows[0]['status'] != 'pending':
            raise ValueError('Only pending jobs may be changed')
        if action == 'cancel':
            self.db.sql("UPDATE jobs SET status='cancelled' WHERE id=?", (job,))
        elif action == 'move':
            if not due or due <= time.time():
                raise ValueError('Choose a future date')
            payload = json.loads(rows[0]['payload'])
            # Deliberate date edit becomes one-off. Recurrence is configured separately.
            payload.pop('wallclock', None)
            self.db.sql('UPDATE jobs SET due=?,interval=0,payload=? WHERE id=?', (due, json.dumps(payload), job))
        else:
            raise ValueError('Unknown calendar action')

    def album(self, m, name):
        user = m['from']['id']
        chat = self.db.get(user, 'session', 'channel')
        self.e.require(chat, user, 'publish', native=True)
        plans.require(self.e,chat)
        reply = m.get('reply_to_message', {})
        group = reply.get('media_group_id')
        items = self.db.get(user, 'albums', group, {}) if group else {}
        media = [v for _,v in sorted(items.items(), key=lambda p: int(p[0]))]
        if not 2 <= len(media) <= 10:
            raise ValueError('Send an album of 2–10 photos/videos to this private chat, then reply /album NAME')
        self.db.put(f'publisher:{user}:{chat}', 'drafts', name[:40], {'kind': 'album', 'media': media})

    def observe_album(self, m):
        if m['chat']['type'] != 'private' or not m.get('media_group_id'):
            return False
        content = self.e.capture(m)
        if content['kind'] not in ('photo','video'):
            return False
        group = m['media_group_id']
        entries = self.db.get(m['from']['id'], 'albums', group, {})
        if len(entries) < 10:
            entries[str(m['message_id'])] = {'type': content['kind'], 'media': content['file_id'],
                'caption': content.get('text', ''), 'caption_entities': content.get('entities', [])}
            self.db.put(m['from']['id'], 'albums', group, entries)
        return True

    def event(self, chat, user, title, at, event_id=None):
        self.e.require(chat, user, native=True)
        if not 1 <= len(title) <= 200 or at <= time.time():
            raise ValueError('An event needs a title and future date')
        key = event_id or secrets.token_hex(5)
        old = self.db.get(chat, 'community_events', key)
        if event_id and not old:
            raise ValueError('Unknown event')
        active=sum(v.get('status')=='active' and v.get('at',0)>time.time() for k,v in self.db.items(chat,'community_events').items() if k!=key)
        plans.count(self.e,chat,'events',active+1)
        event = {'title': title, 'at': at, 'actor': user, 'revision': secrets.token_hex(5),
                 'status': 'active', 'rsvp': (old or {}).get('rsvp', {})}
        self.db.put(chat, 'community_events', key, event)
        self.db.job(chat, 'community_reminder', max(time.time(), at-3600), {'event': key, 'revision': event['revision']})
        return key

    def event_card(self, chat, dest, key):
        event = self.db.get(chat, 'community_events', key)
        if not event or event['status'] != 'active':
            raise ValueError('Event is unavailable')
        token = self.x.token(dest, 0, chat, 'rsvp', {'event': key, 'revision': event['revision']}, ttl=max(1, min(604800, event['at']-time.time())), reusable=True)
        self.e.say(dest, event['title'] + '\n' + local_label(event['at'], self.e.settings(chat)['timezone']),
            reply_markup={'inline_keyboard': [[{'text': self.x.tr(dest, 'RSVP / withdraw'), 'callback_data': token}]]})

    def rsvp(self, chat, user, p):
        event = self.db.get(chat, 'community_events', p['event'])
        if not event or event['status'] != 'active' or event['revision'] != p['revision'] or event['at'] <= time.time():
            raise ValueError('Event changed or ended')
        if self.e.member(chat, user)['status'] in ('left', 'kicked'):
            raise PermissionError('Current group membership required')
        key = str(user)
        if key in event['rsvp']:
            event['rsvp'].pop(key)
        else:
            event['rsvp'][key] = time.time()
        self.db.put(chat, 'community_events', p['event'], event)

    def poll(self, chat, user, question, answers, correct=None):
        self.e.require(chat, user, 'publish', native=True)
        if not 1 <= len(question) <= 300 or not 2 <= len(answers) <= 10 or any(not a or len(a) > 100 for a in answers):
            raise ValueError('Use a question and 2–10 short answers')
        if correct is not None and not 0 <= correct < len(answers):
            raise ValueError('Invalid correct answer index')
        kwargs = {'type': 'quiz', 'correct_option_id': correct} if correct is not None else {'type': 'regular'}
        result = self.e.tg.call('sendPoll', chat_id=chat, question=question,
            options=[{'text': a} for a in answers], is_anonymous=True, **kwargs)
        self.db.put(chat, 'community_polls', result['message_id'], {'actor': user, 'at': time.time(), 'question': question})

    def ticket(self, user, key, action, value=None):
        if user not in self.e.config.support_admins:
            raise PermissionError('Support staff access required')
        ticket = self.db.get('support', 'tickets', key)
        if not ticket:
            raise ValueError('Unknown ticket')
        if action == 'assign':
            if int(value) not in self.e.config.support_admins:
                raise ValueError('Assignee must be current support staff')
            ticket['assignee'] = int(value)
        elif action == 'priority':
            if value not in ('low','normal','high','urgent'):
                raise ValueError('Invalid priority')
            ticket['priority'] = value
        elif action == 'note':
            if not value or len(value) > 2000:
                raise ValueError('Note must be 1–2000 characters')
            notes = ticket.setdefault('notes', [])
            notes.append({'staff': user, 'at': time.time(), 'text': value})
            ticket['notes'] = notes[-100:]
        elif action == 'close':
            ticket['status'] = 'closed'
            self.db.put(ticket['user'], 'session', 'support', False)
        else:
            raise ValueError('Unknown ticket action')
        self.db.put('support', 'tickets', key, ticket)

    def support_received(self, tid):
        ticket = self.db.get('support', 'tickets', tid)
        ticket['last_inbound'] = time.time()
        ticket.setdefault('priority', 'normal')
        self.db.put('support', 'tickets', tid, ticket)
        self.db.job(self.e.config.support_chat, 'ticket_reminder', time.time()+3600,
            {'ticket': tid, 'inbound': ticket['last_inbound']})

    def support_replied(self, tid):
        ticket = self.db.get('support', 'tickets', tid)
        ticket['last_reply'] = time.time()
        ticket.setdefault('first_response_seconds', time.time()-ticket['created'])
        self.db.put('support', 'tickets', tid, ticket)

    def personal(self, user, delete=False):
        """Never export group content, staff notes, access tokens or other members' identities."""
        result = {'user': user, 'groups': {}, 'tickets': {}, 'limits':
            'Telegram copies and operator backups are separate. Active safety restrictions, bans and moderation evidence may be retained.'}
        result['drafts']={row['scope']:self.db.items(row['scope'],'drafts') for row in
            self.db.sql("SELECT DISTINCT scope FROM docs WHERE scope LIKE ? AND kind='drafts'",(f'publisher:{user}:%',))}
        result['activity']=self.db.sql("SELECT chat,kind,at FROM events WHERE user=? AND kind IN ('message','join','leave') ORDER BY at DESC LIMIT 1000",(user,))
        result['activity_limit']=1000
        own = ('members','points','trusted','warnings','privacy_requests')
        for row in self.db.sql('SELECT scope,kind,key,value FROM docs WHERE key=?', (str(user),)):
            if row['kind'] in own and row['scope'].startswith('-'):
                value = json.loads(row['value'])
                if row['kind'] in ('members','points'):
                    result['groups'].setdefault(row['scope'], {})[row['kind']] = value
                    if delete:
                        self.db.delete(row['scope'], row['kind'], user)
        for key, ticket in self.db.items('support', 'tickets').items():
            if ticket['user'] == user:
                result['tickets'][key] = {k: ticket[k] for k in ('created','status','priority','first_response_seconds') if k in ticket}
                if delete:
                    self.db.delete('support','tickets',key)
                    for mid, tid in self.db.items('support','relay').items():
                        if tid == key:
                            self.db.delete('support','relay',mid)
        result['community_tickets']={}
        for row in self.db.sql("SELECT scope,key,value FROM docs WHERE scope LIKE 'community:%' AND kind='tickets'"):
            ticket=json.loads(row['value'])
            if ticket['user']!=user:continue
            result['community_tickets'][row['scope']+':'+row['key']]={k:ticket[k] for k in ('created','status','priority','first_response_seconds') if k in ticket}
            if delete:
                self.db.delete(row['scope'],'tickets',row['key'])
                self.db.delete(row['scope'],'active',user)
                self.db.delete(row['scope'],'last',user)
                for mid,key in self.db.items(row['scope'],'relay').items():
                    if key==row['key']:self.db.delete(row['scope'],'relay',mid)
        if delete:
            self.db.sql('DELETE FROM events WHERE user=? AND kind NOT IN (\'mod\')', (user,))
            self.db.sql('DELETE FROM docs WHERE scope=?', (str(user),))
            self.db.sql('DELETE FROM docs WHERE scope LIKE ?', (f'publisher:{user}:%',))
            self.db.delete('global','broadcast_users',user)
            self.db.put('support','subscribers',user,False)
            self.db.delete('support','last',user)
            self.db.delete('support','active',user)
            self.db.put('privacy','no_ai',user,True)
            for row in self.db.sql("SELECT scope,kind,key,value FROM docs WHERE kind IN ('ai_messages','community_events','campaigns','ui_tokens','ui_inputs','access','web_changes')"):
                value = json.loads(row['value'])
                if row['kind'] == 'community_events':
                    value.get('rsvp', {}).pop(str(user), None)
                    self.db.put(row['scope'], row['kind'], row['key'], value)
                elif row['kind'] == 'campaigns':
                    if value.get('owner')==user:
                        self.db.delete(row['scope'],row['kind'],row['key'])
                        continue
                    value['targets'] = [t for t in value.get('targets', []) if t['chat'] != user]
                    self.db.put(row['scope'], row['kind'], row['key'], value)
                elif value.get('user') == user:
                    self.db.delete(row['scope'], row['kind'], row['key'])
            # Do not replay queued private deliveries to a deleted recipient.
            self.db.sql("UPDATE jobs SET status='cancelled',payload='{}' WHERE chat=? AND status='pending'", (user,))
            for job in self.db.sql("SELECT id,payload FROM jobs WHERE kind IN ('publish','super_broadcast','broadcast') AND status='pending'"):
                if json.loads(job['payload']).get('actor')==user:
                    self.db.sql("UPDATE jobs SET status='cancelled',payload='{}' WHERE id=?",(job['id'],))
        return result

    def job(self, kind, chat, p):
        if kind == 'community_reminder':
            event = self.db.get(chat, 'community_events', p['event'])
            if event and event['status'] == 'active' and event['revision'] == p['revision'] and event['at'] > time.time():
                self.e.require(chat, event['actor'], native=True)
                self.event_card(chat, chat, p['event'])
        elif kind == 'ticket_reminder':
            ticket = self.db.get('support','tickets',p['ticket'])
            if ticket and ticket['status']=='open' and ticket.get('last_inbound') == p['inbound'] and ticket.get('last_reply',0) < p['inbound']:
                self.e.say(self.e.config.support_chat, 'Unresolved support ticket: '+p['ticket'])
        else:
            return False
        return True
