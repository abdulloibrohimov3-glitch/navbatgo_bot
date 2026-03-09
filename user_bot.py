import telebot
from telebot import types
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
import sqlite3
from datetime import datetime, timedelta
import threading
from time import sleep
import re

from config import USER_BOT_TOKEN, LANGUAGES, get_translation, TIME_SLOTS
from utils import (
    get_user_language, get_text, register_user, get_cities, get_districts,
    get_barbershops_by_location, get_barbershop_details, create_booking,
    get_user_bookings, get_nearby_barbershops, format_booking_details,
    get_available_time_slots, calculate_distance, send_booking_notifications
)

# Initialize bot
bot = telebot.TeleBot(USER_BOT_TOKEN)

# User session data storage
user_sessions = {}


class UserSession:
    """Store user session data during booking process"""

    def __init__(self, user_id):
        self.user_id = user_id
        self.city_id = None
        self.district_id = None
        self.barbershop_id = None
        self.barber_id = None
        self.service_id = None
        self.booking_date = None
        self.booking_time = None
        self.notes = ""
        self.current_step = None


def get_user_session(user_id):
    """Get or create user session"""
    if user_id not in user_sessions:
        user_sessions[user_id] = UserSession(user_id)
    return user_sessions[user_id]


def clear_user_session(user_id):
    """Clear user session data"""
    if user_id in user_sessions:
        del user_sessions[user_id]

# -------------------- COMMAND HANDLERS --------------------


@bot.message_handler(commands=['start'])
def start_command(message):
    """Handle /start command"""
    user_id = message.from_user.id
    full_name = message.from_user.full_name
    username = message.from_user.username

    # Check if user is registered
    conn = sqlite3.connect('barbershop.db')
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (user_id,))
    user_exists = cursor.fetchone()
    conn.close()

    if user_exists:
        # User is registered, show main menu
        show_main_menu(message, user_id)
    else:
        # User needs to register - show language selection
        show_language_selection(message)


def show_language_selection(message):
    """Show language selection buttons"""
    markup = InlineKeyboardMarkup(row_width=2)

    for lang_code, lang_data in LANGUAGES.items():
        btn_text = f"{lang_data['emoji']} {lang_data['language_name']}"
        markup.add(InlineKeyboardButton(
            btn_text, callback_data=f"lang_{lang_code}"))

    bot.send_message(
        message.chat.id,
        "🌐 *NavbatGo - Barbershop Booking*\n\n"
        "Assalomu alaykum! Добро пожаловать! Welcome!\n\n"
        "👆 Пожалуйста, выберите язык / Please choose your language:",
        parse_mode='Markdown',
        reply_markup=markup
    )


@bot.message_handler(commands=['mybookings'])
def my_bookings_command(message):
    """Handle /mybookings command"""
    user_id = message.from_user.id

    # Check if user is registered
    conn = sqlite3.connect('barbershop.db')
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (user_id,))
    user = cursor.fetchone()
    conn.close()

    if not user:
        bot.send_message(
            message.chat.id, "❌ Сначала зарегистрируйтесь / Please register first")
        return

    show_my_bookings(message, user_id)


@bot.message_handler(commands=['help'])
def help_command(message):
    """Handle /help command"""
    user_id = message.from_user.id
    lang = get_user_language(user_id)

    help_text = f"""
🤖 *{get_text(user_id, 'help')} - NavbatGo*

📋 *{get_text(user_id, 'main_menu')}:*
/start - {get_text(user_id, 'main_menu')}
/mybookings - {get_text(user_id, 'my_bookings')}
/help - {get_text(user_id, 'help')}

💡 *{get_text(user_id, 'about')}:*
NavbatGo - это удобный бот для бронирования времени в парикмахерских. 
Выбирайте город, район, парикмахерскую, мастера и удобное время.

📞 *{get_text(user_id, 'contact_us')}:*
@support_navbatgo
    """

    bot.send_message(message.chat.id, help_text, parse_mode='Markdown')


@bot.message_handler(commands=['settings'])
def settings_command(message):
    """Handle /settings command"""
    user_id = message.from_user.id

    # Check if user is registered
    conn = sqlite3.connect('barbershop.db')
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (user_id,))
    user = cursor.fetchone()
    conn.close()

    if not user:
        bot.send_message(
            message.chat.id, "❌ Сначала зарегистрируйтесь / Please register first")
        return

    show_settings_menu(message, user_id)

# -------------------- REGISTRATION FLOW --------------------


@bot.callback_query_handler(func=lambda call: call.data.startswith('lang_'))
def handle_language_selection(call):
    """Handle language selection"""
    user_id = call.from_user.id
    lang_code = call.data.split('_')[1]

    # Ask for phone number
    markup = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(KeyboardButton(get_translation(
        lang_code, 'share_contact'), request_contact=True))
    markup.add(KeyboardButton(get_translation(lang_code, 'cancel')))

    bot.send_message(
        call.message.chat.id,
        f"{get_translation(lang_code, 'send_contact')}\n\n"
        f"📱 {get_translation(lang_code, 'send_contact')}",
        reply_markup=markup
    )

    # Store language in session temporarily
    user_sessions[user_id] = {'language': lang_code, 'step': 'waiting_contact'}


@bot.message_handler(content_types=['contact'])
def handle_contact(message):
    """Handle contact sharing"""
    user_id = message.from_user.id

    if user_id not in user_sessions or user_sessions[user_id].get('step') != 'waiting_contact':
        return

    phone_number = message.contact.phone_number
    full_name = message.from_user.full_name
    username = message.from_user.username
    language = user_sessions[user_id]['language']

    # Register user
    if register_user(user_id, full_name, username, phone_number, language):
        bot.send_message(
            message.chat.id,
            f"✅ {get_translation(language, 'thank_you')}!\n\n"
            f"👤 {get_translation(language, 'profile')}: {full_name}\n"
            f"📱 {get_translation(language, 'phone')}: {phone_number}\n\n"
            f"🎉 {get_translation(language, 'welcome')}",
            reply_markup=types.ReplyKeyboardRemove()
        )

        # Show main menu
        show_main_menu(message, user_id)
    else:
        bot.send_message(
            message.chat.id,
            "❌ Регистрация не удалась. Пожалуйста, попробуйте снова.",
            reply_markup=types.ReplyKeyboardRemove()
        )

    # Clear session
    if user_id in user_sessions:
        del user_sessions[user_id]

# -------------------- MAIN MENU --------------------


