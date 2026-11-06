import argparse, copy, datetime as dt, hashlib, json, re, sqlite3, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
def now(): return dt.datetime.now(dt.timezone.utc).isoformat()
def stamp(s):
    d = dt.datetime.fromisoformat(s.replace('Z', '+00:00'))
    if d.tzinfo is None: raise ValueError('timestamp requires timezone')
    return d.astimezone(dt.timezone.utc)
def identity(chain, address):
    if chain not in (1, 8453) or not isinstance(address, str) or not re.fullmatch(r'0x[0-9a-fA-F]{40}', address): raise ValueError('invalid supported chain/address')
    return f'{chain}:{address.lower()}'
def connect(path):
    db = sqlite3.connect(path)
    db.executescript('''CREATE TABLE IF NOT EXISTS candidates(id TEXT PRIMARY KEY, record TEXT NOT NULL, last_surface TEXT);
    CREATE TABLE IF NOT EXISTS events(source TEXT NOT NULL, event_id TEXT NOT NULL, digest TEXT NOT NULL, payload TEXT NOT NULL, outcome TEXT NOT NULL, PRIMARY KEY(source,event_id));
    CREATE TABLE IF NOT EXISTS actions(id INTEGER PRIMARY KEY, candidate_id TEXT NOT NULL, action TEXT NOT NULL, actor TEXT NOT NULL, at TEXT NOT NULL, reason TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS feeds(source TEXT PRIMARY KEY, cursor INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL, last_attempt TEXT, last_success TEXT, error TEXT, processed INTEGER NOT NULL DEFAULT 0, pending INTEGER NOT NULL DEFAULT 0);''')
    return db
class FixtureAdapter:
    def __init__(self, path, fail=False): self.path, self.fail = path, fail
    def read(self, cursor):
        if self.fail: raise OSError('simulated fixture source failure')
        data = json.loads(Path(self.path).read_text(encoding='utf-8'))
        if data['source_kind'] != 'fixture': raise ValueError('only labeled fixture sources are supported')
        return data['events'][cursor:]
class NoScoringPolicy:
    def screen(self, record): return record['screening']
class TestResurfacePolicy:
    # Demonstration only: changes explicitly labeled material by the fixture, after a configurable cooldown.
    def __init__(self, seconds): self.seconds = seconds
    def should_surface(self, event, previous):
        return bool(event.get('material_change')) and (previous is None or (stamp(event['observed_at'])-stamp(previous)).total_seconds() >= self.seconds)
def run(db, source, adapter, budget, cooldown):
    if budget < 0 or cooldown < 0: raise ValueError('budget and cooldown must be nonnegative')
    row = db.execute('SELECT cursor,last_success FROM feeds WHERE source=?',(source,)).fetchone()
    cursor, last_success = row if row else (0,None)
    attempted = now()
    try: events = adapter.read(cursor)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as e:
        with db: db.execute('INSERT INTO feeds(source,cursor,status,last_attempt,last_success,error) VALUES(?,?,?,?,?,?) ON CONFLICT(source) DO UPDATE SET status=excluded.status,last_attempt=excluded.last_attempt,error=excluded.error',(source,cursor,'feed_down',attempted,last_success,str(e)))
        return {'status':'feed_down','cursor':cursor,'error':str(e)}
    processed = 0
    policy = TestResurfacePolicy(cooldown)
    # Each event and its cursor are committed together. Invalid events stop the source at its checkpoint.
    for event in events[:budget]:
        try:
            eid = event['event_id']; candidate = copy.deepcopy(event['candidate']); key = identity(candidate['identity']['chain_id'], candidate['identity']['address'])
            if candidate['candidate_id'] != key: raise ValueError('candidate ID does not match identity')
            stamp(event['observed_at'])
            if candidate['mode'] not in ('historical_replay','synthetic_demo'): raise ValueError('fixture mode must be historical or synthetic')
            if not isinstance(eid,str) or not eid: raise ValueError('event ID required')
            raw = json.dumps(event, sort_keys=True, separators=(',',':')); digest=hashlib.sha256(raw.encode()).hexdigest()
            with db:
                existing = db.execute('SELECT digest FROM events WHERE source=? AND event_id=?',(source,eid)).fetchone()
                if existing and existing[0] != digest: raise ValueError('event ID reused with different payload')
                if not existing:
                    row2 = db.execute('SELECT record,last_surface FROM candidates WHERE id=?',(key,)).fetchone()
                    if row2:
                        old, surface = json.loads(row2[0]), row2[1]
                        if old['mode'] != candidate['mode']: raise ValueError('candidate provenance mode conflict')
                        for field in ('triggers','evidence'):
                            for item in candidate[field]:
                                if item not in old[field]: old[field].append(item)
                        old['screening']['quality_issues'] = list(dict.fromkeys(old['screening']['quality_issues'] + candidate['screening']['quality_issues']))
                        record = old
                    else:
                        record, surface = candidate, None
                        record['state']='awaiting_selection'; record['selection']={'status':'not_selected','selected_by':None,'selected_at':None,'reason':None}
                    if record['screening']['status'] != 'not_scored' or record['screening']['score'] is not None or record['screening']['score_version'] is not None or record['screening']['threshold_version'] is not None: raise ValueError('unapproved screening values')
                    record['screening']=NoScoringPolicy().screen(record)
                    if event.get('observation_time_known') is True and (record['last_observed_at'] is None or stamp(event['observed_at']) > stamp(record['last_observed_at'])): record['last_observed_at']=event['observed_at']
                    if not record['identity']['symbol'].strip(): record['screening']['quality_issues'].append('Missing symbol; identity is address-based.')
                    surface_now = policy.should_surface(event,surface) and record['selection']['status'] != 'selected'
                    if surface_now: record['state']='awaiting_selection'; surface=event['observed_at']
                    db.execute('INSERT OR REPLACE INTO candidates VALUES(?,?,?)',(key,json.dumps(record),surface))
                    db.execute('INSERT INTO events VALUES(?,?,?,?,?)',(source,eid,digest,raw,'resurfaced' if surface_now else 'recorded'))
                cursor += 1; processed += 1
                db.execute('INSERT INTO feeds(source,cursor,status,last_attempt,last_success,error,processed,pending) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(source) DO UPDATE SET cursor=excluded.cursor,status=excluded.status,last_attempt=excluded.last_attempt,last_success=excluded.last_success,error=NULL,processed=excluded.processed,pending=excluded.pending',(source,cursor,'ok',attempted,attempted,None,processed,len(events)-processed))
        except (KeyError, TypeError, ValueError) as e:
            with db: db.execute('INSERT INTO feeds(source,cursor,status,last_attempt,last_success,error,processed,pending) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(source) DO UPDATE SET status=excluded.status,last_attempt=excluded.last_attempt,error=excluded.error,processed=excluded.processed,pending=excluded.pending',(source,cursor,'invalid_event',attempted,last_success,str(e),processed,len(events)-processed))
            return {'status':'invalid_event','cursor':cursor,'error':str(e)}
    status='backpressure' if len(events)>processed else ('no_new_candidates' if processed==0 else 'ok')
    with db: db.execute('INSERT INTO feeds(source,cursor,status,last_attempt,last_success,error,processed,pending) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(source) DO UPDATE SET cursor=excluded.cursor,status=excluded.status,last_attempt=excluded.last_attempt,last_success=excluded.last_success,error=NULL,processed=excluded.processed,pending=excluded.pending',(source,cursor,status,attempted,attempted,None,processed,len(events)-processed))
    return {'status':status,'processed':processed,'pending':len(events)-processed,'cursor':cursor}
