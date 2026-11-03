"""
Минимальный API для админки из admin_dist/index.html.
Работает с той же базой shop.db, что и бот, и даёт страницы + обработчики форм.

Запуск:
    python api.py

По умолчанию слушает 127.0.0.1:5000.
GitHub Pages ставить не нужно — это отдельный сервер для форм и БД.
Статика из admin_dist/index.html может лежать на GitHub Pages,
а api.py крутиться отдельно на сервере/хостинге с Python и shop.db.
"""

import json
import os
import secrets
import sqlite3
import time
import urllib.request
from datetime import datetime

from flask import Flask, g, jsonify, request

DB_PATH = os.getenv("DB_PATH", "shop.db")
TOKEN = os.getenv("BOT_TOKEN", "8341160507:AAHT4k1nWZzYEeCfpeejTbc3dvgmDeaJQWg")
PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY") or secrets.token_hex(32)
app.config.update(SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_HTTPONLY=True)

DEFAULTS = {
    "greeting": "Привет {name}! Ты попал в магазин Grand SAMP Shop. Тут ты можешь приобрести донат, виртуальную валюту и многое многое другое 🔥",
    "shop_name": "Grand SAMP shop",
    "created": "2025-11-07",
    "chat_url": "https://t.me/your_chat",
    "channel_url": "https://t.me/your_channel",
    "rules_url": "https://t.me/your_channel/3",
    "support": "@grandsampsupport_bot",
    "service_text": "Бот создан на Python + aiogram 3.",
    "ref_bonus": "5",
}
LABELS = {
    "greeting": "Приветствие (/start), {name} — имя пользователя",
    "shop_name": "Название магазина",
    "created": "Дата создания",
    "chat_url": "Ссылка на чат",
    "channel_url": "Ссылка на канал",
    "rules_url": "Ссылка на правила",
    "support": "Бот поддержки",
    "service_text": "Текст «О сервисе»",
    "ref_bonus": "Бонус за реферала (⭐)",
}
STATUS = {"new": "🆕 Новый", "done": "✅ Выдан", "refunded": "↩️ Возврат"}
NAV = [
    ("/", "📊 Главная"),
    ("/users", "👥 Пользователи"),
    ("/orders", "🧾 Заказы"),
    ("/categories", "📖 Категории"),
    ("/products", "🛒 Товары"),
    ("/coupons", "🎟 Купоны"),
    ("/topups", "💰 Пополнения"),
    ("/broadcast", "📢 Рассылка"),
    ("/settings", "⚙️ Настройки"),
]


def connect_db(path=None):
    db = sqlite3.connect(path or DB_PATH, timeout=10)
    db.row_factory = sqlite3.Row
    return db


