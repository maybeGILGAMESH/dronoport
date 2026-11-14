"""Cinematic publication theme for the two-study tensor-restoration atlas.

Тёмная «нефтяная» тема NEBULA NOIR: собственные colormaps, неоновые
primitives, poster-типографика и статистические помощники Q1-уровня.
Модуль не хранит состояния анализа — только оформление и вычисления.
"""

from __future__ import annotations

import glob
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib import font_manager
from matplotlib.colors import LinearSegmentedColormap, to_rgba
from matplotlib.patches import FancyBboxPatch
import matplotlib.patheffects as pe

# --------------------------------------------------------------- typography ---
_LATO_GLOB = "/usr/share/fonts/truetype/lato/*.ttf"


def register_fonts() -> list[str]:
    """Регистрирует системную Lato в matplotlib (кириллица поддержана)."""
    registered = []
    for path in sorted(glob.glob(_LATO_GLOB)):
        try:
            font_manager.fontManager.addfont(path)
            registered.append(Path(path).name)
        except Exception:
            continue
    return registered


# ------------------------------------------------------------------ palette ---
VOID = "#04060E"          # внешний фон кадра
PANEL = "#090D1A"         # фон панели
PANEL_HI = "#111730"      # подсветка панели
GRID = "#1C2540"          # линии сетки
EDGE = "#2A3557"          # рамки
INK = "#EEF3FF"           # основной текст
INK_DIM = "#93A2C6"       # вторичный текст
INK_FAINT = "#5A688C"     # третичный текст

MINT = "#00F5D4"          # ключевой акцент
CYAN = "#00BBF9"
VIOLET = "#9B5DE5"
PINK = "#F15BB5"
GOLD = "#FEE440"
CORAL = "#FF7B54"
STEEL = "#7B8BB2"
CRIMSON = "#FF3D71"
LIME = "#00F5A0"

GOOD = LIME
BAD = CRIMSON
WARN = "#FFB84D"
ACCENT = MINT
ACCENT_2 = PINK

CYCLE = [MINT, PINK, GOLD, CYAN, VIOLET, CORAL, LIME, STEEL]

FAMILY_COLORS = {
    "itc": MINT,
    "cpd": VIOLET,
    "tucker": PINK,
    "tensor_train": GOLD,
    "svd": CYAN,
    "pca": CORAL,
    "zca": STEEL,
}

MASK_MODE_COLORS = {
    "direct_mask": MINT,
    "expanded_mask": CYAN,
    "partial_mask": VIOLET,
    "under_mask": PINK,
    "boundary_band": GOLD,
    "no_mask": STEEL,
}

MASK_SOURCE_COLORS = {
    "oracle_abs_error": CORAL,
    "rect_truth": GOLD,
    "image_only_proxy_v2": MINT,
    "proxy_thin_edges": CYAN,
}

STUDY_COLORS = {"R1": CYAN, "R2": PINK}


def _cmap(name: str, colors: list[str]) -> LinearSegmentedColormap:
    cm = LinearSegmentedColormap.from_list(name, colors, N=512)
    cm.set_bad(PANEL)
    try:
        mpl.colormaps.register(cm, name=name, force=True)
    except Exception:
        pass
    return cm


# Собственные colormaps: не viridis и не magma.
NEBULA = _cmap("nebula", ["#04060E", "#131A3F", "#2E1A72", "#6B1E9E",
                          "#C22B8C", "#F5566B", "#FF9F45", "#FFE59A", "#FFFFFF"])
AURORA = _cmap("aurora", ["#04060E", "#062B3F", "#0A5A6B", "#12908C",
                          "#4FD1A5", "#B8F5C8", "#F4FFF9"])
EMBER = _cmap("ember", ["#04060E", "#2B0B3F", "#7A1264", "#C42A5C",
                        "#F26B3A", "#FFC24B", "#FFF6C2"])
GLACIER = _cmap("glacier", ["#04060E", "#0B1B3E", "#12386F", "#1E6FA8",
                            "#37B3D8", "#8FE9F5", "#F0FEFF"])
# Диверегентная: розово-красный (хуже) → тёмный ноль → мятный (лучше).
TIDE = _cmap("tide", ["#FFC2D8", "#FF3D71", "#B02A5C", "#3A1430", "#090D1A",
                      "#0E3A38", "#12A08C", "#00F5A0", "#CBFFE6"])
# Плотность для hexbin: стартует с цвета панели, поэтому фон «сливается».
DEEPSPACE = _cmap("deepspace", ["#090D1A", "#14224A", "#1B4C8C", "#1E8BB8",
                                "#2FD1C0", "#9FF5C8", "#FEE440", "#FFFFFF"])

SEQ = NEBULA
DENSITY = DEEPSPACE
DIVERGE = TIDE
ERRMAP = EMBER


