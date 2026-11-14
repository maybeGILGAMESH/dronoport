"""Cache official TeX bundle byte ranges using Python's HTTPS transport."""
from pathlib import Path
from http.server import HTTPServer,BaseHTTPRequestHandler
import urllib.request,urllib.error,time,hashlib,json
ROOT=Path(__file__).resolve().parents[1]
URL='https://data1.fullyjustified.net/tlextras-2022.0r0.tar'
cache=ROOT/'.tools/tex-downloads';cache.mkdir(exist_ok=True)
index=cache/'index.gz'
if not index.exists():
    prior=ROOT/'.cache/tectonic_index.gz'
    index.write_bytes(prior.read_bytes() if prior.exists() else urllib.request.urlopen(URL+'.index.gz',timeout=60).read())
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_HEAD(self):
        self.send_response(200);self.send_header('Accept-Ranges','bytes');self.end_headers()
    def do_GET(self):
        if self.path.endswith('.index.gz'):
            data=index.read_bytes();self.send_response(200);self.end_headers();self.wfile.write(data);return
        ran=self.headers.get('Range')
        if not ran:self.send_error(400,'Byte range required');return
        key=ran.replace('=','_').replace('-','_');path=cache/(key+'.bin')
        try:
            if path.exists():data=path.read_bytes()
            else:
                for attempt in range(6):
                    try:
                        req=urllib.request.Request(URL,headers={'Range':ran})
                        with urllib.request.urlopen(req,timeout=60) as r:
                            if r.status!=206:raise RuntimeError('Expected partial official bundle response')
                            data=r.read()
                        path.write_bytes(data);print('Cached',ran,len(data),flush=True);break
                    except urllib.error.HTTPError as e:
                        if e.code not in (429,503) or attempt==5:raise
                        time.sleep(min(30,2**(attempt+1)))
            self.send_response(206);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        except Exception as e:print(type(e).__name__,str(e),flush=True);self.send_error(502,str(e))
HTTPServer(('127.0.0.1',18766),Handler).serve_forever()