def ensure_schema(path=None):
    c = sqlite3.connect(path or DB_PATH)
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, name TEXT, balance INTEGER DEFAULT 0, referrer INTEGER, created TEXT);
    CREATE TABLE IF NOT EXISTS categories(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE);
    CREATE TABLE IF NOT EXISTS products(id INTEGER PRIMARY KEY AUTOINCREMENT, category_id INTEGER, name TEXT, price INTEGER, stock INTEGER DEFAULT 999);
    CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, product TEXT, price INTEGER, date TEXT);
    CREATE TABLE IF NOT EXISTS topups(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, amount INTEGER, date TEXT);
    CREATE TABLE IF NOT EXISTS coupons(code TEXT PRIMARY KEY, amount INTEGER, uses_left INTEGER);
    CREATE TABLE IF NOT EXISTS used_coupons(user_id INTEGER, code TEXT);
    CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
    """)
    try:
        c.execute("ALTER TABLE orders ADD COLUMN status TEXT DEFAULT 'new'")
    except sqlite3.OperationalError:
        pass
    c.commit()
    c.close()


def to_int(v, default=0):
    try:
        return int(str(v).strip())
    except ValueError:
        return default


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def setting(key):
    db = connect_db()
    r = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    db.close()
    return r["value"] if r else DEFAULTS[key]


def ref_bonus():
    try:
        return int(setting("ref_bonus"))
    except ValueError:
        return 0


def tg(method, **data):
    if not TOKEN:
        return {"ok": False, "error": "BOT_TOKEN не задан"}
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{TOKEN}/{method}",
        data=json.dumps(data).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.load(resp)
    except Exception as e:
        return {"ok": False, "error": str(e)}


def notify(uid, text):
    return tg("sendMessage", chat_id=uid, text=text).get("ok", False)


@app.before_request
def guard():
    if request.path in ("/api/login", "/api/static", "/"):
        return
    if not session.get("auth"):
        return jsonify({"redirect": "/api/login"})
    if request.method == "POST":
        sent = request.form.get("_csrf", "")
        if not secrets.compare_digest(sent, session.get("csrf", "x")):
            return jsonify({"error": "Ошибка CSRF, обновите страницу"})


@app.route("/api/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        time.sleep(0.5)
        if secrets.compare_digest(request.form.get("password", ""), PASSWORD):
            session.clear()
            session["auth"] = True
            session["csrf"] = secrets.token_hex(16)
            return jsonify({"redirect": "/"})
        return jsonify({"error": "Неверный пароль"})
    return jsonify({"html": tmpl_login(session.get("csrf", secrets.token_hex(16)))})


@app.route("/api/logout")
def logout():
    session.clear()
    return jsonify({"redirect": "/api/login"})


@app.route("/api/")
def index_page():
    if not session.get("auth"):
        return jsonify({"redirect": "/api/login"})
    s = dict(
        users=db().execute("SELECT COUNT(*) c FROM users").fetchone()["c"],
        orders=db().execute("SELECT COUNT(*) c FROM orders").fetchone()["c"],
        new=db().execute("SELECT COUNT(*) c FROM orders WHERE status='new'").fetchone()["c"],
        revenue=db().execute("SELECT COALESCE(SUM(price),0) c FROM orders WHERE status!='refunded'").fetchone()["c"],
        topups=db().execute("SELECT COALESCE(SUM(amount),0) c FROM topups").fetchone()["c"],
        balances=db().execute("SELECT COALESCE(SUM(balance),0) c FROM users").fetchone()["c"],
    )
    recent = db().execute(
        "SELECT o.*, u.name FROM orders o LEFT JOIN users u ON u.id=o.user_id ORDER BY o.id DESC LIMIT 10"
    ).fetchall()
    return jsonify({"html": tmpl_index(s, recent)})


@app.route("/api/users")
def users_page():
    term = request.args.get("q", "").strip()
    db = connect_db()
    if term:
        rows = db.execute(
            "SELECT * FROM users WHERE CAST(id AS TEXT) LIKE ? OR name LIKE ? ORDER BY created DESC LIMIT 200",
            f"%{term}%",
            f"%{term}%",
        ).fetchall()
    else:
        rows = db.execute("SELECT * FROM users ORDER BY created DESC LIMIT 200").fetchall()
    db.close()
    return jsonify({"html": tmpl_users(rows, term)})


@app.route("/api/users/<int:uid>")
def user_page(uid):
    db = connect_db()
    u = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not u:
        db.close()
        return jsonify({"error": "Пользователь не найден", "redirect": "/api/users"})
    orders = db.execute("SELECT * FROM orders WHERE user_id=? ORDER BY id DESC LIMIT 50", (uid,)).fetchall()
    topups = db.execute("SELECT * FROM topups WHERE user_id=? ORDER BY id DESC LIMIT 50", (uid,)).fetchall()
    refs = db.execute("SELECT COUNT(*) c FROM users WHERE referrer=?", (uid,)).fetchone()["c"]
    db.close()
    return jsonify({"html": tmpl_user(u, orders, topups, refs)})


@app.route("/api/users/<int:uid>/balance", methods=["POST"])
def user_balance(uid):
    mode = request.form.get("mode")
    amount = to_int(request.form.get("amount"))
    db = connect_db()
    if mode == "set":
        db.execute("UPDATE users SET balance=? WHERE id=?", (amount, uid))
    else:
        db.execute("UPDATE users SET balance=balance+? WHERE id=?", (amount, uid))
        if amount > 0:
            db.execute(
                "INSERT INTO topups(user_id,amount,date) VALUES(?,?,?)",
                (uid, amount, now() + " (выдано админом)"),
            )
    db.commit()
    if request.form.get("notify") and amount:
        notify(uid, f"💰 Администратор изменил ваш баланс: {amount:+}⭐")
    db.close()
    return jsonify({"flash": f"Баланс изменён на {amount:+}⭐"})


@app.route("/api/users/<int:uid>/name", methods=["POST"])
def user_name(uid):
    name = request.form.get("name", "").strip()
    db = connect_db()
    db.execute("UPDATE users SET name=? WHERE id=?", (name, uid))
    db.commit()
    db.close()
    return jsonify({"flash": "Имя обновлено"})


@app.route("/api/users/<int:uid>/msg", methods=["POST"])
def user_msg(uid):
    ok = notify(uid, request.form.get("text", ""))
    return jsonify({
        "flash": "Сообщение отправлено ✅" if ok else "Не удалось отправить"
    })


@app.route("/api/users/<int:uid>/give", methods=["POST"])
def user_give(uid):
    pid = to_int(request.form.get("product_id"))
    db = connect_db()
    p = db.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
    if not p:
        db.close()
        return jsonify({"error": "Товар не найден"})
    db.execute("INSERT INTO orders(user_id,product,price,date,status) VALUES(?,?,?,?,'done')",
               (uid, p["name"], 0, now()))
    db.commit()
    if request.form.get("notify"):
        notify(uid, f"🎁 Вам выдан товар: {p['name']}")
    db.close()
    return jsonify({"flash": f"Выдано: {p['name']}", "redirect": f"/api/users/{uid}"})


@app.route("/api/users/<int:uid>/delete", methods=["POST"])
def user_delete(uid):
    db = connect_db()
    db.execute("DELETE FROM users WHERE id=?", (uid,))
    db.commit()
    db.close()
    return jsonify({"flash": "Пользователь удалён", "redirect": "/api/users"})


@app.route("/api/orders")
def orders_page():
    st = request.args.get("status", "")
    db = connect_db()
    sql = "SELECT o.*, u.name FROM orders o LEFT JOIN users u ON u.id=o.user_id"
    if st:
        rows = db.execute(sql + " WHERE o.status=? ORDER BY o.id DESC LIMIT 300", (st,)).fetchall()
    else:
        rows = db.execute(sql + " ORDER BY o.id DESC LIMIT 300").fetchall()
    db.close()
    return jsonify({"html": tmpl_orders(rows, st)})


@app.route("/api/orders/<int:oid>/<action>", methods=["POST"])
def order_action(oid, action):
    o = db().execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
    if not o:
        return jsonify({"error": "Заказ не найден"})
    if action == "done":
        db().execute("UPDATE orders SET status='done' WHERE id=?", (oid,))
        db().commit()
        notify(o["user_id"], f"✅ Ваш заказ #{oid} ({o['product']}) выдан. Спасибо за покупку!")
        return jsonify({"flash": f"Заказ #{oid} отмечен как выданный, клиент уведомлён"})
    if action == "refund" and o["status"] != "refunded":
        db().execute("UPDATE users SET balance=balance+? WHERE id=?", (o["price"], o["user_id"]))
        db().execute("UPDATE orders SET status='refunded' WHERE id=?", (oid,))
        db().commit()
        notify(o["user_id"], f"↩️ Заказ #{oid} отменён, {o['price']}⭐ возвращены на баланс.")
        return jsonify({"flash": f"Заказ #{oid}: возврат {o['price']}⭐"})
    if action == "delete":
        db().execute("DELETE FROM orders WHERE id=?", (oid,))
        db().commit()
        return jsonify({"flash": f"Заказ #{oid} удалён"})
    return jsonify({"error": "Неизвестное действие"})


@app.route("/api/categories", methods=["GET", "POST"])
def categories_page():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if name:
            try:
                db().execute("INSERT INTO categories(name) VALUES(?)", (name,))
                db().commit()
            except sqlite3.IntegrityError:
                return jsonify({"error": "Такая категория уже есть"})
        return jsonify({"redirect": "/api/categories"})
    rows = db().execute(
        "SELECT c.*, (SELECT COUNT(*) FROM products p WHERE p.category_id=c.id) cnt FROM categories c ORDER BY c.id"
    ).fetchall()
    return jsonify({"html": tmpl_categories(rows)})


@app.route("/api/categories/<int:cid>/rename", methods=["POST"])
def category_rename(cid):
    name = request.form.get("name", "").strip()
    db().execute("UPDATE categories SET name=? WHERE id=?", (name, cid))
    db().commit()
    return jsonify({"flash": "Категория переименована"})


@app.route("/api/categories/<int:cid>/delete", methods=["POST"])
def category_delete(cid):
    db().execute("DELETE FROM products WHERE category_id=?", (cid,))
    db().execute("DELETE FROM categories WHERE id=?", (cid,))
    db().commit()
    return jsonify({"flash": "Категория и её товары удалены"})


@app.route("/api/products", methods=["GET", "POST"])
def products_page():
    if request.method == "POST":
        db().execute(
            "INSERT INTO products(category_id,name,price,stock) VALUES(?,?,?,?)",
            (
                to_int(request.form.get("category_id")),
                request.form.get("name", "").strip(),
                to_int(request.form.get("price")),
                to_int(request.form.get("stock"), 999),
            ),
        )
        db().commit()
        return jsonify({"redirect": "/api/products"})
    cats = db().execute("SELECT * FROM categories ORDER BY id").fetchall()
    rows = db().execute(
        "SELECT p.*, c.name cat FROM products p LEFT JOIN categories c ON c.id=p.category_id ORDER BY c.id, p.id"
    ).fetchall()
    return jsonify({"html": tmpl_products(rows, cats)})


@app.route("/api/products/<int:pid>/edit", methods=["POST"])
def product_edit(pid):
    db().execute(
        "UPDATE products SET category_id=?, name=?, price=?, stock=? WHERE id=?",
        (
            to_int(request.form.get("category_id")),
            request.form.get("name", "").strip(),
            to_int(request.form.get("price")),
            to_int(request.form.get("stock")),
            pid,
        ),
    )
    db().commit()
    return jsonify({"flash": "Товар сохранён"})


@app.route("/api/products/<int:pid>/delete", methods=["POST"])
def product_delete(pid):
    db().execute("DELETE FROM products WHERE id=?", (pid,))
    db().commit()
    return jsonify({"flash": "Товар удалён"})


@app.route("/api/coupons", methods=["GET", "POST"])
def coupons_page():
    if request.method == "POST":
        code = request.form.get("code", "").strip().upper()
        if code:
            db().execute(
                "INSERT OR REPLACE INTO coupons(code,amount,uses_left) VALUES(?,?,?)",
                (
                    code,
                    to_int(request.form.get("amount")),
                    to_int(request.form.get("uses")),
                ),
            )
            db().commit()
        return jsonify({"redirect": "/api/coupons"})
    rows = db().execute(
        "SELECT c.*, (SELECT COUNT(*) FROM used_coupons u WHERE u.code=c.code) used FROM coupons c ORDER BY c.code"
    ).fetchall()
    return jsonify({"html": tmpl_coupons(rows)})


@app.route("/api/coupons/<code>/delete", methods=["POST"])
def coupon_delete(code):
    db().execute("DELETE FROM coupons WHERE code=?", (code,))
    db().commit()
    return jsonify({"flash": "Купон удалён"})


@app.route("/api/topups")
def topups_page():
    rows = db().execute(
        "SELECT t.*, u.name FROM topups t LEFT JOIN users u ON u.id=t.user_id ORDER BY t.id DESC LIMIT 300"
    ).fetchall()
    return jsonify({"html": tmpl_topups(rows)})


@app.route("/api/broadcast", methods=["GET", "POST"])
def broadcast_page():
    result = None
    if request.method == "POST":
        text = request.form.get("text", "").strip()
        if text:
            ok = fail = 0
            for u in db().execute("SELECT id FROM users").fetchall():
                if notify(u["id"], text):
                    ok += 1
                else:
                    fail += 1
                time.sleep(0.05)
            result = f"Отправлено: {ok}, не доставлено: {fail}"
    total = db().execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
    return jsonify({"html": tmpl_broadcast(total, result)})


@app.route("/api/settings", methods=["GET", "POST"])
def settings_page():
    if request.method == "POST":
        for k in DEFAULTS:
            if k in request.form:
                db().execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)\", k, request.form[k])
        db().commit()
        return jsonify({"flash": "Настройки сохранены", "redirect": "/api/settings"})
    items = [(k, LABELS[k], setting(k)) for k in DEFAULTS]
    return jsonify({"html": tmpl_settings(items)})


# ---------- шаблоны (минимальные, без навигации, чтобы API отдавал готовую страницу) ----------
def csrf_session():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]


def tmpl_login(csrf):
    return f"""