def show_main_menu(message, user_id):
    """Show main menu"""
    lang = get_user_language(user_id)

    markup = InlineKeyboardMarkup(row_width=2)

    markup.add(
        InlineKeyboardButton(
            f"{get_text(user_id, 'choose_barbershop')}", callback_data='book_new'),
        InlineKeyboardButton(
            f"{get_text(user_id, 'nearby')}", callback_data='nearby_shops')
    )

    markup.add(
        InlineKeyboardButton(
            f"{get_text(user_id, 'my_bookings')}", callback_data='my_bookings'),
        InlineKeyboardButton(
            f"{get_text(user_id, 'search')}", callback_data='search_shops')
    )

    markup.add(
        InlineKeyboardButton(
            f"{get_text(user_id, 'settings')}", callback_data='settings'),
        InlineKeyboardButton(
            f"{get_text(user_id, 'help')}", callback_data='help')
    )

    if isinstance(message, types.Message):
        bot.send_message(
            message.chat.id,
            f"*{get_text(user_id, 'main_menu')} - NavbatGo*\n\n"
            f"Выберите действие:",
            parse_mode='Markdown',
            reply_markup=markup
        )
    else:
        bot.edit_message_text(
            f"*{get_text(user_id, 'main_menu')} - NavbatGo*\n\n"
            f"Выберите действие:",
            message.chat.id,
            message.message_id,
            parse_mode='Markdown',
            reply_markup=markup
        )

# -------------------- BOOKING FLOW --------------------


@bot.callback_query_handler(func=lambda call: call.data == 'book_new')
def start_booking_flow(call):
    """Start new booking flow"""
    user_id = call.from_user.id
    lang = get_user_language(user_id)

    # Show city selection
    show_city_selection(call.message, user_id)


def show_city_selection(message, user_id):
    """Show city selection"""
    lang = get_user_language(user_id)
    cities = get_cities(lang)

    markup = InlineKeyboardMarkup(row_width=2)

    for city_id, city_name in cities:
        markup.add(InlineKeyboardButton(
            city_name, callback_data=f"city_{city_id}"))

    markup.add(InlineKeyboardButton(
        f"🔙 {get_text(user_id, 'back')}", callback_data='main_menu'))

    if isinstance(message, types.Message):
        bot.send_message(
            message.chat.id,
            f"🏙 *{get_text(user_id, 'choose_city')}*",
            parse_mode='Markdown',
            reply_markup=markup
        )
    else:
        bot.edit_message_text(
            f"🏙 *{get_text(user_id, 'choose_city')}*",
            message.chat.id,
            message.message_id,
            parse_mode='Markdown',
            reply_markup=markup
        )


@bot.callback_query_handler(func=lambda call: call.data.startswith('city_'))
def handle_city_selection(call):
    """Handle city selection"""
    user_id = call.from_user.id
    city_id = int(call.data.split('_')[1])

    # Store city in session
    session = get_user_session(user_id)
    session.city_id = city_id
    session.current_step = 'city_selected'

    # Show district selection
    show_district_selection(call.message, user_id, city_id)


def show_district_selection(message, user_id, city_id):
    """Show district selection for selected city"""
    lang = get_user_language(user_id)
    districts = get_districts(city_id, lang)

    markup = InlineKeyboardMarkup(row_width=2)

    # Add "All districts" option
    markup.add(InlineKeyboardButton(
        f"🌍 {get_text(user_id, 'all')}", callback_data=f"district_all"))

    for district_id, district_name in districts:
        markup.add(InlineKeyboardButton(district_name,
                   callback_data=f"district_{district_id}"))

    markup.add(
        InlineKeyboardButton(
            f"🔙 {get_text(user_id, 'back')}", callback_data='book_new'),
        InlineKeyboardButton(
            f"➡️ {get_text(user_id, 'next')}", callback_data='skip_district')
    )

    bot.edit_message_text(
        f"📍 *{get_text(user_id, 'choose_district')}*",
        message.chat.id,
        message.message_id,
        parse_mode='Markdown',
        reply_markup=markup
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith('district_'))
def handle_district_selection(call):
    """Handle district selection"""
    user_id = call.from_user.id
    district_data = call.data.split('_')[1]

    session = get_user_session(user_id)

    if district_data == 'all':
        session.district_id = None
    else:
        session.district_id = int(district_data)

    session.current_step = 'district_selected'

    # Show barbershops
    show_barbershops_selection(
        call.message, user_id, session.city_id, session.district_id)


@bot.callback_query_handler(func=lambda call: call.data == 'skip_district')
def skip_district(call):
    """Skip district selection"""
    user_id = call.from_user.id
    session = get_user_session(user_id)
    session.district_id = None
    session.current_step = 'district_skipped'

    # Show barbershops
    show_barbershops_selection(call.message, user_id, session.city_id, None)


def show_barbershops_selection(message, user_id, city_id, district_id):
    """Show barbershops in selected location"""
    lang = get_user_language(user_id)
    barbershops = get_barbershops_by_location(city_id, district_id, lang)

    if not barbershops:
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton(
            f"🔙 {get_text(user_id, 'back')}", callback_data=f"city_{city_id}"))

        bot.edit_message_text(
            f"❌ *{get_text(user_id, 'no_results')}*\n\n"
            f"В выбранном районе пока нет активных парикмахерских.",
            message.chat.id,
            message.message_id,
            parse_mode='Markdown',
            reply_markup=markup
        )
        return

    markup = InlineKeyboardMarkup(row_width=1)

    for shop in barbershops[:10]:  # Show first 10 shops
        shop_id, name, address, phone, rating, description = shop
        rating_str = "⭐" * int(rating) if rating else "⭐"
        btn_text = f"{rating_str} {name}"
        if address and len(address) > 20:
            address_preview = address[:20] + "..."
            btn_text += f"\n📍 {address_preview}"

        markup.add(InlineKeyboardButton(
            btn_text, callback_data=f"shop_{shop_id}"))

    # Add navigation buttons
    nav_buttons = []
    nav_buttons.append(InlineKeyboardButton(
        f"🔙 {get_text(user_id, 'back')}", callback_data=f"city_{city_id}"))

    if len(barbershops) > 10:
        nav_buttons.append(InlineKeyboardButton(
            f"➡️ {get_text(user_id, 'next')}", callback_data='more_shops'))

    markup.row(*nav_buttons)

    bot.edit_message_text(
        f"✂️ *{get_text(user_id, 'choose_barbershop')}*\n\n"
        f"Найдено {len(barbershops)} парикмахерских:",
        message.chat.id,
        message.message_id,
        parse_mode='Markdown',
        reply_markup=markup
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith('shop_'))
def handle_barbershop_selection(call):
    """Handle barbershop selection"""
    user_id = call.from_user.id
    shop_id = int(call.data.split('_')[1])

    # Store barbershop in session
    session = get_user_session(user_id)
    session.barbershop_id = shop_id
    session.current_step = 'shop_selected'

    # Show barbershop details
    show_barbershop_details(call.message, user_id, shop_id)


