#!/usr/bin/env python3
import itertools,json,os,re,shutil,subprocess,sys
from pathlib import Path
from functools import lru_cache
import argparse
BASE=Path(__file__).resolve().parent
parser=argparse.ArgumentParser(description="Landscape Legal trilingual facing-spread PDF")
parser.add_argument("--input", type=Path, required=True)
parser.add_argument("--out", type=Path, required=True)
parser.add_argument("--mode", choices=["adaptive","fixed"], default="adaptive")
parser.add_argument("--require-tnr", action="store_true", help="Fail unless licensed Times New Roman is resolved")
cfgpath=parser.parse_args()
cfg=json.loads(cfgpath.input.read_text(encoding="utf-8"))
if cfg.get("schema_version")!=1: parser.error("expected schema_version 1")
rows=cfg["passages"]
ids=[r["id"] for r in rows]
chapters=cfg["chapters"]
if not ids or len(ids)!=len(set(ids)): parser.error("passage IDs must be nonempty and unique")
if not chapters or chapters[0]["first_id"]!=ids[0]: parser.error("map must start at first passage")
try: starts=[ids.index(c["first_id"]) for c in chapters]
except ValueError: parser.error("chapter starts must refer to passage IDs")
if starts!=sorted(set(starts)): parser.error("chapter map must have unique starts in source order")
groups=[rows[i:j] for i,j in zip(starts,starts[1:]+[len(rows)])]
names=[c["label"] for c in chapters]
idx={}
notes={}
for k,r in enumerate(rows,1):
 r["row"]=k
 idx[k]=r
 if r.get("note"):notes[k]="note"
out=cfgpath.out.resolve()
out.mkdir(exist_ok=True,parents=True)
os.chdir(out)
shutil.copyfile(BASE/"proof.tex","proof.tex")
E={'\\':r'\textbackslash{}','{':r'\{','}':r'\}','$':r'\$','&':r'\&','#':r'\#','_':r'\_','%':r'\%','~':r'\textasciitilde{}','^':r'\textasciicircum{}'}
def esc(s):
 return ''.join(E.get(c,c) for c in s)
def mixed(s):
 parts=re.split(r'([\u0590-\u05ff]+(?:[ "\-\u05f3\u05f4]+[\u0590-\u05ff]+)*)',s)
 return ''.join(r'\foreignlanguage{hebrew}{'+esc(t)+'}' if i%2 else esc(t) for i,t in enumerate(parts))
def args(*ss):return ''.join('{'+str(x)+'}' for x in ss)
def latin_en(r):return mixed(r["en"])
widths=[(0.34,0.32,0.34),(0.32,0.31,0.37),(0.35,0.31,0.34),(0.36,0.30,0.34),(0.32,0.35,0.33),(0.33,0.36,0.31),(0.34,0.30,0.36),(0.36,0.32,0.32),(0.31,0.33,0.36)]
def write(name,v):Path(name).write_text('\n'.join(v)+'\n',encoding='utf-8')
def data(r):return esc(r["he"]),mixed(r["roman"]),latin_en(r)
def note(r):
 return r'\textsuperscript{'+str(r['row'])+'} '+mixed(r[notes[r['row']]])
def measurements():
 rows=[r'\Measure'+args(r['row'],j,*w,*data(r)) for r in idx.values() for j,w in enumerate(widths)]
 rows += [r'\MeasureNote'+args(k,note(r)) for k,r in idx.items() if k in notes]
 write("measure.tex",rows)
def tex(job,measure=False):
 subprocess.run(['lualatex','-interaction=nonstopmode','-halt-on-error','-file-line-error','-no-shell-escape','-jobname='+job,(r'\def\DoMeasure{1}\input{proof.tex}' if measure else 'proof.tex')],check=True,stdout=subprocess.PIPE)
 log=Path(job+'.log').read_text(errors='replace')
 if re.search(r'Missing character:|Overfull \\[hv]box',log):raise RuntimeError('font or layout warning: '+job+'.log')
 return log
