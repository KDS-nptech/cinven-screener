import sys, re, html
from html.parser import HTMLParser
class P(HTMLParser):
    def __init__(self):
        super().__init__(); self.out=[]; self.skip=0; self.cur=[]
    def handle_starttag(self,t,a):
        if t in ('script','style','noscript','svg'): self.skip+=1
        if t in ('p','div','h1','h2','h3','h4','h5','h6','li','br','tr','section','article','header','footer','blockquote'):
            self.flush()
    def handle_endtag(self,t):
        if t in ('script','style','noscript','svg') and self.skip>0: self.skip-=1
        if t in ('p','div','h1','h2','h3','h4','h5','h6','li','tr','section','article','blockquote','a'):
            self.flush()
    def handle_data(self,d):
        if self.skip==0: self.cur.append(d)
    def flush(self):
        s=' '.join(''.join(self.cur).split())
        if s: self.out.append(s)
        self.cur=[]
for f in sys.argv[1:]:
    p=P(); p.feed(open(f,encoding='utf-8',errors='ignore').read()); p.flush()
    print(f"##### {f}")
    seen=set()
    for line in p.out:
        if line in seen and len(line)<40: continue
        seen.add(line); print(line)
