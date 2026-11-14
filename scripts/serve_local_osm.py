"""Loopback-only OSM tile server. Public OSM tile servers are never contacted."""
from pathlib import Path
import sys,json,argparse,re
from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from droneport.local_osm import Basemap
from droneport.ingest import ROOT
parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8765);args=parser.parse_args()
root=ROOT/'reports/latex/maps';renderer=Basemap(root/'tiles')
class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*a,**kw):super().__init__(*a,directory=str(root),**kw)
    def log_message(self,*a):pass
    def do_GET(self):
        path=self.path.split('?')[0]
        if path=='/health':
            body=json.dumps(dict(ready=True,features=len(renderer.geometry))).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(body);return
        m=re.fullmatch(r'/tiles/(\d+)/(\d+)/(\d+)\.png',path)
        if m:
            z,x,y=map(int,m.groups())
            if not(0<=z<=13 and 0<=x<2**z and 0<=y<2**z):self.send_error(404);return
            body=renderer.tile(z,x,y);self.send_response(200);self.send_header('Content-Type','image/png');self.send_header('Cache-Control','public,max-age=31536000');self.end_headers();self.wfile.write(body);return
        super().do_GET()
server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
print('OSM server: http://127.0.0.1:'+str(server.server_port),flush=True)
server.serve_forever()
