"""Read-only diagnostics and consistent SQLite backup; never contacts Telegram."""
import argparse
import json
import sqlite3
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',default='data/nexora.sqlite3')
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('status')
    backup=sub.add_parser('backup')
    backup.add_argument('destination')
    args=parser.parse_args()
    source=Path(args.db).resolve()
    if not source.is_file():
        parser.error('Database does not exist')
    con=sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)
    con.row_factory=sqlite3.Row
    if args.command=='status':
        output={}
        for table in ('jobs','updates'):
            output[table]=[dict(r) for r in con.execute(f'SELECT status,count(*) AS count FROM {table} GROUP BY status')]
        output['failed_jobs']=[dict(r) for r in con.execute("SELECT id,chat,kind,status,error FROM jobs WHERE status IN ('failed','uncertain') ORDER BY id DESC LIMIT 100")]
        print(json.dumps(output,indent=2))
    else:
        dest=Path(args.destination).resolve()
        if dest.exists():
            parser.error('Backup destination already exists; choose a new file')
        dest.parent.mkdir(parents=True,exist_ok=True)
        with sqlite3.connect(dest) as target:
            con.backup(target)
        print('Backup created:',dest)
    con.close()


if __name__=='__main__':
    main()
