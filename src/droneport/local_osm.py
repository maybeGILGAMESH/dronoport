"""Local XYZ raster tiles from a selective, attributed OSM extract."""
from pathlib import Path
from collections import Counter
import gzip, json, math, io, threading
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from shapely.geometry import LineString, Polygon, Point, box
from shapely.strtree import STRtree
from .ingest import ROOT


def xy(lon, lat):
    return (lon + 180) / 360, (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2


class Basemap:
    def __init__(self, output):
        with gzip.open(ROOT / 'data/cartography/basemap.json.gz', 'rt') as f:
            data = json.load(f)
        self.meta, self.geometry = [], []
        levels = {'motorway':5,'trunk':6,'primary':7,'secondary':8,'tertiary':9,'unclassified':11,'residential':11}
        for kind, subtype, coords, oid in data['features']:
            pts = [xy(x, y) for x, y in coords]
            geom = Polygon(pts) if kind == 'water' and len(pts) >= 4 else LineString(pts)
            base = subtype.removesuffix('_link')
            zoom = levels.get(base,11) if kind == 'road' else 7 if kind == 'water' else 8 if kind == 'rail' else 11 if subtype == 'stream' else 6
            if '_link' in subtype:zoom=max(zoom,10)
            self.geometry.append(geom)
            self.meta.append((kind,subtype,zoom))
        self.tree = STRtree(self.geometry)
        self.places = sorted([(xy(x,y),name,kind,oid) for x,y,name,kind,oid in data['places'] if name],key=lambda p:({'city':0,'town':1,'village':2}[p[2]],p[3]))
        self.output = Path(output);self.output.mkdir(parents=True,exist_ok=True)
        self.fonts = {k:ImageFont.truetype(str(ROOT / 'reports/latex/fonts/DejaVuSans.ttf'),s) for k,s in [('city',23),('town',21),('village',18)]}
        self.lock = threading.Lock();self.count = 0
        print('Local OSM ready:',len(self.geometry),'geometries',flush=True)

    def tile(self,z,x,y):
        path=self.output/str(z)/str(x)/(str(y)+'.png')
        if path.exists():return path.read_bytes()
        # A shared render lock bounds peak memory and duplicate work.
        with self.lock:
            if path.exists():return path.read_bytes()
            size=512;pad=100;scale=size*2**z;left=x*size-pad;top=y*size-pad
            im=Image.new('RGB',(size+2*pad,size+2*pad),'#fafbf9');draw=ImageDraw.Draw(im)
            bounds=box(left/scale,top/scale,(left+im.width)/scale,(top+im.height)/scale)
            indices=[int(i) for i in self.tree.query(bounds) if self.meta[int(i)][2]<=z]
            def coords(g):return [(p[0]*scale-left,p[1]*scale-top) for p in (g.exterior.coords if g.geom_type=='Polygon' else g.coords)]
            water=[i for i in indices if self.meta[i][0]=='water']
            for i in water:
                g=self.geometry[i]
                if g.geom_type=='Polygon':draw.polygon(coords(g),fill='#dceef2')
            for i in indices:
                kind,subtype,_=self.meta[i]
                if kind=='waterline':draw.line(coords(self.geometry[i]),fill='#badbe5',width=3 if subtype=='river' else 1)
                elif kind=='rail':draw.line(coords(self.geometry[i]),fill='#b7bfc5',width=2)
            road_ids=sorted([i for i in indices if self.meta[i][0]=='road'],key=lambda i:self.meta[i][2],reverse=True)
            for i in road_ids:
                subtype=self.meta[i][1];major=subtype in ('motorway','trunk','primary');width=(5 if major else 3) if z>=9 else (3 if major else 2)
                pts=coords(self.geometry[i]);draw.line(pts,fill='#ffffff',width=width+3)
                draw.line(pts,fill='#e4ce9b' if major else '#d8dce0',width=width)
            occupied=[]
            for (px,py),name,kind,oid in self.places:
                if z<({'city':6,'town':8,'village':11}[kind]):continue
                xpix,ypix=px*scale-left,py*scale-top
                if not(-40<xpix<im.width+40 and -30<ypix<im.height+30):continue
                font=self.fonts[kind];bb=draw.textbbox((xpix,ypix),name,font=font,anchor='mm',stroke_width=2)
                expanded=(bb[0]-7,bb[1]-4,bb[2]+7,bb[3]+4)
                if any(not(expanded[2]<a or expanded[0]>c or expanded[3]<b or expanded[1]>d) for a,b,c,d in occupied):continue
                occupied.append(expanded)
                draw.text((xpix,ypix),name,font=font,fill='#677580',anchor='mm',stroke_width=3,stroke_fill='#ffffff')
            im=im.crop((pad,pad,pad+size,pad+size));buf=io.BytesIO();im.save(buf,format='PNG',optimize=True)
            path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(buf.getvalue());self.count+=1
            return buf.getvalue()
