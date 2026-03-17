# الجزء 4: لوحات المفاتيح (keyboards.py)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from questions import SUBJECTS, BRANCHES

def main_menu_kb():
    b = InlineKeyboardBuilder()
    b.button(text="📚 اختر المادة",        callback_data="subjects_menu")
    b.button(text="🎲 كل المواد",          callback_data="subject:all")
    b.button(text="📖 وضع الدراسة",        callback_data="study_mode_menu")
    b.button(text="⚔️ تحدي صديق",          callback_data="challenge_menu")
    b.button(text="👥 جولة مجموعة",        callback_data="group_menu")
    b.button(text="🏆 المتصدرون",          callback_data="leaderboard")
    b.button(text="📊 إحصائياتي",          callback_data="my_stats")
    b.button(text="🎯 توقعات درجاتي",      callback_data="grade_prediction_menu")
    b.button(text="📅 تذكير يومي",         callback_data="reminder_menu")
    b.button(text="📈 تقريري الأسبوعي",   callback_data="weekly_report")
    b.button(text="⚙️ الإعدادات",          callback_data="settings")
    b.adjust(2, 2, 2, 2, 2, 1)
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
