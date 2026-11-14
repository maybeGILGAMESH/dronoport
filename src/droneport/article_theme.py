"""White adaptation of the user's Cinematic Atlas, with print-sized typography."""
import matplotlib as mpl
from matplotlib.colors import LinearSegmentedColormap
from .vendor import atlas_theme as atlas

COLORS={'A':'#0072b2','B':'#007f5f','C':'#bb4e12'}
INK='#172033'
MUTED='#5b6472'
SEQUENTIAL=LinearSegmentedColormap.from_list('atlas_white_blue',['#ffffff','#d4e8f2','#69a9ce','#0072b2','#073f64'])
SEQUENTIAL.set_bad('#d9dee8')

def apply_theme():
    # The registry resolves VOID at export time; no dark backgrounds survive.
    atlas.VOID=atlas.PANEL=atlas.PANEL_HI='#ffffff'
    atlas.INK=INK;atlas.INK_DIM=MUTED;atlas.INK_FAINT=MUTED
    atlas.EDGE='#aab2bf';atlas.GRID='#d9dee8'
    atlas.register_fonts()
    mpl.rcParams.update({'figure.facecolor':'white','axes.facecolor':'white','savefig.facecolor':'white',
        'savefig.edgecolor':'white','savefig.transparent':False,'font.family':'DejaVu Sans','font.size':9,
        'axes.labelsize':9,'axes.titlesize':10,'axes.titleweight':'bold','axes.titlelocation':'left',
        'axes.labelcolor':INK,'text.color':INK,'axes.titlecolor':INK,'axes.edgecolor':'#aab2bf',
        'xtick.color':MUTED,'ytick.color':MUTED,'xtick.labelsize':8,'ytick.labelsize':8,
        'axes.spines.top':False,'axes.spines.right':False,'axes.linewidth':.7,
        'grid.color':'#d9dee8','grid.linewidth':.5,'axes.axisbelow':True,
        'legend.facecolor':'white','legend.edgecolor':'#c7cdd6','legend.fontsize':7.5,
        'legend.frameon':False,'pdf.fonttype':42,'ps.fonttype':42,'svg.fonttype':'none',
        'axes.prop_cycle':mpl.cycler(color=list(COLORS.values())+['#8e659d','#a77a10']),
        'lines.linewidth':1.5,'lines.markersize':4,'savefig.dpi':300})