# ------------------------------------------------------------------- rcparams --
def apply_theme(inline_dpi: int = 100) -> None:
    """Применяет тёмную кинематографичную тему ко всем последующим фигурам."""
    register_fonts()
    families = [f.name for f in font_manager.fontManager.ttflist]
    body = ["Lato", "DejaVu Sans"] if "Lato" in families else ["DejaVu Sans"]
    mpl.rcParams.update({
        "figure.facecolor": VOID,
        "figure.edgecolor": VOID,
        "savefig.facecolor": VOID,
        "savefig.edgecolor": VOID,
        "axes.facecolor": PANEL,
        "axes.edgecolor": EDGE,
        "axes.linewidth": 0.9,
        "axes.labelcolor": INK_DIM,
        "axes.titlecolor": INK,
        "axes.titlesize": 13.5,
        "axes.titleweight": "bold",
        "axes.titlelocation": "left",
        "axes.titlepad": 10,
        "axes.labelsize": 11,
        "axes.labelweight": "medium",
        "axes.grid": True,
        "axes.axisbelow": True,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "grid.color": GRID,
        "grid.linestyle": "-",
        "grid.linewidth": 0.6,
        "grid.alpha": 0.55,
        "font.family": body,
        "font.size": 10.5,
        "text.color": INK,
        "xtick.color": INK_FAINT,
        "ytick.color": INK_FAINT,
        "xtick.labelcolor": INK_DIM,
        "ytick.labelcolor": INK_DIM,
        "xtick.labelsize": 9.5,
        "ytick.labelsize": 9.5,
        "xtick.direction": "out",
        "ytick.direction": "out",
        "xtick.major.size": 3.5,
        "ytick.major.size": 3.5,
        "xtick.major.width": 0.8,
        "ytick.major.width": 0.8,
        "legend.frameon": True,
        "legend.facecolor": PANEL_HI,
        "legend.edgecolor": EDGE,
        "legend.framealpha": 0.92,
        "legend.labelcolor": INK,
        "legend.fontsize": 9.5,
        "legend.title_fontsize": 9.5,
        "image.cmap": "nebula",
        "figure.dpi": inline_dpi,
        "savefig.dpi": 300,
        "savefig.bbox": "tight",
        "figure.autolayout": False,
        "axes.prop_cycle": mpl.cycler(color=CYCLE),
        "path.simplify": True,
        "path.simplify_threshold": 1.0,
        "agg.path.chunksize": 20000,
    })


# ------------------------------------------------------------- text helpers ---
def glow_text(*, lw: float = 3.2, color: str = VOID, alpha: float = 0.75):
    """Path-effect: мягкая обводка, отделяющая подписи от плотного фона."""
    return [pe.withStroke(linewidth=lw, foreground=color, alpha=alpha)]


def neon_text(color: str = MINT, lw: float = 4.0, alpha: float = 0.35):
    """Path-effect: неоновое свечение вокруг текста."""
    return [pe.withStroke(linewidth=lw, foreground=color, alpha=alpha),
            pe.Normal()]


def spaced(text: str, gap: str = "\u2009") -> str:
    """Разрядка букв для kicker-строк постера."""
    return gap.join(text.upper())


def _pt_to_fig(fig, points: float) -> float:
    """Переводит пункты в долю высоты кадра — отступы не зависят от размера."""
    return points / (fig.get_figheight() * 72.0)


def hero_title(fig, kicker: str, title: str, subtitle: str | None = None, *,
               y: float = 0.995, x: float = 0.012, accent: str = MINT,
               title_size: float = 34, kicker_size: float = 11,
               subtitle_size: float = 12.5) -> None:
    """Постерная шапка кадра: kicker с разрядкой, крупный титул, подзаголовок."""
    fig.text(x, y, spaced(kicker), color=accent, fontsize=kicker_size,
             fontweight="bold", va="top", ha="left",
             path_effects=neon_text(accent, lw=3.5, alpha=0.28))
    y_title = y - _pt_to_fig(fig, kicker_size * 2.05)
    fig.text(x, y_title, title, color=INK, fontsize=title_size,
             fontweight="black", va="top", ha="left",
             path_effects=glow_text(lw=4.0))
    if subtitle:
        fig.text(x, y_title - _pt_to_fig(fig, title_size * 1.32), subtitle,
                 color=INK_DIM, fontsize=subtitle_size, va="top", ha="left",
                 linespacing=1.45)


def footer(fig, source: str, note: str = "", *, y: float | None = None,
           x: float = 0.012) -> None:
    """Штамп происхождения данных — обязательная часть Q1-фигуры."""
    text = f"источник: {source}"
    if note:
        text += f"   ·   {note}"
    fig.text(x, _pt_to_fig(fig, 4) if y is None else y, text, color=INK_FAINT,
             fontsize=8.0, va="bottom", ha="left", family="DejaVu Sans Mono")


def axis_title(ax, title: str, subtitle: str | None = None, *,
               size: float = 13.0, color: str = INK):
    """Заголовок панели с необязательным пояснением под ним."""
    ax.set_title(title, loc="left", fontsize=size, fontweight="bold",
                 color=color, pad=18 if subtitle else 9)
    if subtitle:
        ax.annotate(subtitle, xy=(0, 1.0), xytext=(0, 5),
                    xycoords="axes fraction", textcoords="offset points",
                    fontsize=9.2, color=INK_FAINT, va="bottom", ha="left")


def direction_hint(ax, text: str = "лучше →", corner: str = "upper right",
                   color: str = GOOD) -> None:
    """Подсказка «куда хорошо» — снимает половину вопросов рецензента."""
    pos = {"upper right": (0.985, 0.955), "upper left": (0.015, 0.955),
           "lower right": (0.985, 0.05), "lower left": (0.015, 0.05)}[corner]
    ha = "right" if "right" in corner else "left"
    ax.annotate(text, xy=pos, xycoords="axes fraction", ha=ha, va="center",
                fontsize=9.2, fontweight="bold", color=color,
                bbox=dict(boxstyle="round,pad=0.34", fc=PANEL_HI,
                          ec=color, lw=0.9, alpha=0.95))


# ------------------------------------------------------------ panel styling ---
def style_axes(ax, *, grid_axis: str = "both", face: str = PANEL,
               spines: tuple[str, ...] = ("left", "bottom")) -> None:
    ax.set_facecolor(face)
    for name, spine in ax.spines.items():
        spine.set_visible(name in spines)
        spine.set_color(EDGE)
    if grid_axis == "none":
        ax.grid(False)
    else:
        ax.grid(True, axis=grid_axis, color=GRID, linewidth=0.6, alpha=0.55)
    ax.set_axisbelow(True)


def blank_axes(ax) -> None:
    ax.set_facecolor("none")
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)


def image_axes(ax, title: str | None = None, *, color: str = EDGE,
               lw: float = 1.1) -> None:
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(True)
        spine.set_color(color)
        spine.set_linewidth(lw)
    if title:
        ax.set_title(title, fontsize=10, fontweight="bold", color=INK,
                     loc="center", pad=6)


