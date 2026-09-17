"""Offline hosting checks. Does not contact Telegram, create resources or inspect secrets."""
import argparse
import json
import os
from pathlib import Path


FREE_RENDER_REASON = (
    'Render Free cannot run this build safely: SQLite needs durable storage and the '
    'poller/scheduler need a continuously running process. See docs/FREE_HOSTING.md. '
    'No service was provisioned and no Telegram request was made.'
)


def runtime_issues(config, environ=None):
    env = os.environ if environ is None else environ
    problems = []
    if env.get('DATABASE_URL'):
        problems.append('DATABASE_URL is not supported by this SQLite build. Do not assume a remote database is being used.')
    raw_db = str(config.db)
    if raw_db == ':memory:' or raw_db.startswith(('file:', 'postgres:', 'postgresql:', 'sqlite:', 'https:')):
        problems.append('DATABASE_PATH must be a durable local SQLite file path, not memory, a URI or a connection string.')
    try:
        database = Path(raw_db).resolve()
    except (OSError, ValueError):
        problems.append('DATABASE_PATH is not a valid local file path.')
        return problems
    persistent = env.get('PERSISTENT_DATA_DIR', '').strip()
    render = env.get('RENDER', '').lower() == 'true'
    if persistent:
        try:
            root = Path(persistent).resolve()
            if not Path(persistent).is_absolute() or root == Path(root.anchor):
                problems.append('PERSISTENT_DATA_DIR must name an absolute data directory, not the filesystem root.')
            elif not database.is_relative_to(root) or database == root:
                problems.append('DATABASE_PATH resolves outside PERSISTENT_DATA_DIR. SQLite and its WAL must stay on that disk.')
            elif render and not root.is_mount():
                problems.append('On Render, PERSISTENT_DATA_DIR must be an existing mounted persistent disk; an ordinary directory is not enough.')
        except (OSError, ValueError):
            problems.append('The persistent data directory could not be verified.')
    elif render:
        problems.append(FREE_RENDER_REASON)
    if render and env.get('NEXORA_HOST_PROFILE') == 'render-free':
        # Explicit profiles cannot override platform limits even if a directory is supplied.
        if FREE_RENDER_REASON not in problems:
            problems.append(FREE_RENDER_REASON)
    if not 1 <= config.port <= 65535:
        problems.append('HTTP_PORT/PORT must be between 1 and 65535.')
    if not 1 <= config.retention_days <= 3650:
        problems.append('RETENTION_DAYS must be between 1 and 3650.')
    return problems


def assert_runtime(config, environ=None):
    problems = runtime_issues(config, environ)
    if problems:
        raise SystemExit('Nexora startup stopped:\n- ' + '\n- '.join(problems))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', choices=('render-free', 'always-on'), required=True)
    args = parser.parse_args()
    if args.profile == 'render-free':
        print(json.dumps({'compatible': False, 'reason': FREE_RENDER_REASON,
            'requirements': ['durable database', 'continuous poller', 'continuous scheduler'],
            'changes_made': False}, indent=2))
        raise SystemExit(2)
    print(json.dumps({'architecture_compatible': True, 'deployment_verified': False,
        'requirements': ['one continuously running process', 'persistent local SQLite data directory',
                         'private Telegram setup', 'outbound HTTPS', 'HTTPS for optional public web verification'],
        'cost_verified': False, 'changes_made': False,
        'note': 'This checks architecture only. Free quota, account eligibility, persistence and uptime must be verified on the host.'}, indent=2))


if __name__ == '__main__':
    main()
