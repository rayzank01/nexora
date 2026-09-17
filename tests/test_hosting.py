import contextlib
import io
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import urlopen

from nexora.config import Config
from nexora.health import WorkerHealth
from nexora.preflight import assert_runtime, runtime_issues, main as preflight_main
from nexora.web import make_server


class HostingTests(unittest.TestCase):
    def config(self, path='data/nexora.sqlite3'):
        return SimpleNamespace(db=path, port=8080, retention_days=90)

    def test_local_default_remains_compatible(self):
        self.assertEqual(runtime_issues(self.config(), {}), [])

    def test_render_without_durable_disk_stops(self):
        with self.assertRaises(SystemExit) as caught:
            assert_runtime(self.config(), {'RENDER':'true'})
        self.assertIn('Render Free', str(caught.exception))

    def test_declared_directory_is_not_proof_of_render_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            env={'RENDER':'true','PERSISTENT_DATA_DIR':tmp}
            with patch.object(Path, 'is_mount', return_value=False):
                issues=runtime_issues(self.config(str(Path(tmp)/'nexora.db')),env)
            self.assertTrue(any('mounted persistent disk' in x for x in issues))

    def test_mounted_disk_must_contain_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'durable'
            with patch.object(Path,'is_mount',return_value=True):
                issues=runtime_issues(self.config(str(Path(tmp)/'outside.db')),
                    {'RENDER':'true','PERSISTENT_DATA_DIR':str(root)})
            self.assertTrue(any('outside' in x for x in issues))

    def test_path_traversal_cannot_escape_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'durable'
            issues=runtime_issues(self.config(str(root/'..'/'outside.db')),
                {'PERSISTENT_DATA_DIR':str(root)})
            self.assertTrue(any('outside' in x for x in issues))

    def test_mount_validation_is_not_plan_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            env={'RENDER':'true','PERSISTENT_DATA_DIR':tmp}
            with patch.object(Path,'is_mount',return_value=True):
                self.assertEqual(runtime_issues(self.config(str(Path(tmp)/'nexora.db')),env),[])
                env['NEXORA_HOST_PROFILE']='render-free'
                self.assertTrue(runtime_issues(self.config(str(Path(tmp)/'nexora.db')),env))

    def test_remote_database_not_silently_ignored_or_echoed(self):
        secret='postgresql://private:do-not-print@example.invalid/db'
        issues=runtime_issues(self.config(),{'DATABASE_URL':secret})
        self.assertTrue(issues)
        self.assertNotIn(secret,' '.join(issues))

    def test_in_memory_and_uri_database_rejected(self):
        for db in (':memory:','postgresql://example.invalid/db','file:test.db?mode=memory'):
            with self.subTest(db=db):
                self.assertTrue(runtime_issues(self.config(db),{}))

    def test_render_port_and_host_defaults(self):
        with patch.dict(os.environ,{'RENDER':'true','PORT':'12345'},clear=True):
            cfg=Config()
            self.assertEqual(cfg.host,'0.0.0.0')
            self.assertEqual(cfg.port,12345)
        with patch.dict(os.environ,{'PORT':'12345','HTTP_PORT':'8088'},clear=True):
            self.assertEqual(Config().port,8088)

    def test_invalid_retention_and_port_rejected(self):
        cfg=self.config();cfg.port=0;cfg.retention_days=-1
        self.assertEqual(len(runtime_issues(cfg,{})),2)

    def test_preflight_has_no_side_effects_and_does_not_read_env_file(self):
        with patch('sys.argv',['preflight','--profile','render-free']), \
                patch('nexora.config.load_env') as load_env, \
                patch('nexora.transport.request_json') as remote, \
                contextlib.redirect_stdout(io.StringIO()) as output:
            with self.assertRaises(SystemExit) as caught:
                preflight_main()
            self.assertEqual(caught.exception.code,2)
            self.assertFalse(json.loads(output.getvalue())['changes_made'])
            load_env.assert_not_called();remote.assert_not_called()

    def test_startup_guard_runs_before_storage_and_telegram(self):
        from nexora.__main__ import main
        with patch.dict(os.environ,{'RENDER':'true','BOT_TOKEN':'not-a-live-token'},clear=True), \
                patch('nexora.__main__.load_env'), patch('nexora.__main__.Telegram') as telegram, \
                patch('nexora.__main__.Store') as store, patch('nexora.__main__.InstanceLock') as lock:
            with self.assertRaises(SystemExit): main()
            telegram.assert_not_called();store.assert_not_called();lock.assert_not_called()

    def test_both_worker_components_must_be_fresh(self):
        now=[0.0]
        h=WorkerHealth(clock=lambda:now[0])
        self.assertFalse(h.snapshot()[0])
        h.poll_ok();self.assertFalse(h.snapshot()[0])
        h.scheduler_ok();self.assertTrue(h.snapshot()[0])
        now[0]=91.0
        h.poll_ok()
        self.assertFalse(h.snapshot()[0])
        h.scheduler_ok();self.assertTrue(h.snapshot()[0])

    def test_ready_endpoint_is_independent_of_worker_database_lock(self):
        class BusyDatabase:
            @property
            def lock(self):
                raise AssertionError('Readiness must not acquire the worker lock')
        engine=SimpleNamespace(config=SimpleNamespace(host='127.0.0.1',port=0),
                               db=BusyDatabase(),health=WorkerHealth())
        server=make_server(engine)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        origin='http://127.0.0.1:'+str(server.server_port)
        try:
            with urlopen(origin+'/health',timeout=2) as r:
                self.assertEqual(r.status,200)
            with self.assertRaises(HTTPError) as caught:
                urlopen(origin+'/ready',timeout=2)
            self.assertEqual(caught.exception.code,503)
            caught.exception.close()
            engine.health.poll_ok();engine.health.scheduler_ok()
            with urlopen(origin+'/ready',timeout=2) as r:
                self.assertEqual(json.load(r)['status'],'ready')
        finally:
            server.shutdown();server.server_close();thread.join()


if __name__=='__main__':
    unittest.main()
