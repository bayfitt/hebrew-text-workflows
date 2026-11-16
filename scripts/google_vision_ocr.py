#!/usr/bin/env python3
"""Independent Google Cloud Vision PDF OCR, resumable per supplied PDF page.

Reads an existing API key through an environment variable, or uses the user's
already configured ADC project. Credentials and request headers are never saved.
Official API: https://docs.cloud.google.com/vision/docs/file-small-batch
"""
import argparse
import base64
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ENDPOINT='https://vision.googleapis.com/v1/files:annotate'
from workflow_io import pdf_page_count, parse_pages, write_records

def authorization(key_env):
    key=os.environ.get(key_env,'').strip()
    if key:
        return {'x-goog-api-key':key},'api_key',None
    # Existing setup uses gcloud ADC rather than a key embedded in a script.
    adc=Path(os.environ.get('GOOGLE_APPLICATION_CREDENTIALS',str(Path.home()/'.config/gcloud/application_default_credentials.json')))
    metadata=json.loads(adc.read_text())
    project=metadata.get('quota_project_id')
    if not project:raise RuntimeError('Existing ADC quota project is not configured')
    result=subprocess.run(['gcloud','auth','application-default','print-access-token'],capture_output=True,text=True,timeout=30)
    if result.returncode or not result.stdout.strip():raise RuntimeError('Existing Google Cloud credentials could not provide an access token')
    return {'Authorization':'Bearer '+result.stdout.strip(),'x-goog-user-project':project},'application_default_credentials',project

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--pdf',required=True)
    p.add_argument('--pages',default='all')
    p.add_argument('--out',required=True)
    p.add_argument('--layout',choices=['single','two_up'],default='single')
    p.add_argument('--key-env',default='GOOGLE_VISION_API_KEY')
    a=p.parse_args()
    source=Path(a.pdf).read_bytes();digest=hashlib.sha256(source).hexdigest()
    page_count=pdf_page_count(a.pdf)
    out=Path(a.out);(out/'spreads').mkdir(parents=True,exist_ok=True)
    requested=parse_pages(a.pages,page_count)
    pending=[]
    for page in requested:
        f=out/'spreads'/f'{page:03}.json'
        if f.exists():
            old=json.loads(f.read_text())
            assert old['source_sha256']==digest and old['pdf_spread']==page
            assert old.get('status')=='success'
        else:pending.append(page)
    if not pending:
        from vision_records import records_from_cache
        write_records(out/'records.jsonl',records_from_cache(out/'spreads',digest,requested,a.layout))
        print(json.dumps({'status':'cached','requested_pages':len(requested)}));return
    headers,auth_method,project=authorization(a.key_env)
    headers.update({'Content-Type':'application/json','Accept':'application/json'})
    encoded=base64.b64encode(source).decode('ascii')
    for offset in range(0,len(pending),5):
        group=pending[offset:offset+5]
        payload={'requests':[{'inputConfig':{'content':encoded,'mimeType':'application/pdf'},'features':[{'type':'DOCUMENT_TEXT_DETECTION'}],'pages':group}]}
        body=json.dumps(payload).encode()
        result=None
        for attempt in range(3):
            req=Request(ENDPOINT,data=body,headers=headers,method='POST')
            try:
                with urlopen(req,timeout=55) as response:result=json.load(response)
                break
            except HTTPError as exc:
                detail=exc.read().decode(errors='replace')
                # Google error text should not include headers, but redact any
                # accidental literal credential before writing a diagnostic.
                for name in ['Authorization','x-goog-api-key']:
                    if name in headers:detail=detail.replace(headers[name],'[REDACTED]')
                if exc.code in [429,500,502,503,504] and attempt<2:
                    time.sleep(2*(attempt+1));continue
                error={'status':'API_error','http_status':exc.code,'detail':detail[:3000],'requested_spreads':group,'auth_method':auth_method,'quota_project':project}
                (out/'last-error.json').write_text(json.dumps(error,ensure_ascii=False)+'\n')
                print(json.dumps(error,ensure_ascii=False),flush=True);raise SystemExit(1)
            except URLError:
                if attempt<2:time.sleep(2*(attempt+1));continue
                raise RuntimeError('Cloud Vision connection failed; request headers were not logged') from None
        assert result is not None
        files=result.get('responses',[])
        assert len(files)==1 and not files[0].get('error'),files[0].get('error') if files else 'No file response'
        answers=files[0].get('responses',[])
        returned=[answer.get('context',{}).get('pageNumber') for answer in answers]
        assert set(returned)==set(group) and len(returned)==len(group),('page response mismatch',returned,group)
        stats=[]
        for answer in answers:
            page=answer['context']['pageNumber']
            assert not answer.get('error'),answer.get('error')
            annotation=answer.get('fullTextAnnotation',{})
            record={'pdf_spread':page,'source_sha256':digest,'provider':'Google Cloud Vision','feature':'DOCUMENT_TEXT_DETECTION','auth_method':auth_method,'quota_project':project,'created_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'status':'success','response':answer}
            target=out/'spreads'/f'{page:03}.json';temp=target.with_suffix('.tmp');temp.write_text(json.dumps(record,ensure_ascii=False)+'\n');temp.replace(target)
            stats.append({'spread':page,'characters':len(annotation.get('text','')),'annotation_pages':len(annotation.get('pages',[]))})
        print(json.dumps({'status':'batch_complete','pages':stats,'auth_method':auth_method},ensure_ascii=False),flush=True)
    from vision_records import records_from_cache
    write_records(out/'records.jsonl',records_from_cache(out/'spreads',digest,requested,a.layout))

if __name__=='__main__':main()