<form method="post" action="/api/login" class="card p-4" style="width:320px;background:#1d2018;margin:0 auto">
<h4 class="mb-3 text-center">🔐 Админ-панель</h4>
<input type="hidden" name="_csrf" value="{csrf}">
<input type="password" name="password" class="form-control mb-3" placeholder="Пароль" autofocus required>
<button class="btn btn-success w-100">Войти</button>
</form>"""


def tmpl_index(s, recent):
    recentRows = "".join(
        f'<tr><td>{o["id"]}</td><td><a href="/api/users/{o["user_id"]}">{o["name"] or o["user_id"]}</a></td>'
        f'<td>{o["product"]}</td><td>{o["price"]}⭐</td><td>{o["date"]}</td>'
        f'<td>{STATUS.get(o["status"], o["status"])}</td></tr>'
        for o in recent
    )
    return f"""
<h4>📊 Статистика</h4>
<div class="row g-3 mb-4">
<div class="col-6 col-md-4 col-xl-2"><div class="card p-3"><div class="text-secondary small">Пользователей</div><div class="fs-3">{s['users']}</div></div></div>
<div class="col-6 col-md-4 col-xl-2"><div class="card p-3"><div class="text-secondary small">Заказов всего</div><div class="fs-3">{s['orders']}</div></div></div>
<div class="col-6 col-md-4 col-xl-2"><div class="card p-3"><div class="text-secondary small">Новых заказов</div><div class="fs-3">{s['new']}</div></div></div>
<div class="col-6 col-md-4 col-xl-2"><div class="card p-3"><div class="text-secondary small">Выручка, ⭐</div><div class="fs-3">{s['revenue']}</div></div></div>
<div class="col-6 col-md-4 col-xl-2"><div class="card p-3"><div class="text-secondary small">Пополнений, ⭐</div><div class="fs-3">{s['topups']}</div></div></div>
<div class="col-6 col-md-4 col-xl-2"><div class="card p-3"><div class="text-secondary small">Балансы юзеров, ⭐</div><div class="fs-3">{s['balances']}</div></div></div>
</div>
<h5>Последние заказы</h5>
<div class="table-responsive"><table class="table table-sm align-middle">
<tr><th>#</th><th>Клиент</th><th>Товар</th><th>Цена</th><th>Дата</th><th>Статус</th></tr>
{recentRows}
</table></div>"""


def tmpl_users(rows, term):
    body = "".join(
        f'<tr><td>{u["id"]}</td><td>{u["name"]}</td><td>{u["balance"]}⭐</td>'
        f'<td>{u["created"]}</td>'
        f'<td><a class="btn btn-sm btn-outline-success" href="/api/users/{u["id"]}">Открыть</a></td></tr>'
        for u in rows
    )
    return f"""
