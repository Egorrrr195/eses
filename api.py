"""
Минимальный JSON-хранилище для админки client/index.html.

Хранит состояние в client/data.json и отдаёт его как API.
Подходит для GitHub Pages + отдельный сервер без БД.

Запуск:
    python client/api.py

По умолчанию слушает 127.0.0.1:5001.
Если хочешь 24/7 без Python, запусти этот сервис один раз,
а index.html закинь на GitHub Pages как статику.
"""

import json
import os
import secrets
import time
from datetime import datetime
from flask import Flask, g, jsonify, request

CLIENT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(CLIENT_DIR, "data.json")

app = Flask(__name__, static_folder=".", static_url_path="")
app.secret_key = os.getenv("SECRET_KEY") or secrets.token_hex(32)
app.config.update(
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_HTTPONLY=True,
)

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
TOKEN = os.getenv("BOT_TOKEN", "")


def load_data():
    if not os.path.exists(DATA_PATH):
        return default_data()
    try:
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default_data()


def default_data():
    return {
        "users": [],
        "orders": [],
        "topups": [],
        "categories": [],
        "products": [],
        "coupons": [],
        "settings": dict(DEFAULTS),
        "s": {
            "users": 0,
            "orders": 0,
            "new": 0,
            "revenue": 0,
            "topups": 0,
            "balances": 0,
        },
        "recent": [],
        "csrf": secrets.token_hex(16),
        "userQuery": "",
        "orderStatus": "",
        "broadcastResult": "",
    }


def save_data(d):
    tmp = DATA_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DATA_PATH)


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def to_int(v, default=0):
    try:
        return int(str(v).strip())
    except Exception:
        return default


def ref_bonus():
    try:
        return int((load_data()["settings"] or {}).get("ref_bonus", "5"))
    except Exception:
        return 5


