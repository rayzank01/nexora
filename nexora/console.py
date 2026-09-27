"""Authenticated multi-group console endpoints; no Mini App init-data trust."""
from . import plans
import json
import secrets
import time
from .engine import scheduled_time
from .extensions import SAFE_TEMPLATE


def read(engine, access, chat):
    uid=access['user'];engine.require(chat,uid,native=True)
    x=engine.ext
    events={k:{a:b for a,b in v.items() if a!='rsvp'} | {'attending':len(v.get('rsvp',{}))}
            for k,v in engine.db.items(chat,'community_events').items()}
    try:calendar=x.ops.calendar(chat,uid)
    except PermissionError:calendar=[]
    data={'chat':chat,'settings':engine.settings(chat),'calendar':calendar,'events':events,
        'raid':engine.db.get(chat,'extensions','raid',{}), 'active_raid':engine.db.get(chat,'extensions','raid_active'),
        'ai':engine.db.get(chat,'extensions','ai',{}),'retention':engine.db.get(chat,'extensions','retention',engine.config.retention_days),
        'templates':engine.db.items(uid,'templates'),'topics':engine.db.items(chat,'topics'),
        'drafts':list(engine.db.items(f'publisher:{uid}:{chat}','drafts'))}
    if uid in engine.config.support_admins and chat==engine.config.support_chat:
        data['tickets']=engine.db.items('support','tickets')
        data['support_mode']='operator'
    elif x.community.config(chat) and uid in x.community.config(chat)['staff']:
        x.community.staff(chat,uid)
        data['tickets']=engine.db.items(x.community.scope(chat),'tickets')
        data['support_mode']='community'
    data['subscription']=x.billing.plan(chat)
    return data


def mutate(engine, access, data):
    uid=access['user'];chat=int(data.get('chat',access['chat']));action=data['action'];db=engine.db;x=engine.ext
    engine.require(chat,uid,native=True)
    if action=='preview':
        change=data['change']
        if not isinstance(change,dict) or change.get('action') in ('preview','confirm'):
            raise ValueError('Invalid change')
        watched=None
        if change.get('action') in ('event','event_cancel','event_publish') and change.get('id'):
            watched={'kind':'event','id':change['id'],'value':db.get(chat,'community_events',change['id'])}
        if change.get('action') in ('job_cancel','job_move'):
            watched={'kind':'job','id':int(change['job']),'value':db.sql('SELECT * FROM jobs WHERE id=? AND chat=?',(int(change['job']),chat))}
        if change.get('action')=='template_apply':
            watched={'kind':'template','id':change['name'],'value':db.get(uid,'templates',change['name'])}
        token=secrets.token_urlsafe(24)
        db.put('global','web_changes',token,{'user':uid,'chat':chat,'expires':time.time()+300,'change':change,
            'settings':engine.settings(chat),'watched':watched})
        return {'confirmation':token,'change':change}
    if action!='confirm':
        raise ValueError('Preview and confirm changes first')
    key=data['confirmation'];p=db.get('global','web_changes',key)
    if not p or p['user']!=uid or p['chat']!=chat or p['expires']<time.time():raise PermissionError('Confirmation expired or belongs to another administrator')
    db.delete('global','web_changes',key)
    if p['settings']!=engine.settings(chat):raise ValueError('Settings changed since preview; refresh')
    watched=p.get('watched')
    if watched:
        current=db.get(chat,'community_events',watched['id']) if watched['kind']=='event' else db.get(uid,'templates',watched['id']) if watched['kind']=='template' else db.sql('SELECT * FROM jobs WHERE id=? AND chat=?',(watched['id'],chat))
        if current!=watched['value']:raise ValueError('Settings changed since preview; refresh')
    change=p['change'];action=change['action']
    if action=='setting':engine.configure(chat,uid,change['key'],change['value'])
    elif action=='raid_start':
        engine.require(chat,uid,'moderate',native=True);x.raid_start(chat,600,'Administrator request')
    elif action=='raid_end':
        engine.require(chat,uid,'moderate',native=True);db.delete(chat,'extensions','raid_active')
    elif action=='raid_policy':
        policy=change['policy']
        if type(policy.get('enabled')) is not bool:raise ValueError('Invalid raid policy')
        for key,low,high in [('joins',2,100),('spam',2,100),('window',5,300),('seconds',60,3600)]:
            if type(policy.get(key)) is not int or not low<=policy[key]<=high:raise ValueError('Invalid raid threshold')
        db.put(chat,'extensions','raid',policy)
    elif action=='retention':
        days=int(change['days'])
        if not 1<=days<=3650:raise ValueError('Invalid retention')
        db.put(chat,'extensions','retention',days)
    elif action=='template_save':
        plans.require(engine,chat,'ultra')
        db.put(uid,'templates',str(change['name'])[:40],{k:v for k,v in engine.settings(chat).items() if k in SAFE_TEMPLATE})
    elif action=='template_apply':
        plans.require(engine,chat,'ultra')
        values=db.get(uid,'templates',change['name'])
        if not values or not set(values)<=SAFE_TEMPLATE:raise ValueError('Unknown template')
        for key,value in values.items():engine.validate_setting(chat,uid,key,value)
        db.put(chat,'config','settings',{**engine.settings(chat),**values})
    elif action=='topic':x.topic(chat,uid,int(change['topic']),change['key'],change['value'])
    elif action=='event':
        return {'event':x.ops.event(chat,uid,change['title'],scheduled_time(change['date'],engine.settings(chat)['timezone']),change.get('id') or None)}
    elif action=='event_cancel':x.action(uid,uid,chat,'event_cancel',{'event':change['id']})
    elif action=='event_publish':x.ops.event_card(chat,chat,change['id'])
    elif action=='poll':x.ops.poll(chat,uid,change['question'],change['answers'],change.get('correct'))
    elif action=='recurrence':x.ops.recurring(chat,uid,change['draft'],change['time'],change['days'])
    elif action=='job_cancel':x.ops.edit_job(chat,uid,int(change['job']),'cancel')
    elif action=='job_move':x.ops.edit_job(chat,uid,int(change['job']),'move',scheduled_time(change['date'],engine.settings(chat)['timezone']))
    elif action=='ticket':
        if chat==engine.config.support_chat:
            x.ops.ticket(uid,change['ticket'],change['operation'],change.get('value'))
        else:
            x.community.update(chat,uid,change['ticket'],change['operation'],change.get('value'))
    elif action=='ai':
        policy=change['policy']
        if not set(policy)<= {'enabled','capture','external'} or any(type(v) is not bool for v in policy.values()):raise ValueError('Invalid AI setting')
        x.action(uid,uid,chat,'ai_policy',policy)
    elif action=='knowledge':
        text=str(change['text'])[:3000];db.put(chat,'knowledge',str(change['name'])[:40],text)
    elif action=='privacy_delete':x.ops.personal(uid,delete=True)
    else:raise ValueError('Unknown console action')
    return {'ok':True}
