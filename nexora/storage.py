import json
import sqlite3
import threading
import time
from contextlib import contextmanager


class Store:
    """Single-process SQLite store; every operation is serialized across HTTP/poller."""
    def __init__(self, path):
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript('''
        PRAGMA journal_mode=WAL;
        PRAGMA busy_timeout=5000;
        CREATE TABLE IF NOT EXISTS docs(scope TEXT, kind TEXT, key TEXT, value TEXT,
          PRIMARY KEY(scope,kind,key));
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, chat INTEGER,
          user INTEGER, kind TEXT, at REAL, data TEXT);
        CREATE INDEX IF NOT EXISTS events_chat_time ON events(chat,at);
        CREATE TABLE IF NOT EXISTS jobs(id INTEGER PRIMARY KEY, chat INTEGER,
          kind TEXT, due REAL, interval INTEGER DEFAULT 0, payload TEXT,
          status TEXT DEFAULT 'pending', error TEXT DEFAULT '');
        CREATE INDEX IF NOT EXISTS jobs_due ON jobs(status,due);
        CREATE TABLE IF NOT EXISTS updates(id INTEGER PRIMARY KEY, payload TEXT,
          status TEXT DEFAULT 'pending', error TEXT DEFAULT '');
        ''')
        self.conn.commit()

    def sql(self, query, args=()):
        with self.lock:
            c = self.conn.execute(query, args)
            rows = [dict(r) for r in c.fetchall()] if c.description else []
            self.conn.commit()
            return rows

    def get(self, scope, kind, key, default=None):
        rows = self.sql('SELECT value FROM docs WHERE scope=? AND kind=? AND key=?',
                        (str(scope), kind, str(key)))
        return json.loads(rows[0]['value']) if rows else default

    def put(self, scope, kind, key, value):
        self.sql('INSERT OR REPLACE INTO docs VALUES(?,?,?,?)',
                 (str(scope), kind, str(key), json.dumps(value, ensure_ascii=False)))

    def delete(self, scope, kind, key):
        self.sql('DELETE FROM docs WHERE scope=? AND kind=? AND key=?', (str(scope), kind, str(key)))

    def items(self, scope, kind):
        return {r['key']: json.loads(r['value']) for r in self.sql(
            'SELECT key,value FROM docs WHERE scope=? AND kind=?', (str(scope), kind))}

    def event(self, chat, user, kind, data=None):
        self.sql('INSERT INTO events(chat,user,kind,at,data) VALUES(?,?,?,?,?)',
                 (chat, user, kind, time.time(), json.dumps(data or {}, ensure_ascii=False)))

    def job(self, chat, kind, due, payload, interval=0):
        with self.lock:
            c = self.conn.execute('INSERT INTO jobs(chat,kind,due,interval,payload) VALUES(?,?,?,?,?)',
                                  (chat, kind, due, interval, json.dumps(payload)))
            self.conn.commit()
            return c.lastrowid

    def migrate(self, old, new):
        with self.lock, self.conn:
            if self.conn.execute('SELECT 1 FROM docs WHERE scope=?', (str(new),)).fetchone():
                raise ValueError('Migration target already has data; operator review required')
            self.conn.execute('UPDATE docs SET scope=? WHERE scope=?', (str(new), str(old)))
            for table in ('events', 'jobs'):
                self.conn.execute(f'UPDATE {table} SET chat=? WHERE chat=?', (new, old))
            # Federation membership is keyed by chat in the global federation document.
            for row in self.conn.execute("SELECT key,value FROM docs WHERE scope='global' AND kind='fed'").fetchall():
                value = json.loads(row['value'])
                value['chats'] = [new if c == old else c for c in value['chats']]
                self.conn.execute("UPDATE docs SET value=? WHERE scope='global' AND kind='fed' AND key=?",
                                  (json.dumps(value), row['key']))
            # Rewrite embedded chat references and private publishing namespaces atomically.
            for row in self.conn.execute('SELECT scope,kind,key,value FROM docs').fetchall():
                value = json.loads(row['value'])
                scope,kind,key = row['scope'],row['kind'],row['key']
                if kind in ('ui_tokens','ui_inputs','web_changes') and value.get('chat') in (old,new):
                    self.conn.execute('DELETE FROM docs WHERE scope=? AND kind=? AND key=?',(scope,kind,key))
                    continue
                if scope=='community:'+str(old):
                    scope='community:'+str(new)
                if scope=='billing' and kind in ('orders','charges') and value.get('chat')==old:
                    value['chat']=new
                if kind=='community_inboxes':
                    if key==str(old):key=str(new)
                    if value==old:value=new
                if kind=='extensions' and key=='support' and value.get('inbox')==old:
                    value['inbox']=new
                if kind=='session' and key=='community_support' and value==old:
                    value=new
                if scope.startswith('publisher:') and scope.endswith(':'+str(old)):
                    scope = scope.rsplit(':',1)[0]+':'+str(new)
                if kind=='session' and key=='channel' and value==old:
                    value=new
                elif kind=='session' and key=='captcha' and value==old:
                    value=new
                elif kind=='channels' and key==str(old):
                    key=str(new)
                elif kind=='broadcast_groups' and scope=='global' and key==str(old):
                    key=str(new)
                elif kind=='campaigns' and scope=='global':
                    for target in value.get('targets',[]):
                        if target['chat']==old:
                            target['chat']=new
                elif kind=='captcha' and isinstance(value,dict):
                    if value.get('chat',{}).get('id')==old:
                        value['chat']['id']=new
                    value['prompts']=[[new if c==old else c,m] for c,m in value.get('prompts',[])]
                elif kind=='access' and value.get('chat')==old:
                    value['chat']=new
                elif kind=='config' and value.get('log_chat')==old:
                    value['log_chat']=new
                self.conn.execute('DELETE FROM docs WHERE scope=? AND kind=? AND key=?',(row['scope'],row['kind'],row['key']))
                self.conn.execute('INSERT INTO docs VALUES(?,?,?,?)',(scope,kind,key,json.dumps(value)))
            for row in self.conn.execute('SELECT id,payload FROM jobs').fetchall():
                p=json.loads(row['payload'])
                if p.get('scope','').startswith('publisher:') and p['scope'].endswith(':'+str(old)):
                    p['scope']=p['scope'].rsplit(':',1)[0]+':'+str(new)
                self.conn.execute('UPDATE jobs SET payload=? WHERE id=?',(json.dumps(p),row['id']))

    def close(self):
        self.conn.close()
