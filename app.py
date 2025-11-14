   # app2.py — App principal Streamlit (router + páginas)
import os
from pathlib import Path
from datetime import datetime
import streamlit as st
import pandas as pd

# ¡DEBE SER LA PRIMERA LLAMADA A STREAMLIT!
st.set_page_config(page_title="SpendSense · Auth + SQLite + Chatbot",
                   page_icon="🧠", layout="wide")

import db  # capa SQLite y CRUD
from auth_ui2 import (
    show_login,
    show_signup,
    show_change_password,
    logout,
    is_authenticated,
)

# --- Rerun compatible con todas las versiones de Streamlit ---
def _rerun():
    try:
        st.rerun()
    except Exception:
        try:
            st.experimental_rerun()  # versiones antiguas
        except Exception:
            pass

# =========================
# Utilidades varias
# =========================
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

def _save_uploaded_file(file, prefix: str) -> str:
    """Guarda un UploadedFile/camera_input y devuelve ruta local (str)."""
    ext = ".png"
    name = f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{ext}"
    dest = UPLOAD_DIR / name
    dest.write_bytes(file.getbuffer())
    return str(dest)

def _safe_link_button(label: str, url: str, key: str | None = None):
    """Usa link_button si existe; si no, cae a un enlace normal."""
    try:
        st.link_button(label, url, key=key)
    except Exception:
        st.markdown(f"[{label}]({url})")

# =========================
# API Key helpers (IA)
# =========================
def _get_api_key() -> str:
    # 1) app_secrets.py local
    try:
        from app_secrets import OPENAI_API_KEY as _KEY
        if _KEY:
            return _KEY
    except Exception:
        pass
    # 2) st.secrets (si tienes .streamlit/secrets.toml)
    try:
        return st.secrets["OPENAI_API_KEY"]
    except Exception:
        pass
    # 3) variable de entorno
    return os.getenv("OPENAI_API_KEY", "")

def llm_available() -> bool:
    return bool(_get_api_key())

def call_llm(messages, model="gpt-4o-mini", temperature=0.2, fallback=""):
    """
    Si no hay clave:
      - fallback == ""       → devuelve "" (no muestra nada)
      - fallback == "local"  → devuelve un mini-resumen demo
    """
    api_key = _get_api_key()
    if not api_key:
        if fallback == "local":
            last_user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
            return f"(demo) {last_user[:120]}..."
        return ""  # silencioso

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
        # No ruido técnico para el usuario final
        return f"(IA no disponible: {e})"

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
        "Ayuda con: (a) resumir/rewrite, (b) plan de estudio, "
        "(c) explicar conceptos con ejemplos, "
        "(d) sugerir SELECT SQL de solo lectura. "
        f"Usuario: {username} | Rol: {role}."
    )

    if "chat_messages" not in st.session_state:
        st.session_state["chat_messages"] = [{"role": "system", "content": system_prompt}]

    c1, c2 = st.columns(2)
    with c1:
        st.button("🧹 Limpiar chat", key="clear_chat_btn",
                  on_click=lambda: st.session_state.update(chat_messages=[{"role": "system", "content": system_prompt}]))
    with c2:
        if llm_available():
            st.caption("IA activa ✅")
        else:
            st.caption("IA en modo demo (sin clave) · puedes activarla más tarde")

    for m in st.session_state["chat_messages"]:
        if m["role"] == "system":
            continue
        with st.chat_message(m["role"]):
            st.markdown(m["content"])

    if prompt := st.chat_input("Escribe tu mensaje..."):
        st.session_state["chat_messages"].append({"role": "user", "content": prompt})

        # Ventana de contexto
        window = st.session_state["chat_messages"][:1]
        history = [m for m in st.session_state["chat_messages"][1:]]
        if len(history) > max_turns:
            history = history[-max_turns:]
        window.extend(history)

        with st.chat_message("assistant"):
            reply = call_llm(window, temperature=temperature, fallback="local")
            st.markdown(reply)

        st.session_state["chat_messages"].append({"role": "assistant", "content": reply})

