"""
TTS Studio License Server - Enhanced Admin
Flask application with full user management and usage tracking
"""
from flask import Flask, request, jsonify, render_template, redirect, url_for
from flask_cors import CORS
from datetime import datetime, timedelta
import sqlite3
import secrets
import hashlib
import os

app = Flask(__name__)
CORS(app)

# Configuration
DATABASE = os.path.join(os.path.dirname(__file__), 'database.db')
ADMIN_KEY = "tts_admin_2024"  # Change this in production
SECRET_KEY = "TTS_STUDIO_LICENSE_KEY_2024"

# Coupon Types
COUPON_TYPES = {
    "PRO30": {"credits": 300, "days": 30, "unlimited": False, "name": "Pro 30 Days"},
    "PRO90": {"credits": 1500, "days": 90, "unlimited": False, "name": "Pro 90 Days"},
    "UNL7": {"credits": 0, "days": 7, "unlimited": True, "name": "Unlimited 7 Days"},
    "UNL30": {"credits": 0, "days": 30, "unlimited": True, "name": "Unlimited 30 Days"},
    "UNL90": {"credits": 0, "days": 90, "unlimited": True, "name": "Unlimited 90 Days"},
    "LIFE": {"credits": 0, "days": 36500, "unlimited": True, "name": "Lifetime"},
}

FREE_DAILY_LIMIT = 10


def get_db():
    """Get database connection"""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initialize database tables"""
    conn = get_db()
    cursor = conn.cursor()
    
    # Coupons table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS coupons (
            code TEXT PRIMARY KEY,
            type TEXT NOT NULL,
            credits INTEGER DEFAULT 0,
            days INTEGER DEFAULT 0,
            unlimited INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            used INTEGER DEFAULT 0,
            used_by TEXT,
            used_at TEXT
        )
    ''')
    
    # Licenses table (enhanced)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS licenses (
            device_id TEXT PRIMARY KEY,
            tier TEXT DEFAULT 'free',
            credits INTEGER DEFAULT 0,
            unlimited INTEGER DEFAULT 0,
            expires TEXT,
            daily_used INTEGER DEFAULT 0,
            daily_reset TEXT,
            coupon_used TEXT,
            suspended INTEGER DEFAULT 0,
            suspend_reason TEXT,
            total_generations INTEGER DEFAULT 0,
            last_active TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Notifications table (for bonus/penalty messages)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT NOT NULL,
            type TEXT NOT NULL,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            credits_change INTEGER DEFAULT 0,
            seen INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Usage logs table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usage_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT NOT NULL,
            text_preview TEXT,
            text_length INTEGER,
            voice TEXT,
            ip_address TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()


def generate_coupon_code(coupon_type):
    """Generate a unique coupon code"""
    random_part = secrets.token_hex(4).upper()
    sig_data = f"{coupon_type}-{random_part}-{SECRET_KEY}"
    signature = hashlib.sha256(sig_data.encode()).hexdigest()[:4].upper()
    return f"{coupon_type}-{random_part}-{signature}"


def get_or_create_license(device_id):
    """Get existing license or create free tier"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM licenses WHERE device_id = ?", (device_id,))
    license_data = cursor.fetchone()
    
    if not license_data:
        today = datetime.now().strftime("%Y-%m-%d")
        cursor.execute('''
            INSERT INTO licenses (device_id, tier, credits, unlimited, daily_used, daily_reset, last_active)
            VALUES (?, 'free', 0, 0, 0, ?, ?)
        ''', (device_id, today, datetime.now().isoformat()))
        conn.commit()
        cursor.execute("SELECT * FROM licenses WHERE device_id = ?", (device_id,))
        license_data = cursor.fetchone()
    else:
        # Update last active
        cursor.execute("UPDATE licenses SET last_active = ? WHERE device_id = ?", 
                      (datetime.now().isoformat(), device_id))
        conn.commit()
    
    conn.close()
    return dict(license_data)