<h4>👥 Пользователи</h4>
<form class="row g-2 mb-3" action="/api/users">
<div class="col-auto"><input name="q" value="{term}" class="form-control" placeholder="ID или имя"></div>
<div class="col-auto"><button class="btn btn-secondary">Найти</button></div>
</form>
<div class="table-responsive"><table class="table table-sm align-middle">
<tr><th>ID</th><th>Имя</th><th>Баланс</th><th>Регистрация</th><th></th></tr>
{body}
</table></div>"""


def tmpl_user(u, orders, topups, refs):
    csrf = csrf_session()
    ordersHtml = "".join(
        f"<tr><td>#{o['id']}</td><td>{o['product']}</td><td>{o['price']}⭐</td>"
        f"<td>{o['date']}</td><td>{STATUS.get(o['status'], o['status'])}</td></tr>"
        for o in orders
    ) or "<tr><td class='text-secondary'>Нет заказов</td></tr>"
    topupsHtml = "".join(
        f"<tr><td>+{t['amount']}⭐</td><td>{t['date']}</td></tr>" for t in topups
    ) or "<tr><td class='text-secondary'>Нет пополнений</td></tr>"
    return f"""
<h4>👤 {u['name']} <small class="text-secondary">ID {u['id']}</small></h4>
<p>Баланс: <b>{u['balance']}⭐</b> · Регистрация: {u['created']} · Рефералов: {refs}</p>
<div class="row g-3">
<div class="col-lg-4"><div class="card p-3">
<h6>💰 Баланс</h6>
<form method="post" action="/api/users/{u['id']}/balance">
<input type="hidden" name="_csrf" value="{csrf}">
<input type="number" name="amount" class="form-control mb-2" placeholder="Сумма (минус = списать)" required>
<select name="mode" class="form-select mb-2">
<option value="add">Начислить / списать</option>
<option value="set">Установить точно</option>
</select>
<div class="form-check mb-2">
<input class="form-check-input" type="checkbox" name="notify" value="1" checked id="n1">
<label class="form-check-label" for="n1">Уведомить в боте</label>
</div>
<button class="btn btn-success w-100">Применить</button>
</form>
</div></div>
<div class="col-lg-4"><div class="card p-3">
<h6>🎁 Выдать товар бесплатно</h6>
<form method="post" action="/api/users/{u['id']}/give">
<input type="hidden" name="_csrf" value="{csrf}">
<input type="number" name="product_id" class="form-control mb-2" placeholder="ID товара (см. раздел Товары)" required>
<div class="form-check mb-2">
<input class="form-check-input" type="checkbox" name="notify" value="1" checked id="n2">
<label class="form-check-label" for="n2">Уведомить в боте</label>
</div>
<button class="btn btn-success w-100">Выдать</button>
</form>
</div></div>
<div class="col-lg-4"><div class="card p-3">
<h6>✉️ Сообщение в бота</h6>
<form method="post" action="/api/users/{u['id']}/msg">
<input type="hidden" name="_csrf" value="{csrf}">
<textarea name="text" class="form-control mb-2" rows="3" required></textarea>
<button class="btn btn-success w-100">Отправить</button>
</form>
</div></div>
</div>
<div class="row g-3 mt-1">
<div class="col-lg-6"><div class="card p-3">
<h6>Имя</h6>
<form method="post" action="/api/users/{u['id']}/name" class="d-flex gap-2">
<input type="hidden" name="_csrf" value="{csrf}">
<input name="name" value="{u['name']}" class="form-control">
<button class="btn btn-secondary">Сохранить</button>
</form>
<form method="post" action="/api/users/{u['id']}/delete" class="mt-3" onsubmit="return confirm('Удалить пользователя?')">
<input type="hidden" name="_csrf" value="{csrf}">
<button class="btn btn-sm btn-outline-danger">Удалить пользователя</button>
</form>
</div></div>
</div>
<h5 class="mt-4">Заказы</h5>
<table class="table table-sm">
{ordersHtml}
</table>
<h5>Пополнения</h5>
<table class="table table-sm">
{topupsHtml}
</table>"""


def tmpl_orders(rows, st):
    csrf = csrf_session()
    rowsHtml = "".join(
        f"""<tr>
