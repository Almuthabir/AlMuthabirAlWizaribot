
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
from aiogram.exceptions import TelegramBadRequest, AiogramError

import config
import database as db
from questions import QUESTION_BANK, SUBJECTS, BRANCHES

logging.basicConfig(level=logging.INFO, format=\'%(asctime)s - %(name)s - %(levelname)s - %(message)s\')
logger = logging.getLogger(__name__)

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

def get_rank(xp: int) -> tuple[int, str, str]:
    """Determines the user\'s rank based on their XP."""
    t = RANK_TITLES[0]
    for threshold, icon, label in RANK_TITLES:
        if xp >= threshold:
            t = (threshold, icon, label)
    return t

def get_certificate(games: int) -> str | None:
    """Determines the user\'s certificate based on the number of games played."""
    cert = None
    for g, label in CERTIFICATES.items():
        if games >= g:
            cert = label
    return cert

def get_display_name(user_id: int, full_name: str) -> str:
    """Returns the user\'s display name, potentially with an active title prefix."""
    stats = db.get_user_stats(user_id)
    title_key = stats.get("active_title")
    announce = stats.get("title_announce", 1)
    if title_key and announce and title_key in TITLES_SHOP:
        return f"{TITLES_SHOP[title_key][\'prefix\']} {full_name}"
    return full_name

def timer_bar(t: int, total: int = 15) -> str:
    """Generates a visual timer bar."""
    filled = int((t / total) * 10)
    char = "🟩" if t > 8 else ("🟨" if t > 4 else "🟥")
    return char * filled + "⬜" * (10 - filled) + f" {t}ث"

def progress_bar(cur: int, total: int) -> str:
    """Generates a visual progress bar."""
    f = int((cur / total) * 10)
    return "▓" * f + "░" * (10 - f)

def subj_info(key: str) -> tuple[str, str]:
    """Returns the name and icon for a given subject key."""
    if key == "all":
        return "كل المواد", "🎲"
    s = SUBJECTS.get(key, {})
    return s.get("name", ""), s.get("icon", "📚")

def pick_questions(key: str, n: int = 10) -> list[dict]:
    """Picks a specified number of random questions for a given subject or all subjects."""
    if key == "all":
        pool = [{**q, "_subject": k} for k, qs in QUESTION_BANK.items() for q in qs]
    else:
        pool = QUESTION_BANK.get(key, [])
    return random.sample(pool, min(n, len(pool)))

# ─── توقعات الدرجات ─────────────────────────────────────────
def calc_grade_prediction(subject_stats: dict, branch: str = None) -> str:
    """Calculates and formats the predicted grades for a user."""
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
                f"{subj[\'icon\']} *{subj[\'name\']}*\n"
                f"  `{bar}` {int(pct)}%\n"
                f"  📝 التوقع: *{predicted}/{max_grade}* — {status}\n"
            )
            total_weighted += predicted
            total_max += max_grade
        else:
            lines.append(f"{subj[\'icon\']} *{subj[\'name\']}*\n  ⚪ لم تراجع بعد\n")
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
    """States for the quiz FSM."""
    choosing_subject = State()
    in_quiz          = State()
    study_mode       = State()
    challenge_wait   = State()

# ─── لوحات المفاتيح ─────────────────────────────────────────
def main_menu_kb() -> InlineKeyboardBuilder:
    """Generates the main menu keyboard."""
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

def branch_select_kb(prefix: str = "branch") -> InlineKeyboardBuilder:
    """Generates a keyboard for selecting a branch."""
    b = InlineKeyboardBuilder()
    for key, branch in BRANCHES.items():
        b.button(text=f"{branch[\'icon\']} {branch[\'name\']}", callback_data=f"{prefix}:{key}")
    b.button(text="🌐 كل الفروع", callback_data=f"{prefix}:all")
    b.button(text="← رجوع", callback_data="back_home")
    b.adjust(1)
    return b.as_markup()

def subjects_for_branch_kb(branch_key: str, prefix: str = "subject") -> InlineKeyboardBuilder:
    """Generates a keyboard for selecting subjects within a branch."""
    b = InlineKeyboardBuilder()
    subjects = list(SUBJECTS.keys()) if branch_key == "all" else BRANCHES[branch_key]["subjects"]
    for key in subjects:
        subj = SUBJECTS[key]
        b.button(text=f"{subj[\'icon\']} {subj[\'name\']}", callback_data=f"{prefix}:{key}")
    b.button(text="🎲 كل مواد الفرع", callback_data=f"{prefix}:branch_{branch_key}")
    b.button(text="← رجوع", callback_data="subjects_menu")
    b.adjust(2)
    return b.as_markup()

def back_home_kb() -> InlineKeyboardBuilder:
    """Generates a \'Back to Home\' keyboard button."""
    b = InlineKeyboardBuilder()
    b.button(text="← القائمة الرئيسية", callback_data="back_home")
    return b.as_markup()

def options_kb(options: list[str], q_index: int, prefix: str = "answer") -> InlineKeyboardBuilder:
    """Generates a keyboard with answer options for a question."""
    b = InlineKeyboardBuilder()
    labels = ["أ", "ب", "ج", "د"]
    for i, opt in enumerate(options):
        b.button(text=f"{labels[i]}) {opt}", callback_data=f"{prefix}:{q_index}:{i}")
    b.adjust(1)
    return b.as_markup()

# ─── نص الترحيب ─────────────────────────────────────────────
def welcome_text(user_id: int, first_name: str) -> str:
    """Generates the welcome message for a user."""
    stats = db.get_user_stats(user_id)
    _, icon, label = get_rank(stats["xp"])
    cert = get_certificate(stats["total_games"])
    cert_line = f"🏅 {cert}\n" if cert else ""
    display = get_display_name(user_id, first_name)
    # XP للمستوى التالي
    next_xp = next((t for t, _, _ in RANK_TITLES if t > stats["xp"]), None)
    xp_line = f"⚡ XP: *{stats[\'xp\']}*" + (f" /{next_xp}" if next_xp else " 🏆 MAX")
    return (
        f"👋 أهلاً {display}!\n\n"
        f"🎓 *المثابر الوزاري*\n"
        f"━━━━━━━━━━━━━━━\n"
        f"{cert_line}"
        f"{icon} لقبك: *{label}*\n"
        f"{xp_line}\n"
        f"🔥 السلسلة: *{stats[\'streak\']}* يوم\n"
        f"🎮 جولات: *{stats[\'total_games\']}*\n\n"
        f"اختر ما تريد 👇"
    )

# ─── /start ──────────────────────────────────────────────────
@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    """Handles the /start command, registers user, and displays main menu."""
    try:
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
            b.button(text="✅ قبول", callback_data=f"accept_challenge:{pending[\'id\']}")
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
    except AiogramError as e:
        logger.error(f"Error in cmd_start for user {message.from_user.id}: {e}")
        await message.answer("حدث خطأ أثناء بدء البوت. يرجى المحاولة مرة أخرى لاحقًا.")
    except Exception as e:
        logger.error(f"Unexpected error in cmd_start for user {message.from_user.id}: {e}")
        await message.answer("حدث خطأ غير متوقع. يرجى إبلاغ المسؤول.")

@dp.callback_query(F.data == "back_home")
async def back_home(callback: CallbackQuery, state: FSMContext):
    """Handles the \'back_home\' callback, clearing state and showing main menu."""
    try:
        await state.clear()
        user = callback.from_user
        await callback.message.edit_text(
            welcome_text(user.id, user.first_name),
            parse_mode="Markdown", reply_markup=main_menu_kb()
        )
        await callback.answer()
        await state.set_state(QuizStates.choosing_subject)
    except TelegramBadRequest:
        # Message was not modified, or already deleted
        logger.warning(f"TelegramBadRequest in back_home for user {callback.from_user.id}. Message might be too old or already modified.")
        await callback.message.answer(
            welcome_text(user.id, user.first_name),
            parse_mode="Markdown", reply_markup=main_menu_kb()
        )
        await callback.answer()
        await state.set_state(QuizStates.choosing_subject)
    except AiogramError as e:
        logger.error(f"Error in back_home for user {callback.from_user.id}: {e}")
        await callback.message.answer("حدث خطأ أثناء العودة للقائمة الرئيسية. يرجى المحاولة مرة أخرى.")
        await callback.answer()
    except Exception as e:
        logger.error(f"Unexpected error in back_home for user {callback.from_user.id}: {e}")
        await callback.message.answer("حدث خطأ غير متوقع. يرجى إبلاغ المسؤول.")
        await callback.answer()

@dp.callback_query(F.data == "subjects_menu")
async def subjects_menu(callback: CallbackQuery, state: FSMContext):
    """Displays the subject selection menu."""
    try:
        await state.set_state(QuizStates.choosing_subject)
        await callback.message.edit_text(
            "اختر الفرع الدراسي:",
            reply_markup=branch_select_kb("select_branch")
        )
        await callback.answer()
    except TelegramBadRequest:
        logger.warning(f"TelegramBadRequest in subjects_menu for user {callback.from_user.id}. Message might be too old or already modified.")
        await callback.message.answer(
            "اختر الفرع الدراسي:",
            reply_markup=branch_select_kb("select_branch")
        )
        await callback.answer()
    except AiogramError as e:
        logger.error(f"Error in subjects_menu for user {callback.from_user.id}: {e}")
        await callback.message.answer("حدث خطأ أثناء عرض قائمة المواد. يرجى المحاولة مرة أخرى.")
        await callback.answer()
    except Exception as e:
        logger.error(f"Unexpected error in subjects_menu for user {callback.from_user.id}: {e}")
        await callback.message.answer("حدث خطأ غير متوقع. يرجى إبلاغ المسؤول.")
        await callback.answer()

