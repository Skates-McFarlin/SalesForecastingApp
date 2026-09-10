"""Catalog ingestion - Phase 0b.

Turns an upload into persistent state: parse the file (reusing the existing
spreadsheet parser) and UPSERT it into the `product` catalog and daily
`sales_record` history. Dedupe is by (product, date), so re-syncing an
overlapping window updates rows instead of duplicating them - the basis for
incremental "sync new sales" instead of re-uploading everything each run.
"""
import json
import re
from collections import defaultdict
from datetime import datetime

import pandas as pd

from app.extensions import db
from app.models.product import Product
from app.models.sales_record import SalesRecord
from app.controllers.prediction_controller import preprocess_data, _read_rows

SKU_COLUMN = "Product ID (SKU)"


# Accepted header aliases for a long/transactional feed (case-insensitive), so
# a Shopify/Square/POS export or the simulator's output all import cleanly.
_ALIASES = {
    "sku": ["product id (sku)", "sku", "product id", "variant sku", "item"],
    "name": ["product name", "name", "product", "title", "item name"],
    "date": ["date", "day", "order date", "week"],
    "qty": ["quantity", "qty", "units", "units sold", "quantity sold"],
    "price": ["unit price", "price", "unit_price"],
    "category": ["category", "type", "product type"],
    # Inventory state & economics (Phase 2) - picked up from the file when present.
    "on_hand": ["on hand", "on_hand", "stock", "stock on hand", "quantity on hand",
                "qoh", "inventory", "inventory on hand"],
    "unit_cost": ["unit cost", "unit_cost", "cost", "cogs", "cost price"],
    "lead_time": ["lead time", "lead_time_days", "lead time (days)",
                  "lead time days", "leadtime"],
}


def _resolve_columns(headers):
    lower = {h.lower(): h for h in headers}
    picked = {}
    for field, names in _ALIASES.items():
        for n in names:
            if n in lower:
                picked[field] = lower[n]
                break
    return picked


def _long_to_json(rows, headers):
    """Parse a long/transactional file - one row per SKU-date - into the same
    shape preprocess_data emits, so ingestion is grain-agnostic. Columns are
    matched by alias (Date/Quantity required; SKU, Name, Category, Unit Price
    optional) - the natural shape of a daily feed (Shopify, Square, a POS)."""
    col = _resolve_columns(headers)
    json_data, extra = [], {}
    for row in rows:
        name = (row.get(col.get("name", ""), "") or "").strip()
        sku = (row.get(col.get("sku", ""), "") or "").strip()
        key = sku or name
        if not key:
            continue
        try:
            ds = pd.to_datetime(row[col["date"]]).strftime("%Y-%m-%d")
            qty = float(row.get(col.get("qty", ""), 0) or 0)
        except (ValueError, KeyError, TypeError):
            continue
        price = row.get(col.get("price", ""))
        json_data.append({"ds": ds, "y": qty, "product_name": name or key,
                          "sku": sku, "price": price})
        if key not in extra:
            cat = (row.get(col.get("category", ""), "") or "").strip()
            extra[key] = {"Category": cat} if cat else {}
    return json_data, extra


def _to_price(value):
    try:
        p = float(value)
        return p if p == p else None  # drop NaN
    except (TypeError, ValueError):
        return None


def _capture_inventory(rows, col):
    """Pull per-product inventory fields (on-hand, unit cost, lead time) out of a
    file that carries them - a POS/inventory export usually has on-hand and cost.
    Returns {product key: {on_hand, unit_cost, lead_time_days}} with the last
    non-empty value seen per product (these repeat per row in a long feed)."""
    if not any(k in col for k in ("on_hand", "unit_cost", "lead_time", "price")):
        return {}
    casters = {"on_hand": float, "unit_cost": float, "price": float,
               "lead_time_days": lambda x: int(float(x))}
    src = {"on_hand": "on_hand", "unit_cost": "unit_cost", "price": "price",
           "lead_time_days": "lead_time"}
    out = {}
    for row in rows:
        name = (row.get(col.get("name", ""), "") or "").strip()
        sku = (row.get(col.get("sku", ""), "") or "").strip()
        key = sku or name
        if not key:
            continue
        vals = out.get(key, {})
        for field, src_field in src.items():
            if src_field in col:
                raw = row.get(col[src_field], "")
                if raw not in ("", None):
                    try:
                        vals[field] = casters[field](raw)
                    except (ValueError, TypeError):
                        pass
        if vals:
            out[key] = vals
    return out


