import telebot
from telebot import types
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import sqlite3
from datetime import datetime, timedelta
import json

from config import ADMIN_BOT_TOKEN, ADMIN_IDS, LANGUAGES, get_translation
from utils import get_user_language, get_text

# Initialize bot
bot = telebot.TeleBot(ADMIN_BOT_TOKEN)

# Admin session storage
admin_sessions = {}


def is_admin(user_id):
    """Check if user is admin"""
    return user_id in ADMIN_IDS

# -------------------- COMMAND HANDLERS --------------------


@bot.message_handler(commands=['start'])
def start_command(message):
    """Handle /start command"""
    user_id = message.from_user.id

    if not is_admin(user_id):
        bot.send_message(message.chat.id, "❌ У вас нет доступа к админ-панели")
        return

    show_admin_dashboard(message, user_id)


def show_admin_dashboard(message, user_id):
    """Show admin dashboard"""
    conn = sqlite3.connect('barbershop.db')
    cursor = conn.cursor()

    # Get statistics
    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM barbershops")
    total_shops = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM barbershops WHERE is_active = 1")
    active_shops = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM barbershops WHERE is_active = 0")
    pending_shops = cursor.fetchone()[0]

    cursor.execute(
        "SELECT COUNT(*) FROM bookings WHERE DATE(created_at) = DATE('now')")
    today_bookings = cursor.fetchone()[0]

    conn.close()

    text = f"👨‍💼 *Админ-панель NavbatGo*\n\n"
    text += f"📊 *Статистика системы:*\n"
    text += f"• 👥 Пользователи: {total_users}\n"
    text += f"• 🏢 Барбершопы: {total_shops}\n"
    text += f"   🟢 Активные: {active_shops}\n"
    text += f"   🟡 На модерации: {pending_shops}\n"
    text += f"• 📅 Бронирования сегодня: {today_bookings}\n\n"
    text += f"⏰ Время сервера: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
    text += "Выберите раздел управления:"

    markup = InlineKeyboardMarkup(row_width=2)

    markup.add(
        InlineKeyboardButton("🏢 Барбершопы", callback_data="manage_shops"),
        InlineKeyboardButton("👥 Пользователи", callback_data="manage_users")
    )

    markup.add(
        InlineKeyboardButton(
            "📋 Бронирования", callback_data="manage_bookings"),
        InlineKeyboardButton(
            "🏙 Города/Районы", callback_data="manage_locations")
    )

    markup.add(
        InlineKeyboardButton("⚙️ Настройки", callback_data="settings"),
        InlineKeyboardButton("📊 Отчеты", callback_data="reports")
    )

    if isinstance(message, types.Message):
        bot.send_message(
            message.chat.id,
            text,
            parse_mode='Markdown',
            reply_markup=markup
        )
    else:
        bot.edit_message_text(
            text,
            message.chat.id,
            message.message_id,
            parse_mode='Markdown',
            reply_markup=markup
        )

# -------------------- SHOPS MANAGEMENT --------------------


@bot.callback_query_handler(func=lambda call: call.data == 'manage_shops')
def manage_shops(call):
    """Manage barbershops"""
    user_id = call.from_user.id

    if not is_admin(user_id):
        bot.answer_callback_query(call.id, "❌ Нет доступа")
        return

    show_shops_management(call.message, user_id)


def show_shops_management(message, user_id):
    """Show shops management interface"""
    conn = sqlite3.connect('barbershop.db')
    cursor = conn.cursor()

    cursor.execute('''
        SELECT b.id, b.name, c.name_ru, b.is_active, COUNT(bk.id) as bookings_count
        FROM barbershops b
        JOIN cities c ON b.city_id = c.id
        LEFT JOIN bookings bk ON b.id = bk.barbershop_id AND DATE(bk.created_at) = DATE('now')
        GROUP BY b.id
        ORDER BY b.created_at DESC
        LIMIT 10
    ''')

    shops = cursor.fetchall()
    conn.close()

    text = f"🏢 *Управление барбершопами*\n\n"
    text += f"Последние 10 барбершопов:\n\n"

    for shop in shops:
        shop_id, name, city, is_active, today_bookings = shop

        status = {
            0: "🟡 На модерации",
            1: "🟢 Активен",
            -1: "🔴 Заблокирован"
        }.get(is_active, "❓ Неизвестно")

        text += f"*{name}*\n"
        text += f"📍 {city} | {status}\n"
        text += f"📅 Записей сегодня: {today_bookings}\n"
        text += f"🆔 ID: {shop_id}\n"
        text += "─" * 30 + "\n"

    markup = InlineKeyboardMarkup(row_width=2)

    markup.add(
        InlineKeyboardButton("🟡 На модерации", callback_data="pending_shops"),
        InlineKeyboardButton("🟢 Активные", callback_data="active_shops")
    )

    markup.add(
        InlineKeyboardButton("🔴 Заблокированные",
                             callback_data="blocked_shops"),
        InlineKeyboardButton("🔍 Поиск", callback_data="search_shop")
    )

    markup.add(InlineKeyboardButton(
        "🔙 Назад", callback_data="back_to_dashboard"))

    if isinstance(message, types.Message):
        bot.send_message(
            message.chat.id,
            text[:4000],
            parse_mode='Markdown',
            reply_markup=markup
        )
    else:
        bot.edit_message_text(
            text[:4000],
            message.chat.id,
            message.message_id,
            parse_mode='Markdown',
            reply_markup=markup
        )


