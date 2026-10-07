# 🚀 Guia de Execução no VSCode e Deploy no Render

Este projeto é o **Decorando Lei Seca**, contendo:
1. **Aplicação Python / Streamlit (`app.py`)**: com fragmentação inteligente de artigos extensos (todos os incisos em algarismos romanos até LXXIX+), nexo lógico de bancas (Cebraspe/OAB) com o caput, ausência de código HTML exposto nos cartões, e exemplos objetivos da vida real gerados por IA ou motor jurídico integrado.
2. **Aplicação Web / React (`src/` e `server.ts`)**: interface SPA moderna com simulador, dashboards e resolvedor de questões.

---

## 💻 1. Como rodar no seu VSCode (Passo a Passo)

### Pré-requisitos
- Ter o **Python 3.10 ou superior** instalado.
- Ter o **VSCode** com a extensão Python instalada.

### Passo 1: Abrir a pasta no VSCode
1. Abra o VSCode.
2. Vá em `File` > `Open Folder...` (ou `Arquivo` > `Abrir Pasta...`).
3. Selecione a pasta do projeto.

### Passo 2: Criar e ativar o ambiente virtual (Recomendado)
Abra o Terminal no VSCode (`Ctrl + '` ou `Terminal` > `Novo Terminal`):

**No Windows (PowerShell):**
```bash
python -m venv venv
.\venv\Scripts\Activate.ps1
```
*(Se o PowerShell bloquear scripts, use no prompt: `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` ou use o Git Bash).*

**No Linux ou Mac:**
```bash
python3 -m venv venv
source venv/bin/activate
```

### Passo 3: Instalar as dependências
Com o terminal aberto na pasta do projeto, execute:
```powershell
python -m pip install -r requirements.txt
```
*(Nota: Seus pacotes como Streamlit, Pandas, PyMuPDF e google-genai já estão todos instalados no seu computador!)*

### Passo 4: Rodar o aplicativo Streamlit (Solução para o erro CommandNotFoundException)
No Windows PowerShell, o comando direto `streamlit run app.py` costuma dar erro de `CommandNotFoundException` porque o executável do Streamlit fica na pasta de usuário (`AppData\Roaming\Python\Python314\Scripts`) e não está adicionado no PATH do Windows.

👉 **Execute este comando que NUNCA falha:**
```powershell
python -m streamlit run app.py
```
*(ou se você usa o inicializador rápido py do Windows: `py -m streamlit run app.py`)*

Ou simplesmente execute o arquivo que criamos:
```powershell
.\iniciar.bat
```
O Streamlit abrirá automaticamente no seu navegador no endereço:
👉 `http://localhost:8501`

---

### ⚠️ Como resolver o aviso "Defaulting to user installation" e "CommandNotFoundException"
1. **O que é**: O Python no Windows (especialmente versão 3.14) instala os pacotes no diretório de usuário `AppData\Roaming\Python\Python314\site-packages`. Seus pacotes estão 100% instalados e funcionando perfeitamente!
2. **A solução**: Sempre que quiser rodar qualquer comando do Streamlit no terminal do VSCode ou PowerShell, use o prefixo `python -m`:
   - Em vez de: `streamlit run app.py` (que o PowerShell não encontra)
   - Use: `python -m streamlit run app.py` (que o Python acha na hora)
3. **Atenção sobre o Render**: O comando com `--server.port $PORT --server.address 0.0.0.0` é **exclusivo para os servidores do Render (Linux)**. No seu VSCode do Windows, use apenas `python -m streamlit run app.py`!

---

## ☁️ 2. Como subir e rodar no Render (Render.com)

O Render é gratuito e excelente para hospedar sua aplicação.

