import logging
import re
import os
import time # Добавлен импорт для создания уникальных имен задач
import random # Добавлен импорт для случайного выбора фраз
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)


# 🔑 Вставь сюда свой токен от BotFather
TOKEN = '' # ЗАМЕНИ НА СВОЙ ТОКЕН

# --- Константы и словари ---
# 🧹 Словарь стандартных задач
tasks = {
    'dishes': '🧼 Помыть посуду',
    'trash': '🗑️ Вынести мусор',
    'plants': '🌿 Полить растения'
}

# Временные опции в минутах
time_options = {
    '1m': 1,
    '5m': 5,
    '10m': 10
}

# 😴 Список шуток для режима прокрастинации
procrastination_phrases = [
    "Окей, мусорный пакет подождет. Надеюсь, он не планирует эволюционировать и захватить кухню за это время!",
    "Понимаю, диван сегодня особенно мягок. Даю тебе еще немного времени на подвиги!",
    "Задача отложена. Помни, великие дела не делаются на голодный желудок... или на полный... в общем, потом.",
    "Хорошо, откладываем. Но если растения завянут, мы скажем им, что это был твой творческий отпуск.",
    "Принято! Эта задача теперь в официальном списке 'Сделаю завтра'. Список длинный, но ты справишься.",
    "Без проблем! Даже Рим не один день строился. Правда, он и не посуду мыл.",
    "Отдыхай, герой! Эта задача подождет твоего триумфального возвращения с кухни с чаем.",
    "Есть! Задача переведена в режим ожидания. Она будет терпеливо ждать, пока ты спасаешь мир в интернете.",
]

# ✨ Список похвалы для выполненных задач
completion_praises = [
    "Отличная работа! Ты просто молодец!",
    "Задача выполнена! Время для заслуженного отдыха.",
    "Супер! Еще одно дело сделано. Ты unstoppable!",
    "Так держать! Дом становится чище благодаря тебе.",
    "Ты справился! Горжусь тобой.",
    "Великолепно! Задача закрыта. Что дальше, покорение мира?",
    "Есть! Минус одна задача. Ты — чемпион по продуктивности!",
]


# --- Словари для управления состоянием и данными ---
user_states = {}
user_task_data = {}
# Константы для обозначения состояний
AWAITING_CUSTOM_TASK = 1
AWAITING_CUSTOM_TIME = 2

# 🛠️ Настройка логов
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Вспомогательные функции для создания клавиатур ---

def get_main_keyboard() -> ReplyKeyboardMarkup:
    """Создает и возвращает ГЛАВНУЮ клавиатуру с кнопками внизу экрана."""
    keyboard = [
        ['Напомнить ⏰', 'Удалить ❌']
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_time_keyboard() -> InlineKeyboardMarkup:
    """Создает и возвращает inline-клавиатуру для выбора времени."""
    keyboard = [
        [
            InlineKeyboardButton("1 мин", callback_data='time_1m'),
            InlineKeyboardButton("5 мин", callback_data='time_5m'),
            InlineKeyboardButton("10 мин", callback_data='time_10m')
        ],
        [InlineKeyboardButton("⏱️ Указать своё время (в минутах)", callback_data='custom_time_start')]
    ]
    return InlineKeyboardMarkup(keyboard)

async def schedule_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE, minutes: int):
    """Устанавливает напоминание и отправляет подтверждение."""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    task_info = user_task_data.get(user_id)
    if not task_info:
        await context.bot.send_message(chat_id, "Что-то пошло не так. Попробуй снова.", reply_markup=get_main_keyboard())
        return

    task_text = tasks.get(task_info, task_info)
    
    # Используем временную метку для гарантии уникальности имени задачи.
    job_name = f"reminder_{chat_id}_{user_id}_{int(time.time())}"

    context.job_queue.run_once(
        reminder_callback,
        when=minutes * 60,
        chat_id=chat_id,
        data=task_text,
        name=job_name
    )
    logger.info(f"Scheduled a reminder with name {job_name} for chat_id {chat_id} in {minutes} minutes.")

    confirmation_text = f"Окей! Напомню о задаче «{task_text}» через {minutes} мин."

    # Проверяем, откуда пришел вызов - от кнопки или из текстового сообщения
    if update.callback_query:
        await update.callback_query.edit_message_text(confirmation_text)
    else:
        await context.bot.send_message(chat_id, confirmation_text, reply_markup=get_main_keyboard())

    # Очищаем временные данные пользователя
    if user_id in user_task_data: del user_task_data[user_id]
    if user_id in user_states: del user_states[user_id]

# --- Основные функции-обработчики ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отправляет приветственное сообщение и показывает главную клавиатуру."""
    await update.message.reply_text(
        "Привет! Я твой ленивый помощник по дому.\n"
        "Нажми 'Напомнить ⏰', чтобы выбрать, о чём тебе напомнить, или 'Удалить ❌' для отмены.\n\n"
        "Когда придет напоминание, ты сможешь:\n"
        "☕ *Отложить* — бот пошутит и предложит перенести задачу.\n"
        "☑️ *Завершить* — бот похвалит тебя за выполненное дело.",
        reply_markup=get_main_keyboard(),
        parse_mode='Markdown'
    )

async def remind_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ИЗМЕНЕНО: Показывает inline-кнопки для выбора задачи, включая последние 3 кастомные."""
    
    # НОВАЯ ЛОГИКА: Достаем последние задачи пользователя
    recent_tasks = context.user_data.get('recent_custom_tasks', [])
    
    keyboard = []
    
    # Создаем кнопки для недавних задач
    if recent_tasks:
        for i, task_text in enumerate(recent_tasks):
            # Обрезаем текст для кнопки, если он слишком длинный
            button_text = f"🔄 {task_text}"
            if len(button_text) > 40:
                 button_text = button_text[:37] + "..."
            # callback_data содержит индекс задачи в списке
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"select_recent_{i}")])

    # Добавляем стандартные кнопки
    keyboard.extend([
        [InlineKeyboardButton("🧼 Помыть посуду", callback_data='task_dishes')],
        [InlineKeyboardButton("🗑️ Вынести мусор", callback_data='task_trash')],
        [InlineKeyboardButton("🌿 Полить растения", callback_data='task_plants')],
        [InlineKeyboardButton("📝 Своя задача", callback_data='custom_task_start')]
    ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Выбери задачу, создай свою или используй недавнюю:", reply_markup=reply_markup)


async def delete_list_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает список активных напоминаний для удаления. Срабатывает по кнопке 'Удалить ❌'."""
    chat_id = update.effective_chat.id
    active_jobs = [job for job in context.job_queue.jobs() if job.chat_id == chat_id]

    if not active_jobs:
        await update.message.reply_text("Активных напоминаний нет.", reply_markup=get_main_keyboard())
        return

    keyboard = []
    for job in active_jobs:
        button_text = f"❌ {job.data} (в {job.next_run_time.strftime('%H:%M:%S')})"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"delete_confirm_{job.name}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Какое напоминание удалить?", reply_markup=reply_markup)

async def reminder_callback(context: ContextTypes.DEFAULT_TYPE):
    """Отправляет сообщение с напоминанием и кнопками 'Отложить' и 'Завершить'."""
    job = context.job
    keyboard = [[
        InlineKeyboardButton("☕ Отложить", callback_data="postpone"),
        InlineKeyboardButton("Завершить ☑️", callback_data="complete")
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await context.bot.send_message(
        chat_id=job.chat_id, 
        text=f"🔔 Напоминание: {job.data}!",
        reply_markup=reply_markup
    )
    logger.info(f"Sent reminder to chat_id {job.chat_id}")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает нажатия на inline-кнопки."""
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    # НОВЫЙ БЛОК: Обработка кнопок с недавними задачами
    if data.startswith('select_recent_'):
        try:
            index = int(data.split('_')[-1])
            recent_tasks = context.user_data.get('recent_custom_tasks', [])
            task_text = recent_tasks[index]
            
            user_task_data[user_id] = task_text
            await query.edit_message_text("Через сколько напомнить?", reply_markup=get_time_keyboard())
        except (IndexError, KeyError):
            await query.edit_message_text("Не удалось найти эту задачу. Попробуй снова.", reply_markup=None)

    elif data.startswith('task_'):
        task_key = data.split('_')[1]
        user_task_data[user_id] = task_key
        await query.edit_message_text("Через сколько напомнить?", reply_markup=get_time_keyboard())

    elif data == 'custom_task_start':
        user_states[user_id] = AWAITING_CUSTOM_TASK
        await query.edit_message_text(
            "Хорошо. О какой задаче мне тебе напомнить? Просто напиши и отправь ее мне.",
            reply_markup=None 
        )

    elif data.startswith('time_'):
        minutes_key = data.split('_')[1]
        minutes = time_options.get(minutes_key)
        await schedule_reminder(update, context, minutes)

    elif data == 'custom_time_start':
        user_states[user_id] = AWAITING_CUSTOM_TIME
        await query.edit_message_text(
            "Понял. Введи количество минут числом (например, 15 или 60).",
            reply_markup=None
        )

    elif data == 'postpone':
        original_message_text = query.message.text
        task_text = original_message_text.replace("🔔 Напоминание: ", "").replace("!", "")
        user_task_data[user_id] = task_text
        joke = random.choice(procrastination_phrases)
        await query.edit_message_text(f"{original_message_text}\n\n_{joke}_", parse_mode='Markdown')
        await context.bot.send_message(
            chat_id=query.effective_chat.id,
            text="Хорошо, на сколько отложим?",
            reply_markup=get_time_keyboard()
        )

    elif data == 'complete':
        original_message_text = query.message.text
        praise = random.choice(completion_praises)
        await query.edit_message_text(f"{original_message_text}\n\n✅ *{praise}*", parse_mode='Markdown')

    elif data.startswith('delete_confirm_'):
        job_name = data.replace('delete_confirm_', '', 1)
        jobs_to_remove = context.job_queue.get_jobs_by_name(job_name)
        
        if not jobs_to_remove:
            await query.edit_message_text("Это напоминание уже было удалено или выполнено.")
            return
        
        for job in jobs_to_remove:
            job.schedule_removal()
        
        logger.info(f"Removed job with name {job_name}")
        await query.edit_message_text("Напоминание удалено!")

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает текстовые сообщения для кастомных задач и времени."""
    user_id = update.message.from_user.id
    current_state = user_states.get(user_id)

    if current_state == AWAITING_CUSTOM_TASK:
        custom_task_text = update.message.text
        user_task_data[user_id] = custom_task_text
        
        # НОВАЯ ЛОГИКА: Сохраняем кастомную задачу в историю
        if 'recent_custom_tasks' not in context.user_data:
            context.user_data['recent_custom_tasks'] = []
        
        recent_tasks = context.user_data['recent_custom_tasks']
        # Убираем дубликат, если он есть, чтобы задача переместилась в начало
        if custom_task_text in recent_tasks:
            recent_tasks.remove(custom_task_text)
        
        # Добавляем новую задачу в начало списка
        recent_tasks.insert(0, custom_task_text)
        
        # Оставляем только последние 3 задачи
        context.user_data['recent_custom_tasks'] = recent_tasks[:3]
        
        user_states.pop(user_id, None)
        await update.message.reply_text(
            f"Принято! Задача: «{custom_task_text}».\nТеперь выбери, через сколько напомнить:", 
            reply_markup=get_time_keyboard()
        )

    elif current_state == AWAITING_CUSTOM_TIME:
        try:
            minutes = int(update.message.text)
            if minutes <= 0:
                await update.message.reply_text("Время должно быть положительным числом. Попробуй еще раз.")
                return
            await schedule_reminder(update, context, minutes)
        except ValueError:
            await update.message.reply_text("Это не похоже на число. Пожалуйста, введи количество минут (например, 15).")

def main():
    """Основная функция для запуска бота."""
    app = ApplicationBuilder().token(TOKEN).build()

    # --- Регистрация обработчиков ---
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'(?i)^старт$'), start))

    app.add_handler(CommandHandler("remind", remind_handler))
    remind_regex = r'(?i)^(Напомнить ⏰|напомни)$'
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(remind_regex), remind_handler))
    
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex('^Удалить ❌$'), delete_list_handler))

    # Обработчик inline-кнопок
    app.add_handler(CallbackQueryHandler(button_handler))
    
    # Обработчик текста для ввода кастомных данных
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    app.run_polling()

if __name__ == '__main__':
    main()