@dp.callback_query(F.data.startswith("select_branch:"))
async def select_branch(callback: CallbackQuery, state: FSMContext):
    """Handles branch selection and displays subjects for that branch."""
    try:
        branch_key = callback.data.split(":")[1]
        await state.update_data(branch=branch_key)
        if branch_key == "all":
            branch_name = "كل الفروع"
        else:
            branch_name = BRANCHES[branch_key]["name"]

        await callback.message.edit_text(
            f"اختر المادة من *{branch_name}*:",
            parse_mode="Markdown",
            reply_markup=subjects_for_branch_kb(branch_key)
        )
        await callback.answer()
    except TelegramBadRequest:
        logger.warning(f"TelegramBadRequest in select_branch for user {callback.from_user.id}. Message might be too old or already modified.")
        await callback.message.answer(
            f"اختر المادة من *{branch_name}*:",
            parse_mode="Markdown",
            reply_markup=subjects_for_branch_kb(branch_key)
        )
        await callback.answer()
    except AiogramError as e:
        logger.error(f"Error in select_branch for user {callback.from_user.id}: {e}")
        await callback.message.answer("حدث خطأ أثناء اختيار الفرع. يرجى المحاولة مرة أخرى.")
        await callback.answer()
    except Exception as e:
        logger.error(f"Unexpected error in select_branch for user {callback.from_user.id}: {e}")
        await callback.message.answer("حدث خطأ غير متوقع. يرجى إبلاغ المسؤول.")
        await callback.answer()

@dp.callback_query(F.data.startswith("subject:"))
async def start_quiz(callback: CallbackQuery, state: FSMContext):
    """Starts a new quiz for the selected subject."""
    try:
        subject_key = callback.data.split(":")[1]
        user_id = callback.from_user.id

        if subject_key.startswith("branch_"):
            branch_key = subject_key.split("_")[1]
            subjects_in_branch = BRANCHES[branch_key]["subjects"]
            # Pick 10 questions randomly from all subjects in the branch
            all_branch_questions = []
            for s_key in subjects_in_branch:
                all_branch_questions.extend([{**q, "_subject": s_key} for q in QUESTION_BANK.get(s_key, [])])
            random.shuffle(all_branch_questions)
            questions = random.sample(all_branch_questions, min(10, len(all_branch_questions)))
            subject_name = BRANCHES[branch_key]["name"] + " (كل المواد)"
            subject_icon = BRANCHES[branch_key]["icon"]
        else:
            questions = pick_questions(subject_key, 10)
            subject_name, subject_icon = subj_info(subject_key)

        if not questions:
            await callback.message.edit_text(f"{subject_icon} لا توجد أسئلة متاحة في *{subject_name}* حاليًا.", parse_mode="Markdown", reply_markup=back_home_kb())
            await callback.answer()
            return

        await state.update_data(subject=subject_key, questions=questions, current_q_index=0, correct_answers=0, start_time=datetime.now())
        await state.set_state(QuizStates.in_quiz)

        current_q = questions[0]
        options_kb_markup = options_kb(current_q["options"], 0)

        await callback.message.edit_text(
            f"{subject_icon} *جولة في {subject_name}*\n\n"
            f"*السؤال 1/10:*\n{current_q[\'q\']}",
            parse_mode="Markdown",
            reply_markup=options_kb_markup
        )
        await callback.answer()
    except TelegramBadRequest:
        logger.warning(f"TelegramBadRequest in start_quiz for user {callback.from_user.id}. Message might be too old or already modified.")
        await callback.message.answer(
            f"{subject_icon} *جولة في {subject_name}*\n\n"
            f"*السؤال 1/10:*\n{current_q[\'q\']}",
            parse_mode="Markdown",
            reply_markup=options_kb_markup
        )
        await callback.answer()
    except AiogramError as e:
        logger.error(f"Error in start_quiz for user {callback.from_user.id}: {e}")
        await callback.message.answer("حدث خطأ أثناء بدء الاختبار. يرجى المحاولة مرة أخرى.")
        await callback.answer()
    except Exception as e:
        logger.error(f"Unexpected error in start_quiz for user {callback.from_user.id}: {e}")
        await callback.message.answer("حدث خطأ غير متوقع. يرجى إبلاغ المسؤول.")
        await callback.answer()

@dp.callback_query(F.data.startswith("answer:"), QuizStates.in_quiz)
async def handle_answer(callback: CallbackQuery, state: FSMContext):
    """Handles user\'s answer during a quiz."""
    try:
        data = await state.get_data()
        questions = data["questions"]
        current_q_index = data["current_q_index"]
        correct_answers = data["correct_answers"]
        subject_key = data["subject"]
        start_time = data["start_time"]

        _, _, chosen_option_index = callback.data.split(":")
        chosen_option_index = int(chosen_option_index)

        current_q = questions[current_q_index]
        is_correct = (chosen_option_index == current_q["answer"])

        feedback_text = "✅ إجابة صحيحة!" if is_correct else f"❌ إجابة خاطئة. الصحيح: {current_q[\'options\'][current_q[\'answer\']]}"
        if is_correct: correct_answers += 1

        current_q_index += 1

        if current_q_index < len(questions):
            next_q = questions[current_q_index]
            options_kb_markup = options_kb(next_q["options"], current_q_index)
            await state.update_data(current_q_index=current_q_index, correct_answers=correct_answers)
            await callback.message.edit_text(
                f"{subj_info(subject_key)[0]} *جولة في {subj_info(subject_key)[0]}*\n\n"
                f"*السؤال {current_q_index + 1}/10:*\n{next_q[\'q\']}\n\n"
                f"_{feedback_text}_",
                parse_mode="Markdown",
                reply_markup=options_kb_markup
            )
            await callback.answer()
        else:
            end_time = datetime.now()
            duration = int((end_time - start_time).total_seconds())
            xp_earned = correct_answers * 10 # 10 XP per correct answer
            bonus_xp = db.update_stats(callback.from_user.id, xp_earned, correct_answers, len(questions), subject_key)

            final_message = (
                f"🎉 *انتهت الجولة!* 🎉\n"
                f"المادة: *{subj_info(subject_key)[0]}*\n"
                f"الأسئلة الصحيحة: *{correct_answers}/{len(questions)}*\n"
                f"نقاط الخبرة المكتسبة: *{xp_earned}* XP"
            )
            if bonus_xp > 0:
                final_message += f"\n🎁 *مكافأة سلسلة: +{bonus_xp} XP!*"
            final_message += f"\nالوقت المستغرق: *{duration} ثانية*\n\n"
            final_message += welcome_text(callback.from_user.id, callback.from_user.first_name)

            await callback.message.edit_text(
                final_message,
                parse_mode="Markdown",
                reply_markup=main_menu_kb()
            )
            await state.clear()
            await callback.answer()
    except TelegramBadRequest:
        logger.warning(f"TelegramBadRequest in handle_answer for user {callback.from_user.id}. Message might be too old or already modified.")
        # Attempt to send a new message with the result or next question
        data = await state.get_data()
        questions = data.get("questions", [])
        current_q_index = data.get("current_q_index", 0)
        correct_answers = data.get("correct_answers", 0)
        subject_key = data.get("subject", "all")
        start_time = data.get("start_time", datetime.now())

        if current_q_index < len(questions):
            next_q = questions[current_q_index]
            options_kb_markup = options_kb(next_q["options"], current_q_index)
            await callback.message.answer(
                f"{subj_info(subject_key)[0]} *جولة في {subj_info(subject_key)[0]}*\n\n"
                f"*السؤال {current_q_index + 1}/10:*\n{next_q[\'q\']}",
                parse_mode="Markdown",
                reply_markup=options_kb_markup
            )
        else:
            end_time = datetime.now()
            duration = int((end_time - start_time).total_seconds())
            xp_earned = correct_answers * 10
            bonus_xp = db.update_stats(callback.from_user.id, xp_earned, correct_answers, len(questions), subject_key)

            final_message = (
                f"🎉 *انتهت الجولة!* 🎉\n"
                f"المادة: *{subj_info(subject_key)[0]}*\n"
                f"الأسئلة الصحيحة: *{correct_answers}/{len(questions)}*\n"
                f"نقاط الخبرة المكتسبة: *{xp_earned}* XP"
            )
            if bonus_xp > 0:
                final_message += f"\n🎁 *مكافأة سلسلة: +{bonus_xp} XP!*"
            final_message += f"\nالوقت المستغرق: *{duration} ثانية*\n\n"
            final_message += welcome_text(callback.from_user.id, callback.from_user.first_name)

            await callback.message.answer(
                final_message,
                parse_mode="Markdown",
                reply_markup=main_menu_kb()
            )
            await state.clear()
        await callback.answer()
    except AiogramError as e:
        logger.error(f"Error in handle_answer for user {callback.from_user.id}: {e}")
        await callback.message.answer("حدث خطأ أثناء معالجة إجابتك. يرجى المحاولة مرة أخرى.")
        await callback.answer()
    except Exception as e:
        logger.error(f"Unexpected error in handle_answer for user {callback.from_user.id}: {e}")
        await callback.message.answer("حدث خطأ غير متوقع. يرجى إبلاغ المسؤول.")
        await callback.answer()

# ─── Study Mode ────────────────────────────────────────────────
@dp.callback_query(F.data == "study_mode_menu")
async def study_mode_menu(callback: CallbackQuery, state: FSMContext):
    """Displays the study mode menu."""
    try:
        await state.set_state(QuizStates.study_mode)
        await callback.message.edit_text(
            "📖 *وضع الدراسة*\nاختر المادة التي تود مراجعتها:",
            parse_mode="Markdown",
            reply_markup=branch_select_kb("study_subject")
        )
        await callback.answer()
    except TelegramBadRequest:
        logger.warning(f"TelegramBadRequest in study_mode_menu for user {callback.from_user.id}. Message might be too old or already modified.")
        await callback.message.answer(
            "📖 *وضع الدراسة*\nاختر المادة التي تود مراجعتها:",
            parse_mode="Markdown",
            reply_markup=branch_select_kb("study_subject")
        )
        await callback.answer()
    except AiogramError as e:
        logger.error(f"Error in study_mode_menu for user {callback.from_user.id}: {e}")
        await callback.message.answer("حدث خطأ أثناء عرض وضع الدراسة. يرجى المحاولة مرة أخرى.")
        await callback.answer()
    except Exception as e:
        logger.error(f"Unexpected error in study_mode_menu for user {callback.from_user.id}: {e}")
        await callback.message.answer("حدث خطأ غير متوقع. يرجى إبلاغ المسؤول.")
        await callback.answer()

