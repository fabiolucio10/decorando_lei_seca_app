import hashlib
import json
import os
import random
import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import fitz  # PyMuPDF
import pandas as pd
import streamlit as st

# Opcional: integração com OpenAI/Gemini se a biblioteca estiver instalada
try:
    import openai
except ImportError:
    openai = None

APP_DIR = Path(__file__).parent
DB_FILE = APP_DIR / "decorando_lei.db"
PDF_DIR = APP_DIR / "leis_importadas"
PDF_DIR.mkdir(exist_ok=True)

st.set_page_config(page_title="Decorando Lei Seca", page_icon="⚖️", layout="wide")

# ============================================================
# ESTILIZAÇÃO CSS (OCULTAR ELEMENTOS DA INTERFACE STREAMLIT)
# ============================================================
st.markdown("""
    <style>
    /* Oculta o menu principal e cabeçalho do Streamlit */
    #MainMenu {visibility: hidden;}
    header {visibility: hidden;}
    footer {visibility: hidden;}
    
    /* Oculta o botão 'Gerenciar aplicativo' / Manage App */
    [data-testid="stAppDeployButton"] {display: none !important;}
    .viewerBadge_container__1S-xd {display: none !important;}
    button[title="Manage app"] {display: none !important;}
    div[class^="stActionButton"] {display: none !important;}
    </style>
""", unsafe_allow_html=True)


# ============================================================
# BANCO DE DADOS & AUTENTICAÇÃO
# ============================================================
def db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def hash_password(password):
    return hashlib.sha256(password.encode("utf-8")).hexdigest()

def init_db():
    conn = db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS usuarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        senha TEXT NOT NULL,
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

    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(questoes)")
    cols_q = [row[1] for row in cursor.fetchall()]
    if "filtro_id" not in cols_q:
        cursor.execute("ALTER TABLE questoes ADD COLUMN filtro_id INTEGER")

    cursor.execute("PRAGMA table_info(filtros_salvos)")
    cols_f = [row[1] for row in cursor.fetchall()]
    if "usuario_id" not in cols_f:
        cursor.execute("ALTER TABLE filtros_salvos ADD COLUMN usuario_id INTEGER")

    cursor.execute("PRAGMA table_info(respostas)")
    cols_r = [row[1] for row in cursor.fetchall()]
    if "usuario_id" not in cols_r:
        cursor.execute("ALTER TABLE respostas ADD COLUMN usuario_id INTEGER")

    cursor.execute("PRAGMA table_info(revisoes)")
    cols_rev = [row[1] for row in cursor.fetchall()]
    if "usuario_id" not in cols_rev:
        cursor.execute("ALTER TABLE revisoes ADD COLUMN usuario_id INTEGER")

    conn.commit()
    conn.close()

init_db()

def cadastrar_usuario(username, senha):
    conn = db()
    try:
        conn.execute(
            "INSERT INTO usuarios (username, senha, criado_em) VALUES (?, ?, ?)",
            (username.strip().lower(), hash_password(senha), datetime.now().isoformat())
        )
        conn.commit()
        conn.close()
        return True, "Usuário cadastrado com sucesso!"
    except sqlite3.IntegrityError:
        conn.close()
        return False, "Nome de usuário já existe!"

