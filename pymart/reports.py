"""Classes de génération des rapports.

Chaque rapport produit des lignes textuelles directement à partir des données
stockées dans le Store. Les rapports sont archivés dans un dossier daté en
fonction de la période concernée.
"""
import calendar
import os
from abc import ABC, abstractmethod
from collections import defaultdict
from decimal import Decimal

from pymart.utils import (CURRENCY, fmt_money, month_bounds, write_lines)

TOP_N = 5
LOW_STOCK = 10


def _month_dir(day):
    return os.path.join(f"{day.year:04d}", f"{day.month:02d}")


def _sales_block(orders):
    """Shared generator: totals, categories, top products (for any period)."""
    zero = Decimal("0")
    subtotal = sum((o.subtotal for o in orders), zero)
    discount = sum((o.discount for o in orders), zero)
    tax = sum((o.tax for o in orders), zero)
    total = sum((o.total for o in orders), zero)
    yield f"Orders          : {len(orders)}"
    yield f"Units sold      : {sum(o.units for o in orders)}"
    yield f"Subtotal        : {fmt_money(subtotal)} {CURRENCY}"
    yield f"Discounts       : {fmt_money(discount)} {CURRENCY}"
    yield f"Tax             : {fmt_money(tax)} {CURRENCY}"
    yield f"Total revenue   : {fmt_money(total)} {CURRENCY}"
    if not orders:
        yield ""
        yield "No sales recorded for this period."
        return

    by_category = defaultdict(lambda: [0, zero])
    by_product = defaultdict(lambda: [0, zero])
    for order in orders:
        for line in order.lines:
            for bucket, key in ((by_category, line.product.category),
                                (by_product, line.product.product_id)):
                bucket[key][0] += line.quantity
                bucket[key][1] += line.subtotal
    yield ""
    yield "-- Sales by category --"
    yield f"{'Category':<20}{'Units':>7}{'Revenue':>14}"
    for name in sorted(by_category):
        units, revenue = by_category[name]
        yield f"{name:<20}{units:>7}{fmt_money(revenue):>14}"
    yield ""
    yield f"-- Top {TOP_N} products (by units) --"
    yield f"{'ID':<8}{'Name':<26}{'Units':>7}{'Revenue':>14}"
    ranking = sorted(by_product.items(), key=lambda kv: (-kv[1][0], kv[0]))
    names = {l.product.product_id: l.product.name
             for o in orders for l in o.lines}
    for pid, (units, revenue) in ranking[:TOP_N]:
        yield f"{pid:<8}{names[pid]:<26}{units:>7}{fmt_money(revenue):>14}"


class Report(ABC):
    title = ""

    def __init__(self, store):
        self.store = store

    @abstractmethod
    def relative_path(self):
        """Archive location of the report, relative to the output directory."""

    @abstractmethod
    def period_label(self):
        """Human-readable reporting period."""

    @abstractmethod
    def body(self):
        """Generator yielding the report body lines."""

    def lines(self):
        yield f"=== PyMart | {self.title} ==="
        yield f"Period        : {self.period_label()}"
        yield f"Data snapshot : {self.store.imported_at or 'n/a'}"
        yield ""
        yield from self.body()

    def write(self, out_dir):
        path = os.path.join(out_dir, self.relative_path())
        write_lines(path, self.lines())
        return path


class DailySalesReport(Report):
    title = "Daily Sales Summary"

    def __init__(self, store, day):
        super().__init__(store)
        self.day = day

    def relative_path(self):
        return os.path.join(_month_dir(self.day),
                            f"daily_sales_{self.day.isoformat()}.txt")

    def period_label(self):
        return f"{self.day.isoformat()} ({calendar.day_name[self.day.weekday()]})"

    def body(self):
        orders = [o for o in self.store.orders_sorted()
                  if o.order_date == self.day]
        yield from _sales_block(orders)
        if orders:
            yield ""
            yield "-- Orders --"
            for o in orders:
                yield (f"{o.order_id:<7}{o.customer.customer_id:<7}"
                       f"{o.customer.name:<24}{o.units:>4} units"
                       f"{fmt_money(o.total):>14} {CURRENCY}")


class MonthlySummaryReport(Report):
    title = "Monthly Summary"

    def __init__(self, store, year, month):
        super().__init__(store)
        self.year, self.month = year, month
        self.first, self.last = month_bounds(year, month)

    def relative_path(self):
        return os.path.join(_month_dir(self.first),
                            f"monthly_summary_{self.year:04d}-{self.month:02d}.txt")

    def period_label(self):
        return (f"{calendar.month_name[self.month]} {self.year} "
                f"({self.first.isoformat()} to {self.last.isoformat()})")

    def body(self):
        orders = [o for o in self.store.orders_sorted()
                  if self.first <= o.order_date <= self.last]
        yield from _sales_block(orders)
        if not orders:
            return
        per_day = defaultdict(lambda: Decimal("0"))
        spend = defaultdict(lambda: Decimal("0"))
        for o in orders:
            per_day[o.order_date] += o.total
            spend[o.customer.customer_id] += o.total
        days_in_month = (self.last - self.first).days + 1
        best_day = max(per_day, key=lambda d: (per_day[d], -d.toordinal()))
        yield ""
        yield f"Days with sales : {len(per_day)} / {days_in_month}"
        yield (f"Best day        : {best_day.isoformat()} "
               f"({calendar.day_name[best_day.weekday()]}) "
               f"{fmt_money(per_day[best_day])} {CURRENCY}")
        yield ""
        yield "-- Revenue per day --"
        for day in sorted(per_day):
            yield f"{day.isoformat()}  {fmt_money(per_day[day]):>14} {CURRENCY}"
        yield ""
        yield f"-- Top {TOP_N} customers (by spend) --"
        ranking = sorted(spend.items(), key=lambda kv: (-kv[1], kv[0]))
        for cid, amount in ranking[:TOP_N]:
            yield (f"{cid:<7}{self.store.customers[cid].name:<26}"
                   f"{fmt_money(amount):>14} {CURRENCY}")


class StockReport(Report):
    title = "Stock Levels"

    def __init__(self, store, day):
        super().__init__(store)
        self.day = day

    def relative_path(self):
        return os.path.join(_month_dir(self.day),
                            f"stock_levels_{self.day.isoformat()}.txt")

    def period_label(self):
        return f"as of {self.day.isoformat()}"

    def body(self):
        yield f"{'ID':<8}{'Name':<26}{'Category':<14}{'Stock':>6}  Status"
        flagged = 0
        for pid in sorted(self.store.products):
            p = self.store.products[pid]
            status = p.stock_label(self.day, LOW_STOCK)
            if status != "OK":
                flagged += 1
            stock = "-" if p.kind == "digital" else str(p.stock)
            yield f"{pid:<8}{p.name:<26}{p.category:<14}{stock:>6}  {status}"
        yield ""
        yield f"Products: {len(self.store.products)}  |  needing attention: {flagged}"


class RejectsReport(Report):
    title = "Failed Records"

    def __init__(self, store, day):
        super().__init__(store)
        self.day = day

    def relative_path(self):
        return os.path.join(_month_dir(self.day),
                            f"failed_records_{self.day.isoformat()}.txt")

    def period_label(self):
        return f"as of {self.day.isoformat()}"

    def body(self):
        rejects = sorted(self.store.rejects,
                         key=lambda r: (r["entity"], r["file"], r["line"]))
        yield f"Rejected records: {len(rejects)}"
        for r in rejects:
            yield ""
            yield f"[{r['entity']}] {r['file']}:{r['line']}  {r['message']}"
            yield f"    raw: {r['raw']}"
