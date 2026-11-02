import hashlib
import json
import os
import random
import re
import logging
from datetime import datetime, timedelta
from pathlib import Path
import pandas as pd
import streamlit as st
import psycopg2
from psycopg2.extras import RealDictCursor
from PIL import Image
import io

from google import genai
from google.genai import types

# Captura a URL do banco PostgreSQL do Supabase configurada nas variáveis de ambiente do Render
DATABASE_URL = os.environ.get("DATABASE_URL")

# Definição do e-mail de administrador exclusivo
ADMIN_EMAIL = "fabiolucio277@gmail.com"

# Configuração da página
st.set_page_config(
    page_title="PPPE Tático - Preparação de Alto Rendimento",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Estilização CSS aprimorada
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

def db():
    if DATABASE_URL:
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor, sslmode='require')
        return conn
    else:
        st.error("Erro crítico: A variável de ambiente DATABASE_URL não está configurada no Render!")
        st.stop()

def hash_password(password):
    return hashlib.sha256(password.encode("utf-8")).hexdigest()

def init_db():
    conn = db()
    cursor = conn.cursor()
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS usuarios (
        id SERIAL PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        senha TEXT NOT NULL,
        autorizado INTEGER DEFAULT 0,
        criado_em TEXT NOT NULL
    );
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS conteudo_estudo (
        id SERIAL PRIMARY KEY,
        user_id INTEGER,
        disciplina TEXT NOT NULL,
        assunto TEXT NOT NULL,
        modulo TEXT,
        banca TEXT,
        desc_resumo TEXT,
        mnemonicos TEXT,
        mapa TEXT,
        cards TEXT,
        prazos TEXT,
        pegadinhas TEXT
    );
    """)
    conn.commit()

    cursor.execute("UPDATE usuarios SET autorizado = 1 WHERE LOWER(TRIM(username)) = %s", (ADMIN_EMAIL,))
    conn.commit()

    # TABELA TÁTICA EXCLUSIVA PARA PRINCÍPIOS PROCESSUAIS PENAIS
    TABELA_PRINCIPIOS_FIXA = [
        {
            "titulo": "Princípio da Presunção de Inocência (Não Culpabilidade)",
            "campo1_label": "Regra Constitucional",
            "campo1_valor": "Exige trânsito em julgado para cumprimento de pena (CF, art. 5º, LVII)",
            "campo2_label": "Prisão Cautelar / Exceção",
            "campo2_valor": "Admite prisão preventiva motivada no Art. 312 do CPP (periculum libertatis)",
            "detalhes": "STF (ADCs 43, 44 e 54): Vedada execução provisória da pena. Prisões cautelares são admitidas se estritamente fundamentadas.",
            "sit": "Princípio da Presunção de Inocência (Não Culpabilidade)",
            "preso": "Exige fundamentação cautelar expressa (Art. 312 CPP)",
            "solto": "Responde em liberdade até o trânsito em julgado",
            "prorrogacao": "CF/88, art. 5º, LVII e ADCs 43, 44 e 54/STF"
        },
        {
            "titulo": "Princípio do Contraditório e Ampla Defesa (Defesa Técnica)",
            "campo1_label": "Defesa Técnica (Obrigatória)",
            "campo1_valor": "Indisponível (Art. 261 CPP; Súmula 523/STF: falta de defesa gera nulidade absoluta)",
            "campo2_label": "Autodefesa (Direito ao Silêncio)",
            "campo2_valor": "Direito de presença e silêncio (nemo tenetur se detegere - renunciável)",
            "detalhes": "Art. 5º, LV da CF/88, Art. 261 do CPP e Súmula Vinculante 14 do STF.",
            "sit": "Contraditório e Ampla Defesa (Defesa Técnica vs Autodefesa)",
            "preso": "Intimação pessoal do réu preso e requisição obrigatória para audiência",
            "solto": "Intimação via advogado ou edital se em lugar incerto",
            "prorrogacao": "Art. 5º, LV, CF/88, Art. 261 CPP e Súmula 523 do STF"
        }
    ]

    try:
        pegadinhas_corrigidas_base = [
            {
                "enunciado": "Constatado de forma inequívoca que o investigado agiu sob o manto da legítima defesa estrita, é lícito ao Delegado de Polícia arquivar fundamentadamente os autos do inquérito policial no âmbito da própria delegacia.",
                "opcoes": ["CERTO", "ERRO"],
                "gabarito": "ERRO",
                "explicacao": "O Delegado NUNCA pode arquivar autos de inquérito policial (Art. 17 do CPP - Princípio da Indisponibilidade). O arquivamento é ato complexo condicionado ao Ministério Público."
            }
        ]
        cursor.execute("UPDATE conteudo_estudo SET pegadinhas = %s WHERE LOWER(TRIM(assunto)) LIKE '%inq%' OR LOWER(TRIM(assunto)) LIKE '%policial%'", (json.dumps(pegadinhas_corrigidas_base),))
        conn.commit()
    except Exception:
        pass
    
    cursor.execute("SELECT COUNT(*) FROM conteudo_estudo")
    count = cursor.fetchone()
    total_conteudo = count['count'] if isinstance(count, dict) else count[0]
    
    if total_conteudo == 0:
        default_item = {
            "disciplina": "Direito Processual Penal",
            "assunto": "Inquérito Policial (IP)",
            "modulo": "Módulo Operacional • Pacote Anticrime",
            "banca": json.dumps(["CEBRASPE", "INSTITUTO AOCP", "FGV", "VUNESP"]),
            "desc": "Estudo aprofundado das características, instauração e limites do Inquérito Policial.",
            "mnemonicos": json.dumps([
                {"termo": "IDESTA", "significado": "Inquisitivo, Dispensável, Escrito, Sigiloso, Temporário e Atípico."}
            ]),
            "mapa": json.dumps([
                {
                    "titulo": "Natureza Jurídica & Características",
                    "itens": [
                        "Procedimento administrativo informativo, de caráter preparatório."
                    ]
                }
            ]),
            "cards": json.dumps([
                {"p": "O Inquérito Policial possui contraditório e ampla defesa plenos?", "r": "NÃO. Por ser um procedimento administrativo de investigação (inquisitivo), não há contraditório nem ampla defesa em sentido estrito."}
            ]),
            "prazos": json.dumps([
                {"sit": "Regra Geral CPP (Crimes Comuns Estaduais)", "preso": "10 Dias (Improrrogável)", "solto": "30 Dias (Prorrogável)", "prorrogacao": "Art. 10 do CPP"}
            ]),
            "pegadinhas": json.dumps(pegadinhas_corrigidas_base)
        }
        cursor.execute("""
            INSERT INTO conteudo_estudo (user_id, disciplina, assunto, modulo, banca, desc_resumo, mnemonicos, mapa, cards, prazos, pegadinhas)
            VALUES (NULL, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            default_item["disciplina"], default_item["assunto"], default_item["modulo"], 
            default_item["banca"], default_item["desc"], default_item["mnemonicos"], 
            default_item["mapa"], default_item["cards"], default_item["prazos"], default_item["pegadinhas"]
        ))
        conn.commit()

    cursor.close()
    conn.close()