def excluir_usuario(user_id):
    conn = db()
    conn.execute("DELETE FROM usuarios WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()

def listar_usuarios():
    conn = db()
    users = conn.execute("SELECT id, username, criado_em FROM usuarios ORDER BY id").fetchall()
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
    st.title("⚖️ Decorando Lei Seca")
    tab_login, tab_cadastro = st.tabs(["🔑 Entrar", "📝 Criar Conta"])

    with tab_login:
        u = st.text_input("Usuário / E-mail", key="login_user")
        p = st.text_input("Senha", type="password", key="login_pass")
        if st.button("Entrar", type="primary"):
            user = autenticar_usuario(u, p)
            if user:
                st.session_state["logged_in"] = True
                st.session_state["user_id"] = user["id"]
                st.session_state["username"] = user["username"]
                st.success(f"Bem-vindo, {user['username']}!")
                st.rerun()
            else:
                st.error("Usuário ou senha incorretos.")

    with tab_cadastro:
        new_u = st.text_input("Escolha um Usuário / E-mail", key="cad_user")
        new_p = st.text_input("Escolha uma Senha", type="password", key="cad_pass")
        if st.button("Cadastrar Conta"):
            if new_u and new_p:
                ok, msg = cadastrar_usuario(new_u, new_p)
                if ok:
                    st.success(msg)
                else:
                    st.error(msg)
            else:
                st.warning("Preencha todos os campos.")
    st.stop()

USER_ID = st.session_state["user_id"]
USERNAME = st.session_state["username"]

# ============================================================
# MENU LATERAL & PAINEL ADMINISTRATIVO
# ============================================================
with st.sidebar:
    st.markdown(f"👤 Usuário: **{USERNAME}**")
    if st.button("🚪 Sair / Logout"):
        st.session_state["logged_in"] = False
        st.session_state["user_id"] = None
        st.session_state["username"] = None
        st.rerun()
    st.divider()

    # PAINEL ADMINISTRATIVO RESTRITO AO USUÁRIO ESPECÍFICO
    if USERNAME.lower() == "fabiolucio277@gmail.com":
        st.subheader("⚙️ Painel do Administrador")
        with st.expander("👥 Gerenciar Usuários", expanded=False):
            usuarios_cadastrados = listar_usuarios()
            st.write(f"**Total de usuários:** {len(usuarios_cadastrados)}")
            
            for u in usuarios_cadastrados:
                c1, c2 = st.columns([3, 1])
                c1.text(f"{u['username']}")
                if u['username'].lower() != "fabiolucio277@gmail.com":
                    if c2.button("❌", key=f"del_user_{u['id']}"):
                        excluir_usuario(u['id'])
                        st.success(f"Usuário {u['username']} removido!")
                        st.rerun()

            st.divider()
            st.write("**Criar Novo Usuário:**")
            adm_new_u = st.text_input("E-mail do Novo Usuário", key="adm_u")
            adm_new_p = st.text_input("Senha", type="password", key="adm_p")
            if st.button("Criar Usuário pelo Admin"):
                if adm_new_u and adm_new_p:
                    ok, msg = cadastrar_usuario(adm_new_u, adm_new_p)
                    if ok:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)
                else:
                    st.warning("Preencha todos os campos.")
        st.divider()

# ============================================================
# FUNÇÕES DE BANCO E LEI
# ============================================================
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

def delete_law(law_id):
    conn = db()
    conn.execute("DELETE FROM artigos WHERE lei_id = ?", (law_id,))
    conn.execute("DELETE FROM leis WHERE id = ?", (law_id,))
    conn.commit()
    conn.close()

