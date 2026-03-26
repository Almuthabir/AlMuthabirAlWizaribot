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

# ─── نظام الألقاب ───────────────────────────────────────────
# format: key -> {name, icon, prefix, cost_xp, desc}
TITLES_SHOP = {
    "lion":    {"name": "الأسد",    "icon": "🦁", "prefix": "🦁 الأسد",    "cost": 500,  "desc": "قوة وثقة"},
    "flame":   {"name": "الشعلة",   "icon": "🔥", "prefix": "🔥 الشعلة",   "cost": 800,  "desc": "مضيء دائماً"},
    "thunder": {"name": "البرق",    "icon": "⚡", "prefix": "⚡ البرق",    "cost": 1200, "desc": "سرعة في الإجابة"},
    "king":    {"name": "الملك",    "icon": "👑", "prefix": "👑 الملك",    "cost": 1500, "desc": "تاج المتصدرين"},
    "genius":  {"name": "العبقري",  "icon": "🧠", "prefix": "🧠 العبقري",  "cost": 2000, "desc": "أعلى مستوى"},
    "star":    {"name": "النجم",    "icon": "⭐", "prefix": "⭐ النجم",    "cost": 3000, "desc": "نجم المجموعة"},
}

# ─── نظام الألقاب التلقائية (XP) ───────────────────────────
RANK_TITLES = [
    (0,    "🌱", "مبتدئ"),
    (100,  "📚", "متعلم"),
    (300,  "🎯", "متقدم"),
    (600,  "⭐", "محترف"),
    (1000, "🏆", "خبير"),
    (2000, "👑", "أسطورة"),
]

CERTIFICATES = {
    5:   "🥉 شهادة المثابر البرونزية",
    15:  "🥈 شهادة المثابر الفضية",
    30:  "🥇 شهادة المثابر الذهبية",
    50:  "💎 شهادة المثابر الماسية",
    100: "👑 شهادة أسطورة المثابر",
}

def get_rank(xp):
    t = RANK_TITLES[0]
    for threshold, icon, label in RANK_TITLES:
        if xp >= threshold:
            t = (threshold, icon, label)
    return t

def get_certificate(games):
    cert = None
    for g, label in CERTIFICATES.items():
        if games >= g:
            cert = label
    return cert

def get_display_name(user_id: int, full_name: str) -> str:
    stats = db.get_user_stats(user_id)
    title_key = stats.get("active_title")
    announce = stats.get("title_announce", 1)
    if title_key and announce and title_key in TITLES_SHOP:
        return f"{TITLES_SHOP[title_key]['prefix']} {full_name}"
    return full_name

def timer_bar(t, total=15):
    filled = int((t / total) * 10)
    char = "🟩" if t > 8 else ("🟨" if t > 4 else "🟥")
    return char * filled + "⬜" * (10 - filled) + f" {t}ث"

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
    return random.sample(pool, min(n, len(pool)))

# ─── توقعات الدرجات ─────────────────────────────────────────
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

# ─── FSM ────────────────────────────────────────────────────
class QuizStates(StatesGroup):
    choosing_subject = State()
    in_quiz          = State()
    study_mode       = State()
    challenge_wait   = State()

# ─── لوحات المفاتيح ─────────────────────────────────────────
def main_menu_kb():
    b = InlineKeyboardBuilder()
    b.button(text="📚 اختر المادة",       callback_data="subjects_menu")
    b.button(text="🎲 كل المواد",         callback_data="subject:all")
    b.button(text="📖 وضع الدراسة",       callback_data="study_mode_menu")
    b.button(text="⚔️ تحدي صديق",         callback_data="challenge_menu")
    b.button(text="👥 جولة مجموعة",       callback_data="group_menu")
    b.button(text="🏆 المتصدرون",         callback_data="leaderboard")
    b.button(text="📊 إحصائياتي",         callback_data="my_stats")
    b.button(text="🎯 توقعات درجاتي",     callback_data="grade_prediction_menu")
    b.button(text="🏅 متجر الألقاب",      callback_data="titles_shop")
    b.button(text="📅 تذكير يومي",        callback_data="reminder_menu")
    b.button(text="📈 تقريري الأسبوعي",  callback_data="weekly_report")
    b.adjust(2, 2, 2, 2, 1, 2)
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
    subjects = list(SUBJECTS.keys()) if branch_key == "all" else BRANCHES[branch_key]["subjects"]
    for key in subjects:
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

# ─── نص الترحيب ─────────────────────────────────────────────
def welcome_text(user_id, first_name):
    stats = db.get_user_stats(user_id)
    _, icon, label = get_rank(stats["xp"])
    cert = get_certificate(stats["total_games"])
    cert_line = f"🏅 {cert}\n" if cert else ""
    display = get_display_name(user_id, first_name)
    # XP للمستوى التالي
    next_xp = next((t for t, _, _ in RANK_TITLES if t > stats["xp"]), None)
    xp_line = f"⚡ XP: *{stats['xp']}*" + (f" /{next_xp}" if next_xp else " 🏆 MAX")
    return (
        f"👋 أهلاً {display}!\n\n"
        f"🎓 *المثابر الوزاري*\n"
        f"━━━━━━━━━━━━━━━\n"
        f"{cert_line}"
        f"{icon} لقبك: *{label}*\n"
        f"{xp_line}\n"
        f"🔥 السلسلة: *{stats['streak']}* يوم\n"
        f"🎮 جولات: *{stats['total_games']}*\n\n"
        f"اختر ما تريد 👇"
    )

