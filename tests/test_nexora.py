import copy
import json
import tempfile
import time
import unittest
import threading
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from nexora.storage import Store
from nexora.engine import Engine, content_types, duration, matches, render, scheduled_time
from nexora.config import PERMISSIONS
from nexora.transport import RemoteError
from nexora.web import authenticate, verify_web, make_server


class FakeTelegram:
    def __init__(self):
        self.calls=[]
        self.members={}
        self.failure=None
        self.counter=100
        self.defaults={p:False for p in PERMISSIONS}
        self.defaults.update(can_send_messages=True,can_send_photos=True,can_send_other_messages=True)

    def call(self,method,**data):
        self.calls.append((method,copy.deepcopy(data)))
        if self.failure and method==self.failure[0]:
            raise self.failure[1]
        cid,uid=data.get('chat_id'),data.get('user_id')
        if method=='getChatMember':
            default={'status':'administrator','can_delete_messages':True,'can_restrict_members':True,
                     'can_invite_users':True,'can_pin_messages':True,'can_post_messages':True} if uid in (1,999) else {'status':'member'}
            return copy.deepcopy(self.members.get((cid,uid),default))
        if method=='getChat':
            return {'id':cid,'type':'channel' if cid==-200 else 'supergroup','title':'Test group', 'permissions':self.defaults.copy()}
        if method=='restrictChatMember':
            self.members[cid,uid]={'status':'restricted','is_member':True,'until_date':data.get('until_date',0),**data['permissions']}
        if method=='banChatMember':
            self.members[cid,uid]={'status':'kicked'}
        if method=='unbanChatMember':
            self.members[cid,uid]={'status':'left'}
        if method=='getChatAdministrators':
            return [{'user':{'id':1,'first_name':'Admin'}}]
        if method=='createChatInviteLink':
            return {'invite_link':'https://t.me/+example'}
        if method.startswith(('send','copy','forward')):
            self.counter+=1
            return {'message_id':self.counter}
        return True

    def photo(self,chat,png,**data):
        assert png.startswith(b'\x89PNG')
        return self.call('sendPhoto',chat_id=chat,**data)


class NexoraTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=Store(str(Path(self.tmp.name)/'test.db'))
        self.tg=FakeTelegram()
        self.config=SimpleNamespace(public_url='https://nexora.example',support_chat=-500,
            support_admins={1},turnstile_secret='test-secret',turnstile_sitekey='test-site',
            turnstile_hostname='nexora.example',retention_days=90,host='127.0.0.1',port=0)
        self.e=Engine(self.db,self.tg,self.config)
        self.e.me={'id':999,'username':'NexoraBot'}
        self.chat={'id':-100,'type':'supergroup','title':'Test <group>'}
        self.user={'id':2,'first_name':'A <B>','is_bot':False}

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def msg(self,text='',uid=1,cid=-100,reply=None,**extra):
        m={'message_id':50,'chat':{'id':cid,'type':'private' if cid>0 else 'supergroup','title':'Test'},
           'from':{'id':uid,'first_name':'Member'},'text':text,**extra}
        if reply:
            m['reply_to_message']=reply
        return m

    def sent(self,method):
        return [d for n,d in self.tg.calls if n==method]

    def set(self,key,value):
        self.e.configure(-100,1,key,value)

    def test_nonadmin_cannot_configure(self):
        with self.assertRaises(PermissionError): self.e.configure(-100,2,'cas',True)
    def test_roles_chat_isolated(self):
        self.db.put(-100,'roles',2,['moderate'])
        self.e.require(-100,2,'moderate')
        with self.assertRaises(PermissionError): self.e.require(-101,2,'moderate')
    def test_departed_role_cannot_moderate(self):
        self.db.put(-100,'roles',2,['moderate'])
        self.tg.members[-100,2]={'status':'left'}
        with self.assertRaises(PermissionError): self.e.require(-100,2,'moderate')
    def test_native_right_required(self):
        self.tg.members[-100,1]={'status':'administrator','can_restrict_members':False}
        with self.assertRaises(PermissionError): self.e.require(-100,1,'moderate')
    def test_bot_rights_checked(self):
        self.tg.members[-100,999]={'status':'member'}
        with self.assertRaises(PermissionError): self.e.moderate(-100,2,'ban')
        self.assertFalse(self.sent('banChatMember'))
    def test_admin_protected(self):
        with self.assertRaises(PermissionError): self.e.moderate(-100,1,'ban')
    def test_short_timeout_rejected(self):
        with self.assertRaises(ValueError): self.e.moderate(-100,2,'mute',10)
    def test_unmute_uses_group_defaults(self):
        self.e.moderate(-100,2,'unmute')
        self.assertEqual(self.sent('restrictChatMember')[-1]['permissions'],self.tg.defaults)
    def test_timed_ban(self):
        self.e.moderate(-100,2,'ban',120)
        self.assertAlmostEqual(self.sent('banChatMember')[-1]['until_date'],time.time()+120,delta=2)
    def test_expired_warn_not_counted(self):
        self.db.put(-100,'warnings',2,[{'expires':time.time()-1,'reason':'old'}])
        self.assertEqual(self.e.warn(-100,2),1)
    def test_threshold_mutes(self):
        self.set('warn_limit',2)
        self.e.warn(-100,2);self.e.warn(-100,2)
        self.assertEqual(len(self.sent('restrictChatMember')),1)
        self.assertIsNone(self.db.get(-100,'warnings',2))
    def test_word_boundary(self):
        r={'type':'word','match':'ad'}
        self.assertFalse(matches(r,{'text':'address'}))
        self.assertTrue(matches(r,{'text':'An AD!'}))
    def test_hidden_link_domain(self):
        r={'type':'domain','match':'bad.example'}
        self.assertTrue(matches(r,{'text':'safe label','entities':[{'type':'text_link','url':'https://sub.bad.example/path'}]}))
        self.assertFalse(matches(r,{'text':'https://notbad.example'}))
    def test_glob_pattern(self):
        self.assertTrue(matches({'type':'pattern','match':'*free?money*'},{'caption':'GET FREE MONEY HERE'}))
    def test_content_lock_types(self):
        m={'animation':{},'forward_origin':{},'caption_entities':[{'type':'text_link','url':'https://example.com'}]}
        self.assertTrue({'animation','media','forward','links'}<=content_types(m))
    def test_lock_deletes_before_command(self):
        self.set('locks',['links'])
        self.e.handle({'message':self.msg('/help https://example.com',uid=2)})
        self.assertEqual(len(self.sent('deleteMessage')),1)
    def test_admin_reply_rule_does_not_punish(self):
        self.e.add_rule(-100,1,'hello',{'type':'word','match':'hello','audience':'admin','actions':['delete','reply'],'reply':'Hi {first_name}'})
        self.e.apply_rules(self.msg('hello',uid=1))
        self.assertFalse(self.sent('deleteMessage'))
        self.assertEqual(self.sent('sendMessage')[-1]['text'],'Hi Member')
    def test_rule_multiple_actions(self):
        self.e.add_rule(-100,1,'spam',{'type':'phrase','match':'bad deal','actions':['delete','warn','reply'],'reply':'No ads'})
        self.e.apply_rules(self.msg('bad deal',uid=2))
        self.assertTrue(self.sent('deleteMessage'))
        self.assertEqual(len(self.db.get(-100,'warnings',2)),1)
    def test_flood(self):
        self.set('flood_count',2)
        for text in ('a','b','c'): self.e.apply_rules(self.msg(text,uid=2))
        self.assertEqual(len(self.sent('restrictChatMember')),1)
    def test_template_escapes_profiles(self):
        self.assertEqual(render('{first_name}',self.user,self.chat),'A &lt;B&gt;')
    def test_media_note_file_id(self):
        note=self.e.capture({'photo':[{'file_id':'small'},{'file_id':'large'}],'caption':'Hello'})
        self.e.send_content(-100,note)
        self.assertEqual(self.sent('sendPhoto')[-1]['photo'],'large')
    def test_notes_chat_isolation(self):
        self.e.command(self.msg('/save greeting hello'))
        with self.assertRaises(ValueError): self.e.command(self.msg('/get greeting',cid=-101,uid=2))
    def test_captcha_callback_wrong_user(self):
        self.set('captcha','button');self.e.start_captcha(self.chat,self.user)
        c=self.db.get(-100,'captcha',2)
        self.e.handle({'callback_query':{'id':'q','from':{'id':3},'data':'v:'+c['token']}})
        self.assertEqual(self.db.get(-100,'captcha',2)['status'],'pending')
    def test_captcha_single_use(self):
        self.set('captcha','button');self.e.start_captcha(self.chat,self.user)
        self.e.complete_captcha(-100,2)
        with self.assertRaises(ValueError): self.e.complete_captcha(-100,2)
    def test_captcha_restores_previous_restriction(self):
        self.tg.members[-100,2]={'status':'restricted','until_date':0,'can_send_messages':True,'can_send_photos':False}
        self.set('captcha','button');self.e.start_captcha(self.chat,self.user);self.e.complete_captcha(-100,2)
        perms=self.sent('restrictChatMember')[-1]['permissions']
        self.assertFalse(perms['can_send_photos']);self.assertTrue(perms['can_send_messages'])
    def test_new_moderation_supersedes_captcha(self):
        self.set('captcha','button');self.e.start_captcha(self.chat,self.user)
        self.e.moderate(-100,2,'mute',3600)
        with self.assertRaises(ValueError): self.e.complete_captcha(-100,2)
    def test_captcha_attempt_limit(self):
        self.set('captcha','math');self.e.start_captcha(self.chat,self.user)
        for _ in range(5): self.assertFalse(self.e.answer_captcha(-100,2,'wrong'))
        with self.assertRaises(ValueError): self.e.answer_captcha(-100,2,self.db.get(-100,'captcha',2)['answer'])
    def test_captcha_timeout_durable(self):
        self.set('captcha','button');self.e.start_captcha(self.chat,self.user)
        self.db.sql("UPDATE jobs SET due=0 WHERE kind='captcha_expire'")
        self.e.tick()
        self.assertTrue(self.sent('banChatMember'));self.assertTrue(self.sent('unbanChatMember'))
    def test_join_request_approval(self):
        self.set('captcha','button');self.e.start_captcha(self.chat,self.user,request=True,private_chat=2)
        self.assertFalse(self.sent('restrictChatMember'))
        self.e.complete_captcha(-100,2)
        self.assertEqual(self.sent('approveChatJoinRequest')[-1]['user_id'],2)
    def test_image_captcha_png(self):
        self.set('captcha','image');self.e.start_captcha(self.chat,self.user)
        self.e.captcha_prompt(-100,2,2)
        self.assertTrue(self.sent('sendPhoto'))
    def test_turnstile_hostname_check(self):
        self.set('captcha','turnstile');self.e.start_captcha(self.chat,self.user)
        c=self.db.get(-100,'captcha',2)
        with patch('nexora.web.request_json',return_value={'success':True,'hostname':'evil.example','action':'nexora'}):
            with self.assertRaises(ValueError): verify_web(self.e,c['token'],turnstile='token')
    def test_turnstile_success(self):
        self.set('captcha','turnstile');self.e.start_captcha(self.chat,self.user)
        c=self.db.get(-100,'captcha',2)
        with patch('nexora.web.request_json',return_value={'success':True,'hostname':'nexora.example','action':'nexora'}):
            verify_web(self.e,c['token'],turnstile='token')
        self.assertEqual(self.db.get(-100,'captcha',2)['status'],'verified')
    def test_cas_opt_in(self):
        with patch('nexora.engine.request_json') as remote:
            self.e.start_captcha(self.chat,self.user)
            remote.assert_not_called()
    def test_cas_positive(self):
        self.set('cas',True)
        with patch('nexora.engine.request_json',return_value={'ok':True,'result':{'offenses':2}}):
            self.e.start_captcha(self.chat,self.user)
        self.assertTrue(self.sent('banChatMember'))
    def test_dashboard_scope_and_revocation(self):
        token=self.e.dashboard_token(-100,1)
        self.assertEqual(authenticate(self.e,'Bearer '+token)['chat'],-100)
        self.tg.members[-100,1]={'status':'member'}
        with self.assertRaises(PermissionError): authenticate(self.e,'Bearer '+token)
    def test_forged_token(self):
        with self.assertRaises(PermissionError): authenticate(self.e,'Bearer fake')
    def test_publisher_revoked_permission_at_send(self):
        self.e.publisher(self.msg(uid=1,cid=1),'channel','-200')
        self.e.publisher(self.msg(uid=1,cid=1),'draft','hello Hello world')
        self.e.publisher(self.msg(uid=1,cid=1),'publish','hello')
        self.tg.members[-200,1]={'status':'member'}
        self.e.tick()
        self.assertEqual(self.db.sql("SELECT status FROM jobs WHERE kind='publish'")[0]['status'],'failed')
        self.assertFalse([c for c in self.sent('sendMessage') if c['chat_id']==-200])
    def test_schedule_survives_reopen(self):
        self.e.publisher(self.msg(uid=1,cid=1),'channel','-200')
        self.e.publisher(self.msg(uid=1,cid=1),'draft','hello Hello world')
        self.e.publisher(self.msg(uid=1,cid=1),'publish','hello')
        self.db.close();self.db=Store(str(Path(self.tmp.name)/'test.db'));self.e.db=self.db
        self.e.tick()
        self.assertTrue([c for c in self.sent('sendMessage') if c['chat_id']==-200])
        self.assertEqual(self.db.sql("SELECT status FROM jobs WHERE kind='publish'")[0]['status'],'done')
    def test_uncertain_send_not_retried(self):
        self.db.job(-200,'publish',0,{'actor':1,'scope':'p','content':{'kind':'text','text':'hi'}})
        self.tg.failure=('sendMessage',RemoteError())
        self.e.tick();self.e.tick()
        self.assertEqual(len(self.sent('sendMessage')),1)
        self.assertEqual(self.db.sql('SELECT status FROM jobs')[0]['status'],'uncertain')
    def test_rate_limit_requeues(self):
        self.db.job(-200,'publish',0,{'actor':1,'scope':'p','content':{'kind':'text','text':'hi'}})
        self.tg.failure=('sendMessage',RemoteError(429,20));self.e.tick()
        j=self.db.sql('SELECT * FROM jobs')[0]
        self.assertEqual(j['status'],'pending');self.assertGreater(j['due'],time.time()+18)
    def test_recurrence_skips_missed_intervals(self):
        self.db.job(-200,'publish',time.time()-3600,{'actor':1,'scope':'p','content':{'kind':'text','text':'hi'}},60)
        self.e.tick()
        j=self.db.sql('SELECT * FROM jobs')[0]
        self.assertGreater(j['due'],time.time());self.assertEqual(len(self.sent('sendMessage')),1)
    def test_dst_ambiguity_rejected(self):
        with self.assertRaises(ValueError): scheduled_time('2026-10-25T01:30:00','Europe/London')
        self.assertIsInstance(scheduled_time('2026-10-25T01:30:00+01:00','Europe/London'),float)
    def test_support_attached_copy(self):
        self.db.put(2,'session','support',True)
        self.e.relay(self.msg(uid=2,cid=2,document={'file_id':'file'}))
        copies=self.sent('copyMessage')
        self.assertEqual(copies[-1]['chat_id'],-500)
        copied_id=self.tg.counter-1 # final acknowledgement incremented counter
        self.e.relay(self.msg('answer',uid=1,cid=-500,reply={'message_id':copied_id}))
        self.assertEqual(self.sent('copyMessage')[-1]['chat_id'],2)
    def test_support_forged_reply_rejected(self):
        self.db.put('support','tickets','t',{'user':2,'status':'open'})
        self.db.put('support','relay',10,'t')
        self.e.relay(self.msg('attack',uid=3,cid=-500,reply={'message_id':10}))
        self.assertFalse(self.sent('copyMessage'))
    def test_support_mapping_not_valid_other_chat(self):
        self.db.put('support','tickets','t',{'user':2,'status':'open'})
        self.db.put('support','relay',10,'t')
        self.e.relay(self.msg('attack',uid=1,cid=-100,reply={'message_id':10}))
        self.assertFalse(self.sent('copyMessage'))
    def test_unsubscribe_before_broadcast_send(self):
        self.db.put('support','subscribers',2,True)
        self.e.support_command(self.msg(uid=1,cid=1,reply=self.msg('News')),'broadcast','')
        self.db.put('support','subscribers',2,False);self.e.tick()
        self.assertFalse([c for c in self.sent('sendMessage') if c['chat_id']==2])
    def test_duplicate_update_does_not_repeat_action(self):
        update={'update_id':10,'message':self.msg('/ban 2')}
        self.e.process(update);self.e.process(update)
        self.assertEqual(len(self.sent('banChatMember')),1)
    def test_anonymous_sender_no_privileges(self):
        self.e.handle({'message':self.msg('/ban 2',sender_chat={'id':-100})})
        self.assertFalse(self.sent('banChatMember'))
    def test_migration_moves_settings_and_jobs(self):
        self.set('rules','Custom');self.db.job(-100,'delete',0,{'message_id':1})
        self.db.migrate(-100,-101)
        self.assertEqual(self.e.settings(-101)['rules'],'Custom')
        self.assertEqual(self.db.sql('SELECT chat FROM jobs')[0]['chat'],-101)
    def test_stats_per_chat(self):
        self.db.event(-100,2,'message');self.db.event(-101,3,'message')
        self.assertEqual(self.e.stats(-100)['users'],{'2':1})
    def test_xp_rate_limited(self):
        for n in range(2): self.e.handle({'message':self.msg('hello '+str(n),uid=2)})
        self.assertEqual(self.db.get(-100,'points',2)['xp'],1)
    def test_upvote_self_rejected(self):
        with self.assertRaises(ValueError): self.e.command(self.msg('/upvote 2',uid=2))
    def test_federation_nonowner_rejected(self):
        self.db.put('global','fed','f',{'owner':4,'chats':[-100],'bans':{}})
        with self.assertRaises(PermissionError): self.e.federation(self.msg(), 'fedban','f 2')
    def test_federation_leave_cancels_queued_ban(self):
        self.db.put('global','fed','f',{'owner':1,'chats':[],'bans':{'2':'spam'}})
        self.db.job(-100,'fedban',0,{'fed':'f','user':2,'reason':'spam'});self.e.tick()
        self.assertFalse(self.sent('banChatMember'))
    def test_federation_unban_does_not_clear_local_ban(self):
        self.db.put('global','fed','f',{'owner':1,'chats':[-100],'bans':{}})
        self.db.put(-100,'ban_source',2,'local')
        self.db.job(-100,'fedunban',0,{'fed':'f','user':2,'reason':'undo'});self.e.tick()
        self.assertFalse(self.sent('unbanChatMember'))
    def test_telegraph_account_and_edit(self):
        results=[{'ok':True,'result':{'access_token':'secret'}},{'ok':True,'result':{'path':'x','url':'https://telegra.ph/x','title':'Title'}},
                 {'ok':True,'result':{'path':'x','url':'https://telegra.ph/x','title':'New'}}]
        with patch('nexora.engine.request_json',side_effect=results) as remote:
            self.e.telegraph('scope','article','a {"title":"Title","content":[{"tag":"p","children":["Hi"]}]}',1)
            self.e.telegraph('scope','article','a {"title":"New","content":[]}',1)
            self.assertTrue(remote.call_args[0][0].endswith('editPage'))

    def test_http_auth_settings_and_scope(self):
        server=make_server(self.e)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        origin='http://127.0.0.1:'+str(server.server_port)
        try:
            with urlopen(origin+'/health') as r: self.assertEqual(json.load(r)['status'],'ok')
            with self.assertRaises(HTTPError) as caught: urlopen(origin+'/api/stats')
            self.assertEqual(caught.exception.code,403)
            caught.exception.close()
            token=self.e.dashboard_token(-100,1)
            headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'}
            req=Request(origin+'/api/settings',headers=headers,data=json.dumps({'key':'warn_limit','value':5,'chat':-101}).encode())
            with urlopen(req) as r: self.assertTrue(json.load(r)['ok'])
            self.assertEqual(self.e.settings(-100)['warn_limit'],5)
            self.assertEqual(self.e.settings(-101)['warn_limit'],3)
            with urlopen(Request(origin+'/api/stats?chat=-101',headers=headers)) as r:
                self.assertEqual(json.load(r)['chat'],-100)
                self.assertEqual(r.headers['Referrer-Policy'],'no-referrer')
            self.tg.members[-100,1]={'status':'member'}
            with self.assertRaises(HTTPError) as caught: urlopen(Request(origin+'/api/stats',headers=headers))
            self.assertEqual(caught.exception.code,403)
            caught.exception.close()
        finally:
            server.shutdown();server.server_close();thread.join()

    def test_web_captcha_replay(self):
        self.set('captcha','web');self.e.start_captcha(self.chat,self.user)
        c=self.db.get(-100,'captcha',2)
        verify_web(self.e,c['token'],c['answer'])
        with self.assertRaises(ValueError): verify_web(self.e,c['token'],c['answer'])

    def test_external_admin_restriction_cancels_verification(self):
        self.set('captcha','button');self.e.start_captcha(self.chat,self.user)
        self.e.handle({'chat_member':{'chat':self.chat,'from':{'id':1},
            'old_chat_member':{'status':'restricted','is_member':True,'user':self.user},
            'new_chat_member':{'status':'restricted','is_member':True,'user':self.user}}})
        with self.assertRaises(ValueError): self.e.complete_captcha(-100,2)

    def test_previous_restriction_near_expiry_has_restore_job(self):
        self.tg.members[-100,2]={'status':'restricted','until_date':int(time.time()+20),'can_send_messages':False}
        self.set('captcha','button');self.e.start_captcha(self.chat,self.user);self.e.complete_captcha(-100,2)
        self.assertEqual(self.sent('restrictChatMember')[-1]['until_date'],0)
        self.assertEqual(len(self.db.sql("SELECT * FROM jobs WHERE kind='restore_permissions'")),1)
        self.db.sql("UPDATE jobs SET due=0 WHERE kind='restore_permissions'");self.e.tick()
        self.assertEqual(self.sent('restrictChatMember')[-1]['permissions'],self.tg.defaults)

    def test_publisher_migration_rewrites_scope(self):
        self.db.put('publisher:1:-100','drafts','hello',{'kind':'text','text':'hi'})
        self.db.put(1,'session','channel',-100)
        self.db.job(-100,'publish',0,{'actor':1,'scope':'publisher:1:-100','content':{'kind':'text','text':'hi'}})
        self.db.migrate(-100,-101)
        self.assertEqual(self.db.get(1,'session','channel'),-101)
        self.assertIsNotNone(self.db.get('publisher:1:-101','drafts','hello'))
        self.assertEqual(json.loads(self.db.sql('SELECT payload FROM jobs')[0]['payload'])['scope'],'publisher:1:-101')


if __name__=='__main__':
    unittest.main()
