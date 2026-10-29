"""Interface en ligne de commande du package PyMart.

Cette couche permet d'utiliser le projet comme un outil terminal. Elle reçoit les
arguments, appelle les services métier et affiche les résultats à l'utilisateur.
"""
import argparse
import sys
import time
from datetime import date, datetime

from pymart import __version__, services
from pymart.exceptions import PyMartError, RecordFormatError
from pymart.reports import (DailySalesReport, MonthlySummaryReport,
                            RejectsReport, StockReport)
from pymart.store import DEFAULT_STATE, Store
from pymart.utils import (CURRENCY, fmt_money, month_bounds,
                          next_report_dates, parse_date, parse_int,
                          parse_month)

REPORT_TYPES = ("daily", "monthly", "stock", "rejects", "all")


def build_parser():
    # Construction du parseur principal : on définit ici les commandes disponibles
    # et les arguments attendus pour chaque action.
    parser = argparse.ArgumentParser(
        prog="pymart", description="PyMart back-office toolkit")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--state", default=DEFAULT_STATE,
                        help=f"state file (default: {DEFAULT_STATE})")
    sub = parser.add_subparsers(dest="command", required=True)

    imp = sub.add_parser("import", help="import product/customer/order files")
    imp.add_argument("--products")
    imp.add_argument("--customers")
    imp.add_argument("--orders")

    orders = sub.add_parser("orders", help="create or list orders")
    osub = orders.add_subparsers(dest="action", required=True)
    create = osub.add_parser("create", help="create an order")
    create.add_argument("--customer", required=True, help="customer id, e.g. C001")
    create.add_argument("--item", action="append", required=True,
                        metavar="PRODUCT:QTY", help="repeatable, e.g. P001:2")
    create.add_argument("--date", help="order date (default: today)")
    lst = osub.add_parser("list", help="list orders")
    lst.add_argument("--customer")
    lst.add_argument("--date")

    rep = sub.add_parser("report", help="generate reports on disk")
    rep.add_argument("--type", choices=REPORT_TYPES, required=True)
    rep.add_argument("--date", help="YYYY-MM-DD (default: today)")
    rep.add_argument("--month", help="YYYY-MM (default: current month)")
    rep.add_argument("--out", default="reports", help="output directory")

    sched = sub.add_parser("schedule", help="show next report dates")
    sched.add_argument("--date", help="reference date (default: today)")
    return parser


# ----------------------------------------------------------------- commands
def cmd_import(args, store):
    jobs = [("products", args.products, services.import_products),
            ("customers", args.customers, services.import_customers),
            ("orders", args.orders, services.import_orders)]
    if not any(path for _, path, _ in jobs):
        raise RecordFormatError(
            "nothing to import: give --products, --customers and/or --orders")
    results = []
    for _, path, func in jobs:  # order matters: products/customers first
        if path:
            results.append(func(path, store))
    services.finish_import(store, results)
    for r in results:
        if r.fatal_error:
            print(f"[{r.entity}] FAILED  {r.fatal_error}", file=sys.stderr)
        else:
            print(f"[{r.entity}] {r.accepted} accepted, {r.rejected} rejected "
                  f"({r.elapsed * 1000:.1f} ms)")
            for item in r.rejects:
                print(f"    ! {item['file']}:{item['line']}: {item['message']}")
    store.save(args.state)
    return 1 if any(r.fatal_error for r in results) else 0


def _print_order(order):
    print(f"{order.order_id}  {order.order_date.isoformat()}  "
          f"{order.customer.describe()}")
    for line in order.lines:
        print(f"    {line.product.product_id} x{line.quantity:<4}"
              f"@ {fmt_money(line.unit_price):>8}  {line.product.name}")
    print(f"    subtotal {fmt_money(order.subtotal)} - discount "
          f"{fmt_money(order.discount)} + tax {fmt_money(order.tax)} "
          f"= TOTAL {fmt_money(order.total)} {CURRENCY}")


def cmd_orders(args, store):
    if args.action == "create":
        items = []
        for spec in args.item:
            product_id, sep, qty = spec.partition(":")
            if not sep:
                raise RecordFormatError(f"bad --item {spec!r}, expected PRODUCT:QTY")
            items.append((product_id.strip().upper(), parse_int(qty, "quantity")))
        day = parse_date(args.date, "date") if args.date else date.today()
        order = services.create_order(store, args.customer, items, day)
        store.save(args.state)
        print("Order created:")
        _print_order(order)
        return 0
    day = parse_date(args.date, "date") if args.date else None
    customer = args.customer.strip().upper() if args.customer else None
    count = 0
    for order in services.iter_orders(store, customer, day):
        _print_order(order)
        count += 1
    print(f"{count} order(s).")
    return 0


def cmd_report(args, store):
    today = date.today()
    day = parse_date(args.date, "date") if args.date else today
    year, month = parse_month(args.month) if args.month else (
        (day.year, day.month) if args.date else (today.year, today.month))
    wanted = {
        "daily": lambda: DailySalesReport(store, day),
        "monthly": lambda: MonthlySummaryReport(store, year, month),
        "stock": lambda: StockReport(store, day),
        "rejects": lambda: RejectsReport(store, day),
    }
    kinds = list(wanted) if args.type == "all" else [args.type]
    print(f"Generating at {datetime.now():%Y-%m-%d %H:%M:%S} "
          f"(unix {int(time.time())})")
    for kind in kinds:
        path = wanted[kind]().write(args.out)
        print(f"  {kind:<8} -> {path}")
    return 0


def cmd_schedule(args, store):
    today = parse_date(args.date, "date") if args.date else date.today()
    tomorrow, next_month = next_report_dates(today)
    _, last_day = month_bounds(today.year, today.month)
    print(f"Reference date          : {today.isoformat()}")
    print(f"Next daily report       : {tomorrow.isoformat()}")
    print(f"Month-end (this month)  : {last_day.isoformat()}")
    print(f"Next monthly report     : {next_month.strftime('%Y-%m')} "
          f"(run on/after {next_month.isoformat()})")
    return 0


COMMANDS = {"import": cmd_import, "orders": cmd_orders,
            "report": cmd_report, "schedule": cmd_schedule}


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        store = Store.load(args.state)
        return COMMANDS[args.command](args, store)
    except PyMartError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
