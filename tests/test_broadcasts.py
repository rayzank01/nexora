import json
import time
import unittest

import test_nexora as fixtures


class BroadcastTests(unittest.TestCase):
    setUp = fixtures.NexoraTests.setUp
    tearDown = fixtures.NexoraTests.tearDown
    msg = fixtures.NexoraTests.msg
    sent = fixtures.NexoraTests.sent

    def prepare(self, audience='all'):
        self.config.super_admins = {1}
        self.e.superadmin.remember({'id':2,'type':'private'}, {'id':2})
        self.e.superadmin.remember(self.chat)
        self.e.command(self.msg('/announce ' + audience + ' Test announcement',cid=1))
        return next(iter(self.db.items('global','campaigns')))

    def confirm(self, cid):
        self.e.command(self.msg('/announce_send ' + cid + ' CONFIRM',cid=1))

    def test_group_admin_is_not_superadmin(self):
        with self.assertRaises(PermissionError):
            self.e.command(self.msg('/announce all hello',cid=1))

    def test_superadmin_console_is_private_only(self):
        self.config.super_admins={1}
        with self.assertRaises(PermissionError):
            self.e.command(self.msg('/superadmin',cid=-100))

    def test_preview_does_not_queue_or_broadcast(self):
        self.prepare()
        self.assertFalse(self.db.sql("SELECT * FROM jobs WHERE kind='super_broadcast'"))
        self.assertTrue(all(m['chat_id']==1 for m in self.sent('sendMessage')))

    def test_explicit_confirmation_required(self):
        cid=self.prepare()
        with self.assertRaises(ValueError):
            self.e.command(self.msg('/announce_send '+cid,cid=1))

    def test_confirmation_consumed_once(self):
        cid=self.prepare();self.confirm(cid)
        with self.assertRaises(ValueError): self.confirm(cid)
        self.assertEqual(len(self.db.sql("SELECT * FROM jobs WHERE kind='super_broadcast'")),2)

    def test_expired_preview_rejected(self):
        cid=self.prepare();c=self.db.get('global','campaigns',cid)
        c['expires']=0;self.db.put('global','campaigns',cid,c)
        with self.assertRaises(ValueError): self.confirm(cid)

    def test_other_superadmin_cannot_send_campaign(self):
        cid=self.prepare();self.config.super_admins.add(3)
        with self.assertRaises(PermissionError):
            self.e.command(self.msg('/announce_send '+cid+' CONFIRM',cid=3,uid=3))

    def test_delivers_to_observed_users_and_admin_groups(self):
        cid=self.prepare();self.confirm(cid)
        self.db.sql("UPDATE jobs SET due=0 WHERE kind='super_broadcast'");self.e.tick()
        self.assertEqual({x['chat_id'] for x in self.sent('sendMessage') if x['chat_id']!=1},{2,-100})

    def test_user_optout_rechecked_at_delivery(self):
        cid=self.prepare('users');self.confirm(cid)
        self.db.put('support','subscribers',2,False);self.e.tick()
        self.assertFalse([x for x in self.sent('sendMessage') if x['chat_id']==2])
        self.assertEqual(self.db.get('campaign:'+cid,'delivery',2)['status'],'skipped')

    def test_group_admin_removal_rechecked(self):
        cid=self.prepare('groups');self.confirm(cid)
        self.tg.members[-100,999]={'status':'member'};self.e.tick()
        self.assertFalse([x for x in self.sent('sendMessage') if x['chat_id']==-100])

    def test_operator_revocation_stops_deliveries(self):
        cid=self.prepare();self.confirm(cid)
        self.config.super_admins.clear()
        self.db.sql("UPDATE jobs SET due=0 WHERE kind='super_broadcast'");self.e.tick()
        self.assertTrue(all(x['chat_id']==1 for x in self.sent('sendMessage')))

    def test_cancel_pending_campaign(self):
        cid=self.prepare();self.confirm(cid)
        self.e.command(self.msg('/announce_cancel '+cid,cid=1))
        self.e.tick()
        self.assertEqual({r['status'] for r in self.db.sql("SELECT status FROM jobs WHERE kind='super_broadcast'")},{'cancelled'})

    def test_failed_and_skipped_results_visible(self):
        cid=self.prepare('users');self.confirm(cid)
        self.db.put('support','subscribers',2,False);self.e.tick()
        self.e.command(self.msg('/announce_status '+cid,cid=1))
        self.assertIn('skipped',self.sent('sendMessage')[-1]['text'])


if __name__ == '__main__':
    unittest.main()