def import_sales(file):
    """Parse an uploaded sales file and merge it into the catalog.

    Returns a summary of what changed so the UI can confirm the sync. Accepts
    both a long/transactional file (Date + Quantity columns - daily-capable) and
    the wide monthly spreadsheet ("Quantity Sold {Mon} {Year}" columns).
    """
    rows, headers = _read_rows(file)
    col = _resolve_columns(headers)
    inv_by_key = _capture_inventory(rows, col)  # on-hand/cost/lead-time if present
    if "date" in col and "qty" in col:  # a long/transactional (daily) feed
        json_data, extra_context_by_group = _long_to_json(rows, headers)
    else:  # the wide monthly spreadsheet
        file.stream.seek(0)
        json_data, extra_context_by_group = preprocess_data(file)

    # Group the flat rows by product identity (SKU when present, else name) and
    # capture each product's display meta from the first row we see for it.
    rows_by_key = defaultdict(list)
    meta_by_key = {}
    for r in json_data:
        name = r.get("product_name") or ""
        sku = (r.get("sku") or "").strip()
        key = sku or name
        if not key:
            continue
        rows_by_key[key].append(r)
        if key not in meta_by_key:
            meta_by_key[key] = {"name": name, "sku": sku or None}

    stats = {
        "products_added": 0, "products_updated": 0,
        "records_added": 0, "records_updated": 0,
    }
    all_dates = []

    existing = {
        p.key: p
        for p in Product.query.filter(Product.key.in_(list(rows_by_key.keys()))).all()
    }

    for key, rows in rows_by_key.items():
        extra = dict(extra_context_by_group.get(key, {}))
        category = extra.pop("Category", None) or None
        attributes = json.dumps(extra) if extra else None

        product = existing.get(key)
        if product is None:
            product = Product(
                key=key, sku=meta_by_key[key]["sku"], name=meta_by_key[key]["name"],
                category=category, attributes=attributes,
            )
            db.session.add(product)
            db.session.flush()  # assign product.id for the sales rows below
            stats["products_added"] += 1
        else:
            changed = False
            for field, value in (("name", meta_by_key[key]["name"]),
                                 ("category", category), ("attributes", attributes)):
                if value is not None and getattr(product, field) != value:
                    setattr(product, field, value)
                    changed = True
            if changed:
                stats["products_updated"] += 1

        # Apply any inventory fields the file carried for this product.
        inv = inv_by_key.get(key)
        if inv:
            for field, value in inv.items():
                setattr(product, field, value)
            if "on_hand" in inv:
                product.inventory_updated_at = datetime.utcnow()

        existing_records = {
            sr.date: sr for sr in SalesRecord.query.filter_by(product_id=product.id).all()
        }
        for r in rows:
            d = datetime.strptime(r["ds"], "%Y-%m-%d").date()
            qty = float(r.get("y") or 0.0)
            price = _to_price(r.get("price"))
            all_dates.append(d)

            record = existing_records.get(d)
            if record is None:
                record = SalesRecord(product_id=product.id, date=d, quantity=qty, unit_price=price)
                db.session.add(record)
                existing_records[d] = record  # so a repeat date in this file updates, not re-inserts
                stats["records_added"] += 1
            elif record.quantity != qty or (price is not None and record.unit_price != price):
                record.quantity = qty
                if price is not None:
                    record.unit_price = price
                stats["records_updated"] += 1

    db.session.commit()

    if all_dates:
        stats["date_from"] = min(all_dates).isoformat()
        stats["date_to"] = max(all_dates).isoformat()
    stats["catalog_size"] = Product.query.count()

    # Newly synced sales may now cover a past forecast's window - grade those
    # runs against what actually sold (Phase 1 ledger). Best-effort.
    try:
        from app.controllers.ledger_controller import reconcile_runs
        stats["runs_reconciled"] = reconcile_runs()
    except Exception:  # noqa: BLE001
        pass

    return stats


