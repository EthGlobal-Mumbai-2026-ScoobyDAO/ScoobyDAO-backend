"""Local operator import of a reviewed historical diagnostic; never starts research."""
import argparse, json, os, re, shutil, tempfile
from pathlib import Path
from store import DATA, db, digest, dumps, event, job, now, PILLARS
from modules.investigation.contract_validate import verify_digest


def install(source, expected_sha, description):
    source = Path(source).resolve()
    if not source.is_dir() or any(p.is_symlink() for p in source.rglob('*')):
        raise ValueError('unsafe diagnostic bundle')
    with tempfile.TemporaryDirectory(dir=DATA) as tmp:
        snap = Path(tmp) / 'bundle'
        shutil.copytree(source, snap)
        doc = verify_digest(snap, expected_sha)
        lineage = json.loads((snap / 'case-lineage.json').read_bytes())
        cid, run = doc['candidate_id'], lineage['run_id']
        original_version = 'run-' + run
        version_ok = doc['report_version'] == original_version
        if not version_ok and re.fullmatch(re.escape(original_version) + r'-editorial[1-9][0-9]*', doc['report_version']):
            provenance_path = snap/'editorial-provenance.json'
            if provenance_path.is_file():
                prov=json.loads(provenance_path.read_bytes())
                original=source.parent.parent/'case-bundle'/'report.json'
                version_ok=(prov.get('kind')=='local_edit_not_authenticated_admin'
                    and prov.get('revision_report_id')==doc['report_id'] and prov.get('revision_report_version')==doc['report_version']
                    and prov.get('original_report_id')==doc['report_id'] and prov.get('original_report_version')==original_version
                    and original.is_file() and not original.is_symlink() and digest(original.read_bytes())==prov.get('original_report_sha256')
                    and any(e.get('path')=='editorial-provenance.json' and e.get('sha256')==digest(provenance_path.read_bytes()) for e in doc['evidence'] + doc['artifacts']))
        if (doc.get('mode') != 'historical_replay' or lineage.get('candidate_id') != cid
                or lineage.get('authorization_reference_id') != 'synthetic_auth_not_admission'
                or doc['report_id'] != 'case-' + lineage['case_id']
                or not version_ok or doc['review']['status'] != 'pending'):
            raise ValueError('diagnostic identity or synthetic lineage mismatch')
        target = DATA / 'bundles' / expected_sha
        target.parent.mkdir(exist_ok=True)
        if not target.exists(): os.rename(snap, target)
        verify_digest(target, expected_sha)
        selection = 'diagnostic-' + run
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            old = c.execute('SELECT * FROM reports WHERE id=? AND version=?',(doc['report_id'],doc['report_version'])).fetchone()
            if old:
                if old['run_id'] != run or old['sha256'] != expected_sha: raise ValueError('immutable report identity conflict')
                return {'run_id':run,'report_id':doc['report_id'],'report_version':doc['report_version'],'sha256':expected_sha}
            if c.execute('SELECT 1 FROM investigations WHERE id=?',(run,)).fetchone(): raise ValueError('run identity already exists')
            payload={'candidate_id':cid,'identity':doc['identity'],'mode':'historical_replay'}
            c.execute('INSERT OR IGNORE INTO candidates VALUES(?,?,?)',(cid,dumps(payload),now()))
            c.execute('INSERT INTO selections VALUES(?,?,?,?,?,?,?)',(selection,cid,'diagnostic_exception','user-requested diagnostic',description,now(),'diagnostic-selection:'+run))
            c.execute('INSERT INTO investigations VALUES(?,?,?,?,?,?)',(run,cid,selection,'reference_only',now(),'diagnostic-run:'+run))
            for name in PILLARS:
                p=doc['pillars'][name]
                c.execute('INSERT INTO pillars VALUES(?,?,?,?)',(run,name,p['status'],p['summary']))
            c.execute('INSERT INTO diagnostic_imports VALUES(?,?,?,?,?)',(run,cid,description,'completed_pending_review',now()))
            c.execute('INSERT INTO reports VALUES(?,?,?,?,?,?)',(doc['report_id'],doc['report_version'],run,expected_sha,str(target),now()))
            c.execute("UPDATE diagnostic_shortlist SET state='draft_pending_review',detail=?,updated=? WHERE candidate_id=?",(description,now(),cid))
            event(c,run,'diagnostic_imported','Historical diagnostic; synthetic producer authorization is not case admission or World verification. Review remains pending.')
            ref=dumps({'id':doc['report_id'],'version':doc['report_version'],'sha256':expected_sha})
            job(c,'render',ref,'diagnostic-render:'+run)
        return {'run_id':run,'report_id':doc['report_id'],'report_version':doc['report_version'],'sha256':expected_sha}

if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('bundle');parser.add_argument('sha256');parser.add_argument('description')
    args=parser.parse_args();print(json.dumps(install(args.bundle,args.sha256,args.description)))