@bot.callback_query_handler(func=lambda call: call.data == 'pending_shops')
def show_pending_shops(call):
    """Show pending shops for approval"""
    user_id = call.from_user.id

    if not is_admin(user_id):
        bot.answer_callback_query(call.id, "❌ Нет доступа")
        return

    conn = sqlite3.connect('barbershop.db')
    cursor = conn.cursor()

    cursor.execute('''
        SELECT b.id, b.name, c.name_ru, d.name_ru, u.full_name, b.created_at
        FROM barbershops b
        JOIN cities c ON b.city_id = c.id
        LEFT JOIN districts d ON b.district_id = d.id
        JOIN users u ON b.owner_id = u.telegram_id
        WHERE b.is_active = 0
        ORDER BY b.created_at
    ''')

    pending_shops = cursor.fetchall()
    conn.close()

    if not pending_shops:
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton(
            "🔙 Назад", callback_data="manage_shops"))

        bot.edit_message_text(
            "🟡 *Нет барбершопов на модерации*",
            call.message.chat.id,
            call.message.message_id,
            parse_mode='Markdown',
            reply_markup=markup
        )
        return

    text = f"🟡 *Барбершопы на модерации*\n\n"
    text += f"Всего: {len(pending_shops)}\n\n"

    for i, shop in enumerate(pending_shops, 1):
        shop_id, name, city, district, owner_name, created_at = shop

        created_date = datetime.strptime(
            created_at, "%Y-%m-%d %H:%M:%S").strftime("%d.%m.%Y")

        text += f"{i}. *{name}*\n"
        text += f"   👤 Владелец: {owner_name}\n"
        text += f"   📍 {city}" + (f", {district}" if district else "") + "\n"
        text += f"   📅 Подана: {created_date}\n"
        text += f"   🆔 ID: {shop_id}\n\n"

    markup = InlineKeyboardMarkup(row_width=2)

    # Add buttons for each shop
    for shop in pending_shops[:5]:
        shop_id, name, city, district, owner_name, created_at = shop
        btn_text = f"🏢 {name[:15]}..."
        markup.add(InlineKeyboardButton(
            btn_text, callback_data=f"review_shop_{shop_id}"))

    markup.add(InlineKeyboardButton("🔙 Назад", callback_data="manage_shops"))

    bot.edit_message_text(
        text[:4000],
        call.message.chat.id,
        call.message.message_id,
        parse_mode='Markdown',
        reply_markup=markup
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith('review_shop_'))
def review_shop(call):
    """Review specific shop"""
    user_id = call.from_user.id
    shop_id = int(call.data.split('_')[2])

    if not is_admin(user_id):
        bot.answer_callback_query(call.id, "❌ Нет доступа")
        return

    conn = sqlite3.connect('barbershop.db')
    cursor = conn.cursor()

    cursor.execute('''
        SELECT b.name, b.address, b.phone, b.description, b.is_active,
               c.name_ru, d.name_ru, u.full_name, u.phone as owner_phone,
               b.created_at
        FROM barbershops b
        JOIN cities c ON b.city_id = c.id
        LEFT JOIN districts d ON b.district_id = d.id
        JOIN users u ON b.owner_id = u.telegram_id
        WHERE b.id = ?
    ''', (shop_id,))

    shop_info = cursor.fetchone()

    if not shop_info:
        bot.answer_callback_query(call.id, "❌ Барбершоп не найден")
        return

    (name, address, phone, description, is_active,
     city, district, owner_name, owner_phone, created_at) = shop_info

    # Get photos
    cursor.execute(
        'SELECT photo_id FROM barbershop_photos WHERE barbershop_id = ?', (shop_id,))
    photos = [row[0] for row in cursor.fetchall()]

    # Get barbers
    cursor.execute(
        'SELECT full_name, experience_years, specialty FROM barbers WHERE barbershop_id = ?', (shop_id,))
    barbers = cursor.fetchall()

    conn.close()

    # Format shop info
    status_text = {
        0: "🟡 На модерации",
        1: "🟢 Активен",
        -1: "🔴 Заблокирован"
    }.get(is_active, "❓ Неизвестно")

    created_date = datetime.strptime(
        created_at, "%Y-%m-%d %H:%M:%S").strftime("%d.%m.%Y %H:%M")

    text = f"🏢 *Детали барбершопа*\n\n"
    text += f"*Название:* {name}\n"
    text += f"*Статус:* {status_text}\n"
    text += f"*ID:* {shop_id}\n\n"

    text += f"👤 *Владелец:*\n"
    text += f"• Имя: {owner_name}\n"
    text += f"• Телефон: {owner_phone or 'Не указан'}\n\n"

    text += f"📍 *Адрес:*\n"
    text += f"• Город: {city}\n"
    if district:
        text += f"• Район: {district}\n"
    text += f"• Адрес: {address}\n"
    text += f"• Телефон: {phone}\n\n"

    if description:
        text += f"📝 *Описание:*\n{description[:200]}...\n\n"

    if barbers:
        text += f"💇 *Мастера ({len(barbers)}):*\n"
        for barber in barbers[:3]:  # Show first 3 barbers
            barber_name, exp, spec = barber
            text += f"• {barber_name}"
            if exp:
                text += f" ({exp} лет)"
            if spec:
                text += f" - {spec}"
            text += "\n"
        text += "\n"

    text += f"📅 *Зарегистрирован:* {created_date}\n"
    text += f"📸 *Фото:* {len(photos)} шт\n\n"

    # Send photos if available
    if photos:
        try:
            # Send first photo
            bot.send_photo(
                call.message.chat.id,
                photos[0],
                caption=text[:1000],
                parse_mode='Markdown'
            )

            # Send other photos as media group
            if len(photos) > 1:
                media = []
                for photo_id in photos[1:4]:  # Send up to 3 more photos
                    media.append(types.InputMediaPhoto(photo_id))

                bot.send_media_group(call.message.chat.id, media)

            # Delete original message
            bot.delete_message(call.message.chat.id, call.message.message_id)

            # Show action buttons in new message
            show_shop_actions(call.message, user_id, shop_id, is_active)
            return

        except Exception as e:
            print(f"Error sending photos: {e}")

    # If no photos or error, just send text
    show_shop_actions(call.message, user_id, shop_id, is_active, text)


