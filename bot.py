import asyncio
import logging
import random
import uuid
from datetime import datetime, date
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest

import config
import database as db
from questions import QUESTION_BANK, SUBJECTS, BRANCHES

logging.basicConfig(level=logging.INFO)
bot = Bot(token=config.BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

MAX_PLAYERS = 25

SUBJECT_MAX_GRADES = {
    "islamic": 50, "arabic": 100, "english": 100, "french": 100,
    "math": 100, "physics": 100, "chemistry": 100, "biology": 100,
    "history": 100, "economics": 100, "geography": 100,
}

# ─────────────────────────────────────────────
# FSM
# ─────────────────────────────────────────────
class QuizStates(StatesGroup):
    choosing_subject  = State()
    in_quiz           = State()
    study_mode        = State()
    challenge_wait    = State()
    challenge_gender  = State()

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

def timer_bar(t, total=15, gender="male"):
    # 15 دائرة صغيرة — ألوان حسب الوقت والجنس
    if gender == "female":
        full  = "🟣"   # وردي/بنفسجي للبنات
        mid   = "🩷"
        low   = "🔴"
    else:
        full  = "🔵"
        mid   = "🟡"
        low   = "🔴"
    char = full if t > 10 else (mid if t > 5 else low)
    filled = t
    empty  = total - t
    return char * filled + "⚪" * empty + f" {t}ث"

def progress_bar(cur, total):
    f = int((cur / total) * 10)
    return "▓" * f + "░" * (10 - f)

def subj_info(key):
    if key == "all":
        return "كل المواد", "🎲"
    s = SUBJECTS.get(key, {})
    return s.get("name", ""), s.get("icon", "📚")

def pick_questions(key, n=10):
    if key == "all":
        pool = [{**q, "_subject": k} for k, qs in QUESTION_BANK.items() for q in qs]
    else:
        pool = QUESTION_BANK.get(key, [])
    selected = random.sample(pool, min(n, len(pool)))
    # خلط ترتيب الخيارات عشوائياً لكل سؤال
    return [shuffle_options(q) for q in selected]

def shuffle_options(q: dict) -> dict:
    """يخلط ترتيب الخيارات ويحدّث رقم الإجابة الصحيحة تلقائياً"""
    options = list(q["options"])
    correct_text = options[q["answer"]]  # نحفظ نص الإجابة الصحيحة
    # نخلط الخيارات
    indices = list(range(len(options)))
    random.shuffle(indices)
    new_options = [options[i] for i in indices]
    new_answer = new_options.index(correct_text)  # نحدد موضع الإجابة الصحيحة الجديد
    return {**q, "options": new_options, "answer": new_answer}

# ─────────────────────────────────────────────
# Grade Prediction
# ─────────────────────────────────────────────
def calc_grade_prediction(subject_stats: dict, branch: str = None) -> str:
    subjects_to_show = list(SUBJECTS.keys())
    if branch and branch in BRANCHES:
        subjects_to_show = BRANCHES[branch]["subjects"]

    lines = []
    total_weighted = 0
    total_max = 0

    for key in subjects_to_show:
        subj = SUBJECTS[key]
        max_grade = SUBJECT_MAX_GRADES.get(key, 100)
        s = subject_stats.get(key)

        if s and s["games"] > 0:
            acc = s["correct"] / (s["games"] * 10)
            predicted = round(acc * max_grade)
            pct = acc * 100
            status = ("🟢 ممتاز" if pct >= 90 else "🔵 جيد جداً" if pct >= 75 else
                      "🟡 جيد" if pct >= 60 else "🟠 مقبول" if pct >= 50 else "🔴 يحتاج مراجعة")
            bar = "▓" * int(pct // 10) + "░" * (10 - int(pct // 10))
            lines.append(
                f"{subj['icon']} *{subj['name']}*\n"
                f"  `{bar}` {int(pct)}%\n"
                f"  📝 التوقع: *{predicted}/{max_grade}* — {status}\n"
            )
            total_weighted += predicted
            total_max += max_grade
        else:
            lines.append(f"{subj['icon']} *{subj['name']}*\n  ⚪ لم تراجع بعد\n")
            total_max += max_grade

    overall = round((total_weighted / total_max) * 100) if total_max > 0 else 0
    overall_label = (
        "🏆 ممتاز — أنت في المسار الصحيح!" if overall >= 85 else
        "⭐ جيد جداً — استمر بالمراجعة!"   if overall >= 70 else
        "💪 جيد — زد من جولاتك!"           if overall >= 55 else
        "📚 تحتاج مراجعة أكثر"             if overall > 0  else
        "العب جولات أولاً لترى توقعاتك!"
    )

    branch_name = BRANCHES[branch]["name"] if branch and branch in BRANCHES else "كل المواد"
    return (
        f"🎯 *توقعات درجاتي — {branch_name}*\n"
        f"━━━━━━━━━━━━━━━\n\n"
        + "\n".join(lines) +
        f"\n━━━━━━━━━━━━━━━\n"
        f"📊 المعدل التقديري: *{overall}%*\n"
        f"{overall_label}\n\n"
        f"_⚠️ توقعات تقريبية بناءً على أدائك في البوت_"
    )

# ─────────────────────────────────────────────
# Keyboards
# ─────────────────────────────────────────────
def main_menu_kb():
    b = InlineKeyboardBuilder()
    # صف 1
    b.button(text="📝 اختبر نفسك",          callback_data="quiz_menu")
    # صف 2
    b.button(text="🌐 اختبار مشترك",        callback_data="group_menu")
    b.button(text="⚔️ تحدي صديق",           callback_data="challenge_menu")
    # صف 3
    b.button(text="🔁 مراجعة أخطائي",      callback_data="wrong_answers_menu")
    b.button(text="🎯 توقع درجتي",          callback_data="grade_prediction_menu")
    # صف 4
    b.button(text="📅 تذكير يومي",          callback_data="reminder_menu")
    b.button(text="📊 إحصائياتي",           callback_data="my_stats")
    # صف 5
    b.button(text="🏆 المتصدرون",           callback_data="leaderboard")
    b.button(text="🎖 شراء لقب",            callback_data="buy_title")
    # صف 6
    b.button(text="⚙️ الإعدادات",           callback_data="settings")
    b.adjust(1, 2, 2, 2, 2, 1)
    return b.as_markup()

def branch_select_kb(prefix="branch"):
    b = InlineKeyboardBuilder()
    for key, branch in BRANCHES.items():
        b.button(text=f"{branch['icon']} {branch['name']}", callback_data=f"{prefix}:{key}")
    b.button(text="🌐 كل الفروع", callback_data=f"{prefix}:all")
    b.button(text="← رجوع", callback_data="back_home")
    b.adjust(1)
    return b.as_markup()

def subjects_for_branch_kb(branch_key: str, prefix="subject"):
    b = InlineKeyboardBuilder()
    if branch_key == "all":
        subjects = list(SUBJECTS.keys())
    else:
        subjects = BRANCHES[branch_key]["subjects"]
    for key in subjects:
        if key in ["arabic_grammar", "arabic_literature"]:
            continue
        subj = SUBJECTS[key]
        b.button(text=f"{subj['icon']} {subj['name']}", callback_data=f"{prefix}:{key}")
    b.button(text="🎲 كل مواد الفرع", callback_data=f"{prefix}:branch_{branch_key}")
    b.button(text="← رجوع", callback_data="subjects_menu")
    b.adjust(2)
    return b.as_markup()

def back_home_kb():
    b = InlineKeyboardBuilder()
    b.button(text="← القائمة الرئيسية", callback_data="back_home")
    return b.as_markup()

def options_kb(options, q_index, prefix="answer"):
    b = InlineKeyboardBuilder()
    labels = ["أ", "ب", "ج", "د"]
    for i, opt in enumerate(options):
        b.button(text=f"{labels[i]}) {opt}", callback_data=f"{prefix}:{q_index}:{i}")
    b.adjust(1)
    return b.as_markup()

# ─────────────────────────────────────────────
# Welcome
# ─────────────────────────────────────────────
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
# /start
# ─────────────────────────────────────────────
@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user = message.from_user
    db.register_user(user.id, user.full_name)

    args = message.text.split()
    if len(args) > 1 and args[1].startswith("session_"):
        await process_join(user, args[1][8:], message)
        return

    pending = db.get_pending_challenge(user.id)
    if pending:
        sn, si = subj_info(pending["subject"])
        b = InlineKeyboardBuilder()
        b.button(text="✅ قبول", callback_data=f"accept_challenge:{pending['id']}")
        b.button(text="❌ رفض",  callback_data="back_home")
        b.adjust(2)
        await message.answer(
            f"⚔️ *تحدي جديد!*\n{si} *{sn}*\nهل تقبل؟",
            parse_mode="Markdown", reply_markup=b.as_markup()
        )
        return

    await message.answer(welcome_text(user.id, user.first_name),
                         parse_mode="Markdown", reply_markup=main_menu_kb())
    await state.set_state(QuizStates.choosing_subject)

@dp.callback_query(F.data == "back_home")
async def back_home(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user = callback.from_user
    try:
        await callback.message.edit_text(
            welcome_text(user.id, user.first_name),
            parse_mode="Markdown", reply_markup=main_menu_kb()
        )
    except TelegramBadRequest:
        await callback.message.answer(
            welcome_text(user.id, user.first_name),
            parse_mode="Markdown", reply_markup=main_menu_kb()
        )
    await state.set_state(QuizStates.choosing_subject)
    await callback.answer()

# ─────────────────────────────────────────────
# اختبر نفسك — القائمة الجديدة
# ─────────────────────────────────────────────
@dp.callback_query(F.data == "quiz_menu")
async def quiz_menu(callback: CallbackQuery):
    b = InlineKeyboardBuilder()
    b.button(text="⚡ اختبار سريع",   callback_data="quiz_type:quick")
    b.button(text="📖 مراجعة هادئة",  callback_data="quiz_type:study")
    b.button(text="← رجوع",           callback_data="back_home")
    b.adjust(2, 1)
    await callback.message.edit_text(
        "📝 *اختبر نفسك*\n\nشلون تريد تراجع؟",
        parse_mode="Markdown", reply_markup=b.as_markup()
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("quiz_type:"))
async def quiz_type_select(callback: CallbackQuery, state: FSMContext):
    qtype = callback.data.split(":")[1]
    await state.update_data(quiz_type=qtype)
    b = InlineKeyboardBuilder()
    for key, branch in BRANCHES.items():
        b.button(text=f"{branch['icon']} {branch['name']}", callback_data=f"qt_branch:{key}")
    b.button(text="← رجوع", callback_data="quiz_menu")
    b.adjust(1)
    await callback.message.edit_text(
        "📚 اختر فرعك الدراسي:",
        parse_mode="Markdown", reply_markup=b.as_markup()
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("qt_branch:"))
async def qt_branch_select(callback: CallbackQuery, state: FSMContext):
    branch_key = callback.data.split(":")[1]
    data = await state.get_data()
    qtype = data.get("quiz_type", "quick")
    await state.update_data(qt_branch=branch_key)

    subjects = BRANCHES[branch_key]["subjects"] if branch_key in BRANCHES else list(SUBJECTS.keys())
    b = InlineKeyboardBuilder()
    for key in subjects:
        if key in ["arabic_grammar", "arabic_literature"]:
            continue
        subj = SUBJECTS[key]
        prefix = "subject" if qtype == "quick" else "study"
        b.button(text=f"{subj['icon']} {subj['name']}", callback_data=f"{prefix}:{key}")
    prefix = "subject" if qtype == "quick" else "study"
    b.button(text="🎲 كل المواد", callback_data=f"{prefix}:branch_{branch_key}")
    b.button(text="← رجوع", callback_data=f"quiz_type:{qtype}")
    b.adjust(2)

    branch_name = BRANCHES[branch_key]["name"] if branch_key in BRANCHES else "كل الفروع"
    await callback.message.edit_text(
        f"📚 *{branch_name}*\n\nاختر مادة الاختبار:",
        parse_mode="Markdown", reply_markup=b.as_markup()
    )
    await callback.answer()

# ─────────────────────────────────────────────
# Subjects Menu (legacy — kept for compatibility)
# ─────────────────────────────────────────────
@dp.callback_query(F.data == "subjects_menu")
async def subjects_menu(callback: CallbackQuery):
    await callback.message.edit_text(
        "📚 *اختر المادة*\n\nأولاً اختر فرعك الدراسي:",
        parse_mode="Markdown",
        reply_markup=branch_select_kb("pick_branch")
    )
    await callback.answer()

@dp.callback_query(F.data == "study_mode_menu")
async def study_mode_menu(callback: CallbackQuery):
    await callback.message.edit_text(
        "📖 *وضع الدراسة*\n\nاختر فرعك الدراسي:",
        parse_mode="Markdown",
        reply_markup=branch_select_kb("study_branch")
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("pick_branch:"))
async def pick_branch(callback: CallbackQuery):
    branch_key = callback.data.split(":")[1]
    branch_name = BRANCHES[branch_key]["name"] if branch_key != "all" else "كل الفروع"
    branch_icon = BRANCHES[branch_key]["icon"] if branch_key != "all" else "🌐"
    await callback.message.edit_text(
        f"{branch_icon} *{branch_name}*\n\nاختر المادة:",
        parse_mode="Markdown",
        reply_markup=subjects_for_branch_kb(branch_key, "subject")
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("study_branch:"))
async def study_branch(callback: CallbackQuery):
    branch_key = callback.data.split(":")[1]
    branch_name = BRANCHES[branch_key]["name"] if branch_key != "all" else "كل الفروع"
    branch_icon = BRANCHES[branch_key]["icon"] if branch_key != "all" else "🌐"
    await callback.message.edit_text(
        f"{branch_icon} *{branch_name}*\n\nاختر المادة:",
        parse_mode="Markdown",
        reply_markup=subjects_for_branch_kb(branch_key, "study")
    )
    await callback.answer()

# ═══════════════════════════════════════════════
# SOLO QUIZ
# ═══════════════════════════════════════════════
@dp.callback_query(F.data.startswith("subject:"))
async def choose_subject(callback: CallbackQuery, state: FSMContext):
    key = callback.data.split(":")[1]
    
    if key == "arabic":
        b = InlineKeyboardBuilder()
        b.button(text="📖 قواعد", callback_data="subject:arabic_grammar")
        b.button(text="📚 أدب", callback_data="subject:arabic_literature")
        b.button(text="← رجوع", callback_data="subjects_menu")
        b.adjust(2, 1)
        await callback.message.edit_text("📝 *العربي*\n\nماذا تريد أن تختبر؟", parse_mode="Markdown", reply_markup=b.as_markup())
        await callback.answer()
        return

    # Handle branch-wide selection
    if key.startswith("branch_"):
        branch_key = key.replace("branch_", "")
        if branch_key == "all":
            qs = pick_questions("all")
        else:
            branch_subjects = BRANCHES[branch_key]["subjects"]
            pool = [{**q, "_subject": k} for k in branch_subjects for q in QUESTION_BANK.get(k, [])]
            qs = random.sample(pool, min(10, len(pool)))
        display_key = key
    else:
        qs = pick_questions(key)
        display_key = key

    sn, si = subj_info(key if not key.startswith("branch_") else "all")
    await state.update_data(subject=display_key, questions=qs, current=0,
                            score=0, answers=[], mode="quiz", quiz_msg_id=None)
    sent = await callback.message.answer(
        f"{si} *{sn}*\n\nجاري تحضير الأسئلة... ⏳", parse_mode="Markdown"
    )
    await state.update_data(quiz_msg_id=sent.message_id)
    await state.set_state(QuizStates.in_quiz)
    await callback.answer()
    await asyncio.sleep(1)
    await run_solo_q(callback.message.chat.id, state)

async def build_q_text(q, cur, total, t, key, gender="male"):
    sn, si = subj_info(key if not key.startswith("branch_") else "all")
    return (
        f"{si} *{sn}* | {cur+1}/{total}\n"
        f"`{progress_bar(cur, total)}`\n\n"
        f"❓ *{q['q']}*\n\n"
        f"⏱ {timer_bar(t, gender=gender)}"
    )

async def show_answer_and_next(chat_id, state: FSMContext, q, cur, total, key, msg_id, timeout=False):
    """عرض الإجابة الصحيحة ثم الانتقال للسؤال التالي"""
    sn, si = subj_info(key if not key.startswith("branch_") else "all")
    labels = ["أ", "ب", "ج", "د"]
    correct_label = f"{labels[q['answer']]}) {q['options'][q['answer']]}"

    if timeout:
        header = "⏰ *انتهى الوقت!*"
    else:
        header = "✅ *انتهى السؤال!*"

    try:
        await bot.edit_message_text(
            chat_id=chat_id, message_id=msg_id,
            text=(
                f"{si} *{sn}* | {cur+1}/{total}\n"
                f"`{progress_bar(cur+1, total)}`\n\n"
                f"❓ *{q['q']}*\n\n"
                f"{header}\n"
                f"✅ الإجابة الصحيحة: *{correct_label}*\n\n"
                f"التالي خلال ثانيتين..."
            ),
            parse_mode="Markdown"
        )
    except TelegramBadRequest:
        pass
    await asyncio.sleep(2)
    await run_solo_q(chat_id, state)

async def run_solo_q(chat_id, state: FSMContext):
    data = await state.get_data()
    qs, cur, key = data["questions"], data["current"], data["subject"]
    msg_id = data["quiz_msg_id"]
    gender = data.get("gender", "male")
    if cur >= len(qs):
        await solo_finish(chat_id, state)
        return
    q = qs[cur]
    total = len(qs)
    await state.update_data(timer_running=True)
    text = await build_q_text(q, cur, total, 15, key, gender)
    try:
        await bot.edit_message_text(chat_id=chat_id, message_id=msg_id,
                                    text=text, parse_mode="Markdown",
                                    reply_markup=options_kb(q["options"], cur))
    except TelegramBadRequest:
        pass
    for t in range(14, -1, -1):
        await asyncio.sleep(1)
        data = await state.get_data()
        if not data.get("timer_running"):
            return
        text = await build_q_text(q, cur, total, t, key, gender)
        try:
            await bot.edit_message_text(chat_id=chat_id, message_id=msg_id,
                                        text=text, parse_mode="Markdown",
                                        reply_markup=options_kb(q["options"], cur))
        except TelegramBadRequest:
            pass

    # انتهى الوقت بدون إجابة
    data = await state.get_data()
    if not data.get("timer_running"):
        return
    await state.update_data(timer_running=False)
    answers = data.get("answers", [])
    answers.append({"q": q["q"], "options": q["options"], "correct": q["answer"], "chosen": -1, "subject": key})
    await state.update_data(current=cur+1, answers=answers)
    # حفظ الخطأ (انتهاء الوقت = خطأ)
    actual_subj = key if not key.startswith("branch_") and key != "all" else q.get("_subject", "mixed")
    db.save_wrong_answer(chat_id, actual_subj, q["q"], q["options"], q["answer"])
    await show_answer_and_next(chat_id, state, q, cur, total, key, msg_id, timeout=True)

@dp.callback_query(F.data.startswith("answer:"), QuizStates.in_quiz)
async def handle_solo_answer(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split(":")
    q_idx, chosen = int(parts[1]), int(parts[2])
    data = await state.get_data()
    if data.get("current") != q_idx or not data.get("timer_running"):
        await callback.answer("⚡ تأخرت!")
        return

    await state.update_data(timer_running=False)

    qs, answers, score = data["questions"], data.get("answers", []), data["score"]
    q, key, msg_id = qs[q_idx], data["subject"], data["quiz_msg_id"]
    chat_id = callback.message.chat.id
    correct = chosen == q["answer"]
    if correct:
        score += 1
    else:
        # حفظ الخطأ
        actual_subj = key if not key.startswith("branch_") and key != "all" else q.get("_subject", "mixed")
        db.save_wrong_answer(chat_id, actual_subj, q["q"], q["options"], q["answer"])

    answers.append({"q": q["q"], "options": q["options"], "correct": q["answer"], "chosen": chosen, "subject": key})
    await state.update_data(current=q_idx+1, score=score, answers=answers)

    sn, si = subj_info(key if not key.startswith("branch_") else "all")
    labels = ["أ", "ب", "ج", "د"]
    correct_label = f"{labels[q['answer']]}) {q['options'][q['answer']]}"
    total = len(qs)

    if correct:
        result_text = f"✅ *إجابة صحيحة!* +10 XP\n✅ الإجابة: *{correct_label}*"
    else:
        chosen_label = f"{labels[chosen]}) {q['options'][chosen]}"
        result_text = f"❌ *إجابة خاطئة!*\nإجابتك: {chosen_label}\n✅ الصحيحة: *{correct_label}*"

    try:
        await bot.edit_message_text(
            chat_id=chat_id, message_id=msg_id,
            text=(
                f"{si} *{sn}* | {q_idx+1}/{total}\n"
                f"`{progress_bar(q_idx+1, total)}`\n\n"
                f"❓ *{q['q']}*\n\n"
                f"{result_text}\n\n"
                f"التالي خلال ثانيتين..."
            ),
            parse_mode="Markdown"
        )
    except TelegramBadRequest:
        pass

    await callback.answer("✅ صحيح!" if correct else "❌ خطأ!")
    await asyncio.sleep(2)
    await run_solo_q(chat_id, state)

async def solo_finish(chat_id, state: FSMContext):
    data = await state.get_data()
    answers, key, mode = data["answers"], data["subject"], data.get("mode", "quiz")
    msg_id = data["quiz_msg_id"]
    score = sum(1 for a in answers if a["chosen"] == a["correct"])
    total = len(answers)
    pct = int((score/total)*100) if total else 0
    xp = score * 10
    grade = ("🌟 ممتاز" if pct>=90 else "⭐ جيد جداً" if pct>=70 else
             "👍 جيد" if pct>=50 else "📚 تحتاج مراجعة")
    if mode == "quiz":
        actual = key if not key.startswith("branch_") and key != "all" else "mixed"
        db.update_stats(chat_id, xp, score, total, actual)
    stats = db.get_user_stats(chat_id)
    _, icon, label = get_title(stats["xp"])
    cert = get_certificate(stats["total_games"])
    cert_line = f"🏅 حصلت على: *{cert}*\n" if cert and mode == "quiz" else ""

    cid = data.get("challenge_id")
    is_ch = data.get("is_challenger", False)
    if cid:
        db.update_challenge_score(cid, is_ch, score)
        challenge = db.get_challenge(cid)
        if challenge and challenge["status"] == "finished":
            c_s, o_s = challenge["challenger_score"], challenge["opponent_score"]
            res = "🤝 تعادل!" if c_s == o_s else ("🏆 فزت!" if (is_ch and c_s > o_s) or (not is_ch and o_s > c_s) else "💪 خسرت!")
            try:
                await bot.edit_message_text(chat_id=chat_id, message_id=msg_id,
                    text=f"⚔️ *نتيجة التحدي*\n━━━━━━━━━━━━━━━\nالمتحدي: {c_s}/10\nالمنافس: {o_s}/10\n\n{res}",
                    parse_mode="Markdown", reply_markup=back_home_kb())
            except TelegramBadRequest:
                pass
            await state.clear()
            return

    sn, si = subj_info(key if not key.startswith("branch_") else "all")
    b = InlineKeyboardBuilder()
    b.button(text="👁 مراجعة الإجابات", callback_data=f"review:0:{key}")
    b.button(text="🔄 جولة جديدة",      callback_data=f"subject:{key}")
    b.button(text="📚 تغيير المادة",    callback_data="subjects_menu")
    b.button(text="🎯 توقعات درجاتي",  callback_data="grade_prediction_menu")
    b.adjust(1, 2, 1)
    try:
        await bot.edit_message_text(chat_id=chat_id, message_id=msg_id,
            text=(f"🏁 *انتهت الجولة!*\n\n{si} *{sn}*\n━━━━━━━━━━━━━━━\n"
                  f"✅ صحيح: *{score}/{total}*\n📊 النسبة: *{pct}%*\n"
                  f"⚡ XP: *+{xp}*\n━━━━━━━━━━━━━━━\n"
                  f"🏅 التقييم: *{grade}*\n{cert_line}"
                  f"{icon} لقبك: {label}\n🔥 السلسلة: {stats['streak']} يوم\n"
                  f"⚡ إجمالي XP: {stats['xp']}"),
            parse_mode="Markdown", reply_markup=b.as_markup())
    except TelegramBadRequest:
        pass
    await state.clear()
    await state.set_state(QuizStates.choosing_subject)

# ═══════════════════════════════════════════════
# STUDY MODE
# ═══════════════════════════════════════════════
@dp.callback_query(F.data.startswith("study:"))
async def start_study(callback: CallbackQuery, state: FSMContext):
    key = callback.data.split(":")[1]
    
    if key == "arabic":
        b = InlineKeyboardBuilder()
        b.button(text="📖 قواعد", callback_data="study:arabic_grammar")
        b.button(text="📚 أدب", callback_data="study:arabic_literature")
        b.button(text="← رجوع", callback_data="study_mode_menu")
        b.adjust(2, 1)
        await callback.message.edit_text("📝 *العربي*\n\nماذا تريد أن تدرس؟", parse_mode="Markdown", reply_markup=b.as_markup())
        await callback.answer()
        return
    if key.startswith("branch_"):
        branch_key = key.replace("branch_", "")
        branch_subjects = BRANCHES[branch_key]["subjects"] if branch_key != "all" else list(SUBJECTS.keys())
        pool = [{**q, "_subject": k} for k in branch_subjects for q in QUESTION_BANK.get(k, [])]
        qs = random.sample(pool, min(10, len(pool)))
    else:
        qs = pick_questions(key)
    await state.update_data(subject=key, questions=qs, current=0,
                            score=0, answers=[], mode="study")
    await callback.message.edit_text("📖 *وضع الدراسة* — خذ وقتك 😊", parse_mode="Markdown")
    await asyncio.sleep(1)
    await send_study_q(callback.message, state)
    await state.set_state(QuizStates.study_mode)
    await callback.answer()

async def send_study_q(message: Message, state: FSMContext):
    data = await state.get_data()
    qs, cur, key = data["questions"], data["current"], data["subject"]
    if cur >= len(qs):
        await solo_finish(message.chat.id, state)
        return
    q = qs[cur]
    total = len(qs)
    sn, si = subj_info(key if not key.startswith("branch_") else "all")
    b = InlineKeyboardBuilder()
    for i, opt in enumerate(q["options"]):
        labels = ["أ", "ب", "ج", "د"]
        b.button(text=f"{labels[i]}) {opt}", callback_data=f"study_ans:{cur}:{i}")
    b.adjust(1)
    await message.answer(
        f"{si} *{sn}* | {cur+1}/{total}\n`{progress_bar(cur, total)}`\n\n📖 *{q['q']}*",
        parse_mode="Markdown", reply_markup=b.as_markup()
    )
    await state.update_data(quiz_msg_id=None)

@dp.callback_query(F.data.startswith("study_ans:"), QuizStates.study_mode)
async def handle_study_ans(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split(":")
    q_idx, chosen = int(parts[1]), int(parts[2])
    data = await state.get_data()
    if data.get("current") != q_idx:
        await callback.answer()
        return
    qs, score, answers = data["questions"], data["score"], data.get("answers", [])
    q = qs[q_idx]
    correct = chosen == q["answer"]
    if correct:
        score += 1
    answers.append({"q": q["q"], "options": q["options"], "correct": q["answer"], "chosen": chosen})
    await state.update_data(current=q_idx+1, score=score, answers=answers,
                            quiz_msg_id=callback.message.message_id)
    feedback = "✅ *صحيح!*" if correct else f"❌ *خطأ!*\n✅ الصحيحة: *{q['options'][q['answer']]}*"
    b = InlineKeyboardBuilder()
    b.button(text="التالي ←", callback_data=f"study_next:{q_idx}")
    try:
        await callback.message.edit_text(f"*{q['q']}*\n\n{feedback}",
                                         parse_mode="Markdown", reply_markup=b.as_markup())
    except TelegramBadRequest:
        pass
    await callback.answer("✅" if correct else "❌")

@dp.callback_query(F.data.startswith("study_next:"))
async def study_next(callback: CallbackQuery, state: FSMContext):
    await send_study_q(callback.message, state)
    await callback.answer()

# ═══════════════════════════════════════════════
# GRADE PREDICTION
# ═══════════════════════════════════════════════
@dp.callback_query(F.data == "grade_prediction_menu")
async def grade_prediction_menu(callback: CallbackQuery):
    await callback.message.edit_text(
        "🎯 *توقعات درجاتي بالوزاري*\n\nاختر فرعك لعرض التوقعات:",
        parse_mode="Markdown",
        reply_markup=branch_select_kb("grade_branch")
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("grade_branch:"))
async def grade_branch(callback: CallbackQuery):
    branch_key = callback.data.split(":")[1]
    subject_stats = db.get_subject_stats(callback.from_user.id)
    text = calc_grade_prediction(subject_stats, branch_key if branch_key != "all" else None)

    b = InlineKeyboardBuilder()
    b.button(text="🔁 فرع آخر", callback_data="grade_prediction_menu")
    b.button(text="← رجوع",    callback_data="back_home")
    b.adjust(2)
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=b.as_markup())
    await callback.answer()

# ═══════════════════════════════════════════════
# GROUP QUIZ
# ═══════════════════════════════════════════════
group_sessions = {}
auto_quiz_tasks = {}   # chat_id -> task
auto_quiz_answered = {}  # msg_id -> question data

MAX_AUTO_ANSWERERS = 3  # عدد المجيبين قبل إقفال السؤال

async def run_auto_quiz(chat_id: int, interval_minutes: int):
    while True:
        await asyncio.sleep(interval_minutes * 60)
        try:
            pool = [{**q, "_subject": k} for k, qs in QUESTION_BANK.items() for q in qs]
            q = shuffle_options(random.choice(pool))
            subj_key = q.get("_subject", "mixed")
            subj = SUBJECTS.get(subj_key, {})
            si = subj.get("icon", "📚")
            sn = subj.get("name", "")
            labels = ["أ", "ب", "ج", "د"]
            b = InlineKeyboardBuilder()
            for i, opt in enumerate(q["options"]):
                b.button(
                    text=f"{labels[i]}) {opt}",
                    callback_data=f"auto_ans:{subj_key}:{q['answer']}:{i}"
                )
            b.adjust(1)
            sent = await bot.send_message(
                chat_id,
                f"🎯 *سؤال المثابر التلقائي*\n{si} *{sn}*\n\n❓ *{q['q']}*\n\n"
                f"⚡ أول 3 أشخاص يجاوبون يظهر اسمهم!\nمن يجاوب صح يحصل +5 XP 🎁",
                parse_mode="Markdown", reply_markup=b.as_markup()
            )
            # تسجيل السؤال كمفتوح
            auto_quiz_answered[sent.message_id] = {
                "answered": False,
                "correct_idx": q["answer"],
                "options": q["options"],
                "question": q["q"],
                "subj_key": subj_key,
                "chat_id": chat_id,
                "msg_id": sent.message_id,
                "answerers": [],        # قائمة من أجابوا
                "answerer_ids": set(),  # لمنع التكرار
            }
        except asyncio.CancelledError:
            break
        except Exception:
            pass

@dp.callback_query(F.data.startswith("auto_ans:"))
async def auto_answer(callback: CallbackQuery):
    parts = callback.data.split(":")
    subj_key, correct_idx, chosen = parts[1], int(parts[2]), int(parts[3])
    msg_id = callback.message.message_id
    user = callback.from_user
    labels = ["أ", "ب", "ج", "د"]

    q_data = auto_quiz_answered.get(msg_id)
    if not q_data:
        await callback.answer("⚡ انتهى السؤال!", show_alert=True)
        return

    # منع التكرار — كل شخص يجاوب مرة واحدة فقط
    if user.id in q_data["answerer_ids"]:
        await callback.answer("✋ أجبت بالفعل!", show_alert=True)
        return

    # السؤال مقفل بعد 3 مجيبين
    if q_data["answered"]:
        await callback.answer("⚡ اكتمل عدد المجيبين!", show_alert=True)
        return

    correct = chosen == correct_idx
    correct_label = f"{labels[correct_idx]}) {q_data['options'][correct_idx]}"

    # إعطاء XP إذا صحيح
    if correct:
        db.update_stats(user.id, 5, 1, 1, subj_key)
        result_icon = "✅"
        await callback.answer("✅ صحيح! +5 XP 🎉", show_alert=False)
    else:
        db.save_wrong_answer(user.id, subj_key,
                             q_data["question"],
                             q_data["options"],
                             correct_idx)
        result_icon = "❌"
        await callback.answer(f"❌ خطأ! الصحيحة: {labels[correct_idx]}", show_alert=True)

    # تسجيل المجيب
    q_data["answerers"].append(f"{result_icon} {user.first_name}")
    q_data["answerer_ids"].add(user.id)

    answerers_count = len(q_data["answerers"])

    # إذا وصلنا 3 مجيبين — أقفل السؤال وأظهر الإجابة
    if answerers_count >= MAX_AUTO_ANSWERERS:
        q_data["answered"] = True

        opts_text = "\n".join(
            f"{'✅' if i == correct_idx else '◻️'} {labels[i]}) {q_data['options'][i]}"
            for i in range(len(q_data["options"]))
        )
        answerers_text = "\n".join(q_data["answerers"])

        try:
            await callback.message.edit_text(
                f"🎯 *سؤال المثابر التلقائي*\n\n"
                f"❓ *{q_data['question']}*\n\n"
                f"{opts_text}\n\n"
                f"━━━━━━━━━━━━━━━\n"
                f"✅ الإجابة الصحيحة: *{correct_label}*\n\n"
                f"👥 *المجيبون:*\n{answerers_text}",
                parse_mode="Markdown"
            )
        except TelegramBadRequest:
            pass
    else:
        # حدّث الرسالة وأظهر من أجاب حتى الآن
        answerers_text = "\n".join(q_data["answerers"])
        remaining = MAX_AUTO_ANSWERERS - answerers_count

        try:
            await callback.message.edit_text(
                f"🎯 *سؤال المثابر التلقائي*\n\n"
                f"❓ *{q_data['question']}*\n\n"
                f"👥 *أجاب ({answerers_count}/{MAX_AUTO_ANSWERERS}):*\n{answerers_text}\n\n"
                f"⏳ متبقي *{remaining}* {'شخص' if remaining > 1 else 'شخص واحد'} للإقفال...",
                parse_mode="Markdown",
                reply_markup=callback.message.reply_markup
            )
        except TelegramBadRequest:
            pass

@dp.callback_query(F.data == "group_menu")
async def group_menu(callback: CallbackQuery):
    b = InlineKeyboardBuilder()
    b.button(text="🚀 ابدأ جولة مجموعة",       callback_data="group_start_flow")
    b.button(text="⏰ سؤال تلقائي للمجموعة",   callback_data="auto_quiz_menu")
    b.button(text="← رجوع",                    callback_data="back_home")
    b.adjust(1)
    await callback.message.edit_text(
        "🌐 *الاختبار المشترك*\n\nاختر نوع الجولة:",
        parse_mode="Markdown", reply_markup=b.as_markup()
    )
    await callback.answer()

@dp.callback_query(F.data == "group_start_flow")
async def group_start_flow(callback: CallbackQuery):
    await callback.message.edit_text(
        "👥 *جولة مجموعة*\n\nاختر فرعك أولاً:",
        parse_mode="Markdown",
        reply_markup=branch_select_kb("group_branch")
    )
    await callback.answer()

@dp.callback_query(F.data == "auto_quiz_menu")
async def auto_quiz_menu(callback: CallbackQuery):
    b = InlineKeyboardBuilder()
    b.button(text="⏱ كل نص ساعة",  callback_data="auto_interval:30")
    b.button(text="⏱ كل ساعة",     callback_data="auto_interval:60")
    b.button(text="← رجوع",         callback_data="group_menu")
    b.adjust(2, 1)
    await callback.message.edit_text(
        "⏰ *السؤال التلقائي*\n\n"
        "أضف البوت لمجموعتك أو قناتك، ثم اختر الفترة الزمنية.\n"
        "سيرسل البوت سؤالاً تلقائياً بالفترة المختارة.\n\n"
        "كم تريد الفترة؟",
        parse_mode="Markdown", reply_markup=b.as_markup()
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("auto_interval:"))
async def auto_interval_select(callback: CallbackQuery):
    interval = int(callback.data.split(":")[1])
    b = InlineKeyboardBuilder()
    b.button(text="📤 شارك في مجموعة أو قناة", switch_inline_query="auto_quiz")
    b.button(text="← رجوع", callback_data="auto_quiz_menu")
    b.adjust(1)
    # حفظ الفترة في بيانات المستخدم
    await callback.message.edit_text(
        f"✅ *تم الاختيار — كل {interval} دقيقة*\n\n"
        f"الآن شارك الرسالة في مجموعتك أو قناتك 👇\n"
        f"أو أضف البوت للمجموعة وأرسل:\n`/autostart {interval}`",
        parse_mode="Markdown", reply_markup=b.as_markup()
    )
    await callback.answer()

@dp.message(Command("autostart"))
async def cmd_autostart(message: Message):
    parts = message.text.split()
    interval = 30
    if len(parts) > 1 and parts[1].isdigit():
        interval = int(parts[1])
        interval = max(10, min(interval, 120))

    chat_id = message.chat.id
    if chat_id in auto_quiz_tasks:
        auto_quiz_tasks[chat_id].cancel()

    task = asyncio.create_task(run_auto_quiz(chat_id, interval))
    auto_quiz_tasks[chat_id] = task
    await message.answer(
        f"✅ *تم تفعيل الأسئلة التلقائية!*\n"
        f"⏱ سؤال كل *{interval}* دقيقة\n\n"
        f"لإيقافه أرسل: `/autostop`",
        parse_mode="Markdown"
    )

@dp.message(Command("autostop"))
async def cmd_autostop(message: Message):
    chat_id = message.chat.id
    if chat_id in auto_quiz_tasks:
        auto_quiz_tasks[chat_id].cancel()
        del auto_quiz_tasks[chat_id]
        await message.answer("🔕 تم إيقاف الأسئلة التلقائية.")
    else:
        await message.answer("ما في أسئلة تلقائية مفعّلة حالياً.")

async def run_auto_quiz(chat_id: int, interval_minutes: int):
    while True:
        await asyncio.sleep(interval_minutes * 60)
        try:
            pool = [{**q, "_subject": k} for k, qs in QUESTION_BANK.items() for q in qs]
            q = shuffle_options(random.choice(pool))
            subj_key = q.get("_subject", "mixed")
            subj = SUBJECTS.get(subj_key, {})
            si = subj.get("icon", "📚")
            sn = subj.get("name", "")
            labels = ["أ", "ب", "ج", "د"]
            b = InlineKeyboardBuilder()
            for i, opt in enumerate(q["options"]):
                b.button(text=f"{labels[i]}) {opt}", callback_data=f"auto_ans:{subj_key}:{q['answer']}:{i}")
            b.adjust(1)
            await bot.send_message(
                chat_id,
                f"🎯 *سؤال المثابر التلقائي*\n{si} *{sn}*\n\n❓ *{q['q']}*",
                parse_mode="Markdown", reply_markup=b.as_markup()
            )
        except asyncio.CancelledError:
            break
        except Exception:
            pass

@dp.callback_query(F.data.startswith("auto_ans:"))
async def auto_answer(callback: CallbackQuery):
    parts = callback.data.split(":")
    subj_key, correct_idx, chosen = parts[1], int(parts[2]), int(parts[3])
    correct = chosen == correct_idx
    labels = ["أ", "ب", "ج", "د"]
    if correct:
        await callback.answer(f"✅ صحيح! أحسنت 🎉", show_alert=False)
    else:
        await callback.answer(f"❌ خطأ! الصحيحة: {labels[correct_idx]}", show_alert=True)

@dp.callback_query(F.data.startswith("group_branch:"))
async def group_branch(callback: CallbackQuery):
    branch_key = callback.data.split(":")[1]
    branch_name = BRANCHES[branch_key]["name"] if branch_key != "all" else "كل الفروع"
    await callback.message.edit_text(
        f"🌐 *الاختبار المشترك — {branch_name}*\n\nاختر المادة:",
        parse_mode="Markdown",
        reply_markup=subjects_for_branch_kb(branch_key, "group_create")
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("group_create:"))
async def group_create(callback: CallbackQuery):
    key = callback.data.split(":")[1]
    
    if key == "arabic":
        b = InlineKeyboardBuilder()
        b.button(text="📖 قواعد", callback_data="group_create:arabic_grammar")
        b.button(text="📚 أدب", callback_data="group_create:arabic_literature")
        b.button(text="← رجوع", callback_data="group_menu")
        b.adjust(2, 1)
        await callback.message.edit_text("📝 *العربي*\n\nاختر نوع الجولة:", parse_mode="Markdown", reply_markup=b.as_markup())
        await callback.answer()
        return
    user = callback.from_user
    sid = str(uuid.uuid4())[:8].upper()
    sn, si = subj_info(key if not key.startswith("branch_") else "all")
    bot_info = await bot.get_me()

    if key.startswith("branch_"):
        branch_key = key.replace("branch_", "")
        branch_subjects = BRANCHES[branch_key]["subjects"] if branch_key != "all" else list(SUBJECTS.keys())
        pool = [{**q, "_subject": k} for k in branch_subjects for q in QUESTION_BANK.get(k, [])]
        questions = random.sample(pool, min(10, len(pool)))
    else:
        questions = pick_questions(key)

    group_sessions[sid] = {
        "subject": key, "owner_id": user.id, "owner_name": user.full_name,
        "status": "waiting", "chat_id": None, "msg_id": None,
        "questions": questions, "current": 0,
        "players": {user.id: {"name": user.full_name, "score": 0}},
        "answered": {},
    }

    share_link = f"https://t.me/{bot_info.username}?start=session_{sid}"
    b = InlineKeyboardBuilder()
    b.button(text="🚀 ابدأ في هذه المحادثة", callback_data=f"start_here:{sid}")
    b.adjust(1)

    await callback.message.edit_text(
        f"✅ *تم إنشاء الجولة!*\n\n{si} *{sn}*\n🔑 الكود: `{sid}`\n\n"
        f"*شارك هذا الأمر بمجموعتك:*\n`/startquiz {sid}`\n\n"
        f"*أو الرابط المباشر:*\n{share_link}",
        parse_mode="Markdown", reply_markup=b.as_markup()
    )
    await callback.answer()

@dp.message(Command("startquiz"))
async def cmd_startquiz(message: Message):
    parts = message.text.split()
    if len(parts) == 1:
        b = InlineKeyboardBuilder()
        for bkey, branch in BRANCHES.items():
            b.button(text=f"{branch['icon']} {branch['name']}",
                     callback_data=f"quick_branch:{bkey}:{message.chat.id}")
        b.adjust(1)
        await message.answer("👥 *جولة مجموعة*\n\nاختر الفرع:", parse_mode="Markdown", reply_markup=b.as_markup())
        return
    sid = parts[1].upper()
    if sid not in group_sessions:
        await message.answer("❌ كود الجولة غير صحيح!")
        return
    session = group_sessions[sid]
    if session["owner_id"] != message.from_user.id:
        await message.answer("❌ فقط صاحب الجولة يقدر يبدأ!")
        return
    session["chat_id"] = message.chat.id
    await launch_group_quiz(message.chat.id, sid)

@dp.callback_query(F.data.startswith("quick_branch:"))
async def quick_branch(callback: CallbackQuery):
    parts = callback.data.split(":")
    branch_key = parts[1]
    chat_id = int(parts[2])
    await callback.message.edit_text(
        "اختر المادة:",
        reply_markup=subjects_for_branch_kb(branch_key, f"quick_quiz_{chat_id}")
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("start_here:"))
async def start_here(callback: CallbackQuery):
    sid = callback.data.split(":")[1]
    if sid not in group_sessions:
        await callback.answer("❌ الجولة غير موجودة!", show_alert=True)
        return
    session = group_sessions[sid]
    if session["owner_id"] != callback.from_user.id:
        await callback.answer("❌ فقط صاحب الجولة!", show_alert=True)
        return
    session["chat_id"] = callback.message.chat.id
    await callback.answer("🚀 تبدأ الجولة!")
    await launch_group_quiz(callback.message.chat.id, sid)

async def process_join(user, sid, source):
    if sid not in group_sessions:
        txt = "❌ الجولة غير موجودة!"
        if isinstance(source, CallbackQuery):
            await source.answer(txt, show_alert=True)
        else:
            await source.answer(txt)
        return

    session = group_sessions[sid]

    if session["status"] != "waiting":
        txt = "❌ الجولة بدأت بالفعل!"
        if isinstance(source, CallbackQuery):
            await source.answer(txt, show_alert=True)
        else:
            await source.answer(txt)
        return

    if len(session["players"]) >= MAX_PLAYERS:
        txt = "❌ الجولة ممتلئة!"
        if isinstance(source, CallbackQuery):
            await source.answer(txt, show_alert=True)
        else:
            await source.answer(txt)
        return

    # ── تحقق إذا الشخص فعّل البوت ──────────────────
    bot_info = await bot.get_me()
    activate_link = f"https://t.me/{bot_info.username}?start=session_{sid}"

    # نحاول نرسل له رسالة خاصة — إذا فشلت يعني ما فعّل البوت
    bot_activated = True
    try:
        await bot.send_message(
            user.id,
            f"⏳ *جاري الانضمام للجولة...*\n\nسيبدأ البوت بإرسال الأسئلة لك هنا.",
            parse_mode="Markdown"
        )
    except Exception:
        bot_activated = False

    if not bot_activated:
        # أخبر المجموعة إنه يحتاج يفعّل البوت
        group_chat_id = session.get("chat_id")

        if isinstance(source, CallbackQuery):
            await source.answer("⚠️ يجب تفعيل البوت أولاً!", show_alert=True)

        # رسالة في المجموعة مع زر تفعيل
        b = InlineKeyboardBuilder()
        b.button(
            text="🤖 فعّل البوت وانضم للجولة",
            url=activate_link
        )
        notification_text = (
            f"⚠️ {user.first_name} يحتاج تفعيل البوت أولاً للمشاركة!\n\n"
            f"اضغط الزر أدناه لتفعيل البوت والانضمام للجولة 👇"
        )

        try:
            if group_chat_id:
                await bot.send_message(
                    group_chat_id,
                    notification_text,
                    parse_mode="Markdown",
                    reply_markup=b.as_markup()
                )
            elif isinstance(source, CallbackQuery):
                await source.message.answer(
                    notification_text,
                    parse_mode="Markdown",
                    reply_markup=b.as_markup()
                )
        except Exception:
            pass
        return

    # ── انضم بنجاح ───────────────────────────────────
    session["players"][user.id] = {"name": user.full_name, "score": 0}
    sn, si = subj_info(session["subject"] if not session["subject"].startswith("branch_") else "all")

    # رسالة خاصة تأكيد الانضمام
    try:
        await bot.send_message(
            user.id,
            f"✅ *انضممت للجولة!*\n\n"
            f"{si} *{sn}*\n"
            f"👥 اللاعبون حالياً: {len(session['players'])}\n\n"
            f"انتظر حتى يبدأ صاحب الجولة... ⏳",
            parse_mode="Markdown"
        )
    except Exception:
        pass

    if isinstance(source, CallbackQuery):
        await source.answer(f"✅ انضممت! ({len(session['players'])} لاعب)")
    elif isinstance(source, Message):
        await source.answer(
            f"✅ *انضممت للجولة!*\n{si} *{sn}*\nاللاعبون: {len(session['players'])}\nانتظر البداية...",
            parse_mode="Markdown"
        )

async def launch_group_quiz(chat_id: int, sid: str):
    session = group_sessions[sid]
    session["status"] = "active"
    session["chat_id"] = chat_id  # تأكد إن chat_id محفوظ
    qs = session["questions"]
    key = session["subject"]
    sn, si = subj_info(key if not key.startswith("branch_") else "all")
    total = len(qs)

    bot_info = await bot.get_me()
    activate_link = f"https://t.me/{bot_info.username}?start=session_{sid}"

    # رسالة البداية مع زر الانضمام
    b = InlineKeyboardBuilder()
    b.button(text="✋ انضم للجولة", url=activate_link)
    b.adjust(1)

    await bot.send_message(
        chat_id,
        f"🚀 *جولة المثابر الوزاري بدأت!*\n"
        f"{si} *{sn}* — {total} أسئلة\n"
        f"⏱ 15 ثانية لكل سؤال\n\n"
        f"⚠️ *للمشاركة يجب تفعيل البوت أولاً*\n"
        f"اضغط الزر أدناه 👇\n\n"
        f"استعدوا... 3️⃣2️⃣1️⃣",
        parse_mode="Markdown",
        reply_markup=b.as_markup()
    )
    await asyncio.sleep(5)

    bot_info = await bot.get_me()
    activate_link_base = f"https://t.me/{bot_info.username}?start=session_{sid}"

    for q_idx, q in enumerate(qs):
        session["answered"] = {}
        session["current"]  = q_idx
        session["q_done"]   = False
        labels = ["أ", "ب", "ج", "د"]
        activate_link = activate_link_base

        def build_group_q(t, _q=q, _q_idx=q_idx):
            names = [p["name"] for uid, p in session["players"].items() if uid in session["answered"]]
            ans_line = f"\n\n✅ أجاب: {', '.join(names)} ({len(names)}/{len(session['players'])})" if names else ""
            return (f"{si} *{sn}* | {_q_idx+1}/{total}\n`{progress_bar(_q_idx, total)}`\n\n"
                    f"❓ *{_q['q']}*\n\n⏱ {timer_bar(t)}{ans_line}")

        def answer_kb(_q_idx=q_idx):
            b = InlineKeyboardBuilder()
            for i, opt in enumerate(q["options"]):
                b.button(text=f"{labels[i]}) {opt}", callback_data=f"gq:{sid}:{_q_idx}:{i}")
            b.button(text="✋ انضم للجولة", url=activate_link)
            b.adjust(1)
            return b.as_markup()

        sent = await bot.send_message(chat_id, build_group_q(15), parse_mode="Markdown", reply_markup=answer_kb())
        session["msg_id"] = sent.message_id

        # Countdown — ينتهي مبكراً إذا أجاب الكل
        for t in range(14, -1, -1):
            await asyncio.sleep(1)

            # تحقق إذا أجاب الكل مبكراً
            if session.get("q_done"):
                break

            all_answered = len(session["answered"]) >= len(session["players"])
            if all_answered:
                session["q_done"] = True
                break

            try:
                await bot.edit_message_text(chat_id=chat_id, message_id=sent.message_id,
                    text=build_group_q(t), parse_mode="Markdown",
                    reply_markup=answer_kb() if t > 0 else None)
            except TelegramBadRequest:
                pass

        # عرض الإجابة الصحيحة + النتيجة فوراً
        correct_ans   = q["answer"]
        correct_label = f"{labels[correct_ans]}) {q['options'][correct_ans]}"
        correct_p = [p["name"] for uid, p in session["players"].items() if session["answered"].get(uid) == correct_ans]
        wrong_p   = [p["name"] for uid, p in session["players"].items() if uid in session["answered"] and session["answered"][uid] != correct_ans]
        no_ans_p  = [p["name"] for uid, p in session["players"].items() if uid not in session["answered"]]

        # تحديث الرسالة بالإجابة الصحيحة
        opts_text = "\n".join(
            f"{'✅' if i == correct_ans else '◻️'} {labels[i]}) {q['options'][i]}"
            for i in range(len(q["options"]))
        )
        early = " (أجاب الكل مبكراً ⚡)" if session.get("q_done") else ""
        try:
            await bot.edit_message_text(
                chat_id=chat_id, message_id=sent.message_id,
                text=(
                    f"{si} *{sn}* | {q_idx+1}/{total}\n"
                    f"`{progress_bar(q_idx+1, total)}`\n\n"
                    f"❓ *{q['q']}*\n\n{opts_text}\n\n"
                    f"✅ الإجابة الصحيحة: *{correct_label}*{early}"
                ),
                parse_mode="Markdown"
            )
        except TelegramBadRequest:
            pass

        # رسالة النتيجة
        res = f"📊 *نتيجة السؤال {q_idx+1}*\n✅ الصحيحة: *{correct_label}*\n\n"
        if correct_p: res += f"✅ أجاب صح ({len(correct_p)}): {', '.join(correct_p)}\n"
        if wrong_p:   res += f"❌ أخطأ ({len(wrong_p)}): {', '.join(wrong_p)}\n"
        if no_ans_p:  res += f"⏰ لم يجب ({len(no_ans_p)}): {', '.join(no_ans_p)}\n"

        await bot.send_message(chat_id, res, parse_mode="Markdown")
        await asyncio.sleep(3)

    # Final results
    sorted_p = sorted(session["players"].items(), key=lambda x: x[1]["score"], reverse=True)
    medals = ["🥇", "🥈", "🥉"]
    final = f"🏆 *النتائج النهائية*\n{si} *{sn}*\n━━━━━━━━━━━━━━━\n"
    for i, (uid, p) in enumerate(sorted_p):
        medal = medals[i] if i < 3 else f"{i+1}."
        pct = int((p["score"] / total) * 100)
        final += f"{medal} *{p['name']}* — {p['score']}/{total} ({pct}%)\n"
    final += "━━━━━━━━━━━━━━━\n🎉 تهانينا للمتصدرين!"

    b = InlineKeyboardBuilder()
    b.button(text="🔄 جولة جديدة", callback_data="group_menu")
    await bot.send_message(chat_id, final, parse_mode="Markdown", reply_markup=b.as_markup())

    for uid, p in session["players"].items():
        if p["score"] > 0:
            db.update_stats(uid, p["score"]*10, p["score"], total, key if not key.startswith("branch_") else "mixed")

    del group_sessions[sid]

@dp.callback_query(F.data.startswith("gq:"))
async def group_answer(callback: CallbackQuery):
    parts = callback.data.split(":")
    sid, q_idx, chosen = parts[1], int(parts[2]), int(parts[3])
    user = callback.from_user

    if sid not in group_sessions:
        await callback.answer("❌ الجولة انتهت!")
        return

    session = group_sessions[sid]
    if user.id not in session["players"]:
        if len(session["players"]) >= MAX_PLAYERS:
            await callback.answer("❌ الجولة ممتلئة!", show_alert=True)
            return
        session["players"][user.id] = {"name": user.full_name, "score": 0}

    if user.id in session["answered"]:
        await callback.answer("✋ أجبت بالفعل!")
        return

    if session["current"] != q_idx:
        await callback.answer("⚡ تأخرت!")
        return

    session["answered"][user.id] = chosen
    q = session["questions"][q_idx]
    correct = chosen == q["answer"]
    if correct:
        session["players"][user.id]["score"] += 1

    labels = ["أ", "ب", "ج", "د"]
    await callback.answer("✅ صحيح! +1" if correct else f"❌ خطأ! الصحيحة: {labels[q['answer']]}")

    # تحديث الرسالة بأسماء من أجاب
    names = [p["name"] for uid, p in session["players"].items() if uid in session["answered"]]
    sn, si = subj_info(session["subject"] if not session["subject"].startswith("branch_") else "all")
    total = len(session["questions"])

    try:
        await callback.message.edit_text(
            f"{si} *{sn}* | {q_idx+1}/{total}\n`{progress_bar(q_idx, total)}`\n\n"
            f"❓ *{q['q']}*\n\n"
            f"✅ أجاب: {', '.join(names)} ({len(names)}/{len(session['players'])} لاعب)",
            parse_mode="Markdown", reply_markup=callback.message.reply_markup
        )
    except TelegramBadRequest:
        pass

    # إذا أجاب الكل — أنهِ السؤال مبكراً
    if len(session["answered"]) >= len(session["players"]):
        session["q_done"] = True

# ═══════════════════════════════════════════════
# CHALLENGE, LEADERBOARD, STATS, REVIEW, REMINDERS
# (نفس الكود من v4 بدون تغيير)
# ═══════════════════════════════════════════════
@dp.callback_query(F.data == "challenge_menu")
async def challenge_menu(callback: CallbackQuery, state: FSMContext):
    b = InlineKeyboardBuilder()
    b.button(text="👦 ولد", callback_data="challenge_gender:male")
    b.button(text="👧 بنت", callback_data="challenge_gender:female")
    b.button(text="← رجوع", callback_data="back_home")
    b.adjust(2, 1)
    await callback.message.edit_text(
        "⚔️ *تحدي صديق*\n\nصديقك بنت ولا ولد؟",
        parse_mode="Markdown", reply_markup=b.as_markup()
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("challenge_gender:"))
async def challenge_gender_select(callback: CallbackQuery, state: FSMContext):
    gender = callback.data.split(":")[1]
    await state.update_data(challenge_gender=gender)
    await callback.message.edit_text(
        "⚔️ *تحدي صديق*\n\nاختر الفرع:",
        parse_mode="Markdown", reply_markup=branch_select_kb("challenge_branch")
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("challenge_branch:"))
async def challenge_branch(callback: CallbackQuery, state: FSMContext):
    branch_key = callback.data.split(":")[1]
    await callback.message.edit_text("⚔️ اختر المادة:", parse_mode="Markdown",
                                     reply_markup=subjects_for_branch_kb(branch_key, "challenge_subject"))
    await callback.answer()

@dp.callback_query(F.data.startswith("challenge_subject:"))
async def challenge_select(callback: CallbackQuery, state: FSMContext):
    key = callback.data.split(":")[1]
    await state.update_data(challenge_subject=key)
    await callback.message.edit_text(
        "⚔️ أرسل يوزرنيم صديقك (مثال: @username):",
        parse_mode="Markdown", reply_markup=back_home_kb()
    )
    await state.set_state(QuizStates.challenge_wait)
    await callback.answer()

@dp.message(QuizStates.challenge_wait)
async def challenge_search(message: Message, state: FSMContext):
    username = message.text.strip().lstrip("@")
    results = db.get_user_by_username_search(username)
    if not results:
        await message.answer(
            "❌ *غير موجود!*\n\nاطلب من صديقك يفعّل البوت أولاً ويرسل /start",
            parse_mode="Markdown", reply_markup=back_home_kb()
        )
        return
    data = await state.get_data()
    key = data.get("challenge_subject", "math")
    b = InlineKeyboardBuilder()
    for u in results:
        if u["user_id"] != message.from_user.id:
            b.button(text=f"⚔️ {u['name']}", callback_data=f"send_challenge:{u['user_id']}:{key}")
    b.button(text="← رجوع", callback_data="back_home")
    b.adjust(1)
    await message.answer("اختر من تريد تتحداه:", reply_markup=b.as_markup())

@dp.callback_query(F.data.startswith("send_challenge:"))
async def send_challenge_cb(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split(":")
    opp, key = int(parts[1]), parts[2]
    data = await state.get_data()
    gender = data.get("challenge_gender", "male")
    cid = db.create_challenge(callback.from_user.id, opp, key)
    sn, si = subj_info(key if not key.startswith("branch_") else "all")
    try:
        b = InlineKeyboardBuilder()
        b.button(text="✅ قبول", callback_data=f"accept_challenge:{cid}")
        b.button(text="❌ رفض",  callback_data="back_home")
        b.adjust(2)
        await bot.send_message(opp, f"⚔️ *تحدي من {callback.from_user.full_name}!*\n{si} *{sn}*\nهل تقبل؟",
                                parse_mode="Markdown", reply_markup=b.as_markup())
    except Exception:
        pass
    qs = pick_questions(key)
    sent = await callback.message.answer(f"✅ *تم إرسال التحدي!*\n{si} *{sn}*\nجولتك تبدأ الآن...", parse_mode="Markdown")
    await state.update_data(subject=key, questions=qs, current=0, score=0, answers=[],
                            mode="challenge", challenge_id=cid, is_challenger=True,
                            quiz_msg_id=sent.message_id, gender=gender)
    await asyncio.sleep(2)
    await state.set_state(QuizStates.in_quiz)
    await run_solo_q(callback.message.chat.id, state)
    await callback.answer()

@dp.callback_query(F.data.startswith("accept_challenge:"))
async def accept_challenge_cb(callback: CallbackQuery, state: FSMContext):
    cid = int(callback.data.split(":")[1])
    challenge = db.get_challenge(cid)
    if not challenge:
        await callback.answer("انتهت صلاحية التحدي", show_alert=True)
        return
    key = challenge["subject"]
    sn, si = subj_info(key if not key.startswith("branch_") else "all")
    qs = pick_questions(key)
    sent = await callback.message.answer(f"⚔️ *قبلت التحدي!*\n{si} *{sn}*\nتبدأ الآن! 🚀", parse_mode="Markdown")
    await state.update_data(subject=key, questions=qs, current=0, score=0, answers=[],
                            mode="challenge", challenge_id=cid, is_challenger=False,
                            quiz_msg_id=sent.message_id, gender="male")
    await asyncio.sleep(1.5)
    await state.set_state(QuizStates.in_quiz)
    await run_solo_q(callback.message.chat.id, state)
    await callback.answer()

@dp.callback_query(F.data == "leaderboard")
async def show_leaderboard(callback: CallbackQuery):
    await _show_leaderboard(callback, "xp")

@dp.callback_query(F.data.startswith("lb_tab:"))
async def leaderboard_tab(callback: CallbackQuery):
    tab = callback.data.split(":")[1]
    await _show_leaderboard(callback, tab)

async def _show_leaderboard(callback: CallbackQuery, tab: str):
    medals = ["🥇", "🥈", "🥉"]
    b = InlineKeyboardBuilder()
    if tab == "xp":
        top = db.get_leaderboard(10)
        title = "🏆 *المتصدرون بالنقاط*"
        b.button(text="🏆 النقاط ✓",     callback_data="lb_tab:xp")
        b.button(text="🔥 السلسلة اليومية", callback_data="lb_tab:streak")
    else:
        top = db.get_streak_leaderboard(10)
        title = "🔥 *المتصدرون بالسلسلة اليومية*"
        b.button(text="🏆 النقاط",           callback_data="lb_tab:xp")
        b.button(text="🔥 السلسلة اليومية ✓", callback_data="lb_tab:streak")
    b.button(text="← رجوع", callback_data="back_home")
    b.adjust(2, 1)

    if not top:
        await callback.message.edit_text("لا يوجد لاعبون بعد!", reply_markup=b.as_markup())
        return
    text = f"{title}\n━━━━━━━━━━━━━━━\n"
    for i, row in enumerate(top):
        medal = medals[i] if i < 3 else f"{i+1}."
        _, icon, label = get_title(row["xp"])
        if tab == "xp":
            text += f"{medal} *{row['name']}* {icon}\n    ⚡ {row['xp']} XP  🔥 {row['streak']} يوم\n\n"
        else:
            text += f"{medal} *{row['name']}* {icon}\n    🔥 {row['streak']} يوم متواصل  ⚡ {row['xp']} XP\n\n"
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=b.as_markup())
    await callback.answer()

@dp.callback_query(F.data == "my_stats")
async def show_my_stats(callback: CallbackQuery):
    uid = callback.from_user.id
    stats = db.get_user_stats(uid)
    subject_stats = db.get_subject_stats(uid)
    report = db.get_weekly_report(uid)
    _, icon, label = get_title(stats["xp"])
    cert = get_certificate(stats["total_games"])
    weekly_acc = int((report["correct"] / (report["games"] * 10)) * 100) if report["games"] > 0 else 0
    weekly_grade = ("🌟 ممتاز" if weekly_acc>=90 else "⭐ جيد جداً" if weekly_acc>=70 else
                    "👍 جيد" if weekly_acc>=50 else "📚 راجع أكثر" if report["games"]>0 else "—")

    text = (
        f"📊 *إحصائياتي*\n━━━━━━━━━━━━━━━\n"
        f"{icon} اللقب: *{label}*\n"
        f"⚡ XP: *{stats['xp']}*\n"
        f"🔥 أيام السلسلة المتواصلة: *{stats['streak']}* يوم\n"
        f"🎮 إجمالي الجولات: *{stats['total_games']}*\n"
    )
    if cert:
        text += f"🏅 الشهادة: *{cert}*\n"

    text += (
        f"\n📈 *تقرير هذا الأسبوع*\n"
        f"🎮 جولات: *{report['games']}*  ✅ إجابات: *{report['correct']}*\n"
        f"📊 دقة: *{weekly_acc}%*  ⚡ XP: *{report['xp']}*\n"
        f"التقييم: *{weekly_grade}*\n"
    )

    text += "\n📚 *تحليل الأداء بالمواد:*\n"
    for key, subj in SUBJECTS.items():
        s = subject_stats.get(key)
        if s and s["games"] > 0:
            acc = int((s["correct"] / (s["games"] * 10)) * 100)
            bar = "▓" * (acc // 10) + "░" * (10 - acc // 10)
            status = ("🟢" if acc>=80 else "🟡" if acc>=60 else "🔴")
            text += f"{status} {subj['icon']} {subj['name']}: `{bar}` {acc}%\n"
        else:
            text += f"⚪ {subj['icon']} {subj['name']}: لم تلعب\n"

    b = InlineKeyboardBuilder()
    b.button(text="🎯 توقع درجتي",      callback_data="grade_prediction_menu")
    b.button(text="🔁 مراجعة أخطائي",  callback_data="wrong_answers_menu")
    b.button(text="← رجوع",             callback_data="back_home")
    b.adjust(2, 1)
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=b.as_markup())
    await callback.answer()

@dp.callback_query(F.data == "buy_title")
async def buy_title(callback: CallbackQuery):
    b = InlineKeyboardBuilder()
    b.button(text="← رجوع", callback_data="back_home")
    await callback.message.edit_text(
        "🎖 *شراء لقب*\n━━━━━━━━━━━━━━━",
        parse_mode="Markdown", reply_markup=b.as_markup()
    )
    await callback.answer()

@dp.callback_query(F.data == "tip_of_day")
async def tip_of_day(callback: CallbackQuery):
    tips = [
        "📌 راجع أخطاءك بعد كل جولة — هي أفضل طريقة للتحسن!",
        "⏰ المراجعة المنتظمة يومياً أفضل من جلسة طويلة كل أسبوع.",
        "🎯 ركّز على المواد الأضعف عندك أكثر من القوية.",
        "💪 السلسلة اليومية تبني عادة المراجعة — لا تكسرها!",
        "🧠 اشرح المعلومة لنفسك بصوت عالٍ — هذا يثبّتها أكثر.",
        "📚 لا تراجع بالحفظ فقط — فهم السبب أهم من الحفظ.",
        "🔄 كرّر الأسئلة التي أخطأت فيها حتى تصير سهلة عليك.",
        "🌙 النوم الجيد قبل الامتحان أهم من السهر على المراجعة.",
        "✏️ اكتب الملاحظات بيدك — الكتابة تساعد على التذكر.",
        "🏆 الثبات يكسب — المثابرة أهم من الموهبة.",
    ]
    import hashlib
    today = date.today().isoformat()
    idx = int(hashlib.md5(today.encode()).hexdigest(), 16) % len(tips)
    tip = tips[idx]
    b = InlineKeyboardBuilder()
    b.button(text="← رجوع", callback_data="back_home")
    await callback.message.edit_text(
        f"💡 *نصيحة اليوم*\n━━━━━━━━━━━━━━━\n\n{tip}",
        parse_mode="Markdown", reply_markup=b.as_markup()
    )
    await callback.answer()

# ═══════════════════════════════════════════════
# مراجعة أخطائي
# ═══════════════════════════════════════════════
@dp.callback_query(F.data == "wrong_answers_menu")
async def wrong_answers_menu(callback: CallbackQuery):
    uid = callback.from_user.id
    wrong_subjects = db.get_wrong_subjects(uid)
    if not wrong_subjects:
        b = InlineKeyboardBuilder()
        b.button(text="← رجوع", callback_data="back_home")
        await callback.message.edit_text(
            "🔁 *مراجعة أخطائي*\n\n✅ ليس لديك أخطاء!\nاستمر بالمراجعة 💪",
            parse_mode="Markdown", reply_markup=b.as_markup()
        )
        await callback.answer()
        return

    b = InlineKeyboardBuilder()
    for ws in wrong_subjects:
        subj_key = ws["subject"]
        subj = SUBJECTS.get(subj_key, {})
        icon = subj.get("icon", "📚")
        name = subj.get("name", subj_key)
        b.button(
            text=f"{icon} {name} ({ws['cnt']} سؤال)",
            callback_data=f"wrong_subject:{subj_key}"
        )
    b.button(text="← رجوع", callback_data="back_home")
    b.adjust(2)
    await callback.message.edit_text(
        "🔁 *مراجعة أخطائي*\n\nاختر المادة:",
        parse_mode="Markdown", reply_markup=b.as_markup()
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("wrong_subject:"))
async def wrong_subject_quiz(callback: CallbackQuery, state: FSMContext):
    subj_key = callback.data.split(":")[1]
    uid = callback.from_user.id
    qs = db.get_wrong_questions(uid, subj_key)
    if not qs:
        await callback.answer("لا يوجد أخطاء في هذه المادة!", show_alert=True)
        return
    sent = await callback.message.answer(
        f"🔁 مراجعة أخطائك في {SUBJECTS.get(subj_key, {}).get('name', subj_key)}...",
        parse_mode="Markdown"
    )
    await state.update_data(
        subject=subj_key, questions=qs, current=0, score=0, answers=[],
        mode="wrong_review", quiz_msg_id=sent.message_id, gender="male"
    )
    await state.set_state(QuizStates.in_quiz)
    await callback.answer()
    await asyncio.sleep(1)
    await run_solo_q(callback.message.chat.id, state)

@dp.callback_query(F.data == "weekly_report")
async def weekly_report(callback: CallbackQuery):
    # إعادة التوجيه لإحصائياتي
    await show_my_stats(callback)

@dp.callback_query(F.data.startswith("review:"))
async def review_answers(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split(":")
    idx, key = int(parts[1]), parts[2]
    data = await state.get_data()
    answers = data.get("answers", [])
    if not answers or idx >= len(answers):
        await callback.answer("انتهت المراجعة ✅", show_alert=True)
        return
    a = answers[idx]
    labels = ["أ", "ب", "ج", "د"]
    opts = ""
    for i, opt in enumerate(a["options"]):
        if i == a["correct"] and i == a["chosen"]: opts += f"✅ {labels[i]}) {opt} ← إجابتك الصحيحة\n"
        elif i == a["correct"]: opts += f"✅ {labels[i]}) {opt} ← الإجابة الصحيحة\n"
        elif i == a["chosen"]:  opts += f"❌ {labels[i]}) {opt} ← إجابتك\n"
        else: opts += f"◻️ {labels[i]}) {opt}\n"
    status = "✅ صحيحة" if a["chosen"]==a["correct"] else ("⏰ انتهى الوقت" if a["chosen"]==-1 else "❌ خاطئة")
    b = InlineKeyboardBuilder()
    if idx > 0: b.button(text="→ السابق", callback_data=f"review:{idx-1}:{key}")
    if idx < len(answers)-1: b.button(text="التالي ←", callback_data=f"review:{idx+1}:{key}")
    b.button(text="← رجوع", callback_data="back_home")
    b.adjust(2, 1)
    await callback.message.edit_text(
        f"📋 *مراجعة {idx+1}/{len(answers)}*\n\n❓ {a['q']}\n\n{opts}\nالنتيجة: {status}",
        parse_mode="Markdown", reply_markup=b.as_markup())
    await callback.answer()

@dp.callback_query(F.data == "reminder_menu")
async def reminder_menu(callback: CallbackQuery):
    stats = db.get_user_stats(callback.from_user.id)
    status = "✅ مفعّل" if stats.get("reminders_on") else "❌ معطّل"
    b = InlineKeyboardBuilder()
    if stats.get("reminders_on"):
        b.button(text="🔕 إيقاف التذكير", callback_data="reminder_off")
    else:
        b.button(text="🔔 8 مساءً",  callback_data="reminder_on:20:00")
        b.button(text="🔔 10 مساءً", callback_data="reminder_on:22:00")
        b.button(text="🔔 7 صباحاً", callback_data="reminder_on:07:00")
    b.button(text="← رجوع", callback_data="back_home")
    b.adjust(1)
    await callback.message.edit_text(f"📅 *التذكير اليومي*\n\nالحالة: {status}",
                                     parse_mode="Markdown", reply_markup=b.as_markup())
    await callback.answer()

@dp.callback_query(F.data.startswith("reminder_on:"))
async def reminder_on(callback: CallbackQuery):
    parts = callback.data.split(":")
    time_str = f"{parts[1]}:{parts[2]}"
    db.set_reminder(callback.from_user.id, True, time_str)
    await callback.message.edit_text(f"✅ *تم تفعيل التذكير الساعة {time_str}* 📚",
                                     parse_mode="Markdown", reply_markup=back_home_kb())
    await callback.answer("✅ تم!")

@dp.callback_query(F.data == "reminder_off")
async def reminder_off(callback: CallbackQuery):
    db.set_reminder(callback.from_user.id, False)
    await callback.message.edit_text("🔕 *تم إيقاف التذكير*", parse_mode="Markdown", reply_markup=back_home_kb())
    await callback.answer()


@dp.callback_query(F.data == "settings")
async def settings_menu(callback: CallbackQuery):
    b = InlineKeyboardBuilder()
    b.button(text="💡 فكرة البوت",          callback_data="bot_idea")
    b.button(text="📢 قناة البوت",           url="https://t.me/AlMuthabir")
    b.button(text="✉️ للاقتراح والتواصل",   url="https://t.me/AlmuthabirBot")
    b.button(text="← رجوع",                 callback_data="back_home")
    b.adjust(1)
    await callback.message.edit_text(
        "⚙️ *الإعدادات*\n━━━━━━━━━━━━━━━",
        parse_mode="Markdown",
        reply_markup=b.as_markup()
    )
    await callback.answer()

@dp.callback_query(F.data == "bot_idea")
async def bot_idea(callback: CallbackQuery):
    b = InlineKeyboardBuilder()
    b.button(text="← رجوع", callback_data="settings")
    await callback.message.edit_text(
        "💡 *فكرة البوت*\n━━━━━━━━━━━━━━━\n\n_(قريباً)_",
        parse_mode="Markdown", reply_markup=b.as_markup()
    )
    await callback.answer()

async def send_daily_reminders():
    while True:
        now = datetime.now().strftime("%H:%M")
        for u in db.get_reminder_users():
            if u["reminder_time"] == now:
                try:
                    await bot.send_message(u["user_id"],
                        f"📚 *تذكير يومي!*\n\nلا تنسَ مراجعتك يا {u['name']}! 💪\nثابر اليوم، تفوّق غداً 🏆",
                        parse_mode="Markdown", reply_markup=main_menu_kb())
                except Exception:
                    pass
        await asyncio.sleep(60)

async def main():
    db.init_db()
    asyncio.create_task(send_daily_reminders())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