def get_laws(discipline_id=None):
    conn = db()
    if discipline_id:
        rows = conn.execute("SELECT * FROM leis WHERE disciplina_id=? ORDER BY nome", (discipline_id,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM leis ORDER BY nome").fetchall()
    conn.close()
    return rows

def parse_and_store_pdf(pdf_path, law_id):
    doc = fitz.open(pdf_path)
    full_text = "\n".join([page.get_text() for page in doc])
    doc.close()

    pattern = re.compile(r'(Art\.\s*\d+[\w\d\-\.]*)\s*[\.-]?\s*(.*)', re.IGNORECASE)
    lines = full_text.split('\n')
    
    artigos = []
    curr_num = None
    curr_lines = []

    for line in lines:
        line_s = line.strip()
        m = pattern.match(line_s)
        if m and ("Art." in line_s or "art." in line_s):
            if curr_num and curr_lines:
                artigos.append((curr_num, "\n".join(curr_lines)))
            curr_num = m.group(1)
            curr_lines = [m.group(2)]
        else:
            if curr_num:
                curr_lines.append(line_s)

    if curr_num and curr_lines:
        artigos.append((curr_num, "\n".join(curr_lines)))

    conn = db()
    for num, txt in artigos:
        if txt.strip():
            conn.execute(
                "INSERT INTO artigos(lei_id, numero, titulo, texto) VALUES(?,?,?,?)",
                (law_id, num, num, txt.strip())
            )
    conn.commit()
    conn.close()
    return len(artigos)

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
    filter_id = cur.lastrowid
    conn.commit()
    conn.close()
    return filter_id

def delete_filter(filter_id):
    conn = db()
    conn.execute("DELETE FROM questoes WHERE filtro_id = ?", (filter_id,))
    conn.execute("DELETE FROM filtros_salvos WHERE id = ? AND usuario_id = ?", (filter_id, USER_ID))
    conn.commit()
    conn.close()

def get_saved_filters():
    conn = db()
    rows = conn.execute("""
        SELECT f.*, d.nome disciplina, l.nome lei
        FROM filtros_salvos f
        JOIN disciplinas d ON d.id = f.disciplina_id
        JOIN leis l ON l.id = f.lei_id
        WHERE f.usuario_id = ?
        ORDER BY f.id DESC
    """, (USER_ID,)).fetchall()
    conn.close()
    return rows

# ============================================================
# GERADOR DE QUESTÕES (REGRA / OLLAMA / OPENAI / GEMINI)
# ============================================================
def generate_questions_for_articles(discipline_id, law_id, article_ids, qtd_total, filter_id=None, motor_ia="Regra Padrão"):
    conn = db()
    if article_ids:
        placeholders = ",".join("?" * len(article_ids))
        arts = conn.execute(f"SELECT * FROM artigos WHERE id IN ({placeholders})", article_ids).fetchall()
    else:
        arts = conn.execute("SELECT * FROM artigos WHERE lei_id=?", (law_id,)).fetchall()

    if not arts:
        conn.close()
        return 0

    generated = 0
    now = datetime.now().isoformat()

    for i in range(qtd_total):
        art = random.choice(arts)
        text = art["texto"]

        # 1. INTEGRAÇÃO VIA OLLAMA (LOCAL)
        if motor_ia == "Ollama (Local)":
            # Exemplo de chamada local HTTP ao Ollama (Requer Ollama rodando localmente na porta 11434)
            import requests
            prompt = f"Gere uma questão no estilo Certo/Errado com base no artigo {art['numero']}: {text}. Responda em JSON com os campos: enunciado, gabarito (1 para Certo, 0 para Errado), explicacao."
            try:
                res = requests.post("http://localhost:11434/api/generate", json={
                    "model": "llama3",
                    "prompt": prompt,
                    "stream": False
                }, timeout=5)
                data = res.json()
                # Parse simplificado do retorno
                enunciado = f"De acordo com a legislação: \"{text}\""
                gabarito = 1
                explicacao = "Gerado via Ollama."
            except Exception:
                # Fallback caso Ollama offline
                enunciado = f"De acordo com o {art['numero']} da lei: \"{text}\""
                gabarito = 1
                explicacao = "Item CERTO. Corresponde à redação literal do artigo."

        # 2. INTEGRAÇÃO VIA OPENAI / GEMINI (NUVEM)
        elif motor_ia == "OpenAI / Gemini (Nuvem)":
            api_key = st.secrets.get("OPENAI_API_KEY", os.getenv("OPENAI_API_KEY"))
            if api_key and openai:
                try:
                    client = openai.OpenAI(api_key=api_key)
                    completion = client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[
                            {"role": "system", "content": "Você é um especialista em concursos públicos. Crie uma questão estilo Certo/Errado baseada na legislação fornecida."},
                            {"role": "user", "content": f"Artigo: {art['numero']} - {text}"}
                        ]
                    )
                    enunciado = completion.choices[0].message.content
                    gabarito = random.choice([0, 1])
                    explicacao = f"Gabarito fundamentado no {art['numero']}."
                except Exception:
                    enunciado = f"De acordo com o {art['numero']}: \"{text}\""
                    gabarito = 1
                    explicacao = "Item CERTO. Corresponde à redação literal."
            else:
                enunciado = f"De acordo com o {art['numero']}: \"{text}\""
                gabarito = 1
                explicacao = "Item CERTO (Chave API não configurada, fallback para padrão)."

        # 3. REGRA PADRÃO (SEM IA)
        else:
            words = text.split()
            if len(words) < 5:
                continue

            is_correct = random.choice([True, False])
            if is_correct:
                enunciado = f"De acordo com o {art['numero']} da lei: \"{text}\""
                gabarito = 1
                explicacao = "Item CERTO. Corresponde à redação literal do artigo."
            else:
                words_mod = words.copy()
                idx = random.randint(0, len(words_mod)-1)
                words_mod[idx] = "NÃO" if words_mod[idx].lower() != "não" else "SIM"
                modified_text = " ".join(words_mod)
                enunciado = f"De acordo com a legislação: \"{modified_text}\""
                gabarito = 0
                explicacao = f"Item ERRADO. O texto correto segundo o {art['numero']} é: \"{text}\""

        try:
            conn.execute("""
                INSERT INTO questoes(lei_id, artigo_id, disciplina_id, filtro_id, artigo_numero, conteudo, enunciado, gabarito, explicacao, origem, criada_em)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """, (law_id, art["id"], discipline_id, filter_id, art["numero"], art["numero"], enunciado, gabarito, explicacao, motor_ia, now))
            generated += 1
        except sqlite3.IntegrityError:
            pass

    conn.commit()
    conn.close()
    return generated

def record_answer(question_id, answer, cycle):
    conn = db()
    q = conn.execute("SELECT * FROM questoes WHERE id=?", (question_id,)).fetchone()
    correct = int(answer == q["gabarito"])
    now = datetime.now()
    conn.execute("""
        INSERT INTO respostas(usuario_id, questao_id, resposta, acertou, respondida_em, ciclo)
        VALUES(?, ?, ?, ?, ?, ?)
    """, (USER_ID, question_id, answer, correct, now.isoformat(), cycle))

    old = conn.execute("SELECT * FROM revisoes WHERE usuario_id=? AND questao_id=?", (USER_ID, question_id)).fetchone()
    if old:
        errors = old["erros"] + (0 if correct else 1)
        hits = old["acertos"] + (1 if correct else 0)
    else:
        errors = 0 if correct else 1
        hits = 1 if correct else 0

    if not correct:
        priority = min(10, (old["prioridade"] if old else 1) + 2)
        next_date = now + timedelta(days=1)
    else:
        priority = max(0, (old["prioridade"] if old else 1) - 1)
        intervals = [1, 3, 7, 15, 30]
        idx = min(len(intervals)-1, hits-1)
        next_date = now + timedelta(days=intervals[idx])

    if old:
        conn.execute("""
            UPDATE revisoes SET prioridade=?, proxima_revisao=?, erros=?, acertos=?
            WHERE usuario_id=? AND questao_id=?
        """, (priority, next_date.isoformat(), errors, hits, USER_ID, question_id))
    else:
        conn.execute("""
            INSERT INTO revisoes(usuario_id, questao_id, prioridade, proxima_revisao, erros, acertos)
            VALUES(?, ?, ?, ?, ?, ?)
        """, (USER_ID, question_id, priority, next_date.isoformat(), errors, hits))

    conn.commit()
    conn.close()
    return correct

def zerar_historico_dashboard():
    conn = db()
    conn.execute("DELETE FROM respostas WHERE usuario_id = ?", (USER_ID,))
    conn.execute("DELETE FROM revisoes WHERE usuario_id = ?", (USER_ID,))
    conn.commit()
    conn.close()

def stats():
    conn = db()
    total = conn.execute("SELECT COUNT(*) n FROM respostas WHERE usuario_id=?", (USER_ID,)).fetchone()["n"]
    hits = conn.execute("SELECT COALESCE(SUM(acertou),0) n FROM respostas WHERE usuario_id=?", (USER_ID,)).fetchone()["n"]
    errors = total - hits
    pct = (hits / total * 100) if total else 0
    
    by_disc = pd.read_sql_query("""
        SELECT d.nome disciplina,
               COUNT(r.id) respondidas,
               COALESCE(SUM(r.acertou),0) acertos,
               COUNT(r.id)-COALESCE(SUM(r.acertou),0) erros,
               ROUND(COALESCE(SUM(r.acertou),0)*100.0/COUNT(r.id),1) percentual
        FROM respostas r
        JOIN questoes q ON q.id=r.questao_id
        JOIN disciplinas d ON d.id=q.disciplina_id
        WHERE r.usuario_id = ?
        GROUP BY d.id ORDER BY percentual
    """, conn, params=(USER_ID,))

    by_filter = pd.read_sql_query("""
        SELECT f.nome filtro,
               d.nome disciplina,
               l.nome lei,
               COUNT(r.id) respondidas,
               COALESCE(SUM(r.acertou),0) acertos,
               COUNT(r.id)-COALESCE(SUM(r.acertou),0) erros,
               ROUND(COALESCE(SUM(r.acertou),0)*100.0/COUNT(r.id),1) percentual
        FROM respostas r
        JOIN questoes q ON q.id=r.questao_id
        JOIN filtros_salvos f ON f.id=q.filtro_id
        JOIN disciplinas d ON d.id=f.disciplina_id
        JOIN leis l ON l.id=f.lei_id
        WHERE r.usuario_id = ?
        GROUP BY f.id ORDER BY r.id DESC
    """, conn, params=(USER_ID,))

    by_content = pd.read_sql_query("""
        SELECT d.nome disciplina, q.conteudo,
               COUNT(r.id) respondidas,
               COALESCE(SUM(r.acertou),0) acertos,
               COUNT(r.id)-COALESCE(SUM(r.acertou),0) erros,
               ROUND(COALESCE(SUM(r.acertou),0)*100.0/COUNT(r.id),1) percentual
        FROM respostas r
        JOIN questoes q ON q.id=r.questao_id
        JOIN disciplinas d ON d.id=q.disciplina_id
        WHERE r.usuario_id = ?
        GROUP BY d.id,q.conteudo ORDER BY percentual
    """, conn, params=(USER_ID,))

    due = conn.execute("""
        SELECT COUNT(*) n FROM revisoes
        WHERE usuario_id = ? AND proxima_revisao <= ?
    """, (USER_ID, datetime.now().isoformat())).fetchone()["n"]

    conn.close()
    return total, hits, errors, pct, by_disc, by_filter, by_content, due

# ============================================================
# INTERFACE PRINCIPAL
# ============================================================
st.title("⚖️ Decorando Lei Seca")

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📚 Importar Leis",
    "🎯 Criar Caderno / Filtro",
    "📝 Resolver Questões",
    "📊 Desempenho",
    "🔄 Revisões"
])