def show_barbershop_details(message, user_id, shop_id):
    """Show detailed information about barbershop"""
    lang = get_user_language(user_id)
    details = get_barbershop_details(shop_id, lang)

    if not details:
        bot.edit_message_text(
            "❌ Ошибка загрузки информации о парикмахерской.",
            message.chat.id,
            message.message_id
        )
        return

    # Create message with details
    details_text = f"*{details['name']}*\n\n"

    if details['rating']:
        details_text += f"⭐ Рейтинг: {details['rating']}/5\n"

    if details['address']:
        details_text += f"📍 Адрес: {details['address']}\n"

    if details['city']:
        details_text += f"🏙 Город: {details['city']}"
        if details['district']:
            details_text += f", {details['district']}"
        details_text += "\n"

    if details['phone']:
        details_text += f"📞 Телефон: {details['phone']}\n"

    if details['description']:
        details_text += f"\n📝 Описание:\n{details['description']}\n"

    if details['services']:
        details_text += f"\n💈 Услуги:\n"
        for service in details['services'][:5]:  # Show first 5 services
            service_id, service_name, price, duration = service
            details_text += f"  • {service_name}: {price} сум ({duration} мин)\n"

    if details['barbers']:
        details_text += f"\n💇 Мастера ({len(details['barbers'])}):\n"
        for barber in details['barbers'][:3]:  # Show first 3 barbers
            barber_id, name, exp, specialty, rating, desc = barber
            details_text += f"  • {name}"
            if exp:
                details_text += f" ({exp} лет опыта)"
            if specialty:
                details_text += f" - {specialty}"
            details_text += "\n"

    markup = InlineKeyboardMarkup(row_width=2)

    # Main action buttons
    markup.add(
        InlineKeyboardButton("💇 Выбрать мастера",
                             callback_data=f"choose_barber_{shop_id}"),
        InlineKeyboardButton("🗺 Показать на карте",
                             callback_data=f"map_{shop_id}")
    )

    # Additional info buttons
    if details['photos']:
        markup.add(InlineKeyboardButton(
            "📸 Фото", callback_data=f"photos_{shop_id}"))

    if len(details['barbers']) > 3:
        markup.add(InlineKeyboardButton("👥 Все мастера",
                   callback_data=f"all_barbers_{shop_id}"))

    if len(details['services']) > 5:
        markup.add(InlineKeyboardButton("💈 Все услуги",
                   callback_data=f"all_services_{shop_id}"))

    # Navigation
    markup.add(
        InlineKeyboardButton("📞 Позвонить", callback_data=f"call_{shop_id}"),
        InlineKeyboardButton("🔙 Назад", callback_data=f"back_to_shops")
    )

    # Send photos if available
    if details['photos']:
        main_photo = None
        other_photos = []

        for photo in details['photos']:
            photo_id, caption, is_main = photo
            if is_main and not main_photo:
                main_photo = photo_id
            else:
                other_photos.append(photo_id)

        if main_photo:
            try:
                bot.send_photo(
                    message.chat.id,
                    main_photo,
                    caption=details_text[:1000],
                    parse_mode='Markdown',
                    reply_markup=markup
                )
                bot.delete_message(message.chat.id, message.message_id)
                return
            except:
                pass

    # If no photos or photo sending failed, send text message
    bot.edit_message_text(
        details_text[:4000],
        message.chat.id,
        message.message_id,
        parse_mode='Markdown',
        reply_markup=markup
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith('choose_barber_'))
def handle_choose_barber(call):
    """Handle choose barber button"""
    user_id = call.from_user.id
    shop_id = int(call.data.split('_')[2])

    # Store barbershop in session
    session = get_user_session(user_id)
    session.barbershop_id = shop_id

    # Show barbers selection
    show_barbers_selection(call.message, user_id, shop_id)


def show_barbers_selection(message, user_id, shop_id):
    """Show barbers for selected barbershop"""
    lang = get_user_language(user_id)
    details = get_barbershop_details(shop_id, lang)

    if not details or not details['barbers']:
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton(
            f"🔙 {get_text(user_id, 'back')}", callback_data=f"shop_{shop_id}"))

        bot.edit_message_text(
            f"❌ В этой парикмахерской пока нет активных мастеров.",
            message.chat.id,
            message.message_id,
            parse_mode='Markdown',
            reply_markup=markup
        )
        return

    markup = InlineKeyboardMarkup(row_width=1)

    for barber in details['barbers']:
        barber_id, name, exp, specialty, rating, desc = barber

        btn_text = f"💇 {name}"
        if exp:
            btn_text += f" ({exp} лет)"
        if specialty:
            btn_text += f" - {specialty}"
        if rating:
            btn_text += f" ⭐{rating}"

        markup.add(InlineKeyboardButton(
            btn_text, callback_data=f"barber_{barber_id}"))

    markup.add(InlineKeyboardButton(
        f"🔙 {get_text(user_id, 'back')}", callback_data=f"shop_{shop_id}"))

    bot.edit_message_text(
        f"💇 *{get_text(user_id, 'choose_barber')}*\n\n"
        f"Выберите мастера:",
        message.chat.id,
        message.message_id,
        parse_mode='Markdown',
        reply_markup=markup
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith('barber_'))
def handle_barber_selection(call):
    """Handle barber selection"""
    user_id = call.from_user.id
    barber_id = int(call.data.split('_')[1])

    # Store barber in session
    session = get_user_session(user_id)
    session.barber_id = barber_id
    session.current_step = 'barber_selected'

    # Show service selection or date selection
    show_service_selection(call.message, user_id, session.barbershop_id)


