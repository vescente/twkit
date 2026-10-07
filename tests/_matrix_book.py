"""A small CSV-backed workbook with one sheet of each common kind, for tool-against-frame tests."""
import csv
import datetime as dt
import os

COUNTRIES = ["Germany", "France", "Spain", "Italy", "Poland", "Austria"]
PRODUCTS = ["Casino", "Sport", "Poker"]
FIELDS = (
    [{"name": n, "datatype": "string", "role": "dimension", "field_type": "nominal"}
     for n in ("country", "product")]
    + [{"name": "date", "datatype": "date", "role": "dimension", "field_type": "ordinal"}]
    + [{"name": n, "datatype": "real", "role": "measure", "field_type": "quantitative"}
       for n in ("sales", "cost", "orders")]
)
SHEETS = ("Table", "Bars", "Chosen", "Trend", "KPI")
OFF_PAGE = ("Palette",)


def write_csv(path: str, scale: float = 1.0) -> str:
    day0 = dt.date(2026, 1, 1)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([x["name"] for x in FIELDS])
        for d in range(0, 120, 3):
            for i, c in enumerate(COUNTRIES):
                for j, p in enumerate(PRODUCTS):
                    sales = (1000 + 370 * i + 150 * j + 11 * d) * scale
                    w.writerow([c, p, (day0 + dt.timedelta(days=d)).isoformat(), sales,
                                round(sales * (0.55 + 0.05 * j), 2), 10 + i + j])
    return path


def build(folder: str) -> str:
    """Write the CSV and the workbook into `folder`; returns the .twbx path."""
    from twkit.book import Book
    data = write_csv(os.path.join(folder, "sales.csv"))
    write_csv(os.path.join(folder, "sales_doubled.csv"), scale=2.0)
    ed = Book()
    ed.set_csv_connection(os.path.abspath(data), fields=[dict(f) for f in FIELDS])
    ed.add_calculated_field("Margin", "SUM([sales]) - SUM([cost])", datatype="real")
    ed.add_parameter("Metric", datatype="string", default_value="Sales", domain_type="list",
                     allowed_values=["Sales", "Cost"])
    ed.add_calculated_field("Chosen Value", "CASE [Parameters].[Metric] WHEN 'Sales' THEN SUM([sales]) "
                            "WHEN 'Cost' THEN SUM([cost]) END", datatype="real")
    for name in SHEETS + OFF_PAGE:
        ed.add_worksheet(name)
    ed.configure_chart("Table", mark_type="Text", rows=["country"],
                       measure_values=["SUM(sales)", "SUM(cost)", "Margin"])
    ed.configure_chart("Bars", mark_type="Bar", rows=["country"], columns=["SUM(sales)"])
    ed.configure_chart("Chosen", mark_type="Bar", rows=["product"], columns=["Chosen Value"])
    ed.configure_chart("Trend", mark_type="Line", columns=["MONTH(date)"], rows=["SUM(sales)"])
    ed.configure_chart("KPI", mark_type="Text", label="SUM(sales)")
    ed.configure_chart("Palette", mark_type="Text", rows=["product"], measure_values=["SUM(sales)", "SUM(cost)"])
    layout = {"type": "container", "direction": "vertical", "children": [
        {"type": "text", "text": "Sales overview", "fixed_size": 40},
        {"type": "worksheet", "name": "KPI", "fixed_size": 90},
        {"type": "container", "direction": "horizontal", "weight": 1, "children": [
            {"type": "worksheet", "name": "Table", "weight": 1},
            {"type": "worksheet", "name": "Bars", "weight": 1},
            {"type": "worksheet", "name": "Chosen", "weight": 1}]},
        {"type": "worksheet", "name": "Trend", "fixed_size": 260},
        {"type": "paramctrl", "parameter": "Metric", "fixed_size": 60}]}
    ed.add_dashboard("Overview", width=1200, height=800, layout=layout,
                     worksheet_names=list(SHEETS))
    column = lambda names: {"type": "container", "direction": "vertical", "weight": 1,
                            "children": [{"type": "worksheet", "name": n, "weight": 1} for n in names]}
    ed.add_dashboard("Grid", width=1200, height=800, worksheet_names=["Table", "Bars", "Trend", "KPI"],
                     layout={"type": "container", "direction": "horizontal",
                             "children": [column(["Table", "Bars"]), column(["Trend", "KPI"])]})
    out = os.path.join(folder, "matrix.twbx")
    ed.save(out)
    return out
