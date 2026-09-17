"""Operator-only broadcasts to observed destinations, with preview and durable jobs."""
import json
import secrets
import time

from .transport import RemoteError


class SuperAdminBroadcasts:
    def __init__(self, engine):
        self.e = engine

    def allowed(self, user):
        return user in getattr(self.e.config, 'super_admins', set())

    def remember(self, chat, user=None):
        if chat.get('type') in ('group', 'supergroup'):
            self.e.db.put('global', 'broadcast_groups', chat['id'], {'title': chat.get('title', ''), 'seen': time.time()})
        elif chat.get('type') == 'private' and user and user.get('id') == chat['id'] and not user.get('is_bot'):
            self.e.db.put('global', 'broadcast_users', chat['id'], {'seen': time.time()})

    def eligible(self, chat, kind):
        if kind == 'user':
            return bool(self.e.db.get('global', 'broadcast_users', chat)) and \
                self.e.db.get('support', 'subscribers', chat) is not False and \
                not self.e.db.get('support', 'blocked', chat, False)
        if chat == self.e.config.support_chat:
            return False
        return self.e.member(chat, self.e.me['id']).get('status') == 'administrator'

    def command(self, m, cmd, args):
        uid = m['from']['id']
        if m['chat']['type'] != 'private' or not self.allowed(uid):
            raise PermissionError('Super-admin broadcasts require an authorized operator in private chat')
        db = self.e.db
        if cmd == 'superadmin':
            self.e.say(uid, 'Super-admin broadcast console\n/announce users|groups|all TEXT (or reply to media)\n'
                '/announce_send ID CONFIRM\n/announce_status ID\n/announce_cancel ID\n'
                'Private recipients must have contacted this bot and must not have opted out. '
                'Groups must be observed and Nexora must still be an administrator.')
            return
        if cmd == 'announce':
            bits = args.split(maxsplit=1)
            if not bits or bits[0] not in ('users', 'groups', 'all'):
                raise ValueError('Use /announce users|groups|all TEXT, or reply to content')
            content = self.e.capture(m.get('reply_to_message', {}), bits[1] if len(bits) > 1 else '')
            if content['kind'] == 'text' and not content.get('text'):
                raise ValueError('Supply text or reply to a media message')
            targets, unchecked = [], 0
            for kind, category in [('user', 'broadcast_users'), ('group', 'broadcast_groups')]:
                if bits[0] not in ('all', kind + 's'):
                    continue
                for target in db.items('global', category):
                    try:
                        if self.eligible(int(target), kind):
                            targets.append({'chat': int(target), 'kind': kind})
                    except RemoteError:
                        unchecked += 1
            campaign_id = secrets.token_hex(6)
            campaign = {'owner': uid, 'created': time.time(), 'expires': time.time() + 900,
                        'status': 'draft', 'targets': targets, 'content': content}
            db.put('global', 'campaigns', campaign_id, campaign)
            self.e.send_content(uid, content)
            self.e.say(uid, f'Preview {campaign_id}: {len(targets)} eligible destinations; {unchecked} could not be checked.\n'
                f'To send within 15 minutes: /announce_send {campaign_id} CONFIRM\n'
                'Recipients and permissions are checked again at delivery. Nothing has been queued yet.')
            return
        parts = args.split()
        if not parts:
            raise ValueError('Supply a campaign ID')
        campaign_id = parts[0]
        campaign = db.get('global', 'campaigns', campaign_id)
        if not campaign or campaign['owner'] != uid:
            raise PermissionError('Unknown campaign or it belongs to a different operator')
        if cmd == 'announce_send':
            if parts[1:] != ['CONFIRM']:
                raise ValueError('Confirm using /announce_send ID CONFIRM')
            if campaign['status'] != 'draft' or campaign['expires'] <= time.time():
                raise ValueError('This preview has expired or has already been queued/cancelled')
            campaign['status'] = 'queued'
            # Enqueue and mark consumed atomically: a restart cannot duplicate the campaign.
            with db.lock, db.conn:
                for index, target in enumerate(campaign['targets']):
                    payload = {'campaign': campaign_id, 'actor': uid, 'kind': target['kind'], 'content': campaign['content']}
                    db.conn.execute('INSERT INTO jobs(chat,kind,due,payload) VALUES(?,?,?,?)',
                        (target['chat'], 'super_broadcast', time.time() + index * 4, json.dumps(payload)))
                db.conn.execute("UPDATE docs SET value=? WHERE scope='global' AND kind='campaigns' AND key=?",
                                (json.dumps(campaign), campaign_id))
            self.e.say(uid, f'Campaign {campaign_id} queued. /announce_status {campaign_id}')
        elif cmd == 'announce_cancel':
            campaign['status'] = 'cancelled'
            with db.lock, db.conn:
                for row in db.conn.execute("SELECT id,payload FROM jobs WHERE kind='super_broadcast' AND status='pending'").fetchall():
                    if json.loads(row['payload']).get('campaign') == campaign_id:
                        db.conn.execute("UPDATE jobs SET status='cancelled' WHERE id=?", (row['id'],))
                db.conn.execute("UPDATE docs SET value=? WHERE scope='global' AND kind='campaigns' AND key=?",
                                (json.dumps(campaign), campaign_id))
            self.e.say(uid, 'Pending deliveries cancelled. Already sent messages are not recalled.')
        elif cmd == 'announce_status':
            counts = {}
            for row in db.sql("SELECT chat,status,payload FROM jobs WHERE kind='super_broadcast'"):
                if json.loads(row['payload']).get('campaign') != campaign_id:
                    continue
                outcome = db.get('campaign:' + campaign_id, 'delivery', row['chat'], {})
                state = outcome.get('status', row['status'])
                counts[state] = counts.get(state, 0) + 1
            self.e.say(uid, f'Campaign {campaign_id}: {campaign["status"]}\n' + json.dumps(counts) +
                       '\nUncertain deliveries are not automatically retried.')
        else:
            raise ValueError('Unknown super-admin command')

    def deliver(self, chat, payload):
        db = self.e.db
        campaign = db.get('global', 'campaigns', payload['campaign'])
        if not campaign or campaign['status'] != 'queued' or not self.allowed(payload['actor']) or \
                campaign['owner'] != payload['actor'] or not self.eligible(chat, payload['kind']):
            result = {'status': 'skipped'}
        else:
            sent = self.e.send_content(chat, payload['content'])
            result = {'status': 'delivered', 'message': sent['message_id']}
        db.put('campaign:' + payload['campaign'], 'delivery', chat, result)