# ─── /start ──────────────────────────────────────────────────
@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user = message.from_user
    db.register_user(user.id, user.full_name)

    # نقاط الدخول اليومي
    got_daily = db.add_daily_login_xp(user.id)

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

    daily_msg = "\n🎁 *+20 XP دخول يومي!*" if got_daily else ""
    await message.answer(
        welcome_text(user.id, user.first_name) + daily_msg,
        parse_mode="Markdown", reply_markup=main_menu_kb()
    )
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

# ─── قوائم المواد ───────────────────────────────────────────
@dp.callback_query(F.data == "subjects_menu")
async def subjects_menu(callback: CallbackQuery):
    await callback.message.edit_text(
        "📚 *اختر المادة*\n\nأولاً اختر فرعك الدراسي:",
        parse_mode="Markdown", reply_markup=branch_select_kb("pick_branch")
    )
    await callback.answer()

@dp.callback_query(F.data == "study_mode_menu")
async def study_mode_menu(callback: CallbackQuery):
    await callback.message.edit_text(
        "📖 *وضع الدراسة*\n\nاختر فرعك الدراسي:",
        parse_mode="Markdown", reply_markup=branch_select_kb("study_branch")
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("pick_branch:"))
async def pick_branch(callback: CallbackQuery):
    branch_key = callback.data.split(":")[1]
    branch_name = BRANCHES[branch_key]["name"] if branch_key != "all" else "كل الفروع"
    branch_icon = BRANCHES[branch_key]["icon"] if branch_key != "all" else "🌐"
    await callback.message.edit_text(
        f"{branch_icon} *{branch_name}*\n\nاختر المادة:",
        parse_mode="Markdown", reply_markup=subjects_for_branch_kb(branch_key, "subject")
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("study_branch:"))
async def study_branch(callback: CallbackQuery):
    branch_key = callback.data.split(":")[1]
    branch_name = BRANCHES[branch_key]["name"] if branch_key != "all" else "كل الفروع"
    branch_icon = BRANCHES[branch_key]["icon"] if branch_key != "all" else "🌐"
    await callback.message.edit_text(
        f"{branch_icon} *{branch_name}*\n\nاختر المادة:",
        parse_mode="Markdown", reply_markup=subjects_for_branch_kb(branch_key, "study")
    )
    await callback.answer()

# ═══ الجولة الفردية ══════════════════════════════════════════
@dp.callback_query(F.data.startswith("subject:"))
async def choose_subject(callback: CallbackQuery, state: FSMContext):
    key = callback.data.split(":")[1]
    if key.startswith("branch_"):
        branch_key = key.replace("branch_", "")
        if branch_key == "all":
            qs = pick_questions("all")
        else:
            branch_subjects = BRANCHES[branch_key]["subjects"]
            pool = [{**q, "_subject": k} for k in branch_subjects for q in QUESTION_BANK.get(k, [])]
            qs = random.sample(pool, min(10, len(pool)))
    else:
        qs = pick_questions(key)

    sn, si = subj_info(key if not key.startswith("branch_") else "all")
    await state.update_data(subject=key, questions=qs, current=0,
                            score=0, answers=[], mode="quiz", quiz_msg_id=None)
    sent = await callback.message.answer(
        f"{si} *{sn}*\n\nجاري تحضير الأسئلة... ⏳", parse_mode="Markdown"
    )
    await state.update_data(quiz_msg_id=sent.message_id)
    await state.set_state(QuizStates.in_quiz)
    await callback.answer()
    await asyncio.sleep(1)
    await run_solo_q(callback.message.chat.id, state)

async def build_q_text(q, cur, total, t, key):
    sn, si = subj_info(key if not key.startswith("branch_") else "all")
    labels = ["أ", "ب", "ج", "د"]
    opts = "\n".join(f"{labels[i]}) {opt}" for i, opt in enumerate(q["options"]))
    return (
        f"{si} *{sn}* | {cur+1}/{total}\n"
        f"`{progress_bar(cur, total)}`\n\n"
        f"❓ *{q['q']}*\n\n{opts}\n\n"
        f"⏱ {timer_bar(t)}"
    )

async def run_solo_q(chat_id, state: FSMContext):
    data = await state.get_data()
    qs, cur, key = data["questions"], data["current"], data["subject"]
    msg_id = data["quiz_msg_id"]
    if cur >= len(qs):
        await solo_finish(chat_id, state)
        return
    q = qs[cur]
    total = len(qs)
    await state.update_data(timer_running=True)
    text = await build_q_text(q, cur, total, 15, key)
    try:
        await bot.edit_message_text(chat_id=chat_id, message_id=msg_id,
                                    text=text, parse_mode="Markdown",
                                    reply_markup=options_kb(q["options"], cur))
    except TelegramBadRequest:
        pass
    # تحديث كل 3 ثواني بدلاً من كل ثانية لتقليل API calls
    for t in range(12, -1, -3):
        await asyncio.sleep(3)
        data = await state.get_data()
        if not data.get("timer_running"):
            return
        text = await build_q_text(q, cur, total, t, key)
        try:
            await bot.edit_message_text(chat_id=chat_id, message_id=msg_id,
                                        text=text, parse_mode="Markdown",
                                        reply_markup=options_kb(q["options"], cur))
        except TelegramBadRequest:
            pass
    data = await state.get_data()
    if not data.get("timer_running"):
        return
    await state.update_data(timer_running=False)
    answers = data.get("answers", [])
    answers.append({"q": q["q"], "options": q["options"], "correct": q["answer"], "chosen": -1})
    await state.update_data(current=cur+1, answers=answers)
    try:
        await bot.edit_message_text(
            chat_id=chat_id, message_id=msg_id,
            text=f"⏰ *انتهى الوقت!*\n\n❓ *{q['q']}*\n\n✅ الصحيحة: *{q['options'][q['answer']]}*\n\nالتالي...",
            parse_mode="Markdown"
        )
    except TelegramBadRequest:
        pass
    await asyncio.sleep(2)
    await run_solo_q(chat_id, state)

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
    answers.append({"q": q["q"], "options": q["options"], "correct": q["answer"], "chosen": chosen})
    await state.update_data(current=q_idx+1, score=score, answers=answers)
    sn, si = subj_info(key if not key.startswith("branch_") else "all")
    result = "✅ *صحيح!* +10 XP" if correct else f"❌ *خطأ!*\n✅ الصحيحة: *{q['options'][q['answer']]}*"
    total = len(qs)
    try:
        await bot.edit_message_text(
            chat_id=chat_id, message_id=msg_id,
            text=f"{si} *{sn}* | {q_idx+1}/{total}\n`{progress_bar(q_idx+1, total)}`\n\n❓ *{q['q']}*\n\n{result}\n\nالتالي...",
            parse_mode="Markdown"
        )
    except TelegramBadRequest:
        pass
    await callback.answer("✅ صحيح!" if correct else "❌ خطأ!")
    await asyncio.sleep(1.5)
    await run_solo_q(chat_id, state)

