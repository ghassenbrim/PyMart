"""Modèles métier du projet.

Ce module contient les objets du domaine applicatif :
- Product -> PerishableProduct, DigitalProduct
- Customer -> IndividualCustomer, BusinessCustomer
- Order -> commande avec lignes de produits

La logique de calcul du prix, des remises et des taxes est ici centralisée.
"""
from datetime import date, timedelta
from decimal import Decimal

from pymart.exceptions import (DataValidationError, DuplicateIdError,
                               InsufficientStockError)
from pymart.utils import CURRENCY, money


# ================================================================= produits
# Les produits possèdent des règles différentes selon leur type.
# Certaines fonctionnalités sont héritées, d'autres sont remplacées dans les
# sous-classes pour adapter la logique métier.
class Product:
    kind = "standard"
    tax_rate = Decimal("0.19")

    def __init__(self, product_id, name, category, price, stock):
        self.product_id = product_id
        self.name = name
        self.category = category
        self.price = price
        self.stock = stock

    # -- encapsulated attributes
    @property
    def price(self):
        return self._price

    @price.setter
    def price(self, value):
        if value <= 0:
            raise DataValidationError(f"price must be positive, got {value}")
        self._price = money(value)

    @property
    def stock(self):
        return self._stock

    @stock.setter
    def stock(self, value):
        if value < 0:
            raise DataValidationError(f"stock cannot be negative, got {value}")
        self._stock = value

    # -- behaviour overridden by subclasses
    def price_on(self, on_date):
        return self._price

    def is_sellable_on(self, on_date):
        return True

    def has_stock_for(self, quantity):
        return self._stock >= quantity

    def reserve(self, quantity):
        if not self.has_stock_for(quantity):
            raise InsufficientStockError(
                f"insufficient stock for {self.product_id}: "
                f"requested {quantity}, available {self._stock}")
        self._stock -= quantity

    def stock_label(self, on_date=None, low_threshold=10):
        if self._stock == 0:
            return "OUT OF STOCK"
        if self._stock < low_threshold:
            return "LOW"
        return "OK"

    def describe(self):
        return (f"{self.product_id} {self.name} [{self.category}] "
                f"{self.price} {CURRENCY} (stock {self._stock})")

    # -- serialisation
    def to_dict(self):
        return {"kind": self.kind, "product_id": self.product_id,
                "name": self.name, "category": self.category,
                "price": str(self._price), "stock": self._stock}

    @classmethod
    def from_dict(cls, data):
        return _PRODUCT_KINDS[data["kind"]]._from_dict(data)

    @classmethod
    def _from_dict(cls, data):
        return cls(data["product_id"], data["name"], data["category"],
                   Decimal(data["price"]), data["stock"])


class PerishableProduct(Product):
    kind = "perishable"
    tax_rate = Decimal("0.07")
    DISCOUNT_WINDOW_DAYS = 2
    DISCOUNT = Decimal("0.30")

    def __init__(self, product_id, name, category, price, stock, expiry_date):
        super().__init__(product_id, name, category, price, stock)
        self.expiry_date = expiry_date

    def price_on(self, on_date):
        """30 % off during the last two days before expiry."""
        if (self.expiry_date - on_date) <= timedelta(days=self.DISCOUNT_WINDOW_DAYS):
            return money(self._price * (1 - self.DISCOUNT))
        return self._price

    def is_sellable_on(self, on_date):
        return on_date <= self.expiry_date

    def stock_label(self, on_date=None, low_threshold=10):
        if on_date is not None and on_date > self.expiry_date:
            return "EXPIRED"
        base = super().stock_label(on_date, low_threshold)
        if on_date is not None and (self.expiry_date - on_date).days <= 2:
            return f"{base} / EXPIRES {self.expiry_date.isoformat()}"
        return base

    def describe(self):
        return f"{super().describe()} expires {self.expiry_date.isoformat()}"

    def to_dict(self):
        data = super().to_dict()
        data["expiry_date"] = self.expiry_date.isoformat()
        return data

    @classmethod
    def _from_dict(cls, data):
        return cls(data["product_id"], data["name"], data["category"],
                   Decimal(data["price"]), data["stock"],
                   date.fromisoformat(data["expiry_date"]))


