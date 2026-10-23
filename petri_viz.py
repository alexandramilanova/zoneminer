from __future__ import annotations

import html

import streamlit.components.v1 as components
from graphviz import Digraph


# -----------------------------
# Graphviz (PM4Py-correct-ish) + Interactive SVG (zoom/pan)
# -----------------------------
def build_petri_graphviz_with_place_labels(
    net,
    im=None,
    fm=None,
    rankdir: str = "LR",
    font_size: str = "10",
    bgcolor: str = "white",
    show_transition_ids: bool = False,
    highlighted_places: dict[str, dict[str, str]] | None = None,
):
    """
    Build a Graphviz Digraph where:
      - Places are circles and ALWAYS show their names (inside the node label).
      - Transitions are boxes; silent transitions are black boxes.
      - Optional marking info is shown as plain text suffix to avoid Graphviz HTML label issues.

    Note:
      We avoid Graphviz HTML-like labels entirely (they caused your SVG 'invalid token' error).
    """
    im = im or {}
    fm = fm or {}

    # Graphviz object
    viz = Digraph(getattr(net, "name", None) or "petri_net", engine="dot")
    viz.graph_attr.update(
        {
            "rankdir": rankdir,
            "bgcolor": bgcolor,
            "splines": "true",
            "overlap": "false",
            "nodesep": "0.35",
            "ranksep": "0.35",
        }
    )

    # -------- transitions --------
    viz.attr("node", shape="box", fontsize=str(font_size), style="rounded,filled", fillcolor="#f3f4f6")

    def _t_text(t) -> str:
        human = str(t.label) if getattr(t, "label", None) is not None else ""
        internal = str(getattr(t, "name", "<?>"))
        if show_transition_ids and human:
            return f"{human}\\n({internal})"
        return human if human else internal

    for t in net.transitions:
        tid = str(id(t))
        if getattr(t, "label", None) is None:
            # silent transition
            viz.node(tid, label="", style="filled", fillcolor="black", color="black", width="0.20", height="0.20")
        else:
            viz.node(tid, label=_t_text(t))

    # -------- places --------
    # Make labels readable for zone selection: keep place name inside the node.
    viz.attr("node", shape="circle", fontsize=str(font_size), style="solid", width="1.0")

    im_places = set(im.keys()) if im else set()
    fm_places = set(fm.keys()) if fm else set()
    highlighted_places = highlighted_places or {}

    for p in net.places:
        pid = str(id(p))
        pname = html.escape(str(p.name))  # safety for weird chars

        # show marking in plain text to avoid HTML label rendering issues
        suffix = ""
        if p in im_places:
            try:
                cnt = int(im[p])
            except Exception:
                cnt = 1
            suffix = f" [im:{cnt}]"
        elif p in fm_places:
            suffix = " [fm]"

        style_kwargs = highlighted_places.get(str(p.name), {})
        if style_kwargs:
            viz.node(
                pid,
                label=pname + suffix,
                style=style_kwargs.get("style", "filled"),
                fillcolor=style_kwargs.get("fillcolor", "#fef3c7"),
                color=style_kwargs.get("color", "#d97706"),
                penwidth=style_kwargs.get("penwidth", "2.0"),
            )
        else:
            viz.node(pid, label=pname + suffix)

    # -------- arcs --------
    viz.attr("edge", arrowsize="0.7")
    for a in net.arcs:
        viz.edge(str(id(a.source)), str(id(a.target)))

    viz.format = "svg"
    return viz


def show_graphviz_interactive(gviz, height: int = 420, element_id: str = "graphviz_container"):
    """
    Render a Graphviz Digraph as an interactive SVG (zoom/pan) in Streamlit.
    - Smaller, nicer sizing by default (height=420).
    - Robust selector so we pan/zoom the correct SVG element.
    """
    try:
        svg_bytes = gviz.pipe(format="svg")
        svg = svg_bytes.decode("utf-8", errors="ignore")
    except Exception as e:
        raise RuntimeError(f"SVG rendering failed: {e}")

    # IMPORTANT: scope selectors to our container so we don't grab the wrong SVG on the page.
    html_block = f"""
    <div id="{element_id}" style="
        width: 100%;
        height: {height}px;
        border: 1px solid #e5e7eb;
        border-radius: 10px;
        overflow: hidden;
        background: white;
    ">
      {svg}
    </div>

    <script src="https://unpkg.com/svg-pan-zoom@3.6.1/dist/svg-pan-zoom.min.js"></script>
    <script>
      (function() {{
        const container = document.getElementById("{element_id}");
        if (!container) return;

        const svg = container.querySelector("svg");
        if (!svg) return;

        svg.setAttribute("width", "100%");
        svg.setAttribute("height", "100%");
        svg.style.display = "block";

        // Some Graphviz SVGs include width/height in pt; keep viewBox-based scaling if present.
        // svg-pan-zoom handles it fine, but we ensure the container drives size.

        svgPanZoom(svg, {{
          zoomEnabled: true,
          controlIconsEnabled: true,
          fit: true,
          center: true,
          minZoom: 0.2,
          maxZoom: 20
        }});
      }})();
    </script>
    """
    components.html(html_block, height=height, scrolling=False)


def show_petri_graphviz_interactive(gviz, height: int = 420):
    show_graphviz_interactive(gviz, height=height, element_id="pn_container")