async def solo_finish(chat_id, state: FSMContext):
    data = await state.get_data()
    answers, key, mode = data["answers"], data["subject"], data.get("mode", "quiz")
    msg_id = data["quiz_msg_id"]
    score = sum(1 for a in answers if a["chosen"] == a["correct"])
    total = len(answers)
    pct = int((score/total)*100) if total else 0
    xp = score * 10 + 5  # +5 بونص إكمال الجولة
    grade = ("🌟 ممتاز" if pct>=90 else "⭐ جيد جداً" if pct>=70 else
             "👍 جيد" if pct>=50 else "📚 تحتاج مراجعة")
    bonus_xp = 0
    if mode == "quiz":
        actual = key if not key.startswith("branch_") and key != "all" else "mixed"
        bonus_xp = db.update_stats(chat_id, xp, score, total, actual) or 0

    # فحص ألقاب جديدة مكتسبة
    new_title = await check_new_titles(chat_id)

    stats = db.get_user_stats(chat_id)
    _, icon, label = get_rank(stats["xp"])
    cert = get_certificate(stats["total_games"])
    cert_line = f"🏅 حصلت على: *{cert}*\n" if cert and mode == "quiz" else ""
    bonus_line = f"🎁 بونص streak: *+{bonus_xp} XP*\n" if bonus_xp > 0 else ""
    new_title_line = f"🏅 لقب جديد متاح: *{new_title}* — من متجر الألقاب!\n" if new_title else ""

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
                  f"⚡ XP: *+{xp}*\n{bonus_line}━━━━━━━━━━━━━━━\n"
                  f"🏅 التقييم: *{grade}*\n{cert_line}{new_title_line}"
                  f"{icon} لقبك: {label}\n🔥 السلسلة: {stats['streak']} يوم\n"
                  f"⚡ إجمالي XP: {stats['xp']}"),
            parse_mode="Markdown", reply_markup=b.as_markup())
    except TelegramBadRequest:
        pass
    await state.clear()
    await state.set_state(QuizStates.choosing_subject)

async def check_new_titles(user_id: int) -> str | None:
    """يفحص إذا المستخدم أصبح يملك XP كافي لشراء لقب جديد"""
    stats = db.get_user_stats(user_id)
    earned = db.get_user_earned_titles(user_id)
    xp = stats["xp"]
    for key, t in TITLES_SHOP.items():
        if xp >= t["cost"] and key not in earned:
            return t["name"]
    return None

# ═══ وضع الدراسة (الوضع الهادئ) ══════════════════════════════
@dp.callback_query(F.data.startswith("study:"))
async def start_study(callback: CallbackQuery, state: FSMContext):
    key = callback.data.split(":")[1]
    if key.startswith("branch_"):
        branch_key = key.replace("branch_", "")
        branch_subjects = BRANCHES[branch_key]["subjects"] if branch_key != "all" else list(SUBJECTS.keys())
        pool = [{**q, "_subject": k} for k in branch_subjects for q in QUESTION_BANK.get(k, [])]
        qs = random.sample(pool, min(10, len(pool)))
    else:
        qs = pick_questions(key)

    # رسالة واحدة تُعدَّل بدلاً من رسائل متعددة
    sn, si = subj_info(key if not key.startswith("branch_") else "all")
    sent = await callback.message.edit_text(
        f"📖 *وضع الدراسة — {si} {sn}*\n\nجاري التحضير... ⏳",
        parse_mode="Markdown"
    )
    await state.update_data(subject=key, questions=qs, current=0,
                            score=0, answers=[], mode="study",
                            quiz_msg_id=sent.message_id)
    await state.set_state(QuizStates.study_mode)
    await callback.answer()
    await asyncio.sleep(0.5)
    await show_study_q(callback.message.chat.id, state)

