"""Per-group package capabilities. Activation is explicit; quotas never delete data."""
import json
import os

LIMITS={
 'free':{'recurring':1,'scheduled':5,'filters':10,'replies':5,'notes':20,'events':2,'analytics':7},
 'pro':{'recurring':10,'scheduled':50,'filters':100,'replies':50,'notes':100,'events':20,'analytics':90},
 'ultra':{'recurring':50,'scheduled':250,'filters':500,'replies':250,'notes':500,'events':100,'analytics':365}}

class PlanLimit(PermissionError):pass

def enabled():return os.getenv('NEXORA_PLAN_LIMITS')=='1'
def tier(e,chat):return e.ext.billing.plan(chat)['plan']
def limit(e,chat,key):return LIMITS[tier(e,chat)][key]
def allows(e,chat,required='pro'):
    return not enabled() or {'free':0,'pro':1,'ultra':2}[tier(e,chat)]>={'pro':1,'ultra':2}[required]
def require(e,chat,required='pro'):
    if not allows(e,chat,required):raise PlanLimit('This feature requires '+required.title()+'. Use /plans to compare packages.')
def count(e,chat,key,total):
    if enabled() and total>limit(e,chat,key):raise PlanLimit('Package limit reached for '+key+'. Use /plans to compare packages.')
def rule(e,chat,name,value):
    rules=e.db.items(chat,'rules');rules[name]=value
    count(e,chat,'filters',sum(bool(set(r.get('actions',[]))-{'reply'}) for r in rules.values()))
    count(e,chat,'replies',sum('reply' in r.get('actions',[]) for r in rules.values()))
    if 'reply' in value.get('actions',[]) and value.get('type')!='word':require(e,chat)
def job(e,chat,recurring,current=None):
    if not enabled():return
    ids=[]
    for r in e.db.sql("SELECT id,interval,payload FROM jobs WHERE chat=? AND kind='publish' AND status IN ('pending','running','paused') ORDER BY id",(chat,)):
        if bool(r['interval'] or json.loads(r['payload']).get('wallclock'))==bool(recurring):ids.append(r['id'])
    total=ids.index(current)+1 if current in ids else len(ids)+1
    count(e,chat,'recurring' if recurring else 'scheduled',total)
