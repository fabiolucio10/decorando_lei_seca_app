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

try:
    import openai
except ImportError:
    openai = None

APP_DIR = Path(__file__).parent
DB_FILE = APP_DIR / "decorando_lei.db"
PDF_DIR = APP_DIR / "leis_importadas"
PDF_DIR.mkdir(exist_ok=True)

# Configuração da página
st.set_page_config(
    page_title="Decorando Lei Seca",
    page_icon="⚖",
    layout="wide"
)

# Estilização CSS para ocultar menus, cabeçalhos, rodapés e a barra flutuante do Streamlit Cloud
st.markdown("""
    <style>
    /* Oculta menus padrão e cabeçalho */
    #MainMenu {visibility: hidden;}
    header {visibility: hidden;}
    footer {visibility: hidden;}
    
    /* Esconde botão de deploy e badges */
    [data-testid="stAppDeployButton"] {display: none !important;}
    .viewerBadge_container__1S-xd {display: none !important;}
    
    /* Desativa a barra flutuante e widgets do Streamlit Cloud */
    [data-testid="stStatusWidget"] {display: none !important;}
    div[class*="stAppToolbar"] {display: none !important;}
    div[class*="viewerBadge"] {display: none !important;}
    div[class*="styles_viewerBadge"] {display: none !important;}
    
    /* Esconde botões de ação e gestão */
    button[title="Manage app"] {display: none !important;}
    button[title="Gerenciar aplicativo"] {display: none !important;}
    div[class^="stActionButton"] {display: none !important;}
    
    /* Remove espaçamento residual do cabeçalho */
    .stApp > header + div {padding-top: 0rem;}
    section[data-testid="stSidebar"] + div {padding-top: 0rem;}
    </style>
""", unsafe_allow_html=True)

def db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def hash_password(password):
    return hashlib.sha256(password.encode("utf-8")).hexdigest()

def limpar_e_formatar_texto_lei(texto):
    """
    Remove notas de alteração/inclusão legislativa, URLs, datas do Planalto.
    """
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

    texto = re.sub(r' +', ' ', texto)
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

    conn.execute("UPDATE usuarios SET autorizado = 1 WHERE LOWER(username) = 'fabiolucio277@gmail.com'")
    conn.commit()
    conn.close()

init_db()

def cadastrar_usuario(username, senha, autorizado=0):
    conn = db()
    u_clean = username.strip().lower()
    if u_clean == "fabiolucio277@gmail.com":
        autorizado = 1
    try:
        conn.execute(
            "INSERT INTO usuarios (username, senha, autorizado, criado_em) VALUES (?, ?, ?, ?)",
            (u_clean, hash_password(senha), autorizado, datetime.now().isoformat())
        )
        conn.commit()
        conn.close()
        return True, "Cadastro realizado! Aguarde a liberação do administrador para acessar o sistema." if autorizado == 0 else "Usuário criado e autorizado!"
    except sqlite3.IntegrityError:
        conn.close()
        return False, "Nome de usuário já existe!"

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
        u = st.text_input("Usuário / E-mail", key="login_user")
        p = st.text_input("Senha", type="password", key="login_pass")
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
                    st.warning("⚠️ Sua conta aguarda aprovação do administrador. Entre em contato para liberação.")
            else:
                st.error("Usuário ou senha incorretos.")

    with tab_cadastro:
        new_u = st.text_input("Escolha um Usuário / E-mail", key="cad_user")
        new_p = st.text_input("Escolha uma Senha", type="password", key="cad_pass")
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