async def show_study_q(chat_id: int, state: FSMContext):
    """يعرض السؤال في نفس الرسالة بدون إرسال رسائل جديدة"""
    data = await state.get_data()
    qs, cur, key = data["questions"], data["current"], data["subject"]
    msg_id = data["quiz_msg_id"]

    if cur >= len(qs):
        await solo_finish(chat_id, state)
        return

    q = qs[cur]
    total = len(qs)
    sn, si = subj_info(key if not key.startswith("branch_") else "all")
    labels = ["أ", "ب", "ج", "د"]

    b = InlineKeyboardBuilder()
    for i, opt in enumerate(q["options"]):
        b.button(text=f"{labels[i]}) {opt}", callback_data=f"study_ans:{cur}:{i}")
    b.adjust(1)

    text = (
        f"📖 *وضع الدراسة — {si} {sn}*\n"
        f"`{progress_bar(cur, total)}` {cur+1}/{total}\n\n"
        f"❓ *{q['q']}*"
    )
    try:
        await bot.edit_message_text(
            chat_id=chat_id, message_id=msg_id,
            text=text, parse_mode="Markdown", reply_markup=b.as_markup()
        )
    except TelegramBadRequest:
        pass

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
    msg_id = data["quiz_msg_id"]
    chat_id = callback.message.chat.id
    correct = chosen == q["answer"]
    if correct:
        score += 1
    answers.append({"q": q["q"], "options": q["options"], "correct": q["answer"], "chosen": chosen})
    await state.update_data(current=q_idx+1, score=score, answers=answers)

    # عرض النتيجة في نفس الرسالة مع زر التالي
    labels = ["أ", "ب", "ج", "د"]
    opts_text = ""
    for i, opt in enumerate(q["options"]):
        if i == q["answer"] and i == chosen:
            opts_text += f"✅ {labels[i]}) {opt} ← صحيح!\n"
        elif i == q["answer"]:
            opts_text += f"✅ {labels[i]}) {opt} ← الصحيحة\n"
        elif i == chosen:
            opts_text += f"❌ {labels[i]}) {opt} ← اخترت\n"
        else:
            opts_text += f"◻️ {labels[i]}) {opt}\n"

    feedback = "✅ *صحيح!*" if correct else "❌ *خطأ!*"
    b = InlineKeyboardBuilder()
    b.button(text="التالي ←", callback_data=f"study_next:{q_idx}")
    b.adjust(1)

    key = data["subject"]
    sn, si = subj_info(key if not key.startswith("branch_") else "all")
    total = len(qs)
    try:
        await bot.edit_message_text(
            chat_id=chat_id, message_id=msg_id,
            text=(f"📖 *{si} {sn}* | {q_idx+1}/{total}\n\n"
                  f"❓ *{q['q']}*\n\n{opts_text}\n{feedback}"),
            parse_mode="Markdown", reply_markup=b.as_markup()
        )
    except TelegramBadRequest:
        pass
    await callback.answer("✅" if correct else "❌")

@dp.callback_query(F.data.startswith("study_next:"))
async def study_next(callback: CallbackQuery, state: FSMContext):
    await show_study_q(callback.message.chat.id, state)
    await callback.answer()

# ═══ توقعات الدرجات ══════════════════════════════════════════
@dp.callback_query(F.data == "grade_prediction_menu")
async def grade_prediction_menu(callback: CallbackQuery):
    await callback.message.edit_text(
        "🎯 *توقعات درجاتي بالوزاري*\n\nاختر فرعك لعرض التوقعات:",
        parse_mode="Markdown", reply_markup=branch_select_kb("grade_branch")
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

# ═══ متجر الألقاب ════════════════════════════════════════════
@dp.callback_query(F.data == "titles_shop")
async def titles_shop(callback: CallbackQuery):
    uid = callback.from_user.id
    stats = db.get_user_stats(uid)
    earned = db.get_user_earned_titles(uid)
    xp = stats["xp"]
    active = stats.get("active_title")

    text = f"🏅 *متجر الألقاب*\n⚡ رصيدك: *{xp} XP*\n━━━━━━━━━━━━━━━\n\n"
    b = InlineKeyboardBuilder()

    for key, t in TITLES_SHOP.items():
        if key in earned:
            status = "✅ مفعّل" if key == active else "✔️ مملوك"
            text += f"{t['icon']} *{t['name']}* — {status}\n_{t['desc']}_\n\n"
            if key != active:
                b.button(text=f"🔄 تفعيل {t['icon']} {t['name']}", callback_data=f"title_activate:{key}")
            else:
                b.button(text=f"🔕 إلغاء اللقب", callback_data="title_deactivate")
        else:
            can = "🛒" if xp >= t["cost"] else "🔒"
            text += f"{t['icon']} *{t['name']}* — {t['cost']} XP {can}\n_{t['desc']}_\n\n"
            if xp >= t["cost"]:
                b.button(text=f"{can} اشتري {t['icon']} {t['name']}", callback_data=f"title_buy:{key}")

    b.button(text="🔔 إعدادات النداء", callback_data="title_announce_settings")
    b.button(text="← رجوع", callback_data="back_home")
    b.adjust(1)
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=b.as_markup())
    await callback.answer()

@dp.callback_query(F.data.startswith("title_buy:"))
async def title_buy(callback: CallbackQuery):
    uid = callback.from_user.id
    key = callback.data.split(":")[1]
    t = TITLES_SHOP.get(key)
    if not t:
        await callback.answer("❌ لقب غير موجود")
        return
    stats = db.get_user_stats(uid)
    if stats["xp"] < t["cost"]:
        await callback.answer(f"❌ تحتاج {t['cost']} XP", show_alert=True)
        return
    earned = db.get_user_earned_titles(uid)
    if key in earned:
        await callback.answer("✅ تملك هذا اللقب بالفعل")
        return
    # خصم الـ XP وإضافة اللقب
    from database import get_conn
    conn = get_conn()
    conn.execute("UPDATE users SET xp=xp-? WHERE user_id=?", (t["cost"], uid))
    conn.commit(); conn.close()
    db.earn_title(uid, key)
    db.set_active_title(uid, key)
    await callback.answer(f"🎉 حصلت على لقب {t['icon']} {t['name']}!", show_alert=True)
    await titles_shop(callback)

