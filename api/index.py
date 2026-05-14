import os
import logging
import uuid
import hashlib
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, session, jsonify, abort
from supabase import create_client, Client
from groq import Groq
from werkzeug.exceptions import HTTPException

# =================================================================
# 1. ГЛОБАЛЬНАЯ КОНФИГУРАЦИЯ И СИСТЕМА ЛОГИРОВАНИЯ
# =================================================================

# Настройка логирования в стиле Production (в консоль Vercel)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("EduSmart_Core")

app = Flask(__name__)

# Безопасность сессий
app.secret_key = os.environ.get("FLASK_SECRET_KEY", hashlib.sha256(b"edusmart_2026_internal_secret").hexdigest())
app.permanent_session_lifetime = timedelta(days=7)
app.config['JSON_AS_ASCII'] = False
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # Лимит 16MB

# =================================================================
# 2. ИНИЦИАЛИЗАЦИЯ ВНЕШНИХ СЕРВИСОВ (SUPABASE & GROQ)
# =================================================================

SUPABASE_URL = "https://sdjrwxsdcgnhklzpxpdd.supabase.co"
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

def get_supabase_client() -> Client:
    if not SUPABASE_KEY:
        logger.critical("Критический сбой: SUPABASE_KEY не найден!")
        raise RuntimeError("Cloud Database Key Missing")
    return create_client(SUPABASE_URL, SUPABASE_KEY)

def get_ai_client() -> Groq:
    if not GROQ_API_KEY:
        logger.critical("Критический сбой: GROQ_API_KEY не найден!")
        raise RuntimeError("AI Engine Key Missing")
    return Groq(api_key=GROQ_API_KEY)

# Инициализация при старте
try:
    supabase = get_supabase_client()
    ai_client = get_ai_client()
    logger.info("EduSmart Core Engine: Успешная синхронизация со всеми API.")
except Exception as e:
    logger.error(f"Сбой инициализации систем: {e}")

# =================================================================
# 3. ДЕКОРАТОРЫ И УТИЛИТЫ БЕЗОПАСНОСТИ
# =================================================================

