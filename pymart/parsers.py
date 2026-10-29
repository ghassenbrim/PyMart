"""Lecture et transformation des fichiers importés.

Ce module lit les fichiers texte, détecte le séparateur, normalise les colonnes
et construit les objets métier correspondant aux produits, clients et commandes.
"""
from pymart.exceptions import (DataValidationError, FileAccessError,
                               RecordFormatError)
from pymart.models import (CUSTOMER_KINDS, PRODUCT_KINDS, BusinessCustomer,
                           DigitalProduct, IndividualCustomer,
                           PerishableProduct, Product)
from pymart.utils import (clean_text, normalise_header, normalise_id,
                          parse_date, parse_decimal, parse_int, split_line)

ALIASES = {"id": "product_id", "date": "order_date", "qty": "quantity",
           "customer": "customer_id", "product": "product_id",
           "order": "order_id", "unit_price": "price"}

PRODUCT_COLUMNS = ("product_id", "name", "category", "price", "stock")
CUSTOMER_COLUMNS = ("customer_id", "name")
ORDER_COLUMNS = ("order_id", "order_date", "customer_id", "product_id", "quantity")


class DelimitedFile:
    """Lit un fichier texte de manière progressive.

    Le séparateur est détecté automatiquement pour chaque ligne ; cela permet
    de supporter plusieurs formats de fichiers comme ;, , | ou tabulation.
    """

    def __init__(self, path, required):
        self.path = path
        self.required = tuple(required)
        self.header = []

    def _content_lines(self):
        """Generator of (line_number, stripped_text), skipping blanks/comments."""
        try:
            handle = open(self.path, encoding="utf-8-sig")
        except OSError as exc:
            raise FileAccessError(
                f"cannot open file: {exc.strerror}").add_context(self.path) from exc
        try:
            for line_no, raw in enumerate(handle, start=1):
                text = raw.strip()
                if text and not text.startswith("#"):
                    yield line_no, text
        except UnicodeDecodeError as exc:
            raise FileAccessError(
                "file is not valid UTF-8 text").add_context(self.path) from exc
        finally:
            handle.close()

    def rows(self):
        """Generator yielding (line_no, raw_text, {column: value or None})."""
        header_found = False
        for line_no, text in self._content_lines():
            fields = split_line(text)
            if not header_found:
                names = [ALIASES.get(h, h) for h in map(normalise_header, fields)]
                missing = [c for c in self.required if c not in names]
                if missing:
                    raise RecordFormatError(
                        "missing required column(s): " + ", ".join(missing)
                    ).add_context(self.path, line_no)
                self.header = names
                header_found = True
                continue
            yield line_no, text, {
                name: (fields[i] if i < len(fields) else None)
                for i, name in enumerate(self.header)}
        if not header_found:
            raise RecordFormatError("file is empty (no header)").add_context(self.path)


def _required_text(row, key, label):
    value = clean_text(row.get(key))
    if not value:
        raise DataValidationError(f"missing {label}")
    return value


def build_product(row):
    product_id = normalise_id(row.get("product_id"), "P", "product id")
    name = _required_text(row, "name", "product name").title()
    category = _required_text(row, "category", "category").title()
    price = parse_decimal(row.get("price"), "price")
    if price <= 0:
        raise DataValidationError(f"price must be positive: {price}")
    stock = parse_int(row.get("stock"), "stock")
    if stock < 0:
        raise DataValidationError(f"stock cannot be negative: {stock}")
    kind = clean_text(row.get("type")).lower() or "standard"
    if kind not in PRODUCT_KINDS:
        raise DataValidationError(
            f"unknown product type {kind!r} (allowed: {', '.join(PRODUCT_KINDS)})")
    if kind == "perishable":
        expiry = parse_date(row.get("expiry_date"), "expiry_date")
        return PerishableProduct(product_id, name, category, price, stock, expiry)
    if kind == "digital":
        return DigitalProduct(product_id, name, category, price, stock)
    return Product(product_id, name, category, price, stock)


def build_customer(row):
    customer_id = normalise_id(row.get("customer_id"), "C", "customer id")
    name = _required_text(row, "name", "customer name").title()
    email = clean_text(row.get("email")).lower()
    if email and ("@" not in email or "." not in email.split("@")[-1]):
        raise DataValidationError(f"invalid email {email!r}")
    kind = clean_text(row.get("type")).lower() or "individual"
    if kind not in CUSTOMER_KINDS:
        raise DataValidationError(
            f"unknown customer type {kind!r} (allowed: {', '.join(CUSTOMER_KINDS)})")
    city = clean_text(row.get("city")).title()
    klass = BusinessCustomer if kind == "business" else IndividualCustomer
    return klass(customer_id, name, email, city)


def build_order_line(row):
    quantity = parse_int(row.get("quantity"), "quantity")
    if quantity <= 0:
        raise DataValidationError(f"quantity must be positive: {quantity}")
    return {"order_id": normalise_id(row.get("order_id"), "O", "order id"),
            "order_date": parse_date(row.get("order_date"), "order date"),
            "customer_id": normalise_id(row.get("customer_id"), "C", "customer id"),
            "product_id": normalise_id(row.get("product_id"), "P", "product id"),
            "quantity": quantity}
