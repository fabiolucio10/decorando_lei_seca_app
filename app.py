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
# MOTOR DE ESTRUTURAÇÃO E FRAGMENTAÇÃO INTELIGENTE (100% BLINDADO CONTRA ERROS)
# ==============================================================================

def normalizar_estrutura_dispositivo(texto):
    if not texto:
        return ""

    texto = texto.replace("\r", "\n")
    texto = re.sub(r'[ \t]+', ' ', texto)

    # Quebra linha antes de Parágrafos
    texto = re.sub(r'\s+(§\s*\d+º?|Parágrafo único)\s*', r'\n\1 ', texto, flags=re.IGNORECASE)

    # Quebra linha antes de Incisos (suporta I até LXXIX e além!)
    padrao_inciso = rf'\s+(?={REGEX_ROMANO}\s*[-–—\.]\s*)'
    texto = re.sub(padrao_inciso, '\n', texto, flags=re.IGNORECASE)

    # Quebra linha antes de Alíneas (a) -, b) -, c) -)
    texto = re.sub(r'\s+(?=[a-z]\s*[\)\-]\s*)', '\n', texto, flags=re.IGNORECASE)

    # Quebra linha antes de itens numéricos
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

    # 1. Extrai o CAPUT
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

    # 2. Extrai INCISOS DO CAPUT
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

    # 3. Extrai PARÁGRAFOS
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

    # 4. Varredura de segurança para incisos posteriores
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

def alterar_texto_para_errado(texto):
    substituicoes = [
        (r'\bdeverá\b', 'poderá', 'troca de obrigação ("deverá") por faculdade ("poderá")'),
        (r'\bpoderá\b', 'deverá', 'troca de faculdade ("poderá") por obrigação ("deverá")'),
        (r'\b24 \(vinte e quatro\) horas\b', '48 (quarenta e oito) horas', 'alteração de prazo legal de 24h para 48h'),
        (r'\b48 \(quarenta e oito\) horas\b', '24 (vinte e quatro) horas', 'alteração de prazo legal de 48h para 24h'),
        (r'\b72 \(setenta e duas\) horas\b', '24 (vinte e quatro) horas', 'alteração de prazo legal de 72h para 24h'),
        (r'\b12 \(doze\) horas\b', '24 (vinte e quatro) horas', 'alteração do prazo de 12h para 24h'),
        (r'\b30 \(trinta\) dias\b', '15 (quinze) dias', 'alteração de prazo legal de 30 para 15 dias'),
        (r'\b15 \(quinze\) dias\b', '30 (trinta) dias', 'alteração de prazo legal de 15 para 30 dias'),
        (r'\bpermitido\b', 'vedado', 'inversão de permissão para proibição'),
        (r'\bvedado\b', 'permitido', 'inversão de proibição para permissão'),
        (r'\bexigido\b', 'dispensado', 'troca de exigência por dispensa legal'),
        (r'\bdispensado\b', 'exigido', 'troca de dispensa por exigência indevida'),
        (r'\bobrigatório\b', 'facultativo', 'troca de obrigatório por facultativo'),
        (r'\bfacultativo\b', 'obrigatório', 'troca de facultativo por obrigatório'),
        (r'\bindependentemente de autorização\b', 'mediante prévia autorização da autoridade', 'exigência indevida de autorização estatal'),
        (r'\bindependentemente de autorização judicial\b', 'mediante prévia autorização judicial', 'exigência indevida de autorização judicial'),
        (r'\bmediante autorização judicial\b', 'independentemente de autorização judicial', 'supressão indevida da reserva de jurisdição'),
        (r'\bsalvo em caso de guerra declarada\b', 'mesmo em caso de guerra declarada', 'supressão da ressalva constitucional expressa'),
        (r'\bsem armas\b', 'com armas de fogo registradas', 'admissão indevida de armas na reunião'),
        (r'\bprévio aviso\b', 'prévia autorização', 'troca do prévio aviso por exigência de prévia autorização'),
        (r'\brazoável duração\b', 'duração discricionária', 'supressão da garantia da razoável duração do processo')
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

# ==============================================================================
# INTEGRAÇÃO GEMINI IA & OPENAI: EXEMPLOS PRÁTICOS DINÂMICOS DA VIDA REAL
# ==============================================================================

def obter_chave_gemini(chave_manual=None):
    """
    Recupera a chave Gemini API na seguinte ordem de prioridade:
    1. Chave fornecida manualmente pelo usuário no input
    2. Session state da sessão do Streamlit
    3. Streamlit secrets (configurado no Streamlit Cloud dashboard)
    4. Variáveis de ambiente (GEMINI_API_KEY ou GOOGLE_API_KEY)
    """
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
    # Remove marcações de código markdown se presentes
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
    """
    Chama a Inteligência Artificial Gemini com tripla camada de redundância:
    1. SDK google.genai moderno (v2.x)
    2. SDK google.generativeai legado (v0.x)
    3. Chamada HTTP REST nativa via urllib (sem dependência de bibliotecas, 100% à prova de falhas)
    """
    chave = obter_chave_gemini(chave_manual)
    if not chave:
        return None

    # Limpa texto para retirar cabeçalho de enunciado caso exista
    texto_puro = texto_dispositivo
    if "De acordo com o" in texto_puro:
        m = re.search(r':\s*"(.*)"\s*$', texto_puro, re.DOTALL)
        if m:
            texto_puro = m.group(1).strip()
        else:
            partes = texto_puro.split("\n\n")
            if len(partes) > 1:
                texto_puro = partes[-1].strip('"\n ')

    prompt = f"""Você é um jurista e professor de Direito para concursos públicos no Brasil.
Dispositivo legal em estudo: {rotulo_dispositivo}
Texto literal da Lei Seca: "{texto_puro}"

Crie um exemplo prático e objetivo da vida real, extremamente claro e direto, demonstrando como esse dispositivo legal exato é aplicado na prática (em um tribunal, delegacia, repartição pública ou cotidiano do cidadão). Use nomes fictícios e uma narrativa simples de 2 a 3 frases.

Responda EXCLUSIVAMENTE em formato JSON com as chaves:
{{
  "situacao_real": "Narrativa objetiva de 2 a 3 frases de um caso concreto real da vida cotidiana aplicando este dispositivo com nomes fictícios",
  "aplicacao_regra": "Como a regra foi aplicada ao caso concreto",
  "objetivo_regra": "Qual a finalidade protetiva ou jurídica da norma",
  "bizu_memorizacao": "Uma dica rápida de memorização ou como as bancas de concurso tentam criar pegadinha neste dispositivo"
}}"""

    # Estratégia 1: SDK google.genai moderno
    if genai and hasattr(genai, "Client"):
        try:
            client = genai.Client(api_key=chave)
            resp = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt
            )
            res = extrair_json_exemplo(resp.text, rotulo_dispositivo)
            if res:
                return res
        except Exception as e:
            logging.info(f"Tentativa com google.genai falhou: {e}")

    # Estratégia 2: SDK google.generativeai legado
    if genai and hasattr(genai, "configure"):
        try:
            genai.configure(api_key=chave)
            model = genai.GenerativeModel("gemini-1.5-flash")
            resp = model.generate_content(prompt)
            res = extrair_json_exemplo(resp.text, rotulo_dispositivo)
            if res:
                return res
        except Exception as e:
            logging.info(f"Tentativa com google.generativeai falhou: {e}")

    # Estratégia 3: Chamada REST nativa via urllib (funciona em qualquer Python, sem dependência externa)
    for model_name in ["gemini-2.5-flash", "gemini-1.5-flash", "gemini-2.0-flash"]:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={chave}"
            headers = {"Content-Type": "application/json"}
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.2}
            }
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=12) as response:
                result_raw = json.loads(response.read().decode("utf-8"))
                candidate = result_raw.get("candidates", [])[0]["content"]["parts"][0]["text"]
                res = extrair_json_exemplo(candidate, rotulo_dispositivo)
                if res:
                    return res
        except Exception as e_rest:
            logging.warning(f"Chamada REST com {model_name} falhou: {e_rest}")

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

Crie um exemplo prático e objetivo da vida real (2 a 3 frases) com caso concreto aplicando a regra.
Responda em JSON puro:
{{
  "situacao_real": "...",
  "aplicacao_regra": "...",
  "objetivo_regra": "...",
  "bizu_memorizacao": "..."
}}"""
        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {chave}"
        }
        payload = {
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
            "response_format": {"type": "json_object"}
        }
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            content = data["choices"][0]["message"]["content"]
            return extrair_json_exemplo(content, rotulo_dispositivo)
    except Exception as e:
        logging.warning(f"Erro OpenAI: {e}")
        return None

# ==============================================================================
# MOTOR HEURÍSTICO CONTEXTUAL JURÍDICO (COBERTURA TOTAL - NUNCA GERA TEXTO GENÉRICO)
# ==============================================================================

def gerar_exemplo_dinamico_heuristico(art_num, texto_original):
    """
    Analisa sintaticamente o texto do dispositivo legal para extrair atores, verbos,
    prazos e vedações, construindo um exemplo com personagens e caso concreto específico,
    garantindo que mesmo sem internet/IA o usuário NUNCA receba uma resposta estática vazia.
    """
    txt = texto_original.strip()
    txt_lower = txt.lower()

    # Detecta prazos específicos
    m_prazo = re.search(r'(\d+)\s*\(([^)]+)\)\s*(dias|horas|meses|anos)', txt, re.IGNORECASE)
    if not m_prazo:
        m_prazo = re.search(r'(\d+)\s*(dias|horas|meses|anos)', txt, re.IGNORECASE)
    
    prazo_str = m_prazo.group(0) if m_prazo else None

    # Detecta se é proibição, dever ou faculdade
    eh_vedacao = any(w in txt_lower for w in ["vedado", "proibido", "não poderá", "não haverá", "inadmissível", "é vedada"])
    eh_obrigacao = any(w in txt_lower for w in ["deverá", "obrigatório", "compete", "incumbe", "é obrigado"])
    eh_faculdade = any(w in txt_lower for w in ["poderá", "facultado", "faculdade", "a critério"])

    # Identifica o ator principal provável
    ator = "O cidadão Pedro"
    if any(w in txt_lower for w in ["servidor", "cargo público", "função pública", "investidura"]):
        ator = "O servidor público Marcos"
    elif any(w in txt_lower for w in ["juiz", "magistrado", "tribunal", "judiciário"]):
        ator = "O juiz titular da comarca"
    elif any(w in txt_lower for w in ["polícia", "policial", "delegado", "autoridade policial"]):
        ator = "A autoridade policial em investigação"
    elif any(w in txt_lower for w in ["preso", "apenado", "reeducando", "pena", "detento"]):
        ator = "O custodiado Lucas"
    elif any(w in txt_lower for w in ["presidente", "ministro", "executivo"]):
        ator = "A autoridade do Poder Executivo"
    elif any(w in txt_lower for w in ["empresa", "fornecedor", "consumidor", "contratada"]):
        ator = "A sociedade empresária contratada"

    # Constrói narrativa personalizada baseada no conteúdo
    if eh_vedacao:
        situacao = f"Em uma situação prática, uma autoridade tentou impor determinada exigência a {ator}. Contudo, por força expressa do {art_num}, a conduta foi barrada imediatamente por configurar vedação legal expressa."
        aplicacao = f"• **Aplicação no {art_num}:** Impede atos arbitrários ao estabelecer proibição imperativa que vincula todos os órgãos públicos e particulares."
        objetivo = "Garantir a preservação dos direitos fundamentais e evitar abusos de poder pelo Estado."
        bizu = f"Pegadinha de banca: costumam trocar a vedação por permissão condicional ou criar exceções inexistentes neste dispositivo ({art_num})."
    elif eh_obrigacao:
        if prazo_str:
            situacao = f"{ator} foi intimado a cumprir uma determinação formal no prazo legal improrrogável de {prazo_str}. Caso o ato não seja praticado nesse lapso temporal, opera-se a preclusão e perda da faculdade processual/administrativa."
            aplicacao = f"• **Aplicação no {art_num}:** Impõe o cumprimento cogente no prazo estrito de {prazo_str}."
            objetivo = "Assegurar a celeridade, a marcha regular do procedimento e a segurança jurídica."
            bizu = f"A banca costuma alterar o prazo de '{prazo_str}' por outro valor similar para induzir o candidato ao erro."
        else:
            situacao = f"Diante de um caso concreto perante a administração, {ator} exerceu pretensão amparada na norma, sendo o órgão competente obrigado a cumprir a diretriz por expressa determinação cogente."
            aplicacao = f"• **Aplicação no {art_num}:** A regra possui caráter vinculante ('deverá'), não cabendo juízo de discricionariedade à autoridade."
            objetivo = "Submeter todos os atos públicos ao império da legalidade estrita."
            bizu = "A banca adora trocar o termo vinculante ('deverá') por faculdade discricionária ('poderá')."
    elif eh_faculdade:
        situacao = f"Analisando as circunstâncias de conveniência e oportunidade do caso, {ator} exerceu a prerrogativa prevista na lei de forma motivada, sem que houvesse ilegalidade na escolha discricionária."
        aplicacao = f"• **Aplicação no {art_num}:** Confere faculdade legítima de atuação, respeitados os princípios gerais de proporcionalidade e razoabilidade."
        objetivo = "Conferir flexibilidade técnica e discricionariedade regulada à aplicação prática."
        bizu = "Cuidado com questões que afirmam ser 'obrigatória' uma conduta que a lei qualifica como mera faculdade."
    else:
        # Extrai os primeiros 100 caracteres do texto para contextualizar
        resumo_regra = txt[:110] + "..." if len(txt) > 110 else txt
        situacao = f"Em um litígio sob exame judicial, {ator} postulou a incidência direta desta regra: '{resumo_regra}'. O magistrado acolheu o pedido exatamente nos termos literais positivados."
        aplicacao = f"• **Aplicação no {art_num}:** Subordina os atos da vida civil e pública à literalidade desta norma."
        objetivo = "Assegurar a previsibilidade dos comportamentos sociais e a tutela jurisdicional efetiva."
        bizu = f"Em provas de lei seca, a cobrança do {art_num} é literal: atente-se aos conectivos 'e/ou', às ressalvas ('salvo') e às condições expressas."

    return situacao, aplicacao, objetivo, bizu

def extrair_exemplo_objetivo_personalizado(art_num, texto_original):
    """
    Biblioteca rica de casos práticos reais e contextualizados para todos os temas
    de Direito Constitucional, Penal, Processual Penal e Administrativo.
    """
    txt = texto_original.lower()
    art_lower = art_num.lower()

    # Art. 5º, I - Igualdade entre homens e mulheres
    if "art. 5" in art_lower and ("inciso i\b" in art_lower or "i -" in art_lower) or ("homens e mulheres são iguais" in txt):
        return (
            "Um edital de concurso público para investigador policial fixou pontuação salarial distinta para homens e mulheres no mesmo cargo e com a mesma carga horária. Uma candidata impetrou mandado de segurança e anulou a cláusula com base na igualdade constitucional absoluta de direitos e obrigações.",
            f"• **Aplicação no {art_num}:** Veda qualquer discriminação arbitrária de gênero na fixação de vencimentos e atribuições públicas.",
            "Garantir a igualdade substancial e formal entre homens e mulheres no ordenamento brasileiro.",
            "Diferenciações entre homens e mulheres só são válidas quando justificadas por critérios biológicos razoáveis (ex: teste de aptidão física adaptado ou licença-maternidade)."
        )

    # Art. 5º, II - Princípio da Legalidade
    if "art. 5" in art_lower and ("inciso ii\b" in art_lower or "ii -" in art_lower) or ("virtude de lei" in txt and "obrigado a fazer" in txt):
        return (
            "Um fiscal municipal aplicou multa de trânsito a um motorista baseando-se unicamente em uma portaria interna da secretaria municipal, sem nenhuma previsão em lei formal aprovada pela Câmara. A Justiça anulou a sanção, pois ninguém é obrigado a cumprir dever que não decorra de lei formal.",
            f"• **Aplicação no {art_num}:** Princípio da legalidade estrita — para o particular, tudo o que não é proibido por lei é permitido; já o poder público só pode agir onde a lei expressamente autoriza.",
            "Proteger a esfera de autonomia e liberdade do cidadão contra imposições arbitrárias do Poder Executivo.",
            "Para os cidadãos vigora a autonomia da vontade (fazer o que a lei não proíbe); para a Administração, vigora a legalidade estrita (fazer apenas o que a lei autoriza)."
        )

    # Art. 5º, III - Vedação à Tortura e Tratamento Desumano
    if "art. 5" in art_lower and ("inciso iii\b" in art_lower or "iii -" in art_lower) or ("submetido a tortura" in txt or "tratamento desumano" in txt):
        return (
            "Policiais civis agrediram fisicamente e ameaçaram um suspeito durante o interrogatório em delegacia para forçar uma confissão de roubo. O juiz declarou a nulidade absoluta da confissão, determinou a soltura imediata do réu e ordenou a instauração de ação penal contra os agentes por crime inafiançável de tortura.",
            f"• **Aplicação no {art_num}:** Proibição absoluta e indelegável de tortura ou tratamento cruel, independentemente da gravidade do crime investigado.",
            "Salvaguardar a dignidade da pessoa humana e a integridade física de qualquer indivíduo perante o aparato estatal.",
            "O direito de não ser torturado é absoluto no Brasil — não admite exceções nem mesmo em estado de defesa, sítio ou guerra declarada."
        )

    # Art. 5º, IV - Livre Manifestação do Pensamento e Vedação ao Anonimato
    if "art. 5" in art_lower and ("inciso iv\b" in art_lower or "iv -" in art_lower) or ("manifestação do pensamento" in txt and "vedado o anonimato" in txt):
        return (
            "Um cidadão publicou em rede social críticas severas à gestão de um prefeito, assinando com seu nome civil real e CPF. O prefeito pediu a censura do post, mas a Justiça negou porque a manifestação é livre quando identificada, ressalvado eventual pedido de indenização caso comprovada calúnia.",
            f"• **Aplicação no {art_num}:** Protege a livre crítica e o debate público, proibindo estritamente denúncias anônimas como único fundamento de sanções estatais.",
            "Promover o pluralismo político e garantir que a liberdade de expressão não seja usada de forma covarde para difamação anônima.",
            "A banca adora dizer que 'o anonimato é admitido em certas hipóteses' (ERRADO! O anonimato é taxativamente VEDADO pela CF)."
        )

    # Art. 5º, V - Direito de Resposta
    if "art. 5" in art_lower and ("inciso v\b" in art_lower or "v -" in art_lower) or ("direito de resposta" in txt):
        return (
            "Um telejornal noticiou incorretamente que um empresário local participava de fraude tributária. O empresário obteve na Justiça o direito de veicular sua resposta no mesmo horário e com o mesmo tempo do telejornal, além de receber indenização pecuniária por danos morais à sua imagem comercial.",
            f"• **Aplicação no {art_num}:** Garante o contraditório social através de resposta proporcional ao agravo, cumulável com indenização material e moral.",
            "Restaurar a verdade pública sobre a honra do indivíduo ofendido pelos meios de comunicação.",
            "O direito de resposta é PROPORCIONAL AO AGRAVO e CUMULÁVEL com indenização por dano material, moral ou à imagem."
        )

    # Art. 5º, VI, VII, VIII - Liberdade Religiosa e Escusa de Consciência
    if any(k in txt for k in ["liberdade de consciência e de crença", "livre exercício dos cultos", "escusa de consciência", "prestação alternativa"]):
        return (
            "Um jovem adventista convocado para o alistamento militar obrigatório declarou que suas convicções religiosas impedem o porte de armas e o serviço militar aos sábados. As Forças Armadas foram obrigadas a conferir-lhe prestação de serviço alternativo em atividades civis durante os dias úteis.",
            f"• **Aplicação no {art_num}:** Protege a liberdade religiosa e garante que ninguém será privado de direitos por convicção de fé se cumprir a prestação alternativa fixada em lei.",
            "Assegurar a laicidade do Estado e a convivência plural de todas as crenças e filosofias.",
            "A perda de direitos políticos só ocorre se o indivíduo invocar escusa de consciência E se RECUSAR a cumprir a prestação alternativa fixada em lei (CF, Art. 15, IV)."
        )

    # Art. 5º, IX, X - Intimidade, Vida Privada, Honra e Imagem
    if any(k in txt for k in ["intimidade", "vida privada", "honra e a imagem", "indenização pelo dano material ou moral"]):
        return (
            "Um hospital privado teve seu banco de dados invadido e fotos íntimas de prontuários cirúrgicos de pacientes vazaram na internet por negligência na segurança digital. Uma paciente acionou o hospital e foi indenizada em R$ 80.000 por violação direta à sua intimidade e honra.",
            f"• **Aplicação no {art_num}:** Tutela a esfera privada e impõe responsabilidade civil com dever de reparação por violação da imagem.",
            "Preservar a intimidade do indivíduo contra intromissões indevidas de particulares ou do poder estatal.",
            "São invioláveis a intimidade, a vida privada, a honra e a imagem das pessoas, assegurado o direito à indenização pelo dano material ou moral decorrente de sua violação."
        )

    # Art. 5º, XI - Inviolabilidade de domicílio
    if "xi" in art_lower or any(k in txt for k in ["domicílio", "casa é asilo", "inviolável"]):
        return (
            "Policiais desconfiam de entorpecentes em uma residência. À noite, eles não podem entrar sem autorização do morador, a não ser em flagrante delito, desastre ou para prestar socorro. Durante o dia, podem cumprir mandado judicial mesmo sem permissão do residente.",
            f"• **Aplicação no {art_num}:** Protege a intimidade doméstica contra invasões arbitrárias do Estado.",
            "Garantir que a residência seja um refúgio inviolável do indivíduo.",
            "Por determinação judicial: SOMENTE DURANTE O DIA. A qualquer hora (dia ou noite): flagrante, desastre ou socorro."
        )

    # Art. 5º, XII - Sigilo de correspondência e telefônico
    if "xii" in art_lower or any(k in txt for k in ["sigilo da correspondência", "comunicações telegráficas", "dados e das comunicações telefônicas"]):
        return (
            "A polícia realizou escuta telefônica de um investigado por homicídio com base apenas em ordem do delegado, sem prévia autorização judicial. O juiz declarou a gravação ilícita e ordenou o desentranhamento do processo, pois a interceptação telefônica exige estrita reserva de jurisdição.",
            f"• **Aplicação no {art_num}:** Comunicações telefônicas só podem ser interceptadas por ordem judicial, para fins de investigação criminal ou instrução processual penal.",
            "Preservar a intimidade das conversas e evitar espionagem estatal sem controle de magistrado.",
            "Interceptação telefônica: SOMENTE por ordem judicial, para investigação criminal ou processo penal (NUNCA para processo civil ou administrativo)."
        )

    # Art. 5º, XVI - Direito de Reunião
    if "xvi" in art_lower or any(k in txt for k in ["reunir", "reunião", "sem armas", "abertos ao público", "prévio aviso"]):
        return (
            "Estudantes e trabalhadores organizam passeata pacífica em praça pública contra o aumento da tarifa de transporte. Eles NÃO precisam pedir permissão ao prefeito ou ao comandante da PM; basta aviso prévio à autoridade para organizar o trânsito e evitar sobreposição com outro evento marcado.",
            f"• **Aplicação no {art_num}:** O direito de reunião independe de autorização do Poder Público; requer apenas que seja pacífica, sem armas e com aviso prévio.",
            "Impedir a censura governamental a manifestações cívicas e garantir a harmonia com o trânsito da cidade.",
            "Pegadinha clássica: 'exige prévia autorização da polícia' (ERRADO!). É INDEPENDENTE de autorização, mas EXIGE PRÉVIO AVISO."
        )

    # Art. 5º, XVII a XXI - Direito de Associação
    if any(k in txt for k in ["associação", "associar-se", "dissolução compulsória", "suspensão de suas atividades"]):
        return (
            "Um grupo de moradores funda uma associação de bairro sem pedir licença à prefeitura. Meses depois, o prefeito tentou fechar a entidade por decreto. A Justiça declarou o decreto nulo: a dissolução de associação exige decisão judicial com trânsito em julgado.",
            f"• **Aplicação no {art_num}:** A criação de associações independe de autorização estatal, e sua dissolução forçada exige ordem judicial transitada em julgado.",
            "Garantir a autonomia da sociedade civil contra o arbítrio governamental.",
            "Para SUSPENDER atividades da associação: basta decisão judicial simples. Para DISSOLVER compulsoriamente: EXIGE TRÂNSITO EM JULGADO."
        )

    # Art. 5º, XXII a XXVI - Propriedade, Desapropriação e Pequena Propriedade Rural
    if any(k in txt for k in ["direito de propriedade", "função social", "desapropriação por necessidade", "pequena propriedade rural", "requisição administrativa"]):
        return (
            "Um pequeno agricultor cultiva milho em sítio familiar de 20 hectares para subsistência de sua família. Ele contraiu dívida para comprar sementes e o banco pediu a penhora da terra. O juiz negou a penhora com base no Art. 5º, XXVI, pois a pequena propriedade rural trabalhada pela família é impenhorável por dívidas produtivas.",
            f"• **Aplicação no {art_num}:** Protege o patrimônio mínimo de sobrevivência da família camponesa contra execuções bancárias.",
            "Fomentar a agricultura familiar e assegurar a dignidade e o trabalho no campo.",
            "Pequena propriedade rural: trabalhada pela família + dívida da atividade produtiva = IMPENHORÁVEL."
        )

    # Art. 5º, XXXVIII - Tribunal do Júri
    if "xxxviii" in art_lower or any(k in txt for k in ["tribunal do júri", "plenitude de defesa", "sigilo das votações", "soberania dos veredictos", "crimes dolosos contra a vida"]):
        return (
            "Um indivíduo é acusado de homicídio tentado após desferir facadas em um vizinho em briga de bar. O juiz togado não pode condená-lo sozinho no mérito: ele profere pronúncia e remete o acusado a julgamento perante 7 jurados populares no Tribunal do Júri.",
            f"• **Aplicação no {art_num}:** Competência constitucional privativa do Júri para julgar crimes dolosos contra a vida (homicídio, infanticídio, aborto, induzimento ao suicídio).",
            "Garantir o julgamento de crimes contra a vida por pares da própria sociedade com soberania de veredicto.",
            "O Tribunal do Júri julga apenas crimes DOLOSOS contra a vida (latrocínio, embora envolva morte, é crime contra o patrimônio julgado por juiz singular, Súmula 603 do STF)."
        )

    # Art. 5º, XXXIX, XL - Legalidade Penal e Irretroatividade
    if any(k in txt for k in ["não há crime sem lei anterior", "não há pena sem prévia", "lei penal não retroagirá", "salvo para beneficiar o réu"]):
        return (
            "Um indivíduo foi condenado a 4 anos por um crime. Meses após a sentença, o Congresso aprovou nova lei reduzindo a pena do mesmo delito para 2 anos. O juiz da execução penal aplicou a nova lei retroativamente, reduzindo a pena do condenado para 2 anos de forma imediata.",
            f"• **Aplicação no {art_num}:** A lei penal mais benéfica sempre retroage para alcançar fatos e processos anteriores, inclusive já transitados em julgado.",
            "Impedir que o Estado mantenha penas mais gravosas quando a própria sociedade reduziu o rigor punitivo.",
            "A lei penal NÃO retroage, SALVO para beneficiar o réu (novatio legis in mellius ou abolitio criminis retroagem SEMPRE)."
        )

    # Art. 5º, XLII, XLIII, XLIV - Racismo, 3T+H e Grupos Armados
    if any(k in txt for k in ["prática do racismo", "tortura", "tráfico ilícito de entorpecentes", "terrorismo", "hediondos", "grupos armados"]):
        return (
            "Um homem profere ofensas racistas contra atendente de loja em shopping. Ele é preso em flagrante. O delegado não pode arbitrar fiança, e o advogado sabe que a ação penal não prescreverá mesmo se passarem 20 anos, pois racismo é inafiançável e imprescritível.",
            f"• **Aplicação no {art_num}:** Racismo e Ação de grupos armados são INAFIANÇÁVEIS e IMPRESCRITÍVEIS. Já os 3T+H (tortura, tráfico, terrorismo e hediondos) são inafiançáveis e insuscetíveis de graça/anistia (mas prescrevem!).",
            "Combater com o mais alto rigor constitucional a discriminação racial e os crimes mais hediondos.",
            "Mnemônico de ouro: RACISMO e GRUPOS ARMADOS = RAÇUDOS = IMPRESCRITÍVEIS e INAFIANÇÁVEIS. 3T+H = INAFIANÇÁVEIS e INSUSCETÍVEIS de graça/anistia."
        )

    # Art. 5º, XLVII - Penas vedadas (Morte, Perpétua, Banimento, Cruéis, Trabalhos forçados)
    if "xlvii" in art_lower or any(k in txt for k in ["de morte", "pena de morte", "guerra declarada", "caráter perpétuo", "perpétu", "trabalhos forçados", "banimento", "cruéis", "não haverá penas"]):
        return (
            "No Brasil, o Código Penal Militar prevê pena de morte por fuzilamento apenas se houver guerra formalmente declarada pelo Presidente com autorização do Congresso Nacional. Em tempo de paz, nenhuma autoridade judicial pode aplicar pena de morte ou de caráter perpétuo.",
            f"• **Aplicação no {art_num}:** Impede punições desumanas, cruéis ou perpétuas no sistema penal brasileiro comum.",
            "Proteger a dignidade da pessoa humana e evitar punições estatais irreversíveis e cruéis.",
            "Banca adora dizer que 'não há pena de morte em hipótese alguma' (FALSO, há em caso de guerra declarada) ou que 'pena de banimento é permitida' (FALSO, é expressamente vedada)."
        )

    # Art. 5º, XLVIII - Estabelecimentos distintos
    if "xlviii" in art_lower or any(k in txt for k in ["estabelecimentos distintos", "natureza do delito", "sexo do apenado"]):
        return (
            "Um jovem de 19 anos condenado por furto simples não violento não pode ser colocado na mesma ala de reincidentes de alta periculosidade de 40 anos condenados por latrocínio, e homens e mulheres devem cumprir pena em locais separados.",
            f"• **Aplicação no {art_num}:** O Estado deve individualizar a execução penal conforme o sexo, a idade e a natureza do delito.",
            "Resguardar a integridade dos reeducandos e evitar aliciamento de criminosos primários.",
            "Critérios constitucionais de separação: natureza do delito, idade e sexo do apenado."
        )

    # Art. 5º, L - Presidiárias e amamentação
    if " l" in art_lower or any(k in txt for k in ["presidiária", "amamenta", "filhos durante o período"]):
        return (
            "Uma detenta deu à luz durante o cumprimento de pena em presídio feminino. O estabelecimento prisional é obrigado a dispor de creche/berçário para que ela amamente o bebê durante os primeiros meses.",
            f"• **Aplicação no {art_num}:** Direito subjetivo da mãe presa e do recém-nascido de permanecerem juntos durante a amamentação.",
            "Garantir a saúde, nutrição e proteção da infância do recém-nascido independentemente da condenação da mãe.",
            "O direito protege a criança e não pode sofrer corte por falta disciplinar da mãe."
        )

    # Art. 5º, LI / LII - Extradição
    if "li" in art_lower or "lii" in art_lower or any(k in txt for k in ["extradit", "brasileiro nato", "naturalizado"]):
        return (
            "Roberto, brasileiro nato, cometeu homicídio na Itália e fugiu para o Brasil. O STF nega qualquer pedido de extradição, pois nato JAMAIS é extraditado (responderá pelo crime perante a Justiça brasileira). Já Pierre, francês naturalizado brasileiro, pode ser extraditado por crime comum praticado ANTES da naturalização ou por tráfico de drogas A QUALQUER TEMPO.",
            f"• **Aplicação no {art_num}:** Garante imunidade absoluta de extradição ao brasileiro nato e fixa os 2 casos estritos do naturalizado.",
            "Proteger os nacionais da jurisdição punitiva estrangeira em território nacional.",
            "Nato NUNCA é extraditado. Naturalizado pode em 2 casos: crime comum ANTES da naturalização OU tráfico de entorpecentes a qualquer tempo."
        )

    # Art. 5º, LVI - Provas ilícitas
    if "lvi" in art_lower or any(k in txt for k in ["provas obtidas por meios ilícitos", "inadmissíveis"]):
        return (
            "Investigadores invadiram um escritório sem mandado judicial à noite e fotografaram planilhas de propina. Na ação penal, o juiz declarou a prova nula de pleno direito e mandou trancar o processo, pois provas colhidas por meio ilícito não podem fundamentar condenação.",
            f"• **Aplicação no {art_num}:** Teoria dos frutos da árvore envenenada: a prova ilícita contamina todas as demais provas que dela derivarem exclusivamente.",
            "Desestimular autoridades a violarem direitos fundamentais na busca por evidências penais.",
            "São inadmissíveis no processo as provas obtidas por meios ilícitos (CF, Art. 5º, LVI)."
        )

    # Art. 5º, LVII - Presunção de inocência
    if "lvii" in art_lower or any(k in txt for k in ["transitou em julgado", "culpado", "presunção de inocência", "trânsito em julgado"]):
        return (
            "Um réu foi condenado em 1ª e 2ª instâncias, mas recorreu ao STJ e STF. Ele não pode ser tratado como culpado nem ter o nome lançado no rol dos culpados antes da decisão final irrecorrível.",
            f"• **Aplicação no {art_num}:** Presunção constitucional de não culpabilidade até o trânsito em julgado de sentença penal condenatória.",
            "Evitar que o Estado aplique estigmas e consequências definitivas antes do esgotamento recursal.",
            "Ninguém será considerado culpado até o TRÂNSITO EM JULGADO de sentença penal condenatória."
        )

    # Art. 5º, LXVII - Prisão civil por dívida
    if "lxvii" in art_lower or any(k in txt for k in ["prisão civil", "alimentícia", "depositário infiel"]):
        return (
            "Carlos deixa de pagar voluntariamente 3 parcelas de pensão alimentícia devidas ao filho menor. O juiz decreta a prisão civil de 30 a 90 dias em regime fechado separado dos presos comuns.",
            f"• **Aplicação no {art_num}:** Apenas a obrigação alimentar enseja prisão civil hoje. O depositário infiel não pode mais ser preso (Súmula Vinculante 25).",
            "Coagir o devedor a honrar a subsistência de quem necessita de alimentos.",
            "Na letra da CF: pensão e depositário infiel. Na prática e jurisprudência (SV 25): apenas devedor de alimentos."
        )

    # Art. 5º, LXVIII a LXXIII - Remédios Constitucionais (HC, MS, HD, Ação Popular)
    if any(k in txt for k in ["habeas corpus", "locomoção", "liberdade de ir e vir"]):
        return (
            "Um cidadão tem prisão preventiva decretada por autoridade incompetente. O advogado impetra habeas corpus diretamente no Tribunal para expedição imediata de alvará de soltura.",
            f"• **Aplicação no {art_num}:** Remédio constitucional gratuito para salvaguardar a liberdade física de locomoção contra ilegalidade ou abuso de poder.",
            "Restabelecer a liberdade de ir e vir cerceada por arbítrio.",
            "Ação gratuita, não exige advogado e não cabe para punições disciplinares militares quanto ao mérito."
        )

    if any(k in txt for k in ["mandado de segurança", "direito líquido e certo"]):
        return (
            "Um candidato aprovado em 1º lugar em concurso público dentro das vagas do edital vê a validade expirar sem nomeação. Cabe Mandado de Segurança provando de plano o direito líquido e certo à posse com documentos pré-constituídos.",
            f"• **Aplicação no {art_num}:** Protege direitos documentados e incontroversos não amparados por habeas corpus ou habeas data.",
            "Sanar ilegalidades administrativas evidentes com celeridade processual.",
            "Prazo decadencial de 120 dias a contar da ciência do ato impugnado. Não admite dilação probatória (perícia/testemunhas)."
        )

    if any(k in txt for k in ["ação popular", "anular ato lesivo", "patrimônio público"]):
        return (
            "Um eleitor descobre que o prefeito contratou obra superfaturada favorecendo parente. Como cidadão no gozo dos direitos políticos, ele ingressa com Ação Popular para anular o contrato e ressarcir o erário.",
            f"• **Aplicação no {art_num}:** Instrumento de controle social direto da moralidade e do patrimônio público por qualquer cidadão.",
            "Permitir o controle social direto dos atos administrativos corruptos ou lesivos.",
            "Legitimidade ativa exclusiva de CIDADÃO (pessoa física no gozo dos direitos políticos com título de eleitor). Pessoa jurídica NÃO pode propor ação popular."
        )

    if any(k in txt for k in ["habeas data", "informações relativas à pessoa", "retificação de dados"]):
        return (
            "Um militar da reserva pede acesso à sua ficha funcional arquivada no Ministério da Defesa para saber por que foi preterido em promoção. Diante da recusa administrativa formal, impetra Habeas Data.",
            f"• **Aplicação no {art_num}:** Remédio gratuito para obter ou retificar dados pessoais do próprio impetrante constantes de registros públicos.",
            "Garantir a transparência governamental sobre os dados cadastrais do cidadão.",
            "É personalíssimo (apenas sobre dados do próprio impetrante) e EXIGE prévia recusa administrativa (Súmula 2 do STJ)."
        )

    # Art. 5º, LXXVIII - Razoável duração do processo e celeridade
    if "lxxviii" in art_lower or any(k in txt for k in ["razoável duração", "celeridade", "tramitação"]):
        return (
            "Um cidadão aguarda há mais de 10 anos a decisão final em um processo administrativo de aposentadoria no INSS sem qualquer complexidade que justifique tamanha demora. Diante da inércia desproporcional, ele impetra mandado de segurança exigindo conclusão imediata e pleiteia indenização por danos morais.",
            f"• **Aplicação no {art_num}:** Garante a qualquer jurisdicionado o direito a um processo sem dilações indevidas, tanto judicial quanto administrativo.",
            "Evitar que a morosidade e lentidão do Estado resultem em denegação prática de justiça.",
            "Atenção: a garantia se aplica a processos JUDICIAIS e ADMINISTRATIVOS (banca adora restringir a 'apenas judiciais')."
        )

    # Art. 5º, LXXIX - Proteção de dados digitais
    if "lxxix" in art_lower or any(k in txt for k in ["dados pessoais", "meios digitais"]):
        return (
            "Uma empresa de tecnologia ou órgão público sofre vazamento de dados de cidadãos sem consentimento. O titular pode acionar o Poder Judiciário invocando direito fundamental expresso à proteção de dados inclusive digitais.",
            f"• **Aplicação no {art_num}:** Eleva a privacidade digital ao patamar de cláusula pétrea fundamental autônoma (EC 115).",
            "Resguardar a autodeterminação informativa no ambiente cibernético moderno.",
            "Incluído pela Emenda 115/2022 como garantia individual fundamental expressa."
        )

    # Art. 84 - Competências do Presidente
    if "84" in art_lower or any(k in txt for k in ["competência privativa do presidente", "sancionar, promulgar", "decretar o estado de defesa"]):
        return (
            "O Presidente da República edita um decreto autônomo extinguindo cargos públicos federais que se encontram vagos, sem criar novas despesas nem órgãos públicos (Art. 84, VI, 'b').",
            f"• **Aplicação no {art_num}:** Exercício de competências privativas privativas do Chefe do Executivo da União.",
            "Harmonizar o equilíbrio republicano de freios e contrapesos.",
            "Atenção aos incisos que admitem DELEGAÇÃO: VI (decreto autônomo), XII (indulto) e XXV (prover cargos federais nos termos da lei)."
        )

    # Art. 37 - Administração Pública e Concursos
    if "37" in art_lower or any(k in txt for k in ["administração pública", "concurso público", "acumulação remunerada", "investidura em cargo"]):
        return (
            "Um médico concursado do SUS é aprovado para outro cargo de médico em hospital municipal. Como há compatibilidade de horários, ele pode acumular os dois cargos de profissional de saúde regulamentada.",
            f"• **Aplicação no {art_num}:** Exceção constitucional permitida à regra geral que proíbe acumulação de cargos públicos.",
            "Permitir o aproveitamento de profissionais de áreas essenciais respeitando a compatibilidade de horários.",
            "Acumulações permitidas se houver compatibilidade: 2 de professor; 1 de professor com 1 técnico/científico; 2 privativos de profissionais de saúde."
        )

    # Se não caiu em nenhum caso tabelado, usa o motor heurístico dinâmico contextual!
    return gerar_exemplo_dinamico_heuristico(art_num, texto_original)

def gerar_explicacao_humana(art_num, texto_original, foi_correto=False, tipo_troca=None, texto_modificado=None, exemplo_customizado=None, foi_ia=False, nome_ia="Gemini IA"):
    if exemplo_customizado and len(exemplo_customizado) == 4:
        situacao_real, aplicacao_regra, objetivo_regra, bizu_memorizacao = exemplo_customizado
    else:
        situacao_real, aplicacao_regra, objetivo_regra, bizu_memorizacao = extrair_exemplo_objetivo_personalizado(art_num, texto_original)

    if foi_correto:
        status_txt = "O item está **CORRETO**."
        detalhe_erro = "O enunciado reproduz com exatidão a literalidade da legislação."
        resumo_erro_bloco = ""
    else:
        status_txt = "O item está **ERRADO**."
        detalhe_erro = "O enunciado promoveu alteração indevida da regra legal."
        resumo_erro_bloco = f"<br>⚠️ <strong>Pegadinha da Questão:</strong> {tipo_troca or 'Substituição de palavra-chave, prazo ou conectivo legal'}."

    tag_ia = f'<span style="background-color: #fef3c7; color: #b45309; padding: 2px 8px; border-radius: 6px; font-size: 11px; font-weight: 600; margin-left: 8px;">✨ Gerado com {nome_ia}</span>' if foi_ia else '<span style="background-color: #eff6ff; color: #1d4ed8; padding: 2px 8px; border-radius: 6px; font-size: 11px; font-weight: 600; margin-left: 8px;">⚖️ Exemplo Prático da Lei</span>'

    card_dispositivo_html = f"""
    <div style="background-color: #f8fafc; border: 1px solid #bfdbfe; border-radius: 10px; padding: 15px; margin-bottom: 14px;">
        <div style="font-weight: 600; color: #1e3a8a; font-size: 13.5px; margin-bottom: 6px;">📖 Dispositivo Literal da Lei Seca ({art_num})</div>
        <div style="color: #334155; font-style: italic; border-left: 3px solid #3b82f6; padding-left: 12px; line-height: 1.5; font-size: 13px;">
            "{texto_original}"
        </div>
    </div>
    """

    card_exemplo_html = f"""
    <div style="background-color: #fffbeb; border: 1px solid #fde68a; border-radius: 12px; padding: 18px; margin-bottom: 14px;">
        <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px;">
            <div style="font-weight: 700; color: #78350f; font-size: 14px;">
                💡 Exemplo Prático e Objetivo da Vida Real {tag_ia}
            </div>
        </div>
        <div style="color: #1f2937; line-height: 1.6; font-size: 13px;">
            <p style="margin-bottom: 8px;"><strong>Situação Concreta:</strong> {situacao_real}</p>
            <p style="margin-bottom: 8px;"><strong>Aplicação Prática:</strong> {aplicacao_regra}</p>
            <p style="margin-bottom: 8px;"><strong>Objetivo da Regra:</strong> {objetivo_regra}</p>
            <div style="margin-top: 10px; padding-top: 8px; border-top: 1px solid #fef3c7; color: #92400e; font-weight: 600;">
                🎯 <strong>Bizu de Memorização:</strong> {bizu_memorizacao}
            </div>
        </div>
    </div>
    """

    explicacao_formatada = f"""
    <div style="margin-bottom: 10px; font-size: 13.5px;">
        💡 <strong>Gabarito e Justificativa:</strong> {status_txt} {detalhe_erro}{resumo_erro_bloco}
    </div>
    {card_dispositivo_html}
    {card_exemplo_html}
    """
    return explicacao_formatada

# ==============================================================================
# GERAÇÃO DE QUESTÕES COM FRAGMENTAÇÃO E SUPORTE REAL AO GEMINI
# ==============================================================================

def generate_questions_for_articles(discipline_id, law_id, article_ids, qtd_total, filter_id=None, motor_ia="♊ Gemini IA (Recomendado)", chave_ia_manual=None, progress_callback=None):
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
        texto_artigo = limpar_e_formatar_texto_lei(art["texto"])
        alvos_artigo = fracionar_artigo_extenso(art["numero"], texto_artigo)
        for alvo in alvos_artigo:
            alvos.append({
                "art": art,
                "numero": alvo["numero"],
                "texto": alvo["texto"]
            })

    if not alvos:
        conn.close()
        return 0

    random.shuffle(alvos)
    generated = 0
    now = datetime.now().isoformat()

    usar_gemini = "Gemini" in motor_ia
    usar_openai = "OpenAI" in motor_ia
    
    # Cache em memória para não repetir chamadas de IA sobre o mesmo artigo/dispositivo
    cache_ia = {}

    for i in range(qtd_total):
        alvo = alvos[i % len(alvos)]
        art = alvo["art"]
        numero_dispositivo = alvo["numero"]
        rotulo_dispositivo = obter_rotulo_dispositivo(numero_dispositivo)
        text = limpar_e_formatar_texto_lei(alvo["texto"])
        is_correct = random.choice([True, False])

        if progress_callback:
            try:
                progress_callback((i + 1) / qtd_total, f"Processando questão {i+1} de {qtd_total}: {rotulo_dispositivo}...")
            except Exception:
                pass

        exemplo_ia = None
        chave_cache = (numero_dispositivo, text[:80])

        if usar_gemini:
            if chave_cache in cache_ia:
                exemplo_ia = cache_ia[chave_cache]
            else:
                exemplo_ia = gerar_exemplo_gemini(rotulo_dispositivo, text, chave_manual=chave_ia_manual)
                if exemplo_ia:
                    cache_ia[chave_cache] = exemplo_ia
        elif usar_openai:
            if chave_cache in cache_ia:
                exemplo_ia = cache_ia[chave_cache]
            else:
                exemplo_ia = gerar_exemplo_openai(rotulo_dispositivo, text, chave_manual=chave_ia_manual)
                if exemplo_ia:
                    cache_ia[chave_cache] = exemplo_ia

        foi_ia_utilizada = bool(exemplo_ia is not None)
        nome_ia = "Gemini IA" if usar_gemini else ("OpenAI" if usar_openai else "Inteligência Artificial")

        if is_correct:
            enunciado = f"De acordo com o **{rotulo_dispositivo}**:\n\n\"{text}\""
            gabarito = 1
            explicacao = gerar_explicacao_humana(
                numero_dispositivo,
                text,
                foi_correto=True,
                exemplo_customizado=exemplo_ia,
                foi_ia=foi_ia_utilizada,
                nome_ia=nome_ia
            )
        else:
            modified_text, tipo_troca = alterar_texto_para_errado(text)
            enunciado = f"De acordo com o **{rotulo_dispositivo}**:\n\n\"{modified_text}\""
            gabarito = 0
            explicacao = gerar_explicacao_humana(
                numero_dispositivo,
                text,
                foi_correto=False,
                tipo_troca=tipo_troca,
                texto_modificado=modified_text,
                exemplo_customizado=exemplo_ia,
                foi_ia=foi_ia_utilizada,
                nome_ia=nome_ia
            )

        try:
            conn.execute("""
                INSERT INTO questoes(lei_id, artigo_id, disciplina_id, filtro_id, artigo_numero, conteudo, enunciado, gabarito, explicacao, origem, criada_em)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """, (
                law_id,
                art["id"],
                discipline_id,
                filter_id,
                numero_dispositivo,
                numero_dispositivo,
                enunciado,
                gabarito,
                explicacao,
                motor_ia,
                now
            ))
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
        next_date = now
    else:
        priority = max(0, (old["prioridade"] if old else 1) - 1)
        intervals = [1, 3, 7, 15, 30]
        idx = min(len(intervals)-1, hits-1)
        next_date = now + timedelta(days=intervals[idx])

    conn.execute("""
        INSERT OR REPLACE INTO revisoes(usuario_id, questao_id, prioridade, proxima_revisao, erros, acertos)
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
    
    b_disc = pd.read_sql_query("""
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

    b_filt = pd.read_sql_query("""
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

    b_cont = pd.read_sql_query("""
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
    return total, hits, errors, pct, b_disc, b_filt, b_cont, due

# ==============================================================================
# INTERFACE PRINCIPAL DO STREAMLIT: BARRA LATERAL & ABAS
# ==============================================================================

with st.sidebar:
    st.markdown(f"👤 Utilizador: **{USERNAME}**")
    if st.button("🚪 Sair / Logout"):
        st.session_state["logged_in"] = False
        st.session_state["user_id"] = None
        st.session_state["username"] = None
        st.rerun()
    st.divider()

    st.markdown("### 🤖 Inteligência Artificial (IA)")
    chave_gemini_detectada = obter_chave_gemini()
    status_ia = "🟢 Ativa (Google Gemini)" if chave_gemini_detectada else "⚪ Modo Regras / Offline"
    st.caption(f"Status: **{status_ia}**")

    with st.expander("🔑 Chave API Gemini (Google AI)", expanded=(not bool(chave_gemini_detectada))):
        st.markdown(
            "Insira sua chave gratuita do **Google AI Studio** para gerar exemplos práticos da vida real inéditos e adaptados a qualquer dispositivo:"
        )
        nova_chave_gemini = st.text_input(
            "GEMINI_API_KEY:",
            value=st.session_state.get("gemini_api_key", chave_gemini_detectada or ""),
            type="password",
            key="input_gemini_side"
        )
        col_s1, col_s2 = st.columns(2)
        if col_s1.button("Salvar Chave", key="btn_save_key_side"):
            if nova_chave_gemini.strip():
                st.session_state["gemini_api_key"] = nova_chave_gemini.strip()
                os.environ["GEMINI_API_KEY"] = nova_chave_gemini.strip()
                st.success("Chave salva na sessão!")
                st.rerun()
            else:
                st.session_state.pop("gemini_api_key", None)
                st.info("Chave removida.")
                st.rerun()
        if col_s2.button("Testar IA", key="btn_test_ia_side"):
            with st.spinner("Testando conexão com a IA..."):
                t_key = nova_chave_gemini.strip() or chave_gemini_detectada
                ex_test = gerar_exemplo_gemini("Art. 5º, II", "ninguém será obrigado a fazer ou deixar de fazer alguma coisa senão em virtude de lei", chave_manual=t_key)
                if ex_test:
                    st.success("✅ IA conectada e gerando exemplos com sucesso!")
                else:
                    st.error("❌ Erro ao conectar com Gemini. Verifique a chave inserida.")

        st.caption("Obtenha sua chave gratuita em: [Google AI Studio](https://aistudio.google.com/app/apikey)")

    auto_ia_ativo = st.toggle(
        "⚡ Gerar IA ao responder questão",
        value=st.session_state.get("auto_ia_responder", True),
        key="toggle_auto_ia",
        help="Ao responder Certo/Errado em uma questão, a IA cria e salva um exemplo da vida real sob medida caso ainda não exista!"
    )
    st.session_state["auto_ia_responder"] = auto_ia_ativo
    st.divider()

    if is_admin_user:
        st.subheader("⚙ Atalho Admin")
        with st.expander("👥 Gerir Utilizadores", expanded=False):
            usuarios_cadastrados = listar_usuarios()
            st.write(f"**Total de utilizadores:** {len(usuarios_cadastrados)}")
            for u in usuarios_cadastrados:
                st.markdown(f"**{u['username']}**")
                c_status, c_del = st.columns([3, 1])
                is_this_admin = u['username'].strip().lower() == ADMIN_EMAIL
                if is_this_admin:
                    c_status.caption("👑 Admin Principal")
                else:
                    status_atual = bool(u['autorizado'])
                    novo_status = c_status.toggle("Autorizado", value=status_atual, key=f"aut_side_{u['id']}")
                    if novo_status != status_atual:
                        alterar_status_autorizacao(u['id'], 1 if novo_status else 0)
                        st.toast(f"Status de {u['username']} alterado!")
                        st.rerun()
                    if c_del.button("❌", key=f"del_side_{u['id']}", help="Excluir Utilizador"):
                        excluir_usuario(u['id'])
                        st.success(f"Utilizador {u['username']} removido!")
                        st.rerun()
                st.divider()

st.title("⚖ Decorando Lei Seca")

is_admin_user = bool(USERNAME and USERNAME.strip().lower() == ADMIN_EMAIL)

if is_admin_user:
    tab1, tab2, tab3, tab4, tab5, tab_admin = st.tabs([
        "📚 Importar Leis",
        "🎯 Criar Caderno / Filtro",
        "📝 Resolver Questões",
        "📊 Desempenho",
        "🔄 Revisões",
        "🛡 Painel Admin"
    ])
else:
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📚 Importar Leis",
        "🎯 Criar Caderno / Filtro",
        "📝 Resolver Questões",
        "📊 Desempenho",
        "🔄 Revisões"
    ])

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
    law_title = st.text_input("Nome da Lei (ex: CF/88, Código Penal, etc.):")
    uploaded_file = st.file_uploader("Escolha o ficheiro PDF da lei", type=["pdf"])

    if st.button("Processar e Salvar Lei"):
        if not disc_sel:
            st.error("Selecione uma disciplina!")
        elif not law_title:
            st.error("Informe o nome da lei!")
        elif not uploaded_file:
            st.error("Envie um ficheiro PDF!")
        else:
            disc_id = [d["id"] for d in discs if d["nome"] == disc_sel][0]
            file_path = PDF_DIR / uploaded_file.name
            with open(file_path, "wb") as f:
                f.write(uploaded_file.getbuffer())

            law_id = add_law(disc_id, law_title, uploaded_file.name)
            qtd = parse_and_store_pdf(file_path, law_id)
            st.success(f"Lei processada com sucesso! {qtd} artigos importados.")

    st.divider()
    st.subheader("🗑 Leis Cadastradas por Disciplina")
    todas_leis = get_laws()
    if todas_leis:
        leis_por_disciplina = {}
        for l in todas_leis:
            disc_nome = l['disciplina_nome']
            if disc_nome not in leis_por_disciplina:
                leis_por_disciplina[disc_nome] = []
            leis_por_disciplina[disc_nome].append(l)

        for disc_nome, lista_leis in leis_por_disciplina.items():
            with st.expander(f"📚 **{disc_nome}** ({len(lista_leis)} Lei(s))", expanded=False):
                for l in lista_leis:
                    lc1, lc2 = st.columns([4, 1])
                    lc1.write(f"📄 **{l['nome']}**")
                    if lc2.button("Excluir Lei", key=f"del_law_{l['id']}"):
                        delete_law(l['id'])
                        st.success(f"Lei '{l['nome']}' excluída com sucesso!")
                        st.rerun()
    else:
        st.info("Nenhuma lei cadastrada ainda.")

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
            
            selected_arts = st.multiselect("3. Selecione os Artigos/Trechos (deixe vazio para TODOS):", list(art_dict.keys()))
            
            total_arts_selecionados = len(selected_arts) if selected_arts else len(articles)
            sugestao_qtd = max(total_arts_selecionados * 2, 10)
            
            st.info(f"💡 **Sugestão do Sistema:** Esta lei/seleção possui **{total_arts_selecionados} artigo(s)/dispositivo(s)**.")

            qtd_q = st.number_input(
                "4. Quantidade de questões para este filtro:",
                min_value=1,
                max_value=500,
                value=sugestao_qtd
            )
            
            motor_ia = st.radio(
                "5. Selecione o Motor para Geração de Questões:",
                ["♊ Gemini IA (Recomendado - Exemplos Reais sob Medida)", "⚙️ Regra Padrão / Motor Contextual Integrado", "🤖 OpenAI (Nuvem)"],
                index=0
            )

            chave_atual = obter_chave_gemini()
            chave_informada_caderno = None
            if "Gemini" in motor_ia:
                if not chave_atual:
                    st.warning("⚠️ Nenhuma chave Gemini detectada. Insira abaixo para ativar a IA em todas as questões ou use o motor contextual.")
                    chave_informada_caderno = st.text_input(
                        "🔑 Chave Gemini API (Google AI Studio):",
                        type="password",
                        key="gemini_caderno_input",
                        help="Obtenha grátis em aistudio.google.com/app/apikey"
                    )
                    if chave_informada_caderno.strip():
                        st.session_state["gemini_api_key"] = chave_informada_caderno.strip()
                else:
                    st.success("🟢 Inteligência Artificial (Gemini) pronta para criar casos práticos reais sob medida!")

            filter_name = st.text_input("6. Nome do seu Caderno / Filtro:")

            if st.button("Salvar Caderno e Gerar Questões", type="primary"):
                if not filter_name:
                    st.error("Informe um nome para o seu caderno!")
                else:
                    chave_usar = chave_informada_caderno or chave_atual
                    prog_bar = st.progress(0, text="Iniciando motor de fragmentação e IA...")
                    
                    def atualizar_progresso(pct, texto):
                        prog_bar.progress(min(max(pct, 0.0), 1.0), text=texto)

                    art_ids = [art_dict[k] for k in selected_arts]
                    f_id = save_filter(filter_name, d_id, l_id, art_ids, qtd_q)
                    qtd_geradas = generate_questions_for_articles(
                        d_id, l_id, art_ids, qtd_q,
                        filter_id=f_id,
                        motor_ia=motor_ia,
                        chave_ia_manual=chave_usar,
                        progress_callback=atualizar_progresso
                    )
                    prog_bar.progress(1.0, text="Concluído com sucesso!")
                    st.success(f"🎉 Caderno '{filter_name}' criado com sucesso! {qtd_geradas} questões fragmentadas geradas com exemplos objetivos.")

    st.divider()
    st.subheader("🗑 Meus Cadernos / Filtros Salvos por Disciplina")
    meus_filtros = get_saved_filters()
    
    if meus_filtros:
        filtros_por_disciplina = {}
        for mf in meus_filtros:
            disc = mf['disciplina']
            if disc not in filtros_por_disciplina:
                filtros_por_disciplina[disc] = []
            filtros_por_disciplina[disc].append(mf)

        for disc_nome, lista_filtros in filtros_por_disciplina.items():
            with st.expander(f"📚 **{disc_nome}** ({len(lista_filtros)} Caderno(s))", expanded=False):
                for mf in lista_filtros:
                    fc1, fc2 = st.columns([4, 1])
                    fc1.write(f"📁 **{mf['nome']}** _(Lei: {mf['lei']})_")
                    if fc2.button("Excluir Caderno", key=f"del_filt_{mf['id']}"):
                        delete_filter(mf['id'])
                        st.success(f"Caderno '{mf['nome']}' removido com sucesso!")
                        st.rerun()

# ==============================================================================
# RESOLVER QUESTÕES (FORMATADO COMO A IMAGEM 2 E COM SUPORTE AO GEMINI AO VIVO)
# ==============================================================================

with tab3:
    st.header("Resolver Questões")
    
    discs = get_disciplines()
    disc_options = {"Todas as Disciplinas": None}
    for d in discs:
        disc_options[d["nome"]] = d["id"]

    selected_disc_label = st.selectbox("Selecione a Disciplina:", list(disc_options.keys()), key="res_disc_filter")
    selected_disc_id = disc_options[selected_disc_label]

    saved_filters = get_saved_filters(selected_disc_id)
    
    if not saved_filters:
        st.info("Nenhum caderno de questões encontrado para a disciplina selecionada.")
    else:
        f_options = {f"{f['nome']} ({f['disciplina']} - {f['lei']})": f["id"] for f in saved_filters}
        sel_filter_label = st.selectbox("Selecione o Caderno para Treinar:", list(f_options.keys()), key="res_caderno_filter")
        sel_filter_id = f_options[sel_filter_label]

        if "last_filter_id" not in st.session_state or st.session_state["last_filter_id"] != sel_filter_id:
            st.session_state["last_filter_id"] = sel_filter_id
            st.session_state["q_index"] = 0
            st.session_state["answered_q"] = {}

        conn = db()
        questoes = conn.execute("SELECT * FROM questoes WHERE filtro_id=? ORDER BY id", (sel_filter_id,)).fetchall()
        conn.close()

        if not questoes:
            st.warning("Nenhuma questão gerada para este caderno.")
        else:
            if "q_index" not in st.session_state:
                st.session_state["q_index"] = 0
            if "answered_q" not in st.session_state:
                st.session_state["answered_q"] = {}

            idx = st.session_state["q_index"]
            if idx >= len(questoes):
                st.success("🎉 Concluiu todas as questões deste caderno!")
                if st.button("Reiniciar Caderno"):
                    st.session_state["q_index"] = 0
                    st.session_state["answered_q"] = {}
                    st.rerun()
            else:
                q = questoes[idx]
                st.subheader(f"Questão {idx + 1} de {len(questoes)}")
                
                num_disp = q['artigo_numero']
                rotulo_formatado = obter_rotulo_dispositivo(num_disp)
                
                col_disp, col_badge = st.columns([4, 1])
                with col_disp:
                    st.markdown(f"**Dispositivo em Estudo:** `{rotulo_formatado}`")
                with col_badge:
                    tamanho = len(q["enunciado"])
                    if tamanho < 250:
                        st.caption("⚡ Dispositivo Curto / Direto")
                    else:
                        st.caption("🧩 Dispositivo Fragmentado")

                # Contexto transparente do Caput para incisos, parágrafos e alíneas
                is_subdevice = any(tag in num_disp.lower() for tag in ["§", "parágrafo", "inciso", "alínea", "alinea"]) or re.search(rf'\b{REGEX_ROMANO}\b', num_disp, re.IGNORECASE)
                if is_subdevice:
                    caput_text = obter_texto_caput(q["artigo_id"])
                    if caput_text:
                        with st.expander("📜 Contexto: Artigo Principal (Caput)", expanded=False):
                            st.write(f"_{caput_text}_")

                st.markdown(q["enunciado"])

                q_id = q["id"]
                ja_respondida = q_id in st.session_state["answered_q"]

                resp = st.radio("A sua resposta:", ["Certo", "Errado"], key=f"q_{q_id}", disabled=ja_respondida)
                
                if not ja_respondida:
                    if st.button("Responder", key=f"btn_{q_id}", type="primary"):
                        val = 1 if resp == "Certo" else 0
                        acertou = record_answer(q_id, val, cycle=1)
                        st.session_state["answered_q"][q_id] = {
                            "acertou": acertou,
                            "resposta": resp
                        }

                        # Auto-geração com IA ao vivo ao responder, caso ainda não tenha IA e esteja configurada
                        chave_ia = obter_chave_gemini()
                        auto_gerar = st.session_state.get("auto_ia_responder", True)
                        explicacao_atual = q["explicacao"] or ""
                        ja_tem_ia = ("✨ Gerado com Gemini IA" in explicacao_atual) or ("✨ Gerado com OpenAI" in explicacao_atual)

                        if chave_ia and auto_gerar and not ja_tem_ia:
                            texto_limpo_lei = q["enunciado"]
                            if "De acordo com o" in texto_limpo_lei:
                                linhas = texto_limpo_lei.split("\n\n")
                                if len(linhas) > 1:
                                    texto_limpo_lei = linhas[-1].strip('"\n ')

                            novo_ex_ia = gerar_exemplo_gemini(rotulo_formatado, texto_limpo_lei, chave_manual=chave_ia)
                            if novo_ex_ia:
                                nova_exp = gerar_explicacao_humana(
                                    num_disp,
                                    texto_limpo_lei,
                                    foi_correto=(val == q["gabarito"]),
                                    tipo_troca=None if q["gabarito"] == 1 else "Alteração indevida da literalidade legal",
                                    exemplo_customizado=novo_ex_ia,
                                    foi_ia=True,
                                    nome_ia="Gemini IA"
                                )
                                st.session_state[f"custom_explicacao_{q_id}"] = nova_exp
                                try:
                                    conn_u = db()
                                    conn_u.execute("UPDATE questoes SET explicacao = ? WHERE id = ?", (nova_exp, q_id))
                                    conn_u.commit()
                                    conn_u.close()
                                except Exception:
                                    pass
                        st.rerun()
                else:
                    dados_resp = st.session_state["answered_q"][q_id]
                    
                    # RENDERIZAÇÃO VISUAL EM CARTÕES MODERNOS
                    if dados_resp["acertou"]:
                        card_status_html = f"""
                        <div style="background-color: #ecfdf5; border: 1px solid #a7f3d0; border-radius: 12px; padding: 15px; margin-bottom: 14px; display: flex; align-items: center; gap: 12px;">
                            <div style="background-color: #059669; color: white; border-radius: 50%; width: 28px; height: 28px; display: flex; align-items: center; justify-content: center; font-weight: bold; font-size: 16px;">✓</div>
                            <div>
                                <div style="font-weight: 700; color: #065f46; font-size: 15px;">✨ Parabéns! Resposta Correta!</div>
                                <div style="color: #047857; font-size: 13px; margin-top: 2px;">Gabarito oficial: <strong>{'CERTO' if q['gabarito'] == 1 else 'ERRADO'}</strong></div>
                            </div>
                        </div>
                        """
                    else:
                        card_status_html = f"""
                        <div style="background-color: #fff1f2; border: 1px solid #fecdd3; border-radius: 12px; padding: 15px; margin-bottom: 14px; display: flex; align-items: center; gap: 12px;">
                            <div style="background-color: #e11d48; color: white; border-radius: 50%; width: 28px; height: 28px; display: flex; align-items: center; justify-content: center; font-weight: bold; font-size: 16px;">✕</div>
                            <div>
                                <div style="font-weight: 700; color: #9f1239; font-size: 15px;">❌ Resposta Incorreta! Atenção aos detalhes!</div>
                                <div style="color: #be123c; font-size: 13px; margin-top: 2px;">Gabarito oficial: <strong>{'CERTO' if q['gabarito'] == 1 else 'ERRADO'}</strong></div>
                            </div>
                        </div>
                        """
                    
                    st.markdown(card_status_html, unsafe_allow_html=True)
                    
                    # Se o usuário pediu para a IA gerar um novo exemplo ao vivo nesta questão:
                    explicacao_exibir = st.session_state.get(f"custom_explicacao_{q_id}", q['explicacao'])
                    st.markdown(explicacao_exibir, unsafe_allow_html=True)

                    c_btn_ia, c_btn_prox = st.columns([1, 1])
                    with c_btn_ia:
                        if st.button("✨ Gerar / Atualizar com IA (Gemini)", key=f"btn_ai_{q_id}"):
                            chave_ia = obter_chave_gemini()
                            if not chave_ia:
                                st.warning("⚠️ Insira a GEMINI_API_KEY na barra lateral à esquerda ou configure no Streamlit Secrets.")
                            else:
                                with st.spinner("Solicitando novo exemplo prático inédito ao Gemini..."):
                                    texto_limpo_lei = q["enunciado"]
                                    if "De acordo com o" in texto_limpo_lei:
                                        linhas = texto_limpo_lei.split("\n\n")
                                        if len(linhas) > 1:
                                            texto_limpo_lei = linhas[-1].strip('"\n ')
                                    novo_exemplo_ia = gerar_exemplo_gemini(rotulo_formatado, texto_limpo_lei, chave_manual=chave_ia)
                                    if novo_exemplo_ia:
                                        nova_exp = gerar_explicacao_humana(
                                            num_disp,
                                            texto_limpo_lei,
                                            foi_correto=(dados_resp["acertou"] == 1),
                                            tipo_troca=None if q["gabarito"] == 1 else "Alteração indevida da regra legal",
                                            exemplo_customizado=novo_exemplo_ia,
                                            foi_ia=True,
                                            nome_ia="Gemini IA"
                                        )
                                        st.session_state[f"custom_explicacao_{q_id}"] = nova_exp
                                        try:
                                            conn_u = db()
                                            conn_u.execute("UPDATE questoes SET explicacao = ? WHERE id = ?", (nova_exp, q_id))
                                            conn_u.commit()
                                            conn_u.close()
                                        except Exception:
                                            pass
                                        st.toast("Exemplo da vida real gerado pelo Gemini e salvo com sucesso!")
                                        st.rerun()
                                    else:
                                        st.error("Não foi possível conectar ao Gemini. Verifique a chave ou conexão.")

                    with c_btn_prox:
                        if st.button("Próxima Questão ➡️", key=f"next_{q_id}", type="primary"):
                            st.session_state["q_index"] += 1
                            st.rerun()

with tab4:
    st.header("O seu Desempenho")
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
    st.subheader("⚠ Redefinir Estatísticas")
    if st.button("Zerar Histórico de Respostas / Limpar Dashboard", type="secondary"):
        zerar_historico_dashboard()
        st.success("O seu histórico de respostas e indicadores do dashboard foram zerados!")
        st.rerun()

with tab5:
    st.header("Revisão Espaçada")
    tot, ac, err, pct, b_disc, b_filt, b_cont, due = stats()
    st.metric("Questões Pendentes para Revisão Hoje", due)

    if due > 0:
        conn = db()
        agora_str = datetime.now().isoformat()
        revs = conn.execute("""
            SELECT q.* FROM revisoes r
            JOIN questoes q ON q.id = r.questao_id
            WHERE r.usuario_id = ? AND r.proxima_revisao <= ?
            ORDER BY r.proxima_revisao ASC
            LIMIT 1
        """, (USER_ID, agora_str)).fetchone()
        
        if not revs:
            revs = conn.execute("""
                SELECT q.* FROM revisoes r
                JOIN questoes q ON q.id = r.questao_id
                WHERE r.usuario_id = ?
                LIMIT 1
            """, (USER_ID,)).fetchone()
            
        conn.close()

        if revs:
            st.subheader("Questão para Revisão")
            
            num_disp = revs['artigo_numero']
            st.markdown(f"**Dispositivo:** `{obter_rotulo_dispositivo(num_disp)}`")

            is_subdevice = any(tag in num_disp.lower() for tag in ["§", "parágrafo", "inciso", "alínea", "alinea"]) or re.search(rf'\b{REGEX_ROMANO}\b', num_disp, re.IGNORECASE)
            if is_subdevice and "artigo_id" in revs.keys() and revs["artigo_id"]:
                caput_text = obter_texto_caput(revs["artigo_id"])
                if caput_text:
                    with st.expander("📜 Contexto: Artigo Principal (Caput)", expanded=False):
                        st.write(f"_{caput_text}_")

            st.markdown(revs["enunciado"])
            
            q_id_rev = revs["id"]
            resp_rev = st.radio("A sua resposta:", ["Certo", "Errado"], key=f"rev_ans_{q_id_rev}")
            
            if st.button("Enviar Resposta da Revisão", key=f"btn_rev_{q_id_rev}", type="primary"):
                val = 1 if resp_rev == "Certo" else 0
                acertou = record_answer(q_id_rev, val, cycle=2)
                if acertou:
                    st.success("✨ Excelente! Próxima revisão agendada.")
                else:
                    st.error("❌ Errou! Ela voltará para revisão em breve.")
                st.markdown(f"{revs['explicacao']}", unsafe_allow_html=True)
                st.rerun()
        else:
            st.info("Nenhuma questão detalhada encontrada para revisão neste momento.")
    else:
        st.success("Tudo em dia! Não há revisões pendentes para hoje.")

if is_admin_user:
    with tab_admin:
        st.header("🛡 Painel de Controlo do Administrador")
        st.write("Gerencie e aprove o acesso de novos utilizadores ao sistema de forma rápida e segura.")
        
        usuarios_cadastrados = listar_usuarios()
        st.info(f"**Total de utilizadores cadastrados no sistema:** {len(usuarios_cadastrados)}")
        
        st.subheader("👥 Lista de Utilizadores e Autorizações")
        for u in usuarios_cadastrados:
            with st.container(border=True):
                col_info, col_toggle, col_del = st.columns([3, 2, 1])
                
                col_info.markdown(f"**E-mail / Utilizador:** `{u['username']}`")
                col_info.caption(f"Criado em: {u['criado_em'][:10]}")
                
                is_this_admin = u['username'].strip().lower() == ADMIN_EMAIL
                
                if is_this_admin:
                    col_toggle.markdown("👑 **Administrador Principal**")
                else:
                    status_atual = bool(u['autorizado'])
                    novo_status = col_toggle.toggle("Acesso Autorizado", value=status_atual, key=f"aut_tab_{u['id']}")
                    if novo_status != status_atual:
                        alterar_status_autorizacao(u['id'], 1 if novo_status else 0)
                        st.toast(f"Status de autorização de {u['username']} atualizado com sucesso!")
                        st.rerun()

                    if col_del.button("🗑️ Excluir", key=f"del_tab_{u['id']}", help="Remover Utilizador"):
                        excluir_usuario(u['id'])
                        st.success(f"Utilizador {u['username']} removido do sistema!")
                        st.rerun()

        st.divider()
        st.subheader("➕ Criar Novo Utilizador Autorizado Diretamente")
        col_au1, col_au2 = st.columns(2)
        with col_au1:
            adm_new_u = st.text_input("E-mail do Novo Utilizador", key="adm_u_tab")
        with col_au2:
            adm_new_p = st.text_input("Palavra-passe Inicial", type="password", key="adm_p_tab")
            
        if st.button("Cadastrar e Autorizar Imediatamente", type="primary"):
            if adm_new_u and adm_new_p:
                ok, msg = cadastrar_usuario(adm_new_u, adm_new_p, autorizado=1)
                if ok:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)
            else:
                st.warning("Preencha todos os campos para prosseguir.")







