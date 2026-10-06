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
    </style>
""", unsafe_allow_html=True)

# Regex universal para algarismos romanos de I até CCC (1 a 300+)
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

# ==============================================================================
# MOTOR DE ESTRUTURAÇÃO E FRAGMENTAÇÃO INTELIGENTE
# ==============================================================================

def normalizar_estrutura_dispositivo(texto):
    if not texto:
        return ""
    texto = texto.replace("\r", "\n")
    texto = re.sub(r'[ \t]+', ' ', texto)
    texto = re.sub(r'\s+(§\s*\d+º?|Parágrafo único)\s*', r'\n\1 ', texto, flags=re.IGNORECASE)
    padrao_inciso = rf'\s+(?={REGEX_ROMANO}\s*[-–—\.]\s*)'
    texto = re.sub(padrao_inciso, '\n', texto, flags=re.IGNORECASE)
    texto = re.sub(r'\s+(?=[a-z]\s*[\)\-]\s*)', '\n', texto)
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
                resultado.append({'numero': f"{rotulo_base} (trecho {parte_idx})", 'texto': acumulado})
                parte_idx += 1
            acumulado = p
    if acumulado:
        resultado.append({'numero': f"{rotulo_base} (trecho {parte_idx})" if parte_idx > 1 else rotulo_base, 'texto': acumulado})
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
    padroes_primeiro = [r'(?m)^§\s*\d+º?', r'(?m)^Parágrafo único\b', rf'(?m)^{REGEX_ROMANO}\s*[-–—\.]\s*']
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
            alvos.append({'numero': num_formatado, 'texto': f'{marcador} {texto_inciso}'.strip()})
            numeros_existentes.add(num_formatado)

    for marcador_par, texto_par in paragrafos:
        if not marcador_par or not texto_par or len(texto_par) <= 5:
            continue
        num_par = f'{num_art}, {marcador_par}'
        alvos.append({'numero': num_par, 'texto': f'{marcador_par} {texto_par}'.strip()})
        numeros_existentes.add(num_par)

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

def alterar_texto_para_errado(texto):
    substituicoes = [
        (r'\bdeverá\b', 'poderá', 'troca de obrigação ("deverá") por faculdade ("poderá")'),
        (r'\bpoderá\b', 'deverá', 'troca de faculdade ("poderá") por obrigação ("deverá")'),
        (r'\b24 \(vinte e quatro\) horas\b', '48 (quarenta e oito) horas', 'alteração de prazo legal de 24h para 48h'),
        (r'\b48 \(quarenta e oito\) horas\b', '24 (vinte e quatro) horas', 'alteração de prazo legal de 48h para 24h'),
        (r'\b30 \(trinta\) dias\b', '15 (quinze) dias', 'alteração de prazo legal de 30 para 15 dias'),
        (r'\bpermitido\b', 'vedado', 'inversão de permissão para proibição'),
        (r'\bvedado\b', 'permitido', 'inversão de proibição para permissão')
    ]
    texto_modificado = texto
    tipo_troca = None
    for padrao, sub, descricao in substituicoes:
        if re.search(padrao, texto_modificado, re.IGNORECASE):
            texto_modificado = re.sub(padrao, sub, texto_modificado, count=1, flags=re.IGNORECASE)
            tipo_troca = descricao
            break
    if not tipo_troca:
        if " não " in texto_modificado:
            texto_modificado = texto_modificado.replace(" não ", " ", 1)
            tipo_troca = 'supressão da negação "não"'
        else:
            words = texto_modificado.split()
            if len(words) > 3:
                words.insert(3, "não")
                texto_modificado = " ".join(words)
                tipo_troca = 'inserção indevida da negação "não"'
    return texto_modificado, tipo_troca

def obter_rotulo_dispositivo(numero_dispositivo):
    num_lower = numero_dispositivo.lower()
    if "alínea" in num_lower or "alinea" in num_lower:
        return f"Alínea ({numero_dispositivo})"
    elif "§" in num_lower or "parágrafo" in num_lower or "paragrafo" in num_lower:
        return f"Parágrafo ({numero_dispositivo})"
    elif "inciso" in num_lower or re.search(rf'\b{REGEX_ROMANO}\b', numero_dispositivo, re.IGNORECASE):
        return f"Inciso ({numero_dispositivo})"
    else:
        return f"Artigo ({numero_dispositivo})"

def obter_chave_gemini(chave_manual=None):
    if chave_manual and str(chave_manual).strip():
        return str(chave_manual).strip()
    if st.session_state.get("gemini_api_key"):
        return str(st.session_state["gemini_api_key"]).strip()
    try:
        if "GEMINI_API_KEY" in st.secrets:
            return str(st.secrets["GEMINI_API_KEY"]).strip()
    except Exception:
        pass
    env_k = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
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
            sit = d.get("situacao_real") or d.get("caso_concreto")
            ap = d.get("aplicacao_regra")
            obj = d.get("objetivo_regra")
            biz = d.get("bizu_memorizacao")
            if sit:
                return (
                    sit.strip(),
                    f"• **Aplicação no {rotulo_dispositivo}:** {ap.strip() if ap else 'Aplicação direta.'}",
                    obj.strip() if obj else "Garantir a segurança jurídica.",
                    biz.strip() if biz else "Atenção às palavras-chave."
                )
        except Exception:
            pass
    return None

def gerar_exemplo_gemini(rotulo_dispositivo, texto_dispositivo, chave_manual=None):
    chave = obter_chave_gemini(chave_manual)
    if not chave:
        return None
    prompt = f"""Jurista e professor de Direito. Dispositivo: {rotulo_dispositivo}. Texto: "{texto_dispositivo}".
Crie um exemplo prático da vida real (2 a 3 frases) em JSON puro com as chaves:
{{"situacao_real": "...", "aplicacao_regra": "...", "objetivo_regra": "...", "bizu_memorizacao": "..."}}"""

    for model_name in ["gemini-2.5-flash", "gemini-1.5-flash"]:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={chave}"
            payload = {"contents": [{"parts": [{"text": prompt}]}]}
            req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=10) as resp:
                res_json = json.loads(resp.read().decode("utf-8"))
                candidate = res_json["candidates"][0]["content"]["parts"][0]["text"]
                parsed = extrair_json_exemplo(candidate, rotulo_dispositivo)
                if parsed:
                    return parsed
        except Exception:
            pass
    return None

def gerar_exemplo_dinamico_heuristico(art_num, texto_original):
    return (
        f"Em litígio submetido à análise judicial aplicando o {art_num}, a norma foi cumprida estritamente.",
        f"• **Aplicação no {art_num}:** Observância direta do texto legal.",
        "Garantir a ordem jurídica e a legalidade.",
        "Atente-se aos prazos e termos da lei seca."
    )

def gerar_explicacao_humana(art_num, texto_original, foi_correto=False, tipo_troca=None, exemplo_customizado=None, foi_ia=False):
    if exemplo_customizado and len(exemplo_customizado) == 4:
        s_real, ap_regra, obj_regra, bizu = exemplo_customizado
    else:
        s_real, ap_regra, obj_regra, bizu = gerar_exemplo_dinamico_heuristico(art_num, texto_original)

    status = "O item está **CORRETO**." if foi_correto else f"O item está **ERRADO** (Pegadinha: {tipo_troca})."
    tag = '<span style="color: #b45309; font-size: 11px; font-weight: 650;">✨ Exemplo IA</span>' if foi_ia else '<span style="color: #1d4ed8; font-size: 11px;">⚖️ Exemplo Lei</span>'

    return f"""
    <div style="font-size: 13.5px; margin-bottom: 8px;">💡 <strong>Gabarito:</strong> {status}</div>
    <div style="background-color: #f8fafc; border: 1px solid #bfdbfe; border-radius: 8px; padding: 12px; margin-bottom: 10px;">
        <div style="font-weight: 600; color: #1e3a8a; font-size: 12.5px;">📖 Texto Legal ({art_num})</div>
        <div style="font-style: italic; color: #334155; font-size: 12.5px;">"{texto_original}"</div>
    </div>
    <div style="background-color: #fffbeb; border: 1px solid #fde68a; border-radius: 8px; padding: 12px;">
        <div style="font-weight: 650; color: #78350f; font-size: 13px;">💡 Caso Prático {tag}</div>
        <div style="font-size: 12.5px; color: #1f2937; margin-top: 4px;">
            <p><strong>Situação:</strong> {s_real}</p>
            <p><strong>Aplicação:</strong> {ap_regra}</p>
            <p><strong>Objetivo:</strong> {obj_regra}</p>
            <p><strong>🎯 Bizu:</strong> {bizu}</p>
        </div>
    </div>
    """

def generate_questions_for_articles(discipline_id, law_id, article_ids, qtd_total, filter_id=None, motor_ia="♊ Gemini IA", chave_manual=None):
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

    if not alvos:
        conn.close()
        return 0

    random.shuffle(alvos)
    generated = 0
    now = datetime.now().isoformat()
    usar_gemini = "Gemini" in motor_ia

    for i in range(qtd_total):
        alvo = alvos[i % len(alvos)]
        art = alvo["art"]
        num_disp = alvo["numero"]
        rotulo = obter_rotulo_dispositivo(num_disp)
        text = limpar_e_formatar_texto_lei(alvo["texto"])
        is_correct = random.choice([True, False])

        exemplo_ia = gerar_exemplo_gemini(rotulo, text, chave_manual=chave_manual) if usar_gemini else None

        if is_correct:
            enunciado = f"De acordo com o **{rotulo}**:\n\n\"{text}\""
            gabarito = 1
            explicacao = gerar_explicacao_humana(num_disp, text, foi_correto=True, exemplo_customizado=exemplo_ia, foi_ia=bool(exemplo_ia))
        else:
            modificado, tipo_troca = alterar_texto_para_errado(text)
            enunciado = f"De acordo com o **{rotulo}**:\n\n\"{modificado}\""
            gabarito = 0
            explicacao = gerar_explicacao_humana(num_disp, text, foi_correto=False, tipo_troca=tipo_troca, exemplo_customizado=exemplo_ia, foi_ia=bool(exemplo_ia))

        try:
            conn.execute("""
                INSERT INTO questoes(lei_id, artigo_id, disciplina_id, filtro_id, artigo_numero, conteudo, enunciado, gabarito, explicacao, origem, criada_em)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """, (law_id, art["id"], discipline_id, filter_id, num_disp, num_disp, enunciado, gabarito, explicacao, motor_ia, now))
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
    conn.execute("INSERT INTO respostas(usuario_id, questao_id, resposta, acertou, respondida_em, ciclo) VALUES(?,?,?,?,?,?)",
                 (USER_ID, question_id, answer, correct, now.isoformat(), cycle))
    
    old = conn.execute("SELECT * FROM revisoes WHERE usuario_id=? AND questao_id=?", (USER_ID, question_id)).fetchone()
    if old:
        errors = old["erros"] + (0 if correct else 1)
        hits = old["acertos"] + (1 if correct else 0)
    else:
        errors = 0 if correct else 1
        hits = 1 if correct else 0

    priority = min(10, (old["prioridade"] if old else 1) + 2) if not correct else max(0, (old["prioridade"] if old else 1) - 1)
    next_date = now if not correct else now + timedelta(days=[1, 3, 7, 15, 30][min(4, hits-1)])

    conn.execute("INSERT OR REPLACE INTO revisoes(usuario_id, questao_id, prioridade, proxima_revisao, erros, acertos) VALUES(?,?,?,?,?,?)",
                 (USER_ID, question_id, priority, next_date.isoformat(), errors, hits))
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
    b_disc = pd.read_sql_query("""
        SELECT d.nome disciplina, COUNT(r.id) respondidas, COALESCE(SUM(r.acertou),0) acertos,
        ROUND(COALESCE(SUM(r.acertou),0)*100.0/COUNT(r.id),1) percentual
        FROM respostas r JOIN questoes q ON q.id=r.questao_id JOIN disciplinas d ON d.id=q.disciplina_id
        WHERE r.usuario_id = ? GROUP BY d.id ORDER BY percentual
    """, conn, params=(USER_ID,))
    due = conn.execute("SELECT COUNT(*) n FROM revisoes WHERE usuario_id = ? AND proxima_revisao <= ?", (USER_ID, datetime.now().isoformat())).fetchone()["n"]
    conn.close()
    return total, hits, errors, pct, b_disc, due

# ==============================================================================
# BARRA LATERAL E INTERFACE DE ABAS
# ==============================================================================

with st.sidebar:
    st.markdown(f"👤 Utilizador: **{USERNAME}**")
    if st.button("🚪 Sair / Logout"):
        st.session_state["logged_in"] = False
        st.session_state["user_id"] = None
        st.session_state["username"] = None
        st.rerun()
    st.divider()

    st.markdown("### 🤖 Inteligência Artificial")
    chave_det = obter_chave_gemini()
    st.caption(f"Status: **{'🟢 Ativa' : '⚪ Offline'}**" if chave_det else "Status: **⚪ Offline**")
    nova_chave = st.text_input("GEMINI_API_KEY:", value=st.session_state.get("gemini_api_key", chave_det or ""), type="password")
    if st.button("Salvar Chave API"):
        if nova_chave.strip():
            st.session_state["gemini_api_key"] = nova_chave.strip()
            st.success("Chave salva!")
            st.rerun()
    st.divider()

    if is_admin_user:
        st.subheader("⚙ Painel Admin na Barra")
        with st.expander("Gerir Utilizadores"):
            for u in listar_usuarios():
                st.write(f"**{u['username']}**")
                if u['username'].strip().lower() != ADMIN_EMAIL:
                    novo_s = st.toggle("Autorizado", value=bool(u['autorizado']), key=f"side_u_{u['id']}")
                    if novo_s != bool(u['autorizado']):
                        alterar_status_autorizacao(u['id'], 1 if novo_s else 0)
                        st.rerun()

st.title("⚖ Decorando Lei Seca")

tabs_list = ["📚 Importar Leis", "🎯 Criar Caderno", "📝 Resolver Questões", "📊 Desempenho", "🔄 Revisões"]
if is_admin_user:
    tabs_list.append("🛡 Painel Admin")

tabs = st.tabs(tabs_list)
tab1, tab2, tab3, tab4, tab5 = tabs[0], tabs[1], tabs[2], tabs[3], tabs[4]
tab_admin = tabs[5] if is_admin_user else None

with tab1:
    st.header("Importar Nova Lei (PDF)")
    discs = get_disciplines()
    col1, col2 = st.columns(2)
    with col1:
        new_disc = st.text_input("Nova Disciplina:")
        if st.button("Cadastrar Disciplina") and new_disc:
            add_discipline(new_disc)
            st.success(f"Disciplina '{new_disc}' cadastrada!")
            st.rerun()
    with col2:
        disc_sel = st.selectbox("Disciplina:", [""] + [d["nome"] for d in discs])

    law_title = st.text_input("Nome da Lei:")
    up_file = st.file_uploader("Ficheiro PDF", type=["pdf"])
    if st.button("Processar e Salvar Lei") and disc_sel and law_title and up_file:
        disc_id = [d["id"] for d in discs if d["nome"] == disc_sel][0]
        f_path = PDF_DIR / up_file.name
        with open(f_path, "wb") as f:
            f.write(up_file.getbuffer())
        law_id = add_law(disc_id, law_title, up_file.name)
        qtd = parse_and_store_pdf(f_path, law_id)
        st.success(f"Lei processada! {qtd} artigos importados.")

    st.divider()
    st.subheader("Leis Cadastradas")
    for l in get_laws():
        col_l1, col_l2 = st.columns([4, 1])
        col_l1.write(f"📄 **{l['disciplina_nome']}** - {l['nome']}")
        if col_l2.button("Excluir", key=f"del_l_{l['id']}"):
            delete_law(l['id'])
            st.success("Lei excluída!")
            st.rerun()

with tab2:
    st.header("Criar Caderno de Questões")
    discs = get_disciplines()
    if discs:
        d_sel = st.selectbox("Disciplina para Caderno:", discs, format_func=lambda x: x["nome"], key="cb_disc")
        laws = get_laws(d_sel["id"])
        if laws:
            l_sel = st.selectbox("Lei:", laws, format_func=lambda x: x["nome"], key="cb_law")
            arts = get_articles(l_sel["id"])
            art_opts = {f"Art. {a['numero']}: {a['texto'][:60]}...": a['id'] for a in arts}
            sel_arts = st.multiselect("Selecione os artigos (vazio = todos):", list(art_opts.keys()))
            art_ids = [art_opts[k] for k in sel_arts]
            
            cb_nome = st.text_input("Nome do Caderno/Filtro:", value=f"Caderno {l_sel['nome']}")
            qtd_q = st.number_input("Quantidade de Questões:", min_value=5, max_value=100, value=15)
            motor = st.selectbox("Motor de Geração:", ["♊ Gemini IA (Recomendado)", "⚖ Regras Padrão"])

            if st.button("Gerar Questões do Caderno", type="primary"):
                with st.spinner("Gerando questões..."):
                    filter_id = save_filter(cb_nome, d_sel["id"], l_sel["id"], art_ids, qtd_q)
                    geradas = generate_questions_for_articles(d_sel["id"], l_sel["id"], art_ids, qtd_q, filter_id=filter_id, motor_ia=motor)
                    st.success(f"✨ {geradas} questões geradas com sucesso!")
        else:
            st.info("Nenhuma lei cadastrada nesta disciplina.")
    else:
        st.info("Cadastre disciplinas e leis primeiro.")

with tab3:
    st.header("Resolver Questões")
    filters = get_saved_filters()
    if filters:
        f_map = {f"[{f['disciplina']}] {f['nome']} ({f['lei']})": f['id'] for f in filters}
        f_sel_name = st.selectbox("Escolha o Caderno Salvo:", list(f_map.keys()))
        f_id = f_map[f_sel_name]

        conn = db()
        questoes = conn.execute("SELECT * FROM questoes WHERE filtro_id = ? ORDER BY id", (f_id,)).fetchall()
        conn.close()

        if questoes:
            if "q_idx" not in st.session_state:
                st.session_state["q_idx"] = 0
            if st.session_state["q_idx"] >= len(questoes):
                st.session_state["q_idx"] = 0

            idx = st.session_state["q_idx"]
            q = questoes[idx]
            st.markdown(f"### Questão {idx+1} de {len(questoes)}")
            st.markdown(q["enunciado"])

            col_r1, col_r2 = st.columns(2)
            ans = None
            if col_r1.button("✅ CERTO", key=f"certo_{q['id']}", use_container_width=True):
                ans = 1
            if col_r2.button("❌ ERRADO", key=f"errado_{q['id']}", use_container_width=True):
                ans = 0

            if ans is not None:
                acertou = record_answer(q["id"], ans, cycle=1)
                if acertou:
                    st.success("🎉 Resposta Correta!")
                else:
                    st.error("❌ Resposta Incorreta!")
                st.markdown(q["explicacao"], unsafe_allow_html=True)

            if st.button("Avançar para Próxima Questão ➡️"):
                st.session_state["q_idx"] = (idx + 1) % len(questoes)
                st.rerun()
        else:
            st.info("Nenhuma questão neste filtro. Gere questões na aba anterior.")
    else:
        st.info("Nenhum caderno salvo encontrado.")

with tab4:
    st.header("Dashboard de Desempenho")
    total, hits, errors, pct, b_disc, due = stats()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Respondidas", total)
    c2.metric("Acertos", hits)
    c3.metric("Erros", errors)
    c4.metric("Aproveitamento", f"{pct:.1f}%")

    if not b_disc.empty:
        st.subheader("Desempenho por Disciplina")
        st.dataframe(b_disc, use_container_width=True)

    if st.button("🗑 Limpar Histórico de Respostas"):
        zerar_historico_dashboard()
        st.success("Histórico limpo!")
        st.rerun()

with tab5:
    st.header("🔄 Revisões Inteligentes (Spaced Repetition)")
    conn = db()
    revisoes_pendentes = conn.execute("""
        r.*, q.enunciado, q.explicacao, d.nome disciplina
        FROM revisoes r
        JOIN questoes q ON q.id = r.questao_id
        JOIN disciplinas d ON d.id = q.disciplina_id
        WHERE r.usuario_id = ? AND r.proxima_revisao <= ?
        ORDER BY r.prioridade DESC
    """, (USER_ID, datetime.now().isoformat())).fetchall()
    conn.close()

    if revisoes_pendentes:
        st.write(f"Você tem **{len(revisoes_pendentes)}** questões para revisar hoje!")
        for rev in revisoes_pendentes[:5]:
            with st.expander(f"Revisão | Prioridade: {rev['prioridade']} | {rev['disciplina']}"):
                st.markdown(rev["enunciado"])
                if st.button("Ver Explicação", key=f"rev_{rev['questao_id']}"):
                    st.markdown(rev["explicacao"], unsafe_allow_html=True)
    else:
        st.success("🎉 Nenhuma revisão pendente para agora. Excelente trabalho!")

if tab_admin and is_admin_user:
    with tab_admin:
        st.header("🛡 Painel Administrativo de Utilizadores")
        usuarios = listar_usuarios()
        for u in usuarios:
            col_a1, col_a2, col_a3 = st.columns([3, 2, 1])
            col_a1.write(f"**{u['username']}** (Criado em: {u['criado_em'][:10]})")
            is_admin_mail = u['username'].strip().lower() == ADMIN_EMAIL
            if is_admin_mail:
                col_a2.caption("👑 Administrador Principal")
            else:
                atv = bool(u['autorizado'])
                novo_atv = col_a2.toggle("Autorizado Acesso", value=atv, key=f"adm_usr_{u['id']}")
                if novo_atv != atv:
                    alterar_status_autorizacao(u['id'], 1 if novo_atv else 0)
                    st.success(f"Utilizador {u['username']} atualizado!")
                    st.rerun()
                if col_a3.button("Excluir", key=f"adm_del_{u['id']}"):
                    excluir_usuario(u['id'])
                    st.warning(f"Utilizador {u['username']} excluído.")
                    st.rerun()
            st.divider()






