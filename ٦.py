# الجزء 3: بنك الأسئلة (questions.py)
# ملاحظة: يجب أن يحتوي هذا الملف على القواميس QUESTION_BANK, SUBJECTS, BRANCHES

SUBJECTS = {
    "islamic": {"name": "إسلامية", "icon": "🕌"},
    "arabic": {"name": "لغة عربية", "icon": "📖"},
    # أضف باقي المواد هنا...
}

BRANCHES = {
    "scientific": {"name": "علمي", "icon": "🧪", "subjects": ["math", "physics", "chemistry", "biology"]},
    "literary": {"name": "أدبي", "icon": "📚", "subjects": ["history", "geography", "economics"]},
    # أضف باقي الفروع هنا...
}

QUESTION_BANK = {
    "islamic": [
        {"question": "سؤال تجريبي؟", "options": ["أ", "ب", "ج", "د"], "answer": 0},
    ],
    # أضف باقي الأسئلة هنا...
}