<td>{o['id']}</td>
<td><a href="/api/users/{o['user_id']}">{o['name'] or o['user_id']}</a></td>
<td>{o['product']}</td>
<td>{o['price']}⭐</td>
<td>{o['date']}</td>
<td>{STATUS.get(o['status'], o['status'])}</td>
<td class="text-nowrap">
{"<form method='post' action='/api/orders/"+str(o['id'])+"/done'><input type='hidden' name='_csrf' value='"+csrf+"'><button class='btn btn-sm btn-success'>Выдать</button></form>" if o['status']=='new' else ''}
{"<form method='post' action='/api/orders/"+str(o['id'])+"/refund' onsubmit='return confirm(\"Вернуть деньги?\")'><input type='hidden' name='_csrf' value='"+csrf+"'><button class='btn btn-sm btn-warning'>Возврат</button></form>" if o['status']!='refunded' else ''}
<form method='post' action='/api/orders/{o['id']}/delete' onsubmit='return confirm(\"Удалить запись?\")'><input type='hidden' name='_csrf' value='{csrf}'><button class='btn btn-sm btn-outline-danger'>✕</button></form>
</td></tr>"""
        for o in rows
    )
    statusBtns = "".join(
        f'<a class="btn btn-sm btn-outline-secondary {"active" if st==k else ""}" href="/api/orders?status={k}">{v}</a>'
        for k, v in STATUS.items()
    )
    return f"""
