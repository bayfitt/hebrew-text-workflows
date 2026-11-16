#!/usr/bin/env python3
"""Cache source-aligned Dicta proposals; never accept them automatically."""
import argparse,bisect,hashlib,json,time
from pathlib import Path
from urllib.request import Request,urlopen
from concurrent.futures import ThreadPoolExecutor,as_completed

ENDPOINT='https://nakdan-u2-1a.loadbalancer.dicta.org.il/api'
CLIENT='https://abbreviation.dicta.org.il/js/app.62d179aa.js'
def sha(value):return hashlib.sha256(value.encode()).hexdigest()
def jl(path):return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--records',required=True);p.add_argument('--output',required=True);p.add_argument('--cache',required=True)
 p.add_argument('--batch-chars',type=int,default=7000);p.add_argument('--workers',type=int,default=2)
 a=p.parse_args();records=jl(a.records);cache=Path(a.cache);cache.mkdir(parents=True,exist_ok=True)
 batches=[];current=[];size=0
 for record in records:
  if record.get('reading_held'):continue
  if current and size+len(record['source_text'])+2>a.batch_chars:batches.append(current);current=[];size=0
  current.append(record);size+=len(record['source_text'])+2
 if current:batches.append(current)
 def run(index,items):
  text='\n\n'.join(r['source_text'] for r in items)
  payload={'task':'abbrexp','data':text,'useTokenization':True,'genre':'rabbinic'}
  fingerprint=sha(json.dumps(payload,ensure_ascii=False,sort_keys=True));path=cache/(fingerprint+'.json')
  if path.exists():response=json.loads(path.read_text())['response']
  else:
   request=Request(ENDPOINT,data=json.dumps(payload,ensure_ascii=False).encode(),headers={'Content-Type':'text/plain;charset=UTF-8'})
   for attempt in range(3):
    try:
     with urlopen(request,timeout=60) as remote:response=json.loads(remote.read())
     break
    except Exception:
     if attempt==2:raise
     time.sleep(2*(attempt+1))
   path.write_text(json.dumps({'endpoint':ENDPOINT,'official_client':CLIENT,'request_sha256':fingerprint,'source_sha256':sha(text),'response':response},ensure_ascii=False)+'\n')
  tokens=response['data'];assert ''.join(t['str'] for t in tokens)==text,'Provider changed tokenized source'
  starts=[];offset=0
  for r in items:starts.append(offset);offset+=len(r['source_text'])+2
  offset=0;proposals=[]
  for token in tokens:
   start,end=offset,offset+len(token['str']);offset=end
   item=token.get('abbreviation')
   if not item:continue
   record_index=bisect.bisect_right(starts,start)-1
   record=items[record_index];local=start-starts[record_index];stop=end-starts[record_index]
   assert 0<=local<stop<=len(record['source_text']),'Abbreviation crossed passage boundary'
   assert record['source_text'][local:stop]==token['str']
   options=[v if isinstance(v,str) else v['w'] for v in item.get('options',[])]
   proposals.append({'id':record['id'],'source_passage_sha256':sha(record['source_text']),'start_char':local,'end_char':stop,'raw_token':token['str'],'provider_options':options,'source_text':record['source_text'],'evidence':CLIENT,'proposal_status':'automated_not_reviewed','cache_file':str(path)})
  return index,proposals,len(tokens)
 all_results={};token_count=0
 with ThreadPoolExecutor(max_workers=a.workers) as executor:
  pending=[executor.submit(run,i,items) for i,items in enumerate(batches)]
  for future in as_completed(pending):
   i,proposals,tokens=future.result();all_results[i]=proposals;token_count+=tokens
   print(json.dumps({'batch':i+1,'of':len(batches),'proposals':len(proposals)}),flush=True)
 result=[r for i in range(len(batches)) for r in all_results[i]]
 for i,r in enumerate(result):r['occurrence_id']=r['id']+':dicta:'+str(i+1).zfill(4)
 output=Path(a.output);output.parent.mkdir(parents=True,exist_ok=True);output.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in result))
 print(json.dumps({'batches':len(batches),'source_records':len(records),'proposals':len(result),'tokens':token_count,'source_preserved':True,'output':str(output)}),flush=True)
if __name__=='__main__':main()