def action(db, key, kind, actor, reason):
    if not actor.strip() or not reason.strip(): raise ValueError('actor and reason are required')
    with db:
        row=db.execute('SELECT record FROM candidates WHERE id=?',(key,)).fetchone()
        if not row: raise ValueError('unknown candidate')
        record=json.loads(row[0]); at=now()
        if record['selection']['status']=='selected': raise ValueError('already selected; reversal is not implemented')
        record['selection']={'status':'selected' if kind=='select' else 'deferred','selected_by':actor if kind=='select' else None,'selected_at':at if kind=='select' else None,'reason':reason}
        record['state']='selected' if kind=='select' else 'monitoring'
        db.execute('UPDATE candidates SET record=? WHERE id=?',(json.dumps(record),key))
        db.execute('INSERT INTO actions(candidate_id,action,actor,at,reason) VALUES(?,?,?,?,?)',(key,kind,actor,at,reason))
    return record
def main():
    p=argparse.ArgumentParser(); p.add_argument('--db',default='discovery.sqlite'); sub=p.add_subparsers(dest='command',required=True)
    r=sub.add_parser('replay'); r.add_argument('--file',default=str(ROOT/'fixtures.json')); r.add_argument('--source',default='demo'); r.add_argument('--budget',type=int,default=100); r.add_argument('--cooldown-seconds',type=int,default=3600); r.add_argument('--fail',action='store_true')
    for name in ('select','defer'):
        a=sub.add_parser(name); a.add_argument('candidate_id'); a.add_argument('--actor',required=True); a.add_argument('--reason',required=True)
    sub.add_parser('status'); sub.add_parser('export-selected'); args=p.parse_args(); db=connect(args.db)
    if args.command=='replay': result=run(db,args.source,FixtureAdapter(args.file,args.fail),args.budget,args.cooldown_seconds)
    elif args.command in ('select','defer'):
        if args.command=='select':
            row=db.execute('SELECT record FROM candidates WHERE id=?',(args.candidate_id,)).fetchone()
            if row and json.loads(row[0]).get('mode')=='live': raise ValueError('Live selections must pass review_queue.py select; use the verified review queue.')
        result=action(db,args.candidate_id,args.command,args.actor,args.reason)
    elif args.command=='export-selected': result=[json.loads(row[0]) for row in db.execute('SELECT record FROM candidates ORDER BY id') if json.loads(row[0])['selection']['status']=='selected']
    else:
        db.row_factory=sqlite3.Row
        result={'candidates':[json.loads(row['record']) for row in db.execute('SELECT record FROM candidates ORDER BY id')], 'feeds':[dict(row) for row in db.execute('SELECT * FROM feeds')], 'actions':[dict(row) for row in db.execute('SELECT * FROM actions')], 'events':[dict(row) for row in db.execute('SELECT source,event_id,outcome FROM events')]}
    print(json.dumps(result,indent=2)); db.close()
    if isinstance(result,dict) and result.get('status') in ('feed_down','invalid_event'): return 1
    return 0
if __name__=='__main__':
    try: sys.exit(main())
    except (ValueError, OSError, sqlite3.Error) as e: print(str(e),file=sys.stderr); sys.exit(1)
