import asyncio
import logging
import random
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config
import database as db
from questions import QUESTION_BANK, SUBJECTS

logging.basicConfig(level=logging.INFO)

bot = Bot(token=config.BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# ─────────────────────────────────────────────
# FSM States
# ─────────────────────────────────────────────
class QuizStates(StatesGroup):
    choosing_subject = State()
    in_quiz = State()
    waiting_next = State()


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────
TITLES = [
    (0,    "🌱 مبتدئ"),
    (100,  "📚 متعلم"),
    (300,  "🎯 متقدم"),
    (600,  "⭐ محترف"),
    (1000, "🏆 خبير"),
    (2000, "👑 أسطورة"),
]

def get_title(xp: int) -> str:
    title = TITLES[0][1]
    for threshold, label in TITLES:
        if xp >= threshold:
            title = label
    return title

def build_subjects_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for key, subj in SUBJECTS.items():
        builder.button(text=f"{subj['icon']} {subj['name']}", callback_data=f"subject:{key}")
    builder.button(text="🏆 المتصدرون", callback_data="leaderboard")
    builder.button(text="📊 إحصائياتي", callback_data="my_stats")
    builder.adjust(2, 2, 2, 2, 2)
    return builder.as_markup()

def build_options_keyboard(options: list, q_index: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    labels = ["أ", "ب", "ج", "د"]
    for i, opt in enumerate(options):
        builder.button(text=f"{labels[i]}) {opt}", callback_data=f"answer:{q_index}:{i}")
    builder.adjust(1)
    return builder.as_markup()

def progress_bar(current: int, total: int) -> str:
    filled = int((current / total) * 10)
    return "▓" * filled + "░" * (10 - filled)


# ─────────────────────────────────────────────
# /start
# ─────────────────────────────────────────────
@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user = message.from_user
    db.register_user(user.id, user.full_name)

    stats = db.get_user_stats(user.id)
    title = get_title(stats["xp"])

    text = (
        f"👋 أهلاً {user.first_name}!\n\n"
        f"🎓 *بوت الوزاري* — اختبر نفسك وتفوّق!\n\n"
        f"🏅 لقبك: {title}\n"
        f"⚡ XP: {stats['xp']}\n"
        f"🔥 السلسلة: {stats['streak']} يوم\n"
        f"🎮 جولات لُعبت: {stats['total_games']}\n\n"
        f"اختر مادة لتبدأ الاختبار 👇"
    )
    await message.answer(text, parse_mode="Markdown", reply_markup=build_subjects_keyboard())
    await state.set_state(QuizStates.choosing_subject)


# ─────────────────────────────────────────────
# Choose Subject
# ─────────────────────────────────────────────
@dp.callback_query(F.data.startswith("subject:"))
async def choose_subject(callback: CallbackQuery, state: FSMContext):
    subject_key = callback.data.split(":")[1]
    subj = SUBJECTS[subject_key]
    questions_pool = QUESTION_BANK[subject_key]
    selected = random.sample(questions_pool, min(10, len(questions_pool)))

    await state.update_data(
        subject=subject_key,
        questions=selected,
        current=0,
        score=0,
        answers=[]
    )

    await callback.message.edit_text(
        f"{subj['icon']} *مادة {subj['name']}*\n\n"
        f"🎯 جولة مكونة من *{len(selected)} أسئلة*\n"
        f"⏱ مدة كل سؤال: *15 ثانية*\n\n"
        f"بالتوفيق! 🚀",
        parse_mode="Markdown"
    )
    await asyncio.sleep(1.5)
    await send_question(callback.message, state)
    await state.set_state(QuizStates.in_quiz)


async def send_question(message: Message, state: FSMContext):
    data = await state.get_data()
    questions = data["questions"]
    current = data["current"]
    subject_key = data["subject"]
    subj = SUBJECTS[subject_key]

    if current >= len(questions):
        await finish_quiz(message, state)
        return

    q = questions[current]
    total = len(questions)
    bar = progress_bar(current, total)

    text = (
        f"{subj['icon']} *{subj['name']}* | السؤال {current + 1}/{total}\n"
        f"`{bar}`\n\n"
        f"❓ *{q['q']}*\n\n"
        f"⏱ لديك 15 ثانية!"
    )

    kb = build_options_keyboard(q["options"], current)
    sent = await message.answer(text, parse_mode="Markdown", reply_markup=kb)

    # Store message id for timer edit
    await state.update_data(last_msg_id=sent.message_id, timer_running=True)

    # Start 15-second timer
    asyncio.create_task(question_timer(message.chat.id, sent.message_id, state, current))


async def question_timer(chat_id: int, msg_id: int, state: FSMContext, q_index: int):
    await asyncio.sleep(15)
    data = await state.get_data()

    # Check still on same question and unanswered
    if data.get("current") != q_index or not data.get("timer_running", False):
        return

    # Timeout — mark as wrong
    questions = data["questions"]
    q = questions[q_index]
    answers = data.get("answers", [])
    answers.append({"q": q["q"], "options": q["options"], "correct": q["answer"], "chosen": -1})

    await state.update_data(
        current=q_index + 1,
        answers=answers,
        timer_running=False
    )

    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=msg_id,
            text=(
                f"⏰ *انتهى الوقت!*\n\n"
                f"❓ {q['q']}\n\n"
                f"✅ الإجابة الصحيحة: *{q['options'][q['answer']]}*"
            ),
            parse_mode="Markdown"
        )
    except Exception:
        pass

    await asyncio.sleep(2)
    try:
        temp_msg = await bot.send_message(chat_id, "...")
        await send_question(temp_msg, state)
    except Exception:
        pass


# ─────────────────────────────────────────────
# Answer Handler
# ─────────────────────────────────────────────
@dp.callback_query(F.data.startswith("answer:"), QuizStates.in_quiz)
async def handle_answer(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split(":")
    q_index = int(parts[1])
    chosen = int(parts[2])

    data = await state.get_data()

    if data.get("current") != q_index or not data.get("timer_running", False):
        await callback.answer("⚡ تأخرت! السؤال انتهى", show_alert=False)
        return

    await state.update_data(timer_running=False)

    questions = data["questions"]
    q = questions[q_index]
    score = data["score"]
    answers = data.get("answers", [])
    subject_key = data["subject"]
    subj = SUBJECTS[subject_key]

    correct = chosen == q["answer"]
    if correct:
        score += 1

    answers.append({
        "q": q["q"],
        "options": q["options"],
        "correct": q["answer"],
        "chosen": chosen
    })

    await state.update_data(current=q_index + 1, score=score, answers=answers)

    labels = ["أ", "ب", "ج", "د"]
    if correct:
        result_text = f"✅ *إجابة صحيحة!* +10 XP\n\n"
    else:
        result_text = (
            f"❌ *إجابة خاطئة!*\n"
            f"✅ الصحيحة: *{q['options'][q['answer']]}*\n\n"
        )

    total = len(questions)
    bar = progress_bar(q_index + 1, total)

    try:
        await callback.message.edit_text(
            f"{subj['icon']} *{subj['name']}* | السؤال {q_index + 1}/{total}\n"
            f"`{bar}`\n\n"
            f"❓ *{q['q']}*\n\n"
            f"{result_text}"
            f"السؤال التالي خلال ثانية...",
            parse_mode="Markdown"
        )
    except Exception:
        pass

    await callback.answer("✅ صحيح!" if correct else "❌ خطأ", show_alert=False)
    await asyncio.sleep(1.5)
    await send_question(callback.message, state)


# ─────────────────────────────────────────────
# Finish Quiz
# ─────────────────────────────────────────────
async def finish_quiz(message: Message, state: FSMContext):
    data = await state.get_data()
    answers = data["answers"]
    subject_key = data["subject"]
    subj = SUBJECTS[subject_key]
    user_id = message.chat.id

    score = sum(1 for a in answers if a["chosen"] == a["correct"])
    total = len(answers)
    pct = int((score / total) * 100)
    earned_xp = score * 10

    grade = (
        "🌟 ممتاز" if pct >= 90 else
        "⭐ جيد جداً" if pct >= 70 else
        "👍 جيد" if pct >= 50 else
        "📚 تحتاج مراجعة"
    )

    # Update DB
    db.update_stats(user_id, earned_xp, score, total, subject_key)
    stats = db.get_user_stats(user_id)
    title = get_title(stats["xp"])

    # Review keyboard
    builder = InlineKeyboardBuilder()
    builder.button(text="👁 مراجعة الإجابات", callback_data=f"review:0:{subject_key}")
    builder.button(text="🔄 جولة جديدة", callback_data=f"subject:{subject_key}")
    builder.button(text="📚 تغيير المادة", callback_data="back_home")
    builder.button(text="🏆 المتصدرون", callback_data="leaderboard")
    builder.adjust(1, 2, 1)

    text = (
        f"🏁 *انتهت الجولة!*\n\n"
        f"{subj['icon']} *{subj['name']}*\n"
        f"━━━━━━━━━━━━━━━\n"
        f"✅ إجابات صحيحة: *{score}/{total}*\n"
        f"📊 النسبة: *{pct}%*\n"
        f"⚡ XP مكتسب: *+{earned_xp}*\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🏅 التقييم: *{grade}*\n"
        f"🎖 لقبك: {title}\n"
        f"🔥 السلسلة: {stats['streak']} يوم\n"
        f"⚡ إجمالي XP: {stats['xp']}"
    )

    await message.answer(text, parse_mode="Markdown", reply_markup=builder.as_markup())
    await state.clear()
    await state.set_state(QuizStates.choosing_subject)


# ─────────────────────────────────────────────
# Review Answers
# ─────────────────────────────────────────────
@dp.callback_query(F.data.startswith("review:"))
async def review_answers(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split(":")
    idx = int(parts[1])
    subject_key = parts[2]

    data = await state.get_data()
    answers = data.get("answers", [])

    if not answers:
        await callback.answer("لا توجد إجابات للمراجعة", show_alert=True)
        return

    if idx >= len(answers):
        await callback.answer("انتهت المراجعة ✅", show_alert=True)
        return

    a = answers[idx]
    labels = ["أ", "ب", "ج", "د"]

    options_text = ""
    for i, opt in enumerate(a["options"]):
        if i == a["correct"] and i == a["chosen"]:
            options_text += f"✅ {labels[i]}) {opt} ← إجابتك الصحيحة\n"
        elif i == a["correct"]:
            options_text += f"✅ {labels[i]}) {opt} ← الإجابة الصحيحة\n"
        elif i == a["chosen"]:
            options_text += f"❌ {labels[i]}) {opt} ← إجابتك\n"
        else:
            options_text += f"◻️ {labels[i]}) {opt}\n"

    status = "✅ صحيحة" if a["chosen"] == a["correct"] else ("⏰ انتهى الوقت" if a["chosen"] == -1 else "❌ خاطئة")

    builder = InlineKeyboardBuilder()
    if idx > 0:
        builder.button(text="→ السابق", callback_data=f"review:{idx-1}:{subject_key}")
    if idx < len(answers) - 1:
        builder.button(text="التالي ←", callback_data=f"review:{idx+1}:{subject_key}")
    builder.adjust(2)

    text = (
        f"📋 *مراجعة السؤال {idx+1}/{len(answers)}*\n\n"
        f"❓ {a['q']}\n\n"
        f"{options_text}\n"
        f"النتيجة: {status}"
    )

    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=builder.as_markup())
    await callback.answer()


# ─────────────────────────────────────────────
# Leaderboard
# ─────────────────────────────────────────────
@dp.callback_query(F.data == "leaderboard")
async def show_leaderboard(callback: CallbackQuery):
    top = db.get_leaderboard(10)
    medals = ["🥇", "🥈", "🥉"]

    if not top:
        await callback.message.edit_text("لا يوجد لاعبون بعد! العب أول جولة 🎮")
        return

    text = "🏆 *المتصدرون*\n━━━━━━━━━━━━━━━\n"
    for i, row in enumerate(top):
        medal = medals[i] if i < 3 else f"{i+1}."
        title = get_title(row["xp"])
        text += f"{medal} *{row['name']}* — {title}\n    ⚡ {row['xp']} XP  🔥 {row['streak']} يوم\n\n"

    builder = InlineKeyboardBuilder()
    builder.button(text="← رجوع", callback_data="back_home")

    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=builder.as_markup())
    await callback.answer()


# ─────────────────────────────────────────────
# My Stats
# ─────────────────────────────────────────────
@dp.callback_query(F.data == "my_stats")
async def show_my_stats(callback: CallbackQuery):
    user_id = callback.from_user.id
    stats = db.get_user_stats(user_id)
    subject_stats = db.get_subject_stats(user_id)
    title = get_title(stats["xp"])

    text = (
        f"📊 *إحصائياتك*\n━━━━━━━━━━━━━━━\n"
        f"🎖 اللقب: {title}\n"
        f"⚡ إجمالي XP: {stats['xp']}\n"
        f"🔥 السلسلة: {stats['streak']} يوم\n"
        f"🎮 جولات لُعبت: {stats['total_games']}\n\n"
        f"📚 *أداء المواد:*\n"
    )

    for key, subj in SUBJECTS.items():
        s = subject_stats.get(key)
        if s and s["games"] > 0:
            acc = int((s["correct"] / (s["games"] * 10)) * 100)
            bar = "▓" * (acc // 10) + "░" * (10 - acc // 10)
            text += f"{subj['icon']} {subj['name']}: `{bar}` {acc}%\n"
        else:
            text += f"{subj['icon']} {subj['name']}: لم تلعب\n"

    builder = InlineKeyboardBuilder()
    builder.button(text="← رجوع", callback_data="back_home")

    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=builder.as_markup())
    await callback.answer()


# ─────────────────────────────────────────────
# Back Home
# ─────────────────────────────────────────────
@dp.callback_query(F.data == "back_home")
async def back_home(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user_id = callback.from_user.id
    stats = db.get_user_stats(user_id)
    title = get_title(stats["xp"])

    text = (
        f"🎓 *بوت الوزاري*\n\n"
        f"🏅 لقبك: {title}\n"
        f"⚡ XP: {stats['xp']}\n"
        f"🔥 السلسلة: {stats['streak']} يوم\n\n"
        f"اختر مادة 👇"
    )
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=build_subjects_keyboard())
    await state.set_state(QuizStates.choosing_subject)
    await callback.answer()


# ─────────────────────────────────────────────
# /stats command
# ─────────────────────────────────────────────
@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    stats = db.get_user_stats(message.from_user.id)
    subject_stats = db.get_subject_stats(message.from_user.id)
    title = get_title(stats["xp"])

    text = (
        f"📊 *إحصائياتك*\n━━━━━━━━━━━━━━━\n"
        f"🎖 اللقب: {title}\n"
        f"⚡ إجمالي XP: {stats['xp']}\n"
        f"🔥 السلسلة: {stats['streak']} يوم\n"
        f"🎮 جولات لُعبت: {stats['total_games']}\n\n"
    )
    await message.answer(text, parse_mode="Markdown", reply_markup=build_subjects_keyboard())


# ─────────────────────────────────────────────
# Run
# ─────────────────────────────────────────────
async def main():
    db.init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
