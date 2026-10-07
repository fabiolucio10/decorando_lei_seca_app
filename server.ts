import express from 'express';
import path from 'path';
import fs from 'fs';
import { fileURLToPath } from 'url';
import { createServer as createViteServer } from 'vite';
import { GoogleGenAI } from '@google/genai';
import dotenv from 'dotenv';

dotenv.config();

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const app = express();
const PORT = Number(process.env.PORT) || 3000;

app.use(express.json());

// Initialize Gemini API client on the server side
const apiKey = process.env.GEMINI_API_KEY;
let aiClient: GoogleGenAI | null = null;
if (apiKey) {
  aiClient = new GoogleGenAI({
    apiKey: apiKey,
    httpOptions: {
      headers: {
        'User-Agent': 'aistudio-build',
      },
    },
  });
}

// Endpoint to generate a realistic objective practical example using Gemini
app.post('/api/gerar-exemplo-pratico', async (req, res) => {
  try {
    const { dispositivo, textoLegal } = req.body;
    if (!dispositivo || !textoLegal) {
      return res.status(400).json({ error: 'Dispositivo e textoLegal são obrigatórios' });
    }

    if (!aiClient) {
      return res.json({
        fallback: true,
        message: 'GEMINI_API_KEY não configurada no servidor; usando motor heurístico.',
      });
    }

    const prompt = `Você é um jurista e professor de Direito para concursos públicos no Brasil.
Dispositivo legal: ${dispositivo}
Texto da Lei: "${textoLegal}"

Crie um exemplo prático e objetivo da vida real, extremamente claro e direto, demonstrando como esse dispositivo legal é aplicado na prática (em um tribunal, delegacia, repartição pública ou cotidiano do cidadão).

Responda em formato JSON válido com as seguintes chaves:
{
  "situacaoReal": "Breve narrativa de 2 ou 3 frases com caso concreto simples",
  "aplicacaoRegra": "Como a regra foi aplicada ao caso concreto",
  "objetivoRegra": "Qual o objetivo protetivo ou formal da norma",
  "bizuMemorizacao": "Uma dica rápida de memorização ou pegadinha comum de banca"
}`;

    const response = await aiClient.models.generateContent({
      model: 'gemini-3.8-flash',
      contents: prompt,
      config: {
        responseMimeType: 'application/json',
      },
    });

    if (response.text) {
      const data = JSON.parse(response.text);
      return res.json({ success: true, data });
    }

    return res.json({ fallback: true });
  } catch (err: any) {
    console.error('Erro na geração via Gemini:', err);
    return res.status(500).json({ error: 'Erro ao gerar exemplo com IA', details: err.message });
  }
});

// Endpoint to fetch the full updated Python code
app.get('/api/python-code', (req, res) => {
  try {
    const pythonFilePath = path.join(__dirname, 'app.py');
    if (fs.existsSync(pythonFilePath)) {
      const code = fs.readFileSync(pythonFilePath, 'utf-8');
      res.setHeader('Content-Type', 'text/plain; charset=utf-8');
      return res.send(code);
    }
    return res.status(404).send('Arquivo app.py não encontrado');
  } catch (err: any) {
    return res.status(500).send('Erro ao ler código python: ' + err.message);
  }
});

// Endpoint to fetch requirements.txt
app.get('/api/requirements', (req, res) => {
  try {
    const filePath = path.join(__dirname, 'requirements.txt');
    if (fs.existsSync(filePath)) {
      const content = fs.readFileSync(filePath, 'utf-8');
      res.setHeader('Content-Type', 'text/plain; charset=utf-8');
      return res.send(content);
    }
    return res.status(404).send('Arquivo requirements.txt não encontrado');
  } catch (err: any) {
    return res.status(500).send('Erro ao ler requirements: ' + err.message);
  }
});

// Endpoint to fetch render.yaml
app.get('/api/render-yaml', (req, res) => {
  try {
    const filePath = path.join(__dirname, 'render.yaml');
    if (fs.existsSync(filePath)) {
      const content = fs.readFileSync(filePath, 'utf-8');
      res.setHeader('Content-Type', 'text/plain; charset=utf-8');
      return res.send(content);
    }
    return res.status(404).send('Arquivo render.yaml não encontrado');
  } catch (err: any) {
    return res.status(500).send('Erro ao ler render.yaml: ' + err.message);
  }
});

// Endpoint to fetch deployment instructions
app.get('/api/instrucoes', (req, res) => {
  try {
    const filePath = path.join(__dirname, 'INSTRUCOES_VSCODE_E_RENDER.md');
    if (fs.existsSync(filePath)) {
      const content = fs.readFileSync(filePath, 'utf-8');
      res.setHeader('Content-Type', 'text/plain; charset=utf-8');
      return res.send(content);
    }
    return res.status(404).send('Arquivo de instruções não encontrado');
  } catch (err: any) {
    return res.status(500).send('Erro ao ler instruções: ' + err.message);
  }
});

// Endpoint to fetch iniciar.bat
app.get('/api/iniciar-bat', (req, res) => {
  try {
    const filePath = path.join(__dirname, 'iniciar.bat');
    if (fs.existsSync(filePath)) {
      const content = fs.readFileSync(filePath, 'utf-8');
      res.setHeader('Content-Type', 'text/plain; charset=utf-8');
      return res.send(content);
    }
    return res.status(404).send('Arquivo iniciar.bat não encontrado');
  } catch (err: any) {
    return res.status(500).send('Erro ao ler iniciar.bat: ' + err.message);
  }
});

async function startServer() {
  const isProd = process.env.NODE_ENV === 'production';

  if (!isProd) {
    // Mount Vite middleware in development
    const vite = await createViteServer({
      server: { middlewareMode: true },
      appType: 'spa',
    });
    app.use(vite.middlewares);
  } else {
    // Serve static build in production
    app.use(express.static(path.join(__dirname, 'dist')));
    app.get('*', (req, res) => {
      res.sendFile(path.join(__dirname, 'dist', 'index.html'));
    });
  }

  app.listen(PORT, '0.0.0.0', () => {
    console.log(`Server listening on http://0.0.0.0:${PORT}`);
  });
}

startServer();
