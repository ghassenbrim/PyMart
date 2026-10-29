"""Fonctions utilitaires du projet.

Ce module regroupe les outils de nettoyage de texte, de validation des nombres,
la conversion de dates et l’écriture sécurisée des fichiers sur le disque.
"""
import calendar
import os
import re
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from pymart.exceptions import (DataValidationError, FileAccessError,
                               RecordFormatError)

DELIMITERS = (";", ",", "|", "\t")
DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d")
CURRENCY = "TND"
_CENT = Decimal("0.01")


def money(value):
    """Round to 2 decimals (half up)."""
    return Decimal(value).quantize(_CENT, rounding=ROUND_HALF_UP)


def fmt_money(value):
    return f"{money(value):,.2f}"


# ----------------------------------------------------------- nettoyage du texte
# Cette section sert à normaliser les chaînes lues dans les fichiers CSV-like.
# On supprime les espaces, les guillemets et les espaces multiples pour éviter
# les erreurs lors de la validation des données importées.
def clean_text(value):
    """Supprime les espaces, guillemets et normalise les chaînes."""
    if value is None:
        return ""
    value = value.strip().strip("\"'").strip()
    return re.sub(r"\s+", " ", value)


def detect_delimiter(line):
    """Pick the most frequent separator of a line (handles wrong separators)."""
    counts = {d: line.count(d) for d in DELIMITERS}
    best = max(DELIMITERS, key=lambda d: counts[d])
    return best if counts[best] else ","


def split_line(line):
    delimiter = detect_delimiter(line)
    return [clean_text(part) for part in line.split(delimiter)]


def normalise_header(name):
    return re.sub(r"[\s\-]+", "_", clean_text(name).lower())


def normalise_id(raw, prefix, label):
    value = clean_text(raw).upper().replace(" ", "")
    if not value:
        raise DataValidationError(f"missing {label}")
    if not re.fullmatch(rf"{prefix}\d{{3,6}}", value):
        raise RecordFormatError(
            f"malformed {label} {raw!r} (expected '{prefix}' + 3-6 digits)")
    return value


# ------------------------------------------------------------- number/date
def parse_decimal(raw, field):
    cleaned = clean_text(raw).upper().replace(CURRENCY, "").replace("$", "")
    cleaned = cleaned.replace(" ", "")
    if not cleaned:
        raise DataValidationError(f"missing {field}")
    if "," in cleaned and "." not in cleaned:
        cleaned = cleaned.replace(",", ".")
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        raise RecordFormatError(f"invalid number for {field}: {raw!r}") from None
    if not value.is_finite():
        raise RecordFormatError(f"invalid number for {field}: {raw!r}")
    return value


def parse_int(raw, field):
    value = parse_decimal(raw, field)
    if value != value.to_integral_value():
        raise RecordFormatError(f"{field} must be a whole number: {raw!r}")
    return int(value)


def parse_date(raw, field="date"):
    text = clean_text(raw)
    if not text:
        raise DataValidationError(f"missing {field}")
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise RecordFormatError(
        f"invalid {field} {raw!r} (accepted: YYYY-MM-DD, DD/MM/YYYY, DD-MM-YYYY)")


def parse_month(text):
    try:
        parsed = datetime.strptime(text.strip(), "%Y-%m")
    except ValueError:
        raise RecordFormatError(
            f"invalid month {text!r} (expected YYYY-MM)") from None
    return parsed.year, parsed.month


def month_bounds(year, month):
    """First and last day of a calendar month."""
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


def next_report_dates(today):
    """Next daily report date and next monthly report date."""
    tomorrow = today + timedelta(days=1)
    year = today.year + (1 if today.month == 12 else 0)
    first_next_month = date(year, today.month % 12 + 1, 1)
    return tomorrow, first_next_month


# ------------------------------------------------------------ file system
def ensure_dir(path):
    try:
        os.makedirs(path, exist_ok=True)
    except OSError as exc:
        raise FileAccessError(
            f"cannot create directory {path}: {exc.strerror}") from exc


def write_lines(path, lines):
    """Write an iterable of lines atomically; returns the number written."""
    ensure_dir(os.path.dirname(path) or ".")
    tmp_path = path + ".tmp"
    count = 0
    try:
        with open(tmp_path, "w", encoding="utf-8", newline="\n") as handle:
            for line in lines:
                handle.write(line + "\n")
                count += 1
        os.replace(tmp_path, path)
    except OSError as exc:
        raise FileAccessError(f"cannot write {path}: {exc.strerror}") from exc
    return count