def check_daily_reset(license_data):
    """Check and reset daily usage if needed"""
    today = datetime.now().strftime("%Y-%m-%d")
    if license_data.get('daily_reset') != today:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE licenses SET daily_used = 0, daily_reset = ?, updated_at = CURRENT_TIMESTAMP
            WHERE device_id = ?
        ''', (today, license_data['device_id']))
        conn.commit()
        conn.close()
        license_data['daily_used'] = 0
        license_data['daily_reset'] = today
    return license_data


def check_expiry(license_data):
    """Check if license expired, reset to free if so"""
    if license_data['expires']:
        expiry = datetime.strptime(license_data['expires'], "%Y-%m-%d")
        if datetime.now() > expiry:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE licenses 
                SET tier = 'free', credits = 0, unlimited = 0, expires = NULL, updated_at = CURRENT_TIMESTAMP
                WHERE device_id = ?
            ''', (license_data['device_id'],))
            conn.commit()
            conn.close()
            license_data['tier'] = 'free'
            license_data['credits'] = 0
            license_data['unlimited'] = 0
            license_data['expires'] = None
    return license_data


# ==================== API ENDPOINTS ====================

@app.route('/')
def admin_panel():
    """Admin dashboard"""
    conn = get_db()
    cursor = conn.cursor()
    
    # Get stats
    cursor.execute("SELECT COUNT(*) as total FROM coupons")
    total_coupons = cursor.fetchone()['total']
    
    cursor.execute("SELECT COUNT(*) as used FROM coupons WHERE used = 1")
    used_coupons = cursor.fetchone()['used']
    
    cursor.execute("SELECT COUNT(*) as total FROM licenses")
    total_users = cursor.fetchone()['total']
    
    cursor.execute("SELECT COUNT(*) as pro FROM licenses WHERE tier = 'pro'")
    pro_users = cursor.fetchone()['pro']
    
    cursor.execute("SELECT COUNT(*) as suspended FROM licenses WHERE suspended = 1")
    suspended_users = cursor.fetchone()['suspended']
    
    cursor.execute("SELECT SUM(total_generations) as total FROM licenses")
    total_generations = cursor.fetchone()['total'] or 0
    
    # Get recent coupons
    cursor.execute("SELECT * FROM coupons ORDER BY created_at DESC LIMIT 10")
    coupons = cursor.fetchall()
    
    # Get recent users
    cursor.execute("SELECT * FROM licenses ORDER BY last_active DESC LIMIT 10")
    users = cursor.fetchall()
    
    conn.close()
    
    return render_template('admin.html',
        total_coupons=total_coupons,
        used_coupons=used_coupons,
        total_users=total_users,
        pro_users=pro_users,
        suspended_users=suspended_users,
        total_generations=total_generations,
        coupons=coupons,
        users=users,
        coupon_types=COUPON_TYPES
    )


@app.route('/admin/users')
def admin_users():
    """List all users"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM licenses ORDER BY last_active DESC")
    users = cursor.fetchall()
    conn.close()
    return render_template('users.html', users=users)


@app.route('/admin/user/<device_id>')
def admin_user_detail(device_id):
    """View user details"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM licenses WHERE device_id = ?", (device_id,))
    user = cursor.fetchone()
    
    if not user:
        return "User not found", 404
    
    # Get usage logs
    cursor.execute("SELECT * FROM usage_logs WHERE device_id = ? ORDER BY created_at DESC LIMIT 50", (device_id,))
    logs = cursor.fetchall()
    
    # Get notifications
    cursor.execute("SELECT * FROM notifications WHERE device_id = ? ORDER BY created_at DESC LIMIT 20", (device_id,))
    notifications = cursor.fetchall()
    
    conn.close()
    return render_template('user_detail.html', user=user, logs=logs, notifications=notifications)


@app.route('/admin/generate', methods=['POST'])
def admin_generate():
    """Generate coupons (admin only)"""
    admin_key = request.form.get('admin_key') or request.json.get('admin_key')
    coupon_type = request.form.get('type') or request.json.get('type')
    count = int(request.form.get('count', 1) or request.json.get('count', 1))
    
    if admin_key != ADMIN_KEY:
        return jsonify({"error": "Unauthorized"}), 401
    
    if coupon_type not in COUPON_TYPES:
        return jsonify({"error": "Invalid coupon type"}), 400
    
    info = COUPON_TYPES[coupon_type]
    conn = get_db()
    cursor = conn.cursor()
    
    generated = []
    for _ in range(count):
        code = generate_coupon_code(coupon_type)
        cursor.execute('''
            INSERT INTO coupons (code, type, credits, days, unlimited)
            VALUES (?, ?, ?, ?, ?)
        ''', (code, coupon_type, info['credits'], info['days'], 1 if info['unlimited'] else 0))
        generated.append(code)
    
    conn.commit()
    conn.close()
    
    if request.form:
        return redirect(url_for('admin_panel'))
    return jsonify({"success": True, "codes": generated})


