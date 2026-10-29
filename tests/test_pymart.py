import os
import tempfile
import unittest
from datetime import date
from decimal import Decimal

from pymart import parsers, services
from pymart.exceptions import (DuplicateIdError, InsufficientStockError,
                               RecordFormatError, UnknownCustomerError)
from pymart.models import (BusinessCustomer, DigitalProduct, IndividualCustomer,
                           Order, PerishableProduct, Product)
from pymart.reports import DailySalesReport, MonthlySummaryReport
from pymart.store import Store
from pymart.utils import (detect_delimiter, month_bounds, next_report_dates,
                          parse_date, parse_decimal)

def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


DATA = os.path.join(os.path.dirname(__file__), "..", "data")


def loaded_store():
    store = Store()
    results = [services.import_products(os.path.join(DATA, "products.txt"), store),
               services.import_customers(os.path.join(DATA, "customers.txt"), store),
               services.import_orders(os.path.join(DATA, "orders.txt"), store)]
    services.finish_import(store, results)
    return store, results


class UtilsTests(unittest.TestCase):
    def test_delimiter_and_numbers(self):
        self.assertEqual(detect_delimiter("a|b|c"), "|")
        self.assertEqual(parse_decimal("4,50", "price"), Decimal("4.50"))
        with self.assertRaises(RecordFormatError):
            parse_decimal("abc", "price")

    def test_dates(self):
        self.assertEqual(parse_date("30/06/2026"), date(2026, 6, 30))
        with self.assertRaises(RecordFormatError):
            parse_date("31-06-2026")
        self.assertEqual(month_bounds(2024, 2)[1], date(2024, 2, 29))
        self.assertEqual(next_report_dates(date(2026, 12, 15))[1], date(2027, 1, 1))


class ModelTests(unittest.TestCase):
    def test_polymorphic_pricing_and_discount(self):
        day = date(2026, 6, 30)
        std = Product("P001", "Rice", "Grocery", Decimal("10"), 5)
        per = PerishableProduct("P002", "Milk", "Dairy", Decimal("10"), 5, date(2026, 7, 1))
        dig = DigitalProduct("P003", "Ebook", "Digital", Decimal("10"), 0)
        self.assertEqual(std.price_on(day), Decimal("10.00"))
        self.assertEqual(per.price_on(day), Decimal("7.00"))
        self.assertTrue(dig.has_stock_for(999))
        self.assertEqual(IndividualCustomer("C001", "A").discount_rate, 0)
        self.assertEqual(BusinessCustomer("C002", "B").discount_rate, Decimal("0.10"))

    def test_duplicate_line_and_stock(self):
        std = Product("P001", "Rice", "Grocery", Decimal("10"), 1)
        order = Order("O001", date(2026, 6, 1), IndividualCustomer("C001", "A"))
        order.add_line(std, 1)
        with self.assertRaises(DuplicateIdError):
            order.add_line(std, 1)
        with self.assertRaises(InsufficientStockError):
            std.reserve(5)


class ImportAndReportTests(unittest.TestCase):
    def test_import_counts_and_context(self):
        store, results = loaded_store()
        self.assertEqual([r.accepted for r in results], [7, 5, 9])
        self.assertTrue(all(r["line"] for r in store.rejects))

    def test_missing_file_is_not_a_crash(self):
        result = services.import_products("nope.txt", Store())
        self.assertIn("cannot open file", result.fatal_error)

    def test_create_order_unknown_customer(self):
        store, _ = loaded_store()
        with self.assertRaises(UnknownCustomerError):
            services.create_order(store, "C999", [("P001", 1)], date(2026, 6, 30))

    def test_reports_reproducible(self):
        store, _ = loaded_store()
        with tempfile.TemporaryDirectory() as tmp:
            first = DailySalesReport(store, date(2026, 6, 30)).write(tmp)
            text1 = read(first)
            second = DailySalesReport(store, date(2026, 6, 30)).write(tmp)
            self.assertEqual(text1, read(second))
            monthly = MonthlySummaryReport(store, 2026, 6).write(tmp)
            self.assertTrue(monthly.endswith(os.path.join("2026", "06", "monthly_summary_2026-06.txt")))


if __name__ == "__main__":
    unittest.main()