@dp.callback_query(F.data.startswith("study_subject:"), QuizStates.study_mode)
async def start_study_mode(callback: CallbackQuery, state: FSMContext):
    """Starts study mode for the selected subject."""
    try:
        subject_key = callback.data.split(":")[1]
        if subject_key.startswith("branch_"):
            branch_key = subject_key.split("_")[1]
            subjects_in_branch = BRANCHES[branch_key]["subjects"]
            all_branch_questions = []
            for s_key in subjects_in_branch:
                all_branch_questions.extend([{**q, "_subject": s_key} for q in QUESTION_BANK.get(s_key, [])])
            random.shuffle(all_branch_questions)
            questions = all_branch_questions # In study mode, we can show all questions
            subject_name = BRANCHES[branch_key]["name"] + " (كل المواد)"
            subject_icon = BRANCHES[branch_key]["icon"]
        else:
            questions = QUESTION_BANK.get(subject_key, [])
            subject_name, subject_icon = subj_info(subject_key)

        if not questions:
            await callback.message.edit_text(f"{subject_icon} لا توجد أسئلة متاحة في *{subject_name}* حاليًا لوضع الدراسة.", parse_mode="Markdown", reply_markup=back_home_kb())
            await callback.answer()
            return

        await state.update_data(subject=subject_key, questions=questions, current_q_index=0)

        current_q = questions[0]
        options_kb_markup = InlineKeyboardBuilder()
        labels = ["أ", "ب", "ج", "د"]
        for i, opt in enumerate(current_q["options"]):
            options_kb_markup.button(text=f"{labels[i]}) {opt}", callback_data=f"study_answer:{current_q_index}:{i}")
        options_kb_markup.adjust(1)
        options_kb_markup.button(text="➡️ السؤال التالي", callback_data="study_next_q")
        options_kb_markup.button(text="🏠 إنهاء وضع الدراسة", callback_data="back_home")
        options_kb_markup.adjust(1, 2)

        await callback.message.edit_text(
            f"{subject_icon} *وضع الدراسة في {subject_name}*\n\n"
            f"*السؤال {1}/{len(questions)}:*\n{current_q[\'q\']}",
            parse_mode="Markdown",
            reply_markup=options_kb_markup.as_markup()
        )
        await callback.answer()
    except TelegramBadRequest:
        logger.warning(f"TelegramBadRequest in start_study_mode for user {callback.from_user.id}. Message might be too old or already modified.")
        await callback.message.answer(
            f"{subject_icon} *وضع الدراسة في {subject_name}*\n\n"
            f"*السؤال {1}/{len(questions)}:*\n{current_q[\'q\']}",
            parse_mode="Markdown",
            reply_markup=options_kb_markup.as_markup()
        )
        await callback.answer()
    except AiogramError as e:
        logger.error(f"Error in start_study_mode for user {callback.from_user.id}: {e}")
        await callback.message.answer("حدث خطأ أثناء بدء وضع الدراسة. يرجى المحاولة مرة أخرى.")
        await callback.answer()
    except Exception as e:
        logger.error(f"Unexpected error in start_study_mode for user {callback.from_user.id}: {e}")
        await callback.message.answer("حدث خطأ غير متوقع. يرجى إبلاغ المسؤول.")
        await callback.answer()

@dp.callback_query(F.data.startswith("study_answer:"), QuizStates.study_mode)
async def handle_study_answer(callback: CallbackQuery, state: FSMContext):
    """Handles user\'s answer in study mode, showing immediate feedback."""
    try:
        data = await state.get_data()
        questions = data["questions"]
        current_q_index = data["current_q_index"]
        subject_key = data["subject"]

        _, q_idx, chosen_option_index = callback.data.split(":")
        q_idx = int(q_idx)
        chosen_option_index = int(chosen_option_index)

        if q_idx != current_q_index:
            await callback.answer("هذا السؤال ليس السؤال الحالي.", show_alert=True)
            return

        current_q = questions[current_q_index]
        is_correct = (chosen_option_index == current_q["answer"])

        feedback_text = "✅ إجابة صحيحة!" if is_correct else f"❌ إجابة خاطئة. الصحيح: {current_q[\'options\'][current_q[\'answer\']]}"

        options_kb_markup = InlineKeyboardBuilder()
        labels = ["أ", "ب", "ج", "د"]
        for i, opt in enumerate(current_q["options"]):
            button_text = f"{labels[i]}) {opt}"
            if i == current_q["answer"]:
                button_text = f"✅ {button_text}"
            elif i == chosen_option_index and not is_correct:
                button_text = f"❌ {button_text}"
            options_kb_markup.button(text=button_text, callback_data=f"study_answer_shown:{current_q_index}:{i}") # Disable further interaction
        options_kb_markup.adjust(1)
        options_kb_markup.button(text="➡️ السؤال التالي", callback_data="study_next_q")
        options_kb_markup.button(text="🏠 إنهاء وضع الدراسة", callback_data="back_home")
        options_kb_markup.adjust(1, 2)

        await callback.message.edit_text(
            f"{subj_info(subject_key)[0]} *وضع الدراسة في {subj_info(subject_key)[0]}*\n\n"
            f"*السؤال {current_q_index + 1}/{len(questions)}:*\n{current_q[\'q\']}\n\n"
            f"_{feedback_text}_",
            parse_mode="Markdown",
            reply_markup=options_kb_markup.as_markup()
        )
        await callback.answer()
    except TelegramBadRequest:
        logger.warning(f"TelegramBadRequest in handle_study_answer for user {callback.from_user.id}. Message might be too old or already modified.")
        await callback.message.answer("حدث خطأ في عرض الإجابة. يرجى الانتقال للسؤال التالي.", reply_markup=back_home_kb())
        await callback.answer()
    except AiogramError as e:
        logger.error(f"Error in handle_study_answer for user {callback.from_user.id}: {e}")
        await callback.message.answer("حدث خطأ أثناء معالجة إجابتك في وضع الدراسة. يرجى المحاولة مرة أخرى.")
        await callback.answer()
    except Exception as e:
        logger.error(f"Unexpected error in handle_study_answer for user {callback.from_user.id}: {e}")
        await callback.message.answer("حدث خطأ غير متوقع. يرجى إبلاغ المسؤول.")
        await callback.answer()

@dp.callback_query(F.data == "study_next_q", QuizStates.study_mode)
async def study_next_question(callback: CallbackQuery, state: FSMContext):
    """Moves to the next question in study mode."""
    try:
        data = await state.get_data()
        questions = data["questions"]
        current_q_index = data["current_q_index"]
        subject_key = data["subject"]

        current_q_index += 1

        if current_q_index < len(questions):
            next_q = questions[current_q_index]
            options_kb_markup = InlineKeyboardBuilder()
            labels = ["أ", "ب", "ج", "د"]
            for i, opt in enumerate(next_q["options"]):
                options_kb_markup.button(text=f"{labels[i]}) {opt}", callback_data=f"study_answer:{current_q_index}:{i}")
            options_kb_markup.adjust(1)
            options_kb_markup.button(text="➡️ السؤال التالي", callback_data="study_next_q")
            options_kb_markup.button(text="🏠 إنهاء وضع الدراسة", callback_data="back_home")
            options_kb_markup.adjust(1, 2)

            await state.update_data(current_q_index=current_q_index)
            await callback.message.edit_text(
                f"{subj_info(subject_key)[0]} *وضع الدراسة في {subj_info(subject_key)[0]}*\n\n"
                f"*السؤال {current_q_index + 1}/{len(questions)}:*\n{next_q[\'q\']}",
                parse_mode="Markdown",
                reply_markup=options_kb_markup.as_markup()
            )
            await callback.answer()
        else:
            await callback.message.edit_text(
                f"✅ *لقد أكملت جميع الأسئلة في وضع الدراسة لهذه المادة!*\n\n"
                f"{welcome_text(callback.from_user.id, callback.from_user.first_name)}",
                parse_mode="Markdown",
                reply_markup=main_menu_kb()
            )
            await state.clear()
            await callback.answer()
    except TelegramBadRequest:
        logger.warning(f"TelegramBadRequest in study_next_question for user {callback.from_user.id}. Message might be too old or already modified.")
        await callback.message.answer("حدث خطأ في عرض السؤال التالي. يرجى العودة للقائمة الرئيسية.", reply_markup=back_home_kb())
        await callback.answer()
    except AiogramError as e:
        logger.error(f"Error in study_next_question for user {callback.from_user.id}: {e}")
        await callback.message.answer("حدث خطأ أثناء الانتقال للسؤال التالي. يرجى المحاولة مرة أخرى.")
        await callback.answer()
    except Exception as e:
        logger.error(f"Unexpected error in study_next_question for user {callback.from_user.id}: {e}")
        await callback.message.answer("حدث خطأ غير متوقع. يرجى إبلاغ المسؤول.")
        await callback.answer()