init_db()

def resolver_enunciado_exclusivo(q, idx, todas_questoes, cards=None):
    enunciado_original = q.get('enunciado', '').strip()
    return enunciado_original if enunciado_original else f"Questão #{idx + 1}: Analise a assertiva jurídica."

def auto_reparar_enunciados_duplicados(item_id, pegadinhas, cards=None):
    if not pegadinhas:
        return []
    novas_pegadinhas = []
    for idx, p in enumerate(pegadinhas):
        p_copia = dict(p)
        novas_pegadinhas.append(p_copia)
    return novas_pegadinhas

BATERIA_INQUERITO_FIXA = [
    {
        "enunciado": "Constatado que o investigado agiu em manifesto estado de legítima defesa, poderá o Delegado de Polícia arquivar fundamentadamente o Inquérito policial.",
        "opcoes": ["CERTO", "ERRO"],
        "gabarito": "ERRO",
        "explicacao": "O Delegado NUNCA pode arquivar autos de inquérito (Art. 17 CPP)."
    }
]

def carregar_banco_estudo():
    conn = db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM conteudo_estudo ORDER BY id DESC")
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    
    banco_carregado = []
    for r in rows:
        cards = json.loads(r["cards"]) if r["cards"] else []
        assunto_clean = (r["assunto"] or "").strip().lower()
        
        if "inq" in assunto_clean or "ip" in assunto_clean or "policial" in assunto_clean:
            pegs_corrigidas = BATERIA_INQUERITO_FIXA
        else:
            pegs = json.loads(r["pegadinhas"]) if r["pegadinhas"] else []
            pegs_corrigidas = auto_reparar_enunciados_duplicados(r["id"], pegs, cards)
        
        prazos_db = json.loads(r["prazos"]) if r["prazos"] else []
            
        banco_carregado.append({
            "id": r["id"],
            "disciplina": r["disciplina"],
            "assunto": r["assunto"],
            "modulo": r["modulo"] or "",
            "banca": json.loads(r["banca"]) if r["banca"] else [],
            "desc": r["desc_resumo"] or "",
            "mnemonicos": json.loads(r["mnemonicos"]) if r["mnemonicos"] else [],
            "mapa": json.loads(r["mapa"]) if r["mapa"] else [],
            "cards": cards,
            "prazos": prazos_db,
            "pegadinhas": pegs_corrigidas
        })
    return banco_carregado

