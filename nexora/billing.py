"""Disabled-by-default Telegram Stars subscriptions, scoped to a group, never a role."""
import json
import os
import secrets
import time
import calendar
from datetime import datetime, timezone

PERIOD=2592000


class Billing:
    def __init__(self,engine):self.e=engine

    @property
    def db(self):return self.e.db

    def settings(self):
        if self.db.get('billing','recovery','blocked',False):raise ValueError('Reconcile payment records after restore before enabling billing')
        price=int(os.getenv('NEXORA_PRO_STARS','0'))
        terms=os.getenv('NEXORA_BILLING_TERMS','')
        enabled=os.getenv('NEXORA_BILLING_ENABLED')=='1'
        if not enabled or not 1<=price<=10000 or not terms or not self.e.config.support_chat or not self.e.config.support_admins:
            raise ValueError('Billing is not enabled or fully configured')
        return price,terms

    def plan(self,chat):
        now=time.time();expires=0;tier='free'
        for charge in self.db.items('billing','charges').values():
            order=self.db.get('billing','orders',charge['payload'],{})
            groups=order.get('groups',[charge['chat']])
            candidate=order.get('product','pro')
            if chat in groups and not charge.get('refunded') and charge['expires']>now:
                if candidate=='ultra' or tier!='ultra':
                    if candidate!=tier:expires=0
                    tier=candidate;expires=max(expires,charge['expires'])
        return {'plan':tier,'expires':expires,'enforced':os.getenv('NEXORA_PLAN_LIMITS')=='1'}

    def package_settings(self,product):
        self.settings()
        if product not in ('pro','ultra'):raise ValueError('Choose Pro or Ultra')
        price=int(os.getenv('NEXORA_PRO_STARS' if product=='pro' else 'NEXORA_ULTRA_STARS','0'))
        if not 1<=price<=10000:raise ValueError('Package Stars price is not configured')
        return price,os.environ['NEXORA_BILLING_TERMS']

    def buy(self,product,user,groups):
        price,terms=self.package_settings(product)
        groups=list(dict.fromkeys(map(int,groups)))
        if not 1<=len(groups)<=(6 if product=='pro' else 1):raise ValueError('Pro covers up to six groups; Ultra covers one')
        for chat in groups:
            self.e.require(chat,user,native=True)
            if self.plan(chat)['plan']!='free':raise ValueError('A selected group already has a paid plan')
        payload=secrets.token_urlsafe(24)
        order={'product':product,'groups':groups,'chat':groups[0],'user':user,'amount':price,
               'created':time.time(),'expires':time.time()+900,'status':'new','terms':terms}
        self.db.put('billing','orders',payload,order)
        description='Six group slots for three calendar months; one-time payment' if product=='pro' else 'One group for 30 days; renews automatically'
        link=self.e.tg.call('createInvoiceLink',title='Nexora '+product.title(),description=description,
            payload=payload,provider_token='',currency='XTR',prices=[{'label':product.title(),'amount':price}],
            **({'subscription_period':PERIOD} if product=='ultra' else {}))
        self.e.say(user,link)
        return payload

    def assign(self,user,payload,chat):
        order=self.db.get('billing','orders',payload)
        if not order or order['user']!=user or order.get('product')!='pro':raise PermissionError('This Pro package belongs to another payer')
        if not any(c['payload']==payload and not c.get('refunded') and c['expires']>time.time() for c in self.db.items('billing','charges').values()):raise ValueError('Package is inactive')
        self.e.require(chat,user,native=True)
        if chat in order['groups']:return
        if len(order['groups'])>=6:raise ValueError('All six group slots are assigned')
        if self.plan(chat)['plan']!='free':raise ValueError('This group already has a paid plan')
        order['groups'].append(chat);self.db.put('billing','orders',payload,order)

    def cancel_package(self,user,payload):
        if self.db.get('billing','recovery','blocked',False):raise ValueError('Reconcile payment records after restore before enabling billing')
        order=self.db.get('billing','orders',payload)
        if not order or order['user']!=user:raise PermissionError('This subscription belongs to another payer')
        if order.get('product')!='pro':self.cancel(user,payload)
        eligible=[(key,c) for key,c in self.db.items('billing','charges').items() if c['payload']==payload and not c.get('refunded') and c.get('paid_at',0)>=time.time()-604800]
        for key,charge in eligible:self.refund_charge(key,charge)
        self.e.say(user,'Eligible payments refunded in Stars. Paid access ends for refunded payments.' if eligible else 'No payment is within the seven-day refund window. Existing paid access continues until expiry.')

    def invoice(self,chat,user):
        price,terms=self.settings();self.e.require(chat,user,native=True)
        if self.plan(chat)['plan']=='pro':raise ValueError('This group already has an active subscription')
        payload=secrets.token_urlsafe(24)
        order={'chat':chat,'user':user,'amount':price,'created':time.time(),'expires':time.time()+900,'status':'new','terms':terms}
        self.db.put('billing','orders',payload,order)
        link=self.e.tg.call('createInvoiceLink',title='Nexora Pro',description=f'Group {chat}: 30-day recurring subscription',
            payload=payload,provider_token='',currency='XTR',prices=[{'label':'Pro','amount':price}],subscription_period=PERIOD)
        self.e.say(user,link)
        return payload

    def precheckout(self,q):
        ok=False
        try:
            self.settings();order=self.db.get('billing','orders',q['invoice_payload'])
            if not order or order['user']!=q['from']['id'] or order['amount']!=q['total_amount'] or q['currency']!='XTR' or order['expires']<time.time() or order['status']!='new':
                raise ValueError('Payment does not match the approved order')
            for chat in order.get('groups',[order['chat']]):
                self.e.require(chat,q['from']['id'],native=True)
                if self.plan(chat)['plan']!='free':raise ValueError('This group already has an active subscription')
            if order.get('product'):self.package_settings(order['product'])
            ok=True
        except (ValueError,PermissionError,KeyError):pass
        from .i18n import translate
        self.e.tg.call('answerPreCheckoutQuery',pre_checkout_query_id=q['id'],ok=ok,
            **({} if ok else {'error_message':translate('Payment is unavailable. Contact /paysupport.',self.e.settings(q['from']['id'])['language'])}))

    def receipt(self,m,refund=False):
        p=m['refunded_payment' if refund else 'successful_payment'];uid=m['chat']['id'] if refund else m.get('from',{}).get('id')
        if m['chat']['type']!='private' or m['chat']['id']!=uid:raise PermissionError('Private payment receipt required')
        order=self.db.get('billing','orders',p['invoice_payload']);charge_id=p['telegram_payment_charge_id']
        if not order or order['user']!=uid or p['currency']!='XTR' or p['total_amount']!=order['amount']:
            raise PermissionError('Payment does not match the approved order')
        previous=self.db.get('billing','charges',charge_id)
        if previous:
            if previous['payload']!=p['invoice_payload'] or previous['user']!=uid:raise PermissionError('Conflicting payment receipt')
            if refund and not previous.get('refunded'):
                previous['refunded']=True;self.db.put('billing','charges',charge_id,previous)
            return
        if refund:
            # Preserve out-of-order refunds. A later success cannot resurrect entitlement.
            self.db.put('billing','charges',charge_id,{'chat':order['chat'],'user':uid,'expires':0,
                'payload':p['invoice_payload'],'refunded':True,'amount':order['amount']})
            return
        paid_at=m.get('date',int(time.time()))
        if type(paid_at) is not int or paid_at>time.time()+300:raise ValueError('Invalid payment date')
        if order.get('product')=='pro':
            if p.get('is_recurring') or order['status']!='new':raise ValueError('Invalid Pro package receipt')
            start=datetime.fromtimestamp(paid_at,timezone.utc)
            month=start.month+3;year=start.year+(month-1)//12;month=(month-1)%12+1
            expiry=start.replace(year=year,month=month,day=min(start.day,calendar.monthrange(year,month)[1])).timestamp()
        else:
            expiry=p.get('subscription_expiration_date')
            if not p.get('is_recurring') or type(expiry) is not int or expiry>time.time()+PERIOD+86400:raise ValueError('Invalid subscription receipt')
            if order['status']=='new' and not p.get('is_first_recurring'):raise ValueError('Initial subscription receipt required')
            if order['status']=='active' and p.get('is_first_recurring'):raise ValueError('Duplicate initial subscription')
        charge={'chat':order['chat'],'user':uid,'expires':expiry,'payload':p['invoice_payload'],
                'amount':order['amount'],'refunded':False,'paid_at':paid_at}
        order['status']='active';order.setdefault('subscription_charge',charge_id)
        with self.db.lock,self.db.conn:
            self.db.conn.execute('INSERT INTO docs VALUES(?,?,?,?)',('billing','charges',charge_id,json.dumps(charge)))
            self.db.conn.execute('UPDATE docs SET value=? WHERE scope=? AND kind=? AND key=?',(json.dumps(order),'billing','orders',p['invoice_payload']))

    def cancel(self,user,payload):
        order=self.db.get('billing','orders',payload)
        if not order or order['user']!=user or not order.get('subscription_charge'):
            raise PermissionError('This subscription belongs to another payer')
        if order.get('cancelled'):return
        self.e.tg.call('editUserStarSubscription',user_id=user,telegram_payment_charge_id=order['subscription_charge'],is_canceled=True)
        order['cancelled']=True;self.db.put('billing','orders',payload,order)

    def refund(self,operator,charge_id):
        if self.db.get('billing','recovery','blocked',False):raise ValueError('Reconcile payment records after restore before enabling billing')
        if not self.e.superadmin.allowed(operator):raise PermissionError('Private super-admin access required')
        charge=self.db.get('billing','charges',charge_id)
        if not charge:raise ValueError('Unknown payment')
        if charge.get('refunded'):return
        self.refund_charge(charge_id,charge)

    def refund_charge(self,charge_id,charge):
        # Remote ambiguity is left for reconciliation; never silently retry money operations.
        if charge.get('refund_attempt'):raise ValueError('Refund needs reconciliation before another attempt')
        charge['refund_attempt']=time.time();self.db.put('billing','charges',charge_id,charge)
        self.e.tg.call('refundStarPayment',user_id=charge['user'],telegram_payment_charge_id=charge_id)
        charge['refunded']=True;self.db.put('billing','charges',charge_id,charge)
