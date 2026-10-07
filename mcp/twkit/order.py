"""Child order inside `<datasource>`: Tableau demands a strict sequence."""
from __future__ import annotations

DATASOURCE_ORDER = (
    "repository-location",
    "connection",
    "utility-dimensions",
    "dimension",
    "overridable-settings",
    "aliases",
    "column",
    "column-instance",
    "group",
    "mapped-images",
    "drill-paths",
    "unlinked-server-hierarchies",
    "folders-common",
    "folders-parameters",
    "actions",
    "calculated-members",
    "extract",
    "layout",
    "style",
    "semantic-values",
    "date-options",
    "default-date-format",
    "default-sorts",
    "field-sort-info",
    "datasource-dependencies",
    "explainability",
    "filter",
    "object-graph",
)

_RANK = {tag: i for i, tag in enumerate(DATASOURCE_ORDER)}
_TAIL = len(DATASOURCE_ORDER)

VIEW_ORDER = (
    "datasources",
    "mapsources",
    "datasource-dependencies",
    "natural-sort",
    "sort",
    "filter",
    "manual-sort",
    "computed-sort",
    "hide-sort-controls",
    "shelf-sorts",
    "single-value-per-nest-shelf-sorts",
    "slices",
    "aggregation",
)
_VIEW_RANK = {tag: i for i, tag in enumerate(VIEW_ORDER)}


def normalize_view(view) -> bool:
    """Reorder the children of one <view> into the order Tableau accepts."""
    kids = [c for c in view]
    if not kids:
        return False
    order = sorted(range(len(kids)),
                   key=lambda i: (_VIEW_RANK.get(kids[i].tag, len(VIEW_ORDER)), i))
    if order == list(range(len(kids))):
        return False
    for i in order:
        view.append(kids[i])
    return True


def normalize_views(root) -> int:
    """Normalize child order in every <view> of the workbook."""
    return sum(1 for v in root.iter("view") if normalize_view(v))


def normalize_datasource(ds) -> bool:
    """Reorder the children of one <datasource> into canonical order."""
    kids = [c for c in ds]
    if not kids:
        return False
    tagged = [c for c in kids if isinstance(getattr(c, "tag", None), str)]
    if len(tagged) < 2:
        return False

    ordered = sorted(tagged, key=lambda c: _RANK.get(c.tag, _TAIL))
    if [id(c) for c in ordered] == [id(c) for c in tagged]:
        return False

    for c in tagged:
        ds.remove(c)
    for c in ordered:
        ds.append(c)
    return True


def normalize_workbook(root) -> int:
    """Normalize child order in every datasource of the workbook."""
    return sum(1 for ds in root.iter("datasource") if normalize_datasource(ds))