### Método Rápido (Render Blueprint - Automático)
O repositório já conta com o arquivo `render.yaml`.
1. Suba seu projeto para o seu GitHub (veja a seção 3 abaixo).
2. Acesse [render.com](https://render.com) e conecte sua conta do GitHub.
3. No painel do Render, clique em **Blueprints** > **New Blueprint Instance**.
4. Selecione o seu repositório. O Render detectará automaticamente o arquivo `render.yaml` e configurará tudo sozinho!

---

### Método Manual (Web Service)
Se preferir criar manualmente:
1. No painel do Render, clique em **New +** e escolha **Web Service**.
2. Conecte o repositório do seu GitHub.
3. Preencha as configurações:
   - **Name**: `decorando-lei-seca`
   - **Language**: `Python`
   - **Branch**: `main` (ou a branch principal)
   - **Region**: `Oregon (US West)` ou a mais próxima.
   - **Build Command**:
     ```bash
     pip install -r requirements.txt
     ```
   - **Start Command**:
     ```bash
     streamlit run app.py --server.port $PORT --server.address 0.0.0.0 --server.headless true
     ```
4. **Variáveis de Ambiente (Environment Variables)**:
   - Adicione `PYTHON_VERSION`: `3.11.9`
   - *(Opcional)* Adicione `GEMINI_API_KEY`: sua chave de API do Google AI Studio para IA ativa.
5. Clique em **Create Web Service**.
6. Aguarde o build (2 a 3 minutos). O Render gerará uma URL pública (ex: `https://decorando-lei-seca.onrender.com`).

---

## 🐙 3. Como subir seus arquivos do VSCode para o GitHub

Se ainda não enviou os arquivos para o seu repositório:
1. No terminal do VSCode na pasta do projeto:
```bash
git init
git add .
git commit -m "Versao atualizada Decorando Lei Seca com correcao de HTML e deploy no Render"
git branch -M main
git remote add origin https://github.com/SEU_USUARIO/SEU_REPOSITORIO.git
git push -u origin main --force
```

---

## 🛡️ 5. Como NÃO PERDER Leis, Cadernos de Questões e Dados no Render

### Por que os dados podem sumir no Render Free?
No plano gratuito do Render (Web Service), os servidores utilizam **disco efêmero (volátil)**. Isso significa que sempre que o Render reinicia a aplicação (a cada 15 min de inatividade ou após um novo `git push`), o disco volta ao estado original do seu repositório Git. Arquivos criados em tempo de execução (como o banco `decorando_lei.db` e PDFs na pasta `leis_importadas/`) seriam apagados.

Para resolver isso de forma definitiva, você tem **3 soluções práticas** (escolha a que preferir):

---

### 🌟 Opção 1 (100% Gratuita e Direta no App): Backup & Restauração com 1 Clique
Implementamos no painel de controle do aplicativo um módulo dedicado a backups:
1. No seu app (seja no VSCode ou no Render), entre com a sua conta de administrador (`fabiolucio277@gmail.com`).
2. Acesse a aba **"🛡 Painel Admin"**.
3. Na seção **"💾 Backup e Persistência de Dados"**:
   - Clique em **"📥 Baixar Banco de Dados Completo (.db)"** para salvar uma cópia exata de todos os seus cadernos, questões, leis e filtros.
   - Clique em **"📦 Baixar PDFs Importados (.zip)"** para baixar seus PDFs originais.
4. **Para restaurar no Render a qualquer momento:**
   - Basta abrir a mesma aba no Render e selecionar o arquivo `decorando_lei.db` no campo **"Restaurar Banco de Dados"**.
   - Em 2 segundos todo o seu acervo volta exatamente como estava!

---

### 🚀 Opção 2 (100% Gratuita e Automática pelo Git): Salvar o Banco no Repositório
Se você alimenta as leis e cadernos no seu computador localmente (no VS Code):
1. Importe suas leis e crie seus cadernos normalmente no VSCode pelo navegador (`localhost:8501`).
2. Quando terminar, abra o terminal do VSCode e faça o commit do arquivo `.db`:
   ```bash
   git add decorando_lei.db leis_importadas/
   git commit -m "Salva leis importadas e cadernos criados"
   git push origin main
   ```
3. O Render vai puxar o arquivo `decorando_lei.db` diretamente do GitHub. Toda vez que o Render iniciar, suas leis e cadernos já estarão lá embutidos!

---

### 💎 Opção 3 (A Mais Profissional na Nuvem): Adicionar um Disco Persistente no Render (Persistent Disk)
O Render permite plugar um "HD virtual permanente" ao seu Web Service. Esse disco **nunca é apagado**, resiste a reinicializações, novos deploys e quedas de servidor.
O código do aplicativo já foi programado para detectar automaticamente o disco persistente em `/var/data`!

**Como configurar no Render:**
1. No painel do [dashboard.render.com](https://dashboard.render.com), clique no seu serviço Web (`decorando-lei-seca`).
2. No menu lateral esquerdo, clique em **Disks**.
3. Clique no botão **Add Disk** (ou crie um novo disco):
   - **Name**: `decorando-data`
   - **Mount Path**: `/var/data`
   - **Size**: `1 GB` (ou conforme preferir)
4. Em **Environment Variables** (Variáveis de Ambiente), confira se a variável `DATA_DIR` está com o valor:
   - `DATA_DIR`: `/var/data`
5. Salve as alterações. O Render reiniciará o serviço conectado a esse disco.
6. Pronto! A partir desse momento, qualquer lei importada, PDF enviado ou caderno gerado será salvo no disco permanente `/var/data` e **nunca mais será perdido**.

---

## ☁️ 6. Passo a Passo Completo: Sincronizar o Render com o Supabase (100% Grátis e Automático)

O **Supabase** é uma plataforma em nuvem que oferece armazenamento de arquivos (Storage) e banco de dados PostgreSQL **100% gratuito**, sem expirar e sem apagar dados.

Com a integração que desenvolvemos no `app.py`, o Render envia automaticamente seu banco de dados (`decorando_lei.db`) e todos os seus arquivos PDFs para o Supabase. **Toda vez que o Render religar, ele baixa e restaura tudo da nuvem instantaneamente!**

Siga este passo a passo simples:

### 📍 Passo 1: Criar a Conta e o Projeto no Supabase
1. Acesse **[supabase.com](https://supabase.com)** e crie uma conta gratuita (ou faça login com seu GitHub).
2. Clique no botão verde **"New Project"** (Novo Projeto).
3. Preencha os dados:
   - **Name**: `decorando-lei-seca`
   - **Database Password**: Digite uma senha forte e anote-a.
   - **Region**: Selecione `South America (São Paulo)` ou a mais próxima.
   - **Pricing Plan**: `Free Plan` (Grátis).
4. Clique em **"Create new project"** e aguarde cerca de 1 a 2 minutos até o projeto inicializar.

---

### 📍 Passo 2: Copiar as Credenciais do Supabase (URL e API Key)
1. No menu lateral esquerdo do Supabase, clique no ícone de engrenagem **Project Settings** (ou clique no botão **Connect** no topo).
2. Clique na aba **"API"** (ou **Data API**).
3. Você verá dois valores fundamentais:
   - **Project URL**: Algo como `https://xyzabcdefghijklm.supabase.co` ➡️ **Copie este valor**.
   - **Project API Keys**: Localize a chave chamada `anon` (public) ou `service_role` (secret) ➡️ **Copie esta chave**.

---

### 📍 Passo 3: Criar o Bucket de Armazenamento no Supabase
1. No menu lateral esquerdo do Supabase, clique no ícone de pasta **"Storage"**.
2. Clique no botão **"New bucket"** (Criar novo bucket).
3. Configure:
   - **Bucket Name**: Digite exatamente: `decorando-data`
   - **Public bucket**: Deixe a chave **marcada (ativada)** (verde) para permitir leitura rápida dos dados.
4. Clique em **"Save"** (Salvar). Pronto! O cofre na nuvem está criado.

---

### 📍 Passo 4: Conectar no Render (Variáveis de Ambiente)
1. Acesse o seu painel no **[dashboard.render.com](https://dashboard.render.com)**.
2. Clique no seu serviço web (`decorando-lei-seca`).
3. No menu lateral esquerdo, clique em **"Environment"** (Variáveis de Ambiente).
4. Clique em **"Add Environment Variable"** e adicione as seguintes variáveis:

| Key (Nome da Variável) | Value (Valor) |
|---|---|
| `SUPABASE_URL` | Cole a sua **Project URL** (ex: `https://xyzabcdefg.supabase.co`) |
| `SUPABASE_KEY` | Cole a sua chave **API Key** copiada do Supabase |
| `SUPABASE_BUCKET` | `decorando-data` |

5. Clique no botão **"Save Changes"** no rodapé do Render.
6. O Render fará o deploy automático e o aplicativo já nascerá conectado à nuvem do Supabase!

---

### 📍 Passo 5: Sincronizar e Usar no Aplicativo
1. Abra o seu aplicativo no Render.
2. Faça login com seu e-mail de administrador (`fabiolucio277@gmail.com`).
3. Vá na aba **"🛡 Painel Admin"** e role até a seção **"☁️ 3. Sincronização em Nuvem com Supabase"**.
4. Você verá o indicador: `🟢 Supabase Conectado`!
5. Clique em **"⬆️ Salvar Tudo no Supabase Agora (Upload Nuvem)"**:
   - O aplicativo enviará o `decorando_lei.db` e todos os PDFs para a nuvem.
6. A partir desse momento:
   - **Sempre que o Render reiniciar:** o app detecta e baixa automaticamente a cópia mais recente da nuvem antes de exibir as telas.
   - **Você nunca mais perde leis, cadernos, filtros ou respostas!**

---

## 🛠️ 7. O que foi corrigido nesta versão

1. **Fim do Código HTML após responder**:
   - No Streamlit, blocos de texto HTML indentados com 4 espaços eram interpretados pelo parser de Markdown como blocos `<pre><code>`.
   - Implementado o tratador `render_html_limpo(...)` que remove qualquer recuo indevido e preserva a renderização visual nativa.
   - Adicionado limpador automático no banco SQLite para tratar questões criadas em versões anteriores.

2. **Cores Mais Nítidas, Vivas e Alto Contraste**:
   - Status verde esmeralda para acertos (`#16a34a`) e vermelho rubi para erros (`#dc2626`).
   - Dispositivo Literal com borda azul e texto em `#0f172a` (preto ardósia ultra-nítido, sem tons apagados).
   - Exemplo Prático com 4 cartões internos em destaque: Situação Concreta (azul), Aplicação Prática (verde), Objetivo da Regra (roxo) e Bizu de Memorização em gradiente dourado.

3. **Arquivos de Deploy prontos para o Render**:
   - `requirements.txt` com todas as dependências requeridas.
   - `Procfile` para inicialização automática em plataformas cloud.
   - `render.yaml` pronto para deploy via Blueprint.
   - Porta dinâmica configurada para a variável `$PORT` do ambiente.
