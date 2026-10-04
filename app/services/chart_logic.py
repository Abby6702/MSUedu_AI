"""Pure functions that turn numbers into SVG chart coordinates (no database, no Flask)."""
import math
from datetime import timedelta

from app.timeutil import to_local


def day_list(today, days):
    """The last `days` dates, oldest first, ending today."""
    return [today - timedelta(days=days - 1 - i) for i in range(days)]


def bucket_by_day(times, today, days):
    """Count UTC datetimes per Philippine-time day. Returns `days` counts, oldest first.
    Times outside the window are ignored."""
    counts = [0] * days
    start = today - timedelta(days=days - 1)
    for t in times:
        if t is None:
            continue
        index = (to_local(t).date() - start).days
        if 0 <= index < days:
            counts[index] += 1
    return counts


def nice_top(maximum):
    """A tidy top value for the y axis (1, 2, 5, 10, 20, 50 ... times a power of ten)."""
    if maximum <= 0:
        return 4
    magnitude = 10 ** math.floor(math.log10(maximum))
    for step in (1, 2, 5, 10):
        if maximum <= step * magnitude:
            return step * magnitude
    return 10 * magnitude


def short(label, limit=24):
    label = str(label)
    return label if len(label) <= limit else label[:limit - 1].rstrip() + "\u2026"


def line_chart(days, series, width=640, height=220):
    """days: list of dates. series: list of (name, css_class, counts), one count per day."""
    left, right, top, bottom = 40, 12, 12, 30
    plot_w, plot_h = width - left - right, height - top - bottom
    peak = max((max(counts) for _n, _c, counts in series if counts), default=0)
    top_value = nice_top(peak)
    count = len(days)

    def x(i):
        return round(left + plot_w * (i / (count - 1 if count > 1 else 1)), 1)

    def y(value):
        return round(top + plot_h * (1 - value / top_value), 1)

    step = 1 if count <= 7 else 2
    drawn = []
    for name, css, counts in series:
        drawn.append({
            "name": name, "css": css, "total": sum(counts),
            "points": " ".join(f"{x(i)},{y(v)}" for i, v in enumerate(counts)),
            "dots": [{"x": x(i), "y": y(v), "value": v, "day": days[i].strftime("%d %b")}
                     for i, v in enumerate(counts)]})
    return {
        "width": width, "height": height, "left": left, "right_x": width - right,
        "y_ticks": [{"y": y(v), "label": v} for v in sorted({0, top_value // 2, top_value})],
        "x_labels": [{"x": x(i), "text": days[i].strftime("%d %b")}
                     for i in range(count) if (count - 1 - i) % step == 0],
        "series": drawn}


def horizontal_bars(items, label_w=170, max_bar=260, bar_h=20, gap=10, value_w=60):
    """items: list of (label, value). Bars are scaled to the largest value."""
    items = list(items)
    peak = max((value for _label, value in items), default=0)
    rows = []
    for i, (label, value) in enumerate(items):
        bar_w = 0 if peak <= 0 or value <= 0 else max(2, round(max_bar * value / peak))
        y = i * (bar_h + gap)
        rows.append({"label": short(label), "full": str(label), "value": value,
                     "y": y, "text_y": y + bar_h - 5, "bar_w": bar_w})
    return {"rows": rows, "width": label_w + max_bar + value_w, "height": max(1, len(rows)) * (bar_h + gap),
            "label_w": label_w, "bar_h": bar_h}