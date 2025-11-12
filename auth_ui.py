import re
import streamlit as st
from datetime import datetime, timedelta, timezone

import db  # capa SQLite

# Políticas (UI / sesión)
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 15

GLOBAL_MAX_FAILED_ATTEMPTS = 12
GLOBAL_LOCK_MINUTES = 15

PASSWORD_EXPIRY_DAYS = 90  # 0 para desactivar


# ---------- Utilidades ----------
def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def parse_iso(dt_str: str) -> datetime:
    try:
        return datetime.fromisoformat(dt_str)
    except Exception:
        return datetime.strptime(dt_str, "%Y-%m-%dT%H:%M:%S")

def validate_password(password: str) -> bool:
    if len(password) < 8:
        return False
    if not re.search(r"[A-Z]", password):               # al menos una mayúscula
        return False
    if not re.search(r"[^A-Za-z0-9]", password):        # al menos un carácter especial
        return False
    return True


# ---------- Guardas globales (por sesión de navegador) ----------
def init_global_guard():
    if "global_failed_attempts" not in st.session_state:
        st.session_state["global_failed_attempts"] = 0
    if "global_lock_until" not in st.session_state:
        st.session_state["global_lock_until"] = None

def is_global_locked() -> tuple[bool, str | None]:
    init_global_guard()
    lock_until = st.session_state.get("global_lock_until")
    if lock_until:
        dt = parse_iso(lock_until)
        if datetime.now(timezone.utc) < dt.astimezone(timezone.utc):
            minutes_left = int((dt - datetime.now(timezone.utc)).total_seconds() // 60) + 1
            return True, f"Acceso global bloqueado. Intenta de nuevo en ~{minutes_left} min."
        else:
            st.session_state["global_lock_until"] = None
            st.session_state["global_failed_attempts"] = 0
            return False, None
    return False, None

def register_global_fail():
    init_global_guard()
    st.session_state["global_failed_attempts"] += 1
    if st.session_state["global_failed_attempts"] >= GLOBAL_MAX_FAILED_ATTEMPTS:
        st.session_state["global_lock_until"] = (
            datetime.now(timezone.utc) + timedelta(minutes=GLOBAL_LOCK_MINUTES)
        ).isoformat()

def reset_global_fail():
    init_global_guard()
    st.session_state["global_failed_attempts"] = 0
    st.session_state["global_lock_until"] = None


# ---------- Lock y expiración a nivel de usuario ----------
def is_locked(user_data: dict) -> tuple[bool, str | None]:
    lock_until = user_data.get("lock_until")
    if lock_until:
        try:
            dt = parse_iso(lock_until)
            if datetime.now(timezone.utc) < dt.astimezone(timezone.utc):
                minutes_left = int((dt - datetime.now(timezone.utc)).total_seconds() // 60) + 1
                return True, f"Cuenta bloqueada por seguridad. Intenta de nuevo en ~{minutes_left} min."
            else:
                db.reset_failed_attempts(user_data["username"])  # limpiar en BD
                return False, None
        except Exception:
            return False, None
    return False, None

def is_password_expired(user_data: dict) -> bool:
    if PASSWORD_EXPIRY_DAYS <= 0:
        return False
    last_set_iso = user_data.get("password_last_set")
    if not last_set_iso:
        return True
    try:
        last_set = parse_iso(last_set_iso)
    except Exception:
        return True
    return datetime.now(timezone.utc) >= (last_set.astimezone(timezone.utc) + timedelta(days=PASSWORD_EXPIRY_DAYS))


# ---------- Sesión ----------
def is_authenticated() -> bool:
    return bool(st.session_state.get("logged_in", False))

def _ensure_session_keys():
    if "logged_in" not in st.session_state:
        st.session_state["logged_in"] = False
        st.session_state["username"] = None
        st.session_state["role"] = None
        st.session_state["must_change_password"] = False
    init_global_guard()


# ---------- UI: Sign-up ----------
def show_signup():
    _ensure_session_keys()
    st.subheader("🆕 Crear cuenta")

    with st.form("signup_form", clear_on_submit=False):
        new_user = st.text_input("Usuario")
        new_pass = st.text_input("Nueva contraseña", type="password")
        confirm  = st.text_input("Confirmar contraseña", type="password")
        role     = st.selectbox("Rol", ["Viewer", "Manager", "Admin"])
        submitted = st.form_submit_button("Registrar")

    if not submitted:
        return

    g_locked, g_msg = is_global_locked()
    if g_locked:
        st.error(f"⛔ {g_msg}")
        return

    if not new_user:
        register_global_fail()
        st.error("⚠️ El nombre de usuario no puede estar vacío.")
        return
    if not validate_password(new_pass):
        register_global_fail()
        st.error("⚠️ La contraseña debe tener mínimo 8 caracteres, al menos una mayúscula y un carácter especial.")
        return
    if new_pass != confirm:
        register_global_fail()
        st.error("⚠️ Las contraseñas no coinciden.")
        return

    ok, msg = db.create_user(new_user, new_pass, role)
    if ok:
        reset_global_fail()
        st.success("✅ Usuario registrado con éxito. Ahora puedes iniciar sesión.")
    else:
        register_global_fail()
        st.error(msg or "⚠️ No se pudo crear el usuario.")


# ---------- UI: Login ----------
def show_login():
    _ensure_session_keys()
    st.subheader("🔐 Iniciar sesión")

    with st.form("login_form", clear_on_submit=False):
        username = st.text_input("Usuario")
        password = st.text_input("Contraseña", type="password")
        submitted = st.form_submit_button("Login")

    if not submitted:
        return

    g_locked, g_msg = is_global_locked()
    if g_locked:
        st.error(f"⛔ {g_msg}")
        return

    user_data = db.get_user(username)
    if not user_data:
        register_global_fail()
        st.error("❌ Usuario o contraseña incorrectos")
        return

    locked, msg = is_locked(user_data)
    if locked:
        register_global_fail()
        st.error(f"⛔ {msg}")
        return

    ok, _ = db.authenticate(username, password)
    if not ok:
        # incrementa contador usuario + global
        db.register_failed_attempt(username, MAX_FAILED_ATTEMPTS, LOCKOUT_MINUTES)
        register_global_fail()

        # calcula restantes (usuario estimado y global actual)
        after_user = int(user_data.get("failed_attempts", 0)) + 1
        remaining_user = max(0, MAX_FAILED_ATTEMPTS - after_user)
        remaining_global = max(0, GLOBAL_MAX_FAILED_ATTEMPTS - st.session_state["global_failed_attempts"])

        if remaining_global == 0:
            st.error(f"⛔ Máximo global alcanzado. Acceso bloqueado por {GLOBAL_LOCK_MINUTES} min.")
        else:
            st.error(f"❌ Credenciales incorrectas. Restantes → Usuario: {remaining_user} | Global: {remaining_global}")
        return

    # OK → reset contadores
    db.reset_failed_attempts(username)
    reset_global_fail()

    if is_password_expired(user_data):
        st.warning("⚠️ Tu contraseña ha expirado. Debes cambiarla para continuar.")
        st.session_state["must_change_password"] = True
        st.session_state["username"] = username
        show_change_password(username, force=True)
        return

    st.session_state["logged_in"] = True
    st.session_state["username"] = username
    st.session_state["role"] = user_data.get("role", "Viewer")
    st.success(f"✅ Bienvenido {username}!")
    try:
        st.rerun()
    except Exception:
        st.experimental_rerun()


# ---------- UI: Cambio de contraseña ----------
def show_change_password(username: str, force: bool = False):
    help_txt = "Tu contraseña ha expirado, cámbiala para continuar." if force else "Actualiza tu contraseña."
    with st.form("force_pw_change", clear_on_submit=False):
        st.info(help_txt)
        current_pw = None if force else st.text_input("Contraseña actual (deja vacío si es por expiración)", type="password")
        new_pw     = st.text_input("Nueva contraseña", type="password")
        confirm_pw = st.text_input("Confirmar nueva contraseña", type="password")
        submitted  = st.form_submit_button("Actualizar")

    if not submitted:
        return

    g_locked, g_msg = is_global_locked()
    if g_locked:
        st.error(f"⛔ {g_msg}")
        return

    # si no es forzado por expiración, valida actual
    if not force:
        ok, _ = db.authenticate(username, current_pw or "")
        if not ok:
            register_global_fail()
            st.error("❌ Contraseña actual incorrecta.")
            return

    if new_pw != confirm_pw:
        register_global_fail()
        st.error("⚠️ Las contraseñas no coinciden.")
        return
    if not validate_password(new_pw):
        register_global_fail()
        st.error("⚠️ La nueva contraseña no cumple los requisitos: mínimo 8, una mayúscula y un carácter especial.")
        return

    db.set_new_password(username, new_pw)
    reset_global_fail()
    st.success("✅ Contraseña actualizada correctamente.")
    st.session_state["must_change_password"] = False
    st.session_state["logged_in"] = True
    fresh = db.get_user(username)
    st.session_state["role"] = fresh.get("role", "Viewer") if fresh else "Viewer"
    try:
        st.rerun()
    except Exception:
        st.experimental_rerun()


# ---------- UI: Logout ----------
def logout():
    st.session_state["logged_in"] = False
    st.session_state["username"] = None
    st.session_state["role"] = None
    st.session_state["must_change_password"] = False
    reset_global_fail()
    try:
        st.rerun()
    except Exception:
        st.experimental_rerun()
