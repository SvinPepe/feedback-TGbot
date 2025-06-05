import logging
import re
from datetime import datetime
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = open("config.txt").readline()
DATE, FULL_NAME, COMMENT, RATING, FOLLOW_UP, SUGGESTIONS = range(6)

ADMIN_IDS = [1444398618, 1299729915]
REMINDER_INTERVAL = 3600

HIGH_OPTIONS = ["Применимо", "Интересно", "Доходчиво", "Понравился эксперт"]
LOW_OPTIONS = ["Неприменимо", "Есть противоречия", "Сложно, непонятно", "Остались вопросы", "Много воды"]


def validate_date(date_str: str) -> bool:
    pattern = r'^\d{2}\.\d{2}\.\d{4}$'
    if re.match(pattern, date_str):
        try:
            day, month, year = map(int, date_str.split('.'))
            datetime(year, month, day)
            return True
        except ValueError:
            return False
    return False


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    if update.message is not None:
        await update.message.reply_text(
            "Привет! Это бот для сбора обратной связи о серии обучающих мероприятий проекта «Вернуть будущее».\n\n"
            "Пожалуйста, ответь на 5 коротких вопросов — это поможет нам улучшить обучение.\n\n"
            "Укажите дату мероприятия (в формате дд.мм.гггг, например, 12.05.2025):"
        )
    else:
        await update.callback_query.message.reply_text(
            "Укажите дату мероприятия (в формате дд.мм.гггг, например, 12.05.2025):")
    return DATE


async def handle_timeout(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    await context.bot.send_message(
        chat_id=job.chat_id,
        text="⏳ Сессия завершена из-за неактивности. Начните заново с /start"
    )


async def date_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text
    if validate_date(text):
        context.user_data['date'] = text
        await update.message.reply_text("Напишите ваше ФИО:")
        return FULL_NAME
    await update.message.reply_text("Неверный формат даты. Используйте дд.мм.гггг:")
    return DATE


async def full_name_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['full_name'] = update.message.text
    await update.message.reply_text(
        "Какие главные выводы вы сделали после обучения?\n"
        "Что сможете применить в работе?"
    )
    return COMMENT


async def comment_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text
    if len(text) > 500:
        await update.message.reply_text("Превышен лимит в 500 символов. Сократите комментарий:")
        return COMMENT

    context.user_data['comment'] = text
    await update.message.reply_text(
        "Оцените организацию мероприятия по шкале от 0 до 10:"
    )
    return RATING


async def rating_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        rating = int(update.message.text)
        if 0 <= rating <= 10:
            context.user_data['rating'] = rating

            if rating >= 7:
                options = HIGH_OPTIONS
                context.user_data['feedback_type'] = 'high'
                question = "Что понравилось?"
            else:
                options = LOW_OPTIONS
                context.user_data['feedback_type'] = 'low'
                question = "Что не понравилось?"

            keyboard = []
            for option in options:
                keyboard.append([InlineKeyboardButton(option, callback_data=option)])
            keyboard.append([InlineKeyboardButton("Продолжить", callback_data="continue")])

            await update.message.reply_text(
                question,
                reply_markup=InlineKeyboardMarkup(keyboard))

            return FOLLOW_UP

        await update.message.reply_text("Оценка должна быть от 0 до 10. Попробуйте снова:")
        return RATING

    except ValueError:
        await update.message.reply_text("Пожалуйста, введите число:")
        return RATING


async def follow_up(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    user_data = context.user_data
    callback_data = query.data

    if callback_data == "continue":
        await query.edit_message_text(text="✅ Спасибо! Принимаются предложения...")
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text='''И последний вопрос. Напишите ваши предложения по улучшению обучения.
             Какие темы хотели бы изучить в будущем?'''
        )
        return SUGGESTIONS

    feedback_options = user_data.setdefault('feedback_options', [])

    if callback_data in feedback_options:
        feedback_options.remove(callback_data)
    else:
        feedback_options.append(callback_data)

    feedback_type = user_data.get('feedback_type')
    options = HIGH_OPTIONS if feedback_type == 'high' else LOW_OPTIONS

    keyboard = []
    for option in options:
        prefix = "✅ " if option in feedback_options else ""
        keyboard.append([InlineKeyboardButton(f"{prefix}{option}", callback_data=option)])

    keyboard.append([InlineKeyboardButton("➡️ Продолжить", callback_data="continue")])

    await query.edit_message_text(
        text=query.message.text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return FOLLOW_UP


async def suggestions_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['suggestions'] = update.message.text
    await finish_survey(update, context)
    return ConversationHandler.END


async def finish_survey(update: Update, context: ContextTypes.DEFAULT_TYPE):
    feedback_text = format_feedback(context.user_data)
    for admin_id in ADMIN_IDS:
        await context.bot.send_message(admin_id, feedback_text)

    if 'reminder_job' in context.user_data:
        context.user_data['reminder_job'].schedule_removal()

    keyboard = [[InlineKeyboardButton("Заполнить ещё один отзыв", callback_data="/start")]]
    await update.message.reply_text(
        "Спасибо за обратную связь! Бот «ВБ» ждёт вас снова!",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    context.user_data.clear()


def format_feedback(data: dict) -> str:
    text = f"📊 Новый отзыв\n\nДата: {data['date']}\nФИО: {data['full_name']}\n"
    text += f"Комментарий: {data['comment']}\nОценка: {data['rating']}/10\n"

    if data['rating'] >= 7:
        text += "Понравилось: " + ", ".join(data.get('feedback_options', [])) + "\n"
    else:
        text += "Не понравилось: " + ", ".join(data.get('feedback_options', [])) + "\n"

    suggestions = data.get('suggestions', 'Не указано')
    text += f"Предложения: {suggestions}"
    return text


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if 'reminder_job' in context.user_data:
        context.user_data['reminder_job'].schedule_removal()
    await update.message.reply_text("Опрос прерван.")
    context.user_data.clear()
    return ConversationHandler.END


def main() -> None:
    application = Application.builder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(

        entry_points=[CommandHandler('start', start), CallbackQueryHandler(start, pattern="^/start$")],
        states={
            DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, date_input)],
            FULL_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, full_name_input)],
            COMMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, comment_input)],
            RATING: [MessageHandler(filters.TEXT & ~filters.COMMAND, rating_input)],
            FOLLOW_UP: [CallbackQueryHandler(follow_up)],
            SUGGESTIONS: [MessageHandler(filters.TEXT & ~filters.COMMAND, suggestions_input)]
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        allow_reentry=True
    )

    application.add_handler(conv_handler)
    application.run_polling()


if __name__ == '__main__':
    main()