# ─── Challenge Mode ──────────────────────────────────────────
@dp.callback_query(F.data == "challenge_menu")
async def challenge_menu(callback: CallbackQuery, state: FSMContext):
    """Displays the challenge menu."""
    try:
        await callback.message.edit_text(
            "⚔️ *تحدي صديق*\nاختر المادة التي تود التحدي فيها:",
            parse_mode="Markdown",
            reply_markup=branch_select_kb("challenge_subject")
        )
        await callback.answer()
    except TelegramBadRequest:
        logger.warning(f"TelegramBadRequest in challenge_menu for user {callback.from_user.id}. Message might be too old or already modified.")
        await callback.message.answer(
            "⚔️ *تحدي صديق*\nاختر المادة التي تود التحدي فيها:",
            parse_mode="Markdown",
            reply_markup=branch_select_kb("challenge_subject")
        )
        await callback.answer()
    except AiogramError as e:
        logger.error(f"Error in challenge_menu for user {callback.from_user.id}: {e}")
        await callback.message.answer("حدث خطأ أثناء عرض قائمة التحدي. يرجى المحاولة مرة أخرى.")
        await callback.answer()
    except Exception as e:
        logger.error(f"Unexpected error in challenge_menu for user {callback.from_user.id}: {e}")
        await callback.message.answer("حدث خطأ غير متوقع. يرجى إبلاغ المسؤول.")
        await callback.answer()

@dp.callback_query(F.data.startswith("challenge_subject:"))
async def select_challenge_subject(callback: CallbackQuery, state: FSMContext):
    """Handles challenge subject selection and prompts for opponent username."""
    try:
        subject_key = callback.data.split(":")[1]
        await state.update_data(challenge_subject=subject_key)
        await state.set_state(QuizStates.challenge_wait)

        subject_name, subject_icon = subj_info(subject_key)

        await callback.message.edit_text(
            f"{subject_icon} *تحدي في {subject_name}*\n\n"
            f"أرسل اسم المستخدم (username) لصديقك الذي تود تحديه (بدون @):",
            parse_mode="Markdown",
            reply_markup=back_home_kb()
        )
        await callback.answer()
    except TelegramBadRequest:
        logger.warning(f"TelegramBadRequest in select_challenge_subject for user {callback.from_user.id}. Message might be too old or already modified.")
        await callback.message.answer(
            f"{subject_icon} *تحدي في {subject_name}*\n\n"
            f"أرسل اسم المستخدم (username) لصديقك الذي تود تحديه (بدون @):",
            parse_mode="Markdown",
            reply_markup=back_home_kb()
        )
        await callback.answer()
    except AiogramError as e:
        logger.error(f"Error in select_challenge_subject for user {callback.from_user.id}: {e}")
        await callback.message.answer("حدث خطأ أثناء اختيار مادة التحدي. يرجى المحاولة مرة أخرى.")
        await callback.answer()
    except Exception as e:
        logger.error(f"Unexpected error in select_challenge_subject for user {callback.from_user.id}: {e}")
        await callback.message.answer("حدث خطأ غير متوقع. يرجى إبلاغ المسؤول.")
        await callback.answer()

@dp.message(QuizStates.challenge_wait)
async def process_challenge_username(message: Message, state: FSMContext):
    """Processes the opponent\'s username for a challenge."""
    try:
        opponent_username = message.text.strip()
        if not opponent_username:
            await message.answer("الرجاء إدخال اسم مستخدم صالح.", reply_markup=back_home_kb())
            return

        opponent_users = db.get_user_by_username_search(opponent_username)
        if not opponent_users:
            await message.answer("لم يتم العثور على هذا المستخدم. تأكد من أن اسم المستخدم صحيح وأن صديقك قد بدأ البوت من قبل.", reply_markup=back_home_kb())
            return
        
        # For simplicity, pick the first one if multiple found. In a real app, might need a selection.
        opponent_user_id = opponent_users[0]["user_id"]
        opponent_full_name = opponent_users[0]["name"]

        if opponent_user_id == message.from_user.id:
            await message.answer("لا يمكنك تحدي نفسك! اختر صديقًا آخر.", reply_markup=back_home_kb())
            return

        data = await state.get_data()
        subject_key = data["challenge_subject"]
        subject_name, subject_icon = subj_info(subject_key)

        challenge_id = db.create_challenge(message.from_user.id, opponent_user_id, subject_key)
        if challenge_id is None:
            await message.answer("حدث خطأ في إنشاء التحدي. يرجى المحاولة مرة أخرى.", reply_markup=back_home_kb())
            return

        # Notify opponent
        challenge_link = f"https://t.me/{bot.me.username}?start=challenge_{challenge_id}"
        await bot.send_message(
            opponent_user_id,
            f"⚔️ *تحدي جديد من {message.from_user.full_name}!*\n"
            f"{subject_icon} في مادة *{subject_name}*\n"
            f"اقبل التحدي من هنا: [ابدأ التحدي]({challenge_link})",
            parse_mode="Markdown"
        )

        await message.answer(
            f"✅ تم إرسال التحدي إلى *{opponent_full_name}* في مادة *{subject_name}*. بانتظار قبوله!",
            parse_mode="Markdown",
            reply_markup=back_home_kb()
        )
        await state.clear()
    except AiogramError as e:
        logger.error(f"Error in process_challenge_username for user {message.from_user.id}: {e}")
        await message.answer("حدث خطأ أثناء معالجة اسم المستخدم للتحدي. يرجى المحاولة مرة أخرى.")
    except Exception as e:
        logger.error(f"Unexpected error in process_challenge_username for user {message.from_user.id}: {e}")
        await message.answer("حدث خطأ غير متوقع. يرجى إبلاغ المسؤول.")

@dp.callback_query(F.data.startswith("accept_challenge:"))
async def accept_challenge(callback: CallbackQuery, state: FSMContext):
    """Accepts a challenge and starts the quiz for the opponent."""
    try:
        challenge_id = int(callback.data.split(":")[1])
        challenge = db.get_challenge(challenge_id)

        if not challenge or challenge["status"] != "pending" or challenge["opponent"] != callback.from_user.id:
            await callback.message.edit_text("❌ هذا التحدي غير صالح أو تم قبوله بالفعل.", reply_markup=back_home_kb())
            await callback.answer()
            return

        subject_key = challenge["subject"]
        subject_name, subject_icon = subj_info(subject_key)
        questions = pick_questions(subject_key, 10)

        if not questions:
            await callback.message.edit_text(f"{subject_icon} لا توجد أسئلة متاحة في *{subject_name}* حاليًا.", parse_mode="Markdown", reply_markup=back_home_kb())
            await callback.answer()
            return

        await state.update_data(subject=subject_key, questions=questions, current_q_index=0, correct_answers=0, start_time=datetime.now(), challenge_id=challenge_id, is_challenger=False)
        await state.set_state(QuizStates.in_quiz)

        current_q = questions[0]
        options_kb_markup = options_kb(current_q["options"], 0)

        await callback.message.edit_text(
            f"⚔️ *تحدي في {subject_name}*\n\n"
            f"*السؤال 1/10:*\n{current_q[\'q\']}",
            parse_mode="Markdown",
            reply_markup=options_kb_markup
        )
        await callback.answer()

        # Notify challenger that challenge was accepted
        challenger_stats = db.get_user_stats(challenge["challenger"])
        challenger_name = challenger_stats.get("name", "صديقك")
        await bot.send_message(
            challenge["challenger"],
            f"✅ *{callback.from_user.full_name} قبل تحديك في مادة {subject_name}!*\n"
            f"بانتظار نتيجته..."
        )

    except TelegramBadRequest:
        logger.warning(f"TelegramBadRequest in accept_challenge for user {callback.from_user.id}. Message might be too old or already modified.")
        await callback.message.answer("حدث خطأ في قبول التحدي. يرجى المحاولة مرة أخرى من القائمة الرئيسية.", reply_markup=main_menu_kb())
        await callback.answer()
    except AiogramError as e:
        logger.error(f"Error in accept_challenge for user {callback.from_user.id}: {e}")
        await callback.message.answer("حدث خطأ أثناء قبول التحدي. يرجى المحاولة مرة أخرى.")
        await callback.answer()
    except Exception as e:
        logger.error(f"Unexpected error in accept_challenge for user {callback.from_user.id}: {e}")
        await callback.message.answer("حدث خطأ غير متوقع. يرجى إبلاغ المسؤول.")
        await callback.answer()