def show_shop_actions(message, user_id, shop_id, is_active, text=None):
    """Show actions for shop"""
    if text:
        bot.send_message(
            message.chat.id,
            text[:4000],
            parse_mode='Markdown'
        )

    markup = InlineKeyboardMarkup(row_width=2)

    if is_active == 0:  # Pending
        markup.add(
            InlineKeyboardButton(
                "✅ Одобрить", callback_data=f"approve_shop_{shop_id}"),
            InlineKeyboardButton(
                "❌ Отклонить", callback_data=f"reject_shop_{shop_id}")
        )
    elif is_active == 1:  # Active
        markup.add(
            InlineKeyboardButton(
                "🔴 Заблокировать", callback_data=f"block_shop_{shop_id}"),
            InlineKeyboardButton("✏️ Редактировать",
                                 callback_data=f"edit_shop_{shop_id}")
        )
    elif is_active == -1:  # Blocked
        markup.add(
            InlineKeyboardButton("🟢 Разблокировать",
                                 callback_data=f"unblock_shop_{shop_id}"),
            InlineKeyboardButton(
                "🗑 Удалить", callback_data=f"delete_shop_{shop_id}")
        )

    markup.add(
        InlineKeyboardButton(
            "📊 Статистика", callback_data=f"shop_stats_{shop_id}"),
        InlineKeyboardButton("🔙 К списку", callback_data="pending_shops")
    )

    bot.send_message(
        message.chat.id,
        "Выберите действие:",
        reply_markup=markup
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith('approve_shop_'))
def approve_shop(call):
    """Approve shop"""
    user_id = call.from_user.id
    shop_id = int(call.data.split('_')[2])

    if not is_admin(user_id):
        bot.answer_callback_query(call.id, "❌ Нет доступа")
        return

    conn = sqlite3.connect('barbershop.db')
    cursor = conn.cursor()

    # Get shop info for notification
    cursor.execute('''
        SELECT b.name, b.owner_id 
        FROM barbershops b 
        WHERE b.id = ?
    ''', (shop_id,))

    shop_info = cursor.fetchone()

    if not shop_info:
        bot.answer_callback_query(call.id, "❌ Барбершоп не найден")
        return

    shop_name, owner_id = shop_info

    # Update shop status
    cursor.execute(
        "UPDATE barbershops SET is_active = 1 WHERE id = ?", (shop_id,))
    conn.commit()
    conn.close()

    # Notify barber
    try:
        from barber_bot import bot as barber_bot
        barber_bot.send_message(
            owner_id,
            f"🎉 *Ваш барбершоп одобрен!*\n\n"
            f"🏢 *{shop_name}* теперь активен в системе NavbatGo.\n\n"
            f"Теперь клиенты могут:\n"
            f"• Найти ваш барбершоп в поиске\n"
            f"• Бронировать время онлайн\n"
            f"• Оставлять отзывы\n\n"
            f"✨ Желаем успешной работы!"
        )
    except:
        pass

    bot.answer_callback_query(call.id, "✅ Барбершоп одобрен")

    # Go back to pending shops
    show_pending_shops(call)


