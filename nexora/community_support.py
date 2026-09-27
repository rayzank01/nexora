"""Explicit, isolated support routing for independent communities."""
import secrets
import time


class CommunitySupport:
    def __init__(self, engine):
        self.e=engine

    @property
    def db(self):
        return self.e.db

    def scope(self,chat):
        return f'community:{chat}'

    def config(self,chat):
        return self.db.get(chat,'extensions','support')

    def validate(self,chat,config):
        inbox=config['inbox'];staff=config['staff']
        if inbox==chat or inbox==self.e.config.support_chat:
            raise ValueError('Use a separate, private staff group for this community')
        if self.e.tg.call('getChat',chat_id=inbox)['type'] not in ('group','supergroup'):
            raise ValueError('The support inbox must be a staff group')
        if self.e.member(inbox,self.e.me['id'])['status'] not in ('member','administrator'):
            raise PermissionError('Add the bot to the staff inbox first')
        for user in staff:
            self.e.require(chat,user,native=True)
            if self.e.member(inbox,user)['status'] not in ('member','administrator','creator'):
                raise PermissionError('Every configured staff member must belong to the inbox')
        # API has no full member enumeration. Count plus explicitly verified staff closes
        # accidental public/shared-inbox routing; see documented membership race limit.
        if self.e.tg.call('getChatMemberCount',chat_id=inbox) != len(staff)+1:
            raise PermissionError('Inbox must contain only the bot and configured staff')
        owner=self.db.get('global','community_inboxes',inbox)
        if owner not in (None,chat):
            raise PermissionError('That support inbox belongs to another community')

    def configure(self,chat,user,inbox,staff):
        self.e.require(chat,user,native=True)
        self.e.require(inbox,user,native=True)
        staff=sorted(set(int(x) for x in staff))
        if not staff or len(staff)>30 or user not in staff:
            raise ValueError('Include yourself and at most 30 authorized staff members')
        config={'inbox':int(inbox),'staff':staff}
        self.validate(chat,config)
        prior=self.config(chat)
        if prior and prior['inbox']!=inbox:
            # Changing inboxes is explicit; old mappings remain private and inaccessible.
            self.db.delete('global','community_inboxes',prior['inbox'])
        self.db.put(chat,'extensions','support',config)
        self.db.put('global','community_inboxes',inbox,chat)

    def staff(self,chat,user,dest=None):
        config=self.config(chat)
        if not config or user not in config['staff'] or dest not in (None,user,config['inbox']):
            raise PermissionError('Community support staff access required')
        self.validate(chat,config)
        return config

    def start(self,user,chat):
        self.db.delete(user,'session','community_support')
        self.db.put(user,'session','support',False)
        if not self.config(chat):raise ValueError('Community support is not configured')
        if self.e.member(chat,user)['status'] in ('left','kicked'):
            raise PermissionError('Current group membership required')
        self.validate(chat,self.config(chat))
        self.db.put(user,'session','support',False)
        self.db.put(user,'session','community_support',chat)
        self.e.say(user,'Your next messages go to this community’s staff. /close ends this conversation.')

    def relay(self,m):
        dest,user=m['chat']['id'],m['from']['id']
        chat=self.db.get('global','community_inboxes',dest)
        if chat is not None:
            self.staff(chat,user,dest)
            if m.get('text','').startswith('/'):
                # Never copy commands (especially notes) into a customer conversation.
                return True
            reply=m.get('reply_to_message',{}).get('message_id')
            key=self.db.get(self.scope(chat),'relay',f'{dest}:{reply}')
            ticket=self.db.get(self.scope(chat),'tickets',key) if key else None
            if ticket and ticket['status']=='open':
                self.e.tg.call('copyMessage',chat_id=ticket['user'],from_chat_id=dest,message_id=m['message_id'])
                ticket['last_reply']=time.time()
                ticket.setdefault('first_response_seconds',time.time()-ticket['created'])
                self.db.put(self.scope(chat),'tickets',key,ticket)
            return True
        if dest<0:return False
        chat=self.db.get(user,'session','community_support')
        if chat is None:return False
        if m.get('text','').startswith('/'):return False
        config=self.config(chat)
        if not config:raise ValueError('Community support is not configured')
        self.validate(chat,config)
        if self.e.member(chat,user)['status'] in ('left','kicked'):
            raise PermissionError('Current group membership required')
        scope=self.scope(chat);last=self.db.get(scope,'last',user,0)
        if time.time()-last<2:raise ValueError('Please wait before sending another support message')
        self.db.put(scope,'last',user,time.time())
        key=self.db.get(scope,'active',user)
        ticket=self.db.get(scope,'tickets',key) if key else None
        if not ticket or ticket['status']!='open':
            key=secrets.token_hex(6);ticket={'user':user,'created':time.time(),'status':'open','priority':'normal','notes':[]}
        ticket['last_inbound']=time.time()
        self.db.put(scope,'tickets',key,ticket);self.db.put(scope,'active',user,key)
        header=self.e.say(config['inbox'],f"Ticket {key} | user {user}\nReply to this header or the copied message.")
        self.db.put(scope,'relay',f"{config['inbox']}:{header['message_id']}",key)
        sent=self.e.tg.call('copyMessage',chat_id=config['inbox'],from_chat_id=dest,message_id=m['message_id'])
        self.db.put(scope,'relay',f"{config['inbox']}:{sent['message_id']}",key)
        self.db.job(chat,'community_ticket_reminder',time.time()+3600,{'ticket':key,'inbound':ticket['last_inbound']})
        self.e.say(user,'Sent to support / സപ്പോർട്ടിലേക്ക് അയച്ചു')
        return True

    def update(self,chat,user,key,action,value=None):
        config=self.staff(chat,user);scope=self.scope(chat)
        ticket=self.db.get(scope,'tickets',key)
        if not ticket:raise ValueError('Unknown ticket')
        if action=='assign':
            if int(value) not in config['staff']:raise PermissionError('Community support staff access required')
            ticket['assignee']=int(value)
        elif action=='priority':
            if value not in ('low','normal','high','urgent'):raise ValueError('Invalid priority')
            ticket['priority']=value
        elif action=='note':
            if not value or len(value)>2000:raise ValueError('Note must be 1–2000 characters')
            ticket.setdefault('notes',[]).append({'staff':user,'at':time.time(),'text':value})
            ticket['notes']=ticket['notes'][-100:]
        elif action=='close':ticket['status']='closed'
        else:raise ValueError('Unknown ticket action')
        self.db.put(scope,'tickets',key,ticket)

    def reminder(self,chat,p):
        config=self.config(chat)
        if not config:return
        self.validate(chat,config)
        ticket=self.db.get(self.scope(chat),'tickets',p['ticket'])
        if ticket and ticket['status']=='open' and ticket.get('last_inbound')==p['inbound'] and ticket.get('last_reply',0)<p['inbound']:
            self.e.say(config['inbox'],'Unresolved support ticket: '+p['ticket'])