def dark_colorbar(fig, mappable, ax, label: str = "", *, pad: float = 0.02,
                  fraction: float = 0.035, orientation: str = "vertical",
                  size: float = 9.0):
    cb = fig.colorbar(mappable, ax=ax, pad=pad, fraction=fraction,
                      orientation=orientation)
    cb.outline.set_edgecolor(EDGE)
    cb.outline.set_linewidth(0.8)
    cb.ax.tick_params(colors=INK_DIM, labelsize=size, width=0.8, length=3)
    if label:
        cb.set_label(label, color=INK_DIM, fontsize=size + 0.6)
    return cb


def vignette(fig, *, alpha: float = 0.30, n: int = 90) -> None:
    """Мягкая виньетка по краям кадра для «киношного» объёма."""
    ax = fig.add_axes([0, 0, 1, 1], zorder=-10)
    ax.set_axis_off()
    yy, xx = np.mgrid[0:n, 0:n]
    r = np.sqrt(((xx - n / 2) / (n / 2)) ** 2 + ((yy - n / 2) / (n / 2)) ** 2)
    ax.imshow(np.clip(r - 0.55, 0, None), cmap=LinearSegmentedColormap.from_list(
        "vig", [(0, 0, 0, 0), (0, 0, 0, alpha)]), extent=(0, 1, 0, 1),
        aspect="auto", interpolation="bilinear")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)


# ----------------------------------------------------------- glow primitives --
def glow_line(ax, x, y, *, color: str = MINT, lw: float = 2.2, layers: int = 5,
              alpha: float = 0.10, zorder: float = 3, label=None, **kwargs):
    """Неоновая линия: несколько размытых слоёв + яркое ядро."""
    for i in range(layers, 0, -1):
        ax.plot(x, y, color=color, lw=lw + i * 1.9, alpha=alpha,
                solid_capstyle="round", zorder=zorder - 0.1, **kwargs)
    return ax.plot(x, y, color=color, lw=lw, solid_capstyle="round",
                   zorder=zorder, label=label, **kwargs)


def glow_scatter(ax, x, y, *, color: str = MINT, s: float = 40,
                 layers: int = 3, alpha: float = 0.13, zorder: float = 4,
                 edgecolor: str = VOID, lw: float = 0.6, label=None, **kwargs):
    for i in range(layers, 0, -1):
        ax.scatter(x, y, s=s * (1 + 0.85 * i), color=color, alpha=alpha,
                   linewidths=0, zorder=zorder - 0.1, **kwargs)
    return ax.scatter(x, y, s=s, color=color, edgecolors=edgecolor,
                      linewidths=lw, zorder=zorder, label=label, **kwargs)


def gradient_band(ax, x, y_low, y_high, *, cmap=None, color=None, alpha=0.55,
                  zorder=2, resolution: int = 240):
    """Заливка между кривыми вертикальным градиентом цвета."""
    x = np.asarray(x, dtype=float)
    y_low = np.asarray(y_low, dtype=float)
    y_high = np.asarray(y_high, dtype=float)
    if cmap is None:
        base = to_rgba(color or MINT)
        cmap = LinearSegmentedColormap.from_list(
            "band", [(base[0], base[1], base[2], 0.05),
                     (base[0], base[1], base[2], 1.0)])
    grad = np.linspace(0, 1, resolution).reshape(-1, 1)
    im = ax.imshow(grad, extent=(x.min(), x.max(), np.nanmin(y_low),
                                 np.nanmax(y_high)),
                   origin="lower", aspect="auto", cmap=cmap, alpha=alpha,
                   zorder=zorder)
    poly = ax.fill_between(x, y_low, y_high, facecolor="none", edgecolor="none")
    im.set_clip_path(poly.get_paths()[0], transform=ax.transData)
    return im


def ridge(ax, values, *, base: float, height: float, color: str,
          cmap=None, bw: float = 0.9, grid: int = 320, lo=None, hi=None,
          lw: float = 1.6, alpha_fill: float = 0.95, zorder: float = 3):
    """Один «гребень» ridgeline-графика с градиентной заливкой."""
    from scipy.stats import gaussian_kde
    v = pd.to_numeric(pd.Series(values), errors="coerce").dropna().to_numpy()
    if v.size < 12 or np.allclose(v.std(), 0):
        return None
    lo = np.nanquantile(v, 0.001) if lo is None else lo
    hi = np.nanquantile(v, 0.999) if hi is None else hi
    xs = np.linspace(lo, hi, grid)
    kde = gaussian_kde(v, bw_method=bw * v.size ** (-1 / 5.))
    dens = kde(xs)
    dens = dens / dens.max() * height
    top = base + dens
    if cmap is None:
        cmap = LinearSegmentedColormap.from_list(
            "r", [PANEL, color, "#FFFFFF"], N=256)
    grad = np.linspace(0, 1, 256).reshape(1, -1)
    im = ax.imshow(grad, extent=(lo, hi, base, base + height * 1.02),
                   origin="lower", aspect="auto", cmap=cmap,
                   alpha=alpha_fill, zorder=zorder)
    poly = ax.fill_between(xs, base, top, facecolor="none", edgecolor="none")
    im.set_clip_path(poly.get_paths()[0], transform=ax.transData)
    ax.plot(xs, top, color="#FFFFFF", lw=lw, alpha=0.92, zorder=zorder + 1,
            solid_capstyle="round")
    ax.plot(xs, top, color=color, lw=lw + 3.0, alpha=0.20, zorder=zorder + 0.5)
    ax.hlines(base, lo, hi, color=EDGE, lw=0.7, alpha=0.7, zorder=zorder - 0.5)
    return dict(x=xs, top=top, median=float(np.median(v)), n=int(v.size))


