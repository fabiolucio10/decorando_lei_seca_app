import React, { useState, useEffect } from 'react';
import { Download, Copy, Check, FileCode, CheckCircle2, AlertCircle, Sparkles } from 'lucide-react';

export const PythonCodeViewer: React.FC = () => {
  const [code, setCode] = useState<string>('');
  const [copied, setCopied] = useState<boolean>(false);
  const [searchQuery, setSearchQuery] = useState<string>('');

  useEffect(() => {
    fetch('/api/python-code')
      .then((res) => res.text())
      .then((data) => setCode(data))
      .catch((err) => console.error('Erro ao carregar código python:', err));
  }, []);

  const handleCopy = () => {
    if (!code) return;
    navigator.clipboard.writeText(code).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 3000);
    });
  };

  const handleDownload = () => {
    if (!code) return;
    const blob = new Blob([code], { type: 'text/x-python;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.setAttribute('download', 'app.py');
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const codeLines = code.split('\n');
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
            <h2 className="text-lg font-bold text-slate-900 flex items-center gap-2">
              <FileCode className="w-5 h-5 text-blue-600" />
              Código Python Atualizado para VS Code (`app.py`)
            </h2>
            <p className="text-xs text-slate-600 mt-1 max-w-2xl leading-relaxed">
              Aqui está o seu arquivo Python completo e ajustado, pronto para ser copiado ou baixado e colocado
              diretamente no seu VS Code para rodar o Streamlit com a nova fragmentação e os exemplos práticos objetivos.
            </p>
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={handleCopy}
              className={`px-4 py-2 text-xs font-semibold rounded-lg flex items-center gap-2 transition-colors cursor-pointer shadow-xs ${
                copied
                  ? 'bg-emerald-600 text-white'
                  : 'bg-blue-600 hover:bg-blue-700 text-white'
              }`}
            >
              {copied ? <Check className="w-4 h-4" /> : <Copy className="w-4 h-4" />}
              <span>{copied ? 'Código Copiado!' : 'Copiar Código'}</span>
            </button>

            <button
              onClick={handleDownload}
              className="px-4 py-2 text-xs font-semibold rounded-lg border border-slate-300 bg-white hover:bg-slate-50 text-slate-700 flex items-center gap-2 transition-colors cursor-pointer shadow-xs"
            >
              <Download className="w-4 h-4 text-slate-600" />
              <span>Baixar `app.py`</span>
            </button>
          </div>
        </div>
      </div>

      {/* Summary of improvements applied */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <div className="bg-white border border-slate-200 rounded-xl p-4 shadow-xs">
          <div className="flex items-center gap-2 font-bold text-slate-900 text-xs mb-1.5">
            <CheckCircle2 className="w-4 h-4 text-blue-600" />
            1. Incisos Romanos até LXXIX+
          </div>
          <p className="text-xs text-slate-600 leading-relaxed">
            Regex universal <code>REGEX_ROMANO</code> cobrindo de <code>I</code> até <code>CCC</code> (1 a 300+), separando com precisão todos os 79 incisos do Art. 5º da CF/88.
          </p>
        </div>

        <div className="bg-white border border-slate-200 rounded-xl p-4 shadow-xs">
          <div className="flex items-center gap-2 font-bold text-slate-900 text-xs mb-1.5">
            <CheckCircle2 className="w-4 h-4 text-emerald-600" />
            2. Nexo com Caput de Origem
          </div>
          <p className="text-xs text-slate-600 leading-relaxed">
            Ligação direta entre incisos/parágrafos e o Caput do artigo correspondente (ex: Art. 5º Todos são iguais perante a lei...), dando pleno sentido e contexto às perguntas.
          </p>
        </div>

        <div className="bg-white border border-slate-200 rounded-xl p-4 shadow-xs">
          <div className="flex items-center gap-2 font-bold text-slate-900 text-xs mb-1.5">
            <CheckCircle2 className="w-4 h-4 text-indigo-600" />
            3. Questões com Nexo (Cebraspe/OAB)
          </div>
          <p className="text-xs text-slate-600 leading-relaxed">
            Assertivas limpas sem marcadores soltos (como "XLIX - ") e pegadinhas com lógica jurídica e gramatical perfeita (fim das inversões estranhas de palavras).
          </p>
        </div>

        <div className="bg-white border border-slate-200 rounded-xl p-4 shadow-xs">
          <div className="flex items-center gap-2 font-bold text-slate-900 text-xs mb-1.5">
            <Sparkles className="w-4 h-4 text-amber-600" />
            4. IA Gemini & Exemplos Reais
          </div>
          <p className="text-xs text-slate-600 leading-relaxed">
            Exemplos objetivos da vida real (Situação Concreta, Aplicação, Objetivo e Bizu), acionados tanto na geração do caderno quanto ao vivo ao responder!
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
            <span className="ml-2 font-mono text-slate-400">app.py (Streamlit)</span>
            <span className="text-slate-600">·</span>
            <span className="text-slate-500 font-mono text-[11px]">{codeLines.length} linhas</span>
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
              onClick={handleCopy}
              className="text-xs text-slate-300 hover:text-white px-2.5 py-1 bg-slate-800 hover:bg-slate-700 rounded-md transition-colors"
            >
              {copied ? 'Copiado!' : 'Copiar'}
            </button>
          </div>
        </div>

        <div className="p-4 max-h-[600px] overflow-y-auto font-mono text-xs text-slate-200 leading-relaxed select-all">
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
                  <span className="text-slate-600 select-none w-10 shrink-0 text-right pr-4 font-mono text-[11px]">
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
