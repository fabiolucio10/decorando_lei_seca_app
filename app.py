import hashlib
import html
import json
import os
import random
import re
import sqlite3
import logging
import textwrap
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

# Suporte ao SDK atualizado google-genai e ao legado google.generativeai
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

# Definição do e-mail de administrador exclusivo
ADMIN_EMAIL = "fabiolucio277@gmail.com"

# Configuração da página - Mantém a barra lateral sempre expandida por padrão
st.set_page_config(
    page_title="Decorando Lei Seca",
    page_icon="⚖",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Estilização CSS aprimorada para justificar os textos e alinhar o layout em cartões modernos
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
    
    /* Garante alinhamento justificado e legibilidade perfeita dos enunciados e citações */
    .stMarkdown, p, div[data-testid="stMarkdownContainer"] {
        text-align: justify !important;
    }

    /* Garante que o botão de alternar/expandir a sidebar permaneça sempre visível */
    [data-testid="stSidebarCollapseButton"] {display: block !important; visibility: visible !important;}
    [data-testid="stHeader"] {background-color: transparent !important; z-index: 999;}

    /* ==================== CARTÕES DA QUESTÃO ==================== */
    .questao-estudo-wrapper { margin: 10px 0 18px 0; }
    .questao-ref-card {
        background: linear-gradient(135deg, #eff6ff, #f8fafc);
        border: 1px solid #bfdbfe;
        border-left: 5px solid #2563eb;
        border-radius: 12px;
        padding: 13px 16px;
        margin-bottom: 9px;
    }
    .questao-ref-label {
        color: #1d4ed8;
        font-size: 11px;
        font-weight: 800;
        letter-spacing: .5px;
        margin-bottom: 5px;
    }
    .questao-ref-text {
        color: #1e3a8a;
        font-size: 13.5px;
        line-height: 1.55;
        font-weight: 650;
    }
    .questao-comando-card {
        background: #f5f3ff;
        border: 1px solid #ddd6fe;
        border-left: 5px solid #7c3aed;
        border-radius: 12px;
        padding: 13px 16px;
        margin-bottom: 9px;
    }
    .questao-comando-label {
        color: #6d28d9;
        font-size: 11px;
        font-weight: 800;
        letter-spacing: .5px;
        margin-bottom: 5px;
    }
    .questao-comando-text {
        color: #4c1d95;
        font-size: 13.5px;
        line-height: 1.6;
        font-weight: 600;
    }
    .questao-assertiva-card {
        background: #ffffff;
        border: 2px solid #93c5fd;
        border-radius: 14px;
        padding: 18px 20px;
        box-shadow: 0 2px 8px rgba(30, 64, 175, .07);
    }
    .questao-assertiva-label {
        color: #0f766e;
        font-size: 11px;
        font-weight: 800;
        letter-spacing: .5px;
        margin-bottom: 8px;
    }
    .questao-assertiva-text {
        color: #172033;
        font-size: 17px;
        line-height: 1.7;
        font-weight: 650;
        text-align: left;
    }
    </style>
""", unsafe_allow_html=True)

# Regex universal para algarismos romanos de I até CCC (1 a 300+), cobrindo com precisão V, X, L, XLV, etc.
REGEX_ROMANO = r'(?=[MDCLXVI])M*(?:C[MD]|D?C{0,3})(?:X[CL]|L?X{0,3})(?:I[XV]|V?I{0,3})'

def db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def hash_password(password):
    return hashlib.sha256(password.encode("utf-8")).hexdigest()

def limpar_conteudo_html_para_renderizacao(conteudo):
    """
    Remove cercas de código Markdown e normaliza HTML escapado antes da renderização.
    """
    if conteudo is None:
        return ""
    texto = str(conteudo).strip()
    texto = re.sub(r"^\s*```(?:html|HTML)?\s*", "", texto)
    texto = re.sub(r"\s*```\s*$", "", texto)
    if "&lt;div" in texto or "&lt;style" in texto or "&gt;" in texto:
        texto = html.unescape(texto)
    return texto.strip()

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
    
    if u_clean == ADMIN_EMAIL:
        autorizado = 1
    else:
        autorizado = 0

    try:
        conn.execute(
            "INSERT INTO usuarios (username, senha, autorizado, criado_em) VALUES (?, ?, ?, ?)",
            (u_clean, hash_password(senha), autorizado, datetime.now().isoformat())
        )
        conn.commit()
        conn.close()
        return True, "Cadastro realizado! Aguarde a liberação do administrador para acessar o sistema." if autorizado == 0 else "Utilizador criado e autorizado!"
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
                    st.warning("⚠️ A sua conta aguarda aprovação do administrador. Entre em contacto para liberação.")
            else:
                st.error("Utilizador ou palavra-passe incorretos.")

    with tab_cadastro:
        new_u = st.text_input("Escolha um Utilizador / E-mail", key="cad_user")
        new_p = st.text_input("Escolha uma Palavra-passe", type="password", key="cad_pass")
        if st.button("Cadastrar Conta"):
            if new_u and new_p:
                ok, msg = cadastrar_usuario(new_u, new_p, autorizado=0)
                if ok:
                    st.info(msg)
                else:
                    st.error(msg)
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
        rows = conn.execute("""
            SELECT l.*, d.nome as disciplina_nome 
            FROM leis l 
            JOIN disciplinas d ON d.id = l.disciplina_id 
            WHERE l.disciplina_id=? 
            ORDER BY d.nome, l.nome
        """, (discipline_id,)).fetchall()
    else:
        rows = conn.execute("""
            SELECT l.*, d.nome as disciplina_nome 
            FROM leis l 
            JOIN disciplinas d ON d.id = l.disciplina_id 
            ORDER BY d.nome, l.nome
        """).fetchall()
    conn.close()
    return rows

def normalizar_estrutura_dispositivo(texto):
    if not texto:
        return ""

    texto = texto.replace("\r", "\n")
    texto = re.sub(r'[ \t]+', ' ', texto)

    texto = re.sub(r'(?:;|\.|\n|\s)\s*(§\s*\d+º?|Parágrafo único)\b', r'\n\1 ', texto, flags=re.IGNORECASE)
    padrao_inciso = rf'(?:;|\.|\n|\s)\s*(?={REGEX_ROMANO}\s*[-–—\.]\s*)'
    texto = re.sub(padrao_inciso, '\n', texto, flags=re.IGNORECASE)
    texto = re.sub(r'(?:;|\.|\n|\s)\s*(?=[a-z]\s*[\)\-]\s*)', '\n', texto)
    texto = re.sub(r'(?<=[;])\s+(?=\d+[\)\.-]\s*)', '\n', texto)

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
    if not linhas:
        return []

    if tipo == 'paragrafo':
        matcher = eh_marcador_paragrafo
    elif tipo == 'inciso':
        matcher = eh_marcador_inciso
    else:
        matcher = eh_marcador_alinea

    blocos = []
    atual_marcador = None
    atual_texto = []

    for linha in linhas:
        if matcher(linha):
            if atual_marcador is not None:
                blocos.append((atual_marcador, ' '.join(atual_texto).strip()))
            
            if tipo == 'paragrafo':
                m = re.match(r'^(§\s*\d+º?|Parágrafo único)', linha, re.IGNORECASE)
            elif tipo == 'inciso':
                m = re.match(rf'^({REGEX_ROMANO}\s*[-–—\.]\s*)', linha, re.IGNORECASE)
            else:
                m = re.match(r'^([a-z]\s*[\)\-]\s*)', linha, re.IGNORECASE)

            atual_marcador = m.group(1).strip() if m else linha.split()[0]
            atual_texto = [linha[m.end():].strip() if m else linha]
        else:
            if atual_marcador is not None:
                atual_texto.append(linha)

    if atual_marcador is not None:
        blocos.append((atual_marcador, ' '.join(atual_texto).strip()))

    return [(m, t) for m, t in blocos if m and t.strip()]

def fragmentar_texto_muito_longo(rotulo_base, texto, max_chars=450):
    texto = texto.strip()
    if len(texto) <= max_chars:
        return [{'numero': rotulo_base, 'texto': texto}]

    partes = [p.strip() for p in re.split(r'(?<=;)\s+|(?<=\.)\s+', texto) if len(p.strip()) > 15]
    if len(partes) <= 1:
        return [{'numero': rotulo_base, 'texto': texto}]

    resultado = []
    acumulado = ""
    parte_idx = 1
    for p in partes:
        if len(acumulado) + len(p) + 1 <= max_chars:
            acumulado = f"{acumulado} {p}".strip()
        else:
            if acumulado:
                resultado.append({
                    'numero': f"{rotulo_base} (trecho {parte_idx})",
                    'texto': acumulado
                })
                parte_idx += 1
            acumulado = p

    if acumulado:
        resultado.append({
            'numero': f"{rotulo_base} (trecho {parte_idx})" if parte_idx > 1 else rotulo_base,
            'texto': acumulado
        })

    return resultado if resultado else [{'numero': rotulo_base, 'texto': texto}]

def fracionar_artigo_extenso(num_art, corpo_limpo):
    texto = normalizar_estrutura_dispositivo(corpo_limpo)

    paragrafos = extrair_blocos_por_marcador(texto, 'paragrafo')
    incisos = extrair_blocos_por_marcador(texto, 'inciso')

    if len(paragrafos) == 0 and len(incisos) == 0:
        if len(corpo_limpo) > 500:
            return fragmentar_texto_muito_longo(f"{num_art} (caput)", corpo_limpo)
        return [{'numero': f"{num_art} (caput)" if len(corpo_limpo) > 100 else num_art, 'texto': corpo_limpo.strip()}]

    alvos = []
    padroes_primeiro = [
        r'(?m)^§\s*\d+º?',
        r'(?m)^Parágrafo único\b',
        rf'(?m)^{REGEX_ROMANO}\s*[-–—\.]\s*'
    ]
    marcadores = []
    for padrao in padroes_primeiro:
        m = re.search(padrao, texto, re.IGNORECASE)
        if m:
            marcadores.append(m.start())

    inicio = texto[:min(marcadores)].strip() if marcadores else texto.strip()

    if inicio and len(inicio) > 10:
        inicio_limpo = re.sub(r'^Art\.\s*\d+[\w\-]*[\.\º\ª]?\s*[-–—]?\s*', '', inicio, flags=re.IGNORECASE).strip()
        if inicio_limpo:
            alvos.append({'numero': f'{num_art} (caput)', 'texto': inicio_limpo})

    posicao_primeiro_paragrafo = None
    if paragrafos:
        m = re.search(r'(?m)^(?:§\s*\d+º?|Parágrafo único)\b', texto, re.IGNORECASE)
        if m:
            posicao_primeiro_paragrafo = m.start()

    trecho_incisos_caput = texto[:posicao_primeiro_paragrafo].strip() if posicao_primeiro_paragrafo is not None else texto
    incisos_caput = extrair_blocos_por_marcador(trecho_incisos_caput, 'inciso')
    numeros_existentes = {a['numero'] for a in alvos}

    for marcador, texto_inciso in incisos_caput:
        if marcador and texto_inciso and len(texto_inciso) > 5:
            clean_marc = str(marcador).rstrip("-–—.").strip()
            num_formatado = f'{num_art}, Inciso {clean_marc}'
            
            texto_inciso_norm = normalizar_estrutura_dispositivo(texto_inciso)
            alineas = extrair_blocos_por_marcador(texto_inciso_norm, 'alinea')
            
            if len(alineas) > 0 and len(texto_inciso) > 250:
                for marc_al, txt_al in alineas:
                    if marc_al:
                        clean_al = str(marc_al).rstrip(')-').strip()
                        num_al = f"{num_formatado}, alínea {clean_al}"
                        alvos.append({'numero': num_al, 'texto': f"{marc_al} {txt_al}".strip()})
                        numeros_existentes.add(num_al)
            else:
                alvos.append({'numero': num_formatado, 'texto': f'{marcador} {texto_inciso}'.strip()})
                numeros_existentes.add(num_formatado)

    for marcador_par, texto_par in paragrafos:
        if not marcador_par or not texto_par or len(texto_par) <= 5:
            continue

        texto_par_estruturado = normalizar_estrutura_dispositivo(texto_par)
        incisos_do_par = extrair_blocos_por_marcador(texto_par_estruturado, 'inciso')
        alineas_do_par = extrair_blocos_por_marcador(texto_par_estruturado, 'alinea')

        if incisos_do_par and len(texto_par) > 250:
            for marc_inc, txt_inc in incisos_do_par:
                if not marc_inc:
                    continue
                clean_marc = str(marc_inc).rstrip("-–—.").strip()
                num_sub = f'{num_art}, {marcador_par}, Inciso {clean_marc}'
                alvos.append({'numero': num_sub, 'texto': f'{marc_inc} {txt_inc}'.strip()})
                numeros_existentes.add(num_sub)
        elif alineas_do_par and len(texto_par) > 250:
            for marc_al, txt_al in alineas_do_par:
                if not marc_al:
                    continue
                clean_al = str(marc_al).rstrip(")-").strip()
                num_sub = f'{num_art}, {marcador_par}, alínea {clean_al}'
                alvos.append({'numero': num_sub, 'texto': f'{marc_al} {txt_al}'.strip()})
                numeros_existentes.add(num_sub)
        else:
            num_par = f'{num_art}, {marcador_par}'
            alvos.append({'numero': num_par, 'texto': f'{marcador_par} {texto_par}'.strip()})
            numeros_existentes.add(num_par)

    todos_incisos = extrair_blocos_por_marcador(texto, 'inciso')
    for marcador, texto_inciso in todos_incisos:
        if marcador and texto_inciso and len(texto_inciso) > 5:
            clean_marc = str(marcador).rstrip("-–—.").strip()
            numero = f'{num_art}, Inciso {clean_marc}'
            if numero not in numeros_existentes:
                alvos.append({'numero': numero, 'texto': f'{marcador} {texto_inciso}'.strip()})
                numeros_existentes.add(numero)

    if not alvos:
        return [{'numero': num_art, 'texto': corpo_limpo.strip()}]

    return alvos

def parse_and_store_pdf(pdf_path, law_id):
    doc = fitz.open(pdf_path)
    full_text = "\n".join([page.get_text() for page in doc])
    doc.close()

    artigo_regex = re.compile(r'(?m)^(Art\.\s*\d+[\w\-]*[\.\º\ª]?)', re.IGNORECASE)
    partes = artigo_regex.split(full_text)
    artigos_brutos = []

    if len(partes) > 1:
        for i in range(1, len(partes), 2):
            num_art = partes[i].strip()
            corpo_art = partes[i + 1] if (i + 1) < len(partes) else ""
            corpo_limpo = limpar_e_formatar_texto_lei(corpo_art)
            if corpo_limpo and len(corpo_limpo) > 10:
                artigos_brutos.append((num_art, corpo_limpo))
    else:
        artigo_regex_alt = re.compile(r'(Art\.\s*\d+[\w\-]*[\.\º\ª]?)', re.IGNORECASE)
        partes = artigo_regex_alt.split(full_text)
        for i in range(1, len(partes), 2):
            num_art = partes[i].strip()
            corpo_art = partes[i + 1] if (i + 1) < len(partes) else ""
            corpo_limpo = limpar_e_formatar_texto_lei(corpo_art)
            if corpo_limpo and len(corpo_limpo) > 10:
                artigos_brutos.append((num_art, corpo_limpo))

    conn = db()
    quantidade = 0
    for num_art, corpo_limpo in artigos_brutos:
        conn.execute(
            "INSERT INTO artigos(lei_id, numero, titulo, texto) VALUES(?,?,?,?)",
            (law_id, num_art, num_art, corpo_limpo)
        )
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
        rows = conn.execute("""
            SELECT f.*, d.nome disciplina, l.nome lei
            FROM filtros_salvos f
            JOIN disciplinas d ON d.id = f.disciplina_id
            JOIN leis l ON l.id = f.lei_id
            WHERE f.usuario_id = ? AND f.disciplina_id = ?
            ORDER BY d.nome, f.id DESC
        """, (USER_ID, discipline_id)).fetchall()
    else:
        rows = conn.execute("""
            SELECT f.*, d.nome disciplina, l.nome lei
            FROM filtros_salvos f
            JOIN disciplinas d ON d.id = f.disciplina_id
            JOIN leis l ON l.id = f.lei_id
            WHERE f.usuario_id = ?
            ORDER BY d.nome, f.id DESC
        """, (USER_ID,)).fetchall()
    conn.close()
    return rows

def obter_texto_caput(artigo_id):
    if not artigo_id:
        return None
    conn = db()
    artigo = conn.execute("SELECT texto FROM artigos WHERE id = ?", (artigo_id,)).fetchone()
    conn.close()
    if artigo and artigo["texto"]:
        texto_limpo = limpar_e_formatar_texto_lei(artigo["texto"])
        texto_normalizado = normalizar_estrutura_dispositivo(texto_limpo)
        
        m = re.search(
            rf'(?m)^(?:§\s*\d+º?|Parágrafo único\b|{REGEX_ROMANO}\s*[-–—\.]\s*)', 
            texto_normalizado, 
            re.IGNORECASE
        )
        if m:
            caput = texto_normalizado[:m.start()].strip()
        else:
            caput = texto_normalizado.strip()
            
        return caput if caput else texto_normalizado.strip()
    return None

def limpar_assertiva_dispositivo(texto):
    if not texto:
        return ""
    t = texto.strip()
    t = re.sub(
        rf'^(?:{REGEX_ROMANO}\s*[-–—\.]\s*|§\s*\d+º?\s*[-–—\.]?\s*|Parágrafo único\s*[-–—\.]?\s*|[a-z]\s*[\)\-]\s*)',
        '',
        t,
        flags=re.IGNORECASE
    ).strip()
    t = re.sub(r'[\s;:,]+$', '', t).strip()
    if not t:
        return texto.strip()
    t = t[0].upper() + t[1:]
    if not t.endswith('.'):
        t += '.'
    return t

def conectar_caput_com_dispositivo(caput_texto, assertiva_limpa, rotulo_dispositivo):
    if not caput_texto or not assertiva_limpa:
        return assertiva_limpa
    
    cap = caput_texto.strip()
    if re.search(r'compete\s+privativamente\s+ao\s+presidente\s+da\s+república', cap, re.IGNORECASE):
        if not re.search(r'compete', assertiva_limpa, re.IGNORECASE):
            verbo_ajustado = assertiva_limpa[0].lower() + assertiva_limpa[1:]
            return f"Compete privativamente ao Presidente da República {verbo_ajustado}"
            
    if re.search(r'administração\s+pública\s+direta\s+e\s+indireta.*obedecerá', cap, re.IGNORECASE):
        if not re.search(r'administração|cargos|princípios', assertiva_limpa, re.IGNORECASE):
            verbo_ajustado = assertiva_limpa[0].lower() + assertiva_limpa[1:]
            return f"Na administração pública direta e indireta, {verbo_ajustado}"

    if cap.endswith(':') and len(cap) < 120:
        cap_sem_dois_pontos = cap.rstrip(':').strip()
        if not assertiva_limpa.lower().startswith(cap_sem_dois_pontos.lower()[:20]):
            verbo_ajustado = assertiva_limpa[0].lower() + assertiva_limpa[1:]
            return f"{cap_sem_dois_pontos} {verbo_ajustado}"

    return assertiva_limpa

def formatar_nome_lei_contextual(nome_lei):
    if not nome_lei:
        return "Constituição Federal / Lei Seca"
    nl = str(nome_lei).strip()
    if re.match(r'^art(?:igo)?s?\.?\s*\d+', nl, re.IGNORECASE):
        return f"Constituição Federal de 1988 ({nl})"
    return nl

def construir_enunciado_com_nexo(nome_lei, rotulo_dispositivo, assertiva_texto, caput_texto=None, num_art=None):
    ref_rotulo = obter_rotulo_dispositivo(rotulo_dispositivo)
    lei_formatada = formatar_nome_lei_contextual(nome_lei)
    vinculo = ""
    if num_art and num_art not in ref_rotulo:
        vinculo = f" (pertencente ao {num_art})"
        
    enunciado = (
        f"**Referência Normativa:** {lei_formatada} — **{ref_rotulo}**{vinculo}\n\n"
        f"À luz da literalidade da legislação e do dispositivo legal em exame, julgue o item a seguir:\n\n"
        f"> \"{assertiva_texto}\""
    )
    return enunciado

def obter_rotulo_dispositivo(numero_dispositivo):
    if not numero_dispositivo:
        return "Dispositivo da Lei"
    s = str(numero_dispositivo).strip()
    s = re.sub(r'^(?:Inciso|Parágrafo|Alínea|Artigo)\s*\((.+)\)$', r'\1', s, flags=re.IGNORECASE)
    return s

def renderizar_enunciado_estudo(enunciado, num_disp=None):
    """
    Renderiza os cartões da questão garantindo que qualquer HTML armazenado
    seja corretamente limpo e escapado para evitar códigos visíveis na tela.
    """
    if not enunciado:
        return

    texto = limpar_conteudo_html_para_renderizacao(enunciado)

    if "questao-comando-card" in texto or "questao-assertiva-card" in texto:
        ref_match = re.search(
            r'(?:Referência Normativa:\s*)(.*?)(?=<div\s+class=["\']questao-comando-card|$)',
            texto,
            flags=re.IGNORECASE | re.DOTALL
        )
        referencia = ref_match.group(1).strip() if ref_match else ""

        comando_match = re.search(
            r'<div\s+class=["\']questao-comando-text["\']\s*>(.*?)</div>',
            texto, flags=re.IGNORECASE | re.DOTALL
        )
        assertiva_match = re.search(
            r'<div\s+class=["\']questao-assertiva-text["\']\s*>(.*?)</div>',
            texto, flags=re.IGNORECASE | re.DOTALL
        )

        comando = html.unescape(re.sub(r'<[^>]+>', '', comando_match.group(1))) if comando_match else "À luz da literalidade da legislação e do dispositivo legal em exame, julgue o item a seguir:"
        assertiva = html.unescape(re.sub(r'<[^>]+>', '', assertiva_match.group(1))) if assertiva_match else ""
        referencia = html.unescape(re.sub(r'<[^>]+>', '', referencia))
    else:
        linhas = [linha.strip() for linha in texto.splitlines() if linha.strip()]
        referencia = re.sub(r'\*\*', '', linhas[0]).strip() if linhas else ""

        m = re.search(
            r'(À luz da literalidade.*?)(?:\n\n|\n|$)',
            texto,
            flags=re.IGNORECASE | re.DOTALL
        )
        comando = re.sub(r'\s+', ' ', m.group(1)).strip() if m else "À luz da literalidade da legislação e do dispositivo legal em exame, julgue o item a seguir:"

        m_assertiva = re.search(r'>\s*["“](.*?)["”]\s*$', texto, flags=re.DOTALL)
        if m_assertiva:
            assertiva = m_assertiva.group(1).strip()
        else:
            partes = texto.split('\n\n')
            assertiva = partes[-1].strip().lstrip('> ').strip('"“”') if partes else texto

    # Normalização robusta para evitar exibição de tags literais
    referencia = html.escape(re.sub(r'<[^>]+>', '', referencia).strip())
    comando = html.escape(re.sub(r'<[^>]+>', '', comando).strip())
    assertiva = html.escape(re.sub(r'<[^>]+>', '', assertiva).strip())

    html_enunciado = f"""
    <div class="questao-estudo-wrapper">
        <div class="questao-ref-card">
            <div class="questao-ref-label">📚 REFERÊNCIA NORMATIVA</div>
            <div class="questao-ref-text">{referencia}</div>
        </div>

        <div class="questao-comando-card">
            <div class="questao-comando-label">🎯 COMANDO DA QUESTÃO</div>
            <div class="questao-comando-text">{comando}</div>
        </div>

        <div class="questao-assertiva-card">
            <div class="questao-assertiva-label">⚖️ ITEM PARA JULGAMENTO</div>
            <div class="questao-assertiva-text">“{assertiva}”</div>
        </div>
    </div>
    """
    st.markdown(limpar_conteudo_html_para_renderizacao(textwrap.dedent(html_enunciado)), unsafe_allow_html=True)

def alterar_texto_para_errado(texto):
    substituicoes = [
        (r'\brespeito à integridade física e moral\b', 'respeito à integridade física, sendo dispensada a tutela de sua integridade moral', 'restrição indevida: a CF/88 assegura expressamente o respeito à integridade física E moral dos presos'),
        (r'\bintegridade física e moral\b', 'integridade física, mas não à integridade moral', 'restrição indevida: a garantia constitucional abrange tanto a integridade física quanto a moral'),
        (r'\bé assegurado aos presos o respeito\b', 'é facultado à administração penitenciária restringir o respeito', 'troca indevida de garantia fundamental cogente por faculdade administrativa'),
        (r'\bestabelecimentos distintos, de acordo com a natureza do delito, a idade e o sexo\b', 'estabelecimentos unificados, independentemente da natureza do delito, idade ou sexo', 'supressão do critério constitucional de separação de presos por delito, idade e sexo'),
        (r'\bpermanecer com seus filhos durante o período de amamentação\b', 'permanecer com seus filhos apenas nos primeiros 15 dias de vida, vedada a amamentação no presídio', 'supressão da garantia constitucional da presidiária de amamentar seus filhos'),
        (r'\bsalvo em caso de guerra declarada\b', 'mesmo em caso de guerra declarada', 'supressão da única ressalva constitucional para a pena de morte no Brasil'),
        (r'\bnenhum brasileiro será extraditado, salvo o naturalizado\b', 'qualquer brasileiro, inclusive o nato, poderá ser extraditado por crime comum', 'violação da imunidade absoluta do brasileiro nato contra extradição'),
        (r'\bnenhum brasileiro será extraditado\b', 'o brasileiro nato poderá ser extraditado em caso de tráfico de drogas', 'o brasileiro nato NUNCA é extraditado, nem mesmo por tráfico de entorpecentes'),
        (r'\bnão será concedida extradição de estrangeiro por crime político ou de opinião\b', 'será admitida a extradição de estrangeiro por crime puramente político ou de opinião', 'violação da vedação expressa de extradição por crime político ou de opinião'),
        (r'\bsão inadmissíveis, no processo, as provas obtidas por meios ilícitos\b', 'são plenamente admissíveis no processo as provas obtidas por meios ilícitos, desde que úteis à verdade real', 'inversão da regra constitucional de inadmissibilidade absoluta das provas ilícitas'),
        (r'\btrânsito em julgado de sentença penal condenatória\b', 'confirmação da condenação em julgamento de segundo grau', 'antecipação indevida da culpabilidade antes do trânsito em julgado'),
        (r'\bsem o devido processo legal\b', 'mediante processo sumário sem contraditório', 'supressão da garantia do devido processo legal'),
        (r'\bo civilmente identificado não será submetido a identificação criminal\b', 'o civilmente identificado será compulsoriamente submetido a identificação criminal em qualquer hipótese', 'violação da regra que dispensa identificação criminal de quem já possui identificação civil'),
        (r'\bnão haverá prisão civil por dívida, salvo a do responsável pelo inadimplemento voluntário e inescusável de obrigação alimentícia e a do depositário infiel\b', 'é admitida a prisão civil por qualquer dívida bancária ou contratual inadimplida', 'generalização indevida da prisão civil, que só cabe para obrigação alimentícia'),
        (r'\bdurante o dia, por determinação judicial\b', 'a qualquer hora do dia ou da noite, por determinação da autoridade policial', 'violação da reserva de jurisdição e do limite diurno para cumprimento de mandado em domicílio'),
        (r'\bindependentemente de autorização\b', 'desde que previamente autorizada pelo órgão policial competente', 'exigência indevida de autorização para o direito constitucional de reunião'),
        (r'\bsem armas\b', 'ainda que os participantes portem armas de fogo registradas', 'admissão indevida de armas na reunião pacífica'),
        (r'\bprévio aviso à autoridade competente\b', 'prévia autorização judicial', 'a CF exige apenas prévio aviso, e não autorização judicial'),
        (r'\bqualquer cidadão é parte legítima para propor ação popular\b', 'qualquer pessoa jurídica ou estrangeiro não eleitor é parte legítima para propor ação popular', 'ação popular é remédio exclusivo de cidadão (pessoa física no gozo dos direitos políticos)'),
        (r'\bisen[ts]o de custas judiciais e do ônus da sucumbência\b', 'sujeito ao recolhimento prévio de custas judiciais e depósito recursal obrigatório', 'cobrança indevida em ação popular constitucionalmente gratuita'),
        (r'\bdireito líquido e certo\b', 'direito controvertido que demande perícia técnica e ampla dilação probatória', 'mandado de segurança exige prova pré-constituída e não admite dilação probatória'),
        (r'\bliberdade de locomoção\b', 'direito patrimonial ou funcional', 'habeas corpus destina-se exclusivamente a tutelar a liberdade de locomoção'),
        (r'\b24 \(vinte e quatro\) horas\b', '48 (quarenta e oito) horas', 'alteração indevida de prazo legal de 24h para 48h'),
        (r'\b48 \(quarenta e oito\) horas\b', '24 (vinte e quatro) horas', 'alteração indevida de prazo legal de 48h para 24h'),
        (r'\b30 \(trinta\) dias\b', '15 (quinze) dias', 'alteração indevida de prazo legal de 30 para 15 dias'),
        (r'\b15 \(quinze\) dias\b', '30 (trinta) dias', 'alteração indevida de prazo legal de 15 para 30 dias'),
        (r'\b120 \(cento e vinte\) dias\b', '60 (sessenta) dias', 'alteração do prazo decadencial do MS de 120 para 60 dias'),
        (r'\bdeverá\b', 'poderá', 'troca de comando obrigatório ("deverá") por faculdade discricionária ("poderá")'),
        (r'\bpoderá\b', 'deverá obrigatoriamente', 'troca de faculdade ("poderá") por imposição obrigatória'),
        (r'\bpermitido\b', 'vedado', 'inversão de permissão legal para vedação'),
        (r'\bvedado\b', 'permitido', 'inversão de proibição expressa para permissão'),
        (r'\bvedada\b', 'permitida', 'inversão de proibição expressa para permissão'),
        (r'\bexigido\b', 'dispensado', 'troca de exigência legal expressa por dispensa indevida'),
        (r'\bdispensado\b', 'exigido', 'troca de dispensa legal por exigência indevida'),
        (r'\bobrigatório\b', 'facultativo', 'troca de obrigatoriedade legal por facultatividade'),
        (r'\bfacultativo\b', 'obrigatório', 'troca de faculdade legal por obrigatoriedade'),
        (r'\bgratuito\b', 'oneroso, mediante pagamento de taxa', 'cobrança indevida em garantia constitucional gratuita')
    ]

    texto_modificado = texto
    tipo_troca = None

    for padrao, sub, desc in substituicoes:
        if re.search(padrao, texto_modificado, re.IGNORECASE):
            texto_modificado = re.sub(padrao, sub, texto_modificado, count=1, flags=re.IGNORECASE)
            tipo_troca = desc
            break

    if not tipo_troca:
        inversoes_sintaticas = [
            (r'^É assegurado\b', 'Não é assegurado', 'inversão do direito assegurado para negativa'),
            (r'^São assegurados\b', 'Não são assegurados', 'inversão da garantia assegurada para negativa'),
            (r'^É assegurada\b', 'Não é assegurada', 'inversão da garantia assegurada para negativa'),
            (r'^São asseguradas\b', 'Não são asseguradas', 'inversão da garantia assegurada para negativa'),
            (r'^São invioláveis\b', 'Não são invioláveis', 'supressão da inviolabilidade constitucional'),
            (r'^É inviolável\b', 'Não é inviolável', 'supressão da inviolabilidade constitucional'),
            (r'^É livre\b', 'Depende de autorização prévia', 'restrição indevida à liberdade constitucional'),
            (r'^É vedad[oa]\b', 'É permitido', 'inversão da vedação para permissão'),
            (r'^Não haverá\b', 'Será admitida a criação de', 'inversão da vedação constitucional expressa'),
            (r'^Nenhum brasileiro\b', 'Qualquer brasileiro', 'supressão da garantia constitucional'),
            (r'\bnão será\b', 'será', 'supressão da partícula negativa "não"'),
            (r'\bnão serão\b', 'serão', 'supressão da partícula negativa "não"')
        ]
        for padrao, sub, desc in inversoes_sintaticas:
            if re.search(padrao, texto_modificado, re.IGNORECASE):
                texto_modificado = re.sub(padrao, sub, texto_modificado, count=1, flags=re.IGNORECASE)
                tipo_troca = desc
                break

    if not tipo_troca:
        texto_limpo_ponto = texto_modificado.rstrip('.')
        texto_modificado = f"{texto_limpo_ponto}, ressalvada decisão discricionária em sentido contrário."
        tipo_troca = 'criação de ressalva não prevista na literalidade da lei'

    if texto_modificado:
        texto_modificado = texto_modificado[0].upper() + texto_modificado[1:]
        if not texto_modificado.endswith('.'):
            texto_modificado += '.'

    return texto_modificado, tipo_troca

def obter_chave_gemini(chave_manual=None):
    if chave_manual and str(chave_manual).strip():
        return str(chave_manual).strip()
    if st.session_state.get("gemini_api_key"):
        return str(st.session_state["gemini_api_key"]).strip()
    try:
        if "GEMINI_API_KEY" in st.secrets:
            return str(st.secrets["GEMINI_API_KEY"]).strip()
        if "GOOGLE_API_KEY" in st.secrets:
            return str(st.secrets["GOOGLE_API_KEY"]).strip()
    except Exception:
        pass
    env_k = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if env_k:
        return str(env_k).strip()
    return None

def obter_chave_openai(chave_manual=None):
    if chave_manual and str(chave_manual).strip():
        return str(chave_manual).strip()
    if st.session_state.get("openai_api_key"):
        return str(st.session_state["openai_api_key"]).strip()
    try:
        if "OPENAI_API_KEY" in st.secrets:
            return str(st.secrets["OPENAI_API_KEY"]).strip()
    except Exception:
        pass
    env_k = os.getenv("OPENAI_API_KEY")
    if env_k:
        return str(env_k).strip()
    return None

def extrair_json_exemplo(raw_text, rotulo_dispositivo):
    if not raw_text:
        return None
    clean = re.sub(r'```(?:json)?\s*', '', raw_text)
    clean = re.sub(r'```', '', clean).strip()

    m = re.search(r'\{[\s\S]*\}', clean)
    if m:
        try:
            d = json.loads(m.group(0))
            sit = d.get("situacao_real") or d.get("situacaoReal") or d.get("caso_concreto")
            ap = d.get("aplicacao_regra") or d.get("aplicacaoRegra")
            obj = d.get("objetivo_regra") or d.get("objetivoRegra")
            biz = d.get("bizu_memorizacao") or d.get("bizuMemorizacao") or d.get("bizu")
            if sit:
                return (
                    sit.strip(),
                    f"• **Aplicação no {rotulo_dispositivo}:** {ap.strip() if ap else 'Aplicação direta da literalidade normativa.'}",
                    obj.strip() if obj else "Garantir a segurança jurídica e a legalidade estrita.",
                    biz.strip() if biz else "Atenção às palavras-chave e prazos cobrados pela banca."
                )
        except Exception:
            pass
    return None

def gerar_exemplo_gemini(rotulo_dispositivo, texto_dispositivo, chave_manual=None):
    chave = obter_chave_gemini(chave_manual)
    if not chave:
        return None

    texto_puro = texto_dispositivo
    if "De acordo com o" in texto_puro:
        m = re.search(r':\s*"(.*)"\s*$', texto_puro, re.DOTALL)
        if m:
            texto_puro = m.group(1).strip()

    prompt = f"""Você é um jurista e professor de Direito para concursos públicos no Brasil.
Dispositivo legal em estudo: {rotulo_dispositivo}
Texto literal da Lei Seca: "{texto_puro}"

Crie um exemplo prático e objetivo da vida real, demonstrando como esse dispositivo legal é aplicado na prática. Responda EXCLUSIVAMENTE em formato JSON com as chaves:
{{
  "situacao_real": "Narrativa objetiva de 2 a 3 frases de um caso concreto aplicando este dispositivo com nomes fictícios",
  "aplicacao_regra": "Como a regra foi aplicada ao caso concreto",
  "objetivo_regra": "Qual a finalidade protetiva ou jurídica da norma",
  "bizu_memorizacao": "Uma dica rápida de memorização ou como as bancas de concurso criam pegadinha neste dispositivo"
}}"""

    if genai and hasattr(genai, "Client"):
        try:
            client = genai.Client(api_key=chave)
            resp = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
            res = extrair_json_exemplo(resp.text, rotulo_dispositivo)
            if res:
                return res
        except Exception:
            pass

    if genai and hasattr(genai, "configure"):
        try:
            genai.configure(api_key=chave)
            model = genai.GenerativeModel("gemini-1.5-flash")
            resp = model.generate_content(prompt)
            res = extrair_json_exemplo(resp.text, rotulo_dispositivo)
            if res:
                return res
        except Exception:
            pass

    for model_name in ["gemini-2.5-flash", "gemini-1.5-flash", "gemini-2.0-flash"]:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={chave}"
            headers = {"Content-Type": "application/json"}
            payload = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.2}}
            req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=12) as response:
                result_raw = json.loads(response.read().decode("utf-8"))
                candidate = result_raw.get("candidates", [])[0]["content"]["parts"][0]["text"]
                res = extrair_json_exemplo(candidate, rotulo_dispositivo)
                if res:
                    return res
        except Exception:
            pass

    return None

def gerar_exemplo_openai(rotulo_dispositivo, texto_dispositivo, chave_manual=None):
    chave = obter_chave_openai(chave_manual)
    if not chave:
        return None
    try:
        texto_puro = texto_dispositivo.strip('"\n ')
        prompt = f"""Você é um jurista e professor de Direito para concursos públicos no Brasil.
Dispositivo legal: {rotulo_dispositivo}
Texto literal da Lei: "{texto_puro}"

Crie um exemplo prático da vida real (2 a 3 frases) com caso concreto aplicando a regra.
Responda em JSON puro:
{{
  "situacao_real": "...",
  "aplicacao_regra": "...",
  "objetivo_regra": "...",
  "bizu_memorizacao": "..."
}}"""
        url = "https://api.openai.com/v1/chat/completions"
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {chave}"}
        payload = {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": prompt}], "temperature": 0.2, "response_format": {"type": "json_object"}}
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            content = data["choices"][0]["message"]["content"]
            return extrair_json_exemplo(content, rotulo_dispositivo)
    except Exception:
        return None

def gerar_exemplo_dinamico_heuristico(art_num, texto_original):
    txt = texto_original.strip()
    txt_lower = txt.lower()

    m_prazo = re.search(r'(\d+)\s*\(([^)]+)\)\s*(dias|horas|meses|anos)', txt, re.IGNORECASE)
    if not m_prazo:
        m_prazo = re.search(r'(\d+)\s*(dias|horas|meses|anos)', txt, re.IGNORECASE)
    prazo_str = m_prazo.group(0) if m_prazo else None

    eh_vedacao = any(w in txt_lower for w in ["vedado", "proibido", "não poderá", "não haverá", "inadmissível", "é vedada"])
    eh_obrigacao = any(w in txt_lower for w in ["deverá", "obrigatório", "compete", "incumbe", "é obrigado"])
    eh_faculdade = any(w in txt_lower for w in ["poderá", "facultado", "faculdade", "a critério"])

    ator = "O cidadão Pedro"
    if any(w in txt_lower for w in ["servidor", "cargo público", "função pública"]):
        ator = "O servidor público Marcos"
    elif any(w in txt_lower for w in ["juiz", "magistrado", "tribunal"]):
        ator = "O magistrado titular da comarca"
    elif any(w in txt_lower for w in ["polícia", "delegado", "autoridade policial"]):
        ator = "A autoridade policial em investigação"
    elif any(w in txt_lower for w in ["preso", "apenado", "detento"]):
        ator = "O custodiado Lucas"

    if eh_vedacao:
        situacao = f"Em uma situação prática, tentou-se impor determinada exigência a {ator}. Contudo, por força expressa do {art_num}, a conduta foi barrada por configurar vedação legal expressa."
        aplicacao = f"• **Aplicação no {art_num}:** Impede atos arbitrários ao estabelecer proibição imperativa."
        objetivo = "Garantir a preservação dos direitos fundamentais e evitar abusos de poder pelo Estado."
        bizu = f"Pegadinha de banca: costumam trocar a vedação por permissão condicional neste dispositivo ({art_num})."
    elif eh_obrigacao:
        if prazo_str:
            situacao = f"{ator} foi intimado a cumprir uma determinação formal no prazo legal improrrogável de {prazo_str}."
            aplicacao = f"• **Aplicação no {art_num}:** Impõe o cumprimento cogente no prazo estrito de {prazo_str}."
            objetivo = "Assegurar a celeridade e a segurança jurídica."
            bizu = f"A banca costuma alterar o prazo de '{prazo_str}' por outro valor similar."
        else:
            situacao = f"Diante de um caso concreto, {ator} exerceu pretensão amparada na norma, sendo o órgão competente obrigado a cumprir a diretriz."
            aplicacao = f"• **Aplicação no {art_num}:** A regra possui caráter vinculante ('deverá')."
            objetivo = "Submeter todos os atos públicos ao império da legalidade estrita."
            bizu = "A banca adora trocar o termo vinculante ('deverá') por faculdade discricionária ('poderá')."
    elif eh_faculdade:
        situacao = f"Analisando as circunstâncias de conveniência e oportunidade, {ator} exerceu a prerrogativa prevista na lei de forma motivada."
        aplicacao = f"• **Aplicação no {art_num}:** Confere faculdade legítima de atuação, respeitados a proporcionalidade e a razoabilidade."
        objetivo = "Conferir flexibilidade técnica e discricionariedade regulada à aplicação prática."
        bizu = "Cuidado com questões que afirmam ser 'obrigatória' uma conduta que a lei qualifica como mera faculdade."
    else:
        resumo_regra = txt[:110] + "..." if len(txt) > 110 else txt
        situacao = f"Em litígio sob exame, {ator} postulou a incidência direta desta regra: '{resumo_regra}', acolhida nos termos literais."
        aplicacao = f"• **Aplicação no {art_num}:** Subordina os atos à literalidade desta norma."
        objetivo = "Assegurar a previsibilidade dos comportamentos sociais."
        bizu = f"Em provas de lei seca, a cobrança do {art_num} é literal: atente-se às palavras-chave e ressalvas."

    return situacao, aplicacao, objetivo, bizu

def obter_exemplo_pratico_contextualizado(art_num, texto_original):
    ex = gerar_exemplo_gemini(art_num, texto_original)
    if not ex:
        ex = gerar_exemplo_openai(art_num, texto_original)
    if not ex:
        ex = gerar_exemplo_dinamico_heuristico(art_num, texto_original)
    return ex

# ==============================================================================
# MENU LATERAL E FLUXOS DA APLICAÇÃO
# ==============================================================================

st.sidebar.title("⚖ Decorando Lei Seca")
st.sidebar.markdown(f"👤 Utilizador: **{USERNAME}**")

menu = st.sidebar.radio(
    "Navegação",
    [
        "📖 Estudar Leis",
        "⚙ Gerenciar Leis & PDFs",
        "🎯 Simulados & Questões",
        "📊 Meu Desempenho",
        "🔑 Configurar IA & API",
        "👥 Gestão de Utilizadores" if is_admin_user else None
    ]
)
menu = [m for m in menu if m is not None]

if st.sidebar.button("🚪 Terminar Sessão"):
    st.session_state["logged_in"] = False
    st.session_state["user_id"] = None
    st.session_state["username"] = None
    st.rerun()

# ------------------------------------------------------------------------------
# 1. ESTUDAR LEIS
# ------------------------------------------------------------------------------
if menu == "📖 Estudar Leis":
    st.header("📖 Leitura Direta e Casos Práticos")
    disciplinas = get_disciplines()
    if not disciplinas:
        st.info("Nenhuma disciplina cadastrada. Vá em 'Gerenciar Leis & PDFs' para cadastrar.")
    else:
        d_map = {d["nome"]: d["id"] for d in disciplinas}
        escolha_disc = st.selectbox("Selecione a Disciplina", list(d_map.keys()), key="estudo_disc")
        disc_id = d_map[escolha_disc]

        leis = get_laws(disc_id)
        if not leis:
            st.warning("Nenhuma lei cadastrada para esta disciplina.")
        else:
            l_map = {l["nome"]: l["id"] for l in leis}
            escolha_lei = st.selectbox("Selecione a Lei / Norma", list(l_map.keys()), key="estudo_lei")
            lei_id = l_map[escolha_lei]

            artigos = get_articles(lei_id)
            if not artigos:
                st.warning("Esta lei não possui artigos importados.")
            else:
                art_map = {f"{a['numero']} - {a['texto'][:60]}...": a["id"] for a in artigos}
                escolha_art = st.selectbox("Selecione o Artigo / Dispositivo", list(art_map.keys()), key="estudo_art")
                art_id = art_map[escolha_art]

                art_obj = next((a for a in artigos if a["id"] == art_id), None)
                if art_obj:
                    st.markdown("---")
                    st.subheader(f"Dispositivo: {art_obj['numero']}")
                    
                    texto_completo = limpar_e_formatar_texto_lei(art_obj["texto"])
                    partes_fracionadas = fracionar_artigo_extenso(art_obj["numero"], texto_completo)

                    for parte in partes_fracionadas:
                        rotulo_parte = parte['numero']
                        texto_parte = parte['texto']

                        with st.container():
                            st.markdown(f"### **{rotulo_parte}**")
                            st.info(texto_parte)

                            if st.button(f"💡 Ver Exemplo Prático e Bizu — {rotulo_parte}", key=f"btn_ex_{art_obj['id']}_{rotulo_parte}"):
                                with st.spinner("Gerando exemplo prático fundamentado..."):
                                    sit, ap, obj, biz = obter_exemplo_pratico_contextualizado(rotulo_parte, texto_parte)
                                    st.success(f"**Caso Concreto:** {sit}")
                                    st.markdown(ap)
                                    st.markdown(f"• **Finalidade Normativa:** {obj}")
                                    st.warning(f"🎯 **Bizu de Concurso:** {biz}")
                            st.markdown("---")

# ------------------------------------------------------------------------------
# 2. GERENCIAR LEIS & PDFS
# ------------------------------------------------------------------------------
elif menu == "⚙ Gerenciar Leis & PDFs":
    st.header("⚙ Gestão de Disciplinas, Leis e Importação PDF")
    
    tab_d, tab_l, tab_p = st.tabs(["📚 Disciplinas", "📜 Leis", "📤 Importar PDF"])

    with tab_d:
        st.subheader("Cadastrar Nova Disciplina")
        nova_disc = st.text_input("Nome da Disciplina", key="input_nova_disc")
        if st.button("Salvar Disciplina"):
            if nova_disc:
                add_discipline(nova_disc)
                st.success(f"Disciplina '{nova_disc}' cadastrada com sucesso!")
                st.rerun()
            else:
                st.warning("Insira o nome da disciplina.")

        st.markdown("### Disciplinas Cadastradas")
        for d in get_disciplines():
            st.write(f"- {d['nome']}")

    with tab_l:
        st.subheader("Cadastrar Lei vinculada a Disciplina")
        discs = get_disciplines()
        if not discs:
            st.info("Cadastre uma disciplina primeiro.")
        else:
            d_map = {d["nome"]: d["id"] for d in discs}
            d_escolha = st.selectbox("Disciplina", list(d_map.keys()), key="lei_disc_sel")
            nome_lei = st.text_input("Nome da Lei / Norma (ex: Constituição Federal, Código Penal)")
            if st.button("Criar Registo de Lei"):
                if nome_lei:
                    add_law(d_map[d_escolha], nome_lei, "")
                    st.success(f"Lei '{nome_lei}' criada!")
                    st.rerun()
                else:
                    st.warning("Informe o nome da lei.")

            st.markdown("### Leis Existentes")
            for l in get_laws():
                col1, col2 = st.columns([4, 1])
                with col1:
                    st.write(f"**{l['disciplina_nome']}** ➔ {l['nome']}")
                with col2:
                    if st.button("🗑 Excluir", key=f"del_law_{l['id']}"):
                        delete_law(l['id'])
                        st.success("Lei excluída!")
                        st.rerun()

    with tab_p:
        st.subheader("Importar Artigos via PDF (Lei Seca)")
        discs = get_disciplines()
        if not discs:
            st.info("Cadastre uma disciplina e uma lei primeiro.")
        else:
            d_map = {d["nome"]: d["id"] for d in discs}
            d_sel = st.selectbox("Disciplina para Importação", list(d_map.keys()), key="pdf_d_sel")
            leis = get_laws(d_map[d_sel])
            if not leis:
                st.warning("Cadastre uma lei para esta disciplina.")
            else:
                l_map = {l["nome"]: l["id"] for l in leis}
                l_sel = st.selectbox("Lei Destino", list(l_map.keys()), key="pdf_l_sel")
                
                uploaded_pdf = st.file_uploader("Selecione o arquivo PDF da Lei", type=["pdf"])
                if uploaded_pdf and st.button("Processar e Indexar Artigos do PDF"):
                    filepath = PDF_DIR / uploaded_pdf.name
                    with open(filepath, "wb") as f:
                        f.write(uploaded_pdf.getbuffer())
                    
                    with st.spinner("Extraindo e estruturando artigos do PDF..."):
                        qtd = parse_and_store_pdf(filepath, l_map[l_sel])
                    st.success(f"Processamento concluído! {qtd} artigos extraídos e indexados com sucesso.")

# ------------------------------------------------------------------------------
# 3. SIMULADOS & QUESTÕES
# ------------------------------------------------------------------------------
elif menu == "🎯 Simulados & Questões":
    st.header("🎯 Simulados de Lei Seca (Padrão Cebraspe / Certo ou Errado)")
    
    tab_gerar, tab_praticar, tab_salvos = st.tabs(["⚡ Gerar Simulado", "📝 Responder Questões", "💾 Filtros Salvos"])

    with tab_gerar:
        st.subheader("Configurar Novo Simulado Personalizado")
        discs = get_disciplines()
        if not discs:
            st.info("Cadastre disciplinas e leis para gerar simulados.")
        else:
            d_map = {d["nome"]: d["id"] for d in discs}
            d_sel = st.selectbox("Disciplina", list(d_map.keys()), key="sim_d_sel")
            leis = get_laws(d_map[d_sel])
            if not leis:
                st.warning("Nenhuma lei cadastrada para esta disciplina.")
            else:
                l_map = {l["nome"]: l["id"] for l in leis}
                l_sel = st.selectbox("Lei", list(l_map.keys()), key="sim_l_sel")
                lei_id = l_map[l_sel]

                artigos = get_articles(lei_id)
                if not artigos:
                    st.warning("Esta lei não possui artigos cadastrados.")
                else:
                    st.markdown("### Selecione os Artigos para o Simulado")
                    todos_art_ids = [a["id"] for a in artigos]
                    selecionar_todos = st.checkbox("Selecionar Todos os Artigos", value=True)

                    art_selecionados = []
                    for a in artigos:
                        chk = st.checkbox(f"{a['numero']} - {a['texto'][:80]}...", value=selecionar_todos, key=f"art_chk_{a['id']}")
                        if chk:
                            art_selecionados.append(a["id"])

                    qtd_questoes = st.slider("Quantidade de Questões", min_value=5, max_value=50, value=10, step=5)
                    nome_filtro = st.text_input("Nome do Filtro / Simulado para Salvar (opcional)", value=f"Simulado {l_sel} - {datetime.now().strftime('%d/%m/%Y')}")

                    if st.button("🚀 Gerar Questões de Simulado", type="primary"):
                        if not art_selecionados:
                            st.warning("Selecione pelo menos um artigo.")
                        else:
                            filter_id = save_filter(nome_filtro, d_map[d_sel], lei_id, art_selecionados, qtd_questoes)
                            
                            conn = db()
                            conn.execute("DELETE FROM questoes WHERE filtro_id = ?", (filter_id,))
                            
                            artigos_escolhidos = conn.execute(
                                f"SELECT * FROM artigos WHERE id IN ({','.join(['?']*len(art_selecionados))})",
                                art_selecionados
                            ).fetchall()

                            geradas = 0
                            while geradas < qtd_questoes and artigos_escolhidos:
                                art = random.choice(artigos_escolhidos)
                                texto_limpo = limpar_e_formatar_texto_lei(art["texto"])
                                partes = fracionar_artigo_extenso(art["numero"], texto_limpo)
                                parte = random.choice(partes)

                                rotulo = parte["numero"]
                                conteudo_base = parte["texto"]

                                caput = obter_texto_caput(art["id"])
                                assertiva_limpa = limpar_assertiva_dispositivo(conteudo_base)
                                assertiva_com_nexo = conectar_caput_com_dispositivo(caput, assertiva_limpa, rotulo)

                                # 50% chance de Certo (1) ou Errado (0)
                                gabarito = random.choice([0, 1])
                                if gabarito == 1:
                                    assertiva_final = assertiva_com_nexo
                                    explicacao = f"O item está **CERTO**, pois reproduz exatamente o texto literal do dispositivo legal ({rotulo})."
                                else:
                                    assertiva_final, tipo_troca = alterar_texto_para_errado(assertiva_com_nexo)
                                    explicacao = f"O item está **ERRADO**, por incorreção material ({tipo_troca}) em relação ao texto literal do dispositivo ({rotulo})."

                                enunciado = construir_enunciado_com_nexo(l_sel, rotulo, assertiva_final, caput, art["numero"])

                                conn.execute("""
                                    INSERT INTO questoes (lei_id, artigo_id, disciplina_id, filtro_id, artigo_numero, conteudo, enunciado, gabarito, explicacao, criada_em)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                """, (
                                    lei_id, art["id"], d_map[d_sel], filter_id, rotulo, conteudo_base, enunciado, gabarito, explicacao, datetime.now().isoformat()
                                ))
                                geradas += 1

                            conn.commit()
                            conn.close()
                            st.success(f"Simulado gerado com sucesso! Vá para a aba 'Responder Questões' para iniciar.")

    with tab_praticar:
        st.subheader("Praticar Questões Geradas")
        filtros = get_saved_filters()
        if not filtros:
            st.info("Nenhum simulado gerado ou salvo. Crie um na aba 'Gerenciar/Gerar Simulado'.")
        else:
            f_map = {f"[{f['disciplina']}] {f['nome']} ({f['qtd_questoes']} questões - {f['criado_em'][:10]})": f["id"] for f in filtros}
            f_sel = st.selectbox("Selecione o Simulado", list(f_map.keys()), key="praticar_f_sel")
            filtro_id_ativo = f_map[f_sel]

            conn = db()
            questoes = conn.execute("SELECT * FROM questoes WHERE filtro_id = ? ORDER BY id", (filtro_id_ativo,)).fetchall()
            conn.close()

            if not questoes:
                st.warning("Este simulado não possui questões gravadas.")
            else:
                if "q_idx" not in st.session_state:
                    st.session_state["q_idx"] = 0

                if st.session_state["q_idx"] >= len(questoes):
                    st.session_state["q_idx"] = 0

                q = questoes[st.session_state["q_idx"]]
                st.markdown(f"### Questão {st.session_state['q_idx'] + 1} de {len(questoes)}")

                renderizar_enunciado_estudo(q["enunciado"], q["artigo_numero"])

                resp_key = f"resp_q_{q['id']}"
                col_c, col_e = st.columns(2)
                
                with col_c:
                    if st.button("🟢 CERTO", key=f"btn_c_{q['id']}", use_container_width=True):
                        st.session_state[resp_key] = 1
                with col_e:
                    if st.button("🔴 ERRADO", key=f"btn_e_{q['id']}", use_container_width=True):
                        st.session_state[resp_key] = 0

                if resp_key in st.session_state:
                    usuario_resp = st.session_state[resp_key]
                    acertou = (usuario_resp == q["gabarito"])
                    
                    if acertou:
                        st.success("🎉 **Resposta Correta!** Parabéns!")
                    else:
                        st.error("❌ **Resposta Incorreta!**")

                    st.markdown("### 📋 Gabarito & Fundamentação Legal")
                    st.info(f"**Gabarito Oficial:** {'CERTO' if q['gabarito'] == 1 else 'ERRADO'}\n\n{q['explicacao']}")

                    conn = db()
                    existente = conn.execute("SELECT * FROM respostas WHERE usuario_id = ? AND questao_id = ?", (USER_ID, q["id"])).fetchone()
                    if not existente:
                        conn.execute(
                            "INSERT INTO respostas (usuario_id, questao_id, resposta, acertou, respondida_em, ciclo) VALUES (?, ?, ?, ?, ?, ?)",
                            (USER_ID, q["id"], usuario_resp, 1 if acertou else 0, datetime.now().isoformat(), 1)
                        )
                        conn.commit()
                    conn.close()

                st.markdown("---")
                col_ant, col_prox = st.columns(2)
                with col_ant:
                    if st.button("⬅ Questão Anterior") and st.session_state["q_idx"] > 0:
                        st.session_state["q_idx"] -= 1
                        st.rerun()
                with col_prox:
                    if st.button("Próxima Questão ➡") and st.session_state["q_idx"] < len(questoes) - 1:
                        st.session_state["q_idx"] += 1
                        st.rerun()

    with tab_salvos:
        st.subheader("Gestão de Filtros Salvos")
        filtros = get_saved_filters()
        if not filtros:
            st.info("Nenhum filtro salvo.")
        else:
            for f in filtros:
                col1, col2 = st.columns([4, 1])
                with col1:
                    st.write(f"**{f['disciplina']}** — {f['nome']} | Qtd: {f['qtd_questoes']} | Criado em: {f['criado_em'][:10]}")
                with col2:
                    if st.button("🗑 Excluir Filtro", key=f"del_f_{f['id']}"):
                        delete_filter(f['id'])
                        st.success("Filtro excluído!")
                        st.rerun()

# ------------------------------------------------------------------------------
# 4. MEU DESEMPENHO
# ------------------------------------------------------------------------------
elif menu == "📊 Meu Desempenho":
    st.header("📊 Estatísticas de Desempenho e Ciclo de Estudos")
    
    conn = db()
    total_resp = conn.execute("SELECT COUNT(*) as total FROM respostas WHERE usuario_id = ?", (USER_ID,)).fetchone()["total"]
    total_acertos = conn.execute("SELECT COUNT(*) as total FROM respostas WHERE usuario_id = ? AND acertou = 1", (USER_ID,)).fetchone()["total"]
    conn.close()

    taxa_acerto = (total_acertos / total_resp * 100) if total_resp > 0 else 0.0

    col1, col2, col3 = st.columns(3)
    col1.metric("Questões Respondidas", total_resp)
    col2.metric("Acertos Totais", total_acertos)
    col3.metric("Taxa de Acerto", f"{taxa_acerto:.1f}%")

    st.markdown("---")
    st.subheader("Evolução e Análise por Matéria")
    if pd and total_resp > 0:
        conn = db()
        df_resp = pd.read_sql_query("""
            SELECT d.nome as disciplina, r.acertou, r.respondida_em
            FROM respostas r
            JOIN questoes q ON q.id = r.questao_id
            JOIN disciplinas d ON d.id = q.disciplina_id
            WHERE r.usuario_id = ?
        """, conn, params=(USER_ID,))
        conn.close()
        
        if not df_resp.empty:
            st.bar_chart(df_resp.groupby("disciplina")["acertou"].mean() * 100)
    else:
        st.info("Resolva questões para visualizar gráficos analíticos de desempenho.")

# ------------------------------------------------------------------------------
# 5. CONFIGURAR IA & API
# ------------------------------------------------------------------------------
elif menu == "🔑 Configurar IA & API":
    st.header("🔑 Chaves de API para Inteligência Artificial")
    st.markdown("Insira sua chave da API Google Gemini ou OpenAI para potencializar a geração dinâmica de exemplos práticos avançados.")

    gemini_key_input = st.text_input("Chave API Google Gemini (GEMINI_API_KEY)", type="password", value=st.session_state.get("gemini_api_key", ""))
    openai_key_input = st.text_input("Chave API OpenAI (OPENAI_API_KEY)", type="password", value=st.session_state.get("openai_api_key", ""))

    if st.button("Guardar Chaves"):
        st.session_state["gemini_api_key"] = gemini_key_input.strip()
        st.session_state["openai_api_key"] = openai_key_input.strip()
        st.success("Chaves de API guardadas com sucesso na sessão!")

# ------------------------------------------------------------------------------
# 6. GESTÃO DE UTILIZADORES (ADMIN)
# ------------------------------------------------------------------------------
elif menu == "👥 Gestão de Utilizadores" and is_admin_user:
    st.header("👥 Painel de Administração de Utilizadores")
    st.markdown(f"Administrador loggado: **{USERNAME}**")

    users = listar_usuarios()
    for u in users:
        col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
        with col1:
            st.write(f"**{u['username']}** {'👑 (Admin)' if u['username'].lower() == ADMIN_EMAIL else ''}")
        with col2:
            st.write("🟢 Autorizado" if u['autorizado'] == 1 else "⏳ Pendente")
        with col3:
            if u['username'].lower() != ADMIN_EMAIL:
                novo_status = 0 if u['autorizado'] == 1 else 1
                label_btn = "Bloquear" if u['autorizado'] == 1 else "Aprovar"
                if st.button(label_btn, key=f"st_{u['id']}"):
                    alterar_status_autorizacao(u['id'], novo_status)
                    st.success(f"Status do utilizador atualizado!")
                    st.rerun()
        with col4:
            if u['username'].lower() != ADMIN_EMAIL:
                if st.button("🗑 Excluir", key=f"del_u_{u['id']}"):
                    excluir_usuario(u['id'])
                    st.success("Utilizador excluído!")
                    st.rerun()