def show_service_selection(message, user_id, shop_id):
    """Show services for selected barbershop"""
    lang = get_user_language(user_id)
    details = get_barbershop_details(shop_id, lang)

    if not details or not details['services']:
        # Skip service selection if no services
        show_date_selection(message, user_id)
        return

    markup = InlineKeyboardMarkup(row_width=1)

    for service in details['services']:
        service_id, name, price, duration = service
        btn_text = f"💈 {name} - {price} сум ({duration} мин)"
        markup.add(InlineKeyboardButton(
            btn_text, callback_data=f"service_{service_id}"))

    markup.add(
        InlineKeyboardButton(f"⏭ Пропустить", callback_data='skip_service'),
        InlineKeyboardButton(
            f"🔙 {get_text(user_id, 'back')}", callback_data=f"choose_barber_{shop_id}")
    )

    bot.edit_message_text(
        f"💈 *{get_text(user_id, 'choose_service')}*\n\n"
        f"Выберите услугу (опционально):",
        message.chat.id,
        message.message_id,
        parse_mode='Markdown',
        reply_markup=markup
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith('service_'))
def handle_service_selection(call):
    """Handle service selection"""
    user_id = call.from_user.id
    service_id = int(call.data.split('_')[1])

    # Store service in session
    session = get_user_session(user_id)
    session.service_id = service_id

    # Show date selection
    show_date_selection(call.message, user_id)


@bot.callback_query_handler(func=lambda call: call.data == 'skip_service')
def skip_service_selection(call):
    """Skip service selection"""
    user_id = call.from_user.id
    session = get_user_session(user_id)
    session.service_id = None

    # Show date selection
    show_date_selection(call.message, user_id)


def show_date_selection(message, user_id):
    """Show date selection"""
    lang = get_user_language(user_id)

    # Generate next 7 days
    today = datetime.now()
    dates = []

    for i in range(14):  # Show next 14 days
        date = today + timedelta(days=i)
        date_str = date.strftime("%Y-%m-%d")

        if i == 0:
            display = f"📅 {get_text(user_id, 'today')} ({date.strftime('%d.%m')})"
        elif i == 1:
            display = f"📅 {get_text(user_id, 'tomorrow')} ({date.strftime('%d.%m')})"
        else:
            weekday = date.strftime('%A')
            weekday_ru = {
                'Monday': 'Пн', 'Tuesday': 'Вт', 'Wednesday': 'Ср',
                'Thursday': 'Чт', 'Friday': 'Пт', 'Saturday': 'Сб', 'Sunday': 'Вс'
            }.get(weekday, weekday)
            display = f"📅 {date.strftime('%d.%m')} ({weekday_ru})"

        dates.append((date_str, display))

    markup = InlineKeyboardMarkup(row_width=2)

    # Add dates in rows of 2
    row = []
    for date_str, display in dates[:8]:  # Show first 8 days
        row.append(InlineKeyboardButton(
            display, callback_data=f"date_{date_str}"))
        if len(row) == 2:
            markup.row(*row)
            row = []

    if row:  # Add remaining button if any
        markup.row(*row)

    # Add more dates button if needed
    if len(dates) > 8:
        markup.add(InlineKeyboardButton(
            "➡️ Еще даты", callback_data="more_dates"))

    session = get_user_session(user_id)
    markup.add(InlineKeyboardButton(
        f"🔙 {get_text(user_id, 'back')}", callback_data=f"choose_barber_{session.barbershop_id}"))

    bot.edit_message_text(
        f"📅 *{get_text(user_id, 'choose_date')}*\n\n"
        f"Выберите удобную дату:",
        message.chat.id,
        message.message_id,
        parse_mode='Markdown',
        reply_markup=markup
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith('date_'))
def handle_date_selection(call):
    """Handle date selection"""
    user_id = call.from_user.id
    date_str = call.data.split('_')[1]

    # Store date in session
    session = get_user_session(user_id)
    session.booking_date = date_str

    # Show time selection
    show_time_selection(call.message, user_id, session.barber_id, date_str)


def show_time_selection(message, user_id, barber_id, date_str):
    """Show available time slots"""
    lang = get_user_language(user_id)
    available_slots = get_available_time_slots(barber_id, date_str)

    if not available_slots:
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton(
            f"🔙 {get_text(user_id, 'back')}", callback_data='back_to_dates'))

        bot.edit_message_text(
            f"❌ На эту дату нет свободных слотов.\n"
            f"Пожалуйста, выберите другую дату.",
            message.chat.id,
            message.message_id,
            parse_mode='Markdown',
            reply_markup=markup
        )
        return

    markup = InlineKeyboardMarkup(row_width=4)

    # Add time slots
    row = []
    for time_slot in available_slots[:16]:  # Show first 16 slots
        row.append(InlineKeyboardButton(
            time_slot, callback_data=f"time_{time_slot}"))
        if len(row) == 4:
            markup.row(*row)
            row = []

    if row:
        markup.row(*row)

    # Add navigation
    session = get_user_session(user_id)
    markup.add(InlineKeyboardButton(
        f"🔙 {get_text(user_id, 'back')}", callback_data='back_to_dates'))

    # Format date for display
    date_obj = datetime.strptime(date_str, "%Y-%m-%d")
    display_date = date_obj.strftime("%d.%m.%Y")

    bot.edit_message_text(
        f"⏰ *{get_text(user_id, 'choose_time')}*\n\n"
        f"📅 Дата: {display_date}\n"
        f"Доступные время:",
        message.chat.id,
        message.message_id,
        parse_mode='Markdown',
        reply_markup=markup
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith('time_'))
def handle_time_selection(call):
    """Handle time selection"""
    user_id = call.from_user.id
    time_str = call.data.split('_')[1]

    # Store time in session
    session = get_user_session(user_id)
    session.booking_time = time_str

    # Show booking confirmation
    show_booking_confirmation(call.message, user_id)


