"""Health check for the one configured Huey scheduler heartbeat."""
import os, sqlite3, sys, time
from pathlib import Path
try:
 with sqlite3.connect(Path(os.environ.get('SCOOBY_DATA','/data'))/'state.sqlite3',timeout=3) as db:
  row=db.execute("SELECT seen FROM heartbeats WHERE name='worker'").fetchone()
 if not row or time.time()-row[0]>150: sys.exit(1)
except (sqlite3.Error,OSError): sys.exit(1)