@dp.callback_query(F.data.startswith("title_activate:"))
async def title_activate(callback: CallbackQuery):
    uid = callback.from_user.id
    key = callback.data.split(":")[1]
    earned = db.get_user_earned_titles(uid)
    if key not in earned:
        await callback.answer("❌ لا تملك هذا اللقب")
        return
    db.set_active_title(uid, key)
    t = TITLES_SHOP[key]
    await callback.answer(f"✅ تم تفعيل {t['icon']} {t['name']}!")
    await titles_shop(callback)

@dp.callback_query(F.data == "title_deactivate")
async def title_deactivate(callback: CallbackQuery):
    db.set_active_title(callback.from_user.id, None)
    await callback.answer("✅ تم إيقاف اللقب، ستظهر باسمك الحقيقي")
    await titles_shop(callback)

@dp.callback_query(F.data == "title_announce_settings")
async def title_announce_settings(callback: CallbackQuery):
    uid = callback.from_user.id
    stats = db.get_user_stats(uid)
    current = stats.get("title_announce", 1)
    b = InlineKeyboardBuilder()
    if current:
        b.button(text="🔕 إيقاف النداء باللقب", callback_data="title_announce_off")
    else:
        b.button(text="🔔 تفعيل النداء باللقب", callback_data="title_announce_on")
    b.button(text="← رجوع", callback_data="titles_shop")
    b.adjust(1)
    status = "مفعّل ✅" if current else "معطّل 🔕"
    await callback.message.edit_text(
        f"🔔 *إعدادات النداء باللقب*\n\nالحالة: {status}\n\n"
        f"عند التفعيل، يناديك البوت باسم لقبك في كل مكان\n"
        f"_(مثال: 👑 الملك محمد أجاب صح!)_",
        parse_mode="Markdown", reply_markup=b.as_markup()
    )
    await callback.answer()

@dp.callback_query(F.data == "title_announce_on")
async def title_announce_on(callback: CallbackQuery):
    db.set_title_announce(callback.from_user.id, True)
    await callback.answer("✅ تم تفعيل النداء باللقب!")
    await title_announce_settings(callback)

@dp.callback_query(F.data == "title_announce_off")
async def title_announce_off(callback: CallbackQuery):
    db.set_title_announce(callback.from_user.id, False)
    await callback.answer("🔕 تم إيقاف النداء باللقب")
    await title_announce_settings(callback)

# ═══ جولة المجموعة ═══════════════════════════════════════════
group_sessions = {}

