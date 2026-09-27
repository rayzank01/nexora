import ast
import json
import os
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import test_nexora as fixtures
from nexora.console import read,mutate
from nexora.i18n import catalog,translate


class PublicBotTests(unittest.TestCase):
    setUp=fixtures.NexoraTests.setUp
    tearDown=fixtures.NexoraTests.tearDown
    msg=fixtures.NexoraTests.msg
    sent=fixtures.NexoraTests.sent

    def support(self,chat=-100,inbox=-600):
        original=self.tg.call
        def call(method,**args):
            if method=='getChatMemberCount':return 2
            return original(method,**args)
        self.tg.call=call
        self.e.ext.community.configure(chat,1,inbox,[1])

    def test_independent_support_inboxes(self):
        self.support();self.e.ext.community.configure(-101,1,-601,[1])
        for uid,chat in [(2,-100),(3,-101)]:
            self.e.ext.community.start(uid,chat)
            self.e.handle({'message':self.msg('Help',uid=uid,cid=uid)})
        copies=self.sent('copyMessage')
        self.assertEqual([(x['from_chat_id'],x['chat_id']) for x in copies],[(2,-600),(3,-601)])
        self.assertFalse(self.db.items('support','tickets'))
        self.assertEqual(len(self.db.items('community:-100','tickets')),1)
        self.assertEqual(len(self.db.items('community:-101','tickets')),1)

    def test_cannot_share_support_inbox(self):
        self.support()
        with self.assertRaises(PermissionError):self.e.ext.community.configure(-101,1,-600,[1])
        with self.assertRaises(ValueError):self.e.ext.community.configure(-101,1,-500,[1])

    def test_nonstaff_member_blocks_support_delivery(self):
        self.support();self.e.ext.community.start(2,-100)
        original=self.tg.call
        self.tg.call=lambda method,**args:3 if method=='getChatMemberCount' else original(method,**args)
        with self.assertRaises(PermissionError):self.e.ext.community.relay(self.msg('private',uid=2,cid=2))
        self.assertFalse(self.sent('copyMessage'))

    def test_support_staff_revocation_blocks_routing(self):
        self.support();self.e.ext.community.start(2,-100)
        self.tg.members[-100,1]={'status':'member'}
        with self.assertRaises(PermissionError):self.e.ext.community.relay(self.msg('private',uid=2,cid=2))
        self.assertFalse(self.sent('copyMessage'))

    def test_failed_community_selection_clears_previous_route(self):
        self.support();self.e.ext.community.start(2,-100)
        with self.assertRaises(ValueError):self.e.ext.community.start(2,-102)
        self.assertIsNone(self.db.get(2,'session','community_support'))
        self.assertFalse(self.e.ext.community.relay(self.msg('private',uid=2,cid=2)))

    def test_community_staff_reply_notes_and_wrong_group(self):
        self.support();self.e.ext.community.start(2,-100)
        self.e.ext.community.relay(self.msg('help',uid=2,cid=2))
        key=next(iter(self.db.items('community:-100','tickets')))
        header=self.sent('sendMessage')[-2]['text']
        self.e.ext.community.update(-100,1,key,'note','Internal only')
        self.assertNotIn('Internal only',str(self.sent('copyMessage')))
        with self.assertRaises(PermissionError):self.e.ext.community.update(-101,1,key,'close')
        mapping=next(iter(self.db.items('community:-100','relay')));mid=int(mapping.split(':')[1])
        self.e.ext.community.relay(self.msg('Staff reply',cid=-600,reply={'message_id':mid}))
        self.assertEqual(self.sent('copyMessage')[-1]['chat_id'],2)
        self.assertIn('first_response_seconds',self.db.get('community:-100','tickets',key))

    def test_community_notes_not_in_personal_export_and_delete_isolation(self):
        self.support();self.e.ext.community.start(2,-100);self.e.ext.community.relay(self.msg('Help',uid=2,cid=2))
        key=next(iter(self.db.items('community:-100','tickets')))
        self.e.ext.community.update(-100,1,key,'note','Staff secret')
        self.db.put('community:-101','tickets','other',{'user':3,'status':'open'})
        personal=self.e.ext.ops.personal(2)
        self.assertNotIn('Staff secret',json.dumps(personal));self.assertNotIn('other',json.dumps(personal))
        self.e.ext.ops.personal(2,True)
        self.assertFalse(self.db.items('community:-100','tickets'))
        self.assertTrue(self.db.items('community:-101','tickets'))

    def test_staff_inbox_commands_are_not_relayed(self):
        self.support();self.e.ext.community.start(2,-100);self.e.ext.community.relay(self.msg('Help',uid=2,cid=2))
        mid=int(next(iter(self.db.items('community:-100','relay'))).split(':')[1]);before=len(self.sent('copyMessage'))
        self.e.ext.community.relay(self.msg('/not-a-customer-message',cid=-600,reply={'message_id':mid}))
        self.assertEqual(len(self.sent('copyMessage')),before)

    def test_bulk_template_all_permissions_before_any_change(self):
        self.db.put(1,'templates','policy',{'warn_limit':7})
        p=self.e.ext.bulk_preview(1,'policy',[-100,-101])
        self.tg.members[-101,1]={'status':'member'}
        with self.assertRaises(PermissionError):self.e.ext.bulk_apply(1,p)
        self.assertEqual(self.e.settings(-100)['warn_limit'],3)

    def test_bulk_template_stale_second_group_rejects_all(self):
        self.db.put(1,'templates','policy',{'warn_limit':7})
        p=self.e.ext.bulk_preview(1,'policy',[-100,-101])
        self.e.configure(-101,1,'warn_limit',9)
        with self.assertRaises(ValueError):self.e.ext.bulk_apply(1,p)
        self.assertEqual(self.e.settings(-100)['warn_limit'],3)

    def test_bulk_template_success_and_no_secret_fields(self):
        self.db.put(1,'templates','policy',{'warn_limit':7})
        p=self.e.ext.bulk_preview(1,'policy',[-100,-101]);self.e.ext.bulk_apply(1,p)
        self.assertEqual([self.e.settings(c)['warn_limit'] for c in (-100,-101)],[7,7])
        self.db.put(1,'templates','bad',{'log_chat':-100})
        with self.assertRaises(ValueError):self.e.ext.bulk_preview(1,'bad',[-101])

    def test_filter_wizard_tests_before_enabling(self):
        x=self.e.ext;x.prompt(1,1,-100,{'kind':'filter','topic':0})
        x.input(self.msg('spam | word | spam | delete',cid=1))
        self.assertFalse(self.db.items(-100,'rules'))
        x.input(self.msg('spam sample',cid=1))
        self.assertFalse(self.db.items(-100,'rules'));self.assertFalse(self.sent('deleteMessage'))
        token=next(d['reply_markup']['inline_keyboard'][0][0]['callback_data'] for d in reversed(self.sent('sendMessage')) if 'inline_keyboard' in d.get('reply_markup',{}))
        x.callback({'id':'q','data':token,'from':{'id':1},'message':{'chat':{'id':1}}})
        self.assertIn('spam',self.db.items(-100,'rules'))

    def test_billing_disabled_by_default(self):
        with patch.dict(os.environ,{},clear=True):
            with self.assertRaises(ValueError):self.e.ext.billing.invoice(-100,1)
        self.assertFalse(self.sent('createInvoiceLink'))
        self.assertEqual(self.e.ext.billing.plan(-100),{'plan':'free','expires':0,'enforced':False})

    def order(self):
        self.db.put('billing','orders','order',{'chat':-100,'user':1,'amount':100,'status':'new','expires':time.time()+600})
        return {'currency':'XTR','total_amount':100,'invoice_payload':'order','telegram_payment_charge_id':'charge1',
                'subscription_expiration_date':int(time.time()+2592000),'is_recurring':True,'is_first_recurring':True}

    def receipt(self,p,uid=1):
        self.e.ext.billing.receipt(self.msg(uid=uid,cid=uid,successful_payment=p))

    def test_receipt_grants_group_not_payer_privilege_and_is_idempotent(self):
        p=self.order();self.receipt(p);self.receipt(p)
        self.assertEqual(len(self.db.items('billing','charges')),1)
        self.assertEqual(self.e.ext.billing.plan(-100)['plan'],'pro')
        self.assertEqual(self.e.ext.billing.plan(-101)['plan'],'free')
        self.tg.members[-100,1]={'status':'member'}
        with self.assertRaises(PermissionError):self.e.require(-100,1,native=True)

    def test_receipt_wrong_payer_currency_and_price(self):
        p=self.order()
        with self.assertRaises(PermissionError):self.receipt(p,2)
        with self.assertRaises(PermissionError):self.receipt(dict(p,total_amount=1))
        with self.assertRaises(PermissionError):self.receipt(dict(p,currency='USD'))
        self.assertEqual(self.e.ext.billing.plan(-100)['plan'],'free')

    def test_renewal_uses_receipt_expiry_not_duplicate_extension(self):
        p=self.order();self.receipt(p)
        new=dict(p,telegram_payment_charge_id='charge2',is_first_recurring=False,subscription_expiration_date=p['subscription_expiration_date']+60)
        self.receipt(new);self.receipt(new)
        self.assertEqual(self.e.ext.billing.plan(-100)['expires'],new['subscription_expiration_date'])

    def test_refund_event_idempotency_and_out_of_order(self):
        p=self.order();refund={k:p[k] for k in ('currency','total_amount','invoice_payload','telegram_payment_charge_id')}
        self.e.ext.billing.receipt({'chat':{'id':1,'type':'private'},'refunded_payment':refund},True)
        self.receipt(p);self.assertEqual(self.e.ext.billing.plan(-100)['plan'],'free')

    def test_precheckout_wrong_payer_and_revoked_admin(self):
        self.order();q={'id':'q','from':{'id':2},'currency':'XTR','total_amount':100,'invoice_payload':'order'}
        env={'NEXORA_BILLING_ENABLED':'1','NEXORA_PRO_STARS':'100','NEXORA_BILLING_TERMS':'Test terms only'}
        with patch.dict(os.environ,env,clear=True):
            self.e.ext.billing.precheckout(q);self.assertFalse(self.sent('answerPreCheckoutQuery')[-1]['ok'])
            q['from']['id']=1;self.e.ext.billing.precheckout(q);self.assertTrue(self.sent('answerPreCheckoutQuery')[-1]['ok'])
            self.tg.members[-100,1]={'status':'member'};self.e.ext.billing.precheckout(q)
            self.assertFalse(self.sent('answerPreCheckoutQuery')[-1]['ok'])

    def test_invoice_uses_stars_and_current_period(self):
        with patch.dict(os.environ,{'NEXORA_BILLING_ENABLED':'1','NEXORA_PRO_STARS':'100','NEXORA_BILLING_TERMS':'Test terms only'},clear=True):
            self.e.ext.billing.invoice(-100,1)
        call=self.sent('createInvoiceLink')[-1]
        self.assertEqual(call['currency'],'XTR');self.assertEqual(call['subscription_period'],2592000)

    def test_cancellation_keeps_paid_period_and_checks_payer(self):
        self.receipt(self.order())
        with self.assertRaises(PermissionError):self.e.ext.billing.cancel(2,'order')
        self.e.ext.billing.cancel(1,'order');self.e.ext.billing.cancel(1,'order')
        self.assertEqual(len(self.sent('editUserStarSubscription')),1)
        self.assertEqual(self.e.ext.billing.plan(-100)['plan'],'pro')

    def test_refund_operator_only_and_single_attempt(self):
        self.receipt(self.order())
        with self.assertRaises(PermissionError):self.e.ext.billing.refund(1,'charge1')
        self.config.super_admins={1};self.e.ext.billing.refund(1,'charge1');self.e.ext.billing.refund(1,'charge1')
        self.assertEqual(len(self.sent('refundStarPayment')),1)
        self.assertEqual(self.e.ext.billing.plan(-100)['plan'],'free')

    def test_downgrade_preserves_data_and_moderation(self):
        p=self.order();p['subscription_expiration_date']=int(time.time()-1);self.receipt(p)
        self.e.add_rule(-100,1,'safety',{'type':'word','match':'spam','actions':['delete']})
        self.assertEqual(self.e.ext.billing.plan(-100)['plan'],'free')
        self.e.apply_rules(self.msg('spam',uid=2));self.assertTrue(self.sent('deleteMessage'))
        self.assertIn('safety',self.db.items(-100,'rules'))

    def test_restore_freezes_financial_operations(self):
        self.db.put('billing','recovery','blocked',True)
        with self.assertRaises(ValueError):self.e.ext.billing.settings()
        self.config.super_admins={1}
        with self.assertRaises(ValueError):self.e.ext.billing.refund(1,'charge')

    def test_public_onboarding_without_operator_allowlist(self):
        self.e.command(self.msg('/start',uid=2,cid=2))
        self.assertTrue(any('inline_keyboard' in m.get('reply_markup',{}) for m in self.sent('sendMessage')))
        self.tg.members[-101,22]={'status':'administrator'}
        self.e.command(self.msg('/panel',uid=22,cid=-101))
        self.assertEqual(self.sent('sendMessage')[-1]['text'],'Nexora control panel')

    def test_private_language_and_localized_menus(self):
        self.e.command(self.msg('/language ml',uid=2,cid=2))
        self.assertEqual(self.e.settings(2)['language'],'ml')
        self.e.configure(-100,1,'language','ml');self.e.command(self.msg('/panel'))
        self.assertEqual(self.sent('sendMessage')[-1]['text'],translate('Nexora control panel','ml'))
        self.assertNotEqual(self.e.settings(-100)['welcome'],'Welcome {first_name} to {chat_title}!')

    def test_topic_flood_counters_do_not_bleed(self):
        self.e.configure(-100,1,'flood_count',1);self.e.configure(-100,1,'repeat_count',99)
        self.e.apply_rules(self.msg('first',uid=2,message_thread_id=1))
        self.e.apply_rules(self.msg('second',uid=2,message_thread_id=2))
        self.assertFalse(self.sent('restrictChatMember'))

    def test_legacy_cancel_job_command_preserved(self):
        self.db.put(1,'session','channel',-100)
        jid=self.db.job(-100,'publish',time.time()+1000,{'actor':1})
        self.e.command(self.msg('/cancel '+str(jid),cid=1))
        self.assertEqual(self.db.sql('SELECT status FROM jobs WHERE id=?',(jid,))[0]['status'],'cancelled')


if __name__=='__main__':unittest.main()
