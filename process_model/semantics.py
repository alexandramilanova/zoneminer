"""Validation for the ordinary weighted place/transition nets replay supports.

No reset/inhibitor/timed/colored semantics are approximated by ordinary arcs.
One explicit initial marking and one exact final marking are required. A
finite complete alignment must exist; boundedness/soundness is not assumed or
proved here. Duplicate visible labels are legal, node identities must be unique.
"""

from numbers import Integral
import xml.etree.ElementTree as ET

from pm4py.objects.petri_net.obj import PetriNet


def validate_petri_net(net, im=None, fm=None):
    if type(net) is not PetriNet:
        raise ValueError("Unsupported Petri net: only ordinary weighted place/transition nets are supported")
    for kind, nodes, node_type in (
        ("place", net.places, PetriNet.Place),
        ("transition", net.transitions, PetriNet.Transition),
    ):
        names = [node.name for node in nodes]
        if any(type(node) is not node_type for node in nodes):
            raise ValueError(f"Unsupported {kind} semantics: only ordinary Petri-net nodes are supported")
        if any(not isinstance(name, str) or not name or name == ">>" for name in names):
            raise ValueError(f"Each {kind} must have a non-empty string identity other than '>>'")
        if len(names) != len(set(names)):
            raise ValueError(f"Duplicate {kind} identities: names must be unique")
    if {place.name for place in net.places} & {transition.name for transition in net.transitions}:
        raise ValueError("Place and transition identities must be distinct across the net")
    for transition in net.transitions:
        if any(key in transition.properties for key in ("guard", "readVariable", "writeVariable", "stochastic_distribution")):
            raise ValueError("Unsupported transition semantics: guards, data variables, and stochastic timing are not supported")
        if transition.label is not None and (
            not isinstance(transition.label, str) or not transition.label or transition.label == ">>"
        ):
            raise ValueError("Transition labels must be non-empty strings other than '>>', or None for silent transitions")
    if net.properties.get("variables"):
        raise ValueError("Data Petri nets are not supported")
    endpoints = set()
    for arc in net.arcs:
        if type(arc) is not PetriNet.Arc or arc.properties.get("arctype") not in (None, "normal"):
            raise ValueError("Unsupported arc semantics: reset/inhibitor arcs are not supported")
        if not (
            (arc.source in net.places and arc.target in net.transitions)
            or (arc.source in net.transitions and arc.target in net.places)
        ):
            raise ValueError("Every arc must connect an existing place and transition")
        if isinstance(arc.weight, bool) or not isinstance(arc.weight, Integral) or arc.weight < 1:
            raise ValueError("Arc weights must be positive integers")
        endpoint = (arc.source, arc.target)
        if endpoint in endpoints:
            raise ValueError("Parallel arcs between the same nodes are unsupported; combine them into one weighted arc")
        endpoints.add(endpoint)
    for kind, marking in (("initial", im), ("final", fm)):
        if marking is None:
            continue
        for place, count in marking.items():
            if place not in net.places:
                raise ValueError(f"The {kind} marking refers to a place outside the net")
            if isinstance(count, bool) or not isinstance(count, Integral) or count < 0:
                raise ValueError(f"The {kind} marking must contain non-negative integer token counts")


def validate_pnml(path):
    """Reject PNML constructs that pm4py would merge, guess, or discard."""
    root = ET.parse(path).getroot()
    tag = lambda element: element.tag.rsplit("}", 1)[-1]
    if tag(root) != "pnml":
        raise ValueError("PNML requires a pnml document root")
    nets = [element for element in root.iter() if tag(element) == "net"]
    if len(nets) != 1:
        raise ValueError("PNML must contain exactly one ordinary P/T net")
    net = nets[0]
    if net.get("type") not in (
        None, "http://www.pnml.org/version-2009/grammar/pnmlcoremodel",
        "http://www.pnml.org/version-2009/grammar/ptnet",
    ):
        raise ValueError(f"Unsupported PNML net type: {net.get('type')!r}; only ordinary P/T nets are supported")
    pages = [element for element in net.iter() if tag(element) == "page"]
    if len(pages) > 1:
        raise ValueError("Multi-page/hierarchical PNML is not supported; supply one flat page")
    if pages and pages[0] not in list(net):
        raise ValueError("Nested PNML pages are not supported")
    body = pages[0] if pages else net
    node_kinds = {
        element.get("id"): tag(element) for element in body
        if tag(element) in ("place", "transition")
    }
    for element in net.iter():
        kind = tag(element)
        if kind in ("place", "transition", "arc") and element.get("id") is not None and element not in list(body):
            raise ValueError("PNML nodes and arcs must be direct children of the single flat page")
        if kind == "arc":
            source, target = element.get("source"), element.get("target")
            if (node_kinds.get(source), node_kinds.get(target)) not in (("place", "transition"), ("transition", "place")):
                raise ValueError("PNML arcs must connect existing place and transition IDs")
        if kind in ("place", "transition") and element in list(body) and not element.get("id"):
            raise ValueError("PNML nodes require non-empty IDs")
        if kind == "place" and element.get("idref") is not None and node_kinds.get(element.get("idref")) != "place":
            raise ValueError("PNML final marking refers to an unknown place ID")
    names = []
    finals = []
    for element in net.iter():
        kind = tag(element)
        if kind not in {
            "net", "name", "text", "page", "place", "transition", "arc",
            "initialMarking", "finalmarkings", "marking", "inscription",
            "graphics", "position", "dimension", "offset", "fill", "line",
            "font", "toolspecific",
        }:
            raise ValueError(f"Unsupported PNML construct {kind!r}; supply a flat ordinary P/T net")
        if kind in ("place", "transition") and element.get("id") is not None:
            names.append(element.get("id"))
        if element.get("guard") is not None:
            raise ValueError(f"Unsupported PNML construct {kind!r}: only ordinary uncolored P/T semantics are supported")
        if kind == "toolspecific" and element.get("tool") != "ProM":
            raise ValueError("Unsupported PNML tool extension; only ProM visibility annotations are supported")
        if kind == "finalmarkings":
            finals.extend(list(element))
        if kind in ("initialMarking", "marking"):
            for text in element.iter():
                if tag(text) == "text" and text.text is not None:
                    try:
                        count = int(text.text)
                    except ValueError:
                        raise ValueError("PNML markings must use non-negative integer counts") from None
                    if count < 0:
                        raise ValueError("PNML markings must use non-negative integer counts")
    if len(names) != len(set(names)):
        raise ValueError("PNML node identities must be unique")
    if len(finals) != 1:
        raise ValueError("PNML must specify exactly one final marking; missing/alternative final markings are not inferred or merged")