# =========================
# CO2 helpers (inspirado en Base 44)
# =========================
_MATERIAL_FACTORS = {
    "cotton": 2.1, "polyester": 5.5, "wool": 10.4, "linen": 1.7,
    "silk": 11.0, "nylon": 6.0, "mixed": 4.0, "leather": 17.0, "other": 4.0
}
_CATEGORY_WEIGHTS = {
    "shirt": 0.2, "pants": 0.5, "dress": 0.4, "jacket": 0.8, "coat": 1.2,
    "shoes": 0.6, "accessories": 0.1, "other": 0.3
}
_TRANSPORT_FACTORS = {
    "España": 0.2, "Portugal": 0.3, "Francia": 0.4, "Italia": 0.4,
    "China": 1.5, "India": 1.4, "Bangladesh": 1.6, "Vietnam": 1.5, "Turquía": 0.8
}
def estimate_co2(material: str, category: str, origin: str):
    mf = _MATERIAL_FACTORS.get(material or "other", _MATERIAL_FACTORS["other"])
    w  = _CATEGORY_WEIGHTS.get(category or "other", _CATEGORY_WEIGHTS["other"])
    tf = _TRANSPORT_FACTORS.get(origin or "", 1.0)
    co2 = mf * w * tf
    level = "low"
    if co2 > 10:
        level = "high"
    elif co2 > 5:
        level = "medium"
    return round(co2, 3), level

