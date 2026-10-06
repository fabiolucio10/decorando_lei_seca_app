import React, { useState } from 'react';
import { fracionarArtigo } from '../utils/fragmentation';
import { SAMPLE_LAWS } from '../data/sampleLaws';
import { Split, AlertCircle, CheckCircle2, ArrowRight, Play, Eye } from 'lucide-react';

export const FragmentationLab: React.FC = () => {
  const [selectedSample, setSelectedSample] = useState<string>('cf-art5');
  const [customArtNumber, setCustomArtNumber] = useState<string>('Art. 5º');
  const [inputText, setInputText] = useState<string>(SAMPLE_LAWS[0].text);

  const handleLoadSample = (sampleId: string) => {
    setSelectedSample(sampleId);
    const found = SAMPLE_LAWS.find((s) => s.id === sampleId);
    if (found) {
      setCustomArtNumber(found.articleNumber);
      setInputText(found.text);
    }
  };

  // Run the smart fragmentation engine on the current text
  const fragmentedDevices = fracionarArtigo(customArtNumber, inputText, 'lab-art');

  return (
    <div className="max-w-6xl mx-auto space-y-8">
      {/* Introduction banner */}
      <div className="bg-white border border-slate-200 rounded-xl p-6 shadow-xs">
        <div className="flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
          <div>
            <h2 className="text-lg font-bold text-slate-900 flex items-center gap-2">
              <Split className="w-5 h-5 text-blue-600" />
              Simulador & Comparador de Fragmentação
            </h2>
            <p className="text-xs text-slate-600 mt-1 max-w-2xl leading-relaxed">
              Compare visualmente como o artigo era exibido antes (bloco único e extenso, como visto no print do seu app)
              contra o novo motor de fragmentação que divide incisos romanos até LXXIX, parágrafos e alíneas em questões concisas.
            </p>
          </div>

          <div className="flex items-center gap-2 text-xs">
            <span className="text-slate-500 font-medium">Exemplos Prontos:</span>
            {SAMPLE_LAWS.map((l) => (
              <button
                key={l.id}
                onClick={() => handleLoadSample(l.id)}
                className={`px-3 py-1.5 rounded-lg border text-xs font-medium cursor-pointer transition-colors ${
                  selectedSample === l.id
                    ? 'border-blue-600 bg-blue-50 text-blue-700'
                    : 'border-slate-200 hover:border-slate-300 text-slate-700 bg-white'
                }`}
              >
                {l.articleNumber} ({l.lawName.split(' ')[0]})
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Before vs After comparison cards */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Card Antes (Como estava no Print do Usuário) */}
        <div className="bg-rose-50/40 border border-rose-200 rounded-xl p-5 flex flex-col">
          <div className="flex items-center justify-between pb-3 border-b border-rose-200/60 mb-3">
            <div className="flex items-center gap-2 text-rose-800 font-bold text-sm">
              <AlertCircle className="w-4 h-4 text-rose-600" />
              <span>Antes (Problema Evidenciado no Print)</span>
            </div>
            <span className="text-xs text-rose-700 bg-rose-100/70 px-2 py-0.5 rounded font-mono">
              1 Questão Gigante (~{inputText.length} caracteres)
            </span>
          </div>

          <p className="text-xs text-slate-600 mb-3">
            O algoritmo antigo limitava incisos romanos até <strong>XX (20)</strong> e não fragmentava textos agrupados,
            gerando uma única questão contendo dezenas de incisos simultâneos:
          </p>

          <div className="bg-white rounded-lg p-4 border border-rose-200 text-xs text-slate-700 font-serif leading-relaxed max-h-96 overflow-y-auto space-y-2 text-justify">
            <div className="text-xs font-sans font-semibold text-rose-800 pb-1 border-b border-rose-100">
              Questão 2 de 14 · Dispositivo: {customArtNumber} (caput agrupado)
            </div>
            <p className="line-clamp-12 text-slate-600 italic">
              "{inputText.slice(0, 1100)}..."
            </p>
            <div className="pt-2 text-[11px] text-rose-600 font-sans font-medium">
              ⚠️ Inviável para memorização: o estudante se depara com 30 a 50 linhas de lei em um único enunciado.
            </div>
          </div>
        </div>

        {/* Card Depois (Motor Atualizado e Fragmentado) */}
        <div className="bg-emerald-50/40 border border-emerald-200 rounded-xl p-5 flex flex-col">
          <div className="flex items-center justify-between pb-3 border-b border-emerald-200/60 mb-3">
            <div className="flex items-center gap-2 text-emerald-800 font-bold text-sm">
              <CheckCircle2 className="w-4 h-4 text-emerald-600" />
              <span>Depois (Motor Inteligente Fragmentado)</span>
            </div>
            <span className="text-xs text-emerald-800 bg-emerald-100/70 px-2 py-0.5 rounded font-mono">
              {fragmentedDevices.length} Questões Concisas
            </span>
          </div>

          <p className="text-xs text-slate-600 mb-3">
            Cada inciso (I até LXXIX), parágrafo e alínea é isolado em seu próprio item. Dispositivos curtos vêm
            diretos; dispositivos longos têm contexto de caput sob demanda:
          </p>

          <div className="space-y-2 max-h-96 overflow-y-auto pr-1">
            {fragmentedDevices.slice(0, 7).map((dev, i) => (
              <div
                key={dev.id}
                className="bg-white rounded-lg p-3 border border-emerald-200 text-xs text-slate-800 shadow-2xs hover:border-emerald-400 transition-colors"
              >
                <div className="flex items-center justify-between font-semibold text-emerald-900 mb-1">
                  <span>{dev.deviceLabel}</span>
                  <span className="text-[11px] font-mono text-slate-500 font-normal">
                    {dev.charCount} caracteres {dev.isShort ? '· Curto' : '· Fragmentado'}
                  </span>
                </div>
                <p className="text-slate-600 line-clamp-2 italic">
                  "{dev.rawText}"
                </p>
              </div>
            ))}

            {fragmentedDevices.length > 7 && (
              <div className="p-2 text-center text-xs text-emerald-700 bg-emerald-50 rounded-lg font-medium">
                + {fragmentedDevices.length - 7} outros dispositivos individualizados prontos para estudo
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Custom Textarea for testing user's own articles */}
      <div className="bg-white border border-slate-200 rounded-xl p-6 shadow-xs space-y-4">
        <h3 className="text-sm font-bold text-slate-900">
          Testar com Seu Próprio Artigo ou Lei
        </h3>
        <div className="grid grid-cols-1 sm:grid-cols-4 gap-4">
          <div className="sm:col-span-1">
            <label className="text-xs font-medium text-slate-600 block mb-1">
              Número do Artigo:
            </label>
            <input
              type="text"
              value={customArtNumber}
              onChange={(e) => setCustomArtNumber(e.target.value)}
              className="w-full text-xs border border-slate-300 rounded-lg px-3 py-2 bg-slate-50"
              placeholder="Ex: Art. 5º"
            />
          </div>

          <div className="sm:col-span-3">
            <label className="text-xs font-medium text-slate-600 block mb-1">
              Texto Completo do Artigo (Cole aqui com incisos, parágrafos e alíneas):
            </label>
            <textarea
              rows={5}
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              className="w-full text-xs border border-slate-300 rounded-lg p-3 bg-slate-50 font-mono"
            />
          </div>
        </div>

        <div className="flex items-center justify-between pt-2">
          <span className="text-xs text-slate-500">
            Total de unidades normativas extraídas: <strong>{fragmentedDevices.length}</strong>
          </span>
          <span className="text-xs text-emerald-700 font-semibold">
            ✓ Fragmentação Instantânea em Tempo Real
          </span>
        </div>
      </div>
    </div>
  );
};