<h4>🧾 Заказы</h4>
<div class="mb-3 btn-group">
<a class="btn btn-sm btn-outline-secondary {"active" if not st else ""}" href="/api/orders">Все</a>
{statusBtns}
</div>
<div class="table-responsive"><table class="table table-sm align-middle">
<tr><th>#</th><th>Клиент</th><th>Товар</th><th>Цена</th><th>Дата</th><th>Статус</th><th>Действия</th></tr>
{rowsHtml}
</table></div>"""


def tmpl_categories(rows):
    csrf = csrf_session()
    rowsHtml = "".join(
        f"""<tr>
<td>{c['id']}</td>
<td>
<form method="post" action="/api/categories/{c['id']}/rename" class="d-flex gap-2">
<input type="hidden" name="_csrf" value="{csrf}">
<input name="name" value="{c['name']}" class="form-control form-control-sm">
<button class="btn btn-sm btn-secondary">OK</button>
</form>
</td>
<td>{c['cnt']}</td>
<td>
<form method="post" action="/api/categories/{c['id']}/delete" onsubmit="return confirm('Удалить категорию вместе с товарами?')">
<input type="hidden" name="_csrf" value="{csrf}">
<button class="btn btn-sm btn-outline-danger">Удалить</button>
</form>
</td>
</tr>"""
        for c in rows
    )
    return f"""