def show_booking_confirmation(message, user_id):
    """Show booking confirmation with all details"""
    session = get_user_session(user_id)
    lang = get_user_language(user_id)

    # Get all details
    conn = sqlite3.connect('barbershop.db')
    cursor = conn.cursor()

    # Get barbershop name
    cursor.execute("SELECT name FROM barbershops WHERE id = ?",
                   (session.barbershop_id,))
    shop_name = cursor.fetchone()[0]

    # Get barber name
    cursor.execute("SELECT full_name FROM barbers WHERE id = ?",
                   (session.barber_id,))
    barber_name = cursor.fetchone()[0]

    # Get service name if selected
    service_name = None
    if session.service_id:
        if lang == 'uz':
            cursor.execute(
                "SELECT name_uz FROM services WHERE id = ?", (session.service_id,))
        elif lang == 'ru':
            cursor.execute(
                "SELECT name_ru FROM services WHERE id = ?", (session.service_id,))
        else:
            cursor.execute(
                "SELECT name_en FROM services WHERE id = ?", (session.service_id,))
        result = cursor.fetchone()
        service_name = result[0] if result else None

    conn.close()

    # Format confirmation message
    confirmation_text = f"✅ *{get_text(user_id, 'booking_confirmed')}*\n\n"
    confirmation_text += f"📋 {get_text(user_id, 'booking_details')}:\n\n"
    confirmation_text += f"🏢 {get_text(user_id, 'name')}: {shop_name}\n"
    confirmation_text += f"💇 {get_text(user_id, 'barber')}: {barber_name}\n"

    if service_name:
        confirmation_text += f"💈 {get_text(user_id, 'services')}: {service_name}\n"

    confirmation_text += f"📅 {get_text(user_id, 'date')}: {session.booking_date}\n"
    confirmation_text += f"⏰ {get_text(user_id, 'time')}: {session.booking_time}\n\n"
    confirmation_text += "📍 *Примечание:*\n"
    confirmation_text += "• Пожалуйста, приходите за 5-10 минут до назначенного времени\n"
    confirmation_text += "• В случае опоздания более 15 минут, бронь может быть отменена\n"
    confirmation_text += "• Для отмены бронирования используйте раздел 'Мои бронирования'\n\n"
    confirmation_text += "Спасибо за выбор NavbatGo! 🎉"

    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("✅ Подтвердить бронь",
                             callback_data="confirm_booking"),
        InlineKeyboardButton("✏️ Добавить заметку", callback_data="add_notes")
    )
    markup.add(InlineKeyboardButton(
        "❌ Отменить", callback_data="cancel_booking"))

    bot.edit_message_text(
        confirmation_text,
        message.chat.id,
        message.message_id,
        parse_mode='Markdown',
        reply_markup=markup
    )


@bot.callback_query_handler(func=lambda call: call.data == 'confirm_booking')
def handle_booking_confirmation(call):
    """Handle booking confirmation"""
    user_id = call.from_user.id
    session = get_user_session(user_id)

    # Create booking in database
    booking_id, booking_info = create_booking(
        user_id,
        session.barber_id,
        session.barbershop_id,
        session.service_id,
        session.booking_date,
        session.booking_time,
        session.notes
    )

    if booking_id:
        # Format success message
        lang = get_user_language(user_id)
        success_text = f"🎉 *{get_text(user_id, 'booking_confirmed')}*\n\n"
        success_text += format_booking_details(booking_info, lang)
        success_text += "\n\n"
        success_text += "✅ Бронь успешно создана!\n"
        success_text += "📱 Вы получите уведомление за 1 час до назначенного времени.\n"
        success_text += "❌ Для отмены брони используйте раздел 'Мои бронирования'.\n\n"
        success_text += "Спасибо за использование NavbatGo! ✨"

        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton(
            f"🏠 {get_text(user_id, 'main_menu')}", callback_data="main_menu"))
        markup.add(InlineKeyboardButton(
            f"📒 {get_text(user_id, 'my_bookings')}", callback_data="my_bookings"))

        bot.edit_message_text(
            success_text,
            call.message.chat.id,
            call.message.message_id,
            parse_mode='Markdown',
            reply_markup=markup
        )

        # Clear session
        clear_user_session(user_id)

        # Send notification to barbershop owner
        try:
            send_booking_notifications(booking_id, bot)
        except Exception as e:
            print(f'Notification error: {e}')

    else:
        bot.answer_callback_query(
            call.id, "❌ Ошибка при создании брони. Пожалуйста, попробуйте снова.")

# -------------------- MY BOOKINGS --------------------


def show_my_bookings(message, user_id):
    """Show user's bookings"""
    lang = get_user_language(user_id)
    bookings = get_user_bookings(user_id)

    if not bookings:
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton(
            f"🏠 {get_text(user_id, 'main_menu')}", callback_data="main_menu"))

        if isinstance(message, types.Message):
            bot.send_message(
                message.chat.id,
                f"📭 *{get_text(user_id, 'no_bookings')}*\n\n"
                f"У вас пока нет активных бронирований.",
                parse_mode='Markdown',
                reply_markup=markup
            )
        else:
            bot.edit_message_text(
                f"📭 *{get_text(user_id, 'no_bookings')}*\n\n"
                f"У вас пока нет активных бронирований.",
                message.chat.id,
                message.message_id,
                parse_mode='Markdown',
                reply_markup=markup
            )
        return

    # Group bookings by status
    active_bookings = []
    past_bookings = []

    today = datetime.now().date()

    for booking in bookings:
        booking_id, shop_name, barber_name, date_str, time_str, status, service_name, price = booking

        booking_date = datetime.strptime(date_str, "%Y-%m-%d").date()

        if status in ['pending', 'confirmed'] and booking_date >= today:
            active_bookings.append(booking)
        else:
            past_bookings.append(booking)

    # Create message with active bookings
    text = f"📒 *{get_text(user_id, 'my_bookings')}*\n\n"

    if active_bookings:
        text += "🟢 *Активные брони:*\n\n"
        # Show first 5 active bookings
        for i, booking in enumerate(active_bookings[:5], 1):
            booking_id, shop_name, barber_name, date_str, time_str, status, service_name, price = booking

            status_emoji = {
                'pending': '⏳',
                'confirmed': '✅',
                'cancelled': '❌',
                'completed': '🏁'
            }.get(status, '❓')

            text += f"{i}. {status_emoji} *{shop_name}*\n"
            text += f"   💇 {barber_name}\n"
            if service_name:
                text += f"   💈 {service_name}"
                if price:
                    text += f" - {price} сум"
                text += "\n"
            text += f"   📅 {date_str} ⏰ {time_str}\n"
            text += f"   [ID: {booking_id}]\n\n"

    if past_bookings:
        text += "🔵 *Прошлые брони:*\n\n"
        # Show first 3 past bookings
        for i, booking in enumerate(past_bookings[:3], 1):
            booking_id, shop_name, barber_name, date_str, time_str, status, service_name, price = booking

            status_emoji = {
                'pending': '⏳',
                'confirmed': '✅',
                'cancelled': '❌',
                'completed': '🏁'
            }.get(status, '❓')

            text += f"{i}. {status_emoji} {shop_name}\n"
            text += f"   {date_str} {time_str}\n\n"

    markup = InlineKeyboardMarkup(row_width=2)

    # Add buttons for active bookings
    if active_bookings:
        # Add buttons for first 3 active bookings
        for booking in active_bookings[:3]:
            booking_id, shop_name, barber_name, date_str, time_str, status, service_name, price = booking
            btn_text = f"📋 {date_str} {time_str[:5]}"
            markup.add(InlineKeyboardButton(
                btn_text, callback_data=f"view_booking_{booking_id}"))

    markup.add(
        InlineKeyboardButton(
            f"🏠 {get_text(user_id, 'main_menu')}", callback_data="main_menu"),
        InlineKeyboardButton(f"🔄 Обновить", callback_data="refresh_bookings")
    )

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


