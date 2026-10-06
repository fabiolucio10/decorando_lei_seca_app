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

import fitz  # PyMuPDF
import pandas as pd
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
    .viewerBadge_container__1S-xd {display: none !important;}
    [data-testid="stStatusWidget"] {display: none !important;}
    div[class*="stAppToolbar"] {display: none !important;}
    div[class*="viewerBadge"] {display: none !important;}
    div[class*="styles_viewerBadge"] {display: none !important;}
    button[title="Manage app"] {display: none !important;}
    button[title="Gerenciar aplicativo"] {display: none !important;}
    div[class^="stActionButton"] {display: none !important;}
    
    .stMarkdown, p, div[data-testid="stMarkdownContainer"] {
        text-align: justify !important;
    }

    [data-testid="stSidebarCollapseButton"] {display: block !important; visibility: visible !important;}
    [data-testid="stHeader"] {background-color: transparent !important; z-index: 999;}
    </style>
""", unsafe_allow_html=True)

REGEX_ROMANO = r'(?:M{0,4}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{1,3}))'

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
        return True, "Cadastro realizado com sucesso!" if autorizado == 1 else "Cadastro realizado! Aguarde a liberação do administrador."
    except sqlite3.IntegrityError:
        conn.close()
        return False, "Nome de utilizador já existe!"

def alterar_status_autorizacao(user_id, status):
    conn = db()
    conn.execute("UPDATE usuarios SET autorizado = ? WHERE id = ?", (status, user_id))
    conn.commit()
    conn.close()

def excluir_usuario(user_id):
    conn = db()
    conn.execute("DELETE FROM usuarios WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()

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
            if user:
                if user["autorizado"] == 1:
                    st.session_state["logged_in"] = True
                    st.session_state["user_id"] = user["id"]
                    st.session_state["username"] = user["username"]
                    st.success(f"Bem-vindo, {user['username']}!")
                    st.rerun()
                else:
                    st.warning("⚠️ A sua conta aguarda aprovação do administrador.")
            else:
                st.error("Utilizador ou palavra-passe incorretos.")
    with tab_cadastro:
        new_u = st.text_input("Escolha um Utilizador / E-mail", key="cad_user")
        new_p = st.text_input("Escolha uma Palavra-passe", type="password", key="cad_pass")
        if st.button("Cadastrar Conta"):
            if new_u and new_p:
                ok, msg = cadastrar_usuario(new_u, new_p, autorizado=0)
                if ok: st.info(msg)
                else: st.error(msg)
            else:
                st.warning("Preencha todos os campos.")
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

def delete_law(law_id):
    conn = db()
    conn.execute("DELETE FROM artigos WHERE lei_id = ?", (law_id,))
    conn.execute("DELETE FROM leis WHERE id = ?", (law_id,))
    conn.commit()
    conn.close()

def get_laws(discipline_id=None):
    conn = db()
    if discipline_id:
        rows = conn.execute("SELECT l.*, d.nome as disciplina_nome FROM leis l JOIN disciplinas d ON d.id = l.disciplina_id WHERE l.disciplina_id=? ORDER BY l.nome", (discipline_id,)).fetchall()
    else:
        rows = conn.execute("SELECT l.*, d.nome as disciplina_nome FROM leis l JOIN disciplinas d ON d.id = l.disciplina_id ORDER BY l.nome").fetchall()
    conn.close()
    return rows

def normalizar_estrutura_dispositivo(texto):
    if not texto: return ""
    texto = texto.replace("\r", "\n")
    texto = re.sub(r'[ \t]+', ' ', texto)
    texto = re.sub(r'\s+(§\s*\d+º?|Parágrafo único)\s*', r'\n\1 ', texto, flags=re.IGNORECASE)
    padrao_inciso = rf'\s+(?={REGEX_ROMANO}\s*[-–—\.]\s*)'
    texto = re.sub(padrao_inciso, '\n', texto, flags=re.IGNORECASE)
    texto = re.sub(r'\s+(?=[a-z]\s*[\)\-]\s*)', '\n', texto, flags=re.IGNORECASE)
    texto = re.sub(r'\n{2,}', '\n', texto)
    return texto.strip()

def eh_marcador_paragrafo(linha):
    return bool(re.match(r'^(§\s*\d+º?|Parágrafo único)\b', linha.strip(), re.IGNORECASE))

def eh_marcador_inciso(linha):
    return bool(re.match(rf'^{REGEX_ROMANO}\s*[-–—\.]\s*', linha.strip(), re.IGNORECASE))

def eh_marcador_alinea(linha):
    return bool(re.match(r'^[a-z]\s*[\)\-]\s*', linha.strip(), re.IGNORECASE))

def extrair_blocos_por_marcador(texto, tipo):
    linhas = [l.strip() for l in texto.split('\n') if l.strip()]
    if not linhas: return []
    matcher = eh_marcador_paragrafo if tipo == 'paragrafo' else (eh_marcador_inciso if tipo == 'inciso' else eh_marcador_alinea)
    blocos, atual_marcador, atual_texto = [], None, []
    for linha in linhas:
        if matcher(linha):
            if atual_marcador is not None:
                blocos.append((atual_marcador, ' '.join(atual_texto).strip()))
            m = re.match(r'^(§\s*\d+º?|Parágrafo único)', linha, re.IGNORECASE) if tipo == 'paragrafo' else (re.match(rf'^({REGEX_ROMANO}\s*[-–—\.]\s*)', linha, re.IGNORECASE) if tipo == 'inciso' else re.match(r'^([a-z]\s*[\)\-]\s*)', linha, re.IGNORECASE))
            atual_marcador = m.group(1).strip() if m else linha.split()[0]
            atual_texto = [linha[m.end():].strip() if m else linha]
        else:
            if atual_marcador is not None:
                atual_texto.append(linha)
    if atual_marcador is not None:
        blocos.append((atual_marcador, ' '.join(atual_texto).strip()))
    return [(m, t) for m, t in blocos if m and t.strip()]

def fracionar_artigo_extenso(num_art, corpo_limpo):
    texto = normalizar_estrutura_dispositivo(corpo_limpo)
    paragrafos = extrair_blocos_por_marcador(texto, 'paragrafo')
    incisos = extrair_blocos_por_marcador(texto, 'inciso')
    if len(paragrafos) == 0 and len(incisos) == 0:
        return [{'numero': f"{num_art} (caput)" if len(corpo_limpo) > 100 else num_art, 'texto': corpo_limpo.strip()}]
    alvos = []
    inicio = texto.split("§")[0].split("I")[0].strip()
    if inicio and len(inicio) > 10:
        alvos.append({'numero': f'{num_art} (caput)', 'texto': inicio})
    for marcador, texto_inciso in incisos:
        if marcador and texto_inciso:
            alvos.append({'numero': f'{num_art}, Inciso {marcador.rstrip("-. ")}', 'texto': f'{marcador} {texto_inciso}'.strip()})
    for marcador_par, texto_par in paragrafos:
        if marcador_par and texto_par:
            alvos.append({'numero': f'{num_art}, {marcador_par}', 'texto': f'{marcador_par} {texto_par}'.strip()})
    return alvos if alvos else [{'numero': num_art, 'texto': corpo_limpo.strip()}]

def parse_and_store_pdf(pdf_path, law_id):
    doc = fitz.open(pdf_path)
    full_text = "\n".join([page.get_text() for page in doc])
    doc.close()
    artigo_regex = re.compile(r'(?m)^(Art\.\s*\d+[\w\-]*[\.\º\ª]?)', re.IGNORECASE)
    partes = artigo_regex.split(full_text)
    conn = db()
    quantidade = 0
    if len(partes) > 1:
        for i in range(1, len(partes), 2):
            num_art = partes[i].strip()
            corpo_limpo = limpar_e_formatar_texto_lei(partes[i + 1] if (i + 1) < len(partes) else "")
            if corpo_limpo and len(corpo_limpo) > 10:
                conn.execute("INSERT INTO artigos(lei_id, numero, titulo, texto) VALUES(?,?,?,?)", (law_id, num_art, num_art, corpo_limpo))
                quantidade += 1
    conn.commit()
    conn.close()
    return quantidade

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

def get_saved_filters(discipline_id=None):
    conn = db()
    if discipline_id:
        rows = conn.execute("SELECT f.*, d.nome disciplina, l.nome lei FROM filtros_salvos f JOIN disciplinas d ON d.id = f.disciplina_id JOIN leis l ON l.id = f.lei_id WHERE f.usuario_id = ? AND f.disciplina_id = ? ORDER BY f.id DESC", (USER_ID, discipline_id)).fetchall()
    else:
        rows = conn.execute("SELECT f.*, d.nome disciplina, l.nome lei FROM filtros_salvos f JOIN disciplinas d ON d.id = f.disciplina_id JOIN leis l ON l.id = f.lei_id WHERE f.usuario_id = ? ORDER BY f.id DESC", (USER_ID,)).fetchall()
    conn.close()
    return rows

def obter_texto_caput(artigo_id):
    if not artigo_id: return None
    conn = db()
    artigo = conn.execute("SELECT texto FROM artigos WHERE id = ?", (artigo_id,)).fetchone()
    conn.close()
    if artigo and artigo["texto"]:
        return limpar_e_formatar_texto_lei(artigo["texto"])
    return None

def alterar_texto_para_errado(texto):
    substituicoes = [
        (r'\bdeverá\b', 'poderá', 'troca de obrigação por faculdade'),
        (r'\bpoderá\b', 'deverá', 'troca de faculdade por obrigação'),
        (r'\b30 \(trinta\) dias\b', '15 (quinze) dias', 'alteração de prazo legal'),
        (r'\bpermitido\b', 'vedado', 'inversão de permissão para proibição'),
        (r'\bvedado\b', 'permitido', 'inversão de proibição para permissão')
    ]
    texto_modificado = texto
    tipo_troca = "Alteração de palavra-chave legal"
    for padrao, sub, desc in substituicoes:
        if re.search(padrao, texto_modificado, re.IGNORECASE):
            texto_modificado = re.sub(padrao, sub, texto_modificado, count=1, flags=re.IGNORECASE)
            tipo_troca = desc
            break
    return texto_modificado, tipo_troca

def obter_rotulo_dispositivo(numero_dispositivo):
    return f"Dispositivo ({numero_dispositivo})"

def obter_chave_gemini(chave_manual=None):
    if chave_manual and str(chave_manual).strip(): return str(chave_manual).strip()
    if st.session_state.get("gemini_api_key"): return str(st.session_state["gemini_api_key"]).strip()
    try:
        if "GEMINI_API_KEY" in st.secrets: return str(st.secrets["GEMINI_API_KEY"]).strip()
    except Exception: pass
    return os.getenv("GEMINI_API_KEY")

def gerar_exemplo_gemini(rotulo_dispositivo, texto_dispositivo, chave_manual=None):
    chave = obter_chave_gemini(chave_manual)
    if not chave or not genai: return None
    try:
        client = genai.Client(api_key=chave)
        prompt = f"Crie um exemplo prático curto da vida real para o dispositivo {rotulo_dispositivo}: {texto_dispositivo} em JSON com chaves situacao_real, aplicacao_regra, objetivo_regra, bizu_memorizacao."
        resp = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
        m = re.search(r'\{[\s\S]*\}', resp.text)
        if m:
            d = json.loads(m.group(0))
            return (d.get("situacao_real"), d.get("aplicacao_regra"), d.get("objetivo_regra"), d.get("bizu_memorizacao"))
    except Exception: pass
    return None

def gerar_explicacao_humana(art_num, texto_original, foi_correto=False, tipo_troca=None, exemplo_customizado=None, foi_ia=False, nome_ia="Gemini IA"):
    if exemplo_customizado and len(exemplo_customizado) == 4:
        sit, ap, obj, biz = exemplo_customizado
    else:
        sit, ap, obj, biz = f"Aplicação prática do dispositivo {art_num}.", f"Cumprimento direto da norma legal.", f"Garantir a segurança jurídica.", f"Fique atento à literalidade da lei."

    status = "O item está **CORRETO**." if foi_correto else f"O item está **ERRADO** ({tipo_troca})."
    tag = f" ✨ Gerado com {nome_ia}" if foi_ia else ""
    return f"""
    <div style="margin-bottom: 10px; font-size: 13.5px;">
        💡 <strong>Gabarito e Justificativa:</strong> {status}
    </div>
    <div style="background-color: #fffbeb; border: 1px solid #fde68a; border-radius: 12px; padding: 15px; margin-bottom: 10px;">
        <div style="font-weight: 700; color: #78350f; font-size: 14px; margin-bottom: 8px;">💡 Exemplo Prático{tag}</div>
        <p style="margin-bottom: 6px;"><strong>Situação:</strong> {sit}</p>
        <p style="margin-bottom: 6px;"><strong>Aplicação:</strong> {ap}</p>
        <p style="margin-bottom: 6px;"><strong>Objetivo:</strong> {obj}</p>
        <div style="color: #92400e; font-weight: 600; margin-top: 6px;">🎯 Bizu: {biz}</div>
    </div>
    """

def generate_questions_for_articles(discipline_id, law_id, article_ids, qtd_total, filter_id=None, motor_ia="Gemini", chave_ia_manual=None, progress_callback=None):
    conn = db()
    if article_ids:
        placeholders = ",".join("?" * len(article_ids))
        arts = conn.execute(f"SELECT * FROM artigos WHERE id IN ({placeholders}) ORDER BY id", article_ids).fetchall()
    else:
        arts = conn.execute("SELECT * FROM artigos WHERE lei_id=? ORDER BY id", (law_id,)).fetchall()
    if not arts:
        conn.close()
        return 0

    alvos = []
    for art in arts:
        for alvo in fracionar_artigo_extenso(art["numero"], limpar_e_formatar_texto_lei(art["texto"])):
            alvos.append({"art": art, "numero": alvo["numero"], "texto": alvo["texto"]})

    random.shuffle(alvos)
    generated = 0
    now = datetime.now().isoformat()
    usar_gemini = "Gemini" in motor_ia

    for i in range(qtd_total):
        alvo = alvos[i % len(alvos)]
        art = alvo["art"]
        num_disp = alvo["numero"]
        text = alvo["texto"]
        is_correct = random.choice([True, False])

        if progress_callback:
            progress_callback((i + 1) / qtd_total, f"Gerando questão {i+1} de {qtd_total}...")

        ex_ia = gerar_exemplo_gemini(num_disp, text, chave_manual=chave_ia_manual) if usar_gemini else None

        if is_correct:
            enunciado = f"De acordo com o **{num_disp}**:\n\n\"{text}\""
            gabarito = 1
            explicacao = gerar_explicacao_humana(num_disp, text, foi_correto=True, exemplo_customizado=ex_ia, foi_ia=bool(ex_ia))
        else:
            mod_text, tipo_troca = alterar_texto_para_errado(text)
            enunciado = f"De acordo com o **{num_disp}**:\n\n\"{mod_text}\""
            gabarito = 0
            explicacao = gerar_explicacao_humana(num_disp, text, foi_correto=False, tipo_troca=tipo_troca, exemplo_customizado=ex_ia, foi_ia=bool(ex_ia))

        conn.execute("""
            INSERT INTO questoes(lei_id, artigo_id, disciplina_id, filtro_id, artigo_numero, conteudo, enunciado, gabarito, explicacao, origem, criada_em)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)
        """, (law_id, art["id"], discipline_id, filter_id, num_disp, num_disp, enunciado, gabarito, explicacao, motor_ia, now))
        generated += 1

    conn.commit()
    conn.close()
    return generated

def record_answer(question_id, answer, cycle):
    conn = db()
    q = conn.execute("SELECT * FROM questoes WHERE id=?", (question_id,)).fetchone()
    correct = int(answer == q["gabarito"])
    conn.execute("INSERT INTO respostas(usuario_id, questao_id, resposta, acertou, respondida_em, ciclo) VALUES(?,?,?,?,?,?)",
                 (USER_ID, question_id, answer, correct, datetime.now().isoformat(), cycle))
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
    b_disc = pd.read_sql_query("SELECT d.nome disciplina, COUNT(r.id) respondidas, COALESCE(SUM(r.acertou),0) acertos FROM respostas r JOIN questoes q ON q.id=r.questao_id JOIN disciplinas d ON d.id=q.disciplina_id WHERE r.usuario_id = ? GROUP BY d.id", conn, params=(USER_ID,)) if pd else None
    b_filt = pd.read_sql_query("SELECT f.nome filtro, COUNT(r.id) respondidas FROM respostas r JOIN questoes q ON q.id=r.questao_id JOIN filtros_salvos f ON f.id=q.filtro_id WHERE r.usuario_id = ? GROUP BY f.id", conn, params=(USER_ID,)) if pd else None
    due = conn.execute("SELECT COUNT(*) n FROM revisoes WHERE usuario_id = ? AND proxima_revisao <= ?", (USER_ID, datetime.now().isoformat())).fetchone()["n"]
    conn.close()
    return total, hits, errors, pct, b_disc, b_filt, due

with st.sidebar:
    st.markdown(f"👤 Utilizador: **{USERNAME}**")
    if st.button("🚪 Sair / Logout"):
        st.session_state.clear()
        st.rerun()
    st.divider()
    if is_admin_user:
        st.subheader("⚙ Painel Admin")
        for u in listar_usuarios():
            st.write(f"**{u['username']}**")
            if u['username'].strip().lower() != ADMIN_EMAIL:
                if st.button(f"Excluir {u['username']}", key=f"del_u_{u['id']}"):
                    excluir_usuario(u['id'])
                    st.rerun()

st.title("⚖ Decorando Lei Seca")

if is_admin_user:
    tab1, tab2, tab3, tab4, tab5, tab_admin = st.tabs(["📚 Importar Leis", "🎯 Criar Caderno", "📝 Resolver Questões", "📊 Desempenho", "🔄 Revisões", "🛡 Painel Admin"])
else:
    tab1, tab2, tab3, tab4, tab5 = st.tabs(["📚 Importar Leis", "🎯 Criar Caderno", "📝 Resolver Questões", "📊 Desempenho", "🔄 Revisões"])

with tab1:
    st.header("Importar Nova Lei (PDF)")
    discs = get_disciplines()
    disc_names = [d["nome"] for d in discs]
    col1, col2 = st.columns(2)
    with col1:
        new_disc = st.text_input("Nova Disciplina:")
        if st.button("Cadastrar Disciplina"):
            if new_disc:
                add_discipline(new_disc)
                st.success(f"Disciplina '{new_disc}' cadastrada!")
                st.rerun()
    with col2:
        disc_sel = st.selectbox("Selecione a Disciplina:", [""] + disc_names)
    law_title = st.text_input("Nome da Lei:")
    uploaded_file = st.file_uploader("Ficheiro PDF", type=["pdf"])
    if st.button("Processar e Salvar Lei"):
        if disc_sel and law_title and uploaded_file:
            d_id = [d["id"] for d in discs if d["nome"] == disc_sel][0]
            file_path = PDF_DIR / uploaded_file.name
            with open(file_path, "wb") as f: f.write(uploaded_file.getbuffer())
            law_id = add_law(d_id, law_title, uploaded_file.name)
            qtd = parse_and_store_pdf(file_path, law_id)
            st.success(f"Lei processada! {qtd} artigos importados.")

with tab2:
    st.header("Criar Caderno de Questões por Filtro")
    discs = get_disciplines()
    disc_dict = {d["nome"]: d["id"] for d in discs}
    disc_f = st.selectbox("Disciplina:", [""] + list(disc_dict.keys()), key="f_disc")
    if disc_f:
        d_id = disc_dict[disc_f]
        laws = get_laws(d_id)
        law_dict = {l["nome"]: l["id"] for l in laws}
        law_f = st.selectbox("Lei:", [""] + list(law_dict.keys()), key="f_law")
        if law_f:
            l_id = law_dict[law_f]
            articles = get_articles(l_id)
            art_dict = {f"{a['numero']} - {a['texto'][:50]}...": a["id"] for a in articles}
            selected_arts = st.multiselect("Artigos (vazio para todos):", list(art_dict.keys()))
            qtd_q = st.number_input("Quantidade de Questões:", min_value=1, value=10)
            filter_name = st.text_input("Nome do Caderno / Filtro:")
            if st.button("Salvar Caderno e Gerar Questões", type="primary"):
                if filter_name:
                    art_ids = [art_dict[k] for k in selected_arts] if selected_arts else [a["id"] for a in articles]
                    f_id = save_filter(filter_name, d_id, l_id, art_ids, qtd_q)
                    generate_questions_for_articles(d_id, l_id, art_ids, qtd_q, filter_id=f_id)
                    st.success(f"Caderno '{filter_name}' criado com sucesso!")

with tab3:
    st.header("Resolver Questões")
    saved_filters = get_saved_filters()
    if not saved_filters:
        st.info("Nenhum caderno criado ainda.")
    else:
        filter_map = {f"{f['nome']} ({f['disciplina']} - {f['lei']})": f["id"] for f in saved_filters}
        sel_f_label = st.selectbox("Escolha o Caderno:", list(filter_map.keys()))
        f_id = filter_map[sel_f_label]
        conn = db()
        questoes = conn.execute("SELECT * FROM questoes WHERE filtro_id=?", (f_id,)).fetchall()
        conn.close()
        if not questoes:
            st.warning("Este caderno não possui questões.")
        else:
            if "q_idx" not in st.session_state: st.session_state["q_idx"] = 0
            idx = st.session_state["q_idx"]
            if idx >= len(questoes):
                st.success("Concluiu todas as questões deste caderno!")
                if st.button("Recomeçar"):
                    st.session_state["q_idx"] = 0
                    st.rerun()
            else:
                q = questoes[idx]
                st.markdown(f"**Dispositivo:** `{q['artigo_numero']}`")
                st.markdown(q["enunciado"])
                resp = st.radio("Sua resposta:", ["Certo", "Errado"], key=f"ans_{q['id']}")
                if st.button("Responder", type="primary"):
                    val = 1 if resp == "Certo" else 0
                    acertou = record_answer(q["id"], val, cycle=1)
                    if acertou: st.success("✨ Correto!")
                    else: st.error("❌ Incorreto!")
                    st.markdown(q["explicacao"], unsafe_allow_html=True)
                    if st.button("Próxima Questão ➡️"):
                        st.session_state["q_idx"] += 1
                        st.rerun()

with tab4:
    st.header("Seu Desempenho")
    tot, ac, err, pct, b_disc, b_filt, due = stats()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Respondidas", tot)
    c2.metric("Acertos", ac)
    c3.metric("Erros", err)
    c4.metric("Aproveitamento", f"{pct:.1f}%")
    if st.button("Zerar Histórico"):
        zerar_historico_dashboard()
        st.success("Histórico zerado!")
        st.rerun()

with tab5:
    st.header("Revisão Espaçada")
    tot, ac, err, pct, b_disc, b_filt, due = stats()
    st.metric("Questões Pendentes", due)
    st.info("Utilize os cadernos para alimentar suas revisões.")

if is_admin_user:
    with tab_admin:
        st.header("🛡 Painel Admin")
        for u in listar_usuarios():
            st.write(f"Utilizador: {u['username']} | Autorizado: {u['autorizado']}")