def notify(text):
    if not TOKEN:
        return False
    import urllib.request
    try:
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data=json.dumps({"chat_id": 0, "text": text}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.load(resp).get("ok", False)
    except Exception:
        return False


@app.before_request
def guard():
    if request.path == "/api/login":
        return
    if not session.get("auth"):
        return jsonify({"redirect": "/api/login"})
    if request.method == "POST":
        sent = request.form.get("_csrf", "")
        if not secrets.compare_digest(sent, session.get("csrf", "x")):
            return jsonify({"error": "Ошибка CSRF"})


@app.route("/api/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        time.sleep(0.5)
        if secrets.compare_digest(request.form.get("password", ""), os.getenv("ADMIN_PASSWORD", "admin")):
            session.clear()
            session["auth"] = True
            session["csrf"] = secrets.token_hex(16)
            return jsonify({"redirect": "/"})
        return jsonify({"error": "Неверный пароль"})
    return jsonify(json_view("login"))


@app.route("/api/logout")
def logout():
    session.clear()
    return jsonify({"redirect": "/api/login"})


@app.route("/api/")
def index():
    d = load_data()
    d["csrf"] = session.setdefault("csrf", secrets.token_hex(16))
    d["s"] = compute_stats(d)
    d["recent"] = list(d.get("orders", [])[-10:])
    return jsonify(json_view("index", d))


@app.route("/api/users")
def users():
    term = (request.args.get("q") or "").strip()
    d = load_data()
    users = d.get("users", [])
    if term:
        users = [u for u in users if str(u.get("id")).__contains__(term) or (u.get("name") or "").lower().__contains__(term.lower())]
    d["csrf"] = session.setdefault("csrf", secrets.token_hex(16))
    d["userQuery"] = term
    d["s"] = compute_stats(d)
    save_data(d)
    return jsonify(json_view("users", dict(users=users, term=term)))


@app.route("/api/users/<int:uid>")
def user(uid):
    d = load_data()
    u = next((x for x in d.get("users", []) if x.get("id") == uid), None)
    if not u:
        return jsonify({"error": "Пользователь не найден", "redirect": "/api/users"})
    d["csrf"] = session.setdefault("csrf", secrets.token_hex(16))
    d["s"] = compute_stats(d)
    save_data(d)
    return jsonify(json_view("user", dict(u=u, orders=d.get("orders", []), topups=d.get("topups", []), refs=len([x for x in d.get("users", []) if x.get("referrer") == uid]))))


@app.route("/api/users/<int:uid>/balance", methods=["POST"])
def user_balance(uid):
    mode = request.form.get("mode")
    amount = to_int(request.form.get("amount"))
    d = load_data()
    users = d.get("users", [])
    for u in users:
        if u.get("id") == uid:
            if mode == "set":
                u["balance"] = amount
            else:
                u["balance"] = u.get("balance", 0) + amount
            if amount > 0:
                d.setdefault("topups", []).append({
                    "id": max((t.get("id", 0) for t in d.get("topups", [])), default=0) + 1,
                    "user_id": uid,
                    "amount": amount,
                    "date": now() + " (выдано админом)",
                })
            break
    d["csrf"] = session.setdefault("csrf", secrets.token_hex(16))
    d["s"] = compute_stats(d)
    d["recent"] = d.get("orders", [])[-10:]
    save_data(d)
    flash = f"Баланс изменён на {amount:+}⭐"
    if request.form.get("notify") and amount:
        notify(f"💰 Администратор изменил ваш баланс: {amount:+}⭐")
    return jsonify({"flash": flash})


@app.route("/api/users/<int:uid>/name", methods=["POST"])
def user_name(uid):
    name = request.form.get("name", "").strip()
    d = load_data()
    for u in d.get("users", []):
        if u.get("id") == uid:
            u["name"] = name
            break
    d["csrf"] = session.setdefault("csrf", secrets.token_hex(16))
    d["s"] = compute_stats(d)
    save_data(d)
    return jsonify({"flash": "Имя обновлено"})


@app.route("/api/users/<int:uid>/msg", methods=["POST"])
def user_msg(uid):
    text = request.form.get("text", "").strip()
    ok = notify(text)
    return jsonify({"flash": "Сообщение отправлено ✅" if ok else "Не удалось отправить"})


@app.route("/api/users/<int:uid>/give", methods=["POST"])
def user_give(uid):
    pid = to_int(request.form.get("product_id"))
    d = load_data()
    products = d.get("products", [])
    p = next((x for x in products if x.get("id") == pid), None)
    if not p and d.get("categories"):
        p = None
    if not p:
        return jsonify({"error": "Товар не найден"})
    oid = max((o.get("id", 0) for o in d.get("orders", [])), default=0) + 1
    d.setdefault("orders", []).append({
        "id": oid,
        "user_id": uid,
        "product": p.get("name", ""),
        "price": 0,
        "date": now(),
        "status": "done",
    })
    if request.form.get("notify"):
        notify(f"🎁 Вам выдан товар: {p.get('name')}")
    d["csrf"] = session.setdefault("csrf", secrets.token_hex(16))
    d["s"] = compute_stats(d)
    d["recent"] = d.get("orders", [])[-10:]
    save_data(d)
    return jsonify({"flash": f"Выдано: {p.get('name')}", "redirect": f"/api/users/{uid}"})


@app.route("/api/users/<int:uid>/delete", methods=["POST"])
def user_delete(uid):
    d = load_data()
    d["users"] = [u for u in d.get("users", []) if u.get("id") != uid]
    d["orders"] = [o for o in d.get("orders", []) if o.get("user_id") != uid]
    d["topups"] = [t for t in d.get("topups", []) if t.get("user_id") != uid]
    d["csrf"] = session.setdefault("csrf", secrets.token_hex(16))
    d["s"] = compute_stats(d)
    d["recent"] = d.get("orders", [])[-10:]
    save_data(d)
    return jsonify({"flash": "Пользователь удалён", "redirect": "/api/users"})


@app.route("/api/orders")
def orders():
    st = (request.args.get("status") or "").strip()
    d = load_data()
    rows = d.get("orders", [])
    if st:
        rows = [o for o in rows if o.get("status") == st]
    d["csrf"] = session.setdefault("csrf", secrets.token_hex(16))
    d["orderStatus"] = st or ""
    d["s"] = compute_stats(d)
    d["recent"] = rows[-10:]
    save_data(d)
    return jsonify(json_view("orders", dict(rows=rows, st=st)))


@app.route("/api/orders/<int:oid>/<action>", methods=["POST"])
def order_action(oid, action):
    d = load_data()
    orders = d.get("orders", [])
    o = next((x for x in orders if x.get("id") == oid), None)
    if not o:
        return jsonify({"error": "Заказ не найден"})
    if action == "done":
        o["status"] = "done"
        notify(f"✅ Ваш заказ #{oid} ({o.get('product')}) выдан. Спасибо за покупку!")
        flash = f"Заказ #{oid} отмечен как выданный, клиент уведомлён"
    elif action == "refund" and o.get("status") != "refunded":
        o["status"] = "refunded"
        add_balance(o.get("user_id"), o.get("price", 0))
        notify(f"↩️ Заказ #{oid} отменён, {o.get('price')}⭐ возвращены на баланс.")
        flash = f"Заказ #{oid}: возврат {o.get('price')}⭐"
    elif action == "delete":
        d["orders"] = [x for x in orders if x.get("id") != oid]
        flash = f"Заказ #{oid} удалён"
        o = None
    else:
        return jsonify({"error": "Неизвестное действие"})
    d["csrf"] = session.setdefault("csrf", secrets.token_hex(16))
    d["s"] = compute_stats(d)
    d["recent"] = d.get("orders", [])[-10:]
    save_data(d)
    return jsonify({"flash": flash})


@app.route("/api/categories", methods=["GET", "POST"])
def categories():
    d = load_data()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            return jsonify({"error": "Введите название"})
        if any(c.get("name") == name for c in d.get("categories", [])):
            return jsonify({"error": "Такая категория уже есть"})
        d.setdefault("categories", []).append({"id": next_id(d.get("categories", [])), "name": name, "cnt": 0})
        d["csrf"] = session.setdefault("csrf", secrets.token_hex(16))
        save_data(d)
        return jsonify({"redirect": "/api/categories"})
    rows = d.get("categories", [])
    for c in rows:
        c["cnt"] = len([p for p in d.get("products", []) if p.get("category_id") == c.get("id")])
    d["csrf"] = session.setdefault("csrf", secrets.token_hex(16))
    d["s"] = compute_stats(d)
    save_data(d)
    return jsonify(json_view("categories", dict(rows=rows)))


@app.route("/api/categories/<int:cid>/rename", methods=["POST"])
def category_rename(cid):
    name = request.form.get("name", "").strip()
    d = load_data()
    for c in d.get("categories", []):
        if c.get("id") == cid:
            c["name"] = name
            break
    d["csrf"] = session.setdefault("csrf", secrets.token_hex(16))
    save_data(d)
    return jsonify({"flash": "Категория переименована"})


@app.route("/api/categories/<int:cid>/delete", methods=["POST"])
def category_delete(cid):
    d = load_data()
    d["products"] = [p for p in d.get("products", []) if p.get("category_id") != cid]
    d["categories"] = [c for c in d.get("categories", []) if c.get("id") != cid]
    d["csrf"] = session.setdefault("csrf", secrets.token_hex(16))
    d["s"] = compute_stats(d)
    save_data(d)
    return jsonify({"flash": "Категория и её товары удалены"})


@app.route("/api/products", methods=["GET", "POST"])
def products():
    d = load_data()
    if request.method == "POST":
        cat_id = to_int(request.form.get("category_id"))
        name = request.form.get("name", "").strip()
        price = to_int(request.form.get("price"))
        stock = to_int(request.form.get("stock"), 999)
        if not name:
            return jsonify({"error": "Введите название"})
        d.setdefault("products", []).append({
            "id": next_id(d.get("products", [])),
            "category_id": cat_id,
            "name": name,
            "price": price,
            "stock": stock,
        })
        d["csrf"] = session.setdefault("csrf", secrets.token_hex(16))
        save_data(d)
        return jsonify({"redirect": "/api/products"})
    rows = d.get("products", [])
    cats = d.get("categories", [])
    d["csrf"] = session.setdefault("csrf", secrets.token_hex(16))
    d["s"] = compute_stats(d)
    save_data(d)
    return jsonify(json_view("products", dict(rows=rows, cats=cats)))


@app.route("/api/products/<int:pid>/edit", methods=["POST"])
def product_edit(pid):
    d = load_data()
    for p in d.get("products", []):
        if p.get("id") == pid:
            p["category_id"] = to_int(request.form.get("category_id"))
            p["name"] = request.form.get("name", "").strip()
            p["price"] = to_int(request.form.get("price"))
            p["stock"] = to_int(request.form.get("stock"))
            break
    d["csrf"] = session.setdefault("csrf", secrets.token_hex(16))
    save_data(d)
    return jsonify({"flash": "Товар сохранён"})


@app.route("/api/products/<int:pid>/delete", methods=["POST"])
def product_delete(pid):
    d = load_data()
    d["products"] = [p for p in d.get("products", []) if p.get("id") != pid]
    d["csrf"] = session.setdefault("csrf", secrets.token_hex(16))
    d["s"] = compute_stats(d)
    save_data(d)
    return jsonify({"flash": "Товар удалён"})


@app.route("/api/coupons", methods=["GET", "POST"])
def coupons():
    d = load_data()
    if request.method == "POST":
        code = (request.form.get("code") or "").strip().upper()
        amount = to_int(request.form.get("amount"))
        uses = to_int(request.form.get("uses"))
        if not code:
            return jsonify({"error": "Введите код"})
        coupons = d.get("coupons", [])
        for c in coupons:
            if c.get("code") == code:
                c["amount"] = amount
                c["uses_left"] = uses
                break
        else:
            coupons.append({"code": code, "amount": amount, "uses_left": uses, "used": 0})
        d["csrf"] = session.setdefault("csrf", secrets.token_hex(16))
        save_data(d)
        return jsonify({"redirect": "/api/coupons"})
    rows = []
    for c in d.get("coupons", []):
        used = len([u for u in d.get("users", []) if any(
            uc.get("code") == c.get("code") and uc.get("user_id") == u.get("id")
            for uc in d.get("used_coupons", [])
        )])
        rows.append({"code": c.get("code"), "amount": c.get("amount"), "uses_left": c.get("uses_left"), "used": used})
    d["csrf"] = session.setdefault("csrf", secrets.token_hex(16))
    d["s"] = compute_stats(d)
    save_data(d)
    return jsonify(json_view("coupons", dict(rows=rows)))


@app.route("/api/coupons/<code>/delete", methods=["POST"])
def coupon_delete(code):
    d = load_data()
    d["coupons"] = [c for c in d.get("coupons", []) if c.get("code") != code]
    d["csrf"] = session.setdefault("csrf", secrets.token_hex(16))
    save_data(d)
    return jsonify({"flash": "Купон удалён"})


@app.route("/api/topups")
def topups():
    d = load_data()
    rows = d.get("topups", [])
    d["csrf"] = session.setdefault("csrf", secrets.token_hex(16))
    d["s"] = compute_stats(d)
    save_data(d)
    return jsonify(json_view("topups", dict(rows=rows)))


@app.route("/api/broadcast", methods=["GET", "POST"])
def broadcast():
    d = load_data()
    result = None
    if request.method == "POST":
        text = request.form.get("text", "").strip()
        if text:
            ok = fail = 0
            for u in d.get("users", []):
                if notify(text):
                    ok += 1
                else:
                    fail += 1
                time.sleep(0.05)
            result = f"Отправлено: {ok}, не доставлено: {fail}"
    d["csrf"] = session.setdefault("csrf", secrets.token_hex(16))
    d["broadcastResult"] = result or ""
    d["s"] = compute_stats(d)
    save_data(d)
    return jsonify(json_view("broadcast", dict(result=result, total=len(d.get("users", [])))))


@app.route("/api/settings", methods=["GET", "POST"])
def settings():
    d = load_data()
    if request.method == "POST":
        settings = d.get("settings", {})
        for k in DEFAULTS:
            if k in request.form:
                settings[k] = request.form[k]
        d["settings"] = settings
        d["csrf"] = session.setdefault("csrf", secrets.token_hex(16))
        save_data(d)
        return jsonify({"flash": "Настройки сохранены", "redirect": "/api/settings"})
    items = []
    s = d.get("settings", {})
    for k in DEFAULTS:
        items.append((k, LABELS[k], s.get(k, DEFAULTS[k])))
    d["csrf"] = session.setdefault("csrf", secrets.token_hex(16))
    d["s"] = compute_stats(d)
    save_data(d)
    return jsonify(json_view("settings", dict(items=items)))


def compute_stats(d):
    users = d.get("users", [])
    orders = d.get("orders", [])
    topups = d.get("topups", [])
    return {
        "users": len(users),
        "orders": len(orders),
        "new": len([o for o in orders if o.get("status") == "new"]),
        "revenue": sum(o.get("price", 0) for o in orders if o.get("status") != "refunded"),
        "topups": sum(t.get("amount", 0) for t in topups),
        "balances": sum(u.get("balance", 0) for u in users),
    }


def add_balance(uid, amount):
    d = load_data()
    for u in d.get("users", []):
        if u.get("id") == uid:
            u["balance"] = u.get("balance", 0) + amount
            break
    d["csrf"] = session.setdefault("csrf", secrets.token_hex(16))
    d["s"] = compute_stats(d)
    save_data(d)


def next_id(items):
    return max((i.get("id", 0) for i in items), default=0) + 1


def json_view(name, extra=None):
    d = load_data()
    base = dict(
        csrf=d.get("csrf") or secrets.token_hex(16),
        STATUS=STATUS,
        DEFAULTS=DEFAULTS,
        LABELS=LABELS,
        DEFAULTS_VALUES=DEFAULTS,
        s=d.get("s", compute_stats(d)),
        recent=d.get("recent", [] or d.get("orders", [])[-10:]),
        users=d.get("users", []),
        orders=d.get("orders", []),
        topups=d.get("topups", []),
        categories=d.get("categories", []),
        products=d.get("products", []),
        coupons=d.get("coupons", []),
        settings=d.get("settings", {}),
        userQuery=d.get("userQuery", ""),
        orderStatus=d.get("orderStatus", ""),
        broadcastResult=d.get("broadcastResult", ""),
    )
    if extra:
        base.update(extra)
    return base


@app.after_request
def headers(response):
    response.headers["Cache-Control"] = "no-store"
    return response


if __name__ == "__main__":
    if not os.path.exists(DATA_PATH):
        save_data(default_data())
    if os.getenv("ADMIN_PASSWORD", "admin") == "admin":
        print("⚠️  Задайте ADMIN_PASSWORD — сейчас пароль по умолчанию: admin")
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5001")))