async def process_join(user, payload, message):
    """Processes a join request from a deep link (e.g., challenge or group session)."""
    try:
        if payload.startswith("challenge_"):
            challenge_id = int(payload.split("_")[1])
            challenge = db.get_challenge(challenge_id)
            if challenge and challenge["opponent"] == user.id and challenge["status"] == "pending":
                sn, si = subj_info(challenge["subject"])
                b = InlineKeyboardBuilder()
                b.button(text="✅ قبول", callback_data=f"accept_challenge:{challenge_id}")
                b.button(text="❌ رفض",  callback_data="back_home")
                b.adjust(2)
                await message.answer(
                    f"⚔️ *تحدي جديد!*\n{si} *{sn}*\nهل تقبل؟",
                    parse_mode="Markdown", reply_markup=b.as_markup()
                )
            else:
                await message.answer("❌ هذا التحدي غير صالح أو تم قبوله بالفعل.", reply_markup=back_home_kb())
        elif payload.startswith("session_"):
            session_id = payload.split("_")[1]
            session = db.get_session(session_id)
            if session and session["status"] == "waiting":
                if db.join_session(session_id, user.id, user.full_name):
                    await message.answer(f"✅ انضممت إلى جولة المجموعة في مادة *{subj_info(session[\'subject\'])[0]}*! بانتظار بدء الجولة.", parse_mode="Markdown", reply_markup=back_home_kb())
                    # Notify owner
                    owner_name = db.get_user_stats(session["owner_id"])[\'name\']
                    await bot.send_message(session["owner_id"], f"👥 *{user.full_name} انضم إلى جولة مجموعتك!*\nعدد اللاعبين: {len(db.get_session_players(session_id))}/{MAX_PLAYERS}")
                else:
                    await message.answer("❌ لا يمكن الانضمام إلى هذه الجولة. قد تكون ممتلئة أو بدأت بالفعل.", reply_markup=back_home_kb())
            else:
                await message.answer("❌ هذه الجولة غير صالحة أو انتهت.", reply_markup=back_home_kb())
        else:
            await message.answer("رابط غير صالح.", reply_markup=back_home_kb())
    except AiogramError as e:
        logger.error(f"Error in process_join for user {user.id} with payload {payload}: {e}")
        await message.answer("حدث خطأ أثناء معالجة طلب الانضمام. يرجى المحاولة مرة أخرى.")
    except Exception as e:
        logger.error(f"Unexpected error in process_join for user {user.id} with payload {payload}: {e}")
        await message.answer("حدث خطأ غير متوقع. يرجى إبلاغ المسؤول.")

# ─── Group Mode ────────────────────────────────────────────────
@dp.callback_query(F.data == "group_menu")
async def group_menu(callback: CallbackQuery, state: FSMContext):
    """Displays the group session menu."""
    try:
        await callback.message.edit_text(
            "👥 *جولة مجموعة*\nاختر المادة التي تود إنشاء جولة فيها:",
            parse_mode="Markdown",
            reply_markup=branch_select_kb("group_subject")
        )
        await callback.answer()
    except TelegramBadRequest:
        logger.warning(f"TelegramBadRequest in group_menu for user {callback.from_user.id}. Message might be too old or already modified.")
        await callback.message.answer(
            "👥 *جولة مجموعة*\nاختر المادة التي تود إنشاء جولة فيها:",
            parse_mode="Markdown",
            reply_markup=branch_select_kb("group_subject")
        )
        await callback.answer()
    except AiogramError as e:
        logger.error(f"Error in group_menu for user {callback.from_user.id}: {e}")
        await callback.message.answer("حدث خطأ أثناء عرض قائمة جولات المجموعة. يرجى المحاولة مرة أخرى.")
        await callback.answer()
    except Exception as e:
        logger.error(f"Unexpected error in group_menu for user {callback.from_user.id}: {e}")
        await callback.message.answer("حدث خطأ غير متوقع. يرجى إبلاغ المسؤول.")
        await callback.answer()

@dp.callback_query(F.data.startswith("group_subject:"))
async def create_group_session(callback: CallbackQuery, state: FSMContext):
    """Creates a new group session for the selected subject."""
    try:
        subject_key = callback.data.split(":")[1]
        session_id = str(uuid.uuid4())
        user = callback.from_user
        chat_id = callback.message.chat.id

        db.create_session(session_id, user.id, user.full_name, subject_key, chat_id)

        session_link = f"https://t.me/{bot.me.username}?start=session_{session_id}"
        subject_name, subject_icon = subj_info(subject_key)

        kb = InlineKeyboardBuilder()
        kb.button(text="🔗 رابط الانضمام", url=session_link)
        kb.button(text="▶️ بدء الجولة", callback_data=f"start_group_session:{session_id}")
        kb.button(text="❌ إلغاء الجولة", callback_data=f"cancel_group_session:{session_id}")
        kb.adjust(1, 2)

        msg = await callback.message.edit_text(
            f"👥 *جولة مجموعة جديدة!*\n"
            f"المادة: {subject_icon} *{subject_name}*\n"
            f"المنظم: *{user.full_name}*\n"
            f"اللاعبون: 1/{MAX_PLAYERS}\n\n"
            f"ادعُ أصدقاءك للانضمام!",
            parse_mode="Markdown",
            reply_markup=kb.as_markup()
        )
        db.set_session_msg(session_id, msg.message_id)
        await callback.answer()
    except TelegramBadRequest:
        logger.warning(f"TelegramBadRequest in create_group_session for user {callback.from_user.id}. Message might be too old or already modified.")
        await callback.message.answer("حدث خطأ في إنشاء الجولة. يرجى المحاولة مرة أخرى من القائمة الرئيسية.", reply_markup=main_menu_kb())
        await callback.answer()
    except AiogramError as e:
        logger.error(f"Error in create_group_session for user {callback.from_user.id}: {e}")
        await callback.message.answer("حدث خطأ أثناء إنشاء جولة المجموعة. يرجى المحاولة مرة أخرى.")
        await callback.answer()
    except Exception as e:
        logger.error(f"Unexpected error in create_group_session for user {callback.from_user.id}: {e}")
        await callback.message.answer("حدث خطأ غير متوقع. يرجى إبلاغ المسؤول.")
        await callback.answer()

@dp.callback_query(F.data.startswith("start_group_session:"))
async def start_group_session(callback: CallbackQuery, state: FSMContext):
    """Starts a group quiz for the session owner."""
    try:
        session_id = callback.data.split(":")[1]
        session = db.get_session(session_id)

        if not session or session["owner_id"] != callback.from_user.id or session["status"] != "waiting":
            await callback.answer("❌ لا يمكنك بدء هذه الجولة.", show_alert=True)
            return

        players = db.get_session_players(session_id)
        if len(players) < 1:
            await callback.answer("لا يوجد لاعبون في الجولة بعد.", show_alert=True)
            return

        db.start_session(session_id)
        subject_name, subject_icon = subj_info(session["subject"])
        questions = pick_questions(session["subject"], 10)

        if not questions:
            await callback.message.edit_text(f"{subject_icon} لا توجد أسئلة متاحة في *{subject_name}* حاليًا.", parse_mode="Markdown", reply_markup=back_home_kb())
            await callback.answer()
            return

        # Send quiz to all players
        for player in players:
            player_id = player["user_id"]
            await bot.send_message(
                player_id,
                f"🎉 *بدأت جولة المجموعة في {subject_name}!*\n"
                f"استعد للإجابة على الأسئلة..."
            )
            await bot.send_message(
                player_id,
                f"*السؤال 1/10:*\n{questions[0][\'q\']}",
                parse_mode="Markdown",
                reply_markup=options_kb(questions[0]["options"], 0, prefix=f"group_answer:{session_id}:{player_id}")
            )
            # Store quiz state for each player
            await dp.storage.set_data(bot=bot, user=player_id, key=f"group_quiz_state_{session_id}", data={
                "questions": questions,
                "current_q_index": 0,
                "correct_answers": 0,
                "start_time": datetime.now(),
                "subject": session["subject"],
                "session_id": session_id
            })
            await dp.storage.set_state(bot=bot, user=player_id, state=QuizStates.in_quiz)

        await callback.message.edit_text(
            f"✅ *بدأت جولة المجموعة في {subject_name}!*\n"
            f"تم إرسال الأسئلة للاعبين. بانتظار النتائج...",
            parse_mode="Markdown",
            reply_markup=back_home_kb()
        )
        await callback.answer()
    except TelegramBadRequest:
        logger.warning(f"TelegramBadRequest in start_group_session for user {callback.from_user.id}. Message might be too old or already modified.")
        await callback.message.answer("حدث خطأ في بدء الجولة. يرجى المحاولة مرة أخرى من القائمة الرئيسية.", reply_markup=main_menu_kb())
        await callback.answer()
    except AiogramError as e:
        logger.error(f"Error in start_group_session for user {callback.from_user.id}: {e}")
        await callback.message.answer("حدث خطأ أثناء بدء جولة المجموعة. يرجى المحاولة مرة أخرى.")
        await callback.answer()
    except Exception as e:
        logger.error(f"Unexpected error in start_group_session for user {callback.from_user.id}: {e}")
        await callback.message.answer("حدث خطأ غير متوقع. يرجى إبلاغ المسؤول.")
        await callback.answer()

@dp.callback_query(F.data.startswith("cancel_group_session:"))
async def cancel_group_session(callback: CallbackQuery, state: FSMContext):
    """Cancels a group session."""
    try:
        session_id = callback.data.split(":")[1]
        session = db.get_session(session_id)

        if not session or session["owner_id"] != callback.from_user.id or session["status"] != "waiting":
            await callback.answer("❌ لا يمكنك إلغاء هذه الجولة.", show_alert=True)
            return

        db.finish_session(session_id) # Mark as finished/cancelled

        await callback.message.edit_text(
            f"❌ *تم إلغاء جولة المجموعة {session_id}.*\n\n"
            f"{welcome_text(callback.from_user.id, callback.from_user.first_name)}",
            parse_mode="Markdown",
            reply_markup=main_menu_kb()
        )
        await callback.answer()
    except TelegramBadRequest:
        logger.warning(f"TelegramBadRequest in cancel_group_session for user {callback.from_user.id}. Message might be too old or already modified.")
        await callback.message.answer("حدث خطأ في إلغاء الجولة. يرجى المحاولة مرة أخرى من القائمة الرئيسية.", reply_markup=main_menu_kb())
        await callback.answer()
    except AiogramError as e:
        logger.error(f"Error in cancel_group_session for user {callback.from_user.id}: {e}")
        await callback.message.answer("حدث خطأ أثناء إلغاء جولة المجموعة. يرجى المحاولة مرة أخرى.")
        await callback.answer()
    except Exception as e:
        logger.error(f"Unexpected error in cancel_group_session for user {callback.from_user.id}: {e}")
        await callback.message.answer("حدث خطأ غير متوقع. يرجى إبلاغ المسؤول.")
        await callback.answer()

@dp.callback_query(F.data.startswith("group_answer:"), QuizStates.in_quiz)
async def handle_group_answer(callback: CallbackQuery, state: FSMContext):
    """Handles a player\'s answer in a group quiz."""
    try:
        # Retrieve player-specific state for this session
        user_id = callback.from_user.id
        session_id, player_id_str, chosen_option_index_str = callback.data.split(":")[1:]
        player_id = int(player_id_str)
        chosen_option_index = int(chosen_option_index_str)

        if user_id != player_id:
            await callback.answer("هذه الإجابة ليست لك.", show_alert=True)
            return

        player_state_key = f"group_quiz_state_{session_id}"
        player_data = await dp.storage.get_data(bot=bot, user=user_id, key=player_state_key)

        if not player_data:
            await callback.answer("انتهت الجولة أو حدث خطأ. يرجى العودة للقائمة الرئيسية.", show_alert=True)
            await state.clear()
            await callback.message.answer(welcome_text(user_id, callback.from_user.first_name), parse_mode="Markdown", reply_markup=main_menu_kb())
            return

        questions = player_data["questions"]
        current_q_index = player_data["current_q_index"]
        correct_answers = player_data["correct_answers"]
        subject_key = player_data["subject"]
        start_time = player_data["start_time"]

        current_q = questions[current_q_index]
        is_correct = (chosen_option_index == current_q["answer"])

        feedback_text = "✅ إجابة صحيحة!" if is_correct else f"❌ إجابة خاطئة. الصحيح: {current_q[\'options\'][current_q[\'answer\']]}"
        if is_correct: correct_answers += 1

        current_q_index += 1

        if current_q_index < len(questions):
            next_q = questions[current_q_index]
            options_kb_markup = options_kb(next_q["options"], current_q_index, prefix=f"group_answer:{session_id}:{user_id}")
            await dp.storage.update_data(bot=bot, user=user_id, key=player_state_key, data={
                "current_q_index": current_q_index,
                "correct_answers": correct_answers
            })
            await callback.message.edit_text(
                f"{subj_info(subject_key)[0]} *جولة في {subj_info(subject_key)[0]}*\n\n"
                f"*السؤال {current_q_index + 1}/10:*\n{next_q[\'q\']}\n\n"
                f"_{feedback_text}_",
                parse_mode="Markdown",
                reply_markup=options_kb_markup
            )
            await callback.answer()
        else:
            end_time = datetime.now()
            duration = int((end_time - start_time).total_seconds())
            xp_earned = correct_answers * 10
            db.update_stats(user_id, xp_earned, correct_answers, len(questions), subject_key)
            db.update_session_score(session_id, user_id, correct_answers)

            final_message = (
                f"🎉 *انتهت جولتك في المجموعة!* 🎉\n"
                f"المادة: *{subj_info(subject_key)[0]}*\n"
                f"الأسئلة الصحيحة: *{correct_answers}/{len(questions)}*\n"
                f"نقاط الخبرة المكتسبة: *{xp_earned}* XP\n"
                f"الوقت المستغرق: *{duration} ثانية*\n\n"
                f"بانتظار بقية اللاعبين..."
            )

            await callback.message.edit_text(
                final_message,
                parse_mode="Markdown",
                reply_markup=back_home_kb()
            )
            await dp.storage.set_state(bot=bot, user=user_id, state=None) # Clear player state
            await callback.answer()

            finished_count, total_players = db.get_finished_count(session_id)
            if finished_count == total_players:
                # All players finished, announce results
                session_data = db.get_session(session_id)
                players_scores = db.get_session_players(session_id)
                leaderboard_text = "🏆 *نتائج جولة المجموعة!* 🏆\n\n"
                for i, p in enumerate(players_scores):
                    leaderboard_text += f"{i+1}. {p[\'user_name\]}: {p[\'score\]} إجابات صحيحة\n"
                leaderboard_text += f"\nالمادة: *{subj_info(subject_key)[0]}*\n"
                leaderboard_text += f"المنظم: *{session_data[\'owner_name\']}*\n"

                await bot.send_message(session_data["chat_id"], leaderboard_text, parse_mode="Markdown")
                db.finish_session(session_id)

    except TelegramBadRequest:
        logger.warning(f"TelegramBadRequest in handle_group_answer for user {callback.from_user.id}. Message might be too old or already modified.")
        await callback.message.answer("حدث خطأ في معالجة إجابتك في جولة المجموعة. يرجى العودة للقائمة الرئيسية.", reply_markup=main_menu_kb())
        await callback.answer()
    except AiogramError as e:
        logger.error(f"Error in handle_group_answer for user {callback.from_user.id}: {e}")
        await callback.message.answer("حدث خطأ أثناء معالجة إجابتك في جولة المجموعة. يرجى المحاولة مرة أخرى.")
        await callback.answer()
    except Exception as e:
        logger.error(f"Unexpected error in handle_group_answer for user {callback.from_user.id}: {e}")
        await callback.message.answer("حدث خطأ غير متوقع. يرجى إبلاغ المسؤول.")
        await callback.answer()

# ─── Leaderboard ──────────────────────────────────────────────
@dp.callback_query(F.data == "leaderboard")
async def show_leaderboard(callback: CallbackQuery):
    """Displays the global leaderboard."""
    try:
        leaderboard_data = db.get_leaderboard(10)
        if not leaderboard_data:
            await callback.message.edit_text("🏆 *المتصدرون*\n\nلا توجد بيانات للمتصدرين بعد.", parse_mode="Markdown", reply_markup=back_home_kb())
            await callback.answer()
            return

        leaderboard_text = "🏆 *المتصدرون* 🏆\n━━━━━━━━━━━━━━━\n"
        for i, user_data in enumerate(leaderboard_data):
            rank_icon = "🥇" if i == 0 else ("🥈" if i == 1 else ("🥉" if i == 2 else f"{i+1}. "))
            title_prefix = TITLES_SHOP[user_data["active_title"]]["prefix"] + " " if user_data["active_title"] else ""
            leaderboard_text += f"{rank_icon} {title_prefix}*{user_data[\'name\']}* - {user_data[\'xp\']} XP (سلسلة: {user_data[\'streak\]} يوم)\n"
        leaderboard_text += "━━━━━━━━━━━━━━━\n"

        await callback.message.edit_text(
            leaderboard_text,
            parse_mode="Markdown",
            reply_markup=back_home_kb()
        )
        await callback.answer()
    except TelegramBadRequest:
        logger.warning(f"TelegramBadRequest in show_leaderboard for user {callback.from_user.id}. Message might be too old or already modified.")
        await callback.message.answer("حدث خطأ في عرض لوحة المتصدرين. يرجى المحاولة مرة أخرى من القائمة الرئيسية.", reply_markup=main_menu_kb())
        await callback.answer()
    except AiogramError as e:
        logger.error(f"Error in show_leaderboard for user {callback.from_user.id}: {e}")
        await callback.message.answer("حدث خطأ أثناء عرض لوحة المتصدرين. يرجى المحاولة مرة أخرى.")
        await callback.answer()
    except Exception as e:
        logger.error(f"Unexpected error in show_leaderboard for user {callback.from_user.id}: {e}")
        await callback.message.answer("حدث خطأ غير متوقع. يرجى إبلاغ المسؤول.")
        await callback.answer()

# ─── My Stats ─────────────────────────────────────────────────
@dp.callback_query(F.data == "my_stats")
async def show_my_stats(callback: CallbackQuery):
    """Displays the user\'s personal statistics."""
    try:
        user_id = callback.from_user.id
        stats = db.get_user_stats(user_id)
        subject_stats = db.get_subject_stats(user_id)

        _, rank_icon, rank_label = get_rank(stats["xp"])
        cert = get_certificate(stats["total_games"])
        cert_line = f"🏅 {cert}\n" if cert else ""
        display_name = get_display_name(user_id, callback.from_user.full_name)

        stats_text = (
            f"📊 *إحصائيات {display_name}*\n"
            f"━━━━━━━━━━━━━━━\n"
            f"{cert_line}"
            f"{rank_icon} لقبك: *{rank_label}*\n"
            f"⚡ XP: *{stats[\'xp\']}*\n"
            f"🔥 السلسلة: *{stats[\'streak\']}* يوم\n"
            f"🎮 جولات: *{stats[\'total_games\']}*\n"
            f"\n*أداء المواد:*\n"
        )

        if not subject_stats:
            stats_text += "  _لم تلعب أي جولات بعد._\n"
        else:
            for subj_key, s_stats in subject_stats.items():
                subj_name, subj_icon = subj_info(subj_key)
                if s_stats["games"] > 0:
                    accuracy = (s_stats["correct"] / (s_stats["games"] * 10)) * 100
                    stats_text += f"  {subj_icon} *{subj_name}*: {s_stats[\'correct\]}/{s_stats[\'games\'] * 10} ({accuracy:.1f}%)\n"
                else:
                    stats_text += f"  {subj_icon} *{subj_name}*: لم تلعب بعد\n"

        await callback.message.edit_text(
            stats_text,
            parse_mode="Markdown",
            reply_markup=back_home_kb()
        )
        await callback.answer()
    except TelegramBadRequest:
        logger.warning(f"TelegramBadRequest in show_my_stats for user {callback.from_user.id}. Message might be too old or already modified.")
        await callback.message.answer("حدث خطأ في عرض إحصائياتك. يرجى المحاولة مرة أخرى من القائمة الرئيسية.", reply_markup=main_menu_kb())
        await callback.answer()
    except AiogramError as e:
        logger.error(f"Error in show_my_stats for user {callback.from_user.id}: {e}")
        await callback.message.answer("حدث خطأ أثناء عرض إحصائياتك. يرجى المحاولة مرة أخرى.")
        await callback.answer()
    except Exception as e:
        logger.error(f"Unexpected error in show_my_stats for user {callback.from_user.id}: {e}")
        await callback.message.answer("حدث خطأ غير متوقع. يرجى إبلاغ المسؤول.")
        await callback.answer()

# ─── Grade Prediction ─────────────────────────────────────────
@dp.callback_query(F.data == "grade_prediction_menu")
async def grade_prediction_menu(callback: CallbackQuery, state: FSMContext):
    """Displays the grade prediction menu."""
    try:
        await callback.message.edit_text(
            "🎯 *توقعات درجاتي*\nاختر الفرع الدراسي لعرض توقعاتك:",
            parse_mode="Markdown",
            reply_markup=branch_select_kb("predict_branch")
        )
        await callback.answer()
    except TelegramBadRequest:
        logger.warning(f"TelegramBadRequest in grade_prediction_menu for user {callback.from_user.id}. Message might be too old or already modified.")
        await callback.message.answer(
            "🎯 *توقعات درجاتي*\nاختر الفرع الدراسي لعرض توقعاتك:",
            parse_mode="Markdown",
            reply_markup=branch_select_kb("predict_branch")
        )
        await callback.answer()
    except AiogramError as e:
        logger.error(f"Error in grade_prediction_menu for user {callback.from_user.id}: {e}")
        await callback.message.answer("حدث خطأ أثناء عرض توقعات الدرجات. يرجى المحاولة مرة أخرى.")
        await callback.answer()
    except Exception as e:
        logger.error(f"Unexpected error in grade_prediction_menu for user {callback.from_user.id}: {e}")
        await callback.message.answer("حدث خطأ غير متوقع. يرجى إبلاغ المسؤول.")
        await callback.answer()

@dp.callback_query(F.data.startswith("predict_branch:"))
async def show_grade_prediction(callback: CallbackQuery, state: FSMContext):
    """Displays grade predictions for the selected branch."""
    try:
        branch_key = callback.data.split(":")[1]
        user_id = callback.from_user.id
        subject_stats = db.get_subject_stats(user_id)

        prediction_text = calc_grade_prediction(subject_stats, branch_key)

        await callback.message.edit_text(
            prediction_text,
            parse_mode="Markdown",
            reply_markup=back_home_kb()
        )
        await callback.answer()
    except TelegramBadRequest:
        logger.warning(f"TelegramBadRequest in show_grade_prediction for user {callback.from_user.id}. Message might be too old or already modified.")
        await callback.message.answer("حدث خطأ في عرض توقعات الدرجات. يرجى المحاولة مرة أخرى من القائمة الرئيسية.", reply_markup=main_menu_kb())
        await callback.answer()
    except AiogramError as e:
        logger.error(f"Error in show_grade_prediction for user {callback.from_user.id}: {e}")
        await callback.message.answer("حدث خطأ أثناء عرض توقعات الدرجات. يرجى المحاولة مرة أخرى.")
        await callback.answer()
    except Exception as e:
        logger.error(f"Unexpected error in show_grade_prediction for user {callback.from_user.id}: {e}")
        await callback.message.answer("حدث خطأ غير متوقع. يرجى إبلاغ المسؤول.")
        await callback.answer()

# ─── Titles Shop ──────────────────────────────────────────────
@dp.callback_query(F.data == "titles_shop")
async def titles_shop_menu(callback: CallbackQuery):
    """Displays the titles shop menu."""
    try:
        user_id = callback.from_user.id
        stats = db.get_user_stats(user_id)
        user_xp = stats["xp"]
        earned_titles = db.get_user_earned_titles(user_id)
        active_title = stats["active_title"]
        title_announce = stats["title_announce"]

        shop_text = "🏅 *متجر الألقاب* 🏅\n\n"
        shop_text += f"⚡ نقاط خبرتك: *{user_xp}* XP\n\n"
        shop_text += "*الألقاب المتاحة للشراء:*\n"

        kb = InlineKeyboardBuilder()
        for key, title in TITLES_SHOP.items():
            status = ""
            if key == active_title:
                status = " (مفعل)"
            elif key in earned_titles:
                status = " (مكتسب)"
            
            if key in earned_titles:
                kb.button(text=f"{title[\'icon\']} {title[\'name\]}{status}", callback_data=f"select_title:{key}")
            else:
                if user_xp >= title["cost"]:
                    kb.button(text=f"{title[\'icon\']} {title[\'name\]} - {title[\'cost\]} XP", callback_data=f"buy_title:{key}")
                else:
                    kb.button(text=f"🔒 {title[\'icon\']} {title[\'name\]} - {title[\'cost\]} XP", callback_data="ignore")
        
        kb.adjust(2)

        # Toggle title announcement
        announce_button_text = "🔔 إخفاء اللقب في الاسم" if title_announce else "🔕 إظهار اللقب في الاسم"
        kb.button(text=announce_button_text, callback_data=f"toggle_title_announce:{1 if title_announce else 0}")
        kb.button(text="← رجوع", callback_data="back_home")
        kb.adjust(1, 1)

        await callback.message.edit_text(
            shop_text,
            parse_mode="Markdown",
            reply_markup=kb.as_markup()
        )
        await callback.answer()
    except TelegramBadRequest:
        logger.warning(f"TelegramBadRequest in titles_shop_menu for user {callback.from_user.id}. Message might be too old or already modified.")
        await callback.message.answer("حدث خطأ في عرض متجر الألقاب. يرجى المحاولة مرة أخرى من القائمة الرئيسية.", reply_markup=main_menu_kb())
        await callback.answer()
    except AiogramError as e:
        logger.error(f"Error in titles_shop_menu for user {callback.from_user.id}: {e}")
        await callback.message.answer("حدث خطأ أثناء عرض متجر الألقاب. يرجى المحاولة مرة أخرى.")
        await callback.answer()
    except Exception as e:
        logger.error(f"Unexpected error in titles_shop_menu for user {callback.from_user.id}: {e}")
        await callback.message.answer("حدث خطأ غير متوقع. يرجى إبلاغ المسؤول.")
        await callback.answer()

@dp.callback_query(F.data.startswith("buy_title:"))
async def buy_title(callback: CallbackQuery):
    """Handles buying a title from the shop."""
    try:
        title_key = callback.data.split(":")[1]
        user_id = callback.from_user.id
        stats = db.get_user_stats(user_id)
        user_xp = stats["xp"]

        if title_key not in TITLES_SHOP:
            await callback.answer("لقب غير صالح.", show_alert=True)
            return

        title_cost = TITLES_SHOP[title_key]["cost"]
        if user_xp < title_cost:
            await callback.answer("نقاط الخبرة لديك غير كافية لشراء هذا اللقب.", show_alert=True)
            return

        # Deduct XP and earn title
        conn = db.get_conn()
        if conn is None: return
        try:
            conn.execute("UPDATE users SET xp=xp-? WHERE user_id=?", (title_cost, user_id))
            db.earn_title(user_id, title_key)
            conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Error buying title {title_key} for user {user_id}: {e}")
            await callback.answer("حدث خطأ أثناء شراء اللقب. يرجى المحاولة مرة أخرى.", show_alert=True)
            return
        finally:
            if conn: conn.close()

        await callback.answer(f"✅ تم شراء لقب {TITLES_SHOP[title_key][\'name\']} بنجاح!", show_alert=True)
        await titles_shop_menu(callback) # Refresh shop menu
    except AiogramError as e:
        logger.error(f"Error in buy_title for user {callback.from_user.id}: {e}")
        await callback.message.answer("حدث خطأ أثناء شراء اللقب. يرجى المحاولة مرة أخرى.")
        await callback.answer()
    except Exception as e:
        logger.error(f"Unexpected error in buy_title for user {callback.from_user.id}: {e}")
        await callback.message.answer("حدث خطأ غير متوقع. يرجى إبلاغ المسؤول.")
        await callback.answer()

@dp.callback_query(F.data.startswith("select_title:"))
async def select_title(callback: CallbackQuery):
    """Handles selecting an earned title to be active."""
    try:
        title_key = callback.data.split(":")[1]
        user_id = callback.from_user.id
        earned_titles = db.get_user_earned_titles(user_id)

        if title_key not in earned_titles:
            await callback.answer("❌ لم تكسب هذا اللقب بعد.", show_alert=True)
            return

        db.set_active_title(user_id, title_key)
        await callback.answer(f"✅ تم تفعيل لقب {TITLES_SHOP[title_key][\'name\']}!", show_alert=True)
        await titles_shop_menu(callback) # Refresh shop menu
    except AiogramError as e:
        logger.error(f"Error in select_title for user {callback.from_user.id}: {e}")
        await callback.message.answer("حدث خطأ أثناء تفعيل اللقب. يرجى المحاولة مرة أخرى.")
        await callback.answer()
    except Exception as e:
        logger.error(f"Unexpected error in select_title for user {callback.from_user.id}: {e}")
        await callback.message.answer("حدث خطأ غير متوقع. يرجى إبلاغ المسؤول.")
        await callback.answer()

@dp.callback_query(F.data.startswith("toggle_title_announce:"))
async def toggle_title_announce(callback: CallbackQuery):
    """Toggles whether the active title should be announced in the display name."""
    try:
        current_status = int(callback.data.split(":")[1])
        new_status = 0 if current_status == 1 else 1
        user_id = callback.from_user.id

        db.set_title_announce(user_id, new_status)
        await callback.answer("✅ تم تحديث إعدادات عرض اللقب.", show_alert=True)
        await titles_shop_menu(callback) # Refresh shop menu
    except AiogramError as e:
        logger.error(f"Error in toggle_title_announce for user {callback.from_user.id}: {e}")
        await callback.message.answer("حدث خطأ أثناء تحديث إعدادات اللقب. يرجى المحاولة مرة أخرى.")
        await callback.answer()
    except Exception as e:
        logger.error(f"Unexpected error in toggle_title_announce for user {callback.from_user.id}: {e}")
        await callback.message.answer("حدث خطأ غير متوقع. يرجى إبلاغ المسؤول.")
        await callback.answer()

@dp.callback_query(F.data == "ignore")
async def ignore_callback(callback: CallbackQuery):
    """Ignores a callback query, typically for disabled buttons."""
    try:
        await callback.answer()
    except AiogramError as e:
        logger.error(f"Error ignoring callback for user {callback.from_user.id}: {e}")
    except Exception as e:
        logger.error(f"Unexpected error ignoring callback for user {callback.from_user.id}: {e}")

# ─── Reminders ────────────────────────────────────────────────
@dp.callback_query(F.data == "reminder_menu")
async def reminder_menu(callback: CallbackQuery):
    """Displays the reminder settings menu."""
    try:
        user_id = callback.from_user.id
        stats = db.get_user_stats(user_id)
        reminders_on = stats["reminders_on"]
        reminder_time = stats["reminder_time"]

        menu_text = "📅 *تذكير يومي*\n\n"
        menu_text += f"حالة التذكيرات: {'مفعلة' if reminders_on else 'معطلة'}\n"
        if reminders_on:
            menu_text += f"وقت التذكير: *{reminder_time}*\n\n"
            menu_text += "يمكنك إيقاف التذكيرات أو تغيير وقتها."
        else:
            menu_text += "يمكنك تفعيل التذكيرات لتصلك أسئلة يومية."

        kb = InlineKeyboardBuilder()
        if reminders_on:
            kb.button(text="❌ إيقاف التذكيرات", callback_data="toggle_reminders:0")
            kb.button(text="⏰ تغيير وقت التذكير", callback_data="set_reminder_time")
            kb.adjust(1)
        else:
            kb.button(text="✅ تفعيل التذكيرات", callback_data="toggle_reminders:1")
        kb.button(text="← رجوع", callback_data="back_home")
        kb.adjust(1)

        await callback.message.edit_text(
            menu_text,
            parse_mode="Markdown",
            reply_markup=kb.as_markup()
        )
        await callback.answer()
    except TelegramBadRequest:
        logger.warning(f"TelegramBadRequest in reminder_menu for user {callback.from_user.id}. Message might be too old or already modified.")
        await callback.message.answer("حدث خطأ في عرض قائمة التذكيرات. يرجى المحاولة مرة أخرى من القائمة الرئيسية.", reply_markup=main_menu_kb())
        await callback.answer()
    except AiogramError as e:
        logger.error(f"Error in reminder_menu for user {callback.from_user.id}: {e}")
        await callback.message.answer("حدث خطأ أثناء عرض قائمة التذكيرات. يرجى المحاولة مرة أخرى.")
        await callback.answer()
    except Exception as e:
        logger.error(f"Unexpected error in reminder_menu for user {callback.from_user.id}: {e}")
        await callback.message.answer("حدث خطأ غير متوقع. يرجى إبلاغ المسؤول.")
        await callback.answer()

@dp.callback_query(F.data.startswith("toggle_reminders:"))
async def toggle_reminders(callback: CallbackQuery):
    """Toggles daily reminders on or off."""
    try:
        status = int(callback.data.split(":")[1])
        user_id = callback.from_user.id

        db.set_reminder(user_id, status)
        await callback.answer(f"✅ تم {'تفعيل' if status else 'إيقاف'} التذكيرات بنجاح!", show_alert=True)
        await reminder_menu(callback) # Refresh menu
    except AiogramError as e:
        logger.error(f"Error in toggle_reminders for user {callback.from_user.id}: {e}")
        await callback.message.answer("حدث خطأ أثناء تحديث التذكيرات. يرجى المحاولة مرة أخرى.")
        await callback.answer()
    except Exception as e:
        logger.error(f"Unexpected error in toggle_reminders for user {callback.from_user.id}: {e}")
        await callback.message.answer("حدث خطأ غير متوقع. يرجى إبلاغ المسؤول.")
        await callback.answer()

@dp.callback_query(F.data == "set_reminder_time")
async def set_reminder_time_prompt(callback: CallbackQuery, state: FSMContext):
    """Prompts the user to set a new reminder time."""
    try:
        await state.set_state(QuizStates.choosing_subject) # Use a generic state for waiting for text input
        await state.update_data(waiting_for_reminder_time=True)
        await callback.message.edit_text(
            "⏰ *تغيير وقت التذكير*\nالرجاء إرسال الوقت الجديد بصيغة HH:MM (مثال: 14:30):",
            parse_mode="Markdown",
            reply_markup=back_home_kb()
        )
        await callback.answer()
    except TelegramBadRequest:
        logger.warning(f"TelegramBadRequest in set_reminder_time_prompt for user {callback.from_user.id}. Message might be too old or already modified.")
        await callback.message.answer("حدث خطأ في طلب تغيير وقت التذكير. يرجى المحاولة مرة أخرى من القائمة الرئيسية.", reply_markup=main_menu_kb())
        await callback.answer()
    except AiogramError as e:
        logger.error(f"Error in set_reminder_time_prompt for user {callback.from_user.id}: {e}")
        await callback.message.answer("حدث خطأ أثناء طلب تغيير وقت التذكير. يرجى المحاولة مرة أخرى.")
        await callback.answer()
    except Exception as e:
        logger.error(f"Unexpected error in set_reminder_time_prompt for user {callback.from_user.id}: {e}")
        await callback.message.answer("حدث خطأ غير متوقع. يرجى إبلاغ المسؤول.")
        await callback.answer()

@dp.message(QuizStates.choosing_subject, F.text)
async def process_reminder_time(message: Message, state: FSMContext):
    """Processes the new reminder time provided by the user."""
    try:
        user_data = await state.get_data()
        if not user_data.get("waiting_for_reminder_time"):
            # This message is not for setting reminder time, ignore or handle as general text
            return

        time_str = message.text.strip()
        try:
            datetime.strptime(time_str, "%H:%M").time()
        except ValueError:
            await message.answer("❌ صيغة الوقت غير صحيحة. يرجى إرسال الوقت بصيغة HH:MM (مثال: 14:30).", reply_markup=back_home_kb())
            return

        db.set_reminder(message.from_user.id, 1, time_str)
        await state.update_data(waiting_for_reminder_time=False) # Reset flag
        await message.answer(f"✅ تم تحديث وقت التذكير إلى *{time_str}* بنجاح!", parse_mode="Markdown", reply_markup=main_menu_kb())
        await state.set_state(QuizStates.choosing_subject) # Return to a neutral state
    except AiogramError as e:
        logger.error(f"Error in process_reminder_time for user {message.from_user.id}: {e}")
        await message.answer("حدث خطأ أثناء تحديث وقت التذكير. يرجى المحاولة مرة أخرى.")
    except Exception as e:
        logger.error(f"Unexpected error in process_reminder_time for user {message.from_user.id}: {e}")
        await message.answer("حدث خطأ غير متوقع. يرجى إبلاغ المسؤول.")

# ─── Weekly Report ────────────────────────────────────────────
@dp.callback_query(F.data == "weekly_report")
async def show_weekly_report(callback: CallbackQuery):
    """Displays the user\'s weekly report."""
    try:
        user_id = callback.from_user.id
        report = db.get_weekly_report(user_id)

        report_text = "📈 *تقريرك الأسبوعي* 📈\n━━━━━━━━━━━━━━━\n"
        if report["games"] == 0:
            report_text += "_لم تلعب أي جولات هذا الأسبوع بعد._\n"
        else:
            accuracy = (report["correct"] / (report["games"] * 10)) * 100 if report["games"] > 0 else 0
            report_text += f"🎮 جولات هذا الأسبوع: *{report[\'games\']}*\n"
            report_text += f"✅ إجابات صحيحة: *{report[\'correct\']}*\n"
            report_text += f"⚡ XP مكتسبة: *{report[\'xp\']}*\n"
            report_text += f"🎯 دقة الإجابات: *{accuracy:.1f}%*\n"
        report_text += "━━━━━━━━━━━━━━━\n"

        await callback.message.edit_text(
            report_text,
            parse_mode="Markdown",
            reply_markup=back_home_kb()
        )
        await callback.answer()
    except TelegramBadRequest:
        logger.warning(f"TelegramBadRequest in show_weekly_report for user {callback.from_user.id}. Message might be too old or already modified.")
        await callback.message.answer("حدث خطأ في عرض تقريرك الأسبوعي. يرجى المحاولة مرة أخرى من القائمة الرئيسية.", reply_markup=main_menu_kb())
        await callback.answer()
    except AiogramError as e:
        logger.error(f"Error in show_weekly_report for user {callback.from_user.id}: {e}")
        await callback.message.answer("حدث خطأ أثناء عرض تقريرك الأسبوعي. يرجى المحاولة مرة أخرى.")
        await callback.answer()
    except Exception as e:
        logger.error(f"Unexpected error in show_weekly_report for user {callback.from_user.id}: {e}")
        await callback.message.answer("حدث خطأ غير متوقع. يرجى إبلاغ المسؤول.")
        await callback.answer()


async def main():
    """Main function to initialize database and start bot polling."""
    db.init_db()
    # Schedule daily cleanup for old challenges and sessions
    # In a real-world scenario, this would be handled by a separate scheduler (e.g., APScheduler)
    # For simplicity, we'll just call it once at startup.
    db.cleanup_old_challenges()
    db.cleanup_old_sessions()

    # Reminder scheduling - this is a simplified approach.
    # A more robust solution would involve a dedicated scheduler like APScheduler.
    async def send_reminders():
        while True:
            now = datetime.now().strftime("%H:%M")
            users_to_remind = db.get_reminder_users()
            for user in users_to_remind:
                if user["reminder_time"] == now:
                    try:
                        await bot.send_message(user["user_id"], "🔔 حان وقت مراجعة دروسك مع المثابر الوزاري!\nاختر مادتك المفضلة وابدأ جولة جديدة.", reply_markup=main_menu_kb())
                        logger.info(f"Sent reminder to user {user[\'user_id\']}")
                    except TelegramBadRequest as e:
                        logger.warning(f"Could not send reminder to user {user[\'user_id\']}: {e}")
                    except AiogramError as e:
                        logger.error(f"Error sending reminder to user {user[\'user_id\']}: {e}")
                    except Exception as e:
                        logger.error(f"Unexpected error sending reminder to user {user[\'user_id\']}: {e}")
            await asyncio.sleep(60) # Check every minute

    # Start reminder task in the background
    asyncio.create_task(send_reminders())

    try:
        await dp.start_polling(bot)
    except AiogramError as e:
        logger.critical(f"Error starting bot polling: {e}")
    except Exception as e:
        logger.critical(f"Unexpected error during bot polling: {e}")

if __name__ == "__main__":
    asyncio.run(main())