class DigitalProduct(Product):
    kind = "digital"

    def has_stock_for(self, quantity):
        return True  # unlimited

    def reserve(self, quantity):
        return None  # nothing to deduct

    def stock_label(self, on_date=None, low_threshold=10):
        return "UNLIMITED"

    def describe(self):
        return (f"{self.product_id} {self.name} [{self.category}] "
                f"{self.price} {CURRENCY} (digital)")


_PRODUCT_KINDS = {c.kind: c for c in (Product, PerishableProduct, DigitalProduct)}


# ================================================================ clients
# Les clients ont des comportements différents selon leur catégorie.
# Par exemple, un client professionnel bénéficie d'une réduction particulière.
class Customer:
    kind = "individual"
    discount_rate = Decimal("0")
    _label = "Individual"

    def __init__(self, customer_id, name, email="", city=""):
        self.customer_id = customer_id
        self.name = name
        self.email = email
        self.city = city

    def describe(self):
        return f"{self.customer_id} {self.name} ({self.city or 'n/a'}) [{self._label}]"

    def to_dict(self):
        return {"kind": self.kind, "customer_id": self.customer_id,
                "name": self.name, "email": self.email, "city": self.city}

    @classmethod
    def from_dict(cls, data):
        klass = _CUSTOMER_KINDS[data["kind"]]
        return klass(data["customer_id"], data["name"],
                     data.get("email", ""), data.get("city", ""))


class IndividualCustomer(Customer):
    pass


class BusinessCustomer(Customer):
    kind = "business"
    discount_rate = Decimal("0.10")
    _label = "Business -10%"


_CUSTOMER_KINDS = {"individual": IndividualCustomer, "business": BusinessCustomer}
CUSTOMER_KINDS = tuple(_CUSTOMER_KINDS)
PRODUCT_KINDS = tuple(_PRODUCT_KINDS)


# ================================================================== commandes
# Une commande est composée de plusieurs lignes, chacune représentant un produit
# acheté avec sa quantité et son prix unitaire au moment de la commande.
class OrderLine:
    def __init__(self, product, quantity, unit_price):
        self.product = product
        self.quantity = quantity
        self.unit_price = unit_price

    @property
    def subtotal(self):
        return money(self.unit_price * self.quantity)


class Order:
    def __init__(self, order_id, order_date, customer):
        self.order_id = order_id
        self.order_date = order_date
        self.customer = customer
        self.lines = []

    def add_line(self, product, quantity):
        if quantity <= 0:
            raise DataValidationError(f"quantity must be positive, got {quantity}")
        if any(l.product.product_id == product.product_id for l in self.lines):
            raise DuplicateIdError(
                f"product {product.product_id} already in order {self.order_id}")
        if not product.is_sellable_on(self.order_date):
            raise DataValidationError(
                f"product {product.product_id} is expired on "
                f"{self.order_date.isoformat()}")
        line = OrderLine(product, quantity, product.price_on(self.order_date))
        self.lines.append(line)
        return line

    @property
    def units(self):
        return sum(l.quantity for l in self.lines)

    @property
    def subtotal(self):
        return sum((l.subtotal for l in self.lines), Decimal("0"))

    @property
    def discount(self):
        return money(self.subtotal * self.customer.discount_rate)

    @property
    def tax(self):
        factor = 1 - self.customer.discount_rate
        return sum((money(l.subtotal * factor * l.product.tax_rate)
                    for l in self.lines), Decimal("0"))

    @property
    def total(self):
        return self.subtotal - self.discount + self.tax

    def to_dict(self):
        return {"order_id": self.order_id, "date": self.order_date.isoformat(),
                "customer_id": self.customer.customer_id,
                "lines": [{"product_id": l.product.product_id,
                           "quantity": l.quantity,
                           "unit_price": str(l.unit_price)} for l in self.lines]}

    @classmethod
    def from_dict(cls, data, products, customers):
        order = cls(data["order_id"], date.fromisoformat(data["date"]),
                    customers[data["customer_id"]])
        for item in data["lines"]:
            order.lines.append(OrderLine(products[item["product_id"]],
                                         item["quantity"],
                                         Decimal(item["unit_price"])))
        return order