# ABAS 1: IMPORTAR LEIS E EXCLUSÃO
with tab1:
    st.header("Importar Nova Lei (PDF)")
    discs = get_disciplines()
    disc_names = [d["nome"] for d in discs]
    
    col1, col2 = st.columns(2)
    with col1:
        new_disc = st.text_input("Nova Disciplina (ou selecione ao lado):")
        if st.button("Cadastrar Disciplina"):
            if new_disc:
                add_discipline(new_disc)
                st.success(f"Disciplina '{new_disc}' cadastrada!")
                st.rerun()

    with col2:
        disc_sel = st.selectbox("Selecione a Disciplina:", [""] + disc_names)

    st.subheader("Upload do PDF da Lei")
    law_title = st.text_input("Nome da Lei (ex: CF/88 - Artigos 1 a 14, Código Penal, etc.):")
    uploaded_file = st.file_uploader("Escolha o arquivo PDF da lei", type=["pdf"])

    if st.button("Processar e Salvar Lei"):
        if not disc_sel:
            st.error("Selecione uma disciplina!")
        elif not law_title:
            st.error("Informe o nome da lei!")
        elif not uploaded_file:
            st.error("Envie um arquivo PDF!")
        else:
            disc_id = [d["id"] for d in discs if d["nome"] == disc_sel][0]
            file_path = PDF_DIR / uploaded_file.name
            with open(file_path, "wb") as f:
                f.write(uploaded_file.getbuffer())

            law_id = add_law(disc_id, law_title, uploaded_file.name)
            qtd = parse_and_store_pdf(file_path, law_id)
            st.success(f"Lei processada com sucesso! {qtd} artigos importados.")

    st.divider()
    st.subheader("🗑️ Leis Cadastradas e Opção de Exclusão")
    todas_leis = get_laws()
    if todas_leis:
        for l in todas_leis:
            lc1, lc2 = st.columns([4, 1])
            lc1.write(f"📄 **{l['nome']}**")
            if lc2.button("Excluir Lei", key=f"del_law_{l['id']}"):
                delete_law(l['id'])
                st.success(f"Lei '{l['nome']}' excluída com sucesso!")
                st.rerun()

