import logging
import re
import os
import time # Добавлен импорт для создания уникальных имен задач
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
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") # ЗАМЕНИ НА СВОЙ ТОКЕН

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
    
    # ИЗМЕНЕНО: Используем временную метку для гарантии уникальности имени задачи.
    # Это предотвращает конфликты и ошибки при создании/удалении задач.
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

    if update.callback_query:
        await update.callback_query.edit_message_text(confirmation_text)
    else:
        await context.bot.send_message(chat_id, confirmation_text, reply_markup=get_main_keyboard())

    if user_id in user_task_data: del user_task_data[user_id]
    if user_id in user_states: del user_states[user_id]

# --- Основные функции-обработчики ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отправляет приветственное сообщение и показывает главную клавиатуру."""
    await update.message.reply_text(
        "Привет! Я твой ленивый помощник по дому.\n"
        "Нажми 'Напомнить ⏰', чтобы выбрать, о чём тебе напомнить, "
        "или 'Удалить ❌' для отмены.",
        reply_markup=get_main_keyboard()
    )

async def remind_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает inline-кнопки для выбора задачи. Срабатывает по кнопке 'Напомнить ⏰' или слову 'напомни'."""
    keyboard = [
        [InlineKeyboardButton("Посуду", callback_data='task_dishes')],
        [InlineKeyboardButton("Мусор", callback_data='task_trash')],
        [InlineKeyboardButton("Растения", callback_data='task_plants')],
        [InlineKeyboardButton("📝 Своя задача", callback_data='custom_task_start')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Выбери задачу или создай свою:", reply_markup=reply_markup)

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
    """Отправляет сообщение с напоминанием."""
    job = context.job
    await context.bot.send_message(chat_id=job.chat_id, text=f"🔔 Напоминание: {job.data}!")
    logger.info(f"Sent reminder to chat_id {job.chat_id}")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает нажатия на inline-кнопки (выбор задачи, времени, удаление)."""
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    if data.startswith('task_'):
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
        user_task_data[user_id] = update.message.text
        user_states.pop(user_id, None)
        await update.message.reply_text(
            f"Принято! Задача: «{update.message.text}».\nТеперь выбери, через сколько напомнить:", 
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
    
    # ИСПРАВЛЕНО: Добавляем обработку команды /start и слов "старт/Старт"
    app.add_handler(CommandHandler("start", start))
    # Флаг (?i) для игнорирования регистра должен стоять в самом начале выражения
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'(?i)^старт$'), start))

    # ИСПРАВЛЕНО: Добавляем обработку команды /remind, кнопки "Напомнить ⏰" и слов "напомни/Напомни"
    app.add_handler(CommandHandler("remind", remind_handler))
    # Флаг (?i) также вынесен в начало
    remind_regex = r'(?i)^(Напомнить ⏰|напомни)$'
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(remind_regex), remind_handler))
    
    # Обработчик кнопки "Удалить" остается без изменений
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex('^Удалить ❌$'), delete_list_handler))

    # Обработчик inline-кнопок
    app.add_handler(CallbackQueryHandler(button_handler))
    
    # Обработчик текста для ввода кастомных данных должен идти ПОСЛЕ всех командных обработчиков
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    app.run_polling()

if __name__ == '__main__':
    main()