# =========================
# Página: Upload (imagen + etiqueta + edición)
# =========================
def upload_page():
    st.header("📤 Subir prenda")

    state = st.session_state
    state.setdefault("upl_step", "choose")
    state.setdefault("upl_product_path", None)
    state.setdefault("upl_label_path", None)
    state.setdefault("upl_data", {
        "brand": "Marca por identificar",
        "price": 50.0,
        "origin": "Desconocido",
        "material": "other",
        "category": "other",
        "title": "Prenda",
        "color": "",
        "confidence": 0.0
    })

    if state.upl_step == "choose":
        st.subheader("1) Elige imagen del producto")
        colA, colB = st.columns(2)
        with colA:
            st.write("**Galería**")
            f = st.file_uploader("Selecciona una imagen", type=["png", "jpg", "jpeg"],
                                 key="file_uploader_gallery")
            if f is not None:
                path = _save_uploaded_file(f, "product")
                state.upl_product_path = path
                state.upl_step = "label"
                st.success("✅ Imagen cargada.")
                _rerun()
        with colB:
            st.write("**Cámara**")
            cam = st.camera_input("Toma una foto", key="camera_input")
            if cam is not None:
                path = _save_uploaded_file(cam, "product")
                state.upl_product_path = path
                state.upl_step = "label"
                st.success("✅ Foto capturada.")
                _rerun()
        return

    if state.upl_step == "label":
        st.subheader("2) Sube foto de la etiqueta (opcional)")
        if state.upl_product_path:
            st.image(state.upl_product_path, caption="Imagen del producto", use_container_width=True)

        lab = st.file_uploader("Foto de etiqueta (opcional)", type=["png", "jpg", "jpeg"],
                               key="label_uploader")
        c1, c2 = st.columns(2)
        with c1:
            if lab is not None:
                path = _save_uploaded_file(lab, "label")
                state.upl_label_path = path
                st.info("Etiqueta subida. Puedes intentar autocompletar con IA (experimental).")
        with c2:
            if st.button("Saltar sin etiqueta", key="skip_label_btn"):
                state.upl_step = "review"
                _rerun()

        # Autocompletar con IA (experimental, sin OCR)
        with st.expander("🧠 Autocompletar con IA (sin OCR)"):
            if not llm_available():
                st.caption("IA en modo demo: se activará cuando configures la clave.")
            hint = st.text_input("Pista breve (ej.: 'Zara camiseta algodón 19.99 hecha en España, blanca')",
                                 key="ia_hint")
            if st.button("Proponer datos", key="ia_propose"):
                prompt = [
                    {"role": "system",
                     "content": "Devuelve JSON compactado con brand, price, origin, material, category, title, color (si conoces) y confidence (0-1)."},
                    {"role": "user", "content": f"Pista: {hint}"}
                ]
                reply = call_llm(prompt, temperature=0.2, fallback="local")
                st.write("Sugerencia IA:")
                st.code(reply)
                st.info("Revisa/edita manualmente abajo.")

        if st.button("Continuar", key="continue_to_review"):
            state.upl_step = "review"
            _rerun()
        return

    if state.upl_step == "review":
        st.subheader("3) Revisa y edita la información")
        colL, colR = st.columns([1, 1])
        with colL:
            if state.upl_product_path:
                st.image(state.upl_product_path, caption="Producto", use_container_width=True)
            if state.upl_label_path:
                st.image(state.upl_label_path, caption="Etiqueta", use_container_width=True)
        with colR:
            data = state.upl_data
            data["brand"]   = st.text_input("Marca", value=data["brand"])
            data["title"]   = st.text_input("Título/Descripción", value=data["title"])
            data["price"]   = st.number_input("Precio (€)", value=float(data["price"]), step=0.5, min_value=0.0)
            data["origin"]  = st.text_input("País de Origen", value=data["origin"])
            data["color"]   = st.text_input("Color principal (opcional)", value=data.get("color", ""))

            col1, col2 = st.columns(2)
            with col1:
                data["material"] = st.selectbox(
                    "Material",
                    ["cotton","polyester","wool","linen","silk","nylon","mixed","leather","other"],
                    index=["cotton","polyester","wool","linen","silk","nylon","mixed","leather","other"].index(data["material"])
                )
            with col2:
                data["category"] = st.selectbox(
                    "Categoría",
                    ["shirt","pants","dress","jacket","coat","shoes","accessories","other"],
                    index=["shirt","pants","dress","jacket","coat","shoes","accessories","other"].index(data["category"])
                )

            co2, lvl = estimate_co2(data["material"], data["category"], data["origin"])
            st.info(f"🌿 Estimación CO₂: **{co2} kg** (nivel: **{lvl}**)")

            if st.button("✅ Confirmar y continuar", key="confirm_review"):
                username = st.session_state.get("username", "anon")
                item_id = db.create_item(
                    created_by=username,
                    source="original",
                    title=data["title"],
                    brand=data["brand"],
                    price=float(data["price"]),
                    origin=data["origin"],
                    material=data["material"],
                    category=data["category"],
                    image_path=state.upl_product_path,
                    label_image_path=state.upl_label_path,
                    co2_estimate=co2,
                    co2_level=lvl,
                    status="in_cart",
                    action_type="none",
                    color=(data.get("color") or None),
                    confidence=float(data.get("confidence") or 0.0),
                )
                st.success("Producto guardado en tu carrito inteligente.")
                # Preparar salto a Alternativas o Carrito
                st.session_state["alt_last_item_id"] = item_id
                st.session_state.upl_step = "choose"
                st.session_state.upl_product_path = None
                st.session_state.upl_label_path = None
                st.session_state.upl_data = {
                    "brand": "Marca por identificar", "price": 50.0, "origin": "Desconocido",
                    "material": "other", "category": "other", "title": "Prenda", "color": "", "confidence": 0.0
                }
                _rerun()

        last_id = st.session_state.get("alt_last_item_id")
        if last_id:
            st.divider()
            st.subheader("¿Ver alternativas de segunda mano?")
            c1, c2 = st.columns([1,1])
            with c1:
                if st.button("Sí, buscar alternativas", key="go_alt_yes"):
                    st.session_state["go_alt_item_id"] = last_id
                    st.session_state["alt_last_item_id"] = None
                    _rerun()
            with c2:
                if st.button("No, ir al carrito", key="go_alt_no"):
                    st.session_state["alt_last_item_id"] = None
                    st.session_state["nav_radio"] = "Carrito"
                    _rerun()

        go_alt_id = st.session_state.get("go_alt_item_id")
        if go_alt_id:
            alternatives_page(go_alt_id)

