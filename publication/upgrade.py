"""Idempotent cleanup of former open-review authority, before any publication process runs."""
import json
from store import db, now, digest

def subject_hash(iss,sub): return digest(f"{iss}|{sub}".encode())
def audit(c,kind,actor,detail):
    c.execute("INSERT INTO admin_events(kind,actor,detail_json,created) VALUES(?,?,?,?)",(kind,actor,json.dumps(detail,sort_keys=True),now()))

def retire_open_review_grants() -> None:
    """Quarantine automatic open-review permissions and attributable receipts before env grants load."""
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        # Grant rows are overwritten on later regrant. Reconstruct historical
        # authority from append-only scope events before touching current grants.
        history={}
        for event_row in c.execute("SELECT kind,actor,detail_json,created,seq FROM admin_events WHERE kind IN ('scope_granted','scope_revoked') ORDER BY created,seq"):
            try:
                details=json.loads(event_row['detail_json']);key=(details['subject_sha256'],details['scope'])
            except (ValueError,KeyError,TypeError):
                continue
            history.setdefault(key,[]).append((event_row['created'],event_row['actor'],event_row['seq'],event_row['kind']))
        for table,scope,event_table in (('rev_receipts','report_review','rev_events'),('pub_receipts','publication','pub_events')):
            for receipt in c.execute(f'SELECT * FROM {table} WHERE revoked_at IS NULL').fetchall():
                key=(subject_hash(receipt['reviewer_iss'],receipt['reviewer_sub']),scope)
                timeline=history.get(key,[])
                reviewer=c.execute('SELECT label FROM pub_reviewers WHERE iss=? AND sub=?',(receipt['reviewer_iss'],receipt['reviewer_sub'])).fetchone()
                if not any(entry[1]=='open-review' for entry in timeline) and not (reviewer and reviewer['label'].startswith('open-review:')):continue
                prior=[entry for entry in timeline if entry[0]<=receipt['verified_at']]
                # When no event predates the receipt, authority is ambiguous.
                if prior and prior[-1][1]!='open-review' and prior[-1][3]=='scope_granted':continue
                if table=='rev_receipts':
                    c.execute('UPDATE rev_receipts SET revoked_at=?,revoke_reason=? WHERE id=?',(now(),'Open-review historical authority requires named-admin re-review',receipt['id']))
                else:
                    c.execute('UPDATE pub_receipts SET revoked_at=? WHERE id=?',(now(),receipt['id']))
                    c.execute("UPDATE pub_outbox SET state='failed',error='Open-review authorization retired' WHERE receipt_id=? AND (state IN ('queued','signing') OR (state='reconcile' AND tx_hash IS NULL))",(receipt['id'],))
                c.execute(f'INSERT INTO {event_table}(target_id,kind,actor,detail_json,created) VALUES(?,?,?,?,?)',(receipt['target_id'],'open_review_receipt_quarantined','migration',json.dumps({'receipt_id':receipt['id'],'note':'Submitted or confirmed transactions require separate reconciliation.'}),now()))
        grants=c.execute("SELECT * FROM admin_scopes WHERE granted_by='open-review' AND revoked_at IS NULL").fetchall()
        for grant_row in grants:
            iss,sub,scope,started=grant_row['iss'],grant_row['sub'],grant_row['scope'],grant_row['created']
            label=c.execute('SELECT label FROM pub_reviewers WHERE iss=? AND sub=?',(iss,sub)).fetchone()
            cutoff=0 if label and label['label'].startswith('open-review:') else started
            if scope=='report_review':
                receipts=c.execute('SELECT id,target_id FROM rev_receipts WHERE reviewer_iss=? AND reviewer_sub=? AND verified_at>=? AND revoked_at IS NULL',(iss,sub,cutoff)).fetchall()
                for receipt in receipts:
                    c.execute('UPDATE rev_receipts SET revoked_at=?,revoke_reason=? WHERE id=?',(now(),'Open-review authorization retired; named-admin review required',receipt['id']))
                    c.execute('INSERT INTO rev_events(target_id,kind,actor,detail_json,created) VALUES(?,?,?,?,?)',(receipt['target_id'],'open_review_receipt_quarantined','migration',json.dumps({'receipt_id':receipt['id']}),now()))
                c.execute("UPDATE rev_attempts SET status='cancelled',error='Open-review authorization retired' WHERE initiator_iss=? AND initiator_sub=? AND status='pending'",(iss,sub))
            if scope=='publication':
                receipts=c.execute('SELECT id,target_id FROM pub_receipts WHERE reviewer_iss=? AND reviewer_sub=? AND verified_at>=? AND revoked_at IS NULL',(iss,sub,cutoff)).fetchall()
                for receipt in receipts:
                    c.execute('UPDATE pub_receipts SET revoked_at=? WHERE id=?',(now(),receipt['id']))
                    c.execute("UPDATE pub_outbox SET state='failed',error='Open-review authorization retired' WHERE receipt_id=? AND (state IN ('queued','signing') OR (state='reconcile' AND tx_hash IS NULL))",(receipt['id'],))
                    c.execute('INSERT INTO pub_events(target_id,kind,actor,detail_json,created) VALUES(?,?,?,?,?)',(receipt['target_id'],'open_review_receipt_quarantined','migration',json.dumps({'receipt_id':receipt['id'],'note':'Existing submitted or confirmed transactions require separate reconciliation.'}),now()))
                c.execute("UPDATE pub_attempts SET status='cancelled',error='Open-review authorization retired' WHERE initiator_iss=? AND initiator_sub=? AND status='pending'",(iss,sub))
            c.execute('UPDATE admin_scopes SET revoked_at=? WHERE iss=? AND sub=? AND scope=? AND granted_by=? AND revoked_at IS NULL',(now(),iss,sub,scope,'open-review'))
            audit(c,'open_review_grant_retired','migration',{'scope':scope,'subject_sha256':subject_hash(iss,sub)})
        c.execute("UPDATE pub_reviewers SET enabled=0 WHERE label LIKE 'open-review:%' AND NOT EXISTS (SELECT 1 FROM admin_scopes s WHERE s.iss=pub_reviewers.iss AND s.sub=pub_reviewers.sub AND s.revoked_at IS NULL AND s.granted_by!='open-review')")

