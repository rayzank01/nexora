import json
import logging
import os
import signal
import threading
import time
from pathlib import Path

from .config import Config, load_env
from .storage import Store
from .transport import Telegram, RemoteError
from .engine import Engine
from .web import make_server
from .instance import InstanceLock
from .preflight import assert_runtime


def main():
    load_env()
    config = Config()
    assert_runtime(config)
    if not config.token or config.token.startswith('replace_'):
        raise SystemExit('Set BOT_TOKEN in your private .env file. See README.md. No token is bundled.')
    os.umask(0o077)
    Path(config.db).parent.mkdir(parents=True,exist_ok=True)
    instance = InstanceLock(config.db+'.lock')
    db = Store(config.db)
    tg = Telegram(config.token)
    engine = Engine(db,tg,config)
    engine.me = tg.call('getMe')
    info = tg.call('getWebhookInfo')
    if info.get('url'):
        raise SystemExit('An existing webhook is configured. Remove it deliberately before using polling.')
    tg.call('setMyCommands',commands=[{'command':k,'description':v} for k,v in
        [('start','Start Nexora / ആരംഭിക്കുക'),('help','Commands / സഹായം'),('setup','Group setup'),
         ('rules','Group rules'),('stats','Community activity'),('support','Contact support'),('channel','Select publishing destination')]])
    # A crash between remote success and local commit is ambiguous; surface it for review.
    db.sql("UPDATE jobs SET status='uncertain',error='Interrupted during execution; inspect Telegram before retry' WHERE status='running'")
    db.sql("UPDATE updates SET status='uncertain',error='Interrupted during execution' WHERE status='running'")
    stop = threading.Event()
    for sig in (signal.SIGINT,signal.SIGTERM):
        signal.signal(sig,lambda *_: stop.set())
    server = make_server(engine)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    logging.info('Nexora started. HTTP listener on %s:%s',config.host,config.port)
    last_cleanup = 0
    try:
        while not stop.is_set():
            try:
                with db.lock:
                    for row in db.sql("SELECT payload FROM updates WHERE status='pending' ORDER BY id LIMIT 20"):
                        engine.process(json.loads(row['payload']))
                    engine.tick()
                    engine.health.scheduler_ok()
                    if time.time()-last_cleanup>3600:
                        cutoff = time.time()-config.retention_days*86400
                        db.sql('DELETE FROM events WHERE at<?',(cutoff,))
                        # Clear failed/uncertain update bodies during hourly cleanup.
                        db.sql("UPDATE updates SET payload='{}' WHERE status IN ('failed','uncertain')")
                        offset = db.get('global','poll','offset',0)
                        db.sql("DELETE FROM updates WHERE id<? AND status='done'",(offset-10000,))
                        # Bounded in-memory anti-flood windows; persisted moderation data is separate.
                        engine.flood={k:v for k,v in engine.flood.items() if v and v[-1][0]>time.time()-3600}
                        for k,v in db.items('global','access').items():
                            if v['expires']<time.time():
                                db.delete('global','access',k)
                        last_cleanup = time.time()
                    offset = db.get('global','poll','offset',0)
                updates = tg.call('getUpdates',offset=offset,timeout=5,
                    allowed_updates=['message','edited_message','callback_query','chat_member','my_chat_member','chat_join_request'])
                engine.health.poll_ok()
                with db.lock:
                    # Persist whole batch and new offset before processing. Pending rows survive restart.
                    for update in updates:
                        db.sql('INSERT OR IGNORE INTO updates(id,payload) VALUES(?,?)',(update['update_id'],json.dumps(update)))
                    if updates:
                        db.put('global','poll','offset',max(u['update_id'] for u in updates)+1)
            except RemoteError as exc:
                logging.warning('Telegram unavailable (code %s); reconnecting',exc.code)
                stop.wait(min(max(exc.retry_after,3),30))
            except Exception as exc:
                # Only exception class is logged; URLs, tokens, message bodies stay out of logs.
                logging.error('Worker stopped on %s; inspect the local database',type(exc).__name__)
                raise SystemExit(1) from None
    finally:
        server.shutdown()
        server.server_close()
        db.close()
        instance.close()


if __name__ == '__main__':
    main()