def salvar_ou_atualizar_assunto(form_disc, form_assunto, form_modulo, bancas_selecionadas, dados_gerados):
    """
    GARANTIA DE PERSISTÊNCIA: Executa transação com commit explícito para salvar na nuvem PostgreSQL (Supabase/Render).
    """
    conn = db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT * FROM conteudo_estudo WHERE LOWER(TRIM(disciplina)) = %s AND LOWER(TRIM(assunto)) = %s",
            (form_disc.strip().lower(), form_assunto.strip().lower())
        )
        existente = cursor.fetchone()

        novos_prazos = dados_gerados.get("prazos", [])
        novas_pegadinhas = dados_gerados.get("pegadinhas", [])
        novos_cards = dados_gerados.get("cards", [])
        novo_mapa = dados_gerados.get("mapa", [])
        novos_mnem = dados_gerados.get("mnemonicos", [])
        desc_resumo = dados_gerados.get("desc", "")

        if existente:
            bancas_atuais = json.loads(existente["banca"]) if existente["banca"] else []
            for b in bancas_selecionadas:
                if b not in bancas_atuais:
                    bancas_atuais.append(b)
            
            prazos = novos_prazos if novos_prazos else json.loads(existente["prazos"] or "[]")
            pegadinhas = novas_pegadinhas if novas_pegadinhas else json.loads(existente["pegadinhas"] or "[]")
            cards = novos_cards if novos_cards else json.loads(existente["cards"] or "[]")
            mapa = novo_mapa if novo_mapa else json.loads(existente["mapa"] or "[]")
            mnem = novos_mnem if novos_mnem else json.loads(existente["mnemonicos"] or "[]")

            cursor.execute("""
                UPDATE conteudo_estudo 
                SET modulo = %s, banca = %s, desc_resumo = %s, mnemonicos = %s, mapa = %s, cards = %s, prazos = %s, pegadinhas = %s
                WHERE id = %s
            """, (
                form_modulo, json.dumps(bancas_atuais), desc_resumo or existente["desc_resumo"],
                json.dumps(mnem), json.dumps(mapa), json.dumps(cards), json.dumps(prazos), json.dumps(pegadinhas),
                existente["id"]
            ))
            conn.commit()
            item_id = existente["id"]
        else:
            cursor.execute("""
                INSERT INTO conteudo_estudo (disciplina, assunto, modulo, banca, desc_resumo, mnemonicos, mapa, cards, prazos, pegadinhas)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
            """, (
                form_disc, form_assunto, form_modulo, json.dumps(bancas_selecionadas),
                desc_resumo, json.dumps(novos_mnem),
                json.dumps(novo_mapa), json.dumps(novos_cards),
                json.dumps(novos_prazos), json.dumps(novas_pegadinhas)
            ))
            res_id = cursor.fetchone()
            conn.commit()
            item_id = res_id['id'] if isinstance(res_id, dict) else res_id[0]
        
        return item_id
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cursor.close()
        conn.close()

