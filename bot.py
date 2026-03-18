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
choosing_subject = State()
in_quiz = State()
study_mode = State()
challenge_wait = State()
challenge_gender = State()
# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────
TITLES = [
(0, " ", "مبتدئ"),
(100, " ", "متعلم"),
(300, " ", "متقدم"),
(600, " ", "محترف"),
(1000, " ", "خبﯿر"),
(2000, " ", "أسطورة"),
]
CERTIFICATES = {
5: "شﮭادة المثابر البرونزﯾة ",
15: "شﮭادة المثابر الفضﯿة ",
30: "شﮭادة المثابر الذھبﯿة ",
50: "شﮭادة المثابر الماسﯿة ",
100: "شﮭادة أسطورة المثابر ",
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
# 15 ﺲﻨﺠﻟاو ﺖﻗﻮﻟا ﺐﺴﺣ ناﻮﻟأ — ةﺮﯿﻐﺻ ةﺮﺋاد
if gender == "female":
full = " " # تﺎﻨﺒﻠﻟ ﻲﺠﺴﻔﻨﺑ/يدرو
mid = " "
low = " "
else:
full = " "
mid = " "
low = " "
char = full if t > 10 else (mid if t > 5 else low)
filled = t
empty = total - t
return char * filled + " " * empty + f"ث}t{ "
def progress_bar(cur, total):
f = int((cur / total) * 10)
return "▓" * f + "░" * (10 - f)
def subj_info(key):
if key == "all":
return "كل المواد", " "
s = SUBJECTS.get(key, {})
return s.get("name", ""), s.get("icon", " ")
def pick_questions(key, n=10):
if key == "all":
pool = [{**q, "_subject": k} for k, qs in QUESTION_BANK.items() for q in qs]
else:
pool = QUESTION_BANK.get(key, [])
selected = random.sample(pool, min(n, len(pool)))
# لاﺆﺳ ﻞﻜﻟ ًﺎﯿﺋاﻮﺸﻋ تارﺎﯿﺨﻟا ﺐﯿﺗﺮﺗ ﻂﻠﺧ
return [shuffle_options(q) for q in selected]
def shuffle_options(q: dict) -> dict:
"""ﯾخلط ترتﯿب الخﯿارات وﯾحّدث رقم اإلجابة الصحﯿحة تلقائﯿاً"""
options = list(q["options"])
correct_text = options[q["answer"]] # ﺔﺤﯿﺤﺼﻟا ﺔﺑﺎﺟﻹا ﺺﻧ ﻆﻔﺤﻧ
# تارﺎﯿﺨﻟا ﻂﻠﺨﻧ
indices = list(range(len(options)))
random.shuffle(indices)
new_options = [options[i] for i in indices]
new_answer = new_options.index(correct_text) # ﺪﯾﺪﺠﻟا ﺔﺤﯿﺤﺼﻟا ﺔﺑﺎﺟﻹا ﻊﺿﻮﻣ دﺪﺤﻧ
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
status = ("ممتاز " if pct >= 90 else "جﯿد جداً " if pct >= 75 else
"جﯿد " if pct >= 60 else "مقبول " if pct >= 50 else "ﯾحتاج مراجعة ")
bar = "▓" * int(pct // 10) + "░" * (10 - int(pct // 10))
lines.append(
f"{subj['icon']} *{subj['name']}*\n"
f" `{bar}` {int(pct)}%\n"
f"n\}sutats{ — *}edarg_xam{/}detciderp{* :التوقع "
)
total_weighted += predicted
total_max += max_grade
else:
lines.append(f"n\لم تراجع بعد n\*}]'eman'[jbus{* }]'noci'[jbus{")
total_max += max_grade
overall = round((total_weighted / total_max) * 100) if total_max > 0 else 0
overall_label = (
"!ممتاز — أنت في المسار الصحﯿح " if overall >= 85 else
"!جﯿد جداً — استمر بالمراجعة " if overall >= 70 else
"!جﯿد — زد من جوالتك " if overall >= 55 else
"تحتاج مراجعة أكثر " if overall > 0 else
"!العب جوالت أوالً لترى توقعاتك"
)
branch_name = BRANCHES[branch]["name"] if branch and branch in BRANCHES else "كل المواد"
return (
f"n\*}eman_hcnarb{ — توقعات درجاتي* "
f"━━━━━━━━━━━━━━━\n\n"
+ "\n".join(lines) +
f"\n━━━━━━━━━━━━━━━\n"
f"n\*%}llarevo{* :المعدل التقدﯾري "
f"{overall_label}\n\n"
f"_توقعات تقرﯾبﯿة بناًء على أدائك في البوت _"
)
# ─────────────────────────────────────────────
# Keyboards
# ─────────────────────────────────────────────
def main_menu_kb():
b = InlineKeyboardBuilder()
# 1 ﻒﺻ
b.button(text="اختبر نفسك ", callback_data="quiz_menu")
# 2 ﻒﺻ
b.button(text="اختبار مشترك ", callback_data="group_menu")
b.button(text="تحدي صدﯾق ", callback_data="challenge_menu")
# 3 ﻒﺻ
b.button(text="مراجعة أخطائي ", callback_data="wrong_answers_menu")
b.button(text="توقع درجتي ", callback_data="grade_prediction_menu")
# 4 ﻒﺻ
b.button(text="تذكﯿر ﯾومي ", callback_data="reminder_menu")
b.button(text="إحصائﯿاتي ", callback_data="my_stats")
# 5 ﻒﺻ
b.button(text="المتصدرون ", callback_data="leaderboard")
b.button(text="شراء لقب ", callback_data="buy_title")
# 6 ﻒﺻ
b.button(text="اإلعدادات ", callback_data="settings")
b.adjust(1, 2, 2, 2, 2, 1)
return b.as_markup()
def branch_select_kb(prefix="branch"):
b = InlineKeyboardBuilder()
for key, branch in BRANCHES.items():
b.button(text=f"{branch['icon']} {branch['name']}", callback_data=f"{prefix}:{key}")
b.button(text="كل الفروع ", callback_data=f"{prefix}:all")
b.button(text="رجوع ←", callback_data="back_home")
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
b.button(text="كل مواد الفرع ", callback_data=f"{prefix}:branch_{branch_key}")
b.button(text="رجوع ←", callback_data="subjects_menu")
b.adjust(2)
return b.as_markup()
def back_home_kb():
b = InlineKeyboardBuilder()
b.button(text="القائمة الرئﯿسﯿة ←", callback_data="back_home")
return b.as_markup()
def options_kb(options, q_index, prefix="answer"):
b = InlineKeyboardBuilder()
labels = ["د" ,"ج" ,"ب" ,"أ"]
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
cert_line = f" {cert}\n" if cert else ""
return (
f"n\n\!}eman_tsrif{ أھالً "
f"n\*المثابر الوزاري* "
f"━━━━━━━━━━━━━━━\n"
f"{cert_line}"
f"n\*}lebal{* :لقبك }noci{"
f" XP: *{stats['xp']}*\n"
f"n\ﯾوم *}]'kaerts'[stats{* :السلسلة "
f"n\n\*}]'semag_latot'[stats{* :جوالت "
f" اختر ما ترﯾد"
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
b.button(text="قبول ", callback_data=f"accept_challenge:{pending['id']}")
b.button(text="رفض ", callback_data="back_home")
b.adjust(2)
await message.answer(
f"ھل تقبل؟n\*}ns{* }is{n\*!تحدي جدﯾد* ",
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
# ةﺪﯾﺪﺠﻟا ﺔﻤﺋﺎﻘﻟا — ﻚﺴﻔﻧ ﺮﺒﺘﺧا
# ─────────────────────────────────────────────
@dp.callback_query(F.data == "quiz_menu")
async def quiz_menu(callback: CallbackQuery):
b = InlineKeyboardBuilder()
b.button(text="اختبار سرﯾع ", callback_data="quiz_type:quick")
b.button(text="مراجعة ھادئة ", callback_data="quiz_type:study")
b.button(text="رجوع ←", callback_data="back_home")
b.adjust(2, 1)
await callback.message.edit_text(
"شلون ترﯾد تراجع؟n\n\*اختبر نفسك* ",
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
b.button(text="رجوع ←", callback_data="quiz_menu")
b.adjust(1)
await callback.message.edit_text(
":اختر فرعك الدراسي ",
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
b.button(text="كل المواد ", callback_data=f"{prefix}:branch_{branch_key}")
b.button(text="رجوع ←", callback_data=f"quiz_type:{qtype}")
b.adjust(2)
branch_name = BRANCHES[branch_key]["name"] if branch_key in BRANCHES else "كل الفروع"
await callback.message.edit_text(
f":اختر مادة االختبارn\n\*}eman_hcnarb{* ",
parse_mode="Markdown", reply_markup=b.as_markup()
)
await callback.answer()
# ─────────────────────────────────────────────
# Subjects Menu (legacy — kept for compatibility)
# ─────────────────────────────────────────────
@dp.callback_query(F.data == "subjects_menu")
async def subjects_menu(callback: CallbackQuery):
await callback.message.edit_text(
":أوالً اختر فرعك الدراسيn\n\*اختر المادة* ",
parse_mode="Markdown",
reply_markup=branch_select_kb("pick_branch")
)
await callback.answer()
@dp.callback_query(F.data == "study_mode_menu")
async def study_mode_menu(callback: CallbackQuery):
await callback.message.edit_text(
":اختر فرعك الدراسيn\n\*وضع الدراسة* ",
parse_mode="Markdown",
reply_markup=branch_select_kb("study_branch")
)
await callback.answer()
@dp.callback_query(F.data.startswith("pick_branch:"))
async def pick_branch(callback: CallbackQuery):
branch_key = callback.data.split(":")[1]
branch_name = BRANCHES[branch_key]["name"] if branch_key != "all" else "كل الفروع"
branch_icon = BRANCHES[branch_key]["icon"] if branch_key != "all" else " "
await callback.message.edit_text(
f":اختر المادةn\n\*}eman_hcnarb{* }noci_hcnarb{",
parse_mode="Markdown",
reply_markup=subjects_for_branch_kb(branch_key, "subject")
)
await callback.answer()
@dp.callback_query(F.data.startswith("study_branch:"))
async def study_branch(callback: CallbackQuery):
branch_key = callback.data.split(":")[1]
branch_name = BRANCHES[branch_key]["name"] if branch_key != "all" else "كل الفروع"
branch_icon = BRANCHES[branch_key]["icon"] if branch_key != "all" else " "
await callback.message.edit_text(
f":اختر المادةn\n\*}eman_hcnarb{* }noci_hcnarb{",
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
b.button(text="قواعد ", callback_data="subject:arabic_grammar")
b.button(text="أدب ", callback_data="subject:arabic_literature")
b.button(text="رجوع ←", callback_data="subjects_menu")
b.adjust(2, 1)
await callback.message.edit_text("ماذا ترﯾد أن تختبر؟n\n\*العربي* ", parse_mode="Markdown", reply_markup=b.as_markup())
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
f" ...جاري تحضﯿر األسئلةn\n\*}ns{* }is{", parse_mode="Markdown"
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
f" *{q['q']}*\n\n"
f" {timer_bar(t, gender=gender)}"
)
async def show_answer_and_next(chat_id, state: FSMContext, q, cur, total, key, msg_id, timeout=False):
"""عرض اإلجابة الصحﯿحة ثم االنتقال للسؤال التالي"""
sn, si = subj_info(key if not key.startswith("branch_") else "all")
labels = ["د" ,"ج" ,"ب" ,"أ"]
correct_label = f"{labels[q['answer']]}) {q['options'][q['answer']]}"
if timeout:
header = "*!انتﮭى الوقت* "
else:
header = "*!انتﮭى السؤال* "
try:
await bot.edit_message_text(
chat_id=chat_id, message_id=msg_id,
text=(
f"{si} *{sn}* | {cur+1}/{total}\n"
f"`{progress_bar(cur+1, total)}`\n\n"
f" *{q['q']}*\n\n"
f"{header}\n"
f"n\n\*}lebal_tcerroc{* :اإلجابة الصحﯿحة "
f"...التالي خالل ثانﯿتﯿن"
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
if t == 0:
await state.update_data(timer_running=False)
answers = data.get("answers", [])
answers.append({"q": q["q"], "options": q["options"], "correct": q["answer"], "chosen": -1})
await state.update_data(current=cur+1, answers=answers)
await show_answer_and_next(chat_id, state, q, cur, total, key, msg_id, timeout=True)
@dp.callback_query(F.data.startswith("answer:"), QuizStates.in_quiz)
async def handle_answer(callback: CallbackQuery, state: FSMContext):
parts = callback.data.split(":")
q_idx, chosen = int(parts[1]), int(parts[2])
data = await state.get_data()
if not data.get("timer_running") or data.get("current") != q_idx:
await callback.answer()
return
await state.update_data(timer_running=False)
chat_id = callback.message.chat.id
msg_id = data["quiz_msg_id"]
qs, score, answers, key = data["questions"], data["score"], data.get("answers", []), data["subject"]
q = qs[q_idx]
correct = chosen == q["answer"]
if correct:
score += 1
answers.append({"q": q["q"], "options": q["options"], "correct": q["answer"], "chosen": chosen})
await state.update_data(current=q_idx+1, score=score, answers=answers)
sn, si = subj_info(key if not key.startswith("branch_") else "all")
labels = ["د" ,"ج" ,"ب" ,"أ"]
correct_label = f"{labels[q['answer']]}) {q['options'][q['answer']]}"
total = len(qs)
if correct:
result_text = f"*}lebal_tcerroc{* :اإلجابة n\PX إجابة صحﯿحة!* +01* "
else:
chosen_label = f"{labels[chosen]}) {q['options'][chosen]}"
result_text = f"*}lebal_tcerroc{* :الصحﯿحة n\}lebal_nesohc{ :إجابتكn\*!إجابة خاطئة* "
try:
await bot.edit_message_text(
chat_id=chat_id, message_id=msg_id,
text=(
f"{si} *{sn}* | {q_idx+1}/{total}\n"
f"`{progress_bar(q_idx+1, total)}`\n\n"
f" *{q['q']}*\n\n"
f"{result_text}\n\n"
f"...التالي خالل ثانﯿتﯿن"
),
parse_mode="Markdown"
)
except TelegramBadRequest:
pass
await callback.answer("!صحﯿح " if correct else "!خطأ ")
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
grade = ("ممتاز " if pct>=90 else "جﯿد جداً " if pct>=70 else
"جﯿد " if pct>=50 else "تحتاج مراجعة ")
if mode == "quiz":
actual = key if not key.startswith("branch_") and key != "all" else "mixed"
db.update_stats(chat_id, xp, score, total, actual)
stats = db.get_user_stats(chat_id)
_, icon, label = get_title(stats["xp"])
cert = get_certificate(stats["total_games"])
cert_line = f"n\*}trec{* :حصلت على " if cert and mode == "quiz" else ""
cid = data.get("challenge_id")
is_ch = data.get("is_challenger", False)
if cid:
db.update_challenge_score(cid, is_ch, score)
challenge = db.get_challenge(cid)
if challenge and challenge["status"] == "finished":
c_s, o_s = challenge["challenger_score"], challenge["opponent_score"]
res = "!تعادل " if c_s == o_s else ("!فزت " if (is_ch and c_s > o_s) or (not is_ch and o_s > c_s) else "!خسرت ")
try:
await bot.edit_message_text(chat_id=chat_id, message_id=msg_id,
text=f"}ser{n\n\01/}s_o{ :المنافسn\01/}s_c{ :المتحديn\━━━━━━━━━━━━━━━n\*نتﯿجة التحدي* ",
parse_mode="Markdown", reply_markup=back_home_kb())
except TelegramBadRequest:
pass
await state.clear()
return
sn, si = subj_info(key if not key.startswith("branch_") else "all")
b = InlineKeyboardBuilder()
b.button(text="مراجعة اإلجابات ", callback_data=f"review:0:{key}")
b.button(text="جولة جدﯾدة ", callback_data=f"subject:{key}")
b.button(text="تغﯿﯿر المادة ", callback_data="subjects_menu")
b.button(text="توقعات درجاتي ", callback_data="grade_prediction_menu")
b.adjust(1, 2, 1)
try:
await bot.edit_message_text(chat_id=chat_id, message_id=msg_id,
text=(f"n\━━━━━━━━━━━━━━━n\*}ns{* }is{n\n\*!انتﮭت الجولة* "
f"n\*%}tcp{* :النسبة n\*}latot{/}erocs{* :صحﯿح "
f" XP: *+{xp}*\n━━━━━━━━━━━━━━━\n"
f"}enil_trec{n\*}edarg{* :التقﯿﯿم "
f"n\ﯾوم }]'kaerts'[stats{ :السلسلة n\}lebal{ :لقبك }noci{"
f"}]'px'[stats{ :PX إجمالي "),
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
b.button(text="قواعد ", callback_data="study:arabic_grammar")
b.button(text="أدب ", callback_data="study:arabic_literature")
b.button(text="رجوع ←", callback_data="study_mode_menu")
b.adjust(2, 1)
await callback.message.edit_text("ماذا ترﯾد أن تدرس؟n\n\*العربي* ", parse_mode="Markdown", reply_markup=b.as_markup())
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
await callback.message.edit_text(" وضع الدراسة* — خذ وقتك* ", parse_mode="Markdown")
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
labels = ["د" ,"ج" ,"ب" ,"أ"]
b.button(text=f"{labels[i]}) {opt}", callback_data=f"study_ans:{cur}:{i}")
b.adjust(1)
await message.answer(
f"{si} *{sn}* | {cur+1}/{total}\n`{progress_bar(cur, total)}`\n\n *{q['q']}*",
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
feedback = "*!صحﯿح* " if correct else f"*}]]'rewsna'[q[]'snoitpo'[q{* :الصحﯿحة n\*!خطأ* "
b = InlineKeyboardBuilder()
b.button(text="← التالي", callback_data=f"study_next:{q_idx}")
try:
await callback.message.edit_text(f"*{q['q']}*\n\n{feedback}",
parse_mode="Markdown", reply_markup=b.as_markup())
except TelegramBadRequest:
pass
await callback.answer(" " if correct else " ")
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
":اختر فرعك لعرض التوقعاتn\n\*توقعات درجاتي بالوزاري* ",
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
b.button(text="فرع آخر ", callback_data="grade_prediction_menu")
b.button(text="رجوع ←", callback_data="back_home")
b.adjust(2)
await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=b.as_markup())
await callback.answer()
# ═══════════════════════════════════════════════
# GROUP QUIZ
# ═══════════════════════════════════════════════
group_sessions = {}
auto_quiz_tasks = {} # chat_id -> task
auto_quiz_answered = {} # msg_id -> question data
MAX_AUTO_ANSWERERS = 3 # لاﺆﺴﻟا لﺎﻔﻗإ ﻞﺒﻗ ﻦﯿﺒﯿﺠﻤﻟا دﺪﻋ
async def run_auto_quiz(chat_id: int, interval_minutes: int):
while True:
await asyncio.sleep(interval_minutes * 60)
try:
pool = [{**q, "_subject": k} for k, qs in QUESTION_BANK.items() for q in qs]
q = shuffle_options(random.choice(pool))
subj_key = q.get("_subject", "mixed")
subj = SUBJECTS.get(subj_key, {})
si = subj.get("icon", " ")
sn = subj.get("name", "")
labels = ["د" ,"ج" ,"ب" ,"أ"]
b = InlineKeyboardBuilder()
for i, opt in enumerate(q["options"]):
b.button(
text=f"{labels[i]}) {opt}",
callback_data=f"auto_ans:{subj_key}:{q['answer']}:{i}"
)
b.adjust(1)
sent = await bot.send_message(
chat_id,
f"n\n\*}]'q'[q{* n\n\*}ns{* }is{n\*سؤال المثابر التلقائي* "
f" PX من ﯾجاوب صح ﯾحصل +5n\!أول 3 أشخاص ﯾجاوبون ﯾظﮭر اسمﮭم ",
parse_mode="Markdown", reply_markup=b.as_markup()
)
# حﻮﺘﻔﻤﻛ لاﺆﺴﻟا ﻞﯿﺠﺴﺗ
auto_quiz_answered[sent.message_id] = {
"answered": False,
"correct_idx": q["answer"],
"options": q["options"],
"question": q["q"],
"subj_key": subj_key,
"chat_id": chat_id,
"msg_id": sent.message_id,
"answerers": [], # اﻮﺑﺎﺟأ ﻦﻣ ﺔﻤﺋﺎﻗ
"answerer_ids": set(), # راﺮﻜﺘﻟا ﻊﻨﻤﻟ
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
labels = ["د" ,"ج" ,"ب" ,"أ"]
q_data = auto_quiz_answered.get(msg_id)
if not q_data:
await callback.answer("!انتﮭى السؤال ", show_alert=True)
return
# ﻂﻘﻓ ةﺪﺣاو ةﺮﻣ بوﺎﺠﯾ ﺺﺨﺷ ﻞﻛ — راﺮﻜﺘﻟا ﻊﻨﻣ
if user.id in q_data["answerer_ids"]:
await callback.answer("!أجبت بالفعل ", show_alert=True)
return
# ﻦﯿﺒﯿﺠﻣ 3 ﺪﻌﺑ ﻞﻔﻘﻣ لاﺆﺴﻟا
if q_data["answered"]:
await callback.answer("!اكتمل عدد المجﯿبﯿن ", show_alert=True)
return
correct = chosen == correct_idx
correct_label = f"{labels[correct_idx]}) {q_data['options'][correct_idx]}"
# ءﺎﻄﻋإ XP ﺢﯿﺤﺻ اذإ
if correct:
db.update_stats(user.id, 5, 1, 1, subj_key)
result_icon = " "
await callback.answer(" PX صحﯿح! +5 ", show_alert=False)
else:
db.save_wrong_answer(user.id, subj_key,
q_data["question"],
q_data["options"],
correct_idx)
result_icon = " "
await callback.answer(f"}]xdi_tcerroc[slebal{ :خطأ! الصحﯿحة ", show_alert=True)
# ﺐﯿﺠﻤﻟا ﻞﯿﺠﺴﺗ
q_data["answerers"].append(f"{result_icon} {user.first_name}")
q_data["answerer_ids"].add(user.id)
answerers_count = len(q_data["answerers"])
# ﺔﺑﺎﺟﻹا ﺮﮭﻇأو لاﺆﺴﻟا ﻞﻔﻗأ — ﻦﯿﺒﯿﺠﻣ 3 ﺎﻨﻠﺻو اذإ
if answerers_count >= MAX_AUTO_ANSWERERS:
q_data["answered"] = True
opts_text = "\n".join(
f"{' ' if i == correct_idx else ' '} {labels[i]}) {q_data['options'][i]}"
for i in range(len(q_data["options"]))
)
answerers_text = "\n".join(q_data["answerers"])
try:
await callback.message.edit_text(
f"n\n\*سؤال المثابر التلقائي* "
f" *{q_data['question']}*\n\n"
f"{opts_text}\n\n"
f"━━━━━━━━━━━━━━━\n"
f"n\n\*}lebal_tcerroc{* :اإلجابة الصحﯿحة "
f"}txet_srerewsna{n\*:المجﯿبون* ",
parse_mode="Markdown"
)
except TelegramBadRequest:
pass
else:
# نﻵا ﻰﺘﺣ بﺎﺟأ ﻦﻣ ﺮﮭﻇأو ﺔﻟﺎﺳﺮﻟا ثﺪّﺣ
answerers_text = "\n".join(q_data["answerers"])
remaining = MAX_AUTO_ANSWERERS - answerers_count
try:
await callback.message.edit_text(
f"n\n\*سؤال المثابر التلقائي* "
f" *{q_data['question']}*\n\n"
f"n\n\}txet_srerewsna{n\*:)}SREREWSNA_OTUA_XAM{/}tnuoc_srerewsna{( أجاب* "
f"...لإلقفال }'شخص واحد' esle 1 > gniniamer fi 'شخص'{ *}gniniamer{* متبقي ",
parse_mode="Markdown",
reply_markup=callback.message.reply_markup
)
except TelegramBadRequest:
pass
@dp.callback_query(F.data == "group_menu")
async def group_menu(callback: CallbackQuery):
b = InlineKeyboardBuilder()
b.button(text="ابدأ جولة مجموعة ", callback_data="group_start_flow")
b.button(text="سؤال تلقائي للمجموعة ", callback_data="auto_quiz_menu")
b.button(text="رجوع ←", callback_data="back_home")
b.adjust(1)
await callback.message.edit_text(
":اختر نوع الجولةn\n\*االختبار المشترك* ",
parse_mode="Markdown", reply_markup=b.as_markup()
)
await callback.answer()
@dp.callback_query(F.data == "group_start_flow")
async def group_start_flow(callback: CallbackQuery):
await callback.message.edit_text(
":اختر فرعك أوالًn\n\*جولة مجموعة* ",
parse_mode="Markdown",
reply_markup=branch_select_kb("group_branch")
)
await callback.answer()
@dp.callback_query(F.data == "auto_quiz_menu")
async def auto_quiz_menu(callback: CallbackQuery):
b = InlineKeyboardBuilder()
b.button(text="كل نص ساعة ", callback_data="auto_interval:30")
b.button(text="كل ساعة ", callback_data="auto_interval:60")
b.button(text="رجوع ←", callback_data="group_menu")
b.adjust(2, 1)
await callback.message.edit_text(
"n\n\*السؤال التلقائي* "
"n\.أضف البوت لمجموعتك أو قناتك، ثم اختر الفترة الزمنﯿة"
"n\n\.سﯿرسل البوت سؤاالً تلقائﯿاً بالفترة المختارة"
"كم ترﯾد الفترة؟",
parse_mode="Markdown", reply_markup=b.as_markup()
)
await callback.answer()
@dp.callback_query(F.data.startswith("auto_interval:"))
async def auto_interval_select(callback: CallbackQuery):
interval = int(callback.data.split(":")[1])
b = InlineKeyboardBuilder()
b.button(text="شارك في مجموعة أو قناة ", switch_inline_query="auto_quiz")
b.button(text="رجوع ←", callback_data="auto_quiz_menu")
b.adjust(1)
# مﺪﺨﺘﺴﻤﻟا تﺎﻧﺎﯿﺑ ﻲﻓ ةﺮﺘﻔﻟا ﻆﻔﺣ
await callback.message.edit_text(
f"n\n\*دقﯿقة }lavretni{ تم االختﯿار — كل* "
f"n\ اآلن شارك الرسالة في مجموعتك أو قناتك"
f"`}lavretni{ tratsotua/`n\:أو أضف البوت للمجموعة وأرسل",
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
f"n\*!تم تفعﯿل األسئلة التلقائﯿة* "
f"n\n\دقﯿقة *}lavretni{* سؤال كل "
f"`potsotua/` :إلﯾقافﮫ أرسل",
parse_mode="Markdown"
)
@dp.message(Command("autostop"))
async def cmd_autostop(message: Message):
chat_id = message.chat.id
if chat_id in auto_quiz_tasks:
auto_quiz_tasks[chat_id].cancel()
del auto_quiz_tasks[chat_id]
await message.answer(".تم إﯾقاف األسئلة التلقائﯿة ")
else:
await message.answer(".ما في أسئلة تلقائﯿة مفعّلة حالﯿاً")
@dp.callback_query(F.data.startswith("group_branch:"))
async def group_branch(callback: CallbackQuery):
branch_key = callback.data.split(":")[1]
branch_name = BRANCHES[branch_key]["name"] if branch_key != "all" else "كل الفروع"
await callback.message.edit_text(
f":اختر المادةn\n\*}eman_hcnarb{ — االختبار المشترك* ",
parse_mode="Markdown",
reply_markup=subjects_for_branch_kb(branch_key, "group_create")
)
await callback.answer()
@dp.callback_query(F.data.startswith("group_create:"))
async def group_create(callback: CallbackQuery):
key = callback.data.split(":")[1]
if key == "arabic":
b = InlineKeyboardBuilder()
b.button(text="قواعد ", callback_data="group_create:arabic_grammar")
b.button(text="أدب ", callback_data="group_create:arabic_literature")
b.button(text="رجوع ←", callback_data="group_menu")
b.adjust(2, 1)
await callback.message.edit_text(":اختر نوع الجولةn\n\*العربي* ", parse_mode="Markdown", reply_markup=b.as_markup())
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
b.button(text="ابدأ في ھذه المحادثة ", callback_data=f"start_here:{sid}")
b.adjust(1)
await callback.message.edit_text(
f"n\n\`}dis{` :الكود n\*}ns{* }is{n\n\*!تم إنشاء الجولة* "
f"n\n\`}dis{ ziuqtrats/`n\*:شارك ھذا األمر بمجموعتك*"
f"}knil_erahs{n\*:أو الرابط المباشر*",
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
callback_data=f"quick_group:{bkey}")
b.button(text="كل الفروع ", callback_data="quick_group:all")
b.adjust(1)
await message.answer(":اختر الفرعn\n\*ابدأ جولة مجموعة* ",
parse_mode="Markdown", reply_markup=b.as_markup())
return
sid = parts[1].upper()
if sid not in group_sessions:
await message.answer("!الجولة غﯿر موجودة ")
return
session = group_sessions[sid]
if session["status"] != "waiting":
await message.answer("!الجولة بدأت بالفعل ")
return
session["chat_id"] = message.chat.id
await launch_group_quiz(message.chat.id, sid)
@dp.callback_query(F.data.startswith("quick_group:"))
async def quick_group(callback: CallbackQuery):
branch_key = callback.data.split(":")[1]
await callback.message.edit_text(
f":اختر المادةn\n\*االختبار المشترك* ",
parse_mode="Markdown",
reply_markup=subjects_for_branch_kb(branch_key, "group_create")
)
await callback.answer()
@dp.callback_query(F.data.startswith("start_here:"))
async def start_here(callback: CallbackQuery):
sid = callback.data.split(":")[1]
if sid not in group_sessions:
await callback.answer("!الجولة غﯿر موجودة ", show_alert=True)
return
session = group_sessions[sid]
if session["owner_id"] != callback.from_user.id:
await callback.answer("!فقط صاحب الجولة ", show_alert=True)
return
session["chat_id"] = callback.message.chat.id
await callback.answer("!تبدأ الجولة ")
await launch_group_quiz(callback.message.chat.id, sid)
async def process_join(user, sid, source):
if sid not in group_sessions:
txt = "!الجولة غﯿر موجودة "
if isinstance(source, CallbackQuery):
await source.answer(txt, show_alert=True)
else:
await source.answer(txt)
return
session = group_sessions[sid]
if session["status"] != "waiting":
txt = "!الجولة بدأت بالفعل "
if isinstance(source, CallbackQuery):
await source.answer(txt, show_alert=True)
else:
await source.answer(txt)
return
if len(session["players"]) >= MAX_PLAYERS:
txt = "!الجولة ممتلئة "
if isinstance(source, CallbackQuery):
await source.answer(txt, show_alert=True)
else:
await source.answer(txt)
return
# ── تﻮﺒﻟا ﻞّﻌﻓ ﺺﺨﺸﻟا اذإ ﻖﻘﺤﺗ ──────────────────
bot_info = await bot.get_me()
activate_link = f"https://t.me/{bot_info.username}?start=session_{sid}"
# تﻮﺒﻟا ﻞّﻌﻓ ﺎﻣ ﻲﻨﻌﯾ ﺖﻠﺸﻓ اذإ — ﺔﺻﺎﺧ ﺔﻟﺎﺳر ﮫﻟ ﻞﺳﺮﻧ لوﺎﺤﻧ
bot_activated = True
try:
await bot.send_message(
user.id,
f".سﯿبدأ البوت بإرسال األسئلة لك ھناn\n\*...جاري االنضمام للجولة* ",
parse_mode="Markdown"
)
except Exception:
bot_activated = False
if not bot_activated:
# تﻮﺒﻟا ﻞّﻌﻔﯾ جﺎﺘﺤﯾ ﮫﻧإ ﺔﻋﻮﻤﺠﻤﻟا ﺮﺒﺧأ
group_chat_id = session.get("chat_id")
if isinstance(source, CallbackQuery):
await source.answer("!ﯾجب تفعﯿل البوت أوالً ", show_alert=True)
# ﻞﯿﻌﻔﺗ رز ﻊﻣ ﺔﻋﻮﻤﺠﻤﻟا ﻲﻓ ﺔﻟﺎﺳر
b = InlineKeyboardBuilder()
b.button(
text="فعّل البوت وانضم للجولة ",
url=activate_link
)
notification_text = (
f"n\n\!ﯾحتاج تفعﯿل البوت أوالً للمشاركة }eman_tsrif.resu{ "
f" اضغط الزر أدناه لتفعﯿل البوت واالنضمام للجولة"
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
# ── حﺎﺠﻨﺑ ﻢﻀﻧا ───────────────────────────────────
session["players"][user.id] = {"name": user.full_name, "score": 0}
sn, si = subj_info(session["subject"] if not session["subject"].startswith("branch_") else "all")
# مﺎﻤﻀﻧﻻا ﺪﯿﻛﺄﺗ ﺔﺻﺎﺧ ﺔﻟﺎﺳر
try:
await bot.send_message(
user.id,
f"n\n\*!انضممت للجولة* "
f"{si} *{sn}*\n"
f"n\n\})]'sreyalp'[noisses(nel{ :الالعبون حالﯿاً "
f" ...انتظر حتى ﯾبدأ صاحب الجولة",
parse_mode="Markdown"
)
except Exception:
pass
if isinstance(source, CallbackQuery):
await source.answer(f")العب })]'sreyalp'[noisses(nel{( !انضممت ")
elif isinstance(source, Message):
await source.answer(
f"...انتظر البداﯾةn\})]'sreyalp'[noisses(nel{ :الالعبونn\*}ns{* }is{n\*!انضممت للجولة* ",
parse_mode="Markdown"
)
async def launch_group_quiz(chat_id: int, sid: str):
session = group_sessions[sid]
session["status"] = "active"
session["chat_id"] = chat_id # نإ ﺪﻛﺄﺗ chat_id ظﻮﻔﺤﻣ
qs = session["questions"]
key = session["subject"]
sn, si = subj_info(key if not key.startswith("branch_") else "all")
total = len(qs)
bot_info = await bot.get_me()
activate_link = f"https://t.me/{bot_info.username}?start=session_{sid}"
# مﺎﻤﻀﻧﻻا رز ﻊﻣ ﺔﯾاﺪﺒﻟا ﺔﻟﺎﺳر
b = InlineKeyboardBuilder()
b.button(text="انضم للجولة ", url=activate_link)
b.adjust(1)
await bot.send_message(
chat_id,
f"n\*!جولة المثابر الوزاري بدأت* "
f"n\أسئلة }latot{ — *}ns{* }is{"
f"n\n\ثانﯿة لكل سؤال 51 "
f"n\*للمشاركة ﯾجب تفعﯿل البوت أوالً* "
f"n\n\ اضغط الزر أدناه"
f"استعدوا... ",
parse_mode="Markdown",
reply_markup=b.as_markup()
)
await asyncio.sleep(5)
bot_info = await bot.get_me()
activate_link_base = f"https://t.me/{bot_info.username}?start=session_{sid}"
for q_idx, q in enumerate(qs):
session["answered"] = {}
session["current"] = q_idx
session["q_done"] = False
labels = ["د" ,"ج" ,"ب" ,"أ"]
activate_link = activate_link_base
def build_group_q(t, _q=q, _q_idx=q_idx):
names = [p["name"] for uid, p in session["players"].items() if uid in session["answered"]]
ans_line = f")})]'sreyalp'[noisses(nel{/})seman(nel{( })seman(nioj.' ,'{ :أجاب n\n\" if names else ""
return (f"{si} *{sn}* | {_q_idx+1}/{total}\n`{progress_bar(_q_idx, total)}`\n\n"
f" *{_q['q']}*\n\n {timer_bar(t)}{ans_line}")
def answer_kb(_q_idx=q_idx):
b = InlineKeyboardBuilder()
for i, opt in enumerate(q["options"]):
b.button(text=f"{labels[i]}) {opt}", callback_data=f"gq:{sid}:{_q_idx}:{i}")
b.button(text="انضم للجولة ", url=activate_link)
b.adjust(1)
return b.as_markup()
sent = await bot.send_message(chat_id, build_group_q(15), parse_mode="Markdown", reply_markup=answer_kb())
session["msg_id"] = sent.message_id
# Countdown — ﻞﻜﻟا بﺎﺟأ اذإ ًاﺮﻜﺒﻣ ﻲﮭﺘﻨﯾ
for t in range(14, -1, -1):
await asyncio.sleep(1)
# ًاﺮﻜﺒﻣ ﻞﻜﻟا بﺎﺟأ اذإ ﻖﻘﺤﺗ
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
# ًارﻮﻓ ﺔﺠﯿﺘﻨﻟا + ﺔﺤﯿﺤﺼﻟا ﺔﺑﺎﺟﻹا ضﺮﻋ
correct_ans = q["answer"]
correct_label = f"{labels[correct_ans]}) {q['options'][correct_ans]}"
correct_p = [p["name"] for uid, p in session["players"].items() if session["answered"].get(uid) == correct_ans]
wrong_p = [p["name"] for uid, p in session["players"].items() if uid in session["answered"] and session["answered"][uid] != correct_ans]
no_ans_p = [p["name"] for uid, p in session["players"].items() if uid not in session["answered"]]
# ﺔﺤﯿﺤﺼﻟا ﺔﺑﺎﺟﻹﺎﺑ ﺔﻟﺎﺳﺮﻟا ﺚﯾﺪﺤﺗ
opts_text = "\n".join(
f"{' ' if i == correct_ans else ' '} {labels[i]}) {q['options'][i]}"
for i in range(len(q["options"]))
)
early = ") أجاب الكل مبكراً( " if session.get("q_done") else ""
try:
await bot.edit_message_text(
chat_id=chat_id, message_id=sent.message_id,
text=(
f"{si} *{sn}* | {q_idx+1}/{total}\n"
f"`{progress_bar(q_idx+1, total)}`\n\n"
f" *{q['q']}*\n\n{opts_text}\n\n"
f"}ylrae{*}lebal_tcerroc{* :اإلجابة الصحﯿحة "
),
parse_mode="Markdown"
)
except TelegramBadRequest:
pass
# ﺔﺠﯿﺘﻨﻟا ﺔﻟﺎﺳر
res = f"n\n\*}lebal_tcerroc{* :الصحﯿحة n\*}1+xdi_q{ نتﯿجة السؤال* "
if correct_p: res += f"n\})p_tcerroc(nioj.' ,'{ :)})p_tcerroc(nel{( أجاب صح "
if wrong_p: res += f"n\})p_gnorw(nioj.' ,'{ :)})p_gnorw(nel{( أخطأ "
if no_ans_p: res += f"n\})p_sna_on(nioj.' ,'{ :)})p_sna_on(nel{( لم ﯾجب "
await bot.send_message(chat_id, res, parse_mode="Markdown")
await asyncio.sleep(3)
# Final results
sorted_p = sorted(session["players"].items(), key=lambda x: x[1]["score"], reverse=True)
medals = [" ", " ", " "]
final = f"n\━━━━━━━━━━━━━━━n\*}ns{* }is{n\*النتائج النﮭائﯿة* "
for i, (uid, p) in enumerate(sorted_p):
medal = medals[i] if i < 3 else f"{i+1}."
pct = int((p["score"] / total) * 100)
final += f"{medal} *{p['name']}* — {p['score']}/{total} ({pct}%)\n"
final += "!تﮭانﯿنا للمتصدرﯾن n\━━━━━━━━━━━━━━━"
b = InlineKeyboardBuilder()
b.button(text="جولة جدﯾدة ", callback_data="group_menu")
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
await callback.answer("!الجولة انتﮭت ")
return
session = group_sessions[sid]
if user.id not in session["players"]:
if len(session["players"]) >= MAX_PLAYERS:
await callback.answer("!الجولة ممتلئة ", show_alert=True)
return
session["players"][user.id] = {"name": user.full_name, "score": 0}
if user.id in session["answered"]:
await callback.answer("!أجبت بالفعل ")
return
if session["current"] != q_idx:
await callback.answer("!تأخرت ")
return
session["answered"][user.id] = chosen
q = session["questions"][q_idx]
correct = chosen == q["answer"]
if correct:
session["players"][user.id]["score"] += 1
labels = ["د" ,"ج" ,"ب" ,"أ"]
await callback.answer("صحﯿح! +1 " if correct else f"}]]'rewsna'[q[slebal{ :خطأ! الصحﯿحة ")
# بﺎﺟأ ﻦﻣ ءﺎﻤﺳﺄﺑ ﺔﻟﺎﺳﺮﻟا ﺚﯾﺪﺤﺗ
names = [p["name"] for uid, p in session["players"].items() if uid in session["answered"]]
sn, si = subj_info(session["subject"] if not session["subject"].startswith("branch_") else "all")
total = len(session["questions"])
try:
await callback.message.edit_text(
f"{si} *{sn}* | {q_idx+1}/{total}\n`{progress_bar(q_idx, total)}`\n\n"
f" *{q['q']}*\n\n"
f")العب })]'sreyalp'[noisses(nel{/})seman(nel{( })seman(nioj.' ,'{ :أجاب ",
parse_mode="Markdown", reply_markup=callback.message.reply_markup
)
except TelegramBadRequest:
pass
# ًاﺮﻜﺒﻣ لاﺆﺴﻟا ِﮫﻧأ — ﻞﻜﻟا بﺎﺟأ اذإ
if len(session["answered"]) >= len(session["players"]):
session["q_done"] = True
# ═══════════════════════════════════════════════
# CHALLENGE, LEADERBOARD, STATS, REVIEW, REMINDERS
# (ﻦﻣ دﻮﻜﻟا ﺲﻔﻧ v4 ﺮﯿﯿﻐﺗ نوﺪﺑ)
# ═══════════════════════════════════════════════
@dp.callback_query(F.data == "challenge_menu")
async def challenge_menu(callback: CallbackQuery, state: FSMContext):
b = InlineKeyboardBuilder()
b.button(text="ولد ", callback_data="challenge_gender:male")
b.button(text="بنت ", callback_data="challenge_gender:female")
b.button(text="رجوع ←", callback_data="back_home")
b.adjust(2, 1)
await callback.message.edit_text(
"صدﯾقك بنت وال ولد؟n\n\*تحدي صدﯾق* ",
parse_mode="Markdown", reply_markup=b.as_markup()
)
await callback.answer()
@dp.callback_query(F.data.startswith("challenge_gender:"))
async def challenge_gender_select(callback: CallbackQuery, state: FSMContext):
gender = callback.data.split(":")[1]
await state.update_data(challenge_gender=gender)
await callback.message.edit_text(
":اختر الفرعn\n\*تحدي صدﯾق* ",
parse_mode="Markdown", reply_markup=branch_select_kb("challenge_branch")
)
await callback.answer()
@dp.callback_query(F.data.startswith("challenge_branch:"))
async def challenge_branch(callback: CallbackQuery, state: FSMContext):
branch_key = callback.data.split(":")[1]
await callback.message.edit_text(":اختر المادة ", parse_mode="Markdown",
reply_markup=subjects_for_branch_kb(branch_key, "challenge_subject"))
await callback.answer()
@dp.callback_query(F.data.startswith("challenge_subject:"))
async def challenge_select(callback: CallbackQuery, state: FSMContext):
key = callback.data.split(":")[1]
await state.update_data(challenge_subject=key)
await callback.message.edit_text(
":)emanresu@ :مثال( أرسل ﯾوزرنﯿم صدﯾقك ",
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
"trats/ اطلب من صدﯾقك ﯾفعّل البوت أوالً وﯾرسلn\n\*!غﯿر موجود* ",
parse_mode="Markdown", reply_markup=back_home_kb()
)
return
data = await state.get_data()
key = data.get("challenge_subject", "math")
b = InlineKeyboardBuilder()
for u in results:
if u["user_id"] != message.from_user.id:
b.button(text=f" {u['name']}", callback_data=f"send_challenge:{u['user_id']}:{key}")
b.button(text="رجوع ←", callback_data="back_home")
b.adjust(1)
await message.answer(":اختر من ترﯾد تتحداه", reply_markup=b.as_markup())
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
b.button(text="قبول ", callback_data=f"accept_challenge:{cid}")
b.button(text="رفض ", callback_data="back_home")
b.adjust(2)
await bot.send_message(opp, f"ھل تقبل؟n\*}ns{* }is{n\*!}eman_lluf.resu_morf.kcabllac{ تحدي من* ",
parse_mode="Markdown", reply_markup=b.as_markup())
except Exception:
pass
qs = pick_questions(key)
sent = await callback.message.answer(f"...جولتك تبدأ اآلنn\*}ns{* }is{n\*!تم إرسال التحدي* ", parse_mode="Markdown")
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
await callback.answer("انتﮭت صالحﯿة التحدي", show_alert=True)
return
key = challenge["subject"]
sn, si = subj_info(key if not key.startswith("branch_") else "all")
qs = pick_questions(key)
sent = await callback.message.answer(f" !تبدأ اآلنn\*}ns{* }is{n\*!قبلت التحدي* ", parse_mode="Markdown")
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
medals = [" ", " ", " "]
b = InlineKeyboardBuilder()
if tab == "xp":
top = db.get_leaderboard(10)
title = "*المتصدرون بالنقاط* "
b.button(text="✓ النقاط ", callback_data="lb_tab:xp")
b.button(text="السلسلة الﯿومﯿة ", callback_data="lb_tab:streak")
else:
top = db.get_streak_leaderboard(10)
title = "*المتصدرون بالسلسلة الﯿومﯿة* "
b.button(text="النقاط ", callback_data="lb_tab:xp")
b.button(text="✓ السلسلة الﯿومﯿة ", callback_data="lb_tab:streak")
b.button(text="رجوع ←", callback_data="back_home")
b.adjust(2, 1)
if not top:
await callback.message.edit_text("!ال ﯾوجد العبون بعد", reply_markup=b.as_markup())
return
text = f"{title}\n━━━━━━━━━━━━━━━\n"
for i, row in enumerate(top):
medal = medals[i] if i < 3 else f"{i+1}."
_, icon, label = get_title(row["xp"])
if tab == "xp":
text += f"n\n\ﯾوم }]'kaerts'[wor{ PX }]'px'[wor{ n\}noci{ *}]'eman'[wor{* }ladem{"
else:
text += f"n\n\PX }]'px'[wor{ ﯾوم متواصل }]'kaerts'[wor{ n\}noci{ *}]'eman'[wor{* }ladem{"
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
weekly_grade = ("ممتاز " if weekly_acc>=90 else "جﯿد جداً " if weekly_acc>=70 else
"جﯿد " if weekly_acc>=50 else "ﯾحتاج مراجعة ")
text = (
f"n\━━━━━━━━━━━━━━━n\*إحصائﯿاتي* "
f" XP: *{stats['xp']}*\n"
f"n\}noci{ *}lebal{* :لقبك "
f"n\ﯾوم *}]'kaerts'[stats{* :السلسلة "
f"n\*}]'semag_latot'[stats{* :جوالت "
f"n\n\*}'ال بعد' esle trec fi trec{* :شﮭادة "
f"n\*:أداءك ھذا األسبوع* "
f"n\*%}cca_ylkeew{* :الدقة "
f"n\*}edarg_ylkeew{* :التقﯿﯿم "
f"n\*}]'semag'[troper{* :جوالت "
)
b = InlineKeyboardBuilder()
b.button(text="نصﯿحة الﯿوم ", callback_data="tip_of_day")
b.button(text="رجوع ←", callback_data="back_home")
b.adjust(1)
await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=b.as_markup())
await callback.answer()
@dp.callback_query(F.data == "buy_title")
async def buy_title(callback: CallbackQuery):
b = InlineKeyboardBuilder()
b.button(text="رجوع ←", callback_data="back_home")
await callback.message.edit_text(
"━━━━━━━━━━━━━━━n\*شراء لقب* ",
parse_mode="Markdown", reply_markup=b.as_markup()
)
await callback.answer()
@dp.callback_query(F.data == "tip_of_day")
async def tip_of_day(callback: CallbackQuery):
tips = [
"!راجع أخطاءك بعد كل جولة — ھي أفضل طرﯾقة للتحسن ",
".المراجعة المنتظمة ﯾومﯿاً أفضل من جلسة طوﯾلة كل أسبوع ",
".ركّز على المواد األضعف عندك أكثر من القوﯾة ",
"!السلسلة الﯿومﯿة تبني عادة المراجعة — ال تكسرھا ",
".اشرح المعلومة لنفسك بصوت عالٍ — ھذا ﯾثبّتﮭا أكثر ",
".ال تراجع بالحفظ فقط — فﮭم السبب أھم من الحفظ ",
".كرّر األسئلة التي أخطأت فﯿﮭا حتى تصﯿر سﮭلة علﯿك ",
".النوم الجﯿد قبل االمتحان أھم من السﮭر على المراجعة ",
".اكتب المالحظات بﯿدك — الكتابة تساعد على التذكر ",
".الثبات ﯾكسب — المثابرة أھم من الموھبة ",
]
import hashlib
today = date.today().isoformat()
idx = int(hashlib.md5(today.encode()).hexdigest(), 16) % len(tips)
tip = tips[idx]
b = InlineKeyboardBuilder()
b.button(text="رجوع ←", callback_data="back_home")
await callback.message.edit_text(
f"}pit{n\n\━━━━━━━━━━━━━━━n\*نصﯿحة الﯿوم* ",
parse_mode="Markdown", reply_markup=b.as_markup()
)
await callback.answer()
# ═══════════════════════════════════════════════
# ﻲﺋﺎﻄﺧأ ﺔﻌﺟاﺮﻣ
# ═══════════════════════════════════════════════
@dp.callback_query(F.data == "wrong_answers_menu")
async def wrong_answers_menu(callback: CallbackQuery):
uid = callback.from_user.id
wrong_subjects = db.get_wrong_subjects(uid)
if not wrong_subjects:
b = InlineKeyboardBuilder()
b.button(text="رجوع ←", callback_data="back_home")
await callback.message.edit_text(
" استمر بالمراجعةn\!لﯿس لدﯾك أخطاء n\n\*مراجعة أخطائي* ",
parse_mode="Markdown", reply_markup=b.as_markup()
)
await callback.answer()
return
b = InlineKeyboardBuilder()
for ws in wrong_subjects:
subj_key = ws["subject"]
subj = SUBJECTS.get(subj_key, {})
icon = subj.get("icon", " ")
name = subj.get("name", subj_key)
b.button(
text=f")سؤال }]'tnc'[sw{( }eman{ }noci{",
callback_data=f"wrong_subject:{subj_key}"
)
b.button(text="رجوع ←", callback_data="back_home")
b.adjust(2)
await callback.message.edit_text(
":اختر المادةn\n\*مراجعة أخطائي* ",
parse_mode="Markdown", reply_markup=b.as_markup()
)
await callback.answer()
@dp.callback_query(F.data.startswith("wrong_subject:"))
async def wrong_subject_quiz(callback: CallbackQuery, state: FSMContext):
subj_key = callback.data.split(":")[1]
uid = callback.from_user.id
qs = db.get_wrong_questions(uid, subj_key)
if not qs:
await callback.answer("!ال ﯾوجد أخطاء في ھذه المادة", show_alert=True)
return
sent = await callback.message.answer(
f"...})yek_jbus ,'eman'(teg.)}{ ,yek_jbus(teg.STCEJBUS{ مراجعة أخطائك في ",
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
# ﻲﺗﺎﯿﺋﺎﺼﺣﻹ ﮫﯿﺟﻮﺘﻟا ةدﺎﻋإ
await show_my_stats(callback)
@dp.callback_query(F.data.startswith("review:"))
async def review_answers(callback: CallbackQuery, state: FSMContext):
parts = callback.data.split(":")
idx, key = int(parts[1]), parts[2]
data = await state.get_data()
answers = data.get("answers", [])
if not answers or idx >= len(answers):
await callback.answer(" انتﮭت المراجعة", show_alert=True)
return
a = answers[idx]
labels = ["د" ,"ج" ,"ب" ,"أ"]
opts = ""
for i, opt in enumerate(a["options"]):
if i == a["correct"] and i == a["chosen"]: opts += f"n\إجابتك الصحﯿحة ← }tpo{ )}]i[slebal{ "
elif i == a["correct"]: opts += f"n\اإلجابة الصحﯿحة ← }tpo{ )}]i[slebal{ "
elif i == a["chosen"]: opts += f"n\إجابتك ← }tpo{ )}]i[slebal{ "
else: opts += f" {labels[i]}) {opt}\n"
status = "صحﯿحة " if a["chosen"]==a["correct"] else ("انتﮭى الوقت " if a["chosen"]==-1 else "خاطئة ")
b = InlineKeyboardBuilder()
if idx > 0: b.button(text="السابق →", callback_data=f"review:{idx-1}:{key}")
if idx < len(answers)-1: b.button(text="← التالي", callback_data=f"review:{idx+1}:{key}")
b.button(text="رجوع ←", callback_data="back_home")
b.adjust(2, 1)
await callback.message.edit_text(
f"}sutats{ :النتﯿجةn\}stpo{n\n\}]'q'[a{ n\n\*})srewsna(nel{/}1+xdi{ مراجعة* ",
parse_mode="Markdown", reply_markup=b.as_markup())
await callback.answer()
@dp.callback_query(F.data == "reminder_menu")
async def reminder_menu(callback: CallbackQuery):
stats = db.get_user_stats(callback.from_user.id)
status = "مفعّل " if stats.get("reminders_on") else "معطّل "
b = InlineKeyboardBuilder()
if stats.get("reminders_on"):
b.button(text="إﯾقاف كذكﯿر ", callback_data="reminder_off")
else:
b.button(text="مساًء 8 ", callback_data="reminder_on:20:00")
b.button(text="مساًء 01 ", callback_data="reminder_on:22:00")
b.button(text="صباحاً 7 ", callback_data="reminder_on:07:00")
b.button(text="رجوع ←", callback_data="back_home")
b.adjust(1)
await callback.message.edit_text(f"}sutats{ :الحالةn\n\*التذكﯿر الﯿومي* ",
parse_mode="Markdown", reply_markup=b.as_markup())
await callback.answer()
@dp.callback_query(F.data.startswith("reminder_on:"))
async def reminder_on(callback: CallbackQuery):
parts = callback.data.split(":")
time_str = f"{parts[1]}:{parts[2]}"
db.set_reminder(callback.from_user.id, True, time_str)
await callback.message.edit_text(f" *}rts_emit{ تم تفعﯿل التذكﯿر الساعة* ",
parse_mode="Markdown", reply_markup=back_home_kb())
await callback.answer("!تم ")
@dp.callback_query(F.data == "reminder_off")
async def reminder_off(callback: CallbackQuery):
db.set_reminder(callback.from_user.id, False)
await callback.message.edit_text("*تم إﯾقاف التذكﯿر* ", parse_mode="Markdown", reply_markup=back_home_kb())
await callback.answer()
@dp.callback_query(F.data == "settings")
async def settings_menu(callback: CallbackQuery):
b = InlineKeyboardBuilder()
b.button(text="فكرة البوت ", callback_data="bot_idea")
b.button(text="قناة البوت ", url="https://t.me/AlMuthabir")
b.button(text="لالقتراح والتواصل ", url="https://t.me/AlmuthabirBot")
b.button(text="رجوع ←", callback_data="back_home")
b.adjust(1)
await callback.message.edit_text(
"━━━━━━━━━━━━━━━n\*اإلعدادات* ",
parse_mode="Markdown",
reply_markup=b.as_markup()
)
await callback.answer()
@dp.callback_query(F.data == "bot_idea")
async def bot_idea(callback: CallbackQuery):
b = InlineKeyboardBuilder()
b.button(text="رجوع ←", callback_data="settings")
await callback.message.edit_text(
"_)قرﯾباً(_n\n\━━━━━━━━━━━━━━━n\*فكرة البوت* ",
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
f" ثابر الﯿوم، تفوّق غداًn\ !}]'eman'[u{ ال تنسَ مراجعتك ﯾاn\n\*!تذكﯿر ﯾومي* ",
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