@dp.callback_query(F.data == "group_menu")
async def group_menu(callback: CallbackQuery):
    await callback.message.edit_text(
        "👥 *جولة المجموعة*\n\nاختر فرعك أولاً:",
        parse_mode="Markdown", reply_markup=branch_select_kb("group_branch")
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("group_branch:"))
async def group_branch(callback: CallbackQuery):
    branch_key = callback.data.split(":")[1]
    branch_name = BRANCHES[branch_key]["name"] if branch_key != "all" else "كل الفروع"
    await callback.message.edit_text(
        f"👥 *جولة المجموعة — {branch_name}*\n\nاختر المادة:",
        parse_mode="Markdown",
        reply_markup=subjects_for_branch_kb(branch_key, "group_create")
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("group_create:"))
async def group_create(callback: CallbackQuery):
    key = callback.data.split(":")[1]
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
    b.button(text="🚀 ابدأ الجولة الآن", callback_data=f"start_here:{sid}")
    b.button(text="← رجوع", callback_data="group_menu")
    b.adjust(1)

    await callback.message.edit_text(
        f"✅ *تم إنشاء الجولة!*\n\n{si} *{sn}*\n🔑 الكود: `{sid}`\n\n"
        f"*شارك هذا الأمر بمجموعتك:*\n`/startquiz {sid}`\n\n"
        f"*أو الرابط المباشر:*\n{share_link}\n\n"
        f"👥 اللاعبون: *{len(group_sessions[sid]['players'])}*\n\n"
        f"_اضغط 'ابدأ' عندما ينضم أصدقاؤك_",
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
        await message.answer("❌ كود الجولة غير صحيح! تأكد من الكود وأعد المحاولة.")
        return
    session = group_sessions[sid]
    if session["owner_id"] != message.from_user.id:
        await message.answer("❌ فقط صاحب الجولة يقدر يبدأها!")
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
        await callback.answer("❌ فقط صاحب الجولة يبدأها!", show_alert=True)
        return
    if len(session["players"]) < 1:
        await callback.answer("❌ لا يوجد لاعبون بعد!", show_alert=True)
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
    session["players"][user.id] = {"name": user.full_name, "score": 0}
    sn, si = subj_info(session["subject"] if not session["subject"].startswith("branch_") else "all")
    if isinstance(source, Message):
        await source.answer(
            f"✅ *انضممت للجولة!*\n{si} *{sn}*\nاللاعبون: {len(session['players'])}\nانتظر البداية...",
            parse_mode="Markdown"
        )

async def launch_group_quiz(chat_id: int, sid: str):
    session = group_sessions[sid]
    session["status"] = "active"
    qs = session["questions"]
    key = session["subject"]
    sn, si = subj_info(key if not key.startswith("branch_") else "all")
    total = len(qs)

    await bot.send_message(chat_id,
        f"🚀 *جولة المثابر الوزاري بدأت!*\n{si} *{sn}* — {total} أسئلة\n⏱ 15 ثانية لكل سؤال\n\nاستعدوا... 3️⃣2️⃣1️⃣",
        parse_mode="Markdown")
    await asyncio.sleep(3)

    for q_idx, q in enumerate(qs):
        session["answered"] = {}
        session["current"] = q_idx
        labels = ["أ", "ب", "ج", "د"]

        def build_group_q(t):
            opts = "\n".join(f"{labels[i]}) {opt}" for i, opt in enumerate(q["options"]))
            names = [get_display_name(uid, p["name"]) for uid, p in session["players"].items() if uid in session["answered"]]
            ans_line = f"\n\n✅ أجاب: {', '.join(names)} ({len(names)})" if names else ""
            return (f"{si} *{sn}* | {q_idx+1}/{total}\n`{progress_bar(q_idx, total)}`\n\n"
                    f"❓ *{q['q']}*\n\n{opts}\n\n⏱ {timer_bar(t)}{ans_line}")

        def answer_kb():
            b = InlineKeyboardBuilder()
            for i, opt in enumerate(q["options"]):
                b.button(text=f"{labels[i]}) {opt}", callback_data=f"gq:{sid}:{q_idx}:{i}")
            b.adjust(1)
            return b.as_markup()

        sent = await bot.send_message(chat_id, build_group_q(15), parse_mode="Markdown", reply_markup=answer_kb())
        session["msg_id"] = sent.message_id

        # تحديث كل 3 ثواني لتقليل API calls
        for t in range(12, -1, -3):
            await asyncio.sleep(3)
            try:
                await bot.edit_message_text(chat_id=chat_id, message_id=sent.message_id,
                    text=build_group_q(t), parse_mode="Markdown",
                    reply_markup=answer_kb() if t > 0 else None)
            except TelegramBadRequest:
                pass

        correct_ans = q["answer"]
        correct_label = f"{labels[correct_ans]}) {q['options'][correct_ans]}"
        correct_p = [get_display_name(uid, p["name"]) for uid, p in session["players"].items() if session["answered"].get(uid) == correct_ans]
        wrong_p   = [get_display_name(uid, p["name"]) for uid, p in session["players"].items() if uid in session["answered"] and session["answered"][uid] != correct_ans]
        no_ans_p  = [get_display_name(uid, p["name"]) for uid, p in session["players"].items() if uid not in session["answered"]]

        res = f"📊 *نتيجة السؤال {q_idx+1}*\n\n❓ *{q['q']}*\n✅ الصحيحة: *{correct_label}*\n\n"
        if correct_p: res += f"✅ أجاب صح ({len(correct_p)}): {', '.join(correct_p)}\n"
        if wrong_p:   res += f"❌ أخطأ ({len(wrong_p)}): {', '.join(wrong_p)}\n"
        if no_ans_p:  res += f"⏰ لم يجب ({len(no_ans_p)}): {', '.join(no_ans_p)}\n"

        await bot.send_message(chat_id, res, parse_mode="Markdown")
        await asyncio.sleep(3)

    sorted_p = sorted(session["players"].items(), key=lambda x: x[1]["score"], reverse=True)
    medals = ["🥇", "🥈", "🥉"]
    final = f"🏆 *النتائج النهائية*\n{si} *{sn}*\n━━━━━━━━━━━━━━━\n"
    for i, (uid, p) in enumerate(sorted_p):
        medal = medals[i] if i < 3 else f"{i+1}."
        pct = int((p["score"] / total) * 100)
        dname = get_display_name(uid, p["name"])
        final += f"{medal} *{dname}* — {p['score']}/{total} ({pct}%)\n"
    final += "━━━━━━━━━━━━━━━\n🎉 تهانينا للمتصدرين!"

    b = InlineKeyboardBuilder()
    b.button(text="🔄 جولة جديدة", callback_data="group_menu")
    await bot.send_message(chat_id, final, parse_mode="Markdown", reply_markup=b.as_markup())

    for uid, p in session["players"].items():
        if p["score"] > 0:
            xp_earned = p["score"] * 10 + 5  # بونص إكمال
            if i == 0:  # الأول يأخذ بونص إضافي
                xp_earned += 30
            db.update_stats(uid, xp_earned, p["score"], total, key if not key.startswith("branch_") else "mixed")

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

    # إضافة اللاعب تلقائياً إن لم يكن مسجلاً
    if user.id not in session["players"]:
        if len(session["players"]) >= MAX_PLAYERS:
            await callback.answer("❌ الجولة ممتلئة!", show_alert=True)
            return
        session["players"][user.id] = {"name": user.full_name, "score": 0}

    if user.id in session["answered"]:
        await callback.answer("✋ أجبت بالفعل!")
        return

    if session.get("current") != q_idx:
        await callback.answer("⚡ تأخرت!")
        return

    session["answered"][user.id] = chosen
    q = session["questions"][q_idx]
    correct = chosen == q["answer"]
    if correct:
        session["players"][user.id]["score"] += 1

    labels = ["أ", "ب", "ج", "د"]
    dname = get_display_name(user.id, user.full_name)
    await callback.answer(f"✅ صحيح! +1 — {dname}" if correct else f"❌ خطأ! الصحيحة: {labels[q['answer']]}")

    # تحديث الرسالة بقائمة من أجاب
    names = [get_display_name(uid, p["name"]) for uid, p in session["players"].items() if uid in session["answered"]]
    sn, si = subj_info(session["subject"] if not session["subject"].startswith("branch_") else "all")
    total = len(session["questions"])
    opts = "\n".join(f"{labels[i]}) {opt}" for i, opt in enumerate(q["options"]))

    try:
        await callback.message.edit_text(
            f"{si} *{sn}* | {q_idx+1}/{total}\n`{progress_bar(q_idx, total)}`\n\n"
            f"❓ *{q['q']}*\n\n{opts}\n\n"
            f"✅ أجاب: {', '.join(names)} ({len(names)} لاعب)",
            parse_mode="Markdown", reply_markup=callback.message.reply_markup
        )
    except TelegramBadRequest:
        pass

# ═══ التحدي ══════════════════════════════════════════════════
@dp.callback_query(F.data == "challenge_menu")
async def challenge_menu(callback: CallbackQuery):
    await callback.message.edit_text("⚔️ *تحدي صديق*\n\nاختر الفرع:",
                                     parse_mode="Markdown", reply_markup=branch_select_kb("challenge_branch"))
    await callback.answer()

@dp.callback_query(F.data.startswith("challenge_branch:"))
async def challenge_branch(callback: CallbackQuery):
    branch_key = callback.data.split(":")[1]
    await callback.message.edit_text("⚔️ اختر المادة:", parse_mode="Markdown",
                                     reply_markup=subjects_for_branch_kb(branch_key, "challenge_subject"))
    await callback.answer()

@dp.callback_query(F.data.startswith("challenge_subject:"))
async def challenge_select(callback: CallbackQuery, state: FSMContext):
    key = callback.data.split(":")[1]
    await state.update_data(challenge_subject=key)
    await callback.message.edit_text("⚔️ أرسل اسم صديقك في البوت:", parse_mode="Markdown", reply_markup=back_home_kb())
    await state.set_state(QuizStates.challenge_wait)
    await callback.answer()

@dp.message(QuizStates.challenge_wait)
async def challenge_search(message: Message, state: FSMContext):
    results = db.get_user_by_username_search(message.text.strip())
    if not results:
        await message.answer("❌ ما وجدنا هذا المستخدم", reply_markup=back_home_kb())
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
    cid = db.create_challenge(callback.from_user.id, opp, key)
    sn, si = subj_info(key if not key.startswith("branch_") else "all")
    challenger_name = get_display_name(callback.from_user.id, callback.from_user.full_name)
    try:
        b = InlineKeyboardBuilder()
        b.button(text="✅ قبول", callback_data=f"accept_challenge:{cid}")
        b.button(text="❌ رفض",  callback_data="back_home")
        b.adjust(2)
        await bot.send_message(opp, f"⚔️ *تحدي من {challenger_name}!*\n{si} *{sn}*\nهل تقبل؟",
                                parse_mode="Markdown", reply_markup=b.as_markup())
    except Exception:
        pass
    qs = pick_questions(key)
    sent = await callback.message.answer(f"✅ *تم إرسال التحدي!*\n{si} *{sn}*\nجولتك تبدأ الآن...", parse_mode="Markdown")
    await state.update_data(subject=key, questions=qs, current=0, score=0, answers=[],
                            mode="challenge", challenge_id=cid, is_challenger=True, quiz_msg_id=sent.message_id)
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
                            mode="challenge", challenge_id=cid, is_challenger=False, quiz_msg_id=sent.message_id)
    await asyncio.sleep(1.5)
    await state.set_state(QuizStates.in_quiz)
    await run_solo_q(callback.message.chat.id, state)
    await callback.answer()

# ═══ لوحة المتصدرين ══════════════════════════════════════════
@dp.callback_query(F.data == "leaderboard")
async def show_leaderboard(callback: CallbackQuery):
    top = db.get_leaderboard(10)
    medals = ["🥇", "🥈", "🥉"]
    if not top:
        await callback.message.edit_text("لا يوجد لاعبون بعد!", reply_markup=back_home_kb())
        return
    text = "🏆 *المتصدرون*\n━━━━━━━━━━━━━━━\n"
    for i, row in enumerate(top):
        medal = medals[i] if i < 3 else f"{i+1}."
        _, icon, label = get_rank(row["xp"])
        dname = get_display_name(0, row["name"])  # نعرض اللقب من الداتا مباشرة
        # عرض اللقب المشترى إن وُجد
        title_key = row.get("active_title")
        prefix = TITLES_SHOP[title_key]["prefix"] + " " if title_key and title_key in TITLES_SHOP else ""
        text += f"{medal} *{prefix}{row['name']}* {icon}\n    ⚡ {row['xp']} XP  🔥 {row['streak']} يوم\n\n"
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=back_home_kb())
    await callback.answer()

# ═══ الإحصائيات ══════════════════════════════════════════════
@dp.callback_query(F.data == "my_stats")
async def show_my_stats(callback: CallbackQuery):
    uid = callback.from_user.id
    stats = db.get_user_stats(uid)
    subject_stats = db.get_subject_stats(uid)
    earned_titles = db.get_user_earned_titles(uid)
    _, icon, label = get_rank(stats["xp"])
    cert = get_certificate(stats["total_games"])
    active_title = stats.get("active_title")
    title_display = f"🏅 اللقب المفعّل: *{TITLES_SHOP[active_title]['icon']} {TITLES_SHOP[active_title]['name']}*\n" if active_title and active_title in TITLES_SHOP else ""
    titles_count = f"🎖️ ألقاب مكتسبة: *{len(earned_titles)}*\n" if earned_titles else ""

    text = (f"📊 *إحصائياتي*\n━━━━━━━━━━━━━━━\n{icon} الرتبة: *{label}*\n"
            f"⚡ XP: *{stats['xp']}*\n🔥 السلسلة: *{stats['streak']}* يوم\n"
            f"🎮 جولات: *{stats['total_games']}*\n")
    if cert:
        text += f"🏅 الشهادة: *{cert}*\n"
    text += title_display + titles_count
    text += "\n📚 *أداء المواد:*\n"
    for key, subj in SUBJECTS.items():
        s = subject_stats.get(key)
        if s and s["games"] > 0:
            acc = int((s["correct"] / (s["games"] * 10)) * 100)
            bar = "▓" * (acc // 10) + "░" * (10 - acc // 10)
            text += f"{subj['icon']} {subj['name']}: `{bar}` {acc}%\n"
        else:
            text += f"{subj['icon']} {subj['name']}: لم تلعب\n"

    b = InlineKeyboardBuilder()
    b.button(text="🎯 توقعات درجاتي", callback_data="grade_prediction_menu")
    b.button(text="← رجوع",           callback_data="back_home")
    b.adjust(1)
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=b.as_markup())
    await callback.answer()