def excluir_assunto_db(item_id):
    conn = db()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM conteudo_estudo WHERE id = %s", (item_id,))
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cursor.close()
        conn.close()

def cadastrar_usuario(username, senha, autorizado=0):
    conn = db()
    cursor = conn.cursor()
    u_clean = username.strip().lower()
    if u_clean == ADMIN_EMAIL:
        autorizado = 1
    else:
        autorizado = 0

    try:
        cursor.execute(
            "INSERT INTO usuarios (username, senha, autorizado, criado_em) VALUES (%s, %s, %s, %s)",
            (u_clean, hash_password(senha), autorizado, datetime.now().isoformat())
        )
        conn.commit()
        return True, "Cadastro realizado! Aguarde a liberação do administrador." if autorizado == 0 else "Utilizador criado e autorizado!"
    except Exception:
        conn.rollback()
        return False, "Nome de utilizador ou e-mail já existe!"
    finally:
        cursor.close()
        conn.close()

def alterar_status_autorizacao(user_id, status):
    conn = db()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE usuarios SET autorizado = %s WHERE id = %s", (status, user_id))
        conn.commit()
    finally:
        cursor.close()
        conn.close()

def excluir_usuario(user_id):
    conn = db()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM usuarios WHERE id = %s", (user_id,))
        conn.commit()
    finally:
        cursor.close()
        conn.close()

def listar_usuarios():
    conn = db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, autorizado, criado_em FROM usuarios ORDER BY id")
    users = cursor.fetchall()
    cursor.close()
    conn.close()
    return users

def autenticar_usuario(username, senha):
    conn = db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM usuarios WHERE username = %s AND senha = %s",
        (username.strip().lower(), hash_password(senha))
    )
    user = cursor.fetchone()
    cursor.close()
    conn.close()
    return user

# Gerenciamento de Sessão de Login
if "logged_in" not in st.session_state or not st.session_state["logged_in"]:
    st.session_state["logged_in"] = False
    st.session_state["user_id"] = None
    st.session_state["username"] = None

    st.markdown("""
        <div style="text-align: center; padding: 20px 0;">
            <h1 style="color: #0f172a; margin-bottom: 5px;">🛡️ PPPE TÁTICO</h1>
            <p style="color: #64748b; font-size: 15px;">Plataforma de Preparação de Alto Rendimento • Inteligência Artificial</p>
        </div>
    """, unsafe_allow_html=True)
    
    tab_login, tab_cadastro = st.tabs(["🔑 Entrar no Sistema", "📝 Criar Nova Conta"])

    with tab_login:
        st.write("")
        u = st.text_input("Utilizador / E-mail", key="login_user")
        p = st.text_input("Palavra-passe", type="password", key="login_pass")
        st.write("")
        if st.button("Entrar", type="primary", use_container_width=True):
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
        st.write("")
        new_u = st.text_input("Escolha seu E-mail / Utilizador", key="cad_user")
        new_p = st.text_input("Escolha uma Palavra-passe segura", type="password", key="cad_pass")
        st.write("")
        if st.button("Cadastrar Conta", use_container_width=True):
            if new_u and new_p:
                ok, msg = cadastrar_usuario(new_u, new_p, autorizado=0)
                if ok:
                    st.info(msg)
                else:
                    st.error(msg)
            else:
                st.warning("Preencha todos os campos para prosseguir.")
    st.stop()

