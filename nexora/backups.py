"""Consistent local backups and offline-only, operator-confirmed recovery."""
import hashlib
import os
import secrets
import sqlite3
import time
from pathlib import Path
from contextlib import closing
from .instance import InstanceLock


def check(path):
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)) as db:
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('Database integrity check failed')
        names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {'docs', 'events', 'jobs', 'updates'} <= names:
            raise ValueError('This is not a Nexora backup')


def create(db, directory, keep=7):
    root = Path(directory).resolve()
    root.mkdir(parents=True, exist_ok=True)
    path = root / ('nexora-' + str(time.time_ns()) + '-' + secrets.token_hex(3) + '.sqlite3')
    try:
        with db.lock, closing(sqlite3.connect(path)) as target:
            db.conn.backup(target)
        os.chmod(path, 0o600)
        check(path)
        for old in sorted(root.glob('nexora-*.sqlite3'), key=lambda p: p.name, reverse=True)[max(1, keep):]:
            if old.is_file() and not old.is_symlink():
                old.unlink()
        return {'file': path.name, 'at': time.time(), 'ok': True}
    except Exception:
        if path.exists():
            path.unlink()
        raise


def restore(source, destination, expected_digest, confirm=False):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    check(source)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if not confirm or not secrets.compare_digest(digest, expected_digest):
        raise ValueError('Inspect the backup and confirm its exact SHA-256 before restoring')
    if source == destination or not destination.is_file():
        raise ValueError('Choose an existing, different destination database')
    lock = InstanceLock(str(destination) + '.lock')
    rollback = destination.with_name(destination.name + '.rollback-' + str(time.time_ns()))
    try:
        # Same OS lock as the worker. Do not replace an open SQLite file or orphan its WAL.
        with closing(sqlite3.connect(destination)) as live, closing(sqlite3.connect(rollback)) as saved:
            live.backup(saved)
            check(rollback)
            with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as recovered:
                recovered.backup(live)
            # Restored deliveries may already exist on Telegram. Never replay them automatically.
            live.execute("UPDATE jobs SET status='uncertain',error='Restored backup; review before resend' WHERE status IN ('pending','running')")
            live.execute("UPDATE updates SET status='uncertain',payload='{}' WHERE status IN ('pending','running')")
            live.execute("DELETE FROM docs WHERE kind IN ('ui_tokens','ui_inputs','access')")
            live.execute("DELETE FROM docs WHERE kind='web_changes'")
            live.execute("INSERT OR REPLACE INTO docs VALUES('billing','recovery','blocked','true')")
            live.commit()
        os.chmod(rollback, 0o600)
        check(destination)
        return str(rollback)
    finally:
        lock.close()
