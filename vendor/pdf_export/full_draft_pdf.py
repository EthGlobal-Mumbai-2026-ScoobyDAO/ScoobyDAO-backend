"""Prepare and print a full-content DRAFT reader; visual/text QA is mandatory afterwards."""
import argparse,hashlib,html,json,pathlib,shutil,subprocess,tempfile
from html.parser import HTMLParser

class ReaderData(HTMLParser):
 def __init__(self):super().__init__();self.capture=False;self.parts=[]
 def handle_starttag(self,tag,attrs):
  if tag=='script' and dict(attrs).get('id')=='data':self.capture=True
 def handle_endtag(self,tag):
  if tag=='script':self.capture=False
 def handle_data(self,data):
  if self.capture:self.parts.append(data)

def print_source(index,report,expected_digest):
 data=report.read_bytes();actual=hashlib.sha256(data).hexdigest()
 if actual!=expected_digest:raise ValueError('report digest mismatch')
 content=index.read_text(encoding='utf-8');parser=ReaderData();parser.feed(content)
 if not parser.parts or json.loads(''.join(parser.parts))!=json.loads(data):raise ValueError('reader and report contents differ')
 obj=json.loads(data)
 # Full long-form markdown is required and is printed as escaped text, never as executable markup.
 matches=[a for a in obj.get('artifacts',[]) if a.get('kind')=='markdown' and a.get('availability')=='available']
 if len(matches)!=1:raise ValueError('version-bound full Markdown required')
 artifact=matches[0];path=artifact.get('path')
 if artifact.get('report_id')!=obj['report_id'] or artifact.get('report_version')!=obj['report_version'] or not isinstance(path,str) or not path or any(x in path for x in ('\\',':','%','?','#')) or path.startswith('/') or any(x in ('','.','..') for x in path.split('/')):raise ValueError('unsafe or mismatched Markdown')
 root=index.parent/'assets';source=root
 for part in path.split('/'):
  source=source/part
  if source.is_symlink():raise ValueError('Markdown symlink forbidden')
 if not source.resolve().is_relative_to(root.resolve()) or not source.is_file():raise ValueError('Markdown unavailable')
 md=source.read_bytes()
 if hashlib.sha256(md).hexdigest()!=artifact.get('sha256'):raise ValueError('Markdown hash mismatch')
 markdown=md.decode('utf-8')
 identity=f"DRAFT - HUMAN REVIEW PENDING | {obj['report_id']} | {obj['report_version']} | SHA-256 {actual}"
 # The reader's own script runs first; this inline script expands all generated nested disclosures.
 # Print links are remapped to an internal evidence index; companion bundle remains necessary
 # for actual evidence bytes. Never leak local file paths or imply files are embedded in PDF.
 entries=[{'id':e['id'],'path':e['path'],'sha256':e['sha256'],'type':'Evidence'} for e in obj.get('evidence',[])]
 entries += [{'id':a['kind'],'path':a['path'],'sha256':a['sha256'],'type':'Artifact'} for a in obj.get('artifacts',[]) if a.get('availability')=='available']
 encoded=json.dumps(entries,ensure_ascii=True).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
 extra='''<style>@media print {header nav,.skip{display:none!important}body{background:white}main{padding:0;max-width:none}details{display:block}details>*{display:block}svg{break-inside:avoid}.analysis-paragraph,.tldr li,tr,.overview-grid .card,.pillar-top,.tldr{break-inside:avoid}.pillar-top{break-after:avoid}.point-table{max-height:none;overflow:visible}.print-id{font:9px sans-serif;overflow-wrap:anywhere;border-bottom:1px solid #aaa;padding:5px 0}a{color:#153b34}.pdf-index p{overflow-wrap:anywhere;font:9pt sans-serif} }</style>'''
 extra+='''<script>(()=>{document.querySelectorAll('details').forEach(d=>{d.open=true});const entries='''+encoded+''';const section=document.createElement('section');section.className='pdf-index';const title=document.createElement('h1');title.textContent='Evidence and artifact index';section.append(title);const note=document.createElement('p');note.textContent='Identifiers and SHA-256 hashes refer to the version-matched companion bundle; evidence bytes are not embedded in this PDF.';section.append(note);const lookup=new Map();entries.forEach((e,i)=>{const anchor='pdf-asset-'+i;const path='assets/'+e.path.split('/').map(encodeURIComponent).join('/');if(!lookup.has(path))lookup.set(path,anchor);const p=document.createElement('p');p.id=anchor;p.textContent=e.type+': '+e.id+' | companion path: '+e.path+' | SHA-256: '+e.sha256;section.append(p)});for(const a of document.querySelectorAll('a[href]')){const h=a.getAttribute('href');if(h&&h.startsWith('#'))continue;const anchor=lookup.get(h);if(anchor)a.setAttribute('href','#'+anchor);else{a.removeAttribute('href');a.title='Source not included in companion manifest'}}document.body.append(section)})();</script>'''
 extra+='<div class="print-id">'+html.escape(identity)+'</div><section class="full-appendix"><h1>Full report appendix</h1><pre style="white-space:pre-wrap;overflow-wrap:anywhere;font:10pt sans-serif">'+html.escape(markdown)+'</pre></section>'
 if '</body>' not in content:raise ValueError('unsupported reader template')
 return content.replace('</body>',extra+'</body>'),identity

def export(reader_dir,output_dir,browser,expected_digest,timeout=120):
 reader_dir=reader_dir.resolve();output_dir=output_dir.resolve();browser=browser.resolve()
 if not browser.is_file():raise ValueError('browser executable unavailable')
 if output_dir.exists() or output_dir==reader_dir or output_dir.is_relative_to(reader_dir):raise ValueError('choose a fresh output outside reader directory')
 content,identity=print_source(reader_dir/'index.html',reader_dir/'report.json',expected_digest)
 output_dir.mkdir(parents=True);pdf=output_dir/'draft-full.pdf'
 with tempfile.TemporaryDirectory(prefix='scooby-print-') as tmp:
  base=pathlib.Path(tmp);site=base/'site';shutil.copytree(reader_dir,site,symlinks=False);(site/'print.html').write_text(content,encoding='utf-8')
  args=[str(browser),'--headless','--disable-gpu','--disable-extensions','--disable-background-networking','--no-first-run','--no-default-browser-check','--disable-sync','--user-data-dir='+str(base/'profile'),'--print-to-pdf='+str(pdf),'--no-pdf-header-footer',(site/'print.html').as_uri()]
  run=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout,check=False)
  if run.returncode!=0 or not pdf.is_file() or pdf.stat().st_size<100:raise RuntimeError('background PDF rendering failed; inspect local browser setup')
 manifest={'status':'unverified_draft','report_sha256':expected_digest,'report_id':json.loads((reader_dir/'report.json').read_bytes())['report_id'],'report_version':json.loads((reader_dir/'report.json').read_bytes())['report_version'],'input_html_sha256':hashlib.sha256((reader_dir/'index.html').read_bytes()).hexdigest(),'pdf_sha256':hashlib.sha256(pdf.read_bytes()).hexdigest(),'limitations':['Deep content is requested open, but text coverage and every-page visual QA have not been completed.','Not human approved or published.']}
 (output_dir/'export-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8');return manifest
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('reader',type=pathlib.Path);p.add_argument('output',type=pathlib.Path);p.add_argument('--browser',type=pathlib.Path,required=True);p.add_argument('--report-sha256',required=True);a=p.parse_args();print(json.dumps(export(a.reader,a.output,a.browser,a.report_sha256),indent=2))