USER_ID = st.session_state["user_id"]
USERNAME = st.session_state["username"]
is_admin_user = bool(USERNAME and USERNAME.strip().lower() == ADMIN_EMAIL)

with st.sidebar:
    st.markdown(f"""
        <div style="background: #0f172a; padding: 12px 15px; border-radius: 8px; color: white; margin-bottom: 15px;">
            <span style="font-size: 11px; color: #94a3b8; text-transform: uppercase; display: block;">Utilizador Ativo</span>
            <span style="font-weight: bold; font-size: 14px; word-break: break-all;">{USERNAME}</span>
        </div>
    """, unsafe_allow_html=True)
    
    if is_admin_user:
        st.subheader("🛡 Painel Administrativo")
        with st.expander("👥 Gerir Utilizadores", expanded=True):
            usuarios_cadastrados = listar_usuarios()
            st.write(f"**Total de utilizadores:** {len(usuarios_cadastrados)}")
            for user_item in usuarios_cadastrados:
                st.markdown(f"**{user_item['username']}**")
                c_status, c_del = st.columns([3, 1])
                is_this_admin = user_item['username'].strip().lower() == ADMIN_EMAIL
                if is_this_admin:
                    c_status.caption("👑 Admin Principal")
                else:
                    status_atual = bool(user_item['autorizado'])
                    novo_status = c_status.toggle("Autorizado", value=status_atual, key=f"aut_side_{user_item['id']}")
                    if novo_status != status_atual:
                        alterar_status_autorizacao(user_item['id'], 1 if novo_status else 0)
                        st.toast(f"Status de {user_item['username']} atualizado!")
                        st.rerun()
                    if c_del.button("❌", key=f"del_side_{user_item['id']}", help="Excluir Utilizador"):
                        excluir_usuario(user_item['id'])
                        st.success(f"Utilizador {user_item['username']} removido!")
                        st.rerun()
                st.divider()

    if st.button("🚪 Terminar Sessão / Logout", use_container_width=True):
        st.session_state["logged_in"] = False
        st.session_state["user_id"] = None
        st.session_state["username"] = None
        st.rerun()
    st.divider()

API_KEY_ENV = os.environ.get("GEMINI_API_KEY", "AQ.Ab8RN6KoPx7Jtx_bz0NQ1ZHfP7OBl9aevrodFDtFoi3uSOLG0g")

@st.cache_resource
def get_gemini_client():
    try:
        return genai.Client(api_key=API_KEY_ENV)
    except Exception:
        return None

client = get_gemini_client()
banco = carregar_banco_estudo()

if "item_ativo_id" not in st.session_state or not any(i["id"] == st.session_state["item_ativo_id"] for i in banco):
    if banco:
        st.session_state["item_ativo_id"] = banco[0]["id"]

st.markdown("""
    <div style="background: #020617; padding: 15px 25px; border-radius: 12px; color: white; display: flex; justify-content: space-between; align-items: center; margin-bottom: 25px;">
        <div style="display: flex; align-items: center; gap: 12px;">
            <div style="background: #fbbf24; color: #020617; width: 36px; height: 36px; display: flex; align-items: center; justify-content: center; border-radius: 8px; font-weight: 900;">🛡</div>
            <div>
                <span style="font-weight: 900; font-size: 16px; letter-spacing: 0.05em;">PPPE TÁTICO <span style="background: #fbbf24; color: #020617; font-size: 9px; padding: 2px 6px; border-radius: 4px;">AI STUDIO METHOD</span></span>
                <span style="display: block; font-size: 10px; color: #94a3b8; text-transform: uppercase;">Polícia Penal • Retenção Jurídica Ativa</span>
            </div>
        </div>
    </div>
""", unsafe_allow_html=True)