@bot.callback_query_handler(func=lambda call: call.data.startswith('reject_shop_'))
def reject_shop(call):
    """Reject shop"""
    user_id = call.from_user.id
    shop_id = int(call.data.split('_')[2])

    if not is_admin(user_id):
        bot.answer_callback_query(call.id, "❌ Нет доступа")
        return

    # Ask for rejection reason
    bot.send_message(
        call.message.chat.id,
        "📝 *Укажите причину отклонения:*",
        parse_mode='Markdown'
    )

    # Store shop_id in session
    if user_id not in admin_sessions:
        admin_sessions[user_id] = {}

    admin_sessions[user_id] = {
        'action': 'rejecting_shop',
        'shop_id': shop_id
    }


@bot.message_handler(func=lambda message:
                     message.from_user.id in admin_sessions and
                     admin_sessions[message.from_user.id].get('action') == 'rejecting_shop')
def handle_rejection_reason(message):
    """Handle rejection reason"""
    user_id = message.from_user.id
    session = admin_sessions[user_id]
    shop_id = session['shop_id']
    reason = message.text.strip()

    conn = sqlite3.connect('barbershop.db')
    cursor = conn.cursor()

    # Get shop info for notification
    cursor.execute('''
        SELECT b.name, b.owner_id 
        FROM barbershops b 
        WHERE b.id = ?
    ''', (shop_id,))

    shop_info = cursor.fetchone()

    if not shop_info:
        bot.send_message(message.chat.id, "❌ Барбершоп не найден")
        return

    shop_name, owner_id = shop_info

    # Delete shop (or mark as rejected)
    cursor.execute("DELETE FROM barbershops WHERE id = ?", (shop_id,))
    conn.commit()
    conn.close()

    # Notify barber
    try:
        from barber_bot import bot as barber_bot
        barber_bot.send_message(
            owner_id,
            f"❌ *Ваша заявка на регистрацию барбершопа отклонена*\n\n"
            f"🏢 *{shop_name}*\n\n"
            f"📝 *Причина:* {reason}\n\n"
            f"Вы можете подать новую заявку с исправленными данными."
        )
    except:
        pass

    bot.send_message(
        message.chat.id,
        f"✅ Барбершоп '{shop_name}' отклонен и удален.\n"
        f"Владелец уведомлен о причине."
    )

    # Clear session
    del admin_sessions[user_id]

    # Go back to pending shops menu
    show_locations_management(message, user_id)


