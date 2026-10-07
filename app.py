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
        criado_em TEXT NOT NULL
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
        criada_em TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS respostas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario_id INTEGER,
        questao_id INTEGER NOT NULL,
        resposta INTEGER NOT NULL,
        acertou INTEGER NOT NULL,
        respondida_em TEXT NOT NULL,
        ciclo INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS revisoes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario_id INTEGER,
        questao_id INTEGER NOT NULL,
        prioridade INTEGER DEFAULT 1,
        proxima_revisao TEXT,
        erros INTEGER DEFAULT 0,
        acertos INTEGER DEFAULT 0,
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
        rows = conn.execute("SELECT l.*, d.nome as disciplina_nome FROM leis l JOIN disciplinas d ON d.id = l.disciplina_id WHERE l.disciplina_id=? ORDER BY d.nome, l.nome", (discipline_id,)).fetchall()
    else:
        rows = conn.execute("SELECT l.*, d.nome as disciplina_nome FROM leis l JOIN disciplinas d ON d.id = l.disciplina_id ORDER BY d.nome, l.nome").fetchall()
    conn.close()
    return rows

def normalizar_estrutura_dispositivo(texto):
    if not texto: return ""
    texto = texto.replace("\r", "\n")
    texto = re.sub(r'[ \t]+', ' ', texto)
    texto = re.sub(r'(?:;|\.|\n|\s)\s*(§\s*\d+º?|Parágrafo único)\b', r'\n\1 ', texto, flags=re.IGNORECASE)
    padrao_inciso = rf'(?:;|\.|\n|\s)\s*(?={REGEX_ROMANO}\s*[-–—\.]\s*)'
    texto = re.sub(padrao_inciso, '\n', texto, flags=re.IGNORECASE)
    texto = re.sub(r'(?:;|\.|\n|\s)\s*(?=[a-z]\s*[\)\-]\s*)', '\n', texto, flags=re.IGNORECASE)
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
    blocos = []
    atual_marcador = None
    atual_texto = []
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
    padroes_primeiro = [r'(?m)^§\s*\d+º?', r'(?m)^Parágrafo único\b', rf'(?m)^{REGEX_ROMANO}\s*[-–—\.]\s*']
    marcadores = [re.search(p, texto, re.IGNORECASE).start() for p in padroes_primeiro if re.search(p, texto, re.IGNORECASE)]
    inicio = texto[:min(marcadores)].strip() if marcadores else texto.strip()
    if inicio and len(inicio) > 10:
        inicio_limpo = re.sub(r'^Art\.\s*\d+[\w\-]*[\.\º\ª]?\s*[-–—]?\s*', '', inicio, flags=re.IGNORECASE).strip()
        if inicio_limpo:
            alvos.append({'numero': f'{num_art} (caput)', 'texto': inicio_limpo})
    for marcador, texto_inciso in incisos:
        if marcador and texto_inciso and len(texto_inciso) > 5:
            clean_marc = str(marcador).rstrip("-–—.").strip()
            alvos.append({'numero': f'{num_art}, Inciso {clean_marc}', 'texto': f'{marcador} {texto_inciso}'.strip()})
    for marcador_par, texto_par in paragrafos:
        if marcador_par and texto_par and len(texto_par) > 5:
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
    cur = conn.execute("INSERT INTO filtros_salvos (usuario_id, nome, disciplina_id, lei_id, artigos_ids, qtd_questoes, criado_em) VALUES (?, ?, ?, ?, ?, ?, ?)", (USER_ID, name, discipline_id, law_id, art_str, qtd_questoes, datetime.now().isoformat()))
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
        texto_limpo = limpar_e_formatar_texto_lei(artigo["texto"])
        texto_normalizado = normalizar_estrutura_dispositivo(texto_limpo)
        m = re.search(rf'(?m)^(?:§\s*\d+º?|Parágrafo único\b|{REGEX_ROMANO}\s*[-–—\.]\s*)', texto_normalizado, re.IGNORECASE)
        return texto_normalizado[:m.start()].strip() if m else texto_normalizado.strip()
    return None

def limpar_assertiva_dispositivo(texto):
    if not texto: return ""
    t = texto.strip()
    t = re.sub(rf'^(?:{REGEX_ROMANO}\s*[-–—\.]\s*|§\s*\d+º?\s*[-–—\.]?\s*|Parágrafo único\s*[-–—\.]?\s*|[a-z]\s*[\)\-]\s*)', '', t, flags=re.IGNORECASE).strip()
    t = re.sub(r'[\s;:,]+$', '', t).strip()
    if not t: return texto.strip()
    t = t[0].upper() + t[1:]
    if not t.endswith('.'): t += '.'
    return t

def conectar_caput_com_dispositivo(caput_texto, assertiva_limpa, rotulo_dispositivo):
    if not caput_texto or not assertiva_limpa: return assertiva_limpa
    cap = caput_texto.strip()
    if re.search(r'compete\s+privativamente\s+ao\s+presidente\s+da\s+república', cap, re.IGNORECASE):
        if not re.search(r'compete', assertiva_limpa, re.IGNORECASE):
            return f"Compete privativamente ao Presidente da República {assertiva_limpa[0].lower() + assertiva_limpa[1:]}"
    if cap.endswith(':') and len(cap) < 120:
        return f"{cap.rstrip(':').strip()} {assertiva_limpa[0].lower() + assertiva_limpa[1:]}"
    return assertiva_limpa

def formatar_nome_lei_contextual(nome_lei):
    if not nome_lei: return "Constituição Federal / Lei Seca"
    nl = str(nome_lei).strip()
    if re.match(r'^art(?:igo)?s?\.?\s*\d+', nl, re.IGNORECASE):
        return f"Constituição Federal de 1988 ({nl})"
    return nl

def construir_enunciado_com_nexo(nome_lei, rotulo_dispositivo, assertiva_texto, caput_texto=None, num_art=None):
    ref_rotulo = obter_rotulo_dispositivo(rotulo_dispositivo)
    lei_formatada = formatar_nome_lei_contextual(nome_lei)
    vinculo = f" (pertencente ao {num_art})" if num_art and num_art not in ref_rotulo else ""
    return f"**Referência Normativa:** {lei_formatada} — **{ref_rotulo}**{vinculo}\n\nÀ luz da literalidade da legislação e do dispositivo legal em exame, julgue o item a seguir:\n\n> \"{assertiva_texto}\""

def obter_rotulo_dispositivo(numero_dispositivo):
    if not numero_dispositivo: return "Dispositivo da Lei"
    s = str(numero_dispositivo).strip()
    return re.sub(r'^(?:Inciso|Parágrafo|Alínea|Artigo)\s*\((.+)\)$', r'\1', s, flags=re.IGNORECASE)

def alterar_texto_para_errado(texto):
    substituicoes = [
        (r'\brespeito à integridade física e moral\b', 'respeito à integridade física, sendo dispensada a tutela de sua integridade moral', 'restrição indevida: a CF/88 assegura o respeito à integridade física E moral'),
        (r'\b24 \(vinte e quatro\) horas\b', '48 (quarenta e oito) horas', 'alteração indevida de prazo legal'),
        (r'\bdeverá\b', 'poderá', 'troca de comando obrigatório por faculdade'),
        (r'\bpoderá\b', 'deverá obrigatoriamente', 'troca de faculdade por obrigação'),
        (r'\bvedado\b', 'permitido', 'inversão de proibição para permissão'),
        (r'\bpermitido\b', 'vedado', 'inversão de permissão para proibição')
    ]
    texto_modificado = texto
    tipo_troca = None
    for padrao, sub, desc in substituicoes:
        if re.search(padrao, texto_modificado, re.IGNORECASE):
            texto_modificado = re.sub(padrao, sub, texto_modificado, count=1, flags=re.IGNORECASE)
            tipo_troca = desc
            break
    if not tipo_troca:
        inversoes = [
            (r'^É assegurado\b', 'Não é assegurado', 'inversão do direito assegurado'),
            (r'^É vedad[oa]\b', 'É permitido', 'inversão de vedação'),
            (r'\bnão será\b', 'será', 'supressão da negativa')
        ]
        for padrao, sub, desc in inversoes:
            if re.search(padrao, texto_modificado, re.IGNORECASE):
                texto_modificado = re.sub(padrao, sub, texto_modificado, count=1, flags=re.IGNORECASE)
                tipo_troca = desc
                break
    if not tipo_troca:
        texto_modificado = f"{texto_modificado.rstrip('.')}, ressalvada decisão discricionária em sentido contrário."
        tipo_troca = 'criação de ressalva não prevista na lei'
    if texto_modificado:
        texto_modificado = texto_modificado[0].upper() + texto_modificado[1:]
        if not texto_modificado.endswith('.'): texto_modificado += '.'
    return texto_modificado, tipo_troca

def obter_chave_gemini(chave_manual=None):
    if chave_manual and str(chave_manual).strip(): return str(chave_manual).strip()
    if st.session_state.get("gemini_api_key"): return str(st.session_state["gemini_api_key"]).strip()
    try:
        if "GEMINI_API_KEY" in st.secrets: return str(st.secrets["GEMINI_API_KEY"]).strip()
    except Exception:
        pass
    return os.getenv("GEMINI_API_KEY")

def extrair_json_exemplo(raw_text, rotulo_dispositivo):
    if not raw_text: return None
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
                return (sit.strip(), f"• **Aplicação no {rotulo_dispositivo}:** {ap.strip() if ap else 'Aplicação direta.'}", obj.strip() if obj else "Garantir a segurança jurídica.", biz.strip() if biz else "Atenção às palavras-chave.")
        except Exception:
            pass
    return None

def gerar_exemplo_gemini(rotulo_dispositivo, texto_dispositivo, chave_manual=None):
    chave = obter_chave_gemini(chave_manual)
    if not chave: return None
    prompt = f"Dispositivo legal: {rotulo_dispositivo} - \"{texto_dispositivo}\". Crie um exemplo prático da vida real em JSON com as chaves: 'situacao_real', 'aplicacao_regra', 'objetivo_regra', 'bizu_memorizacao'."
    for model_name in ["gemini-2.5-flash", "gemini-1.5-flash"]:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={chave}"
            req = urllib.request.Request(url, data=json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=10) as resp:
                res = json.loads(resp.read().decode("utf-8"))
                txt = res["candidates"][0]["content"]["parts"][0]["text"]
                parsed = extrair_json_exemplo(txt, rotulo_dispositivo)
                if parsed: return parsed
        except Exception:
            pass
    return None

def extrair_exemplo_objetivo_personalizado(art_num, texto_original):
    return (
        f"Num caso prático envolvendo o {art_num}, aplicou-se rigorosamente a norma legal para assegurar a justiça e a legalidade na situação concreta.",
        f"• **Aplicação no {art_num}:** Observância estrita da literalidade normativa.",
        "Garantir a eficácia da lei e a segurança jurídica.",
        "Atente-se aos termos literais e prazos previstos."
    )

def gerar_explicacao_humana(art_num, texto_original, foi_correto=False, tipo_troca=None, texto_modificado=None, exemplo_customizado=None, foi_ia=False, nome_ia="Gemini IA", caput_texto=None):
    situacao_real, aplicacao_regra, objetivo_regra, bizu_memorizacao = exemplo_customizado or extrair_exemplo_objetivo_personalizado(art_num, texto_original)
    status_txt = "O item está **CORRETO**." if foi_correto else "O item está **ERRADO**."
    detalhe_erro = "O enunciado reproduz com exatidão a literalidade da legislação." if foi_correto else f"<br>⚠️ <strong>Pegadinha:</strong> {tipo_troca or 'Alteração indevida'}"
    tag_ia = f'<span style="background-color: #fef3c7; color: #b45309; padding: 2px 8px; border-radius: 6px; font-size: 11px; font-weight: 600;">✨ Gerado com {nome_ia}</span>' if foi_ia else '<span style="background-color: #eff6ff; color: #1d4ed8; padding: 2px 8px; border-radius: 6px; font-size: 11px; font-weight: 600;">⚖️ Exemplo Prático</span>'
    
    return f"""
    <div style="margin-bottom: 10px; font-size: 13.5px;">💡 <strong>Gabarito e Justificativa:</strong> {status_txt} {detalhe_erro}</div>
    <div style="background-color: #f8fafc; border: 1px solid #bfdbfe; border-radius: 10px; padding: 15px; margin-bottom: 14px;">
        <div style="font-weight: 600; color: #1e3a8a; font-size: 13.5px; margin-bottom: 6px;">📖 Dispositivo Literal ({art_num})</div>
        <div style="color: #334155; font-style: italic; border-left: 3px solid #3b82f6; padding-left: 12px;">"{texto_original}"</div>
    </div>
    <div style="background-color: #fffbeb; border: 1px solid #fde68a; border-radius: 12px; padding: 18px; margin-bottom: 14px;">
        <div style="display: flex; justify-content: space-between; margin-bottom: 10px; font-weight: 700; color: #78350f;">💡 Exemplo Prático {tag_ia}</div>
        <div style="color: #1f2937; font-size: 13px;">
            <p style="margin-bottom: 8px;"><strong>Situação:</strong> {situacao_real}</p>
            <p style="margin-bottom: 8px;"><strong>Aplicação:</strong> {aplicacao_regra}</p>
            <p style="margin-bottom: 8px;"><strong>Objetivo:</strong> {objetivo_regra}</p>
            <div style="margin-top: 10px; border-top: 1px solid #fef3c7; color: #92400e; font-weight: 600; padding-top: 6px;">🎯 <strong>Bizu:</strong> {bizu_memorizacao}</div>
        </div>
    </div>
    """

def generate_questions_for_articles(discipline_id, law_id, article_ids, qtd_total, filter_id=None, motor_ia="♊ Gemini IA", chave_ia_manual=None):
    conn = db()
    lei_row = conn.execute("SELECT nome FROM leis WHERE id=?", (law_id,)).fetchone()
    nome_lei = lei_row["nome"] if lei_row else "Legislação"
    arts = conn.execute(f"SELECT * FROM artigos WHERE id IN ({','.join('?'*len(article_ids))}) ORDER BY id", article_ids).fetchall() if article_ids else conn.execute("SELECT * FROM artigos WHERE lei_id=? ORDER BY id", (law_id,)).fetchall()
    if not arts:
        conn.close()
        return 0
    alvos = [{'art': a, 'numero': a['numero'], 'texto': limpar_e_formatar_texto_lei(a['texto']), 'caput': obter_texto_caput(a['id'])} for a in arts]
    random.shuffle(alvos)
    generated = 0
    now = datetime.now().isoformat()
    usar_gemini = "Gemini" in motor_ia

    for i in range(qtd_total):
        alvo = alvos[i % len(alvos)]
        art, num, text, caput = alvo['art'], alvo['numero'], alvo['texto'], alvo['caput']
        rotulo = obter_rotulo_dispositivo(num)
        is_correct = random.choice([True, False])
        exemplo_ia = gerar_exemplo_gemini(rotulo, text, chave_manual=chave_ia_manual) if usar_gemini else None
        
        assertiva = limpar_assertiva_dispositivo(text)
        assertiva_nexo = conectar_caput_com_dispositivo(caput, assertiva, rotulo)
        
        if is_correct:
            enunciado = construir_enunciado_com_nexo(nome_lei, rotulo, assertiva_nexo, caput_texto=caput, num_art=art["numero"])
            explicacao = gerar_explicacao_humana(num, text, foi_correto=True, exemplo_customizado=exemplo_ia, foi_ia=bool(exemplo_ia), caput_texto=caput)
            gabarito = 1
        else:
            assertiva_errada, tipo_troca = alterar_texto_para_errado(assertiva_nexo)
            enunciado = construir_enunciado_com_nexo(nome_lei, rotulo, assertiva_errada, caput_texto=caput, num_art=art["numero"])
            explicacao = gerar_explicacao_humana(num, text, foi_correto=False, tipo_troca=tipo_troca, exemplo_customizado=exemplo_ia, foi_ia=bool(exemplo_ia), caput_texto=caput)
            gabarito = 0

        conn.execute("INSERT INTO questoes(lei_id, artigo_id, disciplina_id, filtro_id, artigo_numero, conteudo, enunciado, gabarito, explicacao, origem, criada_em) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                     (law_id, art["id"], discipline_id, filter_id, num, num, enunciado, gabarito, explicacao, motor_ia, now))
        generated += 1
    conn.commit()
    conn.close()
    return generated

def record_answer(question_id, answer, cycle):
    conn = db()
    q = conn.execute("SELECT * FROM questoes WHERE id=?", (question_id,)).fetchone()
    correct = int(answer == q["gabarito"])
    now = datetime.now()
    conn.execute("INSERT INTO respostas(usuario_id, questao_id, resposta, acertou, respondida_em, ciclo) VALUES(?,?,?,?,?,?)", (USER_ID, question_id, answer, correct, now.isoformat(), cycle))
    conn.execute("INSERT OR REPLACE INTO revisoes(usuario_id, questao_id, prioridade, proxima_revisao, erros, acertos) VALUES(?,?,?,?,?,?)",
                 (USER_ID, question_id, 1, (now + timedelta(days=1)).isoformat(), 0 if correct else 1, 1 if correct else 0))
    conn.commit()
    conn.close()
    return correct

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
    if st.button("🚪 Sair"):
        st.session_state.clear()
        st.rerun()

st.title("⚖ Decorando Lei Seca")

tab1, tab2, tab3, tab4, tab5 = st.tabs(["📚 Importar Leis", "🎯 Criar Caderno", "📝 Resolver Questões", "📊 Desempenho", "🔄 Revisões"])

with tab1:
    st.header("Importar Nova Lei")
    discs = get_disciplines()
    disc_names = [d["nome"] for d in discs]
    col1, col2 = st.columns(2)
    with col1:
        new_disc = st.text_input("Nova Disciplina:")
        if st.button("Cadastrar Disciplina") and new_disc:
            add_discipline(new_disc)
            st.rerun()
    with col2:
        disc_sel = st.selectbox("Disciplina:", [""] + disc_names)
    law_title = st.text_input("Nome da Lei:")
    uploaded_file = st.file_uploader("PDF", type=["pdf"])
    if st.button("Processar Lei") and disc_sel and law_title and uploaded_file:
        d_id = [d["id"] for d in discs if d["nome"] == disc_sel][0]
        path = PDF_DIR / uploaded_file.name
        with open(path, "wb") as f: f.write(uploaded_file.getbuffer())
        law_id = add_law(d_id, law_title, uploaded_file.name)
        parse_and_store_pdf(path, law_id)
        st.success("Lei processada com sucesso!")

with tab2:
    st.header("Criar Caderno")
    discs = get_disciplines()
    disc_dict = {d["nome"]: d["id"] for d in discs}
    disc_f = st.selectbox("Disciplina:", [""] + list(disc_dict.keys()), key="c_disc")
    if disc_f:
        d_id = disc_dict[disc_f]
        laws = get_laws(d_id)
        law_dict = {l["nome"]: l["id"] for l in laws}
        law_f = st.selectbox("Lei:", [""] + list(law_dict.keys()), key="c_law")
        if law_f:
            l_id = law_dict[law_f]
            arts = get_articles(l_id)
            art_dict = {f"{a['numero']} - {a['texto'][:50]}...": a["id"] for a in arts}
            sel_arts = st.multiselect("Artigos:", list(art_dict.keys()))
            qtd = st.number_input("Quantidade:", min_value=1, value=10)
            f_name = st.text_input("Nome do Caderno:")
            if st.button("Gerar Caderno") and f_name:
                art_ids = [art_dict[k] for k in sel_arts] if sel_arts else [a["id"] for a in arts]
                f_id = save_filter(f_name, d_id, l_id, art_ids, qtd)
                generate_questions_for_articles(d_id, l_id, art_ids, qtd, filter_id=f_id)
                st.success("Caderno gerado com sucesso!")

with tab3:
    st.header("Resolver Questões")
    filters = get_saved_filters()
    if not filters:
        st.info("Nenhum caderno criado.")
    else:
        f_map = {f"{f['nome']} ({f['disciplina']} - {f['lei']})": f["id"] for f in filters}
        sel_label = st.selectbox("Caderno:", list(f_map.keys()))
        f_id = f_map[sel_label]
        conn = db()
        questoes = conn.execute("SELECT * FROM questoes WHERE filtro_id=?", (f_id,)).fetchall()
        conn.close()
        if not questoes:
            st.warning("Sem questões.")
        else:
            if "q_idx" not in st.session_state: st.session_state["q_idx"] = 0
            idx = st.session_state["q_idx"]
            if idx >= len(questoes):
                st.success("Concluído!")
                if st.button("Recomeçar"):
                    st.session_state["q_idx"] = 0
                    st.rerun()
            else:
                q = questoes[idx]
                st.markdown(f"**Dispositivo:** `{q['artigo_numero']}`")
                st.markdown(q["enunciado"])
                resp = st.radio("Resposta:", ["Certo", "Errado"], key=f"ans_{q['id']}")
                if st.button("Responder", type="primary"):
                    val = 1 if resp == "Certo" else 0
                    acertou = record_answer(q["id"], val, 1)
                    st.session_state[f"resp_{q['id']}"] = acertou
                    st.rerun()
                
                if f"resp_{q['id']}" in st.session_state:
                    acertou = st.session_state[f"resp_{q['id']}"]
                    if acertou: st.success("✨ Correto!")
                    else: st.error("❌ Incorreto!")
                    
                    # CORREÇÃO CRUCIAL APLICADA AQUI (unsafe_allow_html=True)
                    explicacao_exibir = st.session_state.get(f"custom_explicacao_{q['id']}", q['explicacao'])
                    st.markdown(explicacao_exibir, unsafe_allow_html=True)
                    
                    if st.button("Próxima Questão ➡️"):
                        st.session_state["q_idx"] += 1
                        st.rerun()

with tab4:
    st.header("Desempenho")
    tot, ac, err, pct, b_disc, b_filt, due = stats()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Respondidas", tot)
    c2.metric("Acertos", ac)
    c3.metric("Erros", err)
    c4.metric("Aproveitamento", f"{pct:.1f}%")

with tab5:
    st.header("Revisão Espaçada")
    tot, ac, err, pct, b_disc, b_filt, due = stats()
    st.metric("Pendentes", due)