# =========================
# Página: Alternativas (segunda mano)
# =========================
def _mk_search_links(brand, category, color):
    term = " ".join([x for x in [brand, category, color] if x]).strip()
    q = term.replace(" ", "+")
    return {
        "Vinted": f"https://www.vinted.es/catalog?search_text={q}",
        "Wallapop": f"https://es.wallapop.com/app/search?keywords={q}",
        "Micolet": f"https://www.micolet.com/buscar/{term.replace(' ','-')}",
        "Vestiaire": f"https://www.vestiairecollective.com/search/?q={q}"
    }

def alternatives_page(item_id: int):
    st.subheader("🛍️ Alternativas de segunda mano")
    item = db.get_item(item_id)
    if not item:
        st.warning("No encuentro el producto seleccionado.")
        return

    cols = st.columns([1, 2])
    with cols[0]:
        if item.get("image_path"):
            st.image(item["image_path"], caption=item["title"], use_container_width=True)
        st.write(f"**{item['brand']}** · €{item['price']:.2f}")
        st.caption(f"CO₂ estimado: {item['co2_estimate']} kg ({item['co2_level']})")
    with cols[1]:
        st.info("Pulsa para abrir la búsqueda en marketplaces y añade alternativas similares a tu carrito.")

        links = _mk_search_links(item.get("brand",""), item.get("category",""), item.get("color",""))
        c1,c2,c3,c4 = st.columns(4)
        _safe_link_button("Vinted", links["Vinted"], key="lk_vinted")
        _safe_link_button("Wallapop", links["Wallapop"], key="lk_wallapop")
        _safe_link_button("Micolet", links["Micolet"], key="lk_micolet")
        _safe_link_button("Vestiaire", links["Vestiaire"], key="lk_vestiaire")

        st.divider()
        st.write("**Añadir alternativa estimada** (rápido):")
        colA, colB, colC = st.columns([2,1,1])
        with colA:
            alt_title = st.text_input("Título",
                value=f"{item['brand']} {item['category']} - segunda mano",
                key=f"alt_title_{item_id}")
        with colB:
            factor = st.slider("Precio %", 30, 80, 60,
                               help="Porcentaje sobre el precio original",
                               key=f"alt_pct_{item_id}")
        with colC:
            add_alt = st.button("➕ Añadir", key=f"add_alt_{item_id}")

        if add_alt:
            alt_price = round(item["price"] * (factor/100), 2)
            _id = db.create_item(
                created_by=st.session_state.get("username","anon"),
                source="second_hand",
                title=alt_title, brand=item.get("brand",""),
                price=alt_price, origin=item.get("origin","Desconocido"),
                material=item.get("material","other"), category=item.get("category","other"),
                image_path=item.get("image_path"), label_image_path=None,
                co2_estimate=round(item.get("co2_estimate",0)*0.3,3), co2_level="low",
                status="in_cart", action_type="none",
                color=item.get("color"), confidence=0.0,
            )
            st.success(f"Alternativa añadida al carrito (id={_id}).")

        st.divider()
        st.button("Ir al carrito inteligente", key="go_cart_btn",
                  on_click=lambda: st.session_state.update(nav_radio="Carrito"))
        if st.session_state.get("nav_radio") == "Carrito":
            _rerun()