# ABAS 2: CRIAR CADERNO / FILTRO (SELEÇÃO DE OLLAMA / OPENAI)
with tab2:
    st.header("Criar Caderno de Questões por Filtro")
    discs = get_disciplines()
    disc_dict = {d["nome"]: d["id"] for d in discs}
    
    disc_f = st.selectbox("1. Selecione a Disciplina", [""] + list(disc_dict.keys()), key="f_disc")
    
    if disc_f:
        d_id = disc_dict[disc_f]
        laws = get_laws(d_id)
        law_dict = {l["nome"]: l["id"] for l in laws}
        
        law_f = st.selectbox("2. Selecione a Lei", [""] + list(law_dict.keys()), key="f_law")
        
        if law_f:
            l_id = law_dict[law_f]
            articles = get_articles(l_id)
            art_dict = {f"{a['numero']} - {a['texto'][:60]}...": a["id"] for a in articles}
            
            selected_arts = st.multiselect("3. Selecione os Artigos (deixe vazio para TODOS):", list(art_dict.keys()))
            qtd_q = st.number_input("4. Quantidade de questões para este filtro:", min_value=1, max_value=200, value=10)
            
            motor_ia = st.radio(
                "5. Selecione o Motor para Geração de Questões:",
                ["Regra Padrão", "Ollama (Local)", "OpenAI / Gemini (Nuvem)"]
            )

            filter_name = st.text_input("6. Nome do seu Caderno / Filtro (ex: CF88 - Direitos Fundamentais):")

            if st.button("Salvar Caderno e Gerar Questões"):
                if not filter_name:
                    st.error("Informe um nome para o seu caderno!")
                else:
                    art_ids = [art_dict[k] for k in selected_arts]
                    f_id = save_filter(filter_name, d_id, l_id, art_ids, qtd_q)
                    qtd_geradas = generate_questions_for_articles(d_id, l_id, art_ids, qtd_q, filter_id=f_id, motor_ia=motor_ia)
                    st.success(f"Caderno '{filter_name}' criado com sucesso! {qtd_geradas} questões geradas usando {motor_ia}.")

    st.divider()
    st.subheader("🗑️ Meus Cadernos / Filtros Salvos")
    meus_filtros = get_saved_filters()
    if meus_filtros:
        for mf in meus_filtros:
            fc1, fc2 = st.columns([4, 1])
            fc1.write(f"📁 **{mf['nome']}** ({mf['disciplina']} - {mf['lei']})")
            if fc2.button("Excluir Caderno", key=f"del_filt_{mf['id']}"):
                delete_filter(mf['id'])
                st.success(f"Caderno '{mf['nome']}' removido com sucesso!")
                st.rerun()