<h4>📖 Категории</h4>
<form method="post" class="row g-2 mb-3">
<input type="hidden" name="_csrf" value="{csrf}">
<div class="col-auto"><input name="name" class="form-control" placeholder="Новая категория" required></div>
<div class="col-auto"><button class="btn btn-success">Добавить</button></div>
</form>
<table class="table align-middle">
<tr><th>ID</th><th>Название</th><th>Товаров</th><th></th></tr>
{rowsHtml}
</table>"""


def tmpl_products(rows, cats):
    csrf = csrf_session()
    catsOpt = "".join(f'<option value="{c["id"]}">{c["name"]}</option>' for c in cats)
    rowsHtml = "".join(
        f"""<tr>
<td>{p['id']}</td>
<td><select form="f{p['id']}" name="category_id" class="form-select form-select-sm">{catsOpt}</select></td>
<td><input form="f{p['id']}" name="name" value="{p['name']}" class="form-control form-control-sm"></td>
<td><input form="f{p['id']}" name="price" type="number" value="{p['price']}" class="form-control form-control-sm" style="width:90px"></td>
<td><input form="f{p['id']}" name="stock" type="number" value="{p['stock']}" class="form-control form-control-sm" style="width:90px"></td>
<td class="text-nowrap">
<form id="f{p['id']}" method="post" action="/api/products/{p['id']}/edit"><input type="hidden" name="_csrf" value="{csrf}"><button class="btn btn-sm btn-success">💾</button></form>
<form method="post" action="/api/products/{p['id']}/delete" onsubmit="return confirm('Удалить товар?')"><input type="hidden" name="_csrf" value="{csrf}"><button class="btn btn-sm btn-outline-danger">✕</button></form>
</td></tr>"""
        for p in rows
    )
    return f"""