@bot.callback_query_handler(func=lambda call: call.data.startswith('view_booking_'))
def handle_view_booking(call):
    """View booking details"""
    user_id = call.from_user.id
    booking_id = int(call.data.split('_')[2])

    # Get booking details
    conn = sqlite3.connect('barbershop.db')
    cursor = conn.cursor()

    cursor.execute('''
        SELECT bk.id, b.name, br.full_name, bk.booking_date, bk.booking_time, bk.status,
               s.name_uz, s.price, bk.notes, b.phone, b.address
        FROM bookings bk
        JOIN barbershops b ON bk.barbershop_id = b.id
        JOIN barbers br ON bk.barber_id = br.id
        LEFT JOIN services s ON bk.service_id = s.id
        WHERE bk.id = ? AND bk.client_id = ?
    ''', (booking_id, user_id))

    booking = cursor.fetchone()
    conn.close()

    if not booking:
        bot.answer_callback_query(call.id, "❌ Бронь не найдена")
        return

    (booking_id, shop_name, barber_name, date_str, time_str,
     status, service_name, price, notes, shop_phone, shop_address) = booking

    # Format status
    status_texts = {
        'pending': '⏳ Ожидает подтверждения',
        'confirmed': '✅ Подтверждена',
        'cancelled': '❌ Отменена',
        'completed': '🏁 Завершена'
    }

    status_display = status_texts.get(status, status)

    # Format details
    details = f"📋 *Детали бронирования*\n\n"
    details += f"🏢 *Парикмахерская:* {shop_name}\n"
    details += f"💇 *Мастер:* {barber_name}\n"

    if service_name:
        details += f"💈 *Услуга:* {service_name}"
        if price:
            details += f" ({price} сум)"
        details += "\n"

    details += f"📅 *Дата:* {date_str}\n"
    details += f"⏰ *Время:* {time_str}\n"
    details += f"📊 *Статус:* {status_display}\n\n"

    if shop_address:
        details += f"📍 *Адрес:* {shop_address}\n"

    if shop_phone:
        details += f"📞 *Телефон:* {shop_phone}\n"

    if notes:
        details += f"📝 *Заметки:* {notes}\n"

    markup = InlineKeyboardMarkup(row_width=2)

    # Add action buttons based on status
    if status in ['pending', 'confirmed']:
        markup.add(
            InlineKeyboardButton(
                "❌ Отменить бронь", callback_data=f"cancel_my_booking_{booking_id}"),
            InlineKeyboardButton(
                "📞 Позвонить", callback_data=f"call_shop_{booking_id}")
        )

    markup.add(
        InlineKeyboardButton("🔙 Назад к броням", callback_data="my_bookings"),
        InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")
    )

    bot.edit_message_text(
        details,
        call.message.chat.id,
        call.message.message_id,
        parse_mode='Markdown',
        reply_markup=markup
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith('cancel_my_booking_'))
def handle_cancel_booking(call):
    """Cancel user's booking"""
    user_id = call.from_user.id
    booking_id = int(call.data.split('_')[3])

    # Update booking status
    conn = sqlite3.connect('barbershop.db')
    cursor = conn.cursor()

    cursor.execute("UPDATE bookings SET status = 'cancelled' WHERE id = ? AND client_id = ?",
                   (booking_id, user_id))
    conn.commit()
    conn.close()

    bot.answer_callback_query(call.id, "✅ Бронь отменена")

    # Go back to bookings list
    show_my_bookings(call.message, user_id)

# -------------------- NEARBY SHOPS --------------------


@bot.callback_query_handler(func=lambda call: call.data == 'nearby_shops')
def handle_nearby_shops(call):
    """Handle nearby shops request"""
    user_id = call.from_user.id
    lang = get_user_language(user_id)

    # Ask for location
    markup = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(KeyboardButton(
        f"📍 {get_text(user_id, 'send_location')}", request_location=True))
    markup.add(KeyboardButton(f"❌ {get_text(user_id, 'cancel')}"))

    bot.send_message(
        call.message.chat.id,
        f"📍 *{get_text(user_id, 'nearby')}*\n\n"
        f"Пожалуйста, отправьте ваше местоположение, "
        f"чтобы найти ближайшие парикмахерские:",
        parse_mode='Markdown',
        reply_markup=markup
    )

    # Store in session
    user_sessions[user_id] = {'action': 'waiting_location'}


@bot.message_handler(content_types=['location'])
def handle_location(message):
    """Handle location sharing"""
    user_id = message.from_user.id

    if user_id not in user_sessions or user_sessions[user_id].get('action') != 'waiting_location':
        return

    latitude = message.location.latitude
    longitude = message.location.longitude

    # Get nearby shops
    lang = get_user_language(user_id)
    nearby_shops = get_nearby_barbershops(latitude, longitude, radius_km=5)

    if not nearby_shops:
        bot.send_message(
            message.chat.id,
            "❌ В радиусе 5 км не найдено парикмахерских.",
            reply_markup=types.ReplyKeyboardRemove()
        )
        return

    # Show nearby shops
    text = f"📍 *Ближайшие парикмахерские*\n\n"
    text += f"Найдено {len(nearby_shops)} парикмахерских рядом с вами:\n\n"

    for i, shop in enumerate(nearby_shops[:5], 1):  # Show first 5
        text += f"{i}. *{shop['name']}*\n"
        text += f"   📍 {shop['address'] or 'Адрес не указан'}\n"
        if shop['rating']:
            text += f"   ⭐ Рейтинг: {shop['rating']}/5\n"
        text += f"   📏 Расстояние: {shop['distance']} км\n"
        if shop['phone']:
            text += f"   📞 {shop['phone']}\n"
        text += "\n"

    markup = InlineKeyboardMarkup(row_width=1)

    for shop in nearby_shops[:3]:  # Add buttons for first 3 shops
        markup.add(InlineKeyboardButton(
            f"✂️ {shop['name']}", callback_data=f"shop_{shop['id']}"))

    markup.add(InlineKeyboardButton(
        f"🏠 {get_text(user_id, 'main_menu')}", callback_data="main_menu"))

    bot.send_message(
        message.chat.id,
        text,
        parse_mode='Markdown',
        reply_markup=markup
    )

    # Clear session
    del user_sessions[user_id]

