# PyMart Back-Office Toolkit

Command-line toolkit (standard library only, Python 3.8+) that imports messy
POS exports, validates and cleans them, processes orders and writes dated,
archived reports to disk.

## Run

```bash
python -m pymart.cli --help
python -m pymart.cli import --products data/products.txt --customers data/customers.txt --orders data/orders.txt
python -m pymart.cli report --type daily --date 2026-06-30 --out reports/
python -m pymart.cli report --type monthly --month 2026-06 --out reports/
python -m pymart.cli report --type stock   --date 2026-06-30 --out reports/
python -m pymart.cli report --type rejects --date 2026-06-30 --out reports/
python -m pymart.cli report --type all     --date 2026-06-30 --out reports/
python -m pymart.cli orders create --customer C002 --item P001:5 --item P004:1 --date 2026-06-30
python -m pymart.cli orders list --date 2026-06-30
python -m pymart.cli schedule --date 2026-06-30
python -m unittest discover -s tests          # run the tests
```
Run from the project root. `pip install .` also provides a `pymart` command.
State is kept in `.pymart/state.json` (change with `--state`).
Exit codes: 0 OK, 1 import file failed, 2 error (message printed, no traceback).

## Structure

```
pymart/
  exceptions.py  custom exceptions with file:line context
  utils.py       cleaning, number/date parsing, calendar helpers, file writing
  models.py      Product (+Perishable, Digital), Customer (+Individual, Business), Order, OrderLine
  parsers.py     DelimitedFile generator + record builders
  services.py    import services, order creation, order generator
  store.py       data store + JSON persistence
  reports.py     Report base class + Daily, Monthly, Stock, Rejects reports
  cli.py         argparse CLI
data/            sample dirty inputs      sample_reports/  sample outputs
docs/            demo_transcript.txt      tests/           unit tests
```

## Requirement mapping

| Requirement | Where |
|---|---|
| String/list cleaning | `utils.clean_text/split_line/detect_delimiter`, `parsers.py` (strip, split, title-case, replace `,`->`.`, aliases) |
| Custom exceptions + try/except/else/finally | `exceptions.py` (8 classes); `services._run_import` uses try/except/else/finally; `parsers.DelimitedFile` uses finally to close files |
| Inheritance + polymorphism | `Product.price_on / tax_rate / stock_label / has_stock_for`, `Customer.discount_rate / describe` overridden by subclasses |
| Generators | `DelimitedFile.rows`, `Store.orders_sorted`, `services.iter_orders`, `Report.lines/body` |
| File system | `utils.ensure_dir`, atomic `write_lines`, archive `reports/YYYY/MM/<type>_<date>.txt` |
| datetime/calendar | date parsing (4 formats), `calendar.monthrange` for month bounds, daily/monthly filenames, `schedule` command |
| Reproducibility | Reports contain no run-time clock; stable sorting; same state => identical file |

## Business rules

* Perishable: 7 % tax, 30 % off in the last 2 days before expiry, not sellable after expiry.
* Standard / digital: 19 % tax; digital has unlimited stock.
* Business customers get 10 % off the subtotal.
* Imported (historical) orders do not change stock; orders created with `orders create` do.
* Re-importing a file replaces that entity's data and its rejected records.

## Input formats (header required, separator `; , | tab` detected per line)

```
products : product_id;name;category;price;stock;type;expiry_date   (type: standard|perishable|digital)
customers: customer_id,name,email,type,city                         (type: individual|business)
orders   : order_id,order_date,customer_id,product_id,quantity
```
IDs: `P###`, `C###`, `O###` (3-6 digits). Dates: `YYYY-MM-DD`, `DD/MM/YYYY`, `DD-MM-YYYY`.
Limitation: quoted fields containing the separator are not supported.