@bot.callback_query_handler(func=lambda call: call.data.startswith('block_shop_'))
def block_shop(call):
    """Block shop"""
    user_id = call.from_user.id
    shop_id = int(call.data.split('_')[2])

    if not is_admin(user_id):
        bot.answer_callback_query(call.id, "❌ Нет доступа")
        return

    conn = sqlite3.connect('barbershop.db')
    cursor = conn.cursor()

    # Get shop info
    cursor.execute(
        "SELECT name, owner_id FROM barbershops WHERE id = ?", (shop_id,))
    shop_info = cursor.fetchone()

    if not shop_info:
        bot.answer_callback_query(call.id, "❌ Барбершоп не найден")
        return

    shop_name, owner_id = shop_info

    # Update status
    cursor.execute(
        "UPDATE barbershops SET is_active = -1 WHERE id = ?", (shop_id,))
    conn.commit()
    conn.close()

    # Notify barber
    try:
        from barber_bot import bot as barber_bot
        barber_bot.send_message(
            owner_id,
            f"🚫 *Ваш барбершоп заблокирован*\n\n"
            f"🏢 *{shop_name}* временно недоступен для бронирования.\n\n"
            f"Причина: нарушение правил платформы.\n"
            f"По вопросам обращайтесь в поддержку."
        )
    except:
        pass

    bot.answer_callback_query(call.id, "🔴 Барбершоп заблокирован")

    # Refresh view
    review_shop(call)

# -------------------- USERS MANAGEMENT --------------------


@bot.callback_query_handler(func=lambda call: call.data == 'manage_users')
def manage_users(call):
    """Manage users"""
    user_id = call.from_user.id

    if not is_admin(user_id):
        bot.answer_callback_query(call.id, "❌ Нет доступа")
        return

    show_users_management(call.message, user_id)


def show_users_management(message, user_id):
    """Show users management interface"""
    conn = sqlite3.connect('barbershop.db')
    cursor = conn.cursor()

    cursor.execute('''
        SELECT u.telegram_id, u.full_name, u.phone, u.language, 
               COUNT(bk.id) as bookings_count,
               MAX(bk.created_at) as last_booking
        FROM users u
        LEFT JOIN bookings bk ON u.telegram_id = bk.client_id
        GROUP BY u.telegram_id
        ORDER BY u.registered_at DESC
        LIMIT 10
    ''')

    users = cursor.fetchall()
    conn.close()

    text = f"👥 *Управление пользователями*\n\n"
    text += f"Последние 10 пользователей:\n\n"

    for user in users:
        telegram_id, full_name, phone, language, bookings_count, last_booking = user

        language_text = {
            'uz': "🇺🇿 Узб",
            'ru': "🇷🇺 Рус",
            'en': "🇺🇸 Англ"
        }.get(language, language)

        last_booking_text = ""
        if last_booking:
            last_date = datetime.strptime(
                last_booking, "%Y-%m-%d %H:%M:%S").strftime("%d.%m.%Y")
            last_booking_text = f" (последняя: {last_date})"

        text += f"*{full_name or 'Без имени'}*\n"
        text += f"📱 {phone or 'Нет телефона'}\n"
        text += f"🌐 {language_text} | 📅 {bookings_count} бронирований{last_booking_text}\n"
        text += f"🆔 {telegram_id}\n"
        text += "─" * 30 + "\n"

    markup = InlineKeyboardMarkup(row_width=2)

    markup.add(
        InlineKeyboardButton("📈 Активные", callback_data="active_users"),
        InlineKeyboardButton("📊 Статистика", callback_data="users_stats")
    )

    markup.add(InlineKeyboardButton(
        "🔙 Назад", callback_data="back_to_dashboard"))

    if isinstance(message, types.Message):
        bot.send_message(
            message.chat.id,
            text[:4000],
            parse_mode='Markdown',
            reply_markup=markup
        )
    else:
        bot.edit_message_text(
            text[:4000],
            message.chat.id,
            message.message_id,
            parse_mode='Markdown',
            reply_markup=markup
        )

# -------------------- LOCATIONS MANAGEMENT --------------------


@bot.callback_query_handler(func=lambda call: call.data == 'manage_locations')
def manage_locations(call):
    """Manage cities and districts"""
    user_id = call.from_user.id

    if not is_admin(user_id):
        bot.answer_callback_query(call.id, "❌ Нет доступа")
        return

    show_locations_management(call.message, user_id)


