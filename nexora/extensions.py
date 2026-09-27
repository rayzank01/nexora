"""Scoped, expiring interactive control plane and community safety features."""
import difflib
import hashlib
import json
import os
import sqlite3
import secrets
import time
import unicodedata
from .config import DEFAULTS, PERMISSIONS
from .transport import RemoteError
from .operations import Operations
from .ai import Assistant
from .community_support import CommunitySupport
from .billing import Billing
from . import backups


SAFE_TEMPLATE = {'language','captcha','captcha_seconds','strict','locks','warn_limit','warn_ttl',
    'warn_action','action_seconds','flood_count','flood_window','repeat_count','new_user_seconds',
    'new_user_locks','cleanup_service','greeting_ttl','timezone','xp','cas'}
TOPIC_KEYS = {'rules','locks','new_user_locks','flood_count','repeat_count','flood_window'}


def fingerprint(member):
    return {k: v for k,v in member.items() if k in PERMISSIONS or k in ('status','until_date','is_member')}


class Extensions:
    def __init__(self, engine):
        self.e = engine
        self.ops = Operations(self)
        self.ai = Assistant(engine)
        self.community = CommunitySupport(engine)
        self.billing = Billing(engine)
        self.last_maintenance = 0

    @property
    def db(self):
        return self.e.db

    def tr(self, chat, text):
        from .i18n import translate
        return translate(text, self.e.settings(chat)['language'])

    def describe(self, chat, value):
        if isinstance(value,dict):
            return '\n'.join(self.tr(chat,str(k))+': '+self.describe(chat,v) for k,v in value.items())
        if isinstance(value,list):
            return '; '.join(self.describe(chat,v) for v in value) or '—'
        if isinstance(value,bool):return self.tr(chat,'Enabled' if value else 'Disabled')
        return self.tr(chat,str(value))

    def token(self, dest, user, chat, action, data=None, ttl=600, reusable=False):
        token = secrets.token_urlsafe(16)
        self.db.put('global','ui_tokens',token,{'dest': dest, 'user': user, 'chat': chat, 'action': action,
            'data': data or {}, 'expires': time.time()+ttl, 'reusable': reusable})
        return 'x:'+token

    def buttons(self, dest, user, chat, text, choices):
        # choices = (label, action, payload), no identifiers/permissions trusted from callback data.
        rows = [[{'text': self.tr(chat, label)[:64], 'callback_data': self.token(dest,user,chat,action,data)}]
                for label,action,data in choices]
        self.e.say(dest, self.tr(chat,text), reply_markup={'inline_keyboard': rows})

    def groups(self, user):
        known = self.db.items('global','broadcast_groups')
        known.update({k:{'title':v} for k,v in self.db.items(user,'channels').items()})
        result = []
        for key, info in known.items():
            try:
                self.e.require(int(key),user,native=True)
            except (PermissionError,RemoteError):
                continue
            result.append({'id':int(key),'title':info.get('title',key)})
        return result

    def panel(self, dest, user, chat, page='home', topic=0):
        self.e.require(chat,user,native=True)
        back = [('Back','page',{'page':'home','topic':topic}),('Cancel','cancel',{})]
        if page == 'home':
            choices = [(name,'page',{'page':key,'topic':topic}) for name,key in
                [('Setup wizard','setup'),('Moderation & raid','raid'),('Topics & rules','topics'),
                 ('Templates','templates'),('Publishing calendar','calendar'),('Events','events'),
                 ('AI settings','ai'),('Privacy & retention','privacy'),('Community support','support')]]
            self.buttons(dest,user,chat,'Nexora control panel',choices+[('Cancel','cancel',{})])
        elif page == 'setup':
            keys = ['welcome','goodbye','rules','captcha','strict','language','warn_action','warn_limit','locks','timezone']
            self.buttons(dest,user,chat,'Choose a setting',[(key,'setting',{'key':key,'topic':0}) for key in keys]+[
                ('More settings','page',{'page':'more'}),('Check bot permissions','permissions',{})]+back)
        elif page == 'more':
            self.buttons(dest,user,chat,'Choose a setting',[(key,'setting',{'key':key,'topic':0}) for key in DEFAULTS if key not in ('welcome','goodbye','rules','captcha','strict','language','warn_action','warn_limit','locks','timezone')]+back)
        elif page == 'raid':
            policy = self.db.get(chat,'extensions','raid',{'enabled':False,'joins':8,'spam':5,'window':30,'seconds':600})
            self.e.say(dest,self.describe(chat,policy))
            self.buttons(dest,user,chat,'Raid controls',[
                ('Enable detection','raid_policy',{'enabled':True}),('Disable detection','raid_policy',{'enabled':False}),
                ('Configure thresholds','prompt',{'kind':'raid'}),('Lock down for 10 minutes','raid_confirm',{}),
                ('End lockdown','raid_end',{}),('Impersonation alerts on','impersonation',{'enabled':True}),
                ('Impersonation alerts off','impersonation',{'enabled':False}),('Similarity threshold','prompt',{'kind':'similarity'}),('Add name exception','prompt',{'kind':'exception'})]+back)
        elif page == 'topics':
            self.buttons(dest,user,chat,'Topic settings inherit group values unless overridden.',[
                ('Topic rules','setting',{'key':'rules','topic':topic}),('Topic locks','setting',{'key':'locks','topic':topic}),
                ('Add filter','prompt',{'kind':'filter','topic':topic}),('Remove filter','prompt',{'kind':'unfilter','topic':topic}),
                ('Test sample without actions','prompt',{'kind':'dryrun','topic':topic}),('Restore topic inheritance','topic_reset',{'topic':topic})]+back)
        elif page == 'templates':
            self.buttons(dest,user,chat,'Templates copy policy only; greetings, rules, notes and secrets stay private.',[
                ('Save policy template','prompt',{'kind':'template_save'}),('Apply a template','prompt',{'kind':'template_apply'}),
                ('Apply to several groups','prompt',{'kind':'bulk_template'})]+back)
        elif page == 'support':
            self.buttons(dest,user,chat,'Community support', [('Configure private staff inbox','prompt',{'kind':'support_config'})]+back)
            config=self.community.config(chat)
            if config and user in config['staff']:
                self.community.staff(chat,user)
                for key,t in self.db.items(self.community.scope(chat),'tickets').items():
                    if t['status']=='open':
                        self.e.say(dest,f"/cticket {chat} {key}")
        elif page == 'calendar':
            jobs = self.ops.calendar(chat,user)
            text = '\n'.join(f"{j['id']} · {j['local']} · {j['status']} · {j['draft']}" for j in jobs[-20:]) or 'No scheduled posts'
            self.e.say(dest,text)
            self.buttons(dest,user,chat,'Publishing calendar',[
                ('Schedule recurring draft','prompt',{'kind':'recurrence'}),('Move scheduled post','prompt',{'kind':'move_job'})]+
                [(f"Cancel {j['id']}",'job_cancel_confirm',{'job':j['id']}) for j in jobs if j['status']=='pending'][:15]+back)
        elif page == 'events':
            events = self.db.items(chat,'community_events')
            self.buttons(dest,user,chat,'Community events',[
                ('Create event','prompt',{'kind':'event'}),('Edit event','prompt',{'kind':'event_edit'}),
                ('Create poll','prompt',{'kind':'poll'}),('Create quiz','prompt',{'kind':'quiz'})]+
                [(v['title'][:50],'event_view',{'event':k,'revision':v['revision']}) for k,v in events.items() if v['status']=='active'][:15]+back)
        elif page == 'ai':
            self.buttons(dest,user,chat,'AI is optional. External processing requires separate consent. Summaries only include observed, opted-in capture.',[
                ('Enable local AI','ai_policy',{'enabled':True}),('Disable AI','ai_policy',{'enabled':False}),
                ('Enable summary capture with notice','ai_capture_confirm',{}),('Stop summary capture','ai_policy',{'capture':False}),
                ('Allow configured external AI','ai_external_confirm',{}),('Disallow external AI','ai_policy',{'external':False}),
                ('Add approved knowledge','prompt',{'kind':'knowledge'}),('Remove approved knowledge','prompt',{'kind':'unknowledge'}),
                ('Summarize observed messages','ai_summary',{}),('Suggest moderation review','prompt',{'kind':'suggest'})]+back)
        elif page == 'privacy':
            self.buttons(dest,user,chat,'Retention applies to observed activity. Active moderation evidence and backups have separate limits.',[
                ('Set activity retention days','prompt',{'kind':'retention'})]+back)

    def prompt(self, dest, user, chat, data):
        hints = {'raid':'Enter join threshold, distinct spammer threshold, window seconds, lockdown seconds: 8 5 30 600',
            'exception':'Enter the numeric member ID to exempt from name similarity alerts.',
            'filter':'Enter NAME | word/phrase/domain/pattern/user | MATCH | delete/warn/mute/ban/kick/reply | optional reply text',
            'unfilter':'Enter filter name. Topic overrides can be removed without changing group filters.',
            'dryrun':'Send a sample message. Nothing will be moderated.',
            'template_save':'Enter a short template name.', 'template_apply':'Enter a saved template name. You will review before applying.',
            'recurrence':'Enter DRAFT | HH:MM | weekdays 0–6 separated by commas (0 is Monday). Group timezone is used.',
            'move_job':'Enter JOB_ID | future ISO date/time with offset.',
            'event':'Enter TITLE | future ISO date/time with offset.',
            'event_edit':'Enter EVENT_ID | TITLE | future ISO date/time with offset.',
            'poll':'Enter QUESTION | ANSWER 1 | ANSWER 2 (up to 10 answers).',
            'quiz':'Enter zero-based CORRECT_INDEX | QUESTION | ANSWER 1 | ANSWER 2.',
            'knowledge':'Enter SOURCE_NAME | approved FAQ text. Do not include private data.',
            'unknowledge':'Enter the source name to remove.', 'suggest':'Send the sample for an advisory AI review.',
            'retention':'Enter activity retention in days, 1–3650.',
            'appeal_reason':'Enter your appeal reason. It will be shared with this group’s administrators.',
            'appeal_review':'Enter the decision reason for the member.', 'ticket_note':'Enter an internal staff note. This will never be relayed to the member.'}
        hints.update({'support_config':'Enter private INBOX_ID | comma-separated staff IDs. Only the bot and these staff may be in that inbox.',
            'community_ticket_note':hints['ticket_note'], 'bulk_template':'Enter TEMPLATE_NAME | comma-separated destination group IDs. Every destination requires current administrator rights.',
            'similarity':'Enter a name similarity threshold from 0.75 to 1.0.', 'test_candidate':hints['dryrun']})
        kind = data.get('kind','setting')
        hint = hints.get(kind,'Send the new value as plain text. For lists, separate values with commas. /cancel stops.')
        sent = self.e.say(dest,self.tr(chat,hint),reply_markup={'force_reply':True,'selective':True})
        self.db.put('global','ui_inputs',f'{dest}:{user}:{chat}',{'dest':dest,'user':user,'chat':chat,'data':data,'expires':time.time()+600,'prompt':sent['message_id']})

    def callback(self,q):
        if not q.get('data','').startswith('x:'):
            return False
        with self.db.lock:
            token = q['data'][2:]
            session = self.db.get('global','ui_tokens',token)
            user = q['from']['id']
            dest = q.get('message',{}).get('chat',{}).get('id')
            try:
                if not session or session['expires'] < time.time() or session['dest'] != dest or session['user'] not in (0,user):
                    raise PermissionError('This button expired or belongs to another session')
                if not session['reusable']:
                    self.db.delete('global','ui_tokens',token)
                chat, action, p = session['chat'], session['action'], session['data']
                member_actions = {'rsvp','privacy_export','privacy_delete_confirm','privacy_delete','privacy_noai','appeal_submit','cancel','billing_cancel','billing_refund','choose_groups','privacy_menu','private_language'}
                staff_actions = {'ticket_assign','ticket_priority','ticket_note','ticket_close'}
                if action in staff_actions:
                    if user not in self.e.config.support_admins:
                        raise PermissionError('Support staff access required')
                elif action not in member_actions:
                    self.e.require(chat,user,native=True)
                self.action(dest,user,chat,action,p)
                self.e.tg.call('answerCallbackQuery',callback_query_id=q['id'],text=self.tr(chat,'Done'))
            except (ValueError,PermissionError,KeyError,TypeError,RemoteError) as exc:
                text = str(exc) if isinstance(exc,(ValueError,PermissionError)) else 'Action failed; reopen the menu and inspect current state'
                self.e.tg.call('answerCallbackQuery',callback_query_id=q['id'],text=self.tr(dest,text)[:180],show_alert=True)
        return True

    def action(self,dest,user,chat,action,p):
        if action == 'cancel':
            self.db.delete('global','ui_inputs',f'{dest}:{user}:{chat}')
        elif action == 'choose_groups':
            self.command({'chat':{'id':dest,'type':'private'},'from':{'id':user}},'panel','')
        elif action=='privacy_menu':
            if dest!=user:raise PermissionError('Open /privacy in a private chat')
            self.command({'chat':{'id':dest,'type':'private'},'from':{'id':user}},'privacy','')
        elif action=='private_language':
            if dest!=user:raise PermissionError('Use /help for private commands')
            self.command({'chat':{'id':dest,'type':'private'},'from':{'id':user}},'language',p['language'])
        elif action == 'billing_invoice':self.billing.invoice(chat,user)
        elif action == 'billing_offer':
            self.command({'chat':{'id':user,'type':'private'},'from':{'id':user}},'upgrade',str(chat))
        elif action == 'billing_cancel':
            if dest!=user:raise PermissionError('Private payment receipt required')
            self.billing.cancel(user,p['payload'])
        elif action == 'billing_refund':
            if dest!=user:raise PermissionError('Private super-admin access required')
            self.billing.refund(user,p['charge'])
        elif action == 'page':
            self.panel(dest,user,chat,p.get('page','home'),p.get('topic',0))
        elif action == 'permissions':
            member = self.e.member(chat,self.e.me['id'])
            self.e.say(dest,self.describe(chat,{k:member.get(k,False) for k in ('status','can_delete_messages','can_restrict_members','can_invite_users','can_pin_messages','can_post_messages','can_manage_topics')}))
        elif action == 'setting':
            key, topic = p['key'], p.get('topic',0)
            if topic and key not in TOPIC_KEYS:
                raise ValueError('This setting is group-wide')
            current = self.e.settings(chat,topic)[key]
            choices = {'captcha':['off','button','response','math','image','private','web','turnstile'],
                'language':['en','ml'],'warn_action':['mute','ban','kick']}.get(key, [True,False] if type(current) is bool else [])
            p = dict(p,kind='setting',before=current)
            if choices:
                self.buttons(dest,user,chat,'Choose the new value',[(str(v),'setting_confirm',dict(p,value=v)) for v in choices]+[('Back','page',{'page':'setup'}),('Cancel','cancel',{})])
            else:
                self.prompt(dest,user,chat,p)
        elif action == 'prompt':
            self.prompt(dest,user,chat,p)
        elif action == 'setting_confirm':
            self.e.say(dest,f"{p['key']}: {p['before']} → {p['value']}")
            self.buttons(dest,user,chat,'Apply this change?', [('Confirm','setting_apply',p),('Back','page',{'page':'setup'}),('Cancel','cancel',{})])
        elif action == 'setting_apply':
            topic = p.get('topic',0)
            if self.e.settings(chat,topic)[p['key']] != p['before']:
                raise ValueError('Setting changed since preview; reopen the menu')
            if topic:
                self.topic(chat,user,topic,p['key'],p['value'])
            else:
                self.e.configure(chat,user,p['key'],p['value'])
            self.panel(dest,user,chat,'setup')
        elif action == 'raid_policy':
            policy = self.db.get(chat,'extensions','raid',{'joins':8,'spam':5,'window':30,'seconds':600})
            policy.update(p);self.db.put(chat,'extensions','raid',policy)
        elif action == 'raid_confirm':
            self.buttons(dest,user,chat,'Temporarily tighten bot moderation for 10 minutes?', [('Confirm','raid_start',{}),('Cancel','cancel',{})])
        elif action == 'raid_start':
            self.e.require(chat,user,'moderate',native=True);self.raid_start(chat,600,'Manual administrator request')
        elif action == 'raid_end':
            self.e.require(chat,user,'moderate',native=True);self.db.delete(chat,'extensions','raid_active')
        elif action == 'impersonation':
            self.db.put(chat,'extensions','impersonation',{**self.db.get(chat,'extensions','impersonation',{}),**p})
        elif action == 'filter_apply':
            self.e.validate_rule(p['rule']);topic=p.get('topic',0)
            if topic:
                self.ensure_topic(chat,topic);rules=self.db.get(chat,'topic_rules',topic,{})
                if rules.get(p['name'])!=p.get('before'):raise ValueError('Setting changed since preview; reopen the menu')
                rules[p['name']]=p['rule'];self.db.put(chat,'topic_rules',topic,rules)
            else:
                if self.db.get(chat,'rules',p['name'])!=p.get('before'):raise ValueError('Setting changed since preview; reopen the menu')
                self.e.add_rule(chat,user,p['name'],p['rule'])
        elif action == 'topic_reset':
            if not p.get('topic'):
                raise ValueError('Open /panel inside a forum topic first')
            self.db.delete(chat,'topics',p['topic'])
            self.db.delete(chat,'topic_rules',p['topic'])
        elif action == 'template_apply':
            # Compare all target values with preview, before making any change.
            current = self.e.settings(chat)
            if any(current[k] != v for k,v in p['before'].items()):
                raise ValueError('Destination settings changed since preview')
            if not set(p['values']) <= SAFE_TEMPLATE:
                raise ValueError('Template contains private or unsupported settings')
            for key,value in p['values'].items():
                self.e.validate_setting(chat,user,key,value)
            self.db.put(chat,'config','settings',{**current,**p['values']})
            self.e.audit(chat,user,'template_applied')
        elif action == 'bulk_apply':self.bulk_apply(user,p)
        elif action == 'support_config':self.community.configure(chat,user,p['inbox'],p['staff'])
        elif action.startswith('community_ticket_'):
            self.community.staff(chat,user,dest)
            if action=='community_ticket_note':self.prompt(dest,user,chat,dict(p,kind='community_ticket_note'))
            else:self.community.update(chat,user,p['ticket'],action.removeprefix('community_ticket_'),p.get('value',user))
        elif action == 'job_cancel_confirm':
            self.buttons(dest,user,chat,'Cancel this scheduled post?', [('Confirm','job_cancel',p),('Cancel','cancel',{})])
        elif action == 'job_cancel':
            self.ops.edit_job(chat,user,p['job'],'cancel')
        elif action == 'event_view':
            self.ops.event_card(chat,dest,p['event'])
            self.buttons(dest,user,chat,'Event actions', [('Publish RSVP card','event_publish',p),('Cancel event','event_cancel_confirm',p),('Back','page',{'page':'events'})])
        elif action == 'event_publish':
            self.ops.event_card(chat,chat,p['event'])
        elif action == 'event_cancel_confirm':
            self.buttons(dest,user,chat,'Cancel this event?', [('Confirm','event_cancel',p),('Cancel','cancel',{})])
        elif action == 'event_cancel':
            event = self.db.get(chat,'community_events',p['event'])
            if p.get('revision') and p['revision']!=event['revision']:raise ValueError('Event changed or ended')
            event['status']='cancelled'
            self.db.put(chat,'community_events',p['event'],event)
        elif action == 'rsvp':
            self.ops.rsvp(chat,user,p)
        elif action in ('ai_capture_confirm','ai_external_confirm'):
            policy = {'capture':True} if action=='ai_capture_confirm' else {'external':True}
            self.buttons(dest,user,chat,'This changes which observed group data can be processed. A notice will be posted in the group. Confirm?', [('Confirm','ai_policy',policy),('Cancel','cancel',{})])
        elif action == 'ai_policy':
            policy = self.db.get(chat,'extensions','ai',{})
            if p.get('capture') or p.get('external'):
                self.e.say(chat,'AI notice: summary capture / external processing configuration is changing. /privacy offers export, deletion and AI capture opt-out. Only observed messages are available.')
            policy.update(p);self.db.put(chat,'extensions','ai',policy)
        elif action == 'ai_summary':
            self.e.say(dest,self.ai.run(chat,user,'summary'))
        elif action == 'privacy_export':
            data=json.dumps(self.ops.personal(user),ensure_ascii=False,indent=2)
            for i in range(0,len(data),3500):self.e.say(user,data[i:i+3500])
        elif action == 'privacy_noai':
            self.db.put('privacy','no_ai',user,True)
        elif action == 'privacy_delete_confirm':
            self.buttons(user,user,user,'Delete your stored activity and support metadata? Safety records, Telegram copies and backups may remain.',[('Confirm deletion','privacy_delete',{}),('Cancel','cancel',{})])
        elif action == 'privacy_delete':
            self.ops.personal(user,delete=True);self.e.say(user,'Personal activity removed. Active safety records and separate backups may remain.')
        elif action == 'appeal_submit':
            self.submit_appeal(user,chat,p['reason'])
        elif action == 'appeal_review':
            self.e.require(chat,user,'moderate',native=True)
            self.prompt(dest,user,chat,dict(p,kind='appeal_review'))
        elif action == 'appeal_decide':
            self.decide_appeal(chat,user,p['appeal'],p['approve'],p['reason'])
        elif action.startswith('ticket_'):
            if action=='ticket_note':self.prompt(dest,user,chat,dict(p,kind='ticket_note'))
            else:self.ops.ticket(user,p['ticket'],action[7:],p.get('value',user))
        else:
            raise ValueError('Unknown action')

    def input(self,m):
        dest,user = m['chat']['id'],m['from']['id']
        candidates = [(k,v) for k,v in self.db.items('global','ui_inputs').items()
            if v['dest']==dest and v['user']==user and v['expires']>=time.time()]
        reply = m.get('reply_to_message',{}).get('message_id')
        if reply:
            candidates=[(k,v) for k,v in candidates if v['prompt']==reply]
        elif dest<0 or len(candidates)!=1:
            return False
        if not candidates:return False
        session_key,s=candidates[0]
        if m.get('text') == '/cancel':
            self.db.delete('global','ui_inputs',session_key);return True
        if m.get('text','').startswith('/'):
            return False
        if s['expires'] < time.time():
            self.db.delete('global','ui_inputs',session_key);return False
        if dest < 0 and m.get('reply_to_message',{}).get('message_id') != s['prompt']:
            return False
        p,chat = s['data'],s['chat'];kind=p.get('kind','setting');text=m.get('text','')[:4000]
        if kind == 'ticket_note':
            if user not in self.e.config.support_admins:raise PermissionError('Support staff access required')
        elif kind != 'appeal_reason':self.e.require(chat,user,native=True)
        self.db.delete('global','ui_inputs',session_key)
        from .engine import scheduled_time
        if kind == 'setting':
            before=p['before']
            value = int(text) if type(before) is int else [v.strip() for v in text.split(',') if v.strip()] if isinstance(before,list) else text
            self.action(dest,user,chat,'setting_confirm',dict(p,value=value))
        elif kind == 'raid':
            joins,spam,window,seconds=map(int,text.split())
            if not 2<=joins<=100 or not 2<=spam<=100 or not 5<=window<=300 or not 60<=seconds<=3600:raise ValueError('Thresholds: 2–100 users, 5–300 second window, 60–3600 second lockdown')
            self.action(dest,user,chat,'raid_policy',{'joins':joins,'spam':spam,'window':window,'seconds':seconds})
        elif kind == 'exception':self.db.put(chat,'name_exceptions',int(text),True)
        elif kind == 'similarity':
            threshold=float(text)
            if not .75<=threshold<=1:raise ValueError('Enter a name similarity threshold from 0.75 to 1.0.')
            self.action(dest,user,chat,'impersonation',{'threshold':threshold})
        elif kind in ('filter','unfilter'):
            topic=p.get('topic',0)
            if kind=='unfilter':
                if topic:
                    rules=self.db.get(chat,'topic_rules',topic,{});rules.pop(text,None);self.db.put(chat,'topic_rules',topic,rules)
                else:self.db.delete(chat,'rules',text)
            else:
                bits=[b.strip() for b in text.split('|')];name,typ,match,action=bits[:4]
                rule={'type':typ,'match':match,'actions':[action]}
                if len(bits)>4:rule['reply']=bits[4]
                self.e.validate_rule(rule)
                before=self.db.get(chat,'topic_rules',topic,{}).get(name[:40]) if topic else self.db.get(chat,'rules',name[:40])
                self.prompt(dest,user,chat,{'kind':'test_candidate','topic':topic,'name':name[:40],'rule':rule,'before':before})
        elif kind=='test_candidate':
            sample=dict(m,chat={'id':chat,'type':'supergroup'},text=text,message_thread_id=p.get('topic',0))
            result=self.dryrun(sample,candidate=(p['name'],p['rule']))
            self.e.say(dest,self.describe(chat,result))
            self.buttons(dest,user,chat,'Enable this tested filter?', [('Confirm','filter_apply',p),('Cancel','cancel',{})])
        elif kind == 'dryrun':
            sample=dict(m,chat={'id':chat,'type':'supergroup'},text=text,message_thread_id=p.get('topic',0))
            self.e.say(dest,self.describe(chat,self.dryrun(sample)))
        elif kind == 'template_save':
            self.db.put(user,'templates',text[:40],{k:v for k,v in self.e.settings(chat).items() if k in SAFE_TEMPLATE})
        elif kind == 'template_apply':
            values=self.db.get(user,'templates',text)
            if not values:raise ValueError('Unknown template')
            self.e.say(dest,self.describe(chat,values))
            self.buttons(dest,user,chat,'Apply this policy to the selected group?', [('Confirm','template_apply',{'values':values,'before':{k:self.e.settings(chat)[k] for k in values}}),('Cancel','cancel',{})])
        elif kind == 'recurrence':
            draft,clock,days=[b.strip() for b in text.split('|')]
            self.ops.recurring(chat,user,draft,clock,[int(d) for d in days.split(',')])
        elif kind == 'move_job':
            job,date=text.split('|',1);self.ops.edit_job(chat,user,int(job),'move',scheduled_time(date.strip(),self.e.settings(chat)['timezone']))
        elif kind in ('event','event_edit'):
            bits=[b.strip() for b in text.split('|')];key=bits.pop(0) if kind=='event_edit' else None
            title,date=bits;key=self.ops.event(chat,user,title,scheduled_time(date,self.e.settings(chat)['timezone']),key)
            self.ops.event_card(chat,dest,key)
        elif kind in ('poll','quiz'):
            bits=[b.strip() for b in text.split('|')];correct=int(bits.pop(0)) if kind=='quiz' else None
            self.ops.poll(chat,user,bits[0],bits[1:],correct)
        elif kind == 'knowledge':
            key,value=text.split('|',1);self.db.put(chat,'knowledge',key.strip()[:40],value.strip()[:3000])
        elif kind == 'unknowledge':self.db.delete(chat,'knowledge',text)
        elif kind == 'suggest':self.e.say(dest,self.ai.run(chat,user,'suggest',text))
        elif kind == 'retention':
            days=int(text)
            if not 1<=days<=3650:raise ValueError('Use 1–3650 days')
            self.db.put(chat,'extensions','retention',days)
        elif kind == 'appeal_reason':
            self.buttons(dest,user,chat,'Submit this reason to group administrators?', [('Confirm','appeal_submit',{'reason':text[:1500]}),('Cancel','cancel',{})])
        elif kind == 'appeal_review':
            self.buttons(dest,user,chat,'Record this appeal decision?', [('Confirm','appeal_decide',dict(p,reason=text[:1500])),('Cancel','cancel',{})])
        elif kind == 'ticket_note':self.ops.ticket(user,p['ticket'],'note',text)
        elif kind == 'community_ticket_note':self.community.update(chat,user,p['ticket'],'note',text)
        elif kind == 'support_config':
            inbox,staff=text.split('|',1)
            self.buttons(dest,user,chat,'Apply this change?', [('Confirm','support_config',{'inbox':int(inbox),'staff':[int(v) for v in staff.split(',')]}),('Cancel','cancel',{})])
        elif kind == 'bulk_template':
            name,destinations=text.split('|',1)
            preview=self.bulk_preview(user,name.strip(),[int(c) for c in destinations.split(',')])
            self.e.say(dest,self.describe(chat,preview))
            self.buttons(dest,user,chat,'Apply this policy to the selected groups?', [('Confirm','bulk_apply',preview),('Cancel','cancel',{})])
        self.e.say(dest,self.tr(chat,'Saved'))
        return True

    def command(self,m,cmd,args):
        cid,uid=m['chat']['id'],m['from']['id'];private=cid>0
        if cmd in ('panel','wizard','setup'):
            if private and not args:
                choices=[(g['title'],g['id']) for g in self.groups(uid)]
                for title,chat in choices:
                    self.buttons(cid,uid,chat,title,[('Open group','page',{'page':'home'})])
                if not choices:self.e.say(cid,'No known groups. Use /panel GROUP_ID or /panel inside your group.')
            else:self.panel(cid,uid,int(args) if private else cid,topic=m.get('message_thread_id',0))
        elif cmd=='csupport':
            if not private:raise ValueError('Use community support in a private chat')
            self.community.start(uid,int(args))
        elif cmd=='close' and private and self.db.get(uid,'session','community_support') is not None:
            self.db.delete(uid,'session','community_support');self.e.say(uid,'Support conversation closed.')
        elif cmd=='cticket':
            chat,key=args.split(maxsplit=1);chat=int(chat)
            config=self.community.staff(chat,uid,cid)
            ticket=self.db.get(self.community.scope(chat),'tickets',key)
            if not ticket:raise ValueError('Unknown ticket')
            self.e.say(cid,self.describe(chat,ticket))
            self.buttons(cid,uid,chat,'Ticket actions',[(str(staff),'community_ticket_assign',{'ticket':key,'value':staff}) for staff in config['staff']]+
                [(priority,'community_ticket_priority',{'ticket':key,'value':priority}) for priority in ('low','normal','high','urgent')]+
                [('Internal note','community_ticket_note',{'ticket':key}),('Close ticket','community_ticket_close',{'ticket':key})])
        elif cmd in ('plan','upgrade'):
            if not private:raise ValueError('Open the plan menu in a private chat')
            chat=int(args);self.e.require(chat,uid,native=True)
            plan=self.billing.plan(chat)
            self.e.say(uid,'Pro subscription active for this group.' if plan['plan']=='pro' else 'All features are currently available. Paid limits are not active.')
            if plan['expires']:
                from .calendar import local_label
                self.e.say(uid,local_label(plan['expires'],self.e.settings(chat)['timezone']))
            try:price,terms=self.billing.settings()
            except ValueError:
                self.e.say(uid,'Upgrades are disabled until the operator confirms pricing and terms.')
                return True
            if cmd=='upgrade':
                self.e.say(uid,f'{price} XTR / 30 days\n'+terms)
                self.buttons(uid,uid,chat,'Agree to the terms and create a subscription invoice?', [('Confirm','billing_invoice',{}),('Cancel','cancel',{})])
            elif plan['plan']!='pro':self.buttons(uid,uid,chat,'Group subscription', [('Review upgrade','billing_offer',{}),('Cancel','cancel',{})])
        elif cmd=='subscriptions':
            if not private:raise ValueError('Open the plan menu in a private chat')
            for payload,order in self.db.items('billing','orders').items():
                if order['user']==uid and order.get('subscription_charge'):
                    self.buttons(uid,uid,uid,str(order['chat']),[('Cancel renewal','billing_cancel',{'payload':payload})])
        elif cmd=='refund':
            if not private or not self.e.superadmin.allowed(uid):raise PermissionError('Private super-admin access required')
            self.buttons(uid,uid,uid,'Refund this payment?', [('Confirm','billing_refund',{'charge':args}),('Cancel','cancel',{})])
        elif cmd=='terms':self.e.say(cid,os.getenv('NEXORA_BILLING_TERMS','Billing is not enabled or fully configured'))
        elif cmd=='paysupport':
            if not private:raise ValueError('Use /help for private commands')
            self.db.delete(uid,'session','community_support');self.e.support_command(m,'support','')
        elif cmd == 'cancel' and not args:
            for key,value in self.db.items('global','ui_inputs').items():
                if value['dest']==cid and value['user']==uid:self.db.delete('global','ui_inputs',key)
        elif cmd == 'language' and private:
            if args not in ('en','ml'):raise ValueError('Supported languages: en, ml')
            settings=self.e.settings(uid);settings['language']=args;self.db.put(uid,'config','settings',settings)
            self.e.say(uid,'Saved')
        elif cmd == 'privacy':
            if not private:raise ValueError('Open /privacy in a private chat')
            self.buttons(uid,uid,uid,'Your privacy controls', [('Export my data','privacy_export',{}),('Delete my activity','privacy_delete_confirm',{}),('Opt out of AI capture','privacy_noai',{})])
        elif cmd == 'appeal':
            if not private:raise ValueError('Submit appeals in private: /appeal GROUP_ID')
            chat=int(args)
            if not self.db.get(chat,'bot_actions',uid):raise ValueError('No eligible recorded bot action in this group')
            self.prompt(uid,uid,chat,{'kind':'appeal_reason'})
        elif cmd == 'appeals':
            if not private:raise ValueError('Review appeals privately: /appeals GROUP_ID')
            chat=int(args)
            self.e.require(chat,uid,'moderate',native=True)
            for key,a in self.db.items(chat,'appeals').items():
                if a['status']=='open':
                    self.e.say(cid,f"{key}: {a['reason']}")
                    self.buttons(cid,uid,chat,'Review appeal', [('Approve','appeal_review',{'appeal':key,'approve':True}),('Reject','appeal_review',{'appeal':key,'approve':False})])
        elif cmd == 'testfilter':
            self.e.require(cid,uid,native=True);sample=dict(m.get('reply_to_message') or m,text=args or (m.get('reply_to_message') or {}).get('text',''))
            sample['chat']=m['chat'];self.e.say(cid,self.describe(cid,self.dryrun(sample)))
        elif cmd == 'ticket':
            if not self.e.support_allowed(m):raise PermissionError('Support staff access required')
            key=args.strip();t=self.db.get('support','tickets',key)
            if not t:raise ValueError('Unknown ticket')
            self.e.say(cid,self.describe(cid,t))
            self.buttons(cid,uid,cid,'Ticket actions', [('Assign to me','ticket_assign',{'ticket':key})]+
                [(str(staff),'ticket_assign',{'ticket':key,'value':staff}) for staff in sorted(self.e.config.support_admins) if staff!=uid]+
                [(priority,'ticket_priority',{'ticket':key,'value':priority}) for priority in ('low','normal','high','urgent')]+
                [('Internal note','ticket_note',{'ticket':key}),('Close ticket','ticket_close',{'ticket':key})])
        elif cmd == 'album':
            if not private:raise ValueError('Prepare albums in private')
            self.ops.album(m,args);self.e.say(cid,'Album draft saved')
        elif cmd == 'faq':
            if private:raise ValueError('Use /faq inside the opted-in group')
            self.e.say(cid,self.ai.run(cid,uid,'faq',args))
        elif cmd == 'backups':
            if not private or not self.e.superadmin.allowed(uid):raise PermissionError('Private super-admin access required')
            self.e.say(cid,json.dumps(self.db.get('global','maintenance','backup',{'configured':False})))
        else:return False
        return True

    def ensure_topic(self,chat,topic):
        if not topic or not self.e.tg.call('getChat',chat_id=chat).get('is_forum'):
            raise ValueError('Open this menu inside a forum topic')

    def bulk_preview(self,user,name,chats):
        values=self.db.get(user,'templates',name)
        if not values or not set(values)<=SAFE_TEMPLATE:raise ValueError('Unknown template')
        chats=sorted(set(chats))
        if not 1<=len(chats)<=20:raise ValueError('Choose 1–20 destination groups')
        before={}
        for chat in chats:
            self.e.require(chat,user,native=True)
            before[str(chat)]={k:self.e.settings(chat)[k] for k in values}
            for key,value in values.items():self.e.validate_setting(chat,user,key,value)
        return {'values':values,'before':before}

    def bulk_apply(self,user,p):
        if not set(p['values'])<=SAFE_TEMPLATE:raise ValueError('Template contains private or unsupported settings')
        prepared={}
        for cid,before in p['before'].items():
            chat=int(cid);self.e.require(chat,user,native=True)
            current=self.e.settings(chat)
            if any(current[k]!=v for k,v in before.items()):raise ValueError('Destination settings changed since preview')
            for key,value in p['values'].items():self.e.validate_setting(chat,user,key,value)
            prepared[cid]={**self.db.get(chat,'config','settings',{}),**p['values']}
        with self.db.lock,self.db.conn:
            for cid,value in prepared.items():
                self.db.conn.execute('INSERT OR REPLACE INTO docs VALUES(?,?,?,?)',(cid,'config','settings',json.dumps(value)))
                self.db.conn.execute('INSERT INTO events(chat,user,kind,at,data) VALUES(?,?,?,?,?)',(int(cid),user,'mod',time.time(),json.dumps({'action':'bulk_template'})))

    def topic(self,chat,user,topic,key,value):
        self.e.require(chat,user,native=True);self.ensure_topic(chat,topic)
        if key not in TOPIC_KEYS:raise ValueError('Setting is not topic-specific')
        self.e.validate_setting(chat,user,key,value)
        values=self.db.get(chat,'topics',topic,{});values[key]=value;self.db.put(chat,'topics',topic,values)

    def rules(self,chat,topic=0):
        return {**self.db.items(chat,'rules'),**(self.db.get(chat,'topic_rules',topic,{}) if topic else {})}

    def dryrun(self,m,candidate=None):
        from .engine import matches,content_types
        cid,uid=m['chat']['id'],m['from']['id'];topic=m.get('message_thread_id',0)
        settings=self.e.settings(cid,topic);admin=self.e.admin(cid,uid);exempt=admin or self.db.get(cid,'trusted',uid,False)
        result={'dry_run':True,'exempt':bool(exempt),'topic':topic,'rules':[], 'locks':sorted(content_types(m)&set(settings['locks'])),
            'limits':'Flood history is not changed. Joining-state locks and CAPTCHA are evaluated separately.'}
        joined=self.db.get(cid,'members',uid,{}).get('joined',0)
        result['new_member_locks']=sorted(content_types(m)&set(settings['new_user_locks'])) if joined and time.time()-joined<settings['new_user_seconds'] else []
        result['lock_actions']=['delete','warn'] if (result['locks'] or result['new_member_locks']) and not exempt else []
        result['raid_lockdown']=not exempt and self.db.get(cid,'extensions','raid_active',{}).get('until',0)>time.time()
        pending=self.db.get(cid,'captcha',uid,{})
        result['captcha_block']=pending.get('status')=='pending' and settings['strict']
        rules={candidate[0]:candidate[1]} if candidate else self.rules(cid,topic)
        for name,r in rules.items():
            audience=r.get('audience','all')
            if m['from'].get('is_bot') and not r.get('bots'):continue
            if (audience=='admin' and not admin) or (audience=='user' and admin):continue
            if matches(r,m):result['rules'].append({'name':name,'match':r['type'],'configured_actions':r.get('actions',[]),'actions':[a for a in r.get('actions',[]) if not exempt or a=='reply']})
        return result

    def raid_start(self,chat,seconds,reason):
        self.e.bot_right(chat,'can_delete_messages')
        revision=secrets.token_hex(6)
        self.db.put(chat,'extensions','raid_active',{'until':time.time()+seconds,'revision':revision})
        self.db.job(chat,'raid_expire',time.time()+seconds,{'revision':revision})
        self.e.say(chat,'Raid protection active: bot-enforced lockdown for non-admin messages. '+reason)

    def raid_observe(self,chat,user,text=None):
        policy=self.db.get(chat,'extensions','raid',{})
        if not policy.get('enabled'):return
        now=time.time();window=policy.get('window',30)
        rows=self.db.get(chat,'extensions','raid_window',[])
        rows=[r for r in rows if r['at']>now-window][-300:]
        digest=hashlib.sha256(text.casefold().strip().encode()).hexdigest() if text else 'join'
        rows.append({'at':now,'user':user,'digest':digest})
        self.db.put(chat,'extensions','raid_window',rows)
        count=len({r['user'] for r in rows if r['digest']==digest})
        active=self.db.get(chat,'extensions','raid_active',{})
        if count>=policy.get('spam' if text else 'joins',5 if text else 8) and active.get('until',0)<now:
            self.raid_start(chat,policy.get('seconds',600),'Observed coordinated messages' if text else 'Observed join burst')

    def observe(self,m):
        if m['chat']['type'] not in ('group','supergroup'):return
        cid,uid=m['chat']['id'],m['from']['id']
        self.ai.observe(m)
        if not self.e.admin(cid,uid):
            text=m.get('text') or m.get('caption')
            if text and len(text.strip())>=12:self.raid_observe(cid,uid,text)
        if self.db.get(cid,'extensions','impersonation',{}).get('enabled') and not self.db.get(cid,'name_exceptions',uid):
            name=' '.join(m['from'].get(k,'') for k in ('first_name','last_name')).strip()
            normalize=lambda s: ''.join(c for c in unicodedata.normalize('NFKC',s).casefold() if c.isalnum())
            normalized=normalize(name)
            last=self.db.get(cid,'name_alerts',uid,{})
            if len(normalized)<3 or last.get('name')==normalized and time.time()-last.get('at',0)<86400:return
            admins=self.e.tg.call('getChatAdministrators',chat_id=cid)
            if any(a['user']['id']==uid for a in admins):return
            for a in admins:
                other=normalize(' '.join(a['user'].get(k,'') for k in ('first_name','last_name')))
                threshold=self.db.get(cid,'extensions','impersonation',{}).get('threshold',.9)
                if other and difflib.SequenceMatcher(None,normalized,other).ratio()>=threshold:
                    self.e.say(cid,f'Name similarity needs administrator review: member {uid}. This is not proof of impersonation; no action was taken.')
                    self.db.put(cid,'name_alerts',uid,{'name':normalized,'at':time.time()});break

    def record_action(self,chat,user,action,prior,reason):
        if action not in ('ban','mute','restrict'):
            self.db.delete(chat,'bot_actions',user);return
        # Never grant appeal reversal over a pre-existing restriction or verification requirement.
        eligible=prior.get('status') not in ('restricted','kicked') and reason not in ('Pending verification','Verification timeout')
        self.db.put(chat,'bot_actions',user,{'revision':secrets.token_hex(8),'action':action,'eligible':eligible,
            'expected':fingerprint(self.e.member(chat,user)),'reason':reason,'at':time.time()})

    def submit_appeal(self,user,chat,reason):
        record=self.db.get(chat,'bot_actions',user)
        if not record or not reason:raise ValueError('No recorded bot action or missing reason')
        key=f'{user}:{record["revision"]}'
        if self.db.get(chat,'appeals',key):raise ValueError('An appeal already exists for this action')
        self.db.put(chat,'appeals',key,{'user':user,'reason':reason,'action_revision':record['revision'],'status':'open','at':time.time()})
        self.e.say(chat,'A private moderation appeal is awaiting administrator review. Use /appeals.')

    def decide_appeal(self,chat,staff,key,approve,reason):
        self.e.require(chat,staff,'moderate',native=True)
        appeal=self.db.get(chat,'appeals',key)
        if not appeal or appeal['status']!='open':raise ValueError('Appeal already handled or unavailable')
        if not reason:raise ValueError('A decision reason is required')
        if approve:
            record=self.db.get(chat,'bot_actions',appeal['user'])
            if not record or not record['eligible'] or record['revision']!=appeal['action_revision'] or record['expected']!=fingerprint(self.e.member(chat,appeal['user'])):
                raise ValueError('Restriction changed or is not eligible; inspect it manually')
            if self.db.get(chat,'ban_source',appeal['user']) not in (None,'local'):
                raise ValueError('Federation ban requires federation review')
            # Mark before remote action. An uncertain result must never be blindly retried.
            appeal['status']='reviewing';self.db.put(chat,'appeals',key,appeal)
            self.e.moderate(chat,appeal['user'],'unban' if record['action']=='ban' else 'unmute',reason='Appeal approved')
        appeal.update(status='approved' if approve else 'rejected',decision_reason=reason,staff=staff,decided=time.time())
        self.db.put(chat,'appeals',key,appeal)
        self.e.say(appeal['user'],'Appeal '+appeal['status']+': '+reason)

    def membership(self,update):
        if update.get('from',{}).get('id')!=self.e.me['id']:
            self.db.delete(update['chat']['id'],'bot_actions',update['new_chat_member']['user']['id'])

    def job(self,kind,chat,p):
        if kind=='community_ticket_reminder':
            self.community.reminder(chat,p);return True
        if kind=='raid_expire':
            active=self.db.get(chat,'extensions','raid_active',{})
            if active.get('revision')==p['revision'] and active.get('until',0)<=time.time():
                self.db.delete(chat,'extensions','raid_active')
            return True
        return self.ops.job(kind,chat,p)

    def maintenance(self):
        now=time.time()
        if now-self.last_maintenance<60:return
        self.last_maintenance=now
        for row in self.db.sql("SELECT scope,kind,key,value FROM docs WHERE kind IN ('ui_tokens','ui_inputs','ai_messages','web_changes')"):
            v=json.loads(row['value'])
            expired=v.get('expires',v.get('at',now)+24*3600)<now
            if expired:self.db.delete(row['scope'],row['kind'],row['key'])
        for entry in self.db.sql('SELECT DISTINCT chat FROM events'):
            group=entry['chat']
            days=self.db.get(group,'extensions','retention',self.e.config.retention_days)
            self.db.sql("DELETE FROM events WHERE chat=? AND at<?",(int(group),now-days*86400))
        for row in self.db.sql("SELECT scope,kind,key,value FROM docs WHERE kind IN ('tickets','members','points')"):
            value=json.loads(row['value']);scope=row['scope']
            group=int(scope.removeprefix('community:')) if scope.startswith('community:') else int(scope) if scope.lstrip('-').isdigit() else 0
            days=self.db.get(group,'extensions','retention',self.e.config.retention_days)
            stamp=next((value[k] for k in ('last_seen','last','last_reply','created','joined') if k in value),now)
            if stamp<now-days*86400 and (row['kind']!='tickets' or value.get('status')=='closed'):
                self.db.delete(scope,row['kind'],row['key'])
        directory=os.getenv('NEXORA_BACKUP_DIR','')
        if directory:
            every=max(3600,int(os.getenv('NEXORA_BACKUP_SECONDS','86400')))
            status=self.db.get('global','maintenance','backup',{})
            if now-status.get('at',0)>=every:
                try:status=backups.create(self.db,directory,max(1,min(90,int(os.getenv('NEXORA_BACKUP_KEEP','7')))))
                except (OSError,ValueError,sqlite3.Error) as exc:status={'at':now,'ok':False,'error':type(exc).__name__}
                self.db.put('global','maintenance','backup',status)