<h4>🛒 Товары</h4>
<form method="post" class="row g-2 mb-4">
<input type="hidden" name="_csrf" value="{csrf}">
<div class="col-md-3"><select name="category_id" class="form-select">{catsOpt}</select></div>
<div class="col-md-4"><input name="name" class="form-control" placeholder="Название" required></div>
<div class="col-md-2"><input name="price" type="number" class="form-control" placeholder="Цена ⭐" required></div>
<div class="col-md-2"><input name="stock" type="number" class="form-control" placeholder="Остаток" value="999"></div>
<div class="col-md-1"><button class="btn btn-success w-100">+</button></div>
</form>
<div class="table-responsive"><table class="table table-sm align-middle">
<tr><th>ID</th><th>Категория</th><th>Название</th><th>Цена ⭐</th><th>Остаток</th><th></th></tr>
{rowsHtml}
</table></div>"""


def tmpl_coupons(rows):
    csrf = csrf_session()
    rowsHtml = "".join(
        f"""<tr>
<td><code>{c['code']}</code></td>
<td>{c['amount']}⭐</td>
<td>{c['uses_left']}</td>
<td>{c['used']}</td>
<td>
<form method="post" action="/api/coupons/{c['code']}/delete" onsubmit="return confirm('Удалить купон?')">
<input type="hidden" name="_csrf" value="{csrf}">
<button class="btn btn-sm btn-outline-danger">Удалить</button>
</form>
</td>
</tr>"""
        for c in rows
    )
    return f"""
<h4>🎟 Купоны</h4>
<form method="post" class="row g-2 mb-4">
<input type="hidden" name="_csrf" value="{csrf}">
<div class="col-md-3"><input name="code" class="form-control" placeholder="Код" required></div>
<div class="col-md-3"><input name="amount" type="number" class="form-control" placeholder="Сумма ⭐" required></div>
<div class="col-md-3"><input name="uses" type="number" class="form-control" placeholder="Кол-во активаций" required></div>
<div class="col-md-3"><button class="btn btn-success">Создать / обновить</button></div>
</form>
<table class="table align-middle">
<tr><th>Код</th><th>Сумма</th><th>Осталось</th><th>Активировано</th><th></th></tr>
{rowsHtml}
</table>"""


def tmpl_topups(rows):
    body = "".join(
        f'<tr><td>{t["id"]}</td><td><a href="/api/users/{t["user_id"]}">{t["name"] or t["user_id"]}</a></td>'
        f'<td>+{t["amount"]}⭐</td><td>{t["date"]}</td></tr>'
        for t in rows
    )
    return f"""
<h4>💰 История пополнений</h4>
<table class="table table-sm">
<tr><th>#</th><th>Пользователь</th><th>Сумма</th><th>Дата</th></tr>
{body}
</table>"""


def tmpl_broadcast(total, result):
    csrf = csrf_session()
    resultHtml = result and f'<div class="alert alert-success">{result}</div>' or ""
    return f"""
<h4>📢 Рассылка</h4>
<p class="text-secondary">Получателей: {total}</p>
{resultHtml}
<form method="post" onsubmit="return confirm('Отправить всем?')">
<input type="hidden" name="_csrf" value="{csrf}">
<textarea name="text" rows="6" class="form-control mb-3" placeholder="Текст сообщения" required></textarea>
<button class="btn btn-success">Отправить всем</button>
</form>"""


def tmpl_settings(items):
    csrf = csrf_session()
    body = "".join(
        f"""<div class="mb-3">
<label class="form-label">{label}</label>
{k in ("greeting","service_text")
  and f'<textarea name="{k}" rows="3" class="form-control">{val}</textarea>'
  or f'<input name="{k}" value="{val}" class="form-control">'}
</div>"""
        for k, label, val in items
    )
    return f"""
<h4>⚙️ Настройки бота</h4>
<form method="post" style="max-width:700px">
<input type="hidden" name="_csrf" value="{csrf}">
{body}
<button class="btn btn-success">Сохранить</button>
</form>"""


@app.teardown_appcontext
def close_db(_):
    d = g.pop("db", None)
    if d:
        d.close()


def db():
    if "db" not in g:
        g.db = connect_db()
    return g.db


if __name__ == "__main__":
    ensure_schema()
    if PASSWORD == "admin":
        print("⚠️  Задайте ADMIN_PASSWORD — сейчас пароль по умолчанию: admin")
    if TOKEN == "8341160507:AAHT4k1nWZzYEeCfpeejTbc3dvgmDeaJQWg":
        print("⚠️  Задайте BOT_TOKEN, если хотите, чтобы рассылка/уведомления работали.")
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