def show_locations_management(message, user_id):
    """Show locations management interface"""
    conn = sqlite3.connect('barbershop.db')
    cursor = conn.cursor()

    # Get cities with district count
    cursor.execute('''
        SELECT c.id, c.name_ru, c.is_active, COUNT(d.id) as district_count
        FROM cities c
        LEFT JOIN districts d ON c.id = d.city_id AND d.is_active = 1
        GROUP BY c.id
        ORDER BY c.name_ru
    ''')

    cities = cursor.fetchall()
    conn.close()

    text = f"🏙 *Управление городами и районами*\n\n"
    text += f"Всего городов: {len(cities)}\n\n"

    for city in cities:
        city_id, name, is_active, district_count = city

        status = "🟢" if is_active == 1 else "🔴"

        text += f"{status} *{name}*\n"
        text += f"   📍 Районов: {district_count}\n"
        text += f"   🆔 ID: {city_id}\n\n"

    markup = InlineKeyboardMarkup(row_width=2)

    markup.add(
        InlineKeyboardButton("➕ Добавить город", callback_data="add_city"),
        InlineKeyboardButton("✏️ Редактировать", callback_data="edit_cities")
    )

    markup.add(
        InlineKeyboardButton("📍 Районы", callback_data="manage_districts"),
        InlineKeyboardButton("🗺 Импорт", callback_data="import_locations")
    )

    markup.add(InlineKeyboardButton(
        "🔙 Назад", callback_data="back_to_dashboard"))

    if isinstance(message, types.Message):
        bot.send_message(
            message.chat.id,
            text[:4000],
            parse_mode='Markdown',
            reply_markup=markup
        )
    else:
        bot.edit_message_text(
            text[:4000],
            message.chat.id,
            message.message_id,
            parse_mode='Markdown',
            reply_markup=markup
        )


@bot.callback_query_handler(func=lambda call: call.data == 'add_city')
def add_city(call):
    """Add new city"""
    user_id = call.from_user.id

    if not is_admin(user_id):
        bot.answer_callback_query(call.id, "❌ Нет доступа")
        return

    bot.send_message(
        call.message.chat.id,
        "🏙 *Добавление нового города*\n\n"
        "Введите название города на русском:",
        parse_mode='Markdown'
    )

    # Store in session
    if user_id not in admin_sessions:
        admin_sessions[user_id] = {}

    admin_sessions[user_id] = {
        'action': 'adding_city',
        'step': 'name_ru'
    }


@bot.message_handler(func=lambda message:
                     message.from_user.id in admin_sessions and
                     admin_sessions[message.from_user.id].get('action') == 'adding_city' and
                     admin_sessions[message.from_user.id].get('step') == 'name_ru')
def handle_city_name_ru(message):
    """Handle city name in Russian"""
    user_id = message.from_user.id
    session = admin_sessions[user_id]

    session['name_ru'] = message.text.strip()
    session['step'] = 'name_uz'

    bot.send_message(
        message.chat.id,
        "Введите название города на узбекском (латиница):"
    )


@bot.message_handler(func=lambda message:
                     message.from_user.id in admin_sessions and
                     admin_sessions[message.from_user.id].get('action') == 'adding_city' and
                     admin_sessions[message.from_user.id].get('step') == 'name_uz')
def handle_city_name_uz(message):
    """Handle city name in Uzbek"""
    user_id = message.from_user.id
    session = admin_sessions[user_id]

    session['name_uz'] = message.text.strip()
    session['step'] = 'name_en'

    bot.send_message(
        message.chat.id,
        "Введите название города на английском:"
    )


@bot.message_handler(func=lambda message:
                     message.from_user.id in admin_sessions and
                     admin_sessions[message.from_user.id].get('action') == 'adding_city' and
                     admin_sessions[message.from_user.id].get('step') == 'name_en')
def handle_city_name_en(message):
    """Handle city name in English"""
    user_id = message.from_user.id
    session = admin_sessions[user_id]

    session['name_en'] = message.text.strip()

    # Save to database
    conn = sqlite3.connect('barbershop.db')
    cursor = conn.cursor()

    cursor.execute('''
        INSERT INTO cities (name_uz, name_ru, name_en)
        VALUES (?, ?, ?)
    ''', (session['name_uz'], session['name_ru'], session['name_en']))

    conn.commit()
    conn.close()

    bot.send_message(
        message.chat.id,
        f"✅ Город '{session['name_ru']}' успешно добавлен!"
    )

    # Clear session
    del admin_sessions[user_id]

    # Show locations management
    show_locations_management(message, user_id)

# -------------------- BACK BUTTONS --------------------


@bot.callback_query_handler(func=lambda call: call.data == 'back_to_dashboard')
def back_to_dashboard(call):
    """Go back to dashboard"""
    user_id = call.from_user.id

    if not is_admin(user_id):
        bot.answer_callback_query(call.id, "❌ Нет доступа")
        return

    show_admin_dashboard(call.message, user_id)

# -------------------- MAIN --------------------


def startadmin():
    """Main function to start the bot"""
    print("👨‍💼 Admin bot is starting...")
    print("✅ Admin bot is running. Press Ctrl+C to stop.")
    bot.infinity_polling()


if __name__ == '__main__':
    startadmin()
