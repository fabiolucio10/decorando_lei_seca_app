import hashlib
import json
import os
import random
import re
import sqlite3
import logging
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

try:
    import pandas as pd
except ImportError:
    pd = None

import streamlit as st

try:
    import openai
except ImportError:
    openai = None

try:
    from google import genai
except ImportError:
    try:
        import google.generativeai as genai
    except ImportError:
        genai = None

APP_DIR = Path(__file__).parent
DB_FILE = APP_DIR / "decorando_lei.db"
PDF_DIR = APP_DIR / "leis_importadas"
PDF_DIR.mkdir(exist_ok=True)

ADMIN_EMAIL = "fabiolucio277@gmail.com"

st.set_page_config(
    page_title="Decorando Lei Seca",
    page_icon="⚖",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    [data-testid="stAppDeployButton"] {display: none !important;}
    .stMarkdown, p, div[data-testid="stMarkdownContainer"] {
        text-align: justify !important;
    }
    [data-testid="stSidebarCollapseButton"] {display: block !important; visibility: visible !important;}
    [data-testid="stHeader"] {background-color: transparent !important; z-index: 999;}
    </style>
""", unsafe_allow_html=True)

REGEX_ROMANO = r'(?=[MDCLXVI])M*(?:C[MD]|D?C{0,3})(?:X[CL]|L?X{0,3})(?:I[XV]|V?I{0,3})'

def db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def hash_password(password):
    return hashlib.sha256(password.encode("utf-8")).hexdigest()

def limpar_e_formatar_texto_lei(texto):
    if not texto:
        return ""
    padroes_remover = [
        r'\((?:Redação|Incluído|Vigência|Regulamento|Vide)\s+dada?\s+pel[ao][^)]*\)',
        r'\((?:Incluído|Restabelecido|Acrescido)\s+pel[ao][^)]*\)',
        r'https?://\S+',
        r'\b\d{2}/\d{2}/\d{4},\s*\d{2}:\d{2}\b',
        r'DEL\d+compilado',
        r'\b\d+/\d+\b'
    ]
    for padrao in padroes_remover:
        texto = re.sub(padrao, '', texto, flags=re.IGNORECASE)
    texto = re.sub(r'[ \t]+', ' ', texto)
    texto = re.sub(r'\n\s*\n', '\n', texto)
    return texto.strip()

def init_db():
    conn = db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS usuarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        senha TEXT NOT NULL,
        autorizado INTEGER DEFAULT 0,
        criado_em TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS disciplinas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT UNIQUE NOT NULL
    );
    CREATE TABLE IF NOT EXISTS leis (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        disciplina_id INTEGER NOT NULL,
        nome TEXT NOT NULL,
        arquivo TEXT,
        criado_em TEXT NOT NULL,
        FOREIGN KEY(disciplina_id) REFERENCES disciplinas(id)
    );
    CREATE TABLE IF NOT EXISTS artigos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lei_id INTEGER NOT NULL,
        numero TEXT NOT NULL,
        titulo TEXT,
        texto TEXT NOT NULL,
        FOREIGN KEY(lei_id) REFERENCES leis(id)
    );
    CREATE TABLE IF NOT EXISTS filtros_salvos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario_id INTEGER,
        nome TEXT NOT NULL,
        disciplina_id INTEGER NOT NULL,
        lei_id INTEGER NOT NULL,
        artigos_ids TEXT NOT NULL,
        qtd_questoes INTEGER NOT NULL,
        criado_em TEXT NOT NULL,
        FOREIGN KEY(usuario_id) REFERENCES usuarios(id),
        FOREIGN KEY(disciplina_id) REFERENCES disciplinas(id),
        FOREIGN KEY(lei_id) REFERENCES leis(id)
    );
    CREATE TABLE IF NOT EXISTS questoes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lei_id INTEGER NOT NULL,
        artigo_id INTEGER,
        disciplina_id INTEGER NOT NULL,
        filtro_id INTEGER,
        artigo_numero TEXT,
        conteudo TEXT,
        enunciado TEXT NOT NULL,
        gabarito INTEGER NOT NULL,
        explicacao TEXT,
        dificuldade TEXT DEFAULT 'Média',
        origem TEXT DEFAULT 'regra',
        criada_em TEXT NOT NULL,
        FOREIGN KEY(filtro_id) REFERENCES filtros_salvos(id)
    );
    CREATE TABLE IF NOT EXISTS respostas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario_id INTEGER,
        questao_id INTEGER NOT NULL,
        resposta INTEGER NOT NULL,
        acertou INTEGER NOT NULL,
        respondida_em TEXT NOT NULL,
        ciclo INTEGER NOT NULL,
        FOREIGN KEY(usuario_id) REFERENCES usuarios(id),
        FOREIGN KEY(questao_id) REFERENCES questoes(id)
    );
    CREATE TABLE IF NOT EXISTS revisoes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario_id INTEGER,
        questao_id INTEGER NOT NULL,
        prioridade INTEGER DEFAULT 1,
        proxima_revisao TEXT,
        erros INTEGER DEFAULT 0,
        acertos INTEGER DEFAULT 0,
        FOREIGN KEY(usuario_id) REFERENCES usuarios(id),
        FOREIGN KEY(questao_id) REFERENCES questoes(id),
        UNIQUE(usuario_id, questao_id)
    );
    """)
    try:
        conn.execute("ALTER TABLE usuarios ADD COLUMN autorizado INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    conn.execute("UPDATE usuarios SET autorizado = 1 WHERE LOWER(TRIM(username)) = ?", (ADMIN_EMAIL,))
    conn.commit()
    conn.close()

init_db()

def cadastrar_usuario(username, senha, autorizado=0):
    conn = db()
    u_clean = username.strip().lower()
    autorizado = 1 if u_clean == ADMIN_EMAIL else 0
    try:
        conn.execute(
            "INSERT INTO usuarios (username, senha, autorizado, criado_em) VALUES (?, ?, ?, ?)",
            (u_clean, hash_password(senha), autorizado, datetime.now().isoformat())
        )
        conn.commit()
        conn.close()
        return True, "Cadastro realizado com sucesso!"
    except sqlite3.IntegrityError:
        conn.close()
        return False, "Nome de utilizador já existe!"

def listar_usuarios():
    conn = db()
    users = conn.execute("SELECT id, username, autorizado, criado_em FROM usuarios ORDER BY id").fetchall()
    conn.close()
    return users

def autenticar_usuario(username, senha):
    conn = db()
    user = conn.execute(
        "SELECT * FROM usuarios WHERE username = ? AND senha = ?",
        (username.strip().lower(), hash_password(senha))
    ).fetchone()
    conn.close()
    return user

if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False
    st.session_state["user_id"] = None
    st.session_state["username"] = None

if not st.session_state["logged_in"]:
    st.title("⚖ Decorando Lei Seca")
    tab_login, tab_cadastro = st.tabs(["🔑 Entrar", "📝 Criar Conta"])
    with tab_login:
        u = st.text_input("Utilizador / E-mail", key="login_user")
        p = st.text_input("Palavra-passe", type="password", key="login_pass")
        if st.button("Entrar", type="primary"):
            user = autenticar_usuario(u, p)
            if user and user["autorizado"] == 1:
                st.session_state["logged_in"] = True
                st.session_state["user_id"] = user["id"]
                st.session_state["username"] = user["username"]
                st.rerun()
            else:
                st.error("Utilizador incorreto ou aguardando aprovação.")
    with tab_cadastro:
        new_u = st.text_input("Utilizador / E-mail", key="cad_user")
        new_p = st.text_input("Palavra-passe", type="password", key="cad_pass")
        if st.button("Cadastrar"):
            ok, msg = cadastrar_usuario(new_u, new_p)
            if ok: st.success(msg)
            else: st.error(msg)
    st.stop()

USER_ID = st.session_state["user_id"]
USERNAME = st.session_state["username"]
is_admin_user = bool(USERNAME and USERNAME.strip().lower() == ADMIN_EMAIL)

def add_discipline(name):
    conn = db()
    conn.execute("INSERT OR IGNORE INTO disciplinas(nome) VALUES(?)", (name.strip(),))
    conn.commit()
    conn.close()

def get_disciplines():
    conn = db()
    rows = conn.execute("SELECT * FROM disciplinas ORDER BY nome").fetchall()
    conn.close()
    return rows

def add_law(discipline_id, name, filename):
    conn = db()
    cur = conn.execute(
        "INSERT INTO leis(disciplina_id, nome, arquivo, criado_em) VALUES(?,?,?,?)",
        (discipline_id, name.strip(), filename, datetime.now().isoformat())
    )
    law_id = cur.lastrowid
    conn.commit()
    conn.close()
    return law_id

def get_laws(discipline_id=None):
    conn = db()
    if discipline_id:
        rows = conn.execute("SELECT l.*, d.nome as disciplina_nome FROM leis l JOIN disciplinas d ON d.id = l.disciplina_id WHERE l.disciplina_id=? ORDER BY l.nome", (discipline_id,)).fetchall()
    else:
        rows = conn.execute("SELECT l.*, d.nome as disciplina_nome FROM leis l JOIN disciplinas d ON d.id = l.disciplina_id ORDER BY l.nome").fetchall()
    conn.close()
    return rows

def parse_and_store_pdf(pdf_path, law_id):
    if not fitz: return 0
    doc = fitz.open(pdf_path)
    full_text = "\n".join([page.get_text() for page in doc])
    doc.close()
    artigo_regex = re.compile(r'(?m)^(Art\.\s*\d+[\w\-]*[\.\º\ª]?)', re.IGNORECASE)
    partes = artigo_regex.split(full_text)
    conn = db()
    count = 0
    for i in range(1, len(partes), 2):
        num_art = partes[i].strip()
        corpo = limpar_e_formatar_texto_lei(partes[i + 1] if (i + 1) < len(partes) else "")
        if corpo:
            conn.execute("INSERT INTO artigos(lei_id, numero, titulo, texto) VALUES(?,?,?,?)", (law_id, num_art, num_art, corpo))
            count += 1
    conn.commit()
    conn.close()
    return count

def get_articles(law_id):
    conn = db()
    rows = conn.execute("SELECT * FROM artigos WHERE lei_id=? ORDER BY id", (law_id,)).fetchall()
    conn.close()
    return rows

def save_filter(name, discipline_id, law_id, article_ids, qtd_questoes):
    conn = db()
    art_str = ",".join(map(str, article_ids))
    cur = conn.execute("""
        INSERT INTO filtros_salvos (usuario_id, nome, disciplina_id, lei_id, artigos_ids, qtd_questoes, criado_em)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (USER_ID, name, discipline_id, law_id, art_str, qtd_questoes, datetime.now().isoformat()))
    f_id = cur.lastrowid
    conn.commit()
    conn.close()
    return f_id

def get_saved_filters():
    conn = db()
    rows = conn.execute("SELECT f.*, d.nome disciplina, l.nome lei FROM filtros_salvos f JOIN disciplinas d ON d.id = f.disciplina_id JOIN leis l ON l.id = f.lei_id WHERE f.usuario_id = ? ORDER BY f.id DESC", (USER_ID,)).fetchall()
    conn.close()
    return rows

def record_answer(q_id, ans):
    conn = db()
    q = conn.execute("SELECT * FROM questoes WHERE id=?", (q_id,)).fetchone()
    correct = int(ans == q["gabarito"])
    conn.execute("INSERT INTO respostas(usuario_id, questao_id, resposta, acertou, respondida_em, ciclo) VALUES(?,?,?,?,?,?)",
                 (USER_ID, q_id, ans, correct, datetime.now().isoformat(), 1))
    conn.commit()
    conn.close()
    return correct

with st.sidebar:
    st.markdown(f"👤 **{USERNAME}**")
    if st.button("🚪 Sair"):
        st.session_state.clear()
        st.rerun()

st.title("⚖ Decorando Lei Seca")

tab1, tab2, tab3, tab4, tab5 = st.tabs(["📚 Importar Leis", "🎯 Criar Caderno", "📝 Resolver Questões", "📊 Desempenho", "🔄 Revisões"])

with tab1:
    st.header("Importar Nova Lei (PDF)")
    discs = get_disciplines()
    disc_names = [d["nome"] for d in discs]
    new_d = st.text_input("Nova Disciplina:")
    if st.button("Adicionar Disciplina"):
        if new_d:
            add_discipline(new_d)
            st.rerun()
    
    disc_sel = st.selectbox("Disciplina:", [""] + disc_names, key="sel_disc_imp")
    law_title = st.text_input("Nome da Lei:")
    up_file = st.file_uploader("PDF da Lei", type=["pdf"])
    if st.button("Processar Lei"):
        if disc_sel and law_title and up_file:
            d_id = [d["id"] for d in discs if d["nome"] == disc_sel][0]
            f_path = PDF_DIR / up_file.name
            with open(f_path, "wb") as f: f.write(up_file.getbuffer())
            l_id = add_law(d_id, law_title, up_file.name)
            qtd = parse_and_store_pdf(f_path, l_id)
            st.success(f"Lei importada com {qtd} artigos!")

with tab2:
    st.header("Criar Caderno de Questões")
    discs = get_disciplines()
    disc_map = {d["nome"]: d["id"] for d in discs}
    disc_choice = st.selectbox("Disciplina para Caderno:", [""] + list(disc_map.keys()), key="cb_disc_safe")
    
    if disc_choice:
        d_id = disc_map[disc_choice]
        laws = get_laws(d_id)
        law_map = {l["nome"]: l["id"] for l in laws}
        law_choice = st.selectbox("Selecione a Lei:", [""] + list(law_map.keys()), key="cb_law_safe")
        
        if law_choice:
            l_id = law_map[law_choice]
            arts = get_articles(l_id)
            art_dict = {f"{a['numero']} - {a['texto'][:40]}...": a["id"] for a in arts}
            sel_arts = st.multiselect("Artigos (vazio para todos):", list(art_dict.keys()))
            qtd_q = st.number_input("Quantidade:", min_value=1, value=10)
            f_name = st.text_input("Nome do Caderno:")
            
            if st.button("Gerar Caderno"):
                if f_name:
                    art_ids = [art_dict[k] for k in sel_arts] if sel_arts else [a["id"] for a in arts]
                    f_id = save_filter(f_name, d_id, l_id, art_ids, qtd_q)
                    conn = db()
                    for aid in art_ids[:qtd_q]:
                        art_row = conn.execute("SELECT * FROM artigos WHERE id=?", (aid,)).fetchone()
                        if art_row:
                            conn.execute("INSERT INTO questoes(lei_id, artigo_id, disciplina_id, filtro_id, artigo_numero, enunciado, gabarito, explicacao, criada_em) VALUES(?,?,?,?,?,?,?,?,?)",
                                         (l_id, aid, d_id, f_id, art_row["numero"], f"À luz da lei, julgue: \"{art_row['texto']}\"", 1, "Dispositivo correto conforme a literalidade da lei.", datetime.now().isoformat()))
                    conn.commit()
                    conn.close()
                    st.success("Caderno gerado com sucesso!")

with tab3:
    st.header("Resolver Questões")
    filters = get_saved_filters()
    if filters:
        f_map = {f"{f['nome']} ({f['disciplina']} - {f['lei'])": f["id"] for f in filters}
        sel_f = st.selectbox("Escolha o Caderno:", list(f_map.keys()))
        f_id = f_map[sel_f]
        conn = db()
        qs = conn.execute("SELECT * FROM questoes WHERE filtro_id=?", (f_id,)).fetchall()
        conn.close()
        if qs:
            if "q_i" not in st.session_state: st.session_state["q_i"] = 0
            idx = st.session_state["q_i"]
            if idx < len(qs):
                q = qs[idx]
                st.markdown(f"**Artigo:** {q['artigo_numero']}")
                st.markdown(q["enunciado"])
                ans = st.radio("Resposta:", ["Certo", "Errado"], key=f"ans_{q['id']}")
                if st.button("Enviar Resposta"):
                    res = record_answer(q["id"], 1 if ans == "Certo" else 0)
                    if res: st.success("Correto!")
                    else: st.error("Incorreto!")
                    st.info(q["explicacao"])
                    if st.button("Próxima ➡️"):
                        st.session_state["q_i"] += 1
                        st.rerun()
            else:
                st.success("Caderno concluído!")
                if st.button("Reiniciar"):
                    st.session_state["q_i"] = 0
                    st.rerun()

with tab4:
    st.header("Desempenho")
    conn = db()
    tot = conn.execute(f"SELECT COUNT(*) n FROM respostas WHERE usuario_id={USER_ID}").fetchone()["n"]
    ac = conn.execute(f"SELECT COALESCE(SUM(acertou),0) n FROM respostas WHERE usuario_id={USER_ID}").fetchone()["n"]
    conn.close()
    st.metric("Total Respondidas", tot)
    st.metric("Acertos", ac)

with tab5:
    st.header("Revisões")
    st.info("Acompanhe suas revisões espaçadas.")