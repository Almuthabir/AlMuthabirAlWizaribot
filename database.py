# الجزء 2: قاعدة البيانات (database.py)
# ملاحظة: يجب أن يحتوي هذا الملف على الدوال التي يستدعيها bot.py
# مثل: register_user, get_user_stats, get_pending_challenge, إلخ.

def register_user(user_id, full_name):
    # كود تسجيل المستخدم هنا
    pass

def get_user_stats(user_id):
    # كود جلب إحصائيات المستخدم هنا
    # مثال لبيانات تجريبية:
    return {"xp": 0, "streak": 0, "total_games": 0}

def get_pending_challenge(user_id):
    # كود جلب التحديات المعلقة هنا
    return None
