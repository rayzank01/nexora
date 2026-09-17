import hashlib
import html
import json
import secrets
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .transport import request_json, RemoteError


def authenticate(engine, authorization):
    if not authorization.startswith('Bearer '):
        raise PermissionError('Authentication required')
    token = authorization[7:]
    access = engine.db.get('global','access',hashlib.sha256(token.encode()).hexdigest())
    if not access or access['expires']<time.time():
        raise PermissionError('Session expired')
    # Membership/administrator revocation takes effect on the next request.
    engine.require(access['chat'],access['user'],native=True)
    return access


def verify_web(engine, token, answer='', turnstile=''):
    cid,uid,c = engine.find_captcha(token)
    if c['mode'] not in ('web','turnstile') or c['status']!='pending' or c['expires']<=time.time():
        raise ValueError('Expired verification')
    if c['attempts']>=5:
        raise ValueError('Too many attempts')
    c['attempts'] += 1
    engine.db.put(cid,'captcha',uid,c)
    if c['mode']=='turnstile':
        if not turnstile or len(turnstile)>2048:
            raise ValueError('Complete the challenge')
        result = request_json('https://challenges.cloudflare.com/turnstile/v0/siteverify',
                              {'secret':engine.config.turnstile_secret,'response':turnstile})
        if not result.get('success') or result.get('hostname')!=engine.config.turnstile_hostname or result.get('action')!='nexora':
            raise ValueError('Challenge validation failed')
    elif not secrets.compare_digest(c['answer'],answer.strip().upper()):
        raise ValueError('Incorrect answer')
    engine.complete_captcha(cid,uid)


def make_server(engine):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):
            pass  # No private URL tokens, identities or request bodies in access logs.

        def reply(self,status,content,kind='application/json'):
            data = json.dumps(content,ensure_ascii=False).encode() if kind=='application/json' else content.encode()
            self.send_response(status)
            self.send_header('Content-Type',kind+'; charset=utf-8')
            self.send_header('Content-Length',str(len(data)))
            self.send_header('Cache-Control','no-store')
            self.send_header('Referrer-Policy','no-referrer')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('X-Frame-Options','DENY')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self' 'unsafe-inline' https://challenges.cloudflare.com; style-src 'self' 'unsafe-inline'; frame-src https://challenges.cloudflare.com; connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            try:
                parsed = urlparse(self.path)
                # Do not wait for the worker's database lock just to report a stuck worker.
                if parsed.path == '/health':
                    self.reply(200, {'status':'ok','service':'nexora'})
                    return
                if parsed.path == '/ready':
                    ready, data = engine.health.snapshot()
                    self.reply(200 if ready else 503, data)
                    return
                with engine.db.lock:
                    if parsed.path=='/':
                        self.reply(200,Path(__file__).with_name('dashboard.html').read_text(encoding='utf-8'),'text/html')
                    elif parsed.path=='/verify':
                        token = parse_qs(parsed.query).get('token',[''])[0]
                        _,_,c = engine.find_captcha(token)
                        if c['status']!='pending' or c['expires']<=time.time() or c['mode'] not in ('web','turnstile'):
                            raise ValueError('Expired verification')
                        if c['mode']=='turnstile':
                            challenge = '<script src="https://challenges.cloudflare.com/turnstile/v0/api.js" async defer></script><div class="cf-turnstile" data-sitekey="' + html.escape(engine.config.turnstile_sitekey,quote=True) + '" data-action="nexora"></div>'
                        else:
                            challenge = '<p>Type <strong>' + html.escape(c['answer']) + '</strong></p><input name="answer" required autocomplete="off">'
                        page = '<!doctype html><meta name="viewport" content="width=device-width"><title>Nexora verification</title><style>body{font:18px system-ui;max-width:520px;margin:10vh auto;padding:24px;background:#101827;color:#fff}input,button{padding:14px;margin:12px 0}button{background:#7ee7c0;border:0;border-radius:9px}</style><h1>Nexora</h1><p>Complete your private verification. Never share this link.</p><form method="POST" action="/verify"><input type="hidden" name="token" value="' + html.escape(token,quote=True) + '">' + challenge + '<br><button>Verify / പരിശോധിക്കുക</button></form>'
                        self.reply(200,page,'text/html')
                    elif parsed.path in ('/api/stats','/api/settings','/api/reports'):
                        access = authenticate(engine,self.headers.get('Authorization',''))
                        cid = access['chat']
                        if parsed.path=='/api/stats':
                            data = engine.stats(cid)
                        elif parsed.path=='/api/settings':
                            data = engine.settings(cid)
                        else:
                            data = engine.db.items(cid,'reports')
                        self.reply(200,data)
                    else:
                        self.reply(404,{'error':'Not found'})
            except PermissionError as exc:
                self.reply(403,{'error':str(exc)})
            except (ValueError,KeyError):
                self.reply(400,{'error':'Invalid or expired request'})
            except RemoteError:
                self.reply(503,{'error':'Telegram/verification service unavailable'})

        def do_POST(self):
            try:
                size = int(self.headers.get('Content-Length','0'))
                if not 0<size<=65536:
                    raise ValueError('Invalid body size')
                raw = self.rfile.read(size).decode('utf-8')
                with engine.db.lock:
                    path = urlparse(self.path).path
                    if path=='/verify':
                        data = parse_qs(raw)
                        verify_web(engine,data.get('token',[''])[0],data.get('answer',[''])[0],data.get('cf-turnstile-response',[''])[0])
                        self.reply(200,'<!doctype html><meta charset="utf-8"><title>Verified</title><h1>Verified / പരിശോധിച്ചു</h1><p>You can return to Telegram.</p>','text/html')
                        return
                    access = authenticate(engine,self.headers.get('Authorization',''))
                    data = json.loads(raw)
                    cid,uid = access['chat'],access['user']
                    if path=='/api/settings':
                        engine.configure(cid,uid,data['key'],data['value'])
                    elif path=='/api/moderate':
                        engine.require(cid,uid,'moderate',native=True)
                        engine.moderate(cid,int(data['user']),data['action'],int(data.get('seconds',0)),str(data.get('reason',''))[:500],data.get('permissions'))
                    elif path=='/api/cancel':
                        engine.require(cid,uid,'publish',native=True)
                        engine.db.sql("UPDATE jobs SET status='cancelled' WHERE id=? AND chat=? AND kind='publish' AND status='pending'",(int(data['job']),cid))
                    else:
                        self.reply(404,{'error':'Not found'})
                        return
                    self.reply(200,{'ok':True})
            except PermissionError as exc:
                self.reply(403,{'error':str(exc)})
            except (ValueError,KeyError,TypeError):
                self.reply(400,{'error':'Invalid request or failed challenge'})
            except RemoteError:
                self.reply(503,{'error':'Remote service unavailable; inspect state before retrying'})

    server = ThreadingHTTPServer((engine.config.host,engine.config.port),Handler)
    server.daemon_threads = True
    return server
