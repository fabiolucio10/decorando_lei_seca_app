import React, { useState, useEffect } from 'react';
import { Download, Copy, Check, FileCode, CheckCircle2, Sparkles, Terminal, Cloud, HelpCircle, Layers, Palette } from 'lucide-react';

export const PythonCodeViewer: React.FC = () => {
  const [activeFile, setActiveFile] = useState<'app.py' | 'requirements.txt' | 'render.yaml' | 'instrucoes'>('app.py');
  const [filesContent, setFilesContent] = useState<{ [key: string]: string }>({
    'app.py': '',
    'requirements.txt': '',
    'render.yaml': '',
    instrucoes: '',
  });
  const [copied, setCopied] = useState<boolean>(false);
  const [copiedCommand, setCopiedCommand] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState<string>('');

  useEffect(() => {
    // Carrega app.py
    fetch('/api/python-code')
      .then((res) => res.text())
      .then((data) => setFilesContent((prev) => ({ ...prev, 'app.py': data })))
      .catch((err) => console.error('Erro ao carregar app.py:', err));

    // Carrega requirements.txt
    fetch('/api/requirements')
      .then((res) => res.text())
      .then((data) => setFilesContent((prev) => ({ ...prev, 'requirements.txt': data })))
      .catch((err) => console.error('Erro ao carregar requirements:', err));

    // Carrega render.yaml
    fetch('/api/render-yaml')
      .then((res) => res.text())
      .then((data) => setFilesContent((prev) => ({ ...prev, 'render.yaml': data })))
      .catch((err) => console.error('Erro ao carregar render.yaml:', err));

    // Carrega instrucoes
    fetch('/api/instrucoes')
      .then((res) => res.text())
      .then((data) => setFilesContent((prev) => ({ ...prev, instrucoes: data })))
      .catch((err) => console.error('Erro ao carregar instrucoes:', err));
  }, []);

  const currentContent = filesContent[activeFile] || '';

  const handleCopy = (textToCopy?: string) => {
    const text = textToCopy || currentContent;
    if (!text) return;
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 3000);
    });
  };

  const handleCopyCommand = (cmd: string) => {
    navigator.clipboard.writeText(cmd).then(() => {
      setCopiedCommand(cmd);
      setTimeout(() => setCopiedCommand(null), 2500);
    });
  };

  const handleDownload = () => {
    if (!currentContent) return;
    const filename =
      activeFile === 'instrucoes'
        ? 'INSTRUCOES_VSCODE_E_RENDER.md'
        : activeFile;
    const blob = new Blob([currentContent], { type: 'text/plain;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.setAttribute('download', filename);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const codeLines = currentContent.split('\n');
  const filteredIndices = searchQuery
    ? codeLines
        .map((line, idx) => (line.toLowerCase().includes(searchQuery.toLowerCase()) ? idx : -1))
        .filter((idx) => idx !== -1)
    : [];

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      {/* Top Banner with Actions */}
      <div className="bg-white border border-slate-200 rounded-xl p-6 shadow-xs">
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
          <div>
            <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-emerald-50 text-emerald-800 text-xs font-semibold mb-2 border border-emerald-200">
              <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" />
              <span>Código Completo e 100% Atualizado (Render + VSCode)</span>
            </div>
            <h2 className="text-xl font-bold text-slate-900 flex items-center gap-2">
              <FileCode className="w-5 h-5 text-blue-600" />
              Arquivos de Configuração e Código Python
            </h2>
            <p className="text-xs text-slate-600 mt-1 max-w-3xl leading-relaxed">
              Todos os arquivos necessários para você rodar perfeitamente no seu VSCode e publicar no Render (Render.com).
              Inclui a remoção dos códigos HTML nos cartões de resposta, textos com alto contraste e cores nítidas, e nexo formal com o Caput.
            </p>
          </div>

          <div className="flex items-center gap-2.5 shrink-0">
            <button
              onClick={() => handleCopy()}
              className={`px-4 py-2 text-xs font-semibold rounded-lg flex items-center gap-2 transition-colors cursor-pointer shadow-xs ${
                copied ? 'bg-emerald-600 text-white' : 'bg-blue-600 hover:bg-blue-700 text-white'
              }`}
            >
              {copied ? <Check className="w-4 h-4" /> : <Copy className="w-4 h-4" />}
              <span>{copied ? 'Copiado!' : `Copiar ${activeFile}`}</span>
            </button>

            <button
              onClick={handleDownload}
              className="px-4 py-2 text-xs font-semibold rounded-lg border border-slate-300 bg-white hover:bg-slate-50 text-slate-700 flex items-center gap-2 transition-colors cursor-pointer shadow-xs"
            >
              <Download className="w-4 h-4 text-slate-600" />
              <span>Baixar {activeFile}</span>
            </button>
          </div>
        </div>

        {/* File selector tabs */}
        <div className="flex items-center gap-2 mt-6 pt-4 border-t border-slate-100 overflow-x-auto">
          <button
            onClick={() => setActiveFile('app.py')}
            className={`px-3.5 py-1.5 text-xs font-semibold rounded-lg transition-all flex items-center gap-2 cursor-pointer ${
              activeFile === 'app.py'
                ? 'bg-blue-600 text-white shadow-xs'
                : 'bg-slate-100 hover:bg-slate-200 text-slate-700'
            }`}
          >
            <FileCode className="w-3.5 h-3.5" />
            <span>app.py (Streamlit Principal)</span>
          </button>

          <button
            onClick={() => setActiveFile('requirements.txt')}
            className={`px-3.5 py-1.5 text-xs font-semibold rounded-lg transition-all flex items-center gap-2 cursor-pointer ${
              activeFile === 'requirements.txt'
                ? 'bg-blue-600 text-white shadow-xs'
                : 'bg-slate-100 hover:bg-slate-200 text-slate-700'
            }`}
          >
            <Layers className="w-3.5 h-3.5" />
            <span>requirements.txt (Pacotes Python)</span>
          </button>

          <button
            onClick={() => setActiveFile('render.yaml')}
            className={`px-3.5 py-1.5 text-xs font-semibold rounded-lg transition-all flex items-center gap-2 cursor-pointer ${
              activeFile === 'render.yaml'
                ? 'bg-blue-600 text-white shadow-xs'
                : 'bg-slate-100 hover:bg-slate-200 text-slate-700'
            }`}
          >
            <Cloud className="w-3.5 h-3.5" />
            <span>render.yaml (Blueprint Render)</span>
          </button>

          <button
            onClick={() => setActiveFile('instrucoes')}
            className={`px-3.5 py-1.5 text-xs font-semibold rounded-lg transition-all flex items-center gap-2 cursor-pointer ${
              activeFile === 'instrucoes'
                ? 'bg-blue-600 text-white shadow-xs'
                : 'bg-slate-100 hover:bg-slate-200 text-slate-700'
            }`}
          >
            <HelpCircle className="w-3.5 h-3.5" />
            <span>Guia Passo a Passo (VSCode & Render)</span>
          </button>
        </div>
      </div>

      {/* Quick Visual Guide for VSCode & Render */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Box 1: Comandos VSCode */}
        <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-xs">
          <div className="flex items-center gap-2 text-xs font-bold text-slate-900 mb-3">
            <Terminal className="w-4 h-4 text-blue-600" />
            <span>Como rodar no terminal do seu VSCode:</span>
          </div>

          <div className="space-y-2.5 text-xs">
            <div className="bg-slate-900 text-slate-200 p-3 rounded-lg font-mono flex items-center justify-between">
              <span className="text-emerald-400">pip install -r requirements.txt</span>
              <button
                onClick={() => handleCopyCommand('pip install -r requirements.txt')}
                className="text-[11px] text-slate-400 hover:text-white px-2 py-0.5 bg-slate-800 rounded"
              >
                {copiedCommand === 'pip install -r requirements.txt' ? 'Copiado!' : 'Copiar'}
              </button>
            </div>

            <div className="bg-slate-900 text-slate-200 p-3 rounded-lg font-mono flex items-center justify-between">
              <span className="text-blue-400">streamlit run app.py</span>
              <button
                onClick={() => handleCopyCommand('streamlit run app.py')}
                className="text-[11px] text-slate-400 hover:text-white px-2 py-0.5 bg-slate-800 rounded"
              >
                {copiedCommand === 'streamlit run app.py' ? 'Copiado!' : 'Copiar'}
              </button>
            </div>
            <p className="text-[11px] text-slate-500 italic">
              💡 Abra a pasta do projeto no VSCode e execute os dois comandos acima no terminal integrado!
            </p>
          </div>
        </div>

        {/* Box 2: Configuração no Render */}
        <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-xs">
          <div className="flex items-center gap-2 text-xs font-bold text-slate-900 mb-3">
            <Cloud className="w-4 h-4 text-emerald-600" />
            <span>Configuração do Web Service no Render.com:</span>
          </div>

          <div className="space-y-2 text-xs text-slate-700">
            <div className="flex items-center justify-between p-2 bg-slate-50 border border-slate-200 rounded-lg">
              <span className="font-semibold text-slate-800">Build Command:</span>
              <code className="bg-white px-2 py-0.5 border border-slate-300 rounded text-slate-900 text-[11px]">
                pip install -r requirements.txt
              </code>
            </div>

            <div className="flex flex-col gap-1 p-2 bg-slate-50 border border-slate-200 rounded-lg">
              <div className="flex items-center justify-between">
                <span className="font-semibold text-slate-800">Start Command:</span>
                <button
                  onClick={() =>
                    handleCopyCommand(
                      'streamlit run app.py --server.port $PORT --server.address 0.0.0.0 --server.headless true'
                    )
                  }
                  className="text-[11px] text-blue-600 hover:underline font-medium"
                >
                  {copiedCommand?.includes('--server.port $PORT') ? 'Copiado!' : 'Copiar Comando'}
                </button>
              </div>
              <code className="bg-white px-2 py-1 border border-slate-300 rounded text-slate-900 text-[11px] break-all font-mono">
                streamlit run app.py --server.port $PORT --server.address 0.0.0.0 --server.headless true
              </code>
            </div>
          </div>
        </div>
      </div>

      {/* Summary of improvements applied */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <div className="bg-white border border-slate-200 rounded-xl p-4 shadow-xs">
          <div className="flex items-center gap-2 font-bold text-slate-900 text-xs mb-1.5">
            <CheckCircle2 className="w-4 h-4 text-emerald-600" />
            1. Zero Código HTML Exposto
          </div>
          <p className="text-xs text-slate-600 leading-relaxed">
            Eliminado o erro onde as tags HTML apareciam como código bruto após clicar em Certo/Errado. Agora todos os cartões usam renderização nativa limpa.
          </p>
        </div>

        <div className="bg-white border border-slate-200 rounded-xl p-4 shadow-xs">
          <div className="flex items-center gap-2 font-bold text-slate-900 text-xs mb-1.5">
            <Palette className="w-4 h-4 text-blue-600" />
            2. Cores Vivas e Alto Contraste
          </div>
          <p className="text-xs text-slate-600 leading-relaxed">
            Textos nítidos em preto ardósia (<code>#0f172a</code>), bordas coloridas, cartões de situação concreta destacados e fim dos tons cinzas apagados.
          </p>
        </div>

        <div className="bg-white border border-slate-200 rounded-xl p-4 shadow-xs">
          <div className="flex items-center gap-2 font-bold text-slate-900 text-xs mb-1.5">
            <CheckCircle2 className="w-4 h-4 text-indigo-600" />
            3. Nexo com o Caput da Lei
          </div>
          <p className="text-xs text-slate-600 leading-relaxed">
            Perguntas gramaticalmente conectadas ao Caput de origem (ex: Art. 5º da CF/88) e fragmentação completa de incisos romanos até LXXIX+.
          </p>
        </div>

        <div className="bg-white border border-slate-200 rounded-xl p-4 shadow-xs">
          <div className="flex items-center gap-2 font-bold text-slate-900 text-xs mb-1.5">
            <Sparkles className="w-4 h-4 text-amber-600" />
            4. Arquivos Prontos para Deploy
          </div>
          <p className="text-xs text-slate-600 leading-relaxed">
            <code>requirements.txt</code>, <code>render.yaml</code> e <code>Procfile</code> prontos para que seu app suba no Render sem erros de módulo ou porta!
          </p>
        </div>
      </div>

      {/* Code viewer box */}
      <div className="bg-slate-900 rounded-xl border border-slate-800 overflow-hidden shadow-md">
        <div className="px-4 py-3 bg-slate-950 border-b border-slate-800 flex items-center justify-between">
          <div className="flex items-center gap-2 text-xs text-slate-300">
            <span className="w-3 h-3 rounded-full bg-rose-500 inline-block"></span>
            <span className="w-3 h-3 rounded-full bg-amber-500 inline-block"></span>
            <span className="w-3 h-3 rounded-full bg-emerald-500 inline-block"></span>
            <span className="ml-2 font-mono text-slate-300 font-semibold">{activeFile}</span>
            <span className="text-slate-600">·</span>
            <span className="text-slate-400 font-mono text-[11px]">{codeLines.length} linhas</span>
          </div>

          <div className="flex items-center gap-2">
            <input
              type="text"
              placeholder="Buscar no código..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="px-2.5 py-1 text-xs bg-slate-800 text-slate-200 border border-slate-700 rounded-md focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
            <button
              onClick={() => handleCopy()}
              className="text-xs text-slate-300 hover:text-white px-2.5 py-1 bg-slate-800 hover:bg-slate-700 rounded-md transition-colors cursor-pointer"
            >
              {copied ? 'Copiado!' : 'Copiar'}
            </button>
          </div>
        </div>

        <div className="p-4 max-h-[620px] overflow-y-auto font-mono text-xs text-slate-200 leading-relaxed select-all">
          <pre>
            {codeLines.map((line, idx) => {
              const isMatch = searchQuery && line.toLowerCase().includes(searchQuery.toLowerCase());
              return (
                <div
                  key={idx}
                  className={`flex items-start hover:bg-slate-800/60 px-2 py-0.5 rounded ${
                    isMatch ? 'bg-amber-950/60 text-amber-200' : ''
                  }`}
                >
                  <span className="text-slate-600 select-none w-12 shrink-0 text-right pr-4 font-mono text-[11px]">
                    {idx + 1}
                  </span>
                  <span className="whitespace-pre-wrap break-all">{line}</span>
                </div>
              );
            })}
          </pre>
        </div>
      </div>
    </div>
  );
};
