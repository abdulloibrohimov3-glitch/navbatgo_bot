"""
admin_server.py - Lightweight Flask API that serves the admin panel
and provides live data from barbershop.db

Run: python admin_server.py
Open: http://localhost:5000
"""

from flask import Flask, jsonify, send_file, request
import sqlite3
import os
import requests as http_requests

app = Flask(__name__)
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'barbershop.db')

# Load tokens from config
try:
    from config import BARBER_BOT_TOKEN
except Exception:
    BARBER_BOT_TOKEN = os.environ.get('BARBER_BOT_TOKEN', '')


def send_telegram(token, chat_id, text):
    """Send a Telegram message to a user."""
    try:
        http_requests.post(
            f'https://api.telegram.org/bot{token}/sendMessage',
            json={'chat_id': chat_id, 'text': text, 'parse_mode': 'HTML'}
        )
    except Exception as e:
        print(f'Telegram notify error: {e}')


def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


@app.route('/')
def index():
    return send_file('admin_panel.html')


@app.route('/api/stats')
def api_stats():
    conn = get_db()
    c = conn.cursor()

    # Stats
    c.execute("SELECT COUNT(*) FROM bookings")
    total_bookings = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM barbershops WHERE is_active = 1")
    active_shops = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM users")
    total_users = c.fetchone()[0]

    c.execute("""
        SELECT COALESCE(SUM(s.price), 0) FROM bookings bk
        JOIN services s ON bk.service_id = s.id
        WHERE bk.status = 'completed'
    """)
    revenue = c.fetchone()[0]

    # Bookings
    c.execute("""
        SELECT bk.id, u.full_name as client, b.name as shop,
               br.full_name as barber,
               COALESCE(s.name_uz, '') as service,
               bk.booking_date as date, bk.booking_time as time,
               bk.status, bk.notes
        FROM bookings bk
        JOIN users u ON bk.client_id = u.telegram_id
        JOIN barbershops b ON bk.barbershop_id = b.id
        JOIN barbers br ON bk.barber_id = br.id
        LEFT JOIN services s ON bk.service_id = s.id
        ORDER BY bk.created_at DESC
        LIMIT 100
    """)
    bookings = [dict(row) for row in c.fetchall()]

    # Shops
    c.execute("""
        SELECT bs.id, bs.name, bs.address, bs.phone, bs.rating, bs.is_active,
               c.name_ru as city,
               u.full_name as owner,
               (SELECT COUNT(*) FROM barbers WHERE barbershop_id = bs.id AND is_active = 1) as barber_count,
               (SELECT COUNT(*) FROM bookings WHERE barbershop_id = bs.id) as booking_count,
               (SELECT COUNT(*) FROM bookings WHERE barbershop_id = bs.id AND status = 'completed') as completed_count
        FROM barbershops bs
        LEFT JOIN cities c ON bs.city_id = c.id
        LEFT JOIN users u ON bs.owner_id = u.telegram_id
        ORDER BY bs.created_at DESC
    """)
    shops = []
    for row in c.fetchall():
        d = dict(row)
        d['pending'] = (d['is_active'] == 0)
        shops.append(d)

    # Users
    c.execute("""
        SELECT u.id, u.telegram_id, u.full_name, u.username, u.phone,
               u.language, u.registered_at,
               (SELECT COUNT(*) FROM bookings WHERE client_id = u.telegram_id) as booking_count
        FROM users u
        ORDER BY u.registered_at DESC
        LIMIT 100
    """)
    users = [dict(row) for row in c.fetchall()]

    # Barbers
    c.execute("""
        SELECT br.id, br.full_name, b.name as barbershop,
               br.experience_years, br.specialty, br.rating, br.is_active
        FROM barbers br
        JOIN barbershops b ON br.barbershop_id = b.id
        ORDER BY br.full_name
    """)
    barbers = [dict(row) for row in c.fetchall()]

    # Services
    c.execute("""
        SELECT s.id, s.name_ru, b.name as barbershop,
               s.price, s.duration_minutes, s.is_active
        FROM services s
        JOIN barbershops b ON s.barbershop_id = b.id
        ORDER BY b.name, s.price
    """)
    services = [dict(row) for row in c.fetchall()]

    # Cities
    c.execute("""
        SELECT c.id, c.name_uz, c.name_ru, c.name_en, c.is_active,
               (SELECT COUNT(*) FROM barbershops WHERE city_id = c.id AND is_active = 1) as shop_count
        FROM cities c
        ORDER BY c.name_uz
    """)
    cities = [dict(row) for row in c.fetchall()]

    # Reviews
    c.execute("""
        SELECT r.id, u.full_name as client, b.name as barbershop,
               r.rating, r.comment, r.created_at as date
        FROM reviews r
        JOIN bookings bk ON r.booking_id = bk.id
        JOIN users u ON bk.client_id = u.telegram_id
        JOIN barbershops b ON bk.barbershop_id = b.id
        ORDER BY r.created_at DESC
    """)
    reviews = [dict(row) for row in c.fetchall()]

    # Chart - last 7 days
    c.execute("""
        SELECT booking_date as date, COUNT(*) as value
        FROM bookings
        WHERE booking_date >= date('now', '-7 days')
        GROUP BY booking_date
        ORDER BY booking_date
    """)
    chart_raw = {row['date']: row['value'] for row in c.fetchall()}

    from datetime import datetime, timedelta
    days_short = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun']
    chart = []
    for i in range(6, -1, -1):
        d = (datetime.now() - timedelta(days=i))
        date_str = d.strftime('%Y-%m-%d')
        chart.append({'label': days_short[d.weekday()], 'value': chart_raw.get(date_str, 0)})

    conn.close()

    return jsonify({
        'stats': {
            'bookings': total_bookings,
            'shops': active_shops,
            'users': total_users,
            'revenue': revenue
        },
        'bookings': bookings,
        'shops': shops,
        'users': users,
        'barbers': barbers,
        'services': services,
        'cities': cities,
        'reviews': reviews,
        'chart': chart
    })