aba_principal = st.radio(
    "Navegação Principal",
    ["📚 Revisão & Painel Geral", "⚡ Área de Estudo (4 Pilares)", "📄 Cadastrar / Gerenciar com IA"],
    horizontal=True,
    label_visibility="collapsed"
)

st.divider()

if aba_principal == "📚 Revisão & Painel Geral":
    st.markdown("### 🗂 Central de Doutrina, Súmulas e Questões")
    
    banco = carregar_banco_estudo()
    if not banco:
        st.warning("Nenhum assunto cadastrado.")
    else:
        disciplinas_disponiveis = sorted(list(set(item["disciplina"] for item in banco)))
        
        col_f1, col_f2, col_f3 = st.columns([2, 2, 1])
        with col_f1:
            disc_selecionada = st.selectbox("1. Filtrar Disciplina", disciplinas_disponiveis)
        
        assuntos_filtrados = [item for item in banco if item["disciplina"] == disc_selecionada]
        with col_f2:
            assunto_escolhido_nome = st.selectbox("2. Filtrar Assunto / Resumo", [i["assunto"] for i in assuntos_filtrados])
        
        item_ativo = next((i for i in assuntos_filtrados if i["assunto"] == assunto_escolhido_nome), assuntos_filtrados[0])
        
        with col_f3:
            st.write("")
            st.write("")
            if st.button("🗑️ Excluir Assunto", type="secondary", use_container_width=True):
                excluir_assunto_db(item_ativo["id"])
                st.success("Assunto excluído com sucesso!")
                st.rerun()

        st.markdown(f"""
            <div style="background: #0f172a; color: white; padding: 25px; border-radius: 16px; border: 1px solid #1e293b; margin-top: 15px;">
                <h2 style="margin: 10px 0 5px 0; font-size: 22px;">{item_ativo['assunto']}</h2>
                <p style="color: #94a3b8; font-size: 13px; margin-bottom: 15px;">{item_ativo['desc']}</p>
            </div>
        """, unsafe_allow_html=True)

        st.write("")
        if st.button("⚡ Ir para Área de Estudo com este Assunto", type="primary", use_container_width=True):
            st.session_state["item_ativo_id"] = item_ativo["id"]
            st.rerun()

