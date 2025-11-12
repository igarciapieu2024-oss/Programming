import sqlite3, os, hashlib, hmac
from pathlib import Path
from datetime import datetime, timezone, timedelta

DB_PATH = Path("app.db")

# Parámetros de hashing (alineados con auth_ui)
PBKDF2_ALGO = "sha256"
PBKDF2_ITERATIONS = 200_000
SALT_BYTES = 16


def get_conn():
    return sqlite3.connect(DB_PATH)


def init_db():
    with get_conn() as conn:
        # Opcional: mejora concurrencia si abres con DBeaver a la vez
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
        except Exception:
            pass
        c = conn.cursor()
        c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            role TEXT NOT NULL DEFAULT 'Viewer',
            salt_hex TEXT NOT NULL,
            password_hash_hex TEXT NOT NULL,
            failed_attempts INTEGER NOT NULL DEFAULT 0,
            lock_until TEXT,
            password_last_set TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT
        )
        """)
        conn.commit()


# -------- hashing --------
def _hash_password(password: str) -> tuple[str, str]:
    salt = os.urandom(SALT_BYTES)
    pwd = hashlib.pbkdf2_hmac(PBKDF2_ALGO, password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return salt.hex(), pwd.hex()

def _verify_password(password: str, salt_hex: str, hash_hex: str) -> bool:
    salt = bytes.fromhex(salt_hex)
    expected = bytes.fromhex(hash_hex)  # bytes del hash guardado
    got = hashlib.pbkdf2_hmac(
        PBKDF2_ALGO,
        password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
    )
    # Comparación segura y constante en tiempo
    return hmac.compare_digest(got, expected)


# -------- helpers --------
def _row_to_dict(row):
    if not row:
        return None
    cols = [
        "id", "username", "role",
        "salt_hex", "password_hash_hex",
        "failed_attempts", "lock_until", "password_last_set",
        "created_at", "updated_at",
    ]
    return dict(zip(cols, row))

def get_user(username: str) -> dict | None:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, username, role, salt_hex, password_hash_hex, failed_attempts,
                   lock_until, password_last_set, created_at, updated_at
            FROM users WHERE username = ?
        """, (username,))
        return _row_to_dict(cur.fetchone())

def create_user(username: str, password: str, role: str = "Viewer") -> tuple[bool, str | None]:
    try:
        salt, pwh = _hash_password(password)
        now = datetime.now(timezone.utc).isoformat()
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO users (username, role, salt_hex, password_hash_hex,
                                   failed_attempts, lock_until, password_last_set,
                                   created_at, updated_at)
                VALUES (?, ?, ?, ?, 0, NULL, ?, ?, ?)
            """, (username, role, salt, pwh, now, now, now))
            conn.commit()
        return True, None
    except sqlite3.IntegrityError:
        return False, "El usuario ya existe."
    except Exception as e:
        return False, f"Error al crear usuario: {e}"

def authenticate(username: str, password: str) -> tuple[bool, dict | None]:
    u = get_user(username)
    if not u:
        return False, None
    ok = _verify_password(password, u["salt_hex"], u["password_hash_hex"])
    return ok, u if ok else None

def register_failed_attempt(username: str, max_attempts: int, lock_minutes: int):
    u = get_user(username)
    if not u:
        return
    fa = int(u.get("failed_attempts") or 0) + 1
    lock_until = u.get("lock_until")
    if fa >= max_attempts:
        lock_until = (datetime.now(timezone.utc) + timedelta(minutes=lock_minutes)).isoformat()
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            UPDATE users SET failed_attempts = ?, lock_until = ?, updated_at = ?
            WHERE username = ?
        """, (fa, lock_until, datetime.now(timezone.utc).isoformat(), username))
        conn.commit()

def reset_failed_attempts(username: str):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            UPDATE users SET failed_attempts = 0, lock_until = NULL, updated_at = ?
            WHERE username = ?
        """, (datetime.now(timezone.utc).isoformat(), username))
        conn.commit()

def clear_lock_if_expired(username: str) -> bool:
    u = get_user(username)
    if not u or not u.get("lock_until"):
        return False
    try:
        dt = datetime.fromisoformat(u["lock_until"])
    except Exception:
        return False
    if datetime.now(timezone.utc) >= dt:
        reset_failed_attempts(username)
        return True
    return False

def set_new_password(username: str, new_password: str):
    salt, pwh = _hash_password(new_password)
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            UPDATE users SET salt_hex = ?, password_hash_hex = ?,
                            password_last_set = ?, updated_at = ?
            WHERE username = ?
        """, (salt, pwh, now, now, username))
        conn.commit()

def seed_initial_users(seed: dict):
    """seed = {'mario': {'password':'1234','role':'Admin'}, ...}"""
    with get_conn() as conn:
        cur = conn.cursor()
        for username, info in seed.items():
            cur.execute("SELECT 1 FROM users WHERE username = ?", (username,))
            if cur.fetchone():
                continue
            salt, pwh = _hash_password(info["password"])
            now = datetime.now(timezone.utc).isoformat()
            cur.execute("""
                INSERT INTO users (username, role, salt_hex, password_hash_hex,
                                   failed_attempts, lock_until, password_last_set,
                                   created_at, updated_at)
                VALUES (?, ?, ?, ?, 0, NULL, ?, ?, ?)
            """, (username, info.get("role","Viewer"), salt, pwh, now, now, now))
        conn.commit()

def db_path() -> str:
    return str(DB_PATH.resolve())

def count_users() -> int:
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM users")
        return c.fetchone()[0]