@app.route('/admin/suspend', methods=['POST'])
def admin_suspend():
    """Suspend or unsuspend a user"""
    data = request.form if request.form else request.get_json()
    admin_key = data.get('admin_key')
    device_id = data.get('device_id')
    action = data.get('action', 'suspend')
    reason = data.get('reason', '')
    
    if admin_key != ADMIN_KEY:
        return jsonify({"error": "Unauthorized"}), 401
    
    conn = get_db()
    cursor = conn.cursor()
    
    if action == 'suspend':
        cursor.execute('''
            UPDATE licenses SET suspended = 1, suspend_reason = ?, updated_at = CURRENT_TIMESTAMP
            WHERE device_id = ?
        ''', (reason, device_id))
        
        # Add notification
        cursor.execute('''
            INSERT INTO notifications (device_id, type, title, message)
            VALUES (?, 'suspend', '⚠️ Account Suspended', ?)
        ''', (device_id, reason or "Your account has been suspended."))
    else:
        cursor.execute('''
            UPDATE licenses SET suspended = 0, suspend_reason = NULL, updated_at = CURRENT_TIMESTAMP
            WHERE device_id = ?
        ''', (device_id,))
        
        cursor.execute('''
            INSERT INTO notifications (device_id, type, title, message)
            VALUES (?, 'unsuspend', '✅ Account Restored', 'Your account has been restored.')
        ''', (device_id,))
    
    conn.commit()
    conn.close()
    
    if request.form:
        return redirect(url_for('admin_user_detail', device_id=device_id))
    return jsonify({"success": True})


@app.route('/admin/bonus', methods=['POST'])
def admin_bonus():
    """Add bonus credits to user"""
    data = request.form if request.form else request.get_json()
    admin_key = data.get('admin_key')
    device_id = data.get('device_id')
    credits = int(data.get('credits', 0))
    message = data.get('message', 'You received bonus credits!')
    
    if admin_key != ADMIN_KEY:
        return jsonify({"error": "Unauthorized"}), 401
    
    if credits <= 0:
        return jsonify({"error": "Credits must be positive"}), 400
    
    conn = get_db()
    cursor = conn.cursor()
    
    # Add credits
    cursor.execute('''
        UPDATE licenses SET credits = credits + ?, tier = 'pro', updated_at = CURRENT_TIMESTAMP
        WHERE device_id = ?
    ''', (credits, device_id))
    
    # Add notification
    cursor.execute('''
        INSERT INTO notifications (device_id, type, title, message, credits_change)
        VALUES (?, 'bonus', '🎁 Bonus Credits!', ?, ?)
    ''', (device_id, message, credits))
    
    conn.commit()
    conn.close()
    
    if request.form:
        return redirect(url_for('admin_user_detail', device_id=device_id))
    return jsonify({"success": True})


@app.route('/admin/penalty', methods=['POST'])
def admin_penalty():
    """Reduce credits with penalty"""
    data = request.form if request.form else request.get_json()
    admin_key = data.get('admin_key')
    device_id = data.get('device_id')
    credits = int(data.get('credits', 0))
    reason = data.get('reason', 'Credits deducted')
    
    if admin_key != ADMIN_KEY:
        return jsonify({"error": "Unauthorized"}), 401
    
    if credits <= 0:
        return jsonify({"error": "Credits must be positive"}), 400
    
    conn = get_db()
    cursor = conn.cursor()
    
    # Reduce credits (don't go below 0)
    cursor.execute('''
        UPDATE licenses SET credits = MAX(0, credits - ?), updated_at = CURRENT_TIMESTAMP
        WHERE device_id = ?
    ''', (credits, device_id))
    
    # Add notification
    cursor.execute('''
        INSERT INTO notifications (device_id, type, title, message, credits_change)
        VALUES (?, 'penalty', '⚠️ Credits Deducted', ?, ?)
    ''', (device_id, reason, -credits))
    
    conn.commit()
    conn.close()
    
    if request.form:
        return redirect(url_for('admin_user_detail', device_id=device_id))
    return jsonify({"success": True})


# ==================== CLIENT API ENDPOINTS ====================

@app.route('/api/status', methods=['POST'])
def api_status():
    """Get license status for device"""
    data = request.get_json() or {}
    device_id = data.get('device_id')
    
    if not device_id:
        return jsonify({"error": "device_id required"}), 400
    
    license_data = get_or_create_license(device_id)
    license_data = check_daily_reset(license_data)
    license_data = check_expiry(license_data)
    
    # Check if suspended
    if license_data.get('suspended'):
        return jsonify({
            "suspended": True,
            "suspend_reason": license_data.get('suspend_reason', 'Account suspended'),
            "remaining": 0
        })
    
    # Calculate remaining
    if license_data['unlimited']:
        remaining = "unlimited"
    elif license_data['tier'] == 'pro':
        remaining = license_data['credits']
    else:
        remaining = FREE_DAILY_LIMIT - license_data['daily_used']
    
    # Tier display
    if license_data['tier'] == 'free':
        tier_display = "Free"
    elif license_data['unlimited']:
        tier_display = "Pro-UNLIMITED" if license_data['expires'] else "LIFETIME"
    else:
        tier_display = "Pro-Limited"
    
    return jsonify({
        "tier": license_data['tier'],
        "tier_display": tier_display,
        "remaining": remaining,
        "unlimited": bool(license_data['unlimited']),
        "expires": license_data['expires'],
        "daily_used": license_data['daily_used'],
        "daily_limit": FREE_DAILY_LIMIT,
        "suspended": False
    })