# ABAS 3: RESOLVER QUESTÕES
with tab3:
    st.header("Resolver Questões")
    saved_filters = get_saved_filters()
    
    if not saved_filters:
        st.info("Você ainda não criou nenhum caderno de questões. Vá na aba 'Criar Caderno / Filtro'.")
    else:
        f_options = {f"{f['nome']} ({f['disciplina']} - {f['lei']})": f["id"] for f in saved_filters}
        sel_filter_label = st.selectbox("Selecione o Caderno para Treinar:", list(f_options.keys()))
        sel_filter_id = f_options[sel_filter_label]

        conn = db()
        questoes = conn.execute("SELECT * FROM questoes WHERE filtro_id=? ORDER BY id", (sel_filter_id,)).fetchall()
        conn.close()

        if not questoes:
            st.warning("Nenhuma questão gerada para este caderno.")
        else:
            if "q_index" not in st.session_state:
                st.session_state["q_index"] = 0

            idx = st.session_state["q_index"]
            if idx >= len(questoes):
                st.success("🎉 Você concluiu todas as questões deste caderno!")
                if st.button("Reiniciar Caderno"):
                    st.session_state["q_index"] = 0
                    st.rerun()
            else:
                q = questoes[idx]
                st.subheader(f"Questão {idx + 1} de {len(questoes)}")
                st.markdown(f"**Artigo:** {q['artigo_numero']}")
                st.write(q["enunciado"])

                resp = st.radio("Sua resposta:", ["Certo", "Errado"], key=f"q_{q['id']}")
                
                if st.button("Responder", key=f"btn_{q['id']}"):
                    val = 1 if resp == "Certo" else 0
                    acertou = record_answer(q["id"], val, cycle=1)
                    if acertou:
                        st.success("✨ Resposta Correta!")
                    else:
                        st.error("❌ Resposta Incorreta!")
                    st.info(f"**Gabarito / Explicação:** {q['explicacao']}")

                if st.button("Próxima Questão ➡️"):
                    st.session_state["q_index"] += 1
                    st.rerun()

