import json
import threading
import time
import unittest
from urllib.request import Request,urlopen
from urllib.error import HTTPError
import test_nexora as fixtures
from nexora.console import mutate
from nexora.web import make_server
from nexora.i18n import translate,catalog

class FinalReviewTests(unittest.TestCase):
    setUp=fixtures.NexoraTests.setUp
    tearDown=fixtures.NexoraTests.tearDown
    msg=fixtures.NexoraTests.msg
    sent=fixtures.NexoraTests.sent

    def preview(self,change):
        return mutate(self.e,{'user':1,'chat':-100},{'action':'preview','change':change})['confirmation']
    def confirm(self,token):
        return mutate(self.e,{'user':1,'chat':-100},{'action':'confirm','confirmation':token})

    def test_event_edit_after_preview_is_preserved(self):
        key=self.e.ext.ops.event(-100,1,'Original',time.time()+7200)
        token=self.preview({'action':'event_cancel','id':key})
        self.e.ext.ops.event(-100,1,'Newer edit',time.time()+9000,key)
        with self.assertRaises(ValueError):self.confirm(token)
        self.assertEqual(self.db.get(-100,'community_events',key)['title'],'Newer edit')

    def test_calendar_job_cancelled_after_preview_is_not_moved(self):
        jid=self.db.job(-100,'publish',time.time()+1000,{'actor':1})
        token=self.preview({'action':'job_move','job':jid,'date':'2027-01-01T10:00:00Z'})
        self.db.sql("UPDATE jobs SET status='cancelled' WHERE id=?",(jid,))
        with self.assertRaises(ValueError):self.confirm(token)
        self.assertEqual(self.db.sql('SELECT status FROM jobs WHERE id=?',(jid,))[0]['status'],'cancelled')

    def test_modified_template_requires_new_preview(self):
        self.db.put(1,'templates','test',{'warn_limit':4})
        token=self.preview({'action':'template_apply','name':'test'})
        self.db.put(1,'templates','test',{'warn_limit':8})
        with self.assertRaises(ValueError):self.confirm(token)
        self.assertEqual(self.e.settings(-100)['warn_limit'],3)

    def test_delegated_roles_cannot_change_native_group_configuration(self):
        self.db.put(-100,'roles',2,['configure','moderate'])
        with self.assertRaises(PermissionError):self.e.configure(-100,2,'warn_limit',8)
        with self.assertRaises(PermissionError):self.e.add_rule(-100,2,'hidden',{'type':'word','match':'x','actions':['delete']})

    def test_album_transmits_order_and_records_all_message_ids(self):
        original=self.tg.call
        def call(method,**data):
            if method=='sendMediaGroup':
                self.assertEqual([x['media'] for x in data['media']],['first','second'])
                return [{'message_id':101},{'message_id':102}]
            return original(method,**data)
        self.tg.call=call
        result=self.e.send_content(-100,{'kind':'album','media':[{'type':'photo','media':'first'},{'type':'video','media':'second'}]})
        self.assertEqual(result['album_messages'],[101,102])

    def test_http_malformed_body_and_localized_errors(self):
        server=make_server(self.e);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        origin='http://127.0.0.1:'+str(server.server_port)
        try:
            request=Request(origin+'/api/console',headers={'X-Nexora-Language':'ml'})
            with self.assertRaises(HTTPError) as error:urlopen(request)
            with error.exception as response:self.assertEqual(json.load(response)['error'],translate('Authentication required','ml'))
            token=self.e.dashboard_token(-100,1)
            for body in ([],{'action':'preview','change':[]},{'action':'preview','change':None}):
                request=Request(origin+'/api/console',data=json.dumps(body).encode(),headers={'Authorization':'Bearer '+token})
                with self.assertRaises(HTTPError) as error:urlopen(request)
                with error.exception as response:self.assertEqual(response.status,400)
        finally:server.shutdown();server.server_close();thread.join()

    def test_web_verification_uses_group_language(self):
        self.e.configure(-100,1,'language','ml');self.e.configure(-100,1,'captcha','web');self.e.start_captcha(self.chat,self.user)
        c=self.db.get(-100,'captcha',2)
        server=make_server(self.e);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with urlopen('http://127.0.0.1:'+str(server.server_port)+'/verify?token='+c['token']) as response:page=response.read().decode()
            self.assertIn('lang="ml"',page)
            self.assertIn(translate('Type the code','ml'),page)
            self.assertNotIn('Complete your private verification.',page)
        finally:server.shutdown();server.server_close();thread.join()

    def test_localized_default_messages_do_not_persist_after_language_switch(self):
        self.e.configure(-100,1,'language','ml')
        self.e.configure(-100,1,'warn_limit',7)
        self.e.configure(-100,1,'language','en')
        self.assertEqual(self.e.settings(-100)['welcome'],'Welcome {first_name} to {chat_title}!')

if __name__=='__main__':unittest.main()