# =========================
# Página: Smart Cart
# =========================
def smart_cart_page():
    st.header("🛒 Smart Shopping Cart")

    username = st.session_state.get("username","anon")
    items = db.list_user_items(username, status="in_cart", order_by="-created_at")

    if not items:
        st.info("Tu carrito está vacío. Sube una imagen en **Subir prenda**.")
        return

    for it in items:
        with st.container():
            cols = st.columns([1, 3, 2])
            with cols[0]:
                if it.get("image_path"):
                    st.image(it["image_path"], caption=None, use_container_width=True)
            with cols[1]:
                st.markdown(f"**{it['title']}**")
                st.caption(f"{it.get('brand','')} · €{it['price']:.2f}")
                st.caption(f"Material: {it.get('material','?')} · CO₂: {it.get('co2_estimate',0)} kg ({it.get('co2_level','')})")
            with cols[2]:
                st.write("Acción")
                act = st.radio(
                    "Elige acción",
                    ["—", "He comprado el original", "He ahorrado el dinero", "He comprado segunda mano"],
                    key=f"act_{it['id']}",
                    label_visibility="collapsed",
                )
                if act == "He comprado el original":
                    if st.button("Confirmar", key=f"neg_{it['id']}"):
                        db.update_item(it["id"], status="negative",
                                       action_type="bought_original",
                                       savings=None, second_hand_price=None)
                        st.success("Acción registrada (negativa).")
                        _rerun()

                elif act == "He ahorrado el dinero":
                    if st.button("Confirmar", key=f"save_{it['id']}"):
                        db.update_item(it["id"], status="positive",
                                       action_type="saved_money",
                                       savings=it["price"], second_hand_price=None)
                        st.success("Acción registrada (positiva).")
                        _rerun()

                elif act == "He comprado segunda mano":
                    sp = st.number_input("Precio segunda mano (€)", min_value=0.0, step=0.5, key=f"sp_{it['id']}")
                    if st.button("Confirmar", key=f"2h_{it['id']}"):
                        savings = max(it["price"] - float(sp), 0.0)
                        db.update_item(it["id"], status="positive",
                                       action_type="bought_second_hand",
                                       savings=savings, second_hand_price=float(sp))
                        st.success("Acción registrada (positiva, 2ª mano).")
                        _rerun()

# =========================
# Página: Métricas
# =========================
def metrics_page():
    st.header("📈 Métricas")
    username = st.session_state.get("username","anon")
    pos = db.list_user_items(username, status="positive", order_by="-created_at")
    neg = db.list_user_items(username, status="negative", order_by="-created_at")

    total_savings = sum([(x.get("savings") or 0) for x in pos])
    total_spent   = sum([(x.get("price") or 0) for x in neg])
    co2_pos = sum([(x.get("co2_estimate") or 0) for x in pos])
    co2_neg = sum([(x.get("co2_estimate") or 0) for x in neg])

    tabs = st.tabs(["Económico", "Ambiental"])

    # --- Económico ---
    with tabs[0]:
        c1, c2 = st.columns(2)
        c1.metric("💚 Ahorro total", f"€{total_savings:.2f}")
        c2.metric("🟥 Gasto en originales", f"€{total_spent:.2f}")

        st.subheader("Acciones positivas")
        df_pos = pd.DataFrame([{
            "id": x["id"], "título": x["title"], "ahorro": x.get("savings",0.0),
            "tipo": x.get("action_type",""), "fecha": x.get("created_at","")
        } for x in pos])
        st.dataframe(df_pos, use_container_width=True)

        st.subheader("Compras originales")
        df_neg = pd.DataFrame([{
            "id": x["id"], "título": x["title"], "precio": x.get("price",0.0),
            "fecha": x.get("created_at","")
        } for x in neg])
        st.dataframe(df_neg, use_container_width=True)

        if llm_available():
            txt = call_llm([
                {"role":"system","content":"Responde con ≤60 palabras, empático y práctico."},
                {"role":"user","content": f"Ahorros: €{total_savings:.2f} en {len(pos)} acciones; Gasto original: €{total_spent:.2f} en {len(neg)} compras."}
            ])
            if txt:
                st.info(f"🧠 IA: {txt}")
        else:
            st.info(f"🧮 Resumen: Ahorros €{total_savings:.2f} ({len(pos)} acciones) · "
                    f"Gasto original €{total_spent:.2f} ({len(neg)} compras)")

    # --- Ambiental ---
    with tabs[1]:
        c1, c2 = st.columns(2)
        c1.metric("🌿 CO₂ evitado", f"{co2_pos:.2f} kg")
        c2.metric("🔥 CO₂ generado", f"{co2_neg:.2f} kg")

        st.subheader("Detalle positivo (CO₂)")
        df_pos2 = pd.DataFrame([{
            "id": x["id"], "título": x["title"], "CO₂": x.get("co2_estimate",0.0),
            "nivel": x.get("co2_level","")
        } for x in pos])
        st.dataframe(df_pos2, use_container_width=True)

        st.subheader("Detalle negativo (CO₂)")
        df_neg2 = pd.DataFrame([{
            "id": x["id"], "título": x["title"], "CO₂": x.get("co2_estimate",0.0),
            "nivel": x.get("co2_level","")
        } for x in neg])
        st.dataframe(df_neg2, use_container_width=True)

        if llm_available():
            txt = call_llm([
                {"role":"system","content":"Responde con ≤60 palabras, inspirador y educativo."},
                {"role":"user","content": f"CO₂ evitado {co2_pos:.2f} kg ({len(pos)} acciones), CO₂ generado {co2_neg:.2f} kg ({len(neg)} compras)."}
            ])
            if txt:
                st.info(f"🧠 IA: {txt}")
        else:
            st.info(f"🧮 Resumen: CO₂ evitado {co2_pos:.2f} kg · CO₂ generado {co2_neg:.2f} kg")

