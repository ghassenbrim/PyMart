"""Services métier du projet.

Ce module contient la logique de traitement des fichiers importés, la création
et la validation des commandes, ainsi que la gestion du stock.
"""
import time
from dataclasses import dataclass, field
from datetime import datetime

from pymart import parsers
from pymart.exceptions import (DataValidationError, DuplicateIdError,
                               FileAccessError, PyMartError,
                               UnknownCustomerError, UnknownProductError)
from pymart.models import Order


@dataclass
class ImportResult:
    entity: str
    path: str
    accepted: int = 0
    rejected: int = 0
    fatal_error: str = ""
    elapsed: float = 0.0
    rejects: list = field(default_factory=list)


def _reject(result, path, line_no, raw, exc):
    exc.add_context(path, line_no)
    result.rejected += 1
    result.rejects.append({"entity": result.entity, "file": exc.file,
                           "line": line_no, "message": exc.message, "raw": raw})


def _run_import(entity, path, required, handle_row):
    """Common loop: stream rows, validate each, keep going on bad records."""
    result = ImportResult(entity, path)
    started = time.perf_counter()
    try:
        reader = parsers.DelimitedFile(path, required)
        for line_no, raw, row in reader.rows():
            try:
                handle_row(row)
            except PyMartError as exc:
                _reject(result, path, line_no, raw, exc)
            else:
                result.accepted += 1
    except PyMartError as exc:  # file-level problem (missing, no header...)
        result.fatal_error = str(exc)
    finally:
        result.elapsed = time.perf_counter() - started
    return result


def import_products(path, store):
    """Importe les produits à partir d'un fichier texte.

    Les produits sont validés un par un. En cas d'erreur, ils sont rejetés sans
    faire planter toute l'importation.
    """
    products = {}

    def handle(row):
        product = parsers.build_product(row)
        if product.product_id in products:
            raise DuplicateIdError(f"duplicate product id {product.product_id}")
        products[product.product_id] = product

    result = _run_import("products", path, parsers.PRODUCT_COLUMNS, handle)
    if not result.fatal_error:
        store.products = products
    return result


def import_customers(path, store):
    customers = {}

    def handle(row):
        customer = parsers.build_customer(row)
        if customer.customer_id in customers:
            raise DuplicateIdError(f"duplicate customer id {customer.customer_id}")
        customers[customer.customer_id] = customer

    result = _run_import("customers", path, parsers.CUSTOMER_COLUMNS, handle)
    if not result.fatal_error:
        store.customers = customers
    return result


def import_orders(path, store):
    orders = {}

    def handle(row):
        data = parsers.build_order_line(row)
        customer = store.customers.get(data["customer_id"])
        if customer is None:
            raise UnknownCustomerError(f"unknown customer {data['customer_id']}")
        product = store.products.get(data["product_id"])
        if product is None:
            raise UnknownProductError(f"unknown product {data['product_id']}")
        order = orders.get(data["order_id"])
        if order is None:
            order = Order(data["order_id"], data["order_date"], customer)
        elif (order.customer is not customer
              or order.order_date != data["order_date"]):
            raise DataValidationError(
                f"order {order.order_id} conflicts with its earlier lines "
                "(different customer or date)")
        order.add_line(product, data["quantity"])  # may raise
        orders[order.order_id] = order  # stored only once a line is valid

    result = _run_import("orders", path, parsers.ORDER_COLUMNS, handle)
    if not result.fatal_error:
        store.orders = orders
    return result


def finish_import(store, results):
    """Replace stored rejects of re-imported entities and stamp the snapshot."""
    done = {r.entity for r in results if not r.fatal_error}
    store.rejects = [r for r in store.rejects if r["entity"] not in done]
    for result in results:
        if not result.fatal_error:
            store.rejects.extend(result.rejects)
    if done:
        store.imported_at = datetime.now().isoformat(timespec="seconds")


# ------------------------------------------------------------ order service
def create_order(store, customer_id, items, order_date):
    """Crée une commande à partir d'une liste de produits et quantités.

    La méthode vérifie l'existence du client et du produit, contrôle le stock,
    puis réserve les quantités avant d'enregistrer la commande.
    """
    customer = store.customers.get(customer_id.strip().upper())
    if customer is None:
        raise UnknownCustomerError(f"unknown customer {customer_id}")
    order = Order(store.next_order_id(), order_date, customer)
    for product_id, quantity in items:
        product = store.products.get(product_id)
        if product is None:
            raise UnknownProductError(f"unknown product {product_id}")
        if not product.has_stock_for(quantity):
            product.reserve(quantity)  # raises InsufficientStockError
        order.add_line(product, quantity)
    for line in order.lines:  # only deduct once everything is valid
        line.product.reserve(line.quantity)
    store.orders[order.order_id] = order
    return order


def iter_orders(store, customer_id=None, on_date=None):
    """Generator of orders matching the optional filters."""
    for order in store.orders_sorted():
        if customer_id and order.customer.customer_id != customer_id:
            continue
        if on_date and order.order_date != on_date:
            continue
        yield order