# ═══ مراجعة الإجابات ══════════════════════════════════════════
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

# ═══ التقرير الأسبوعي ══════════════════════════════════════════
@dp.callback_query(F.data == "weekly_report")
async def weekly_report(callback: CallbackQuery):
    report = db.get_weekly_report(callback.from_user.id)
    acc = int((report["correct"] / (report["games"] * 10)) * 100) if report["games"] > 0 else 0
    grade = ("🌟 ممتاز" if acc>=90 else "⭐ جيد جداً" if acc>=70 else
             "👍 جيد" if acc>=50 else "📚 تحتاج مراجعة" if report["games"] > 0 else "لم تلعب هذا الأسبوع!")
    await callback.message.edit_text(
        f"📈 *تقريري الأسبوعي*\n━━━━━━━━━━━━━━━\n"
        f"🎮 جولات: *{report['games']}*\n✅ صحيح: *{report['correct']}*\n"
        f"📊 دقة: *{acc}%*\n⚡ XP: *{report['xp']}*\n\nالتقييم: *{grade}*",
        parse_mode="Markdown", reply_markup=back_home_kb())
    await callback.answer()

# ═══ التذكير اليومي ══════════════════════════════════════════
@dp.callback_query(F.data == "reminder_menu")
async def reminder_menu(callback: CallbackQuery):
    stats = db.get_user_stats(callback.from_user.id)
    current_time = stats.get("reminder_time", "20:00")
    status = f"✅ مفعّل — الساعة {current_time}" if stats.get("reminders_on") else "❌ معطّل"
    b = InlineKeyboardBuilder()
    if stats.get("reminders_on"):
        b.button(text="🔕 إيقاف التذكير", callback_data="reminder_off")
        b.button(text="🔄 تغيير الوقت",   callback_data="reminder_change")
    else:
        # مرتبة من الصبح للمساء
        b.button(text="🌅 7 صباحاً",  callback_data="reminder_on:07:00")
        b.button(text="☀️ 2 ظهراً",   callback_data="reminder_on:14:00")
        b.button(text="🌙 8 مساءً",   callback_data="reminder_on:20:00")
        b.button(text="🌙 10 مساءً",  callback_data="reminder_on:22:00")
    b.button(text="← رجوع", callback_data="back_home")
    b.adjust(1)
    await callback.message.edit_text(
        f"📅 *التذكير اليومي*\n\nالحالة: {status}\n\n"
        f"_سيرسل لك البوت تذكيراً للمراجعة في الوقت الذي تختاره_",
        parse_mode="Markdown", reply_markup=b.as_markup()
    )
    await callback.answer()

@dp.callback_query(F.data == "reminder_change")
async def reminder_change(callback: CallbackQuery):
    b = InlineKeyboardBuilder()
    b.button(text="🌅 7 صباحاً",  callback_data="reminder_on:07:00")
    b.button(text="☀️ 2 ظهراً",   callback_data="reminder_on:14:00")
    b.button(text="🌙 8 مساءً",   callback_data="reminder_on:20:00")
    b.button(text="🌙 10 مساءً",  callback_data="reminder_on:22:00")
    b.button(text="← رجوع", callback_data="reminder_menu")
    b.adjust(1)
    await callback.message.edit_text("اختر الوقت الجديد:", reply_markup=b.as_markup())
    await callback.answer()

@dp.callback_query(F.data.startswith("reminder_on:"))
async def reminder_on(callback: CallbackQuery):
    parts = callback.data.split(":")
    time_str = f"{parts[1]}:{parts[2]}"
    db.set_reminder(callback.from_user.id, True, time_str)
    labels = {"07:00": "7 صباحاً 🌅", "14:00": "2 ظهراً ☀️", "20:00": "8 مساءً 🌙", "22:00": "10 مساءً 🌙"}
    label = labels.get(time_str, time_str)
    await callback.message.edit_text(
        f"✅ *تم تفعيل التذكير الساعة {label}* 📚\n\nسيصلك تذكير يومي للمراجعة! 💪",
        parse_mode="Markdown", reply_markup=back_home_kb()
    )
    await callback.answer("✅ تم!")

@dp.callback_query(F.data == "reminder_off")
async def reminder_off(callback: CallbackQuery):
    db.set_reminder(callback.from_user.id, False)
    await callback.message.edit_text("🔕 *تم إيقاف التذكير*", parse_mode="Markdown", reply_markup=back_home_kb())
    await callback.answer()

# ═══ المهام الخلفية ══════════════════════════════════════════
async def send_daily_reminders():
    while True:
        now = datetime.now().strftime("%H:%M")
        for u in db.get_reminder_users():
            if u["reminder_time"] == now:
                title_key = u.get("active_title")
                announce = u.get("title_announce", 1)
                prefix = ""
                if title_key and announce and title_key in TITLES_SHOP:
                    prefix = TITLES_SHOP[title_key]["prefix"] + " "
                try:
                    await bot.send_message(u["user_id"],
                        f"📚 *تذكير يومي!*\n\nلا تنسَ مراجعتك يا {prefix}{u['name']}! 💪\nثابر اليوم، تفوّق غداً 🏆",
                        parse_mode="Markdown", reply_markup=main_menu_kb())
                except Exception:
                    pass
        await asyncio.sleep(60)

async def daily_cleanup():
    while True:
        await asyncio.sleep(3600)  # كل ساعة
        db.cleanup_old_challenges()
        db.cleanup_old_sessions()

async def main():
    db.init_db()
    asyncio.create_task(send_daily_reminders())
    asyncio.create_task(daily_cleanup())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