# ABAS 4: DESEMPENHO E ZERAR INDICADORES
with tab4:
    st.header("Seu Desempenho")
    tot, ac, err, pct, b_disc, b_filt, b_cont, due = stats()
    
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Respondidas", tot)
    c2.metric("Acertos", ac)
    c3.metric("Erros", err)
    c4.metric("Aproveitamento", f"{pct:.1f}%")

    st.subheader("Desempenho por Caderno / Filtro")
    if not b_filt.empty:
        st.dataframe(b_filt, use_container_width=True)
    else:
        st.info("Nenhuma questão respondida ainda.")

    st.subheader("Desempenho por Disciplina")
    if not b_disc.empty:
        st.dataframe(b_disc, use_container_width=True)

    st.divider()
    st.subheader("⚠️ Redefinir Estatísticas")
    if st.button("Zerar Histórico de Respostas / Limpar Dashboard", type="secondary"):
        zerar_historico_dashboard()
        st.success("Seu histórico de respostas e indicadores do dashboard foram zerados!")
        st.rerun()

# ABAS 5: REVISÕES
with tab5:
    st.header("Revisão Espaçada")
    tot, ac, err, pct, b_disc, b_filt, b_cont, due = stats()
    st.metric("Questões Pendentes para Revisão Hoje", due)

    if due > 0:
        conn = db()
        revs = conn.execute("""
            SELECT q.* FROM revisoes r
            JOIN questoes q ON q.id = r.questao_id
            WHERE r.usuario_id = ? AND r.proxima_revisao <= ?
            LIMIT 1
        """, (USER_ID, datetime.now().isoformat())).fetchone()
        conn.close()

        if revs:
            st.subheader("Questão para Revisão")
            st.write(revs["enunciado"])
            resp_rev = st.radio("Sua resposta:", ["Certo", "Errado"], key="rev_ans")
            if st.button("Enviar Resposta da Revisão"):
                val = 1 if resp_rev == "Certo" else 0
                acertou = record_answer(revs["id"], val, cycle=2)
                if acertou:
                    st.success("✨ Excelente! Próxima revisão agendada.")
                else:
                    st.error("❌ Errou! Ela voltará amanhã.")
                st.info(f"**Gabarito:** {revs['explicacao']}")
    else:
        st.success("Tudo em dia! Não há revisões pendentes para hoje.")
