import os
import streamlit as st
import pandas as pd

# Debe ser la PRIMERA llamada a Streamlit en este archivo
st.set_page_config(page_title="Auth + SQLite + Chatbot", page_icon="🔐", layout="centered")

import db  # capa SQLite
from auth_ui import (
    show_login,
    show_signup,
    show_change_password,
    logout,
    is_authenticated,
)

# =========================
# LLM (secrets.py -> st.secrets -> env var)
# =========================
def call_llm(messages, model="gpt-4o-mini", temperature=0.2):
    """
    Orden de lectura robusto de la API key:
    1) app_secrets.py  -> OPENAI_API_KEY
    2) st.secrets      -> OPENAI_API_KEY (si lo usas)
    3) variable de entorno OPENAI_API_KEY
    Si no hay clave, responde en modo local.
    """
    api_key = ""

    # 1) app_secrets.py (archivo local, evita conflicto con el stdlib 'secrets')
    try:
        from app_secrets import OPENAI_API_KEY as _KEY
        if _KEY:
            api_key = _KEY
    except Exception:
        pass

    # 2) st.secrets (protegido: no falla si no tienes secrets.toml)
    if not api_key:
        try:
            api_key = st.secrets["OPENAI_API_KEY"]
        except Exception:
            pass

    # 3) ENV
    if not api_key:
        api_key = os.getenv("OPENAI_API_KEY", "")

    if not api_key:
        user_msg = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        return f"(modo local) He recibido: {user_msg[:400]}\n\nConfigura OPENAI_API_KEY en app_secrets.py o env vars para respuestas reales."

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
        )
        return resp.choices[0].message.content
    except Exception as e:
        return f"(error LLM) {e}"
# =========================
# Chatbot UI
# =========================
def chatbot_page():
    st.header("💬 Chatbot (LLM)")

    col1, col2 = st.columns(2)
    with col1:
        mode = st.selectbox("Tono", ["Preciso", "Creativo"], index=0)
    with col2:
        max_turns = st.slider("Contexto (turnos previos)", 4, 20, 10)

    temperature = 0.2 if mode == "Preciso" else 0.8

    username = st.session_state.get("username", "usuario")
    role = st.session_state.get("role", "Viewer")
    system_prompt = (
        "Eres un asistente integrado en una app de Streamlit para estudiantes. "
        "Ayuda con: (a) resumir/rewrite, (b) planes de estudio, "
        "(c) explicar conceptos con ejemplos breves, "
        "(d) sugerir consultas SQL de solo lectura (SELECT). "
        f"Usuario: {username} | Rol: {role}."
    )

    if "chat_messages" not in st.session_state:
        st.session_state["chat_messages"] = [{"role": "system", "content": system_prompt}]

    c1, c2 = st.columns(2)
    with c1:
        st.button(
            "🧹 Limpiar chat",
            key="clear_chat_btn",
            on_click=lambda: st.session_state.update(
                chat_messages=[{"role": "system", "content": system_prompt}]
            ),
        )
    with c2:
        st.caption("Usa OPENAI_API_KEY para respuestas reales.")

    for m in st.session_state["chat_messages"]:
        if m["role"] == "system":
            continue
        with st.chat_message(m["role"]):
            st.markdown(m["content"])

    if prompt := st.chat_input("Escribe tu mensaje..."):
        st.session_state["chat_messages"].append({"role": "user", "content": prompt})

        # Ventana de contexto
        window = st.session_state["chat_messages"][:1]  # system
        history = [m for m in st.session_state["chat_messages"][1:]]
        if len(history) > max_turns:
            history = history[-max_turns:]
        window.extend(history)

        with st.chat_message("assistant"):
            reply = call_llm(window, temperature=temperature)
            st.markdown(reply)

        st.session_state["chat_messages"].append({"role": "assistant", "content": reply})


# =========================
# Panel Admin: ver tabla users
# =========================
def admin_db_view():
    """Panel Admin para visualizar la tabla users sin exponer hashes/salts."""
    st.subheader("📦 Base de datos (solo Admin)")

    st.caption("Ruta del fichero SQLite:")
    st.code(db.db_path(), language="bash")

    st.caption(f"Usuarios en la tabla: {db.count_users()}")

    # Leer filas visibles
    cols = ["id", "username", "role", "failed_attempts", "lock_until", "password_last_set", "created_at"]
    rows = []
    with db.get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, username, role, failed_attempts, lock_until, password_last_set, created_at
            FROM users ORDER BY id
        """)
        for r in cur.fetchall():
            rows.append(dict(zip(cols, r)))

    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True)

    st.download_button(
        "⬇️ Descargar CSV",
        df.to_csv(index=False).encode("utf-8"),
        "users.csv",
        "text/csv",
    )


# =========================
# App principal (router)
# =========================
def main():
    # Inicializa BD y siembra usuarios de ejemplo (solo si no existen)
    db.init_db()
    db.seed_initial_users({
        "mario": {"password": "1234", "role": "Admin"},
        "lucas": {"password": "abcd", "role": "Manager"},
        "irene": {"password": "pass", "role": "Viewer"},
    })

    st.title("🔐 Login + Sign-up + SQLite")

    if not is_authenticated():
        tabs = st.tabs(["Login", "Registrarse"])
        with tabs[0]:
            show_login()
        with tabs[1]:
            show_signup()
        return

    # === Zona autenticada ===
    username = st.session_state.get("username", "—")
    role = st.session_state.get("role", "Viewer")

    st.success(f"👋 Hola, {username} ({role})")

    # Botón logout (con key única para evitar duplicados)
    with st.sidebar:
        st.write(f"Usuario: {username}")
        st.button("Logout", key="logout_sidebar", on_click=logout)

    # Navegación: incluye Chatbot SIEMPRE
    items = ["Inicio", "Chatbot", "Dashboard", "Configuración"]
    if role == "Admin":
        items.append("Base de datos")
    page = st.sidebar.radio("Navegación", items, index=1)  # abrir en Chatbot por defecto

    if page == "Inicio":
        st.header("🏠 Inicio")
        st.write("Bienvenido a la aplicación.")
        with st.expander("🔒 Cambiar mi contraseña"):
            show_change_password(username, force=False)

    elif page == "Chatbot":
        chatbot_page()

    elif page == "Dashboard":
        st.header("📊 Dashboard")
        st.write("Aquí irían gráficas y datos.")

    elif page == "Configuración":
        if role == "Admin":
            st.header("⚙️ Configuración (Admin)")
            st.write("Opciones avanzadas…")
        else:
            st.info("No tienes permisos para esta sección.")

    elif page == "Base de datos" and role == "Admin":
        admin_db_view()


if __name__ == "__main__":
    main()
