import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mcp"))

from lxml import etree

from twkit import edit as ED


def _root(n=17):
    zones = "".join(
        f"<zone id='{i + 10}' type-v2='empty' fixed-size='10' is-fixed='true'/>"
        for i in range(n))
    return etree.fromstring(f"""
<workbook>
  <dashboards>
    <dashboard name='Pg'>
      <size sizing-mode='range' minwidth='800' maxwidth='1600'/>
      <zones><zone id='1' type-v2='layout-flow' param='vert'
                   x='0' y='0' w='100000' h='100000'>{zones}</zone></zones>
    </dashboard>
  </dashboards>
  <windows>
    <window class='dashboard' name='Pg'><viewpoints/></window>
  </windows>
</workbook>""")


HEIGHTS = [44, 60, 10, 58, 12, 300, 12, 300, 12, 70, 165, 12, 300, 12, 760, 12, 80]


def _stack(root, size=None):
    items = [{"kind": "keep", "id": str(i + 10), "h": h} for i, h in enumerate(HEIGHTS)]
    return ED.stack_page(root, "Pg", items, size)


def _zones(root):
    outer = root.find(".//zones/zone")
    return outer.findall("zone")


def test_heights_sum_to_canvas():
    root = _root(len(HEIGHTS))
    _stack(root)
    zs = _zones(root)
    assert sum(int(z.get("h")) for z in zs) == 100000
    last = zs[-1]
    assert int(last.get("y")) + int(last.get("h")) == 100000


def test_zones_contiguous_without_gaps_or_overlaps():
    root = _root(len(HEIGHTS))
    _stack(root)
    y = 0
    for z in _zones(root):
        assert int(z.get("y")) == y
        y += int(z.get("h"))


def test_block_order_kept():
    root = _root(len(HEIGHTS))
    _stack(root)
    assert [z.get("id") for z in _zones(root)] == [str(i + 10) for i in range(len(HEIGHTS))]


def test_canvas_size_rewritten_whole():
    root = _root(len(HEIGHTS))
    out = _stack(root, {"minwidth": 1500, "maxwidth": 2400,
                        "minheight": 2240, "maxheight": 4400})
    assert out["height_px"] == sum(HEIGHTS)
    size = root.find(".//dashboard/size")
    assert size.get("minheight") == "2240" and size.get("maxwidth") == "2400"