REPLACE_APPROVE
def approve_shop(shop_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        SELECT bs.name, u.telegram_id 
        FROM barbershops bs
        LEFT JOIN users u ON bs.owner_id = u.telegram_id
        WHERE bs.id = ?
    """, (shop_id,))
    row = c.fetchone()
    conn.execute("UPDATE barbershops SET is_active = 1 WHERE id = ?", (shop_id,))
    conn.commit()
    conn.close()
    if row and row['telegram_id']:
        send_telegram(
            BARBER_BOT_TOKEN, row['telegram_id'],
            f"✅ Ваша барбершоп одобрена!\n\n🏪 {row['name']} теперь активна.\nКлиенты могут записываться к вам!"
        )
    return jsonify({'ok': True})


@app.route('/api/shops/<int:shop_id>/reject', methods=['POST'])
def reject_shop(shop_id):
    conn = get_db()
    c = conn.cursor()
    data = request.get_json() or {}
    reason = data.get('reason', 'Не указана')
    c.execute("""
        SELECT bs.name, u.telegram_id 
        FROM barbershops bs
        LEFT JOIN users u ON bs.owner_id = u.telegram_id
        WHERE bs.id = ?
    """, (shop_id,))
    row = c.fetchone()
    conn.execute("UPDATE barbershops SET is_active = -1 WHERE id = ?", (shop_id,))
    conn.commit()
    conn.close()
    if row and row['telegram_id']:
        send_telegram(
            BARBER_BOT_TOKEN, row['telegram_id'],
            f"❌ Ваша заявка отклонена\n\n🏪 {row['name']}\nПричина: {reason}\n\nИсправьте данные и подайте заявку снова."
        )
    return jsonify({'ok': True})


@app.route('/api/bookings/<int:booking_id>/status', methods=['POST'])
def update_booking_status(booking_id):
    data = request.get_json()
    status = data.get('status')
    if status not in ('confirmed', 'cancelled', 'completed', 'pending'):
        return jsonify({'ok': False, 'error': 'Invalid status'}), 400
    conn = get_db()
    conn.execute("UPDATE bookings SET status = ? WHERE id = ?", (status, booking_id))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


@app.route('/api/cities', methods=['POST'])
def add_city():
    data = request.get_json()
    conn = get_db()
    conn.execute(
        "INSERT INTO cities (name_uz, name_ru, name_en, is_active) VALUES (?, ?, ?, 1)",
        (data['name_uz'], data['name_ru'], data['name_en'])
    )
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


@app.route('/api/cities/<int:city_id>/toggle', methods=['POST'])
def toggle_city(city_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT is_active FROM cities WHERE id = ?", (city_id,))
    row = c.fetchone()
    if row:
        new_val = 0 if row[0] else 1
        conn.execute("UPDATE cities SET is_active = ? WHERE id = ?", (new_val, city_id))
        conn.commit()
    conn.close()
    return jsonify({'ok': True})


if __name__ == '__main__':
    if not os.path.exists(DB):
        print("⚠️  Database not found. Run database.py first to initialize it.")
        print("   python database.py")
    print("🌐 Admin panel running at http://localhost:5000")
    app.run(host='0.0.0.0', port=5000, debug=False)