# -------------------- SEARCH FUNCTIONALITY --------------------


@bot.callback_query_handler(func=lambda call: call.data == 'search_shops')
def handle_search_shops(call):
    """Handle search request"""
    user_id = call.from_user.id

    bot.send_message(
        call.message.chat.id,
        "🔍 *Поиск парикмахерских*\n\n"
        "Введите название парикмахерской или мастера:",
        parse_mode='Markdown'
    )

    # Store in session
    user_sessions[user_id] = {'action': 'waiting_search'}


@bot.message_handler(func=lambda message:
                     message.from_user.id in user_sessions and
                     user_sessions[message.from_user.id].get('action') == 'waiting_search')
def handle_search_query(message):
    """Handle search query"""
    user_id = message.from_user.id
    query = message.text.strip()

    if not query or len(query) < 2:
        bot.send_message(
            message.chat.id, "❌ Пожалуйста, введите минимум 2 символа")
        return

    # Search in database
    conn = sqlite3.connect('barbershop.db')
    cursor = conn.cursor()

    search_pattern = f"%{query}%"

    # Search barbershops
    cursor.execute('''
        SELECT id, name, address, rating 
        FROM barbershops 
        WHERE is_active = 1 AND (name LIKE ? OR address LIKE ?)
        LIMIT 10
    ''', (search_pattern, search_pattern))

    shops = cursor.fetchall()

    # Search barbers
    cursor.execute('''
        SELECT b.id, br.full_name, b.name, b.address
        FROM barbers br
        JOIN barbershops b ON br.barbershop_id = b.id
        WHERE br.is_active = 1 AND b.is_active = 1 AND br.full_name LIKE ?
        LIMIT 10
    ''', (search_pattern,))

    barbers = cursor.fetchall()
    conn.close()

    # Prepare results
    text = f"🔍 *Результаты поиска для: '{query}'*\n\n"

    if not shops and not barbers:
        text += "❌ Ничего не найдено"
    else:
        if shops:
            text += "🏢 *Парикмахерские:*\n\n"
            for shop_id, name, address, rating in shops[:5]:
                rating_str = f"⭐ {rating}" if rating else ""
                text += f"• *{name}*\n"
                if address:
                    text += f"  📍 {address[:50]}\n"
                if rating_str:
                    text += f"  {rating_str}\n"
                text += f"  [ID: {shop_id}]\n\n"

        if barbers:
            text += "💇 *Мастера:*\n\n"
            for barber_id, barber_name, shop_name, shop_address in barbers[:5]:
                text += f"• *{barber_name}*\n"
                text += f"  🏢 {shop_name}\n"
                if shop_address:
                    text += f"  📍 {shop_address[:50]}\n"
                text += f"  [ID: {barber_id}]\n\n"

    markup = InlineKeyboardMarkup(row_width=1)

    # Add buttons for shops
    for shop_id, name, address, rating in shops[:3]:
        markup.add(InlineKeyboardButton(
            f"🏢 {name}", callback_data=f"shop_{shop_id}"))

    # Add buttons for barbers
    for barber_id, barber_name, shop_name, shop_address in barbers[:3]:
        markup.add(InlineKeyboardButton(
            f"💇 {barber_name} ({shop_name})", callback_data=f"barber_{barber_id}"))

    markup.add(InlineKeyboardButton(
        f"🏠 {get_text(user_id, 'main_menu')}", callback_data="main_menu"))

    bot.send_message(
        message.chat.id,
        text[:4000],
        parse_mode='Markdown',
        reply_markup=markup
    )

    # Clear session
    del user_sessions[user_id]

# -------------------- SETTINGS --------------------


def show_settings_menu(message, user_id):
    """Show settings menu"""
    lang = get_user_language(user_id)

    # Get user info
    conn = sqlite3.connect('barbershop.db')
    cursor = conn.cursor()
    cursor.execute(
        "SELECT full_name, phone FROM users WHERE telegram_id = ?", (user_id,))
    user_info = cursor.fetchone()
    conn.close()

    full_name, phone = user_info if user_info else ("Не указано", "Не указано")

    text = f"⚙️ *{get_text(user_id, 'settings')}*\n\n"
    text += f"👤 *{get_text(user_id, 'profile')}:*\n"
    text += f"   • {get_text(user_id, 'name')}: {full_name}\n"
    text += f"   • {get_text(user_id, 'phone')}: {phone}\n"
    text += f"   • {get_text(user_id, 'language')}: {LANGUAGES[lang]['language_name']} {LANGUAGES[lang]['emoji']}\n\n"
    text += "Выберите действие:"

    markup = InlineKeyboardMarkup(row_width=2)

    markup.add(
        InlineKeyboardButton(
            f"✏️ {get_text(user_id, 'edit_profile')}", callback_data="edit_profile"),
        InlineKeyboardButton(
            f"🌐 {get_text(user_id, 'language')}", callback_data="change_language")
    )

    markup.add(
        InlineKeyboardButton(
            f"🔔 {get_text(user_id, 'notifications')}", callback_data="notifications"),
        InlineKeyboardButton(
            f"ℹ️ {get_text(user_id, 'about')}", callback_data="about_bot")
    )

    markup.add(InlineKeyboardButton(
        f"🏠 {get_text(user_id, 'main_menu')}", callback_data="main_menu"))

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


@bot.callback_query_handler(func=lambda call: call.data == 'edit_profile')
def handle_edit_profile(call):
    """Handle edit profile request"""
    user_id = call.from_user.id
    lang = get_user_language(user_id)

    text = f"✏️ *{get_text(user_id, 'edit_profile')}*\n\n"
    text += "Что вы хотите изменить?"

    markup = InlineKeyboardMarkup(row_width=2)

    markup.add(
        InlineKeyboardButton(
            f"👤 {get_text(user_id, 'change_name')}", callback_data="change_name"),
        InlineKeyboardButton(
            f"📱 {get_text(user_id, 'change_phone')}", callback_data="change_phone")
    )

    markup.add(InlineKeyboardButton(
        f"🔙 {get_text(user_id, 'back')}", callback_data="settings"))

    bot.edit_message_text(
        text,
        call.message.chat.id,
        call.message.message_id,
        parse_mode='Markdown',
        reply_markup=markup
    )


