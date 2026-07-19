import os
import sys
import threading
import time
import json
import logging
from datetime import datetime, timedelta
from flask import Flask, jsonify
import telebot
from telebot import types as tg_types

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------
# ТОКЕНЫ (только Telegram)
# ---------------------------------------------------------------------
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
if not TELEGRAM_TOKEN:
    raise ValueError("Задайте TELEGRAM_TOKEN")

logger.info(f"TELEGRAM_TOKEN установлен")

# Создаём бота
tg_bot = telebot.TeleBot(TELEGRAM_TOKEN)
logger.info(f"tg_bot создан")

# ---------------------------------------------------------------------
# ВЕБ-СЕРВЕР ДЛЯ RENDER (health check)
# ---------------------------------------------------------------------
app = Flask(__name__)

@app.route('/')
@app.route('/health')
def health():
    return jsonify({"status": "ok", "bot": "running"}), 200

def run_web():
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=False)

web_thread = threading.Thread(target=run_web, daemon=True)
web_thread.start()
time.sleep(2)
logger.info("Flask-сервер запущен")

# ---------------------------------------------------------------------
# ФАЙЛЫ ДАННЫХ
# ---------------------------------------------------------------------
REQUESTS_FILE = 'requests.json'
SETTINGS_FILE = 'settings.json'

STATUSES = {
    'queue': {'name': 'В очереди', 'emoji': '⏳'},
    'work': {'name': 'В работе', 'emoji': '🔄'},
    'guilty': {'name': 'Виновен', 'emoji': '🔴'},
    'not_guilty': {'name': 'Не виновен (на согласовании)', 'emoji': '🟡'},
    'approved': {'name': 'Согласовано', 'emoji': '🟢'},
    'rejected': {'name': 'Не согласовано', 'emoji': '⚫'}
}

# ---------------------------------------------------------------------
# РАБОТА С ФАЙЛАМИ
# ---------------------------------------------------------------------
file_lock = threading.Lock()

