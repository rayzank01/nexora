import json
import os
import time
import unittest
from unittest.mock import patch
from datetime import datetime,timezone
import test_nexora as fixtures
from nexora import plans

class PackageTests(unittest.TestCase):
    setUp=fixtures.NexoraTests.setUp
    tearDown=fixtures.NexoraTests.tearDown
    msg=fixtures.NexoraTests.msg
    sent=fixtures.NexoraTests.sent
    env={'NEXORA_BILLING_ENABLED':'1','NEXORA_PRO_STARS':'100','NEXORA_ULTRA_STARS':'100','NEXORA_BILLING_TERMS':'Synthetic test terms'}

    def buy(self,product='pro',groups=None):
        with patch.dict(os.environ,self.env):return self.e.ext.billing.buy(product,1,groups or [-100])
    def pay(self,key,product='pro',date=None,charge='charge'):
        p={'currency':'XTR','total_amount':100,'invoice_payload':key,'telegram_payment_charge_id':charge}
        if product=='ultra':p.update(is_recurring=True,is_first_recurring=True,subscription_expiration_date=int(time.time()+2592000))
        self.e.ext.billing.receipt(self.msg(cid=1,date=int(date or time.time()),successful_payment=p))
        return p

    def test_pro_one_time_six_groups_three_calendar_months(self):
        groups=list(range(-106,-100));key=self.buy(groups=groups)
        self.assertNotIn('subscription_period',self.sent('createInvoiceLink')[-1])
        stamp=int(datetime(2026,1,31,tzinfo=timezone.utc).timestamp());self.pay(key,date=stamp)
        expiry=self.db.get('billing','charges','charge')['expires']
        self.assertEqual(datetime.fromtimestamp(expiry,timezone.utc),datetime(2026,4,30,tzinfo=timezone.utc))
        self.assertEqual(self.db.get('billing','orders',key)['groups'],groups)

    def test_bundle_entitlement_all_six_not_seventh(self):
        groups=list(range(-106,-100));key=self.buy(groups=groups);self.pay(key)
        for g in groups:self.assertEqual(self.e.ext.billing.plan(g)['plan'],'pro')
        self.assertEqual(self.e.ext.billing.plan(-107)['plan'],'free')
        with self.assertRaises(ValueError):self.buy(groups=groups+[-107])

    def test_bundle_rejects_one_unauthorized_destination(self):
        self.tg.members[-101,1]={'status':'member'}
        with self.assertRaises(PermissionError):self.buy(groups=[-100,-101])
        self.assertFalse(self.sent('createInvoiceLink'))

    def test_bundle_unused_slots_require_owner_and_native_rights(self):
        key=self.buy();self.pay(key)
        with self.assertRaises(PermissionError):self.e.ext.billing.assign(2,key,-101)
        self.e.ext.billing.assign(1,key,-101)
        self.assertEqual(self.e.ext.billing.plan(-101)['plan'],'pro')
        self.tg.members[-102,1]={'status':'member'}
        with self.assertRaises(PermissionError):self.e.ext.billing.assign(1,key,-102)

    def test_ultra_is_thirty_day_recurring_one_group(self):
        key=self.buy('ultra');self.pay(key,'ultra')
        self.assertEqual(self.sent('createInvoiceLink')[-1]['subscription_period'],2592000)
        self.assertEqual(self.e.ext.billing.plan(-100)['plan'],'ultra')
        with self.assertRaises(ValueError):self.buy('ultra',[-101,-102])

    def test_pro_duplicate_receipt_does_not_extend_expiry(self):
        key=self.buy();p=self.pay(key);expiry=self.db.get('billing','charges','charge')['expires']
        self.e.ext.billing.receipt(self.msg(cid=1,successful_payment=p))
        self.assertEqual(self.db.get('billing','charges','charge')['expires'],expiry)

    def test_cancellation_within_week_refunds_whole_bundle(self):
        key=self.buy(groups=[-100,-101]);self.pay(key)
        self.e.ext.billing.cancel_package(1,key);self.e.ext.billing.cancel_package(1,key)
        self.assertEqual(len(self.sent('refundStarPayment')),1)
        self.assertFalse(self.sent('editUserStarSubscription'))
        for g in [-100,-101]:self.assertEqual(self.e.ext.billing.plan(g)['plan'],'free')

    def test_cancellation_after_week_preserves_paid_access(self):
        key=self.buy();self.pay(key,date=time.time()-8*86400)
        self.e.ext.billing.cancel_package(1,key)
        self.assertFalse(self.sent('refundStarPayment'))
        self.assertEqual(self.e.ext.billing.plan(-100)['plan'],'pro')

    def test_ultra_cancel_refunds_and_stops_renewal(self):
        key=self.buy('ultra');self.pay(key,'ultra');self.e.ext.billing.cancel_package(1,key)
        self.assertTrue(self.sent('editUserStarSubscription')[-1]['is_canceled'])
        self.assertEqual(len(self.sent('refundStarPayment')),1)

    def test_refund_owner_and_restore_guard(self):
        key=self.buy();self.pay(key)
        with self.assertRaises(PermissionError):self.e.ext.billing.cancel_package(2,key)
        self.db.put('billing','recovery','blocked',True)
        with self.assertRaises(ValueError):self.e.ext.billing.cancel_package(1,key)
        self.assertFalse(self.sent('refundStarPayment'))

    def test_free_one_recurring_across_administrators(self):
        self.db.put('publisher:1:-100','drafts','a',{'kind':'text','text':'a'})
        with patch.dict(os.environ,{'NEXORA_PLAN_LIMITS':'1'}):
            self.e.ext.ops.recurring(-100,1,'a','12:00',[0])
            with self.assertRaises(plans.PlanLimit):self.e.ext.ops.recurring(-100,1,'a','13:00',[0])
            self.e.configure(-100,1,'warn_limit',4)
            self.assertEqual(self.e.settings(-100)['warn_limit'],4)

    def test_pro_and_ultra_recurring_limits(self):
        key=self.buy();self.pay(key)
        with patch.dict(os.environ,{'NEXORA_PLAN_LIMITS':'1'}):
            self.assertEqual(plans.limit(self.e,-100,'recurring'),10)
            with self.assertRaises(PermissionError):plans.require(self.e,-100,'ultra')
        key2=self.buy('ultra',[-101]);self.pay(key2,'ultra',charge='ultra')
        with patch.dict(os.environ,{'NEXORA_PLAN_LIMITS':'1'}):self.assertEqual(plans.limit(self.e,-101,'recurring'),50)

    def test_downgrade_preserves_records_but_blocks_excess_job(self):
        key=self.buy();self.pay(key)
        for _ in range(2):jid=self.db.job(-100,'publish',time.time()+50,{'actor':1},60)
        self.e.ext.billing.cancel_package(1,key)
        with patch.dict(os.environ,{'NEXORA_PLAN_LIMITS':'1'}):
            with self.assertRaises(plans.PlanLimit):plans.job(self.e,-100,True,jid)
        self.assertEqual(len(self.db.sql('SELECT * FROM jobs WHERE chat=?',(-100,))),2)

    def test_operator_group_links_private_and_permission_bound(self):
        self.config.super_admins={1};self.e.superadmin.remember({'id':-100,'type':'supergroup','title':'Group'})
        original=self.tg.call
        self.tg.call=lambda method,**kw:dict(original(method,**kw),username='examplegroup') if method=='getChat' else original(method,**kw)
        self.e.command(self.msg('/operator_groups',cid=1))
        link=next(m for m in self.sent('sendMessage') if m.get('reply_markup',{}).get('inline_keyboard'))
        self.assertEqual(link['reply_markup']['inline_keyboard'][0][0]['url'],'https://t.me/examplegroup')
        with self.assertRaises(PermissionError):self.e.superadmin.command(self.msg(cid=2,uid=2),'operator_groups','')

    def test_ads_exclude_paid_groups_and_recheck_upgrade(self):
        self.config.super_admins={1}
        for g in [-100,-101]:self.e.superadmin.remember({'id':g,'type':'supergroup','title':'Group'})
        key=self.buy(groups=[-101]);self.pay(key)
        self.e.command(self.msg('/advertise Example advertisement',cid=1))
        cid,campaign=next(iter(self.db.items('global','campaigns').items()))
        self.assertEqual(campaign['targets'],[{'chat':-100,'kind':'free_group'}])
        self.e.command(self.msg('/announce_send '+cid+' CONFIRM',cid=1))
        key2=self.buy(groups=[-100]);self.pay(key2,charge='second')
        job=self.db.sql("SELECT payload FROM jobs WHERE kind='super_broadcast'")[0]
        self.e.superadmin.deliver(-100,json.loads(job['payload']))
        self.assertEqual(self.db.get('campaign:'+cid,'delivery',-100)['status'],'skipped')

    def test_ads_exclude_staff_inbox_and_removed_bot(self):
        self.db.put('global','community_inboxes',-600,-100)
        self.assertFalse(self.e.superadmin.eligible(-600,'free_group'))
        self.tg.members[-100,999]={'status':'left'}
        self.assertFalse(self.e.superadmin.eligible(-100,'free_group'))

    def test_scheduler_pauses_excess_recurrence_without_sending(self):
        content={'kind':'text','text':'Scheduled'}
        first=self.db.job(-100,'publish',time.time()+100,{'actor':1,'content':content,'scope':'publisher:1:-100','draft':'a'},60)
        second=self.db.job(-100,'publish',time.time()-1,{'actor':1,'content':content,'scope':'publisher:1:-100','draft':'a'},60)
        with patch.dict(os.environ,{'NEXORA_PLAN_LIMITS':'1'}):self.e.tick()
        self.assertEqual(self.db.sql('SELECT status FROM jobs WHERE id=?',(second,))[0]['status'],'paused')
        self.assertFalse(any(m.get('text')=='Scheduled' for m in self.sent('sendMessage')))

    def test_operator_button_rechecks_revoked_access(self):
        self.config.super_admins={1}
        token=self.e.ext.token(1,1,1,'operator_groups',{'page':0})
        self.config.super_admins=set()
        self.e.ext.callback({'id':'q','data':token,'from':{'id':1},'message':{'chat':{'id':1}}})
        self.assertFalse(self.sent('getChat'))

    def test_payment_group_binding_survives_migration(self):
        key=self.buy(groups=[-100,-101]);self.pay(key)
        self.db.migrate(-101,-100101)
        self.assertEqual(self.e.ext.billing.plan(-100101)['plan'],'pro')
        self.assertEqual(self.e.ext.billing.plan(-101)['plan'],'free')

if __name__=='__main__':unittest.main()