def beeswarm(ax, values, *, y: float, color: str, width: float = 0.34,
             s: float = 6, alpha: float = 0.35, rng=None, max_points=4000,
             zorder: float = 3):
    """Разбросанный «пчелиный роёк» точек вокруг горизонтальной линии."""
    v = pd.to_numeric(pd.Series(values), errors="coerce").dropna().to_numpy()
    if v.size == 0:
        return
    rng = rng or np.random.default_rng(42)
    if v.size > max_points:
        v = rng.choice(v, max_points, replace=False)
    order = np.argsort(v)
    ranks = np.empty_like(order, dtype=float)
    ranks[order] = np.arange(v.size)
    hist, edges = np.histogram(v, bins=min(90, max(12, v.size // 25)))
    idx = np.clip(np.digitize(v, edges[1:-1]), 0, len(hist) - 1)
    local = hist[idx] / max(hist.max(), 1)
    jitter = rng.uniform(-1, 1, v.size) * width * np.sqrt(local)
    ax.scatter(v, y + jitter, s=s, color=color, alpha=alpha, linewidths=0,
               zorder=zorder, rasterized=True)


def kpi_card(ax, value: str, label: str, sub: str = "", *, color: str = MINT,
             value_size: float = 30, label_size: float = 10.5,
             sub_size: float = 8.6) -> None:
    """Карточка ключевого числа с неоновой рамкой."""
    blank_axes(ax)
    ax.add_patch(FancyBboxPatch(
        (0.02, 0.05), 0.96, 0.90, transform=ax.transAxes,
        boxstyle="round,pad=0.012,rounding_size=0.055",
        facecolor=PANEL_HI, edgecolor=color, linewidth=1.5, alpha=0.95,
        zorder=0))
    ax.add_patch(FancyBboxPatch(
        (0.02, 0.05), 0.96, 0.90, transform=ax.transAxes,
        boxstyle="round,pad=0.012,rounding_size=0.055",
        facecolor="none", edgecolor=color, linewidth=6.0, alpha=0.10,
        zorder=0))
    ax.text(0.5, 0.63, value, ha="center", va="center", fontsize=value_size,
            fontweight="black", color=color, transform=ax.transAxes,
            path_effects=neon_text(color, lw=6, alpha=0.22))
    ax.text(0.5, 0.315, label, ha="center", va="center", fontsize=label_size,
            color=INK, transform=ax.transAxes, fontweight="bold",
            linespacing=1.35)
    if sub:
        ax.text(0.5, 0.14, sub, ha="center", va="center", fontsize=sub_size,
                color=INK_DIM, transform=ax.transAxes, linespacing=1.3)


def dumbbell(ax, labels, before, after, *, before_label="До", after_label="После",
             before_color=BAD, after_color=GOOD, rail=EDGE, s=58):
    labels = list(labels)
    before = np.asarray(before, dtype=float)
    after = np.asarray(after, dtype=float)
    y = np.arange(len(labels))
    for yi, b, a in zip(y, before, after):
        colour = GOOD if a >= b else BAD
        ax.plot([b, a], [yi, yi], color=colour, lw=5.5, alpha=0.16,
                solid_capstyle="round", zorder=1)
        ax.plot([b, a], [yi, yi], color=colour, lw=1.6, alpha=0.8,
                solid_capstyle="round", zorder=2)
    ax.scatter(before, y, s=s, color=before_color, edgecolors=VOID, lw=0.8,
               zorder=4, label=before_label)
    ax.scatter(after, y, s=s, color=after_color, edgecolors=VOID, lw=0.8,
               zorder=4, label=after_label)
    ax.set_yticks(y)
    ax.set_yticklabels(labels)
    ax.set_ylim(-0.7, len(labels) - 0.3)
    return y


def forest(ax, frame, label_col, *, mean="mean", low="ci_low", high="ci_high",
           color=MINT, ref: float = 0.0, sort=True, size=42):
    frame = frame.sort_values(mean).reset_index(drop=True) if sort else frame
    y = np.arange(len(frame))
    ax.axvline(ref, color=INK_FAINT, lw=1.0, ls="--", zorder=1)
    for yi, row in zip(y, frame.itertuples()):
        lo, hi = getattr(row, low), getattr(row, high)
        m = getattr(row, mean)
        colour = GOOD if lo > ref else (BAD if hi < ref else STEEL)
        ax.plot([lo, hi], [yi, yi], color=colour, lw=5.0, alpha=0.18,
                solid_capstyle="round", zorder=2)
        ax.plot([lo, hi], [yi, yi], color=colour, lw=1.5, alpha=0.9,
                solid_capstyle="round", zorder=3)
        ax.scatter([m], [yi], s=size, color=colour, edgecolors=VOID, lw=0.8,
                   zorder=4)
    ax.set_yticks(y)
    ax.set_yticklabels(frame[label_col])
    ax.set_ylim(-0.7, len(frame) - 0.3)
    return frame


def heat(ax, matrix, *, cmap=DIVERGE, center=None, vmin=None, vmax=None,
         annot=True, fmt="{:+.1f}", fontsize=8.4, xrot=32, cell_edge=VOID,
         annot_color=None):
    """Тепловая карта с тонкими разделителями и адаптивным цветом подписей."""
    values = matrix.to_numpy(dtype=float)
    if center is not None:
        span = np.nanmax(np.abs(values - center))
        vmin, vmax = center - span, center + span
    im = ax.imshow(values, cmap=cmap, vmin=vmin, vmax=vmax, aspect="auto",
                   interpolation="nearest")
    ax.set_xticks(np.arange(matrix.shape[1]))
    ax.set_yticks(np.arange(matrix.shape[0]))
    ax.set_xticklabels(matrix.columns, rotation=xrot,
                       ha="right" if xrot else "center")
    ax.set_yticklabels(matrix.index)
    ax.set_xticks(np.arange(-.5, matrix.shape[1], 1), minor=True)
    ax.set_yticks(np.arange(-.5, matrix.shape[0], 1), minor=True)
    ax.grid(which="minor", color=cell_edge, linewidth=1.1)
    ax.grid(which="major", visible=False)
    ax.tick_params(which="minor", length=0)
    if annot:
        norm = im.norm
        for i in range(matrix.shape[0]):
            for j in range(matrix.shape[1]):
                v = values[i, j]
                if not np.isfinite(v):
                    ax.text(j, i, "нет", ha="center", va="center",
                            fontsize=fontsize - 0.6, color=INK_FAINT,
                            style="italic")
                    continue
                rgba = im.cmap(norm(v))
                lum = 0.299 * rgba[0] + 0.587 * rgba[1] + 0.114 * rgba[2]
                col = annot_color or ("#08101F" if lum > 0.62 else INK)
                ax.text(j, i, fmt.format(v), ha="center", va="center",
                        fontsize=fontsize, color=col, fontweight="medium")
    return im


def pareto_front(frame, x, y, *, minimize_x=True, maximize_y=True):
    """Недоминируемые точки (векторно, без O(n^2) циклов по строкам)."""
    work = frame[[x, y]].apply(pd.to_numeric, errors="coerce")
    ok = work.notna().all(axis=1).to_numpy()
    xs = work[x].to_numpy(dtype=float)
    ys = work[y].to_numpy(dtype=float)
    xs_s = xs if minimize_x else -xs
    ys_s = ys if maximize_y else -ys
    mask = np.zeros(len(frame), dtype=bool)
    idx = np.where(ok)[0]
    order = idx[np.lexsort((-ys_s[idx], xs_s[idx]))]
    best = -np.inf
    for i in order:
        if ys_s[i] > best:
            mask[i] = True
            best = ys_s[i]
    return mask


# ----------------------------------------------------------------- statistics --
def bootstrap_ci(values, *, repeats: int = 2000, seed: int = 42,
                 statistic=np.mean, alpha: float = 0.05):
    """Percentile bootstrap CI одной выборки."""
    v = pd.to_numeric(pd.Series(values), errors="coerce").dropna().to_numpy()
    if v.size == 0:
        return np.nan, np.nan, np.nan, 0
    if v.size == 1:
        return float(v[0]), np.nan, np.nan, 1
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, v.size, size=(repeats, v.size))
    est = statistic(v[draws], axis=1)
    return (float(statistic(v)), float(np.quantile(est, alpha / 2)),
            float(np.quantile(est, 1 - alpha / 2)), int(v.size))


def cluster_bootstrap_ci(frame, value, cluster, *, repeats: int = 2000,
                         seed: int = 42, statistic=np.mean, alpha: float = 0.05):
    """Bootstrap по кластерам (например по изображениям), а не по строкам."""
    work = frame[[value, cluster]].dropna()
    groups = [g[value].to_numpy(dtype=float) for _, g in work.groupby(cluster)]
    if not groups:
        return np.nan, np.nan, np.nan, 0
    rng = np.random.default_rng(seed)
    point = float(statistic(np.concatenate(groups)))
    est = np.empty(repeats)
    n = len(groups)
    for i in range(repeats):
        pick = rng.integers(0, n, n)
        est[i] = statistic(np.concatenate([groups[j] for j in pick]))
    return (point, float(np.quantile(est, alpha / 2)),
            float(np.quantile(est, 1 - alpha / 2)), n)


def cluster_bootstrap_mean(frame, value, cluster, *, repeats: int = 2000,
                           seed: int = 42, alpha: float = 0.05):
    """Векторный кластерный bootstrap среднего: ресэмплинг сумм и размеров кластеров."""
    work = frame[[value, cluster]].dropna()
    if work.empty:
        return np.nan, np.nan, np.nan, 0
    grouped = work.groupby(cluster)[value].agg(["sum", "count"])
    sums = grouped["sum"].to_numpy(dtype=float)
    counts = grouped["count"].to_numpy(dtype=float)
    n = sums.size
    point = float(sums.sum() / counts.sum())
    if n < 2:
        return point, np.nan, np.nan, n
    rng = np.random.default_rng(seed)
    pick = rng.integers(0, n, size=(repeats, n))
    est = sums[pick].sum(axis=1) / counts[pick].sum(axis=1)
    return (point, float(np.quantile(est, alpha / 2)),
            float(np.quantile(est, 1 - alpha / 2)), n)


def cluster_bootstrap_table(frame, group, value, cluster, *, repeats: int = 2000,
                            seed: int = 42) -> pd.DataFrame:
    """Кластерный bootstrap среднего для каждой группы (например для 45 методов)."""
    rows = []
    for key, part in frame.groupby(group, dropna=False, observed=True):
        mean, lo, hi, clusters = cluster_bootstrap_mean(
            part, value, cluster, repeats=repeats, seed=seed)
        rows.append({group: key, "mean": mean, "ci_low": lo, "ci_high": hi,
                     "clusters": clusters, "n": int(part[value].notna().sum())})
    return pd.DataFrame(rows)


def bootstrap_groups(frame, group, value, *, repeats: int = 1500, seed: int = 42,
                     statistic=np.mean):
    rows = []
    for key, part in frame.groupby(group, dropna=False, observed=True):
        m, lo, hi, n = bootstrap_ci(part[value], repeats=repeats, seed=seed,
                                    statistic=statistic)
        rows.append({group: key, "mean": m, "ci_low": lo, "ci_high": hi, "n": n})
    return pd.DataFrame(rows)


def cliffs_delta(a, b) -> float:
    """Непараметрический размер эффекта Cliff's delta через ранги (O(n log n))."""
    a = pd.to_numeric(pd.Series(a), errors="coerce").dropna().to_numpy()
    b = pd.to_numeric(pd.Series(b), errors="coerce").dropna().to_numpy()
    if a.size == 0 or b.size == 0:
        return np.nan
    from scipy.stats import rankdata
    pooled = np.concatenate([a, b])
    ranks = rankdata(pooled)
    r1 = ranks[:a.size].sum()
    u1 = r1 - a.size * (a.size + 1) / 2
    return float(2 * u1 / (a.size * b.size) - 1)


def rank_biserial(diff) -> float:
    """Матч-парный размер эффекта для Wilcoxon signed-rank."""
    d = pd.to_numeric(pd.Series(diff), errors="coerce").dropna().to_numpy()
    d = d[d != 0]
    if d.size == 0:
        return np.nan
    from scipy.stats import rankdata
    r = rankdata(np.abs(d))
    total = r.sum()
    return float((r[d > 0].sum() - r[d < 0].sum()) / total)


def bh_fdr(pvalues):
    """Benjamini–Hochberg скорректированные p-значения."""
    p = np.asarray(pd.to_numeric(pd.Series(pvalues), errors="coerce"),
                   dtype=float)
    out = np.full(p.shape, np.nan)
    ok = np.isfinite(p)
    if ok.sum() == 0:
        return out
    vals = p[ok]
    n = vals.size
    order = np.argsort(vals)
    ranked = vals[order] * n / (np.arange(n) + 1)
    adj = np.minimum.accumulate(ranked[::-1])[::-1]
    res = np.empty(n)
    res[order] = np.clip(adj, 0, 1)
    out[ok] = res
    return out


def smooth_band(frame, x, y, *, bins: int = 26, window: int = 3,
                spread: str = "sd2", quantiles=(0.1, 0.9)):
    """Биннированное среднее с полосой разброса (±2σ или межквантильной)."""
    work = frame[[x, y]].apply(pd.to_numeric, errors="coerce").dropna()
    if work.empty:
        return pd.DataFrame(columns=["x", "mean", "low", "high", "n"])
    edges = np.unique(np.nanquantile(work[x], np.linspace(0, 1, bins + 1)))
    if edges.size < 3:
        edges = np.linspace(work[x].min(), work[x].max(), 4)
    work = work.assign(_bin=pd.cut(work[x], edges, include_lowest=True,
                                   duplicates="drop"))
    agg = work.groupby("_bin", observed=True).agg(
        x=(x, "mean"), mean=(y, "mean"), sd=(y, "std"), n=(y, "size"),
        qlo=(y, lambda s: s.quantile(quantiles[0])),
        qhi=(y, lambda s: s.quantile(quantiles[1]))).reset_index(drop=True)
    agg["mean"] = agg["mean"].rolling(window, center=True, min_periods=1).mean()
    agg["sd"] = agg["sd"].fillna(0).rolling(window, center=True,
                                            min_periods=1).mean()
    if spread == "sd2":
        agg["low"] = agg["mean"] - 2 * agg["sd"]
        agg["high"] = agg["mean"] + 2 * agg["sd"]
    else:
        agg["low"] = agg["qlo"].rolling(window, center=True, min_periods=1).mean()
        agg["high"] = agg["qhi"].rolling(window, center=True, min_periods=1).mean()
    return agg[["x", "mean", "low", "high", "n", "sd"]]


def kde_grid(x, y, *, gridsize: int = 260, bw: float | None = None,
             max_points: int = 60000, seed: int = 42):
    """Плотность 2D на регулярной сетке (для контуров поверх точек)."""
    from scipy.stats import gaussian_kde
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    if x.size < 30:
        return None
    rng = np.random.default_rng(seed)
    if x.size > max_points:
        pick = rng.choice(x.size, max_points, replace=False)
        xs, ys = x[pick], y[pick]
    else:
        xs, ys = x, y
    kde = gaussian_kde(np.vstack([xs, ys]), bw_method=bw)
    xi = np.linspace(x.min(), x.max(), gridsize)
    yi = np.linspace(y.min(), y.max(), gridsize)
    XX, YY = np.meshgrid(xi, yi)
    ZZ = kde(np.vstack([XX.ravel(), YY.ravel()])).reshape(XX.shape)
    return XX, YY, ZZ


# ------------------------------------------------------------------- naming ---
FAMILY_LABEL = {"itc": "ITC", "cpd": "CPD", "tucker": "Tucker",
                "tensor_train": "Tensor Train", "svd": "SVD", "pca": "PCA",
                "zca": "ZCA"}

DEGRADATION_LABEL = {
    "gaussian_noise": "Гауссов шум",
    "gaussian_blur": "Гауссово размытие",
    "random_missing": "Случайные пропуски",
    "random_blackout": "Случайные чёрные пиксели",
    "grid_missing": "Сетчатые пропуски",
    "diagonal_missing": "Диагональные пропуски",
    "channel_blackout": "Отключение каналов",
    "occlusion_rect": "Прямоугольная окклюзия",
    "gaussian_blur_itc_mask": "Размытие + ITC-маска",
}

MASK_MODE_LABEL = {
    "no_mask": "без маски",
    "direct_mask": "точная маска",
    "expanded_mask": "расширенная",
    "partial_mask": "частичная",
    "under_mask": "недооценённая",
    "boundary_band": "граничная полоса",
}

MASK_SOURCE_LABEL = {
    "oracle_abs_error": "oracle (|ошибка|)",
    "rect_truth": "oracle (прямоугольник)",
    "image_only_proxy_v2": "proxy v2 (по изображению)",
    "proxy_thin_edges": "proxy (тонкие края)",
}

INIT_LABEL = {"channel_mean": "среднее канала",
              "local_interpolation": "локальная интерполяция",
              "degraded": "повреждённое изображение"}


def family_of(method: str) -> str:
    value = str(method).lower()
    for family in ("itc", "tensor_train", "tucker", "cpd", "svd", "pca", "zca"):
        if value.startswith(family):
            return family
    return value.split("_")[0]


def label_degradation(name) -> str:
    return DEGRADATION_LABEL.get(str(name), str(name))


def label_family(name) -> str:
    return FAMILY_LABEL.get(str(name), str(name).upper())


def label_mask_mode(name) -> str:
    return MASK_MODE_LABEL.get(str(name), str(name))


def label_mask_source(name) -> str:
    return MASK_SOURCE_LABEL.get(str(name), str(name))


def ru_int(value) -> str:
    """Разряды тонкими пробелами: 220 200."""
    try:
        return f"{int(round(float(value))):,}".replace(",", "\u2009")
    except Exception:
        return str(value)


def short_model(name: str) -> str:
    return str(name).replace("_", " ").replace("convnext", "ConvNeXt") \
        .replace("efficientnet", "EffNet").replace("resnet", "ResNet") \
        .replace("mobilenet", "MobileNet").replace("regnet", "RegNet") \
        .replace("densenet", "DenseNet").replace("swin", "Swin") \
        .replace("vit ", "ViT ").replace("maxvit", "MaxViT")


# ------------------------------------------------------------------ registry ---
@dataclass
class FigureRegistry:
    """Реестр фигур: пути, n, агрегация, неопределённость, источник."""

    figures_dir: Path
    tables_dir: Path
    dpi: int = 300
    # Потолок растра: очень высокие фигуры-галереи при большом dpi выходят за
    # пределы памяти рендерера, поэтому для них dpi понижается автоматически.
    max_megapixels: float = 180.0
    rows: list[dict] = field(default_factory=list)

    def __post_init__(self):
        self.png_dir = self.figures_dir / "png"
        self.pdf_dir = self.figures_dir / "pdf"
        for d in (self.png_dir, self.pdf_dir, self.tables_dir):
            d.mkdir(parents=True, exist_ok=True)

    def save(self, fig, fig_id: str, title: str, *, source: str, n_obs=None,
             aggregation: str = "не применялась", uncertainty: str = "нет",
             comparability: str = "within-study", takeaway: str = "",
             dpi: int | None = None, pdf: bool = True) -> Path:
        dpi = self.dpi if dpi is None else dpi
        dpi = self._fit_dpi(fig, dpi)
        stem = fig_id.lower().replace(" ", "_")
        png = self.png_dir / f"{stem}.png"
        fig.savefig(png, dpi=dpi, facecolor=VOID, bbox_inches="tight",
                    pad_inches=0.28)
        pdf_path = None
        if pdf:
            pdf_path = self.pdf_dir / f"{stem}.pdf"
            # dpi управляет разрешением растеризованных слоёв внутри вектора.
            fig.savefig(pdf_path, dpi=dpi, facecolor=VOID, bbox_inches="tight",
                        pad_inches=0.28)
        self.rows.append({
            "figure_id": fig_id, "title": title, "source": source,
            "n_obs": n_obs, "aggregation": aggregation,
            "uncertainty": uncertainty, "comparability": comparability,
            "takeaway": takeaway,
            "png": str(png), "pdf": str(pdf_path) if pdf_path else "",
        })
        return png

    def _fit_dpi(self, fig, dpi: int) -> int:
        width, height = fig.get_size_inches()
        limit = (self.max_megapixels * 1e6 / (width * height)) ** 0.5
        if dpi <= limit:
            return dpi
        capped = int(limit // 10 * 10)
        print(f"  dpi понижен {dpi} → {capped}: кадр {width:.0f}×{height:.0f} "
              f"дюймов упёрся бы в {width * height * dpi ** 2 / 1e6:.0f} Мпикс")
        return capped

    def table(self, frame: pd.DataFrame, name: str) -> Path:
        path = self.tables_dir / (name if name.endswith(".csv") else f"{name}.csv")
        frame.to_csv(path, index=False)
        return path

    def manifest(self) -> pd.DataFrame:
        return pd.DataFrame(self.rows)


# ------------------------------------------------------------------- caption ---
def caption(what: str, how: str, takeaway: str, *, n: str = "",
            uncertainty: str = "") -> None:
    """Тёмная карточка-подпись: что показано, как читать, что из этого следует."""
    from IPython.display import HTML, display
    meta = ""
    if n or uncertainty:
        bits = [b for b in (f"n = {n}" if n else "",
                            f"неопределённость: {uncertainty}" if uncertainty else "")
                if b]
        meta = (f"<div style='margin-top:9px;font-family:DejaVu Sans Mono,monospace;"
                f"font-size:11px;color:{INK_FAINT};letter-spacing:.02em'>"
                + "&nbsp;&nbsp;·&nbsp;&nbsp;".join(bits) + "</div>")
    html = f"""
<div style="background:linear-gradient(135deg,{PANEL} 0%,{PANEL_HI} 100%);
            border:1px solid {EDGE};border-left:4px solid {MINT};
            border-radius:10px;padding:14px 18px;margin:4px 0 26px 0;
            font-family:Lato,DejaVu Sans,sans-serif;font-size:13.5px;
            line-height:1.62;color:{INK};box-shadow:0 6px 22px rgba(0,0,0,.35)">
  <div style="margin-bottom:5px"><b style="color:{MINT};letter-spacing:.06em;
      font-size:11.5px">ЧТО ПОКАЗАНО</b><br>{what}</div>
  <div style="margin-bottom:5px"><b style="color:{CYAN};letter-spacing:.06em;
      font-size:11.5px">КАК ЧИТАТЬ</b><br>{how}</div>
  <div><b style="color:{GOLD};letter-spacing:.06em;font-size:11.5px">ВЫВОД</b>
      <br>{takeaway}</div>{meta}
</div>"""
    display(HTML(html))


def banner(kicker: str, title: str, lead: str = "", *, accent: str = MINT) -> None:
    """Кинематографичный разделитель части исследования внутри ноутбука."""
    from IPython.display import HTML, display
    html = f"""
<div style="position:relative;overflow:hidden;border-radius:14px;
            margin:34px 0 20px 0;padding:30px 34px 26px 34px;
            background:radial-gradient(1200px 260px at 4% 0%,{accent}22 0%,
                       {PANEL} 42%,{VOID} 100%);
            border:1px solid {EDGE};box-shadow:0 12px 40px rgba(0,0,0,.45)">
  <div style="font-family:DejaVu Sans Mono,monospace;font-size:11px;
              letter-spacing:.34em;color:{accent};margin-bottom:10px">
      {kicker.upper()}</div>
  <div style="font-family:Lato,DejaVu Sans,sans-serif;font-size:31px;
              font-weight:900;color:{INK};line-height:1.16;
              text-shadow:0 2px 18px {accent}55">{title}</div>
  {f'<div style="font-family:Lato,DejaVu Sans,sans-serif;font-size:14px;color:{INK_DIM};margin-top:12px;max-width:1080px;line-height:1.6">{lead}</div>' if lead else ''}
</div>"""
    display(HTML(html))


def note(text: str, *, kind: str = "info") -> None:
    """Компактная плашка: ограничение, предупреждение или подтверждение."""
    from IPython.display import HTML, display
    palette = {"info": CYAN, "warn": WARN, "limit": CORAL, "ok": LIME}
    icon = {"info": "i", "warn": "!", "limit": "△", "ok": "✓"}
    color = palette.get(kind, CYAN)
    html = f"""
<div style="display:flex;gap:12px;align-items:flex-start;background:{PANEL};
            border:1px solid {EDGE};border-left:3px solid {color};
            border-radius:8px;padding:11px 15px;margin:6px 0 18px 0;
            font-family:Lato,DejaVu Sans,sans-serif;font-size:13px;
            line-height:1.58;color:{INK}">
  <div style="flex:0 0 20px;height:20px;border-radius:50%;background:{color}22;
              border:1px solid {color};color:{color};font-weight:900;
              text-align:center;font-size:12px;line-height:19px">{icon.get(kind,'i')}</div>
  <div>{text}</div>
</div>"""
    display(HTML(html))


def styled_table(frame: pd.DataFrame, *, caption_text: str = "",
                 fmt: dict | None = None, max_rows: int = 40,
                 highlight: str | None = None, ascending: bool = False):
    """Тёмная стилизованная таблица для вывода в ноутбуке."""
    view = frame.head(max_rows).copy()
    styler = (view.style
              .format(fmt or {}, na_rep="—")
              .set_table_styles([
                  {"selector": "", "props": [
                      ("border-collapse", "separate"),
                      ("border-spacing", "0"),
                      ("font-family", "Lato,DejaVu Sans,sans-serif"),
                      ("font-size", "12.5px"),
                      ("background", PANEL),
                      ("border", f"1px solid {EDGE}"),
                      ("border-radius", "10px"),
                      ("overflow", "hidden")]},
                  {"selector": "th", "props": [
                      ("background", PANEL_HI), ("color", MINT),
                      ("font-weight", "700"), ("text-align", "left"),
                      ("padding", "9px 13px"), ("letter-spacing", ".04em"),
                      ("font-size", "11.5px"),
                      ("border-bottom", f"1px solid {EDGE}")]},
                  {"selector": "td", "props": [
                      ("color", INK), ("padding", "7px 13px"),
                      ("border-bottom", f"1px solid {GRID}")]},
                  {"selector": "tr:hover td", "props": [
                      ("background", PANEL_HI)]},
                  {"selector": "caption", "props": [
                      ("caption-side", "top"), ("color", INK_DIM),
                      ("font-size", "12px"), ("padding", "0 0 8px 2px"),
                      ("text-align", "left")]},
              ]))
    if caption_text:
        styler = styler.set_caption(caption_text)
    if highlight and highlight in view.columns:
        styler = styler.background_gradient(
            subset=[highlight], cmap=AURORA if ascending else DEEPSPACE)
    return styler


# ------------------------------------------------------------------- caching ---
def cached_frame(path: Path, builder, *, sources: list[Path] | None = None,
                 verbose: bool = True) -> pd.DataFrame:
    """Кэш parquet: пересобирается, если исходники новее кэша."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fresh = path.exists()
    if fresh and sources:
        newest = max(Path(s).stat().st_mtime for s in sources if Path(s).exists())
        fresh = path.stat().st_mtime >= newest
    if fresh:
        if verbose:
            print(f"  кэш: {path.name}")
        return pd.read_parquet(path)
    frame = builder()
    frame.to_parquet(path, index=False)
    if verbose:
        print(f"  собрано и закэшировано: {path.name} ({len(frame):,} строк)")
    return frame


def timed(label: str, builder):
    """Выполняет тяжёлый шаг и печатает, сколько он занял."""
    started = time.perf_counter()
    result = builder()
    print(f"  {label}: {time.perf_counter() - started:.1f} с")
    return result


def plotly_dark_layout(title: str = "", *, height: int = 640,
                       subtitle: str = "") -> dict:
    """Единый тёмный layout для интерактивных фигур."""
    return dict(
        template="plotly_dark",
        title=dict(text=(f"<b>{title}</b>" +
                         (f"<br><span style='font-size:12px;color:{INK_DIM}'>"
                          f"{subtitle}</span>" if subtitle else "")),
                   x=0.012, xanchor="left", font=dict(size=21, color=INK)),
        paper_bgcolor=VOID, plot_bgcolor=PANEL, height=height,
        font=dict(family="Lato, DejaVu Sans, sans-serif", size=12.5, color=INK),
        margin=dict(l=70, r=40, t=90 if not subtitle else 108, b=60),
        legend=dict(bgcolor=PANEL_HI, bordercolor=EDGE, borderwidth=1),
        hoverlabel=dict(bgcolor=PANEL_HI, bordercolor=MINT,
                        font=dict(color=INK, size=12)),
    )


__all__ = [name for name in dir() if not name.startswith("_")]