def login_required(f):
    """Декоратор для защиты приватных маршрутов."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            logger.warning(f"Попытка несанкционированного доступа к {request.path}")
            return redirect(url_for('login', next=request.path))
        return f(*args, **kwargs)
    return decorated_function

def handle_api_error(e):
    """Глобальный обработчик ошибок API."""
    logger.error(f"API Error: {str(e)}")
    code = 500
    if isinstance(e, HTTPException):
        code = e.code
    return jsonify(error=str(e), status="fail"), code

# =================================================================
# 4. ЯДРО АНАЛИТИКИ И БИЗНЕС-ЛОГИКИ
# =================================================================

class EduAnalytics:
    @staticmethod
    def commit_activity(user_id, category, value=1):
        """Профессиональная запись метрик пользователя."""
        if not user_id: return
        ts = datetime.utcnow().date().isoformat()
        try:
            # Атомарная операция: проверка существования и обновление
            res = supabase.table("activity_log").select("*").eq("user_id", user_id).eq("date", ts).execute()
            
            if res.data:
                current = res.data[0]
                update_field = 'tasks_done' if category == "task" else 'focus_minutes'
                new_val = max(0, (current.get(update_field, 0) or 0) + value)
                supabase.table("activity_log").update({update_field: new_val}).eq("id", current['id']).execute()
            else:
                data = {
                    "user_id": user_id,
                    "date": ts,
                    "tasks_done": value if category == "task" else 0,
                    "focus_minutes": value if category == "focus" else 0
                }
                supabase.table("activity_log").insert(data).execute()
        except Exception as err:
            logger.error(f"Analytics Commit Fail: {err}")

# =================================================================
# 5. МАРШРУТИЗАЦИЯ (ROUTES)
# =================================================================

@app.route('/')
def landing():
    if 'user_id' in session:
        return redirect(url_for('chat_interface'))
    return render_template('login.html')

@app.route('/chat')
@login_required
def chat_interface():
    return render_template('chat.html', user_email=session.get('user_email'))

@app.route('/tracker')
@login_required
def tracker_page():
    return render_template('tracker.html')

@app.route('/focus')
@login_required
def focus_timer():
    return render_template('focus.html')

# --- СИСТЕМА АУТЕНТИФИКАЦИИ ---

@app.route('/auth/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form.get('email', '').lower().strip()
        password = request.form.get('password')
        
        if len(password) < 6:
            return render_template('register.html', error="Пароль должен быть не менее 6 символов")

        try:
            response = supabase.auth.sign_up({"email": email, "password": password})
            logger.info(f"Новый пользователь зарегистрирован: {email}")
            return redirect(url_for('login', msg="Регистрация успешна! Проверьте почту для подтверждения."))
        except Exception as e:
            return render_template('register.html', error=f"Ошибка регистрации: {str(e)}")
    return render_template('register.html')

@app.route('/auth/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').lower().strip()
        password = request.form.get('password')
        
        try:
            auth_response = supabase.auth.sign_in_with_password({"email": email, "password": password})
            session.permanent = True
            session['user_id'] = auth_response.user.id
            session['user_email'] = auth_response.user.email
            logger.info(f"Успешный вход: {email}")
            return redirect(url_for('chat_interface'))
        except Exception:
            return render_template('login.html', error="Неверные учетные данные или email не подтвержден.")
    return render_template('login.html')

@app.route('/auth/logout')
def logout():
    user_email = session.get('user_email')
    session.clear()
    logger.info(f"Пользователь вышел из системы: {user_email}")
    return redirect(url_for('login'))

# --- ВОССТАНОВЛЕНИЕ ДОСТУПА ---

@app.route('/auth/reset-password', methods=['GET', 'POST'])
def reset_password_request():
    if request.method == 'POST':
        email = request.form.get('email')
        try:
            supabase.auth.reset_password_for_email(email, {
                "redirect_to": url_for('update_password_form', _external=True)
            })
            return render_template('reset_password.html', message="Ссылка для сброса отправлена.")
        except Exception as e:
            return render_template('reset_password.html', error=str(e))
    return render_template('reset_password.html')

@app.route('/auth/update-password', methods=['GET', 'POST'])
def update_password_form():
    if request.method == 'POST':
        new_pwd = request.form.get('password')
        try:
            supabase.auth.update_user({"password": new_pwd})
            return redirect(url_for('login', msg="Пароль обновлен."))
        except Exception as e:
            return render_template('update_password.html', error=str(e))
    return render_template('update_password.html')

# =================================================================
# 6. API ЭНДПОИНТЫ (JSON)
# =================================================================

@app.route('/api/ai/ask', methods=['POST'])
@login_required
def ai_ask():
    data = request.get_json()
    user_input = data.get('message', '').strip()
    
    if not user_input:
        return jsonify({"answer": "Запрос не может быть пустым."}), 400

    try:
        # Профессиональный системный промпт для EduSmart
        system_instructions = (
            "Ты — EduSmart AI, когнитивный ассистент. Твоя цель — помогать студентам "
            "в обучении, написании кода и структурировании мыслей. Будь точен, используй "
            "Markdown для форматирования. Отвечай на языке пользователя."
        )
        
        response = ai_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_instructions},
                {"role": "user", "content": user_input}
            ],
            temperature=0.7,
            max_tokens=2048
        )
        
        answer = response.choices[0].message.content
        return jsonify({"answer": answer, "status": "success"})
    except Exception as e:
        logger.error(f"AI Engine Error: {e}")
        return jsonify({"answer": "Извините, произошла внутренняя ошибка нейросети.", "status": "error"}), 500

# --- API ТРЕКЕРА ЗАДАЧ ---

@app.route('/api/tasks', methods=['GET'])
@login_required
def list_tasks():
    uid = session['user_id']
    try:
        res = supabase.table("tasks").select("*").eq("user_id", uid).order("created_at", desc=True).execute()
        return jsonify(res.data)
    except Exception as e:
        return handle_api_error(e)

@app.route('/api/tasks/add', methods=['POST'])
@login_required
def add_task():
    uid = session['user_id']
    content = request.json.get('text', '').strip()
    if not content: return abort(400)

    try:
        record = {"user_id": uid, "text": content, "is_done": False}
        res = supabase.table("tasks").insert(record).execute()
        return jsonify(res.data[0]), 201
    except Exception as e:
        return handle_api_error(e)

@app.route('/api/tasks/toggle', methods=['POST'])
@login_required
def toggle_task():
    uid = session['user_id']
    tid = request.json.get('id')
    state = request.json.get('is_done')
    
    try:
        supabase.table("tasks").update({"is_done": state}).eq("id", tid).eq("user_id", uid).execute()
        # Логируем в аналитику
        EduAnalytics.commit_activity(uid, "task", 1 if state else -1)
        return jsonify(status="updated")
    except Exception as e:
        return handle_api_error(e)

@app.route('/api/analytics/activity', methods=['GET'])
@login_required
def get_user_activity():
    uid = session['user_id']
    try:
        # Получаем данные за последнюю неделю
        res = supabase.table("activity_log").select("*").eq("user_id", uid).order("date", desc=True).limit(7).execute()
        return jsonify(res.data)
    except Exception as e:
        return handle_api_error(e)

# =================================================================
# 7. ЗАПУСК ПРИЛОЖЕНИЯ
# =================================================================