with st.sidebar:
    st.markdown(f"👤 Usuário: **{USERNAME}**")
    if st.button("🚪 Sair / Logout"):
        st.session_state["logged_in"] = False
        st.session_state["user_id"] = None
        st.session_state["username"] = None
        st.rerun()
    st.divider()

    if USERNAME.lower() == "fabiolucio277@gmail.com":
        st.subheader("⚙️ Painel do Administrador")
        with st.expander("👥 Gerenciar e Autorizar Usuários", expanded=False):
            usuarios_cadastrados = listar_usuarios()
            st.write(f"**Total de usuários:** {len(usuarios_cadastrados)}")
            
            for u in usuarios_cadastrados:
                st.markdown(f"**{u['username']}**")
                c_status, c_del = st.columns([3, 1])
                
                is_admin = u['username'].lower() == "fabiolucio277@gmail.com"
                
                if is_admin:
                    c_status.caption("👑 Administrador Principal")
                else:
                    status_atual = bool(u['autorizado'])
                    novo_status = c_status.toggle("Autorizado", value=status_atual, key=f"aut_{u['id']}")
                    if novo_status != status_atual:
                        alterar_status_autorizacao(u['id'], 1 if novo_status else 0)
                        st.toast(f"Status de {u['username']} alterado!")
                        st.rerun()

                    if c_del.button("❌", key=f"del_user_{u['id']}", help="Excluir Usuário"):
                        excluir_usuario(u['id'])
                        st.success(f"Usuário {u['username']} removido!")
                        st.rerun()

                st.divider()

            st.write("**Criar Novo Usuário Autorizado:**")
            adm_new_u = st.text_input("E-mail do Novo Usuário", key="adm_u")
            adm_new_p = st.text_input("Senha", type="password", key="adm_p")
            if st.button("Criar Usuário pelo Admin"):
                if adm_new_u and adm_new_p:
                    ok, msg = cadastrar_usuario(adm_new_u, adm_new_p, autorizado=1)
                    if ok:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)
                else:
                    st.warning("Preencha todos os campos.")
        st.divider()

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

def parse_and_store_pdf(pdf_path, law_id):
    """
    Lê o PDF e fraciona o conteúdo por Artigo e por subdivisiones (Parágrafos/Incisos)
    quando o artigo for extenso, garantindo enunciados curtos e focados.
    """
    doc = fitz.open(pdf_path)
    full_text = "\n".join([page.get_text() for page in doc])
    doc.close()

    artigo_regex = re.compile(r'(Art\.\s*\d+[\w\d\-\.]*)', re.IGNORECASE)
    
    # Divide primeiro por "Art."
    partes = artigo_regex.split(full_text)
    artigos_brutos = []
    
    for i in range(1, len(partes), 2):
        num_art = partes[i].strip()
        corpo_art = partes[i+1] if (i+1) < len(partes) else ""
        artigos_brutos.append((num_art, corpo_art))

    unidades_finais = []

    for num_art, corpo in artigos_brutos:
        corpo_limpo = limpar_e_formatar_texto_lei(corpo)
        
        # Se o artigo for longo (mais de 300 caracteres), quebra por Parágrafo ou Inciso
        if len(corpo_limpo) > 300:
            subblocos = re.split(r'(\n\s*(?:§\s*\d+º?|Parágrafo único|[I|V|X]+\s*-))', corpo_limpo, flags=re.IGNORECASE)
            
            if len(subblocos) > 1:
                caput = subblocos[0].strip()
                if caput:
                    unidades_finais.append((f"{num_art} (caput)", caput))
                
                idx_sub = 1
                while idx_sub < len(subblocos):
                    rotulo = subblocos[idx_sub].strip()
                    texto_sub = subblocos[idx_sub+1].strip() if (idx_sub+1) < len(subblocos) else ""
                    bloco_completo = f"{rotulo} {texto_sub}".strip()
                    if bloco_completo:
                        unidades_finais.append((f"{num_art} - {rotulo}", bloco_completo))
                    idx_sub += 2
            else:
                unidades_finais.append((num_art, corpo_limpo))
        else:
            unidades_finais.append((num_art, corpo_limpo))

    conn = db()
    for num, txt in unidades_finais:
        if txt.strip():
            conn.execute(
                "INSERT INTO artigos(lei_id, numero, titulo, texto) VALUES(?,?,?,?)",
                (law_id, num, num, txt.strip())
            )
    conn.commit()
    conn.close()
    return len(unidades_finais)

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
    """
    Modifica o texto para criar um erro sutil e natural.
    """
    substituicoes = [
        (r'\bdeverá\b', 'poderá', 'troca de obrigação ("deverá") por faculdade ("poderá")'),
        (r'\bpoderá\b', 'deverá', 'troca de faculdade ("poderá") por obrigação ("deverá")'),
        (r'\b24 \(vinte e quatro\) horas\b', '48 (quarenta e oito) horas', 'alteração de prazo legal de 24h para 48h'),
        (r'\b72 \(setenta e duas\) horas\b', '24 (vinte e quatro) horas', 'alteração de prazo legal de 72h para 24h'),
        (r'\b12 \(doze\) horas\b', '24 (vinte e quatro) horas', 'alteração do prazo de manifestação de 12h para 24h'),
        (r'\b30 \(trinta\) dias\b', '15 (quinze) dias', 'alteração do prazo de fornecimento de dados'),
        (r'\bpermitido\b', 'vedado', 'inversão de permissão para proibição'),
        (r'\bvedado\b', 'permitido', 'inversão de proibição para permissão'),
        (r'\bexigido\b', 'dispensado', 'troca de exigência por dispensa'),
        (r'\bdispensado\b', 'exigido', 'troca de dispensa por exigência'),
        (r'\bobrigatório\b', 'facultativo', 'troca de obrigação por faculdade'),
        (r'\bfacultativo\b', 'obrigatório', 'troca de faculdade por obrigação'),
        (r'\bindependentemente de autorização judicial\b', 'mediante autorização judicial', 'exigência indevida de autorização judicial'),
        (r'\bmediante autorização judicial\b', 'independente de autorização judicial', 'supressão da necessidade de autorização judicial')
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

def gerar_explicacao_humana(art_num, texto_original, foi_correto=False, tipo_troca=None, texto_modificado=None):
    """
    Gera explicações didáticas focadas na historinha prática do caso concreto.
    """
    txt_lower = texto_original.lower()

    # Construção contextualizada da história do caso real
    if "dados" in txt_lower or "informações cadastrais" in txt_lower or "requisitar" in txt_lower:
        situacao_real = "Ocorre um sequestro ou tráfico de pessoas e a polícia precisa identificar rapidamente a vítima ou os suspeitos obtendo dados de cadastro (nome, CPF, endereço)."
        regra_aplicada = f"O **{art_num}** permite que o Delegado ou Promotor requisite esses dados diretamente a órgãos públicos ou empresas privadas sem precisar aguardar autorização judicial prévia."
    elif "sinal" in txt_lower or "telecomunicações" in txt_lower or "localização" in txt_lower:
        situacao_real = "Um crime grave está em andamento e a polícia precisa rastrear a localização do telemóvel do suspeito através das antenas de telefonia."
        regra_aplicada = f"O **{art_num}** autoriza a requisição do sinal (estação de cobertura), mas exige **autorização judicial** e estabelece prazos rigorosos para o procedimento."
    elif "flagrante" in txt_lower or "prisão" in txt_lower:
        situacao_real = "Um suspeito rouba uma pessoa na rua e é apanhado logo em seguida pela polícia ainda em posse do bem."
        regra_aplicada = f"O **{art_num}** determina que a prisão em flagrante exige a lavratura do auto e o envio imediato da documentação ao juiz e família no prazo legal."
    elif "inquérito" in txt_lower or "instaurado" in txt_lower:
        situacao_real = "A polícia toma conhecimento da prática de uma infração penal e precisa dar início oficial às investigações formalizadas."
        regra_aplicada = f"O **{art_num}** fixa o prazo máximo obrigatório para a abertura oficial do inquérito policial a contar do registo da ocorrência."
    else:
        situacao_real = "Diante de um caso prático no dia a dia policial ou jurídico envolvendo a aplicação desta norma."
        regra_aplicada = f"O **{art_num}** determina exatamente a conduta e os prazos que as autoridades devem respeitar."

    if foi_correto:
        status_txt = "O item está **CORRETO**."
        detalhe_erro = f"O enunciado reproduz com exatidão o disposto no **{art_num}**."
        resumo_erro_bloco = ""
    else:
        status_txt = "O item está **ERRADO**."
        detalhe_erro = f"A banca alterou a regra original do artigo."
        resumo_erro_bloco = f"\n• **Resumo do Erro da Questão:** A lei estabelece uma regra específica, porém a questão alterou o sentido original mediante **{tipo_troca or 'modificação de termos'}**."

    explicacao_formatada = f"""💡 **Explicação Direta:**
{status_txt} {detalhe_erro}

📌 **Exemplo Prático da Vida Real (Como funciona o {art_num}):**
Imagine a seguinte situação:

• **A Situação Concreta:** {situacao_real}
• **A Regra do {art_num}:** {regra_aplicada}{resumo_erro_bloco}

📜 **Texto Original da Lei:**
> "{texto_original}"
"""
    return explicacao_formatada

def generate_questions_for_articles(discipline_id, law_id, article_ids, qtd_total, filter_id=None, motor_ia="⚙️ Regra Padrão"):
    conn = db()
    if article_ids:
        placeholders = ",".join("?" * len(article_ids))
        arts = conn.execute(f"SELECT * FROM artigos WHERE id IN ({placeholders}) ORDER BY id", article_ids).fetchall()
    else:
        arts = conn.execute("SELECT * FROM artigos WHERE lei_id=? ORDER BY id", (law_id,)).fetchall()

    if not arts:
        conn.close()
        return 0

    generated = 0
    now = datetime.now().isoformat()
    
    artigos_pool = list(arts)
    random.shuffle(artigos_pool)

    for i in range(qtd_total):
        art = artigos_pool[i % len(artigos_pool)]
        text = limpar_e_formatar_texto_lei(art["texto"])
        is_correct = random.choice([True, False])

        if "Ollama" in motor_ia:
            import requests
            try:
                prompt = f"Crie uma questão Certo/Errado curta baseada neste trecho do {art['numero']}:\n{text}"
                res = requests.post("http://localhost:11434/api/generate", json={
                    "model": "llama3",
                    "prompt": prompt,
                    "stream": False
                }, timeout=3)
                data = res.json()
                enunciado = data.get("response", f"De acordo com a legislação:\n\n\"{text}\"")
                gabarito = 1 if is_correct else 0
                explicacao = gerar_explicacao_humana(art['numero'], text, is_correct)
            except Exception:
                if is_correct:
                    enunciado = f"De acordo com o {art['numero']}:\n\n\"{text}\""
                    gabarito = 1
                    explicacao = gerar_explicacao_humana(art['numero'], text, True)
                else:
                    modified_text, tipo_troca = alterar_texto_para_errado(text)
                    enunciado = f"De acordo com a legislação:\n\n\"{modified_text}\""
                    gabarito = 0
                    explicacao = gerar_explicacao_humana(art['numero'], text, False, tipo_troca, modified_text)

        elif "OpenAI" in motor_ia or "Gemini" in motor_ia:
            api_key = st.secrets.get("OPENAI_API_KEY", os.getenv("OPENAI_API_KEY"))
            if api_key and openai:
                try:
                    client = openai.OpenAI(api_key=api_key)
                    prompt_system = (
                        "Você é uma banca examinadora de concursos públicos. "
                        "Crie uma afirmação de Certo ou Errado focada estritamente no trecho da lei fornecido. "
                        "Mantenha o enunciado conciso e direto."
                    )
                    completion = client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[
                            {"role": "system", "content": prompt_system},
                            {"role": "user", "content": f"Artigo/Dispositivo: {art['numero']}\n{text}\n\nGabarito pretendido: {'CERTO' if is_correct else 'ERRADO'}"}
                        ]
                    )
                    enunciado = completion.choices[0].message.content
                    gabarito = 1 if is_correct else 0
                    explicacao = gerar_explicacao_humana(art['numero'], text, is_correct)
                except Exception:
                    if is_correct:
                        enunciado = f"De acordo com o {art['numero']}:\n\n\"{text}\""
                        gabarito = 1
                        explicacao = gerar_explicacao_humana(art['numero'], text, True)
                    else:
                        modified_text, tipo_troca = alterar_texto_para_errado(text)
                        enunciado = f"De acordo com a legislação:\n\n\"{modified_text}\""
                        gabarito = 0
                        explicacao = gerar_explicacao_humana(art['numero'], text, False, tipo_troca, modified_text)
            else:
                if is_correct:
                    enunciado = f"De acordo com o {art['numero']}:\n\n\"{text}\""
                    gabarito = 1
                    explicacao = gerar_explicacao_humana(art['numero'], text, True)
                else:
                    modified_text, tipo_troca = alterar_texto_para_errado(text)
                    enunciado = f"De acordo com a legislação:\n\n\"{modified_text}\""
                    gabarito = 0
                    explicacao = gerar_explicacao_humana(art['numero'], text, False, tipo_troca, modified_text)

        else:
            if is_correct:
                enunciado = f"De acordo com o {art['numero']}:\n\n\"{text}\""
                gabarito = 1
                explicacao = gerar_explicacao_humana(art['numero'], text, True)
            else:
                modified_text, tipo_troca = alterar_texto_para_errado(text)
                enunciado = f"De acordo com a legislação:\n\n\"{modified_text}\""
                gabarito = 0
                explicacao = gerar_explicacao_humana(art['numero'], text, False, tipo_troca, modified_text)

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
        next_date = now
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

st.title("⚖️ Decorando Lei Seca")

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
            st.success(f"Lei processada com sucesso! {qtd} dispositivos/trechos importados de forma fracionada.")

    st.divider()
    st.subheader("🗑️ Leis Cadastradas por Disciplina")
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
            
            st.info(f"💡 **Sugestão do Sistema:** Esta lei/seleção possui **{total_arts_selecionados} trecho(s) fracionado(s)**. Recomendamos gerar no mínimo **{sugestao_qtd} questões** para cobrir todos os pontos.")

            qtd_q = st.number_input(
                "4. Quantidade de questões para este filtro:",
                min_value=total_arts_selecionados if total_arts_selecionados > 0 else 1,
                max_value=500,
                value=sugestao_qtd
            )
            
            motor_ia = st.radio(
                "5. Selecione o Motor para Geração de Questões:",
                ["⚙️ Regra Padrão", "🦙 Ollama (Local)", "🤖 OpenAI / Gemini (Nuvem)"]
            )

            filter_name = st.text_input("6. Nome do seu Caderno / Filtro:")

            if st.button("Salvar Caderno e Gerar Questões"):
                if not filter_name:
                    st.error("Informe um nome para o seu caderno!")
                else:
                    art_ids = [art_dict[k] for k in selected_arts]
                    f_id = save_filter(filter_name, d_id, l_id, art_ids, qtd_q)
                    qtd_geradas = generate_questions_for_articles(d_id, l_id, art_ids, qtd_q, filter_id=f_id, motor_ia=motor_ia)
                    st.success(f"Caderno '{filter_name}' criado com sucesso! {qtd_geradas} questões geradas de forma fracionada.")

    st.divider()
    st.subheader("🗑️ Meus Cadernos / Filtros Salvos por Disciplina")
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
                st.markdown(f"**Dispositivo:** {q['artigo_numero']}")
                st.markdown(q["enunciado"])

                resp = st.radio("Sua resposta:", ["Certo", "Errado"], key=f"q_{q['id']}")
                
                if st.button("Responder", key=f"btn_{q['id']}"):
                    val = 1 if resp == "Certo" else 0
                    acertou = record_answer(q["id"], val, cycle=1)
                    if acertou:
                        st.success("✨ Resposta Correta!")
                    else:
                        st.error("❌ Resposta Incorreta!")
                    st.markdown(f"**Gabarito / Explicação Prática:**\n\n{q['explicacao']}")

                if st.button("Próxima Questão ➡️"):
                    st.session_state["q_index"] += 1
                    st.rerun()

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
    st.subheader("⚠ Redefinir Estatísticas")
    if st.button("Zerar Histórico de Respostas / Limpar Dashboard", type="secondary"):
        zerar_historico_dashboard()
        st.success("Seu histórico de respostas e indicadores do dashboard foram zerados!")
        st.rerun()

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
            st.markdown(revs["enunciado"])
            resp_rev = st.radio("Sua resposta:", ["Certo", "Errado"], key="rev_ans")
            if st.button("Enviar Resposta da Revisão"):
                val = 1 if resp_rev == "Certo" else 0
                acertou = record_answer(revs["id"], val, cycle=2)
                if acertou:
                    st.success("✨ Excelente! Próxima revisão agendada.")
                else:
                    st.error("❌ Errou! Ela voltará para revisão.")
                st.markdown(f"**Gabarito / Explicação:**\n\n{revs['explicacao']}")
    else:
        st.success("Tudo em dia! Não há revisões pendentes para hoje.")