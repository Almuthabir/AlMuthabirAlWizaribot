# الجزء 5: الملف الرئيسي (bot.py)
import asyncio
import logging
import random
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import TelegramBadRequest

# استيراد الأجزاء الأخرى
import config
import database as db
from questions import QUESTION_BANK, SUBJECTS, BRANCHES
import keyboards as kb

logging.basicConfig(level=logging.INFO)
bot = Bot(token=config.BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# ─────────────────────────────────────────────
# FSM
# ─────────────────────────────────────────────
class QuizStates(StatesGroup):
    choosing_subject = State()
    in_quiz          = State()
    study_mode       = State()
    challenge_wait   = State()

# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────
TITLES = [
    (0,    "🌱", "مبتدئ"),
    (100,  "📚", "متعلم"),
    (300,  "🎯", "متقدم"),
    (600,  "⭐", "محترف"),
    (1000, "🏆", "خبير"),
    (2000, "👑", "أسطورة"),
]

CERTIFICATES = {
    5: "🥉 شهادة المثابر البرونزية",
    15: "🥈 شهادة المثابر الفضية",
    30: "🥇 شهادة المثابر الذهبية",
    50: "💎 شهادة المثابر الماسية",
    100: "👑 شهادة أسطورة المثابر",
}

def get_title(xp):
    t = TITLES[0]
    for threshold, icon, label in TITLES:
        if xp >= threshold:
            t = (threshold, icon, label)
    return t

def get_certificate(games):
    cert = None
    for g, label in CERTIFICATES.items():
        if games >= g:
            cert = label
    return cert

def welcome_text(user_id, first_name):
    stats = db.get_user_stats(user_id)
    _, icon, label = get_title(stats["xp"])
    cert = get_certificate(stats["total_games"])
    cert_line = f"🏅 {cert}\n" if cert else ""
    return (
        f"👋 أهلاً {first_name}!\n\n"
        f"🎓 *المثابر الوزاري*\n"
        f"━━━━━━━━━━━━━━━\n"
        f"{cert_line}"
        f"{icon} لقبك: *{label}*\n"
        f"⚡ XP: *{stats['xp']}*\n"
        f"🔥 السلسلة: *{stats['streak']}* يوم\n"
        f"🎮 جولات: *{stats['total_games']}*\n\n"
        f"اختر ما تريد 👇"
    )

# ─────────────────────────────────────────────
# Handlers
# ─────────────────────────────────────────────
@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user = message.from_user
    db.register_user(user.id, user.full_name)

    pending = db.get_pending_challenge(user.id)
    if pending:
        # معالجة التحدي المعلق
        pass

    await message.answer(welcome_text(user.id, user.first_name),
                         parse_mode="Markdown", reply_markup=kb.main_menu_kb())
    await state.set_state(QuizStates.choosing_subject)

@dp.callback_query(F.data == "back_home")
async def back_home(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user = callback.from_user
    try:
        await callback.message.edit_text(
            welcome_text(user.id, user.first_name),
            parse_mode="Markdown", reply_markup=kb.main_menu_kb()
        )
    except TelegramBadRequest:
        await callback.message.answer(
            welcome_text(user.id, user.first_name),
            parse_mode="Markdown", reply_markup=kb.main_menu_kb()
        )
    await state.set_state(QuizStates.choosing_subject)
    await callback.answer()

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
