import hashlib,json,shutil,zipfile
from pathlib import Path
import pytest
import store,seed_restore


def test_seed_archive_idempotence_and_tamper_fails_closed(tmp_path,monkeypatch):
 monkeypatch.setenv('SCOOBY_REPORT_RELEASE','approved')
 data=tmp_path/'data';data.mkdir();monkeypatch.setattr(store,'DB',data/'db.sqlite3');monkeypatch.setattr(seed_restore,'DATA',data);store.init()
 root=tmp_path/'seed';folder=root/'report-01-abcdef';folder.mkdir(parents=True)
 source=Path(__file__).parent/'historical-bundle';shutil.copytree(source,folder/'bundle')
 doc=json.loads((folder/'bundle'/'report.json').read_bytes());candidate={'candidate_id':doc['candidate_id'],'identity':doc['identity'],'mode':doc['mode']}
 raw=json.dumps(candidate).encode();(folder/'candidate.json').write_bytes(raw)
 item={'folder':folder.name,'report_id':doc['report_id'],'version':doc['report_version'],'report_sha256':hashlib.sha256((folder/'bundle'/'report.json').read_bytes()).hexdigest(),'candidate_id':doc['candidate_id'],'candidate_sha256':hashlib.sha256(raw).hexdigest(),'original_run_id':'seedtest','mode':doc['mode']}
 manifest=json.dumps({'reports':[item]}).encode();(root/'manifest.json').write_bytes(manifest);mh=hashlib.sha256(manifest).hexdigest()
 archive=tmp_path/'seed.zip'
 with zipfile.ZipFile(archive,'w') as z:
  for f in root.rglob('*'):
   if f.is_file():z.write(f,f.relative_to(root))
 assert seed_restore.restore(archive,mh,[doc['report_id']])==1
 assert seed_restore.restore(archive,mh,[doc['report_id']])==1
 # Simulate an upgrade from PR23, which installed these rows before the marker existed.
 with store.db() as c:c.execute('DELETE FROM seed_imports')
 store.init()
 with store.db() as c:
  assert c.execute('select count(*) from reports').fetchone()[0]==1
  assert c.execute("select count(*) from jobs where kind='investigate'").fetchone()[0]==0
  from publication import db as publication_db
  publication_db.init()
  from publication.review import consumer_visible
  monkeypatch.setenv('SCOOBY_REPORT_RELEASE','all')
  assert not consumer_visible(c,doc['report_id'],doc['report_version'])
  import publication.review as review
  actual_approved=review.approved
  monkeypatch.setattr(review,'approved',lambda *args:True)
  assert consumer_visible(c,doc['report_id'],doc['report_version'])
  monkeypatch.setenv('SCOOBY_REPORT_RELEASE','invalid')
  assert not consumer_visible(c,doc['report_id'],doc['report_version'])
  monkeypatch.setattr(review,'approved',actual_approved)
 monkeypatch.setenv('SCOOBY_REPORT_RELEASE','all')
 from fastapi.testclient import TestClient
 from app import app
 client=TestClient(app)
 assert not any(x['report_id']==doc['report_id'] for x in client.get('/reports').json())
 assert client.get('/reports/'+doc['report_id']+'/'+doc['report_version']+'/artifacts').status_code==404
 with pytest.raises(ValueError):seed_restore.restore(archive,'0'*64,[doc['report_id']])