@bot.callback_query_handler(func=lambda call: call.data == 'change_language')
def handle_change_language(call):
    """Handle change language request"""
    user_id = call.from_user.id

    markup = InlineKeyboardMarkup(row_width=2)

    for lang_code, lang_data in LANGUAGES.items():
        btn_text = f"{lang_data['emoji']} {lang_data['language_name']}"
        markup.add(InlineKeyboardButton(
            btn_text, callback_data=f"set_lang_{lang_code}"))

    markup.add(InlineKeyboardButton(
        f"🔙 {get_text(user_id, 'back')}", callback_data="settings"))

    bot.edit_message_text(
        f"🌐 *{get_text(user_id, 'language')}*\n\n"
        f"Выберите язык интерфейса:",
        call.message.chat.id,
        call.message.message_id,
        parse_mode='Markdown',
        reply_markup=markup
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith('set_lang_'))
def handle_set_language(call):
    """Set user language"""
    user_id = call.from_user.id
    lang_code = call.data.split('_')[2]

    # Update language in database
    conn = sqlite3.connect('barbershop.db')
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET language = ? WHERE telegram_id = ?", (lang_code, user_id))
    conn.commit()
    conn.close()

    bot.answer_callback_query(
        call.id, f"✅ Язык изменен на {LANGUAGES[lang_code]['language_name']}")

    # Return to settings
    show_settings_menu(call.message, user_id)

# -------------------- NOTIFICATION SYSTEM --------------------


def send_reminders():
    """Send booking reminders"""
    while True:
        try:
            conn = sqlite3.connect('barbershop.db')
            cursor = conn.cursor()

            # Get current time
            now = datetime.now()

            # 1 hour before reminder
            reminder_time = (now + timedelta(hours=1)
                             ).strftime("%Y-%m-%d %H:%M")

            cursor.execute('''
                SELECT bk.client_id, b.name, br.full_name, bk.booking_date, bk.booking_time
                FROM bookings bk
                JOIN barbershops b ON bk.barbershop_id = b.id
                JOIN barbers br ON bk.barber_id = br.id
                WHERE bk.status = 'confirmed'
                AND datetime(bk.booking_date || ' ' || bk.booking_time) 
                BETWEEN datetime(?, '-1 minute') AND datetime(?, '+1 minute')
            ''', (reminder_time, reminder_time))

            for booking in cursor.fetchall():
                client_id, shop_name, barber_name, date, time = booking

                reminder_text = f"⏰ *Напоминание о бронировании*\n\n"
                reminder_text += f"Через 1 час у вас запись:\n\n"
                reminder_text += f"🏢 *{shop_name}*\n"
                reminder_text += f"💇 *{barber_name}*\n"
                reminder_text += f"📅 *Дата:* {date}\n"
                reminder_text += f"⏰ *Время:* {time}\n\n"
                reminder_text += "📍 Пожалуйста, приходите вовремя!"

                try:
                    bot.send_message(client_id, reminder_text,
                                     parse_mode='Markdown')
                except:
                    pass

            # 30 minutes before reminder
            reminder_time = (now + timedelta(minutes=30)
                             ).strftime("%Y-%m-%d %H:%M")

            cursor.execute('''
                SELECT bk.client_id, b.name, br.full_name, bk.booking_date, bk.booking_time
                FROM bookings bk
                JOIN barbershops b ON bk.barbershop_id = b.id
                JOIN barbers br ON bk.barber_id = br.id
                WHERE bk.status = 'confirmed'
                AND datetime(bk.booking_date || ' ' || bk.booking_time) 
                BETWEEN datetime(?, '-1 minute') AND datetime(?, '+1 minute')
            ''', (reminder_time, reminder_time))

            for booking in cursor.fetchall():
                client_id, shop_name, barber_name, date, time = booking

                reminder_text = f"⏰ *Скоро ваша запись*\n\n"
                reminder_text += f"Через 30 минут у вас запись:\n\n"
                reminder_text += f"🏢 *{shop_name}*\n"
                reminder_text += f"💇 *{barber_name}*\n"
                reminder_text += f"📅 *Дата:* {date}\n"
                reminder_text += f"⏰ *Время:* {time}\n\n"
                reminder_text += "📍 Пожалуйста, не опаздывайте!"

                try:
                    bot.send_message(client_id, reminder_text,
                                     parse_mode='Markdown')
                except:
                    pass

            conn.close()

        except Exception as e:
            print(f"Error in reminder system: {e}")

        # Sleep for 1 minute
        sleep(60)

# -------------------- BACK BUTTONS --------------------


@bot.callback_query_handler(func=lambda call: call.data == 'main_menu')
def handle_main_menu(call):
    """Go to main menu"""
    user_id = call.from_user.id
    show_main_menu(call.message, user_id)


@bot.callback_query_handler(func=lambda call: call.data == 'my_bookings')
def handle_my_bookings(call):
    """Go to my bookings"""
    user_id = call.from_user.id
    show_my_bookings(call.message, user_id)


@bot.callback_query_handler(func=lambda call: call.data == 'settings')
def handle_settings(call):
    """Go to settings"""
    user_id = call.from_user.id
    show_settings_menu(call.message, user_id)


@bot.callback_query_handler(func=lambda call: call.data == 'back_to_shops')
def handle_back_to_shops(call):
    """Go back to shops list"""
    user_id = call.from_user.id
    session = get_user_session(user_id)

    if session and session.city_id:
        show_barbershops_selection(
            call.message, user_id, session.city_id, session.district_id)
    else:
        show_main_menu(call.message, user_id)


@bot.callback_query_handler(func=lambda call: call.data == 'back_to_dates')
def handle_back_to_dates(call):
    """Go back to date selection"""
    user_id = call.from_user.id
    show_date_selection(call.message, user_id)


@bot.callback_query_handler(func=lambda call: call.data == 'refresh_bookings')
def handle_refresh_bookings(call):
    """Refresh bookings list"""
    user_id = call.from_user.id
    show_my_bookings(call.message, user_id)

# -------------------- MAIN --------------------


def startuser():
    """Main function to start the bot"""
    print("🤖 User bot is starting...")

    # Start reminder thread
    reminder_thread = threading.Thread(target=send_reminders, daemon=True)
    reminder_thread.start()

    # Start bot
    print("✅ User bot is running. Press Ctrl+C to stop.")
    bot.infinity_polling()


if __name__ == '__main__':
    startuser()