def metrics(log):
 m={(int(k),int(j)):tuple(int(z)/65536 for z in vs.split('|')) for k,j,vs in re.findall(r'^METRIC\|(\d+)\|(\d+)\|([\d|]+)',log,re.M)}
 n={int(k):int(v)/65536 for k,v in re.findall(r'^NOTE\|(\d+)\|(\d+)',log,re.M)}
 cap=int(re.search(r'^CAPACITY\|(\d+)',log,re.M)[1])/65536
 assert len(m)==len(idx)*len(widths) and len(n)==sum(k in notes for k in idx)
 return m,n,cap
def plan(m,n,cap,fixed=False):
 # The 46pt page header + 12pt conservative bottom buffer are outside body.
 cap-=58
 allowed=[0] if fixed else list(range(len(widths)))
 ans=[]
 for gi,g in enumerate(groups):
  keys=[r['row'] for r in g]
  @lru_cache(None)
  def best(i,prev):
   if i==len(keys): return 0,[]
   result=(float('inf'),[])
   for j in range(i+1,len(keys)+1):
    for k in range(j,min(j+8,len(keys))+1):
     if k==j and j!=len(keys):continue
     u,v=keys[i:j],keys[j:k]
     nh=sum(n.get(s,0) for s in u+v)+(27+3*sum(s in n for s in u+v) if any(s in n for s in u+v) else 0)
     for a,b in itertools.product(allowed,repeat=2):
      ul=[m[s,a] for s in u];vl=[m[s,b] for s in v]
      eh=sum(max(t)+17 for t in ul)
      ev=sum(max(t)+17 for t in vl)
      if eh>cap or ev+nh>cap:continue
      depths=[eh,ev]
      whitespace=(cap-eh)**2+(cap-nh-ev)**2
      disparity=sum(sum(max(t)-x for x in t) for t in ul+vl)
      jitter=sum(abs(x-y) for x,y in zip(widths[a],widths[b]))+sum(abs(x-y) for x,y in zip(widths[prev],widths[a]))
      cost=2_000_000+whitespace+100*disparity+100_000*jitter
      tail,rest=best(k,b)
      if cost+tail<result[0]:
       result=(cost+tail,[(gi,u,v,a,b,round(eh,2),round(ev,2),round(nh,2))]+rest)
   return result
  score,layout=best(0,0)
  if not layout:raise RuntimeError('No legal fit for section '+names[gi]+'. Split overlong passage at verified matching subparagraph boundaries; do not shrink fonts.')
  ans+=layout
 return ans
def pages(layout):
 cmd=[]
 toc=[]
 seen=set()
 for i,(gi,L,R,a,b,*_) in enumerate(layout,1):
  if gi not in seen:
   toc.append(esc(names[gi])+r'\dotfill '+str(2*i)+r'\par')
   seen.add(gi)
  for side,rows,w in [('Left',L,a),('Right',R,b)]:
   cmd.append(r'\ProofHead'+args(esc(names[gi]),f'Spread {i} / {side}',esc(f'Width ratio {widths[w][0]:.0%} / {widths[w][1]:.0%} / {widths[w][2]:.0%}')))
   for k in rows:
    r=idx[k]; lab=esc(r['id'])+(r'\textsuperscript{'+str(k)+r'}' if k in notes else '')
    cmd.append(r'\ProofRow'+args(*widths[w],lab,*data(r)))
   if side=='Right' and any(k in notes for k in L+R):
    cmd.append(r'\ProofNotes'+args(r'\par\vskip3pt '.join(note(idx[k]) for k in L+R if k in notes)))
   cmd.append(r'\clearpage')
 write('pages.tex',cmd)
 write('contents.tex',toc)

if not shutil.which("lualatex"):sys.exit("Install LuaLaTeX before building")
title=cfg["title"]
write("title.tex",[r"\newcommand{\BookTitle}{"+mixed(title)+"}"])
if cfgpath.require_tnr:
 write("font-policy.tex",[r"\def\RequireTimesNewRoman{1}"])
else:
 write("font-policy.tex",[])
measurements()
m,n,cap=metrics(tex("measure",True))
layout=plan(m,n,cap,fixed=(cfgpath.mode=="fixed"))
pages(layout)
write("layout.json",[json.dumps(layout,indent=2)])
tex("book")
