"""
FastAPI version of the SaaS Finance Module for Barbearia

File: saas_finance_api.py

Features:
- FastAPI app exposing REST endpoints for managing barbers, services, transactions and expenses.
- Endpoints to get aggregated reports (daily, weekly, monthly) and to download CSV reports.
- Uses SQLite for persistence (same schema as the previous module).
- Pydantic models for request validation.
- CORS enabled for frontend integration.
"""
from __future__ import annotations
from fastapi import FastAPI, HTTPException, Depends, Query, Body
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime, date
import sqlite3
import os
import csv
from collections import defaultdict

DB_PATH = os.environ.get('SAAS_FINANCE_DB', 'saas_finance_api.db')

# -----------------
# DB init (same schema)
# -----------------
def ensure_db(db_path: str = DB_PATH):
    init_needed = not os.path.exists(db_path)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS barbers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            commission_type TEXT,
            commission_value REAL
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS services (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            base_price REAL NOT NULL
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            barber_id INTEGER,
            service_id INTEGER,
            price REAL,
            payment_method TEXT,
            timestamp TEXT,
            note TEXT
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            description TEXT,
            category TEXT,
            amount REAL,
            timestamp TEXT
        )
    ''')
    conn.commit()
    conn.close()

ensure_db()

# -----------------
# Pydantic models
# -----------------
class BarberIn(BaseModel):
    name: str = Field(..., example="João")
    commission_type: Optional[str] = Field(None, example="percent")
    commission_value: Optional[float] = Field(None, example=30.0)

class ServiceIn(BaseModel):
    name: str = Field(..., example="Corte simples")
    base_price: float = Field(..., example=30.0)

class TransactionIn(BaseModel):
    barber_id: int = Field(..., example=1)
    service_id: int = Field(..., example=1)
    price: Optional[float] = Field(None, example=35.0)
    payment_method: Optional[str] = Field('cash', example='pix')
    timestamp: Optional[datetime] = None
    note: Optional[str] = None

class ExpenseIn(BaseModel):
    description: str
    category: Optional[str] = 'other'
    amount: float
    timestamp: Optional[datetime] = None

# -----------------
# App init
# -----------------
app = FastAPI(title='SaaS Finance API - Barbearia')
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Utility DB connection
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# -----------------
# CRUD endpoints
# -----------------
@app.post('/barbers', status_code=201)
def create_barber(b: BarberIn):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('INSERT INTO barbers (name, commission_type, commission_value) VALUES (?, ?, ?)',
                (b.name, b.commission_type, b.commission_value))
    conn.commit()
    barber_id = cur.lastrowid
    conn.close()
    return {'id': barber_id}

@app.post('/services', status_code=201)
def create_service(s: ServiceIn):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('INSERT INTO services (name, base_price) VALUES (?, ?)', (s.name, float(s.base_price)))
    conn.commit()
    sid = cur.lastrowid
    conn.close()
    return {'id': sid}

@app.post('/transactions', status_code=201)
def create_transaction(t: TransactionIn):
    ts = t.timestamp or datetime.now()
    price = t.price
    if price is None:
        # fetch service base price
        conn = get_conn()
        cur = conn.cursor()
        cur.execute('SELECT base_price FROM services WHERE id = ?', (t.service_id,))
        row = cur.fetchone()
        conn.close()
        if not row:
            raise HTTPException(status_code=400, detail='service_id not found and no price provided')
        price = float(row['base_price'])
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('INSERT INTO transactions (barber_id, service_id, price, payment_method, timestamp, note) VALUES (?, ?, ?, ?, ?, ?)',
                (t.barber_id, t.service_id, float(price), t.payment_method, ts.isoformat(), t.note))
    conn.commit()
    tid = cur.lastrowid
    conn.close()
    return {'id': tid}

@app.post('/expenses', status_code=201)
def create_expense(e: ExpenseIn):
    ts = e.timestamp or datetime.now()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('INSERT INTO expenses (description, category, amount, timestamp) VALUES (?, ?, ?, ?)',
                (e.description, e.category, float(e.amount), ts.isoformat()))
    conn.commit()
    eid = cur.lastrowid
    conn.close()
    return {'id': eid}

# -----------------
# Reporting helpers
# -----------------

def _in_period(ts: datetime, period: str, reference_date: date) -> bool:
    if period == 'daily':
        return ts.date() == reference_date
    elif period == 'weekly':
        return ts.isocalendar()[:2] == reference_date.isocalendar()[:2]
    elif period == 'monthly':
        return (ts.year, ts.month) == (reference_date.year, reference_date.month)
    else:
        raise ValueError('period must be daily, weekly or monthly')


def _load_transactions_for_period(period: str, reference_date: date) -> List[Dict[str, Any]]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('SELECT id, barber_id, service_id, price, payment_method, timestamp, note FROM transactions')
    rows = cur.fetchall()
    conn.close()
    results = []
    for r in rows:
        ts = datetime.fromisoformat(r['timestamp'])
        if _in_period(ts, period, reference_date):
            results.append({
                'id': r['id'], 'barber_id': r['barber_id'], 'service_id': r['service_id'], 'price': r['price'],
                'payment_method': r['payment_method'], 'timestamp': datetime.fromisoformat(r['timestamp']), 'note': r['note']
            })
    return results


def _load_expenses_for_period(period: str, reference_date: date) -> List[Dict[str, Any]]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('SELECT id, description, category, amount, timestamp FROM expenses')
    rows = cur.fetchall()
    conn.close()
    results = []
    for r in rows:
        ts = datetime.fromisoformat(r['timestamp'])
        if _in_period(ts, period, reference_date):
            results.append({'id': r['id'], 'description': r['description'], 'category': r['category'], 'amount': r['amount'], 'timestamp': datetime.fromisoformat(r['timestamp'])})
    return results


def _calculate_commissions(transactions: List[Dict[str, Any]], default_percent: float = 30.0) -> Dict[int, float]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('SELECT id, commission_type, commission_value FROM barbers')
    rows = cur.fetchall()
    conn.close()
    barber_settings = {r['id']: (r['commission_type'], r['commission_value']) for r in rows}

    commissions = defaultdict(float)
    for t in transactions:
        bid = t['barber_id']
        price = float(t['price'])
        setting = barber_settings.get(bid, (None, None))
        if setting[0] == 'percent' and setting[1] is not None:
            pct = float(setting[1])
            commissions[bid] += price * (pct / 100.0)
        elif setting[0] == 'fixed' and setting[1] is not None:
            commissions[bid] += float(setting[1])
        else:
            commissions[bid] += price * (default_percent / 100.0)
    return dict(commissions)

# -----------------
# Report endpoints
# -----------------
@app.get('/report')
def get_report(period: str = Query('monthly', regex='^(daily|weekly|monthly)$'),
               reference_date: Optional[date] = Query(None, description='YYYY-MM-DD')):
    if reference_date is None:
        reference_date = date.today()
    txs = _load_transactions_for_period(period, reference_date)
    exps = _load_expenses_for_period(period, reference_date)

    counts = defaultdict(int)
    totals = defaultdict(float)
    totals_by_service = defaultdict(float)
    total_revenue = 0.0
    for t in txs:
        counts[t['barber_id']] += 1
        totals[t['barber_id']] += float(t['price'])
        totals_by_service[t['service_id']] += float(t['price'])
        total_revenue += float(t['price'])

    total_expenses = sum(float(e['amount']) for e in exps)
    net_profit = total_revenue - total_expenses
    commissions_due = _calculate_commissions(txs)

    return {
        'period': period,
        'reference_date': str(reference_date),
        'counts_by_barber': dict(counts),
        'totals_by_barber': dict(totals),
        'totals_by_service': dict(totals_by_service),
        'total_revenue': total_revenue,
        'total_expenses': total_expenses,
        'net_profit': net_profit,
        'commissions_due': commissions_due,
        'transactions': txs,
        'expenses': exps
    }

@app.get('/export_csv')
def export_csv(period: str = Query('monthly', regex='^(daily|weekly|monthly)$'), reference_date: Optional[date] = Query(None)):
    if reference_date is None:
        reference_date = date.today()
    report = get_report(period, reference_date)
    path = f'report_{period}_{reference_date}.csv'
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['BARBER_ID', 'CUTS', 'TOTAL'])
        for bid, cuts in report['counts_by_barber'].items():
            writer.writerow([bid, cuts, f"{report['totals_by_barber'].get(bid, 0.0):.2f}"])
        writer.writerow([])
        writer.writerow(['SERVICE_ID', 'TOTAL'])
        for sid, total in report['totals_by_service'].items():
            writer.writerow([sid, f"{total:.2f}"])
        writer.writerow([])
        writer.writerow(['TOTAL_REVENUE', f"{report['total_revenue']:.2f}"])
        writer.writerow(['TOTAL_EXPENSES', f"{report['total_expenses']:.2f}"])
        writer.writerow(['NET_PROFIT', f"{report['net_profit']:.2f}"])
    return FileResponse(path, filename=os.path.basename(path), media_type='text/csv')

@app.get('/health')
def health():
    return {'status': 'ok'}