def detect_grain():
    """WEEKLY when the catalog holds sub-monthly (daily) data, else MONTHLY.

    Monthly imports store one row per month dated to the 1st, so if every stored
    date is a 1st, the data is monthly; any other day means it's daily-capable
    and we forecast a weekly rate (the operational grain)."""
    from app.forecasting.base import MONTHLY, WEEKLY
    non_first = (
        db.session.query(SalesRecord.id)
        .filter(db.func.strftime("%d", SalesRecord.date) != "01")
        .first()
    )
    return WEEKLY if non_first else MONTHLY


def forecast_origin(grain=None):
    """The first period a forward forecast will cover: the period immediately
    after the catalog's last period, on the grain's grid.

    This is where the engine ACTUALLY forecasts from (the statistical/foundation
    members forecast the periods after each series' last observation), so the app
    anchors here rather than trusting a picked start date - that mismatch is what
    made a non-edge start silently return "the next N periods" relabeled. Returns
    a date, or None when the catalog has no history yet.
    """
    from app.forecasting.base import WEEKLY
    if grain is None:
        grain = detect_grain()
    last = db.session.query(db.func.max(SalesRecord.date)).scalar()
    if last is None:
        return None
    last_ts = pd.Timestamp(last)
    if grain is WEEKLY:
        # Match catalog_to_json_data's weekly resample: buckets end on Sunday.
        last_period = last_ts.to_period("W-SUN").end_time.normalize()
    else:
        last_period = last_ts.to_period("M").start_time
    return pd.date_range(start=last_period, periods=2, freq=grain.freq)[1].date()


def catalog_to_json_data(grain=None):
    """Reconstruct the parser's output shape from the stored catalog, resampled
    to the forecasting grain, so the existing pipeline runs over the DB with no
    changes to it. Returns (json_data, extra_context_by_group, grain).

    Daily data is resampled to a weekly rate (summed by week-ending Sunday, to
    match WEEKLY.freq); monthly data passes through as-is.
    """
    from app.forecasting.base import WEEKLY
    if grain is None:
        grain = detect_grain()

    json_data = []
    extra_context_by_group = {}
    for product in Product.query.all():
        ctx = {}
        if product.category:
            ctx["Category"] = product.category
        if product.attributes:
            try:
                ctx.update(json.loads(product.attributes))
            except (ValueError, TypeError):
                pass
        extra_context_by_group[product.key] = ctx

        recs = [(sr.date, sr.quantity, sr.unit_price) for sr in product.sales]
        if not recs:
            continue
        meta = {"product_name": product.name, "sku": product.sku or ""}

        if grain is WEEKLY:
            s = pd.DataFrame(recs, columns=["date", "q", "p"])
            s["date"] = pd.to_datetime(s["date"])
            s["week"] = s["date"].dt.to_period("W-SUN").dt.end_time.dt.normalize()
            agg = s.groupby("week").agg(q=("q", "sum"), p=("p", "mean")).reset_index()
            for _, r in agg.iterrows():
                json_data.append({
                    "ds": r["week"].strftime("%Y-%m-%d"), "y": float(r["q"]),
                    "price": None if pd.isna(r["p"]) else float(r["p"]), **meta,
                })
        else:
            for d, q, p in recs:
                json_data.append({"ds": d.strftime("%Y-%m-%d"), "y": q, "price": p, **meta})

    return json_data, extra_context_by_group, grain


def catalog_summary():
    """A lightweight view of the stored business for the UI to open onto."""
    product_count = Product.query.count()
    if product_count == 0:
        return {"empty": True, "products": 0}

    span = db.session.query(
        db.func.min(SalesRecord.date), db.func.max(SalesRecord.date),
        db.func.count(SalesRecord.id),
    ).one()
    categories = [
        c[0] for c in db.session.query(Product.category)
        .filter(Product.category.isnot(None)).distinct().all()
    ]
    return {
        "empty": False,
        "products": product_count,
        "records": span[2] or 0,
        "date_from": span[0].isoformat() if span[0] else None,
        "date_to": span[1].isoformat() if span[1] else None,
        "categories": sorted(categories),
        "grain": detect_grain().label,
        # Where the next forecast will start (the data's edge + 1 period), so the
        # UI can show the anchor and turn a "forecast through <month>" target into
        # a horizon length.
        "forecast_origin": (lambda o: o.isoformat() if o else None)(forecast_origin()),
    }