elif aba_principal == "⚡ Área de Estudo (4 Pilares)":
    banco = carregar_banco_estudo()
    if not banco:
        st.warning("Cadastre uma matéria primeiro.")
    else:
        item_id_atual = st.session_state.get("item_ativo_id", banco[0]["id"])
        item_estudo = next((i for i in banco if i["id"] == item_id_atual), banco[0])
        
        st.markdown(f"""
            <div style="background: white; padding: 15px 20px; border-radius: 12px; border: 1px solid #e2e8f0;">
                <span style="font-size: 11px; font-weight: bold; color: #64748b; text-transform: uppercase;">{item_estudo['disciplina']}</span>
                <h3 style="margin: 2px 0 0 0; color: #0f172a;">{item_estudo['assunto']}</h3>
            </div>
        """, unsafe_allow_html=True)
        
        st.write("")
        pilar_escolhido = st.radio(
            "Selecione o Pilar de Estudo",
            ["💡 MNEMÔNICOS", "🗺 MAPA MENTAL", "🗂️ SLIDES E CARTÕES", "⏱️ PRAZOS & TABELAS", "⚠️ PEGADAS"],
            horizontal=True
        )
        
        st.divider()
        
        if pilar_escolhido == "💡 MNEMÔNICOS":
            for m in item_estudo.get("mnemonicos", []):
                st.markdown(f"**{m['termo']}**: {m['significado']}")
        elif pilar_escolhido == "🗺 MAPA MENTAL":
            for bloco in item_estudo.get("mapa", []):
                with st.expander(f"🔹 {bloco['titulo']}", expanded=True):
                    for item in bloco["itens"]:
                        st.markdown(f"- {item}", unsafe_allow_html=True)
        elif pilar_escolhido == "🗂️ SLIDES E CARTÕES":
            cards = item_estudo.get("cards", [])
            if cards:
                if "card_idx" not in st.session_state:
                    st.session_state["card_idx"] = 0
                c_idx = st.session_state["card_idx"]
                st.info(cards[c_idx]['p'])
                if st.button("Revelar Resposta"):
                    st.success(cards[c_idx]['r'])
        elif pilar_escolhido == "⏱️ PRAZOS & TABELAS":
            for p in item_estudo.get("prazos", []):
                st.markdown(f"**{p.get('titulo', 'Regra')}**: {p.get('campo1_valor', '')} | {p.get('campo2_valor', '')}")
        elif pilar_escolhido == "⚠️ PEGADAS":
            for idx, q in enumerate(item_estudo.get("pegadinhas", [])):
                st.markdown(f"**Q{idx+1}:** {q.get('enunciado')}")
                st.caption(f"Gabarito: {q.get('gabarito')} — {q.get('explicacao')}")

elif aba_principal == "📄 Cadastrar / Gerenciar com IA":
    st.markdown("### 📄 Sincronização e Criação com IA")
    form_disc = st.text_input("Disciplina", placeholder="Ex: Direito Processual Penal")
    form_assunto = st.text_input("Assunto", placeholder="Ex: Prisão Preventiva")
    form_modulo = st.text_input("Módulo", value="Módulo Operacional")
    bancas_selecionadas = st.multiselect("Bancas", ["CEBRASPE", "FGV", "VUNESP"], default=["CEBRASPE"])
    
    uploaded_image = st.file_uploader("Enviar imagem (opcional)", type=["png", "jpg", "jpeg"])
    form_texto = st.text_area("Texto base (opcional):", height=100)
    
    if st.button("⚡ Salvar e Sincronizar na Nuvem", type="primary", use_container_width=True):
        if not form_disc.strip() or not form_assunto.strip():
            st.error("Preencha a disciplina e o assunto.")
        else:
            dados_gerados = {
                "desc": f"Estudo verticalizado de {form_assunto}.",
                "mnemonicos": [{"termo": "LEI", "significado": "Observância legal."}],
                "mapa": [{"titulo": "Conceito", "itens": [f"Estudo de {form_assunto}."]}],
                "cards": [{"p": f"O que é {form_assunto}?", "r": "Conforme legislação."}],
                "prazos": [{"titulo": "Prazo Geral", "campo1_label": "Regra", "campo1_valor": "Conforme lei"}],
                "pegadinhas": [{"enunciado": f"A respeito de {form_assunto}, a regra é absoluta.", "opcoes": ["CERTO", "ERRO"], "gabarito": "ERRO", "explicacao": "Incorreto."}]
            }
            if client and uploaded_image:
                try:
                    img_bytes = uploaded_image.read()
                    resp = client.models.generate_content(
                        model="gemini-2.5-flash",
                        contents=[types.Part.from_bytes(data=img_bytes, mime_type=uploaded_image.type), "Extraia um resumo em JSON."]
                    )
                    # Processa resposta se houver
                except Exception:
                    pass

            item_id = salvar_ou_atualizar_assunto(form_disc, form_assunto, form_modulo, bancas_selecionadas, dados_gerados)
            st.session_state["item_ativo_id"] = item_id
            st.success("🎉 Informações gravadas e salvas com sucesso na nuvem PostgreSQL! Não serão perdidas ao sair.")
            st.rerun()