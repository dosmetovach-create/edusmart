import os
import logging
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from supabase import create_client, Client
from groq import Groq
from datetime import datetime, timedelta

# --- НАСТРОЙКИ ЛОГИРОВАНИЯ ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "edusmart_ultra_deep_secret_2026_premium")
app.permanent_session_lifetime = timedelta(days=7)

# --- КОНФИГУРАЦИЯ API СЕРВИСОВ ---
SUPABASE_URL = "https://sdjrwxsdcgnhklzpxpdd.supabase.co"
SUPABASE_KEY = "sb_publishable_nB7DU3zObCYPAFmQWJ_ZVg_YfRKDd9E"
GROQ_API_KEY = "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"

try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    ai_client = Groq(api_key=GROQ_API_KEY.strip())
    logger.info("Все сервисы EduSmart успешно запущены.")
except Exception as e:
    logger.error(f"Ошибка инициализации API: {e}")

# --- МОДУЛЬ АНАЛИТИКИ ---

def log_activity(user_id, act_type="task", amount=1):
    if not user_id: return
    today = datetime.now().date().isoformat()
    try:
        query = supabase.table("activity_log").select("*").eq("user_id", user_id).eq("date", today).execute()
        if query.data:
            record = query.data[0]
            field = 'tasks_done' if act_type == "task" else 'focus_minutes'
            new_value = max(0, (record.get(field, 0) or 0) + amount)
            supabase.table("activity_log").update({field: new_value}).eq("id", record['id']).execute()
        else:
            new_record = {
                "user_id": user_id,
                "date": today,
                "tasks_done": amount if act_type == "task" else 0,
                "focus_minutes": amount if act_type == "focus" else 0
            }
            supabase.table("activity_log").insert(new_record).execute()
    except Exception as e:
        logger.error(f"Ошибка записи в SQL: {e}")

# --- МАРШРУТЫ СТРАНИЦ ---

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('chat'))
    return redirect(url_for('login'))

@app.route('/chat')
def chat():
    if 'user_id' not in session: return redirect(url_for('login'))
    return render_template('chat.html')

@app.route('/tracker')
def tracker():
    if 'user_id' not in session: return redirect(url_for('login'))
    return render_template('tracker.html')

@app.route('/focus')
def focus():
    if 'user_id' not in session: return redirect(url_for('login'))
    return render_template('focus.html')

# --- ФУНКЦИИ ВОССТАНОВЛЕНИЯ ПАРОЛЯ (ДОБАВЛЕНО) ---

@app.route('/reset_password', methods=['GET', 'POST'])
def reset_password():
    if request.method == 'POST':
        email = request.form.get('email')
        try:
            # Отправка ссылки. redirectTo должен вести на твой URL /update_password
            supabase.auth.reset_password_for_email(email, {
                "redirectTo": url_for('update_password', _external=True)
            })
            return render_template('reset_password.html', message="Инструкции отправлены на почту!")
        except Exception as e:
            return render_template('reset_password.html', error=f"Ошибка: {str(e)}")
    return render_template('reset_password.html')

@app.route('/update_password', methods=['GET', 'POST'])
def update_password():
    if request.method == 'POST':
        new_password = request.form.get('password')
        try:
            supabase.auth.update_user({"password": new_password})
            return redirect(url_for('login', message="Пароль успешно обновлен!"))
        except Exception as e:
            return render_template('update_password.html', error=f"Ошибка: {str(e)}")
    return render_template('update_password.html')

# --- API ЭНДПОИНТЫ (ТРЕКЕР) ---

@app.route('/get_tasks', methods=['GET'])
def get_tasks():
    user_id = session.get('user_id')
    if not user_id: return jsonify([])
    try:
        res = supabase.table("tasks").select("*").eq("user_id", user_id).order("created_at", desc=True).execute()
        tasks = res.data
        for t in tasks:
            dt = datetime.fromisoformat(t['created_at'].replace('Z', '+00:00'))
            t['date_display'] = f"Сегодня, {dt.strftime('%H:%M')}" if dt.date() == datetime.now().date() else dt.strftime("%d.%m.%Y %H:%M")
        return jsonify(tasks)
    except: return jsonify([])

@app.route('/add_task', methods=['POST'])
def add_task():
    user_id = session.get('user_id')
    task_text = request.json.get('text', '').strip()
    if not task_text: return jsonify({"error": "Пусто"}), 400
    try:
        res = supabase.table("tasks").insert({"user_id": user_id, "text": task_text, "is_done": False}).execute()
        return jsonify(res.data[0])
    except: return jsonify({"status": "error"}), 500

@app.route('/toggle_task', methods=['POST'])
def toggle_task():
    user_id = session.get('user_id')
    data = request.json
    task_id = data.get('id')
    is_done = data.get('is_done')
    try:
        supabase.table("tasks").update({"is_done": is_done}).eq("id", task_id).execute()
        change = 1 if is_done else -1
        log_activity(user_id, act_type="task", amount=change)
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/delete_task', methods=['POST'])
def delete_task():
    task_id = request.json.get('id')
    try:
        supabase.table("tasks").delete().eq("id", task_id).execute()
        return jsonify({"status": "deleted"})
    except: return jsonify({"status": "error"})

@app.route('/get_activity', methods=['GET'])
def get_activity():
    user_id = session.get('user_id')
    if not user_id: return jsonify([])
    try:
        res = supabase.table("activity_log").select("date, tasks_done, focus_minutes")\
            .eq("user_id", user_id).order("date", desc=False).limit(7).execute()
        return jsonify(res.data)
    except: return jsonify([])

# --- ИИ И АВТОРИЗАЦИЯ ---

@app.route('/ask', methods=['POST'])
def ask():
    user_id = session.get('user_id')
    if not user_id: return jsonify({"answer": "Войдите в систему."}), 401
    user_msg = request.json.get('message', '')
    try:
        sys_prompt = "Ты EduSmart AI. Помогай с учебой, книгами и кодом. Отвечай кратко и экспертно."
        completion = ai_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": user_msg}]
        )
        return jsonify({"answer": completion.choices[0].message.content})
    except: return jsonify({"answer": "Ошибка нейросети."})

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email, pwd = request.form.get('email'), request.form.get('password')
        try:
            auth = supabase.auth.sign_in_with_password({"email": email, "password": pwd})
            session['user_id'], session['user_email'] = auth.user.id, auth.user.email
            return redirect(url_for('chat'))
        except: return render_template('login.html', error="Ошибка входа.")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True, port=5000)