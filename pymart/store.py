"""Stockage des données du projet.

Le Store contient les produits, clients, commandes et rejets. Il est sauvegardé
periodiquement dans un fichier JSON afin de conserver l'état entre deux exécutions
du programme.
"""
import json
import os
import re

from pymart.exceptions import FileAccessError
from pymart.models import Customer, Order, Product
from pymart.utils import write_lines

DEFAULT_STATE = os.path.join(".pymart", "state.json")


class Store:
    def __init__(self):
        self.products = {}
        self.customers = {}
        self.orders = {}
        self.rejects = []
        self.imported_at = None

    def orders_sorted(self):
        """Generator: orders in a stable (id) order -> reproducible reports."""
        for order_id in sorted(self.orders):
            yield self.orders[order_id]

    def next_order_id(self):
        numbers = [int(m.group(1)) for oid in self.orders
                   if (m := re.fullmatch(r"O(\d+)", oid))]
        return f"O{(max(numbers) + 1) if numbers else 1:03d}"

    # ---------------------------------------------------------- persistence
    def save(self, path):
        # La persistance est faite en JSON pour que le programme puisse relever
        # son état lors d'une prochaine exécution sans perdre les données importées.
        data = {"imported_at": self.imported_at,
                "products": [p.to_dict() for p in self.products.values()],
                "customers": [c.to_dict() for c in self.customers.values()],
                "orders": [o.to_dict() for o in self.orders.values()],
                "rejects": self.rejects}
        write_lines(path, [json.dumps(data, indent=1, ensure_ascii=False)])

    @classmethod
    def load(cls, path):
        store = cls()
        try:
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
        except FileNotFoundError:
            return store  # first run: empty store
        except (OSError, json.JSONDecodeError) as exc:
            raise FileAccessError(f"cannot read state file {path}: {exc}") from exc
        try:
            store.imported_at = data.get("imported_at")
            for item in data["products"]:
                product = Product.from_dict(item)
                store.products[product.product_id] = product
            for item in data["customers"]:
                customer = Customer.from_dict(item)
                store.customers[customer.customer_id] = customer
            for item in data["orders"]:
                order = Order.from_dict(item, store.products, store.customers)
                store.orders[order.order_id] = order
            store.rejects = data.get("rejects", [])
        except (KeyError, ValueError) as exc:
            raise FileAccessError(
                f"state file {path} is corrupted ({exc!r}); re-run 'import'") from exc
        return store