def load_requests():
    with file_lock:
        if os.path.exists(REQUESTS_FILE):
            with open(REQUESTS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        return []

def save_requests(requests):
    with file_lock:
        with open(REQUESTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(requests, f, ensure_ascii=False, indent=2)

def load_settings():
    with file_lock:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        default_settings = {
            'admin_ids': DEFAULT_ADMINS,
            'reminder_time': '09:00',
            'points': ['Ашан, Химки', 'Metro, Черная Грязь']
        }
        save_settings(default_settings)
        return default_settings

def save_settings(settings):
    with file_lock:
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)

# ---------------------------------------------------------------------
# АДМИНЫ ПО УМОЛЧАНИЮ
# ---------------------------------------------------------------------
DEFAULT_ADMINS = [
    {'id': 995419713, 'points': ['Ашан, Химки', 'Metro, Черная Грязь'], 'name': 'Даша'},
]

# ---------------------------------------------------------------------
# ОБЩИЕ ФУНКЦИИ
# ---------------------------------------------------------------------
user_data = {}

def is_admin(user_id):
    settings = load_settings()
    for admin in settings['admin_ids']:
        if admin['id'] == user_id:
            return True
    return False

def get_admin_points(user_id):
    settings = load_settings()
    for admin in settings['admin_ids']:
        if admin['id'] == user_id:
            return admin.get('points', [])
    return []

def is_super_admin(user_id):
    points = get_admin_points(user_id)
    settings = load_settings()
    return len(points) == len(settings.get('points', []))

def get_admin_name(user_id):
    settings = load_settings()
    for admin in settings['admin_ids']:
        if admin['id'] == user_id:
            return admin.get('name', f"Админ {user_id}")
    try:
        user = tg_bot.get_chat(user_id)
        return user.first_name or user.username or str(user_id)
    except:
        pass
    return str(user_id)

def get_available_requests(admin_id):
    requests = load_requests()
    if is_super_admin(admin_id):
        return requests
    points = get_admin_points(admin_id)
    return [r for r in requests if r.get('point') in points]

def can_admin_view_request(admin_id, request):
    if is_super_admin(admin_id):
        return True
    return request.get('point') in get_admin_points(admin_id)

# ---------------------------------------------------------------------
# АДАПТЕРЫ ОТПРАВКИ (только Telegram)
# ---------------------------------------------------------------------
def send_message(chat_id, text, reply_markup=None, parse_mode='HTML'):
    try:
        tg_bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception as e:
        logger.error(f"TG send error: {e}")

def send_photo(chat_id, photo, caption=None, reply_markup=None):
    try:
        tg_bot.send_photo(chat_id, photo, caption=caption, reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"TG send_photo error: {e}")

def edit_message_text(new_text, chat_id, message_id, reply_markup=None, parse_mode='HTML'):
    try:
        tg_bot.edit_message_text(new_text, chat_id, message_id, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception as e:
        logger.error(f"TG edit error: {e}")

def answer_callback(call, text=None, show_alert=False):
    try:
        tg_bot.answer_callback_query(call.id, text=text, show_alert=show_alert)
    except Exception as e:
        logger.error(f"TG answer error: {e}")

# ---------------------------------------------------------------------
# ГЛАВНОЕ МЕНЮ
# ---------------------------------------------------------------------
def show_main_menu(chat_id, user_id):
    markup = tg_types.InlineKeyboardMarkup()
    btn1 = tg_types.InlineKeyboardButton("📝 Подать заявку", callback_data="menu_new")
    btn2 = tg_types.InlineKeyboardButton("📋 Мои заявки", callback_data="menu_my")
    btn3 = tg_types.InlineKeyboardButton("ℹ️ Помощь", callback_data="menu_help")
    btn4 = tg_types.InlineKeyboardButton("📝 Пример заявки", callback_data="menu_example")
    markup.row(btn1, btn2)
    markup.row(btn3, btn4)
    if is_admin(user_id):
        btn5 = tg_types.InlineKeyboardButton("🔧 Админ-панель", callback_data="menu_admin")
        markup.row(btn5)
    send_message(chat_id, "👋 Привет! Выберите действие:", reply_markup=markup)

# ---------------------------------------------------------------------
# ОБРАБОТЧИКИ МЕНЮ
# ---------------------------------------------------------------------
def handle_menu_callback(call):
    chat_id = call.message.chat.id
    data = call.data
    if data == "menu_new":
        show_point_selection(chat_id)
    elif data == "menu_my":
        show_my_requests(chat_id)
    elif data == "menu_help":
        send_message(chat_id, "📖 Помощь: ...")
    elif data == "menu_example":
        show_example_request(chat_id)
    elif data == "menu_admin":
        if is_admin(chat_id):
            admin_panel(chat_id)
        else:
            send_message(chat_id, "⛔ Нет доступа.")
    answer_callback(call)

# ---------------------------------------------------------------------
# ВСЕ ОБРАБОТЧИКИ (ЗАЯВКИ, АДМИНКА, СТАТУСЫ)
# ---------------------------------------------------------------------
def show_point_selection(chat_id):
    settings = load_settings()
    points = settings.get('points', ['Точка А', 'Точка Б'])
    markup = tg_types.InlineKeyboardMarkup()
    for point in points:
        btn = tg_types.InlineKeyboardButton(f"📍 {point}", callback_data=f"point_{point}")
        markup.add(btn)
    send_message(chat_id, "🏢 Выберите точку:", reply_markup=markup)

def handle_point_callback(call):
    chat_id = call.message.chat.id
    point = call.data.replace('point_', '')
    user_data[chat_id] = {'step': 'fio', 'point': point}
    edit_message_text(f"✅ Выбрана точка: {point}\n\n👤 Введите ваше ФИО полностью:", chat_id, call.message.message_id)
    answer_callback(call)

def process_request_creation(chat_id, text):
    if chat_id not in user_data:
        return
    step = user_data[chat_id].get('step')
    if step == 'fio':
        user_data[chat_id]['fio'] = text
        user_data[chat_id]['step'] = 'photo'
        send_message(chat_id, "📸 Отправьте фото штрафа (одно фото):")
    elif step == 'date':
        try:
            datetime.strptime(text, '%d.%m.%Y')
            user_data[chat_id]['date'] = text
            user_data[chat_id]['step'] = 'confirm'
            markup = tg_types.InlineKeyboardMarkup()
            btn_yes = tg_types.InlineKeyboardButton("✅ Да, все верно", callback_data="confirm_yes")
            btn_no = tg_types.InlineKeyboardButton("❌ Нет, исправить", callback_data="confirm_no")
            markup.row(btn_yes, btn_no)
            send_message(
                chat_id,
                f"📋 Проверьте данные:\n\n"
                f"🏢 Точка: {user_data[chat_id]['point']}\n"
                f"👤 ФИО: {user_data[chat_id]['fio']}\n"
                f"📅 Дата штрафа: {text}\n"
                f"📸 Фото: получено\n\n"
                f"Все верно?",
                reply_markup=markup
            )
        except ValueError:
            send_message(chat_id, "❌ Неверный формат! Используйте ДД.ММ.ГГГГ")

def handle_photo_message(message):
    chat_id = message.chat.id
    if chat_id in user_data and user_data[chat_id].get('step') == 'photo':
        if hasattr(message, 'photo'):
            file_id = message.photo[-1].file_id
        else:
            file_id = None
        if file_id:
            user_data[chat_id]['photo_id'] = file_id
            user_data[chat_id]['step'] = 'date'
            send_message(chat_id, "📅 Введите дату в формате ДД.ММ.ГГГГ:")
        else:
            send_message(chat_id, "❌ Не удалось получить фото.")

def handle_confirm_callback(call):
    chat_id = call.message.chat.id
    data = call.data
    if data == 'confirm_yes':
        if chat_id not in user_data:
            return
        requests = load_requests()
        new_request = {
            'id': len(requests) + 1,
            'user_id': chat_id,
            'username': call.from_user.username or 'Не указан',
            'first_name': call.from_user.first_name,
            'fio': user_data[chat_id]['fio'],
            'point': user_data[chat_id]['point'],
            'photo_id': user_data[chat_id]['photo_id'],
            'date': user_data[chat_id]['date'],
            'status': 'queue',
            'penalty_number': '',
            'taken_by': None,
            'taken_by_name': None,
            'appeal_by': None,
            'appeal_by_name': None,
            'status_history': [
                {
                    'status': 'queue',
                    'date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'comment': f'Заявка создана. Точка: {user_data[chat_id]["point"]}'
                }
            ],
            'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'admin_comments': [],
            'appeal_text': '',
            'reminder_date': None,
            'reminder_sent': False
        }
        requests.append(new_request)
        save_requests(requests)
        del user_data[chat_id]
        edit_message_text(
            f"✅ Заявка №{new_request['id']} принята!\n\n"
            f"🏢 Точка: {new_request['point']}\n"
            f"👤 ФИО: {new_request['fio']}\n"
            f"📅 Дата штрафа: {new_request['date']}\n"
            f"⏳ Статус: В очереди\n\n"
            "Ожидайте обработки.",
            chat_id, call.message.message_id
        )
        notify_admins_for_point(new_request)
        answer_callback(call)
    elif data == 'confirm_no':
        show_point_selection(chat_id)
        answer_callback(call)

def notify_admins_for_point(request):
    settings = load_settings()
    point = request.get('point')
    status_info = STATUSES.get(request['status'], {'emoji': '⚪', 'name': 'Неизвестно'})
    for admin in settings['admin_ids']:
        if point in admin.get('points', []):
            admin_id = admin['id']
            caption = (
                f"🔔 НОВАЯ ЗАЯВКА №{request['id']}!\n\n"
                f"🏢 Точка: {point}\n"
                f"👤 ФИО: {request['fio']}\n"
                f"📅 Дата штрафа: {request['date']}\n"
                f"👤 Пользователь: @{request['username']}\n"
                f"📊 Статус: {status_info['emoji']} {status_info['name']}"
            )
            markup = tg_types.InlineKeyboardMarkup()
            btn = tg_types.InlineKeyboardButton(
                f"📋 Перейти к заявке №{request['id']}",
                callback_data=f"view_{request['id']}"
            )
            markup.add(btn)
            send_photo(admin_id, request['photo_id'], caption=caption, reply_markup=markup)

def show_my_requests(chat_id):
    requests = load_requests()
    user_requests = [r for r in requests if r['user_id'] == chat_id]
    if not user_requests:
        send_message(chat_id, "📭 У вас нет заявок.")
        return
    text = "📋 Ваши заявки:\n\n"
    for req in user_requests[-10:]:
        status_info = STATUSES.get(req['status'], {'emoji': '⚪', 'name': 'Неизвестно'})
        text += f"{status_info['emoji']} №{req['id']} - {req['fio']}\n"
        text += f"   🏢 Точка: {req.get('point', 'Не указана')}\n"
        text += f"   Статус: {status_info['name']}\n"
        text += f"   Дата штрафа: {req['date']}\n"
        if req.get('taken_by_name'):
            text += f"   👨‍💼 Взял: {req['taken_by_name']}\n"
        text += f"   Создана: {req['created_at']}\n\n"
    send_message(chat_id, text)

def show_example_request(chat_id):
    example_text = (
        "📝 **ПРИМЕР ЗАЯВКИ**\n\n"
        "1️⃣ Точка: выберите из списка\n"
        "2️⃣ ФИО: Иванов Иван Иванович\n"
        "3️⃣ Фото: чёткое, все данные видны\n"
        "4️⃣ Дата: 15.05.2026\n\n"
        "✅ Правильно: все поля заполнены, фото чёткое\n"
        "❌ Неправильно: неполное ФИО, размытое фото\n\n"
        "💡 Советы: фотографируйте при хорошем освещении."
    )
    send_message(chat_id, example_text, parse_mode='HTML')

def admin_panel(chat_id):
    if not is_admin(chat_id):
        send_message(chat_id, "⛔ У вас нет доступа.")
        return
    admin_points = get_admin_points(chat_id)
    is_super = is_super_admin(chat_id)
    points_text = "все точки" if is_super else ", ".join(admin_points)
    markup = tg_types.InlineKeyboardMarkup()
    btn_all = tg_types.InlineKeyboardButton("📋 Все заявки", callback_data="admin_all")
    btn_queue = tg_types.InlineKeyboardButton("⏳ В очереди", callback_data="admin_queue")
    btn_work = tg_types.InlineKeyboardButton("🔄 В работе", callback_data="admin_work")
    btn_not_guilty = tg_types.InlineKeyboardButton("🟡 На согласовании", callback_data="admin_not_guilty")
    btn_reminders = tg_types.InlineKeyboardButton("⏰ Напоминания", callback_data="admin_reminders")
    btn_stats = tg_types.InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")
    btn_settings = tg_types.InlineKeyboardButton("⚙️ Настройки", callback_data="admin_settings")
    markup.row(btn_queue, btn_work)
    markup.row(btn_not_guilty, btn_all)
    markup.row(btn_reminders, btn_stats)
    markup.row(btn_settings)
    available = get_available_requests(chat_id)
    send_message(
        chat_id,
        f"🔧 АДМИН-ПАНЕЛЬ\n\n👤 Вы отвечаете за: {points_text}\n📊 Доступно заявок: {len(available)}",
        reply_markup=markup
    )

def handle_admin_callback(call):
    chat_id = call.message.chat.id
    if not is_admin(chat_id):
        answer_callback(call, "⛔ Нет доступа", True)
        return
    data = call.data
    available = get_available_requests(chat_id)
    if data == 'admin_all':
        show_requests_list(chat_id, available, "Все доступные заявки")
    elif data == 'admin_queue':
        filtered = [r for r in available if r['status'] == 'queue']
        show_requests_list(chat_id, filtered, "Заявки в очереди")
    elif data == 'admin_work':
        filtered = [r for r in available if r['status'] == 'work']
        show_requests_list(chat_id, filtered, "Заявки в работе")
    elif data == 'admin_not_guilty':
        filtered = [r for r in available if r['status'] == 'not_guilty']
        show_requests_list(chat_id, filtered, "Заявки на согласовании")
    elif data == 'admin_reminders':
        show_reminders(chat_id)
    elif data == 'admin_stats':
        show_stats(chat_id)
    elif data == 'admin_settings':
        show_settings(chat_id)
    answer_callback(call)

def show_requests_list(chat_id, requests, title):
    if not requests:
        send_message(chat_id, f"📭 {title} не найдены.")
        return
    markup = tg_types.InlineKeyboardMarkup()
    for req in requests[:20]:
        status_info = STATUSES.get(req['status'], {'emoji': '⚪', 'name': 'Неизвестно'})
        taken_info = f" (взял: {req['taken_by_name']})" if req.get('taken_by_name') else ""
        btn = tg_types.InlineKeyboardButton(
            f"{status_info['emoji']} №{req['id']} - {req['point']} | {req['fio'][:15]}{taken_info}",
            callback_data=f"view_{req['id']}"
        )
        markup.add(btn)
    send_message(chat_id, f"📋 {title} ({len(requests)} шт.):", reply_markup=markup)

def view_request(call):
    chat_id = call.message.chat.id
    req_id = int(call.data.split('_')[1])
    requests = load_requests()
    req = next((r for r in requests if r['id'] == req_id), None)
    if not req:
        answer_callback(call, "❌ Заявка не найдена", True)
        return
    if not can_admin_view_request(chat_id, req):
        answer_callback(call, "⛔ Нет доступа", True)
        return
    status_info = STATUSES.get(req['status'], {'emoji': '⚪', 'name': 'Неизвестно'})
    admin = is_admin(chat_id)
    text = f"📌 ЗАЯВКА №{req['id']}\n━━━━━━━━━━━━━━━━━━\n"
    text += f"🏢 ТОЧКА: {req.get('point', 'Не указана')}\n"
    text += f"👤 ФИО: {req['fio']}\n"
    text += f"📅 Дата штрафа: {req['date']}\n"
    if admin and req.get('penalty_number'):
        text += f"🔢 Номер штрафа: {req['penalty_number']}\n"
    if req.get('taken_by_name'):
        text += f"👨‍💼 Взял в работу: {req['taken_by_name']}\n"
    else:
        if req['status'] == 'queue':
            text += "👨‍💼 Взял в работу: ⏳ ожидает\n"
    if req.get('appeal_by_name'):
        text += f"✍️ Оспаривание написал: {req['appeal_by_name']}\n"
    text += f"👤 Пользователь: @{req['username']}\n"
    text += f"📊 Статус: {status_info['emoji']} {status_info['name']}\n"
    text += f"📅 Создана: {req['created_at']}\n━━━━━━━━━━━━━━━━━━\n"
    text += "📝 История статусов:\n"
    for h in req['status_history'][-5:]:
        s_info = STATUSES.get(h['status'], {'emoji': '⚪', 'name': 'Неизвестно'})
        text += f"  {s_info['emoji']} {s_info['name']} - {h['date']}\n"
        if h.get('comment'):
            text += f"     💬 {h['comment']}\n"
    send_photo(chat_id, req['photo_id'], caption=text)

    # Кнопки действий
    markup = tg_types.InlineKeyboardMarkup()
    if req['status'] == 'queue':
        btn = tg_types.InlineKeyboardButton("🔄 Взять в работу", callback_data=f"take_{req_id}")
        markup.add(btn)
    elif req['status'] == 'work':
        btn1 = tg_types.InlineKeyboardButton("🔴 Виновен", callback_data=f"guilty_{req_id}")
        btn2 = tg_types.InlineKeyboardButton("🟡 Не виновен", callback_data=f"not_guilty_{req_id}")
        markup.row(btn1, btn2)
    elif req['status'] == 'not_guilty':
        btn1 = tg_types.InlineKeyboardButton("🟢 Согласовано", callback_data=f"approved_{req_id}")
        btn2 = tg_types.InlineKeyboardButton("⚫ Не согласовано", callback_data=f"rejected_{req_id}")
        btn3 = tg_types.InlineKeyboardButton("⏰ Напомнить через день", callback_data=f"remind_{req_id}")
        markup.row(btn1, btn2)
        markup.row(btn3)
    btn_c = tg_types.InlineKeyboardButton("💬 Комментарий", callback_data=f"comment_{req_id}")
    btn_a = tg_types.InlineKeyboardButton("✍️ Оспаривание", callback_data=f"appeal_{req_id}")
    btn_h = tg_types.InlineKeyboardButton("📜 История", callback_data=f"history_{req_id}")
    markup.row(btn_c, btn_a)
    markup.row(btn_h)
    btn_back = tg_types.InlineKeyboardButton("◀️ Назад", callback_data="admin_back")
    markup.add(btn_back)
    send_message(chat_id, "Выберите действие:", reply_markup=markup)
    answer_callback(call)

def take_to_work(call):
    chat_id = call.message.chat.id
    req_id = int(call.data.split('_')[1])
    if not is_admin(chat_id):
        answer_callback(call, "⛔ Нет доступа", True)
        return
    requests = load_requests()
    req = next((r for r in requests if r['id'] == req_id), None)
    if not req or req['status'] != 'queue':
        answer_callback(call, "❌ Нельзя взять", True)
        return
    admin_name = get_admin_name(chat_id)
    req['status'] = 'work'
    req['taken_by'] = chat_id
    req['taken_by_name'] = admin_name
    req['status_history'].append({
        'status': 'work',
        'date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'comment': f'Взял в работу: {admin_name}'
    })
    save_requests(requests)
    send_message(req['user_id'], f"🔄 Вашу заявку №{req_id} взял в работу {admin_name}.")
    edit_message_text(f"✅ Заявка №{req_id} взята в работу!\n👤 Админ: {admin_name}", chat_id, call.message.message_id)
    answer_callback(call)

def change_status(call):
    chat_id = call.message.chat.id
    if not is_admin(chat_id):
        answer_callback(call, "⛔ Нет доступа", True)
        return
    action, req_id = call.data.split('_')
    req_id = int(req_id)
    requests = load_requests()
    req = next((r for r in requests if r['id'] == req_id), None)
    if not req:
        answer_callback(call, "❌ Не найдена", True)
        return
    # Проверки
    if action == 'guilty' and req['status'] != 'work':
        answer_callback(call, "❌ Сначала возьмите в работу", True)
        return
    if action == 'not_guilty' and req['status'] != 'work':
        answer_callback(call, "❌ Сначала возьмите в работу", True)
        return
    if action == 'approved' and req['status'] != 'not_guilty':
        answer_callback(call, "❌ Заявка не на согласовании", True)
        return
    if action == 'rejected' and req['status'] != 'not_guilty':
        answer_callback(call, "❌ Заявка не на согласовании", True)
        return

    # Если это not_guilty — запрашиваем номер штрафа
    if action == 'not_guilty':
        user_data[chat_id] = {'action': 'add_penalty_number', 'req_id': req_id}
        send_message(chat_id, f"✍️ Введите НОМЕР ШТРАФА для заявки №{req_id} (только для админов):")
        answer_callback(call)
        return

    # Остальные статусы
    status_map = {'guilty': 'guilty', 'approved': 'approved', 'rejected': 'rejected'}
    new_status = status_map[action]
    admin_name = get_admin_name(chat_id)
    req['status'] = new_status
    req['status_history'].append({
        'status': new_status,
        'date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'comment': f'Статус изменил: {admin_name}'
    })
    save_requests(requests)
    status_info = STATUSES[new_status]
    send_message(req['user_id'], f"📊 Статус заявки №{req_id} изменён на {status_info['emoji']} {status_info['name']}")
    edit_message_text(f"✅ Статус заявки №{req_id} изменён на {status_info['emoji']} {status_info['name']}", chat_id, call.message.message_id)
    answer_callback(call)

def add_penalty_number(message):
    chat_id = message.chat.id
    if chat_id not in user_data or user_data[chat_id].get('action') != 'add_penalty_number':
        return
    req_id = user_data[chat_id]['req_id']
    penalty_number = message.text.strip()
    if not penalty_number:
        send_message(chat_id, "❌ Номер не может быть пустым. Введите номер штрафа:")
        return
    requests = load_requests()
    req = next((r for r in requests if r['id'] == req_id), None)
    if not req:
        send_message(chat_id, "❌ Заявка не найдена")
        del user_data[chat_id]
        return
    admin_name = get_admin_name(chat_id)
    req['penalty_number'] = penalty_number
    req['status'] = 'not_guilty'
    req['status_history'].append({
        'status': 'not_guilty',
        'date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'comment': f'Отправлено на согласование. Номер штрафа: {penalty_number}'
    })
    req['reminder_date'] = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
    req['reminder_sent'] = False
    save_requests(requests)
    send_message(chat_id, f"✅ Номер штрафа сохранён! Заявка №{req_id} отправлена на согласование.")
    send_message(req['user_id'], f"📊 Ваша заявка №{req_id} отправлена на согласование! Статус: 🟡 Не виновен")
    del user_data[chat_id]

# ---------------------------------------------------------------------
# ОСТАЛЬНЫЕ ФУНКЦИИ (appeal, comment, history, remind, reminders, stats, settings, admin_back)
# ---------------------------------------------------------------------
def add_appeal(call):
    chat_id = call.message.chat.id
    req_id = int(call.data.split('_')[1])
    if not is_admin(chat_id):
        answer_callback(call, "⛔ Нет доступа", True)
        return
    user_data[chat_id] = {'action': 'add_appeal', 'req_id': req_id}
    send_message(chat_id, f"✍️ Введите ТЕКСТ ОСПАРИВАНИЯ для заявки №{req_id}:")
    answer_callback(call)

def add_appeal_text(message):
    chat_id = message.chat.id
    if chat_id not in user_data or user_data[chat_id].get('action') != 'add_appeal':
        return
    req_id = user_data[chat_id]['req_id']
    appeal_text = message.text.strip()
    if not appeal_text:
        send_message(chat_id, "❌ Текст не может быть пустым.")
        return
    requests = load_requests()
    req = next((r for r in requests if r['id'] == req_id), None)
    if not req:
        send_message(chat_id, "❌ Заявка не найдена")
        del user_data[chat_id]
        return
    admin_name = get_admin_name(chat_id)
    req['appeal_text'] = appeal_text
    req['appeal_by'] = chat_id
    req['appeal_by_name'] = admin_name
    if req['status'] != 'not_guilty':
        req['status'] = 'not_guilty'
        req['status_history'].append({
            'status': 'not_guilty',
            'date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'comment': f'Текст оспаривания написал: {admin_name}'
        })
        req['reminder_date'] = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
        req['reminder_sent'] = False
    save_requests(requests)
    send_message(chat_id, f"✅ Текст оспаривания сохранён! Заявка №{req_id} отправлена на согласование.")
    send_message(req['user_id'], f"✍️ По вашей заявке №{req_id} добавлен текст оспаривания:\n\n{appeal_text}")
    del user_data[chat_id]

def add_comment(call):
    chat_id = call.message.chat.id
    req_id = int(call.data.split('_')[1])
    if not is_admin(chat_id):
        answer_callback(call, "⛔ Нет доступа", True)
        return
    user_data[chat_id] = {'action': 'add_comment', 'req_id': req_id}
    send_message(chat_id, f"💬 Введите комментарий для заявки №{req_id}:")
    answer_callback(call)

def add_comment_text(message):
    chat_id = message.chat.id
    if chat_id not in user_data or user_data[chat_id].get('action') != 'add_comment':
        return
    req_id = user_data[chat_id]['req_id']
    comment_text = message.text.strip()
    if not comment_text:
        send_message(chat_id, "❌ Комментарий не может быть пустым.")
        return
    requests = load_requests()
    req = next((r for r in requests if r['id'] == req_id), None)
    if not req:
        send_message(chat_id, "❌ Заявка не найдена")
        del user_data[chat_id]
        return
    admin_name = get_admin_name(chat_id)
    timestamp = datetime.now().strftime('%d.%m.%Y %H:%M')
    req['admin_comments'].append(f"{timestamp} - {admin_name}: {comment_text}")
    save_requests(requests)
    send_message(chat_id, f"✅ Комментарий добавлен к заявке №{req_id}")
    send_message(req['user_id'], f"💬 Администратор {admin_name} оставил комментарий к вашей заявке №{req_id}:\n\n{comment_text}")
    del user_data[chat_id]

def show_history(call):
    chat_id = call.message.chat.id
    req_id = int(call.data.split('_')[1])
    requests = load_requests()
    req = next((r for r in requests if r['id'] == req_id), None)
    if not req:
        answer_callback(call, "❌ Не найдена", True)
        return
    if not can_admin_view_request(chat_id, req):
        answer_callback(call, "⛔ Нет доступа", True)
        return
    text = f"📜 ПОЛНАЯ ИСТОРИЯ ЗАЯВКИ №{req['id']}\n━━━━━━━━━━━━━━━━━━\n\n"
    for i, h in enumerate(req['status_history'], 1):
        s_info = STATUSES.get(h['status'], {'emoji': '⚪', 'name': 'Неизвестно'})
        text += f"{i}. {s_info['emoji']} {s_info['name']} - {h['date']}\n"
        if h.get('comment'):
            text += f"   💬 {h['comment']}\n"
        text += "\n"
    if req.get('admin_comments'):
        text += "━━━━━━━━━━━━━━━━━━\n💬 Комментарии:\n"
        for c in req['admin_comments']:
            text += f"  • {c}\n"
        text += "\n"
    if req.get('appeal_text'):
        text += "━━━━━━━━━━━━━━━━━━\n✍️ Текст оспаривания:\n" + req['appeal_text'] + "\n"
        if req.get('appeal_by_name'):
            text += f"👤 Написал: {req['appeal_by_name']}\n"
    if req.get('penalty_number'):
        text += f"\n🔢 Номер штрафа: {req['penalty_number']} (только для админов)"
    send_message(chat_id, text)
    answer_callback(call)

def set_reminder(call):
    chat_id = call.message.chat.id
    req_id = int(call.data.split('_')[1])
    if not is_admin(chat_id):
        answer_callback(call, "⛔ Нет доступа", True)
        return
    requests = load_requests()
    req = next((r for r in requests if r['id'] == req_id), None)
    if not req or req['status'] != 'not_guilty':
        answer_callback(call, "❌ Нельзя", True)
        return
    req['reminder_date'] = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
    req['reminder_sent'] = False
    save_requests(requests)
    send_message(chat_id, f"⏰ Напоминание для заявки №{req_id} установлено на завтра.")
    answer_callback(call)

def show_reminders(chat_id):
    available = get_available_requests(chat_id)
    today = datetime.now().strftime('%Y-%m-%d')
    reminders = [r for r in available if r.get('reminder_date') == today and r['status'] == 'not_guilty' and not r.get('reminder_sent', False)]
    if not reminders:
        send_message(chat_id, "⏰ Напоминаний на сегодня нет.")
        return
    markup = tg_types.InlineKeyboardMarkup()
    for req in reminders:
        btn = tg_types.InlineKeyboardButton(
            f"№{req['id']} - {req['fio']} ({req['date']})",
            callback_data=f"view_{req['id']}"
        )
        markup.add(btn)
    send_message(chat_id, f"⏰ НАПОМИНАНИЯ НА СЕГОДНЯ ({len(reminders)} шт.):", reply_markup=markup)

def show_stats(chat_id):
    available = get_available_requests(chat_id)
    total = len(available)
    text = f"📊 СТАТИСТИКА\n━━━━━━━━━━━━━━━━━━\nВсего доступных: {total}\n\n"
    points = {}
    for req in available:
        p = req.get('point', 'Без точки')
        points[p] = points.get(p, 0) + 1
    if points:
        text += "🏢 По точкам:\n"
        for p, c in points.items():
            text += f"  • {p}: {c}\n"
        text += "\n"
    for k, v in STATUSES.items():
        count = len([r for r in available if r['status'] == k])
        text += f"{v['emoji']} {v['name']}: {count}\n"
    send_message(chat_id, text)

def show_settings(chat_id):
    settings = load_settings()
    text = "⚙️ НАСТРОЙКИ\n━━━━━━━━━━━━━━━━━━\n"
    text += f"🏢 Точки: {', '.join(settings.get('points', []))}\n\n"
    text += "👤 Админы:\n"
    if settings['admin_ids']:
        for adm in settings['admin_ids']:
            text += f"  • {adm.get('name')} (ID: {adm['id']}) - точки: {', '.join(adm.get('points', []))}\n"
    else:
        text += "  ❌ Не установлены\n"
    text += f"\n⏰ Время напоминаний: {settings.get('reminder_time', '09:00')}\n\n"
    text += "📌 Команды для управления:\n"
    text += "/add_admin <ID> <Точки> <Имя>\n"
    text += "/remove_admin <ID>\n"
    text += "/add_point <Название>\n"
    text += "/remove_point <Название>\n"
    text += "/set_time <HH:MM>"
    send_message(chat_id, text)

def admin_back(call):
    admin_panel(call.message.chat.id)
    answer_callback(call)

# ---------------------------------------------------------------------
# ОБРАБОТКА ТЕКСТОВЫХ СООБЩЕНИЙ И ФОТО
# ---------------------------------------------------------------------
def handle_text_message(message):
    chat_id = message.chat.id
    if chat_id in user_data:
        action = user_data[chat_id].get('action')
        if action == 'add_penalty_number':
            add_penalty_number(message)
        elif action == 'add_appeal':
            add_appeal_text(message)
        elif action == 'add_comment':
            add_comment_text(message)
        else:
            process_request_creation(chat_id, message.text)
    else:
        show_main_menu(chat_id, chat_id)

def handle_photo_message_global(message):
    handle_photo_message(message)

# ---------------------------------------------------------------------
# КОМАНДА /add_admin
# ---------------------------------------------------------------------
def handle_add_admin_command(message, user_id):
    settings = load_settings()
    if is_admin(user_id):
        pass
    elif len(settings['admin_ids']) == 0:
        pass
    else:
        send_message(message.chat.id, "⛔ У вас нет прав для добавления админов.")
        return

    try:
        parts = message.text.split(' ', 3)
        if len(parts) < 3:
            send_message(message.chat.id,
                         "❌ Использование: /add_admin <ID> <Точки> <Имя>\n"
                         "Пример: /add_admin 123456789 Точка А,Точка Б Иван Иванов")
            return
        new_id = int(parts[1])
        points = [p.strip() for p in parts[2].split(',')]
        name = parts[3] if len(parts) > 3 else f"Админ {new_id}"
        available_points = settings.get('points', [])
        for p in points:
            if p not in available_points:
                send_message(message.chat.id, f"❌ Точка '{p}' не найдена. Доступные: {', '.join(available_points)}")
                return
        for adm in settings['admin_ids']:
            if adm['id'] == new_id:
                adm['points'] = points
                adm['name'] = name
                save_settings(settings)
                send_message(message.chat.id, f"✅ Админ {new_id} обновлён.")
                return
        settings['admin_ids'].append({'id': new_id, 'points': points, 'name': name})
        save_settings(settings)
        send_message(message.chat.id, f"✅ Админ добавлен: {name} (ID: {new_id})")
        try:
            send_message(new_id, f"👑 Вы назначены администратором!\nТочки: {', '.join(points)}")
        except:
            pass
    except Exception as e:
        send_message(message.chat.id, f"❌ Ошибка: {e}")

# ---------------------------------------------------------------------
# РЕГИСТРАЦИЯ ОБРАБОТЧИКОВ TELEGRAM
# ---------------------------------------------------------------------
def setup_handlers():
    @tg_bot.message_handler(commands=['start'])
    def tg_start(message):
        logger.info(f"Telegram start от {message.from_user.id}")
        show_main_menu(message.chat.id, message.from_user.id)

    @tg_bot.callback_query_handler(func=lambda call: True)
    def tg_callback(call):
        data = call.data
        if data.startswith('menu_'):
            handle_menu_callback(call)
        elif data.startswith('point_'):
            handle_point_callback(call)
        elif data.startswith('confirm_'):
            handle_confirm_callback(call)
        elif data.startswith('admin_'):
            handle_admin_callback(call)
        elif data.startswith('view_'):
            view_request(call)
        elif data.startswith('take_'):
            take_to_work(call)
        elif data.startswith(('guilty_', 'not_guilty_', 'approved_', 'rejected_')):
            change_status(call)
        elif data.startswith('appeal_'):
            add_appeal(call)
        elif data.startswith('comment_'):
            add_comment(call)
        elif data.startswith('history_'):
            show_history(call)
        elif data.startswith('remind_'):
            set_reminder(call)
        elif data == 'admin_back':
            admin_back(call)
        else:
            answer_callback(call, "Неизвестная команда")

    @tg_bot.message_handler(content_types=['text'])
    def tg_text(message):
        chat_id = message.chat.id
        if message.text.startswith('/add_admin'):
            handle_add_admin_command(message, chat_id)
        else:
            handle_text_message(message)

    @tg_bot.message_handler(content_types=['photo'])
    def tg_photo(message):
        handle_photo_message_global(message)

# ---------------------------------------------------------------------
# ФОНОВАЯ ЗАДАЧА НАПОМИНАНИЙ
# ---------------------------------------------------------------------
def reminder_checker():
    while True:
        try:
            now = datetime.now()
            settings = load_settings()
            reminder_time = settings.get('reminder_time', '09:00')
            if now.strftime('%H:%M') == reminder_time:
                requests = load_requests()
                today = now.strftime('%Y-%m-%d')
                for req in requests:
                    if req.get('reminder_date') == today and req['status'] == 'not_guilty' and not req.get('reminder_sent', False):
                        point = req.get('point')
                        for admin in settings['admin_ids']:
                            if point in admin.get('points', []):
                                admin_id = admin['id']
                                text = (
                                    f"⏰ НАПОМИНАНИЕ!\n\n"
                                    f"Заявка №{req['id']} ожидает согласования!\n"
                                    f"🏢 Точка: {point}\n"
                                    f"👤 ФИО: {req['fio']}\n"
                                    f"📅 Дата штрафа: {req['date']}\n"
                                    f"🔢 Номер штрафа: {req.get('penalty_number', 'Не указан')}"
                                )
                                markup = tg_types.InlineKeyboardMarkup()
                                btn = tg_types.InlineKeyboardButton(
                                    f"📋 Перейти к заявке №{req['id']}",
                                    callback_data=f"view_{req['id']}"
                                )
                                markup.add(btn)
                                send_message(admin_id, text, reply_markup=markup)
                        req['reminder_sent'] = True
                        save_requests(requests)
            time.sleep(60)
        except Exception as e:
            logger.error(f"Reminder error: {e}")
            time.sleep(60)

def start_reminder_thread():
    t = threading.Thread(target=reminder_checker, daemon=True)
    t.start()
    logger.info("Напоминания запущены")

# ---------------------------------------------------------------------
# ЗАПУСК БОТА
# ---------------------------------------------------------------------
def run_tg():
    print("🟢 Telegram бот запущен (polling)", flush=True)
    while True:
        try:
            tg_bot.polling(none_stop=True, interval=0)
        except Exception as e:
            print(f"❌ Telegram polling упал: {e}", flush=True)
            logger.error(f"Telegram polling упал: {e}")
            time.sleep(5)

# ---------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 50, flush=True)
    print("🤖 TELEGRAM БОТ ЗАПУЩЕН на Render", flush=True)
    print("=" * 50, flush=True)
    settings = load_settings()
    print(f"🏢 Точки: {', '.join(settings.get('points', []))}", flush=True)
    print(f"👤 Админов: {len(settings['admin_ids'])}", flush=True)
    for adm in settings['admin_ids']:
        print(f"  • {adm.get('name')} (ID: {adm['id']}) - точки: {', '.join(adm.get('points', []))}", flush=True)

    setup_handlers()
    start_reminder_thread()
    
    # Запускаем бота в основном потоке (без создания дополнительного потока)
    run_tg()