@app.route('/api/notifications', methods=['POST'])
def api_notifications():
    """Get unread notifications for device"""
    data = request.get_json() or {}
    device_id = data.get('device_id')
    
    if not device_id:
        return jsonify({"error": "device_id required"}), 400
    
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT * FROM notifications WHERE device_id = ? AND seen = 0 ORDER BY created_at DESC
    ''', (device_id,))
    notifications = [dict(row) for row in cursor.fetchall()]
    
    # Mark as seen
    cursor.execute('''
        UPDATE notifications SET seen = 1 WHERE device_id = ? AND seen = 0
    ''', (device_id,))
    
    conn.commit()
    conn.close()
    
    return jsonify({"notifications": notifications})


@app.route('/api/validate', methods=['POST'])
def api_validate():
    """Check if device can generate (before generation)"""
    data = request.get_json() or {}
    device_id = data.get('device_id')
    
    if not device_id:
        return jsonify({"error": "device_id required"}), 400
    
    license_data = get_or_create_license(device_id)
    license_data = check_daily_reset(license_data)
    license_data = check_expiry(license_data)
    
    # Check suspended
    if license_data.get('suspended'):
        return jsonify({"can_generate": False, "reason": "Account suspended"})
    
    can_generate = False
    
    if license_data['unlimited']:
        can_generate = True
    elif license_data['tier'] == 'pro' and license_data['credits'] > 0:
        can_generate = True
    elif license_data['tier'] == 'free' and license_data['daily_used'] < FREE_DAILY_LIMIT:
        can_generate = True
    
    return jsonify({"can_generate": can_generate})


@app.route('/api/use', methods=['POST'])
def api_use():
    """Deduct one credit and log usage"""
    data = request.get_json() or {}
    device_id = data.get('device_id')
    text = data.get('text', '')
    voice = data.get('voice', '')
    
    if not device_id:
        return jsonify({"error": "device_id required"}), 400
    
    license_data = get_or_create_license(device_id)
    license_data = check_daily_reset(license_data)
    license_data = check_expiry(license_data)
    
    conn = get_db()
    cursor = conn.cursor()
    
    # Log usage
    text_preview = text[:100] + "..." if len(text) > 100 else text
    cursor.execute('''
        INSERT INTO usage_logs (device_id, text_preview, text_length, voice, ip_address)
        VALUES (?, ?, ?, ?, ?)
    ''', (device_id, text_preview, len(text), voice, request.remote_addr))
    
    # Increment total generations
    cursor.execute('''
        UPDATE licenses SET total_generations = total_generations + 1, last_active = ?
        WHERE device_id = ?
    ''', (datetime.now().isoformat(), device_id))
    
    # Deduct credits
    if license_data['unlimited']:
        pass
    elif license_data['tier'] == 'pro' and license_data['credits'] > 0:
        new_credits = license_data['credits'] - 1
        if new_credits <= 0:
            cursor.execute('''
                UPDATE licenses SET tier = 'free', credits = 0, unlimited = 0, expires = NULL, updated_at = CURRENT_TIMESTAMP
                WHERE device_id = ?
            ''', (device_id,))
        else:
            cursor.execute('''
                UPDATE licenses SET credits = ?, updated_at = CURRENT_TIMESTAMP
                WHERE device_id = ?
            ''', (new_credits, device_id))
    else:
        cursor.execute('''
            UPDATE licenses SET daily_used = daily_used + 1, updated_at = CURRENT_TIMESTAMP
            WHERE device_id = ?
        ''', (device_id,))
    
    conn.commit()
    conn.close()
    
    return api_status()


@app.route('/api/activate', methods=['POST'])
def api_activate():
    """Activate license with coupon code"""
    data = request.get_json() or {}
    device_id = data.get('device_id')
    coupon_code = data.get('code', '').strip().upper()
    
    if not device_id:
        return jsonify({"error": "device_id required"}), 400
    if not coupon_code:
        return jsonify({"error": "Coupon code required"}), 400
    
    # Check if suspended
    license_data = get_or_create_license(device_id)
    if license_data.get('suspended'):
        return jsonify({"error": "Account is suspended"}), 403
    
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM coupons WHERE code = ?", (coupon_code,))
    coupon = cursor.fetchone()
    
    if not coupon:
        conn.close()
        return jsonify({"error": "Invalid coupon code"}), 400
    
    if coupon['used']:
        conn.close()
        return jsonify({"error": "Coupon already used"}), 400
    
    cursor.execute('''
        UPDATE coupons SET used = 1, used_by = ?, used_at = CURRENT_TIMESTAMP
        WHERE code = ?
    ''', (device_id, coupon_code))
    
    expiry = (datetime.now() + timedelta(days=coupon['days'])).strftime("%Y-%m-%d")
    
    # Get current license to preserve total_generations and ADD credits
    cursor.execute("SELECT credits, total_generations FROM licenses WHERE device_id = ?", (device_id,))
    existing = cursor.fetchone()
    
    if existing:
        # ADD new credits to existing credits (for limited coupons)
        new_credits = (existing['credits'] or 0) + coupon['credits']
        total_gen = existing['total_generations'] or 0
        
        cursor.execute('''
            UPDATE licenses SET 
                tier = 'pro', 
                credits = ?, 
                unlimited = ?, 
                expires = ?,
                coupon_used = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE device_id = ?
        ''', (new_credits, coupon['unlimited'], expiry, coupon_code, device_id))
    else:
        # New user
        cursor.execute('''
            INSERT INTO licenses (device_id, tier, credits, unlimited, expires, coupon_used, daily_used, daily_reset, total_generations, last_active, updated_at)
            VALUES (?, 'pro', ?, ?, ?, ?, 0, ?, 0, ?, CURRENT_TIMESTAMP)
        ''', (device_id, coupon['credits'], coupon['unlimited'], expiry, coupon_code, datetime.now().strftime("%Y-%m-%d"), datetime.now().isoformat()))
        new_credits = coupon['credits']
    
    conn.commit()
    conn.close()
    
    type_name = COUPON_TYPES.get(coupon['type'], {}).get('name', 'Pro')
    
    return jsonify({
        "success": True,
        "message": f"License activated: {type_name}",
        "tier": "pro",
        "credits": new_credits,
        "unlimited": bool(coupon['unlimited']),
        "expires": expiry
    })


if __name__ == '__main__':
    init_db()
    print("🔑 TTS Studio License Server")
    print("📍 Running on http://localhost:5005")
    print("👤 Admin Panel: http://localhost:5005/")
    app.run(host='0.0.0.0', port=5005, debug=True)