# =========================
# Página: Admin (ver usuarios e items)
# =========================
def admin_db_view():
    st.header("🛠️ Admin · Base de datos")
    st.caption("Ruta del fichero SQLite:")
    st.code(db.db_path(), language="bash")

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Usuarios")
        st.caption(f"Total usuarios: {db.count_users()}")
        df_users = db.list_users_df()
        st.dataframe(df_users, use_container_width=True)
        st.download_button("⬇️ Exportar usuarios",
                           df_users.to_csv(index=False).encode("utf-8"),
                           "users.csv", "text/csv", key="dl_users")
    with c2:
        st.subheader("Items")
        st.caption(f"Total items: {db.count_items()}")
        df_items = db.list_items_df()
        st.dataframe(df_items, use_container_width=True)
        st.download_button("⬇️ Exportar items",
                           df_items.to_csv(index=False).encode("utf-8"),
                           "items.csv", "text/csv", key="dl_items")

# =========================
# Router principal
# =========================
def main():
    # Init BD y seed de ejemplo
    db.init_db()
    db.seed_initial_users({
        "mario": {"password": "1234", "role": "Admin"},
        "lucas": {"password": "abcd", "role": "Manager"},
        "irene": {"password": "pass", "role": "Viewer"},
    })

    st.sidebar.title("SpendSense")
    if not is_authenticated():
        tabs = st.tabs(["Login", "Registrarse"])
        with tabs[0]:
            show_login()
        with tabs[1]:
            show_signup()
        return

    # Zona autenticada
    username = st.session_state.get("username", "—")
    role = st.session_state.get("role", "Viewer")

    st.sidebar.write(f"👤 {username} ({role})")
    st.sidebar.button("Logout", key="logout_sidebar_btn", on_click=logout)

    pages = ["Subir prenda", "Carrito", "Métricas", "Chatbot"]
    if role == "Admin":
        pages.append("Admin")
    page = st.sidebar.radio("Navegación", pages, index=0, key="nav_radio")

    if page == "Subir prenda":
        upload_page()
    elif page == "Carrito":
        smart_cart_page()
    elif page == "Métricas":
        metrics_page()
    elif page == "Chatbot":
        chatbot_page()
    elif page == "Admin" and role == "Admin":
        admin_db_view()

if __name__ == "__main__":
    main()
