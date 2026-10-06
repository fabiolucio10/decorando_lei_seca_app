import React, { useState } from 'react';
import { SAMPLE_LAWS } from '../data/sampleLaws';
import { BookMarked, Plus, Sparkles, Trash2, CheckCircle2 } from 'lucide-react';

interface NotebookCreatorProps {
  onCreateNotebook: (name: string, discipline: string, lawName: string, articleIds: string[], questionCount: number) => void;
  availableFilters: string[];
}

export const NotebookCreator: React.FC<NotebookCreatorProps> = ({
  onCreateNotebook,
  availableFilters,
}) => {
  const [notebookName, setNotebookName] = useState('');
  const [selectedDiscipline, setSelectedDiscipline] = useState('Direito Constitucional');
  const [selectedLaw, setSelectedLaw] = useState('Constituição Federal de 1988');
  const [selectedArticles, setSelectedArticles] = useState<string[]>(['cf-art5']);
  const [questionCount, setQuestionCount] = useState<number>(15);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  const disciplines = Array.from(new Set(SAMPLE_LAWS.map((l) => l.discipline)));
  const lawsForDiscipline = SAMPLE_LAWS.filter((l) => l.discipline === selectedDiscipline);

  const handleToggleArticle = (artId: string) => {
    setSelectedArticles((prev) =>
      prev.includes(artId) ? prev.filter((id) => id !== artId) : [...prev, artId]
    );
  };

  const handleCreate = (e: React.FormEvent) => {
    e.preventDefault();
    if (!notebookName.trim()) return;

    onCreateNotebook(
      notebookName.trim(),
      selectedDiscipline,
      selectedLaw,
      selectedArticles.length > 0 ? selectedArticles : lawsForDiscipline.map((l) => l.id),
      questionCount
    );

    setSuccessMessage(`Caderno "${notebookName}" criado e fragmentado com sucesso!`);
    setNotebookName('');
    setTimeout(() => setSuccessMessage(null), 4000);
  };

  return (
    <div className="max-w-4xl mx-auto space-y-8">
      {/* Creation form */}
      <div className="bg-white border border-slate-200 rounded-xl p-6 sm:p-8 shadow-xs">
        <h2 className="text-lg font-bold text-slate-900 flex items-center gap-2 mb-1">
          <BookMarked className="w-5 h-5 text-blue-600" />
          Criar Novo Caderno de Questões com Fragmentação
        </h2>
        <p className="text-xs text-slate-600 mb-6 leading-relaxed">
          Monte o seu filtro de estudo por disciplina e lei. Cada artigo selecionado será automaticamente
          decomposto em seus incisos, parágrafos e alíneas com exemplos objetivos.
        </p>

        {successMessage && (
          <div className="mb-6 p-4 rounded-xl bg-emerald-50 text-emerald-900 border border-emerald-200 text-xs font-semibold flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-emerald-600" />
            <span>{successMessage}</span>
          </div>
        )}

        <form onSubmit={handleCreate} className="space-y-5">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1">
                1. Disciplina:
              </label>
              <select
                value={selectedDiscipline}
                onChange={(e) => {
                  setSelectedDiscipline(e.target.value);
                  const firstLaw = SAMPLE_LAWS.find((l) => l.discipline === e.target.value);
                  if (firstLaw) setSelectedLaw(firstLaw.lawName);
                }}
                className="w-full text-xs border border-slate-300 rounded-lg px-3 py-2 bg-slate-50 focus:ring-2 focus:ring-blue-500"
              >
                {disciplines.map((d) => (
                  <option key={d} value={d}>
                    {d}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1">
                2. Legislação:
              </label>
              <select
                value={selectedLaw}
                onChange={(e) => setSelectedLaw(e.target.value)}
                className="w-full text-xs border border-slate-300 rounded-lg px-3 py-2 bg-slate-50 focus:ring-2 focus:ring-blue-500"
              >
                {Array.from(new Set(lawsForDiscipline.map((l) => l.lawName))).map((law) => (
                  <option key={law} value={law}>
                    {law}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-700 mb-2">
              3. Selecione os Artigos (deixe todos marcados para estudo completo):
            </label>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 max-h-48 overflow-y-auto p-3 bg-slate-50 border border-slate-200 rounded-lg">
              {lawsForDiscipline.map((art) => {
                const isChecked = selectedArticles.includes(art.id);
                return (
                  <label
                    key={art.id}
                    className="flex items-center gap-2 p-2 rounded hover:bg-slate-100 cursor-pointer text-xs"
                  >
                    <input
                      type="checkbox"
                      checked={isChecked}
                      onChange={() => handleToggleArticle(art.id)}
                      className="rounded text-blue-600 focus:ring-blue-500"
                    />
                    <span className="font-semibold text-slate-800">{art.articleNumber}</span>
                    <span className="text-slate-500 truncate text-[11px]">
                      — {art.text.slice(0, 50)}...
                    </span>
                  </label>
                );
              })}
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1">
                4. Quantidade de Questões a Gerar:
              </label>
              <input
                type="number"
                min={5}
                max={100}
                value={questionCount}
                onChange={(e) => setQuestionCount(Number(e.target.value))}
                className="w-full text-xs border border-slate-300 rounded-lg px-3 py-2 bg-slate-50"
              />
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1">
                5. Nome do seu Caderno / Filtro:
              </label>
              <input
                type="text"
                required
                placeholder="Ex: CF/88 - Direitos Fundamentais Fragmentados"
                value={notebookName}
                onChange={(e) => setNotebookName(e.target.value)}
                className="w-full text-xs border border-slate-300 rounded-lg px-3 py-2 bg-slate-50"
              />
            </div>
          </div>

          <div className="flex justify-end pt-2">
            <button
              type="submit"
              className="px-5 py-2.5 text-xs font-semibold rounded-lg text-white bg-blue-600 hover:bg-blue-700 flex items-center gap-2 transition-colors cursor-pointer shadow-xs"
            >
              <Plus className="w-4 h-4" />
              <span>Salvar Caderno e Gerar Questões Fragmentadas</span>
            </button>
          </div>
        </form>
      </div>

      {/* Cadernos salvos list */}
      <div className="bg-white border border-slate-200 rounded-xl p-6 shadow-xs">
        <h3 className="text-sm font-bold text-slate-900 mb-3">
          Cadernos Ativos Disponíveis ({availableFilters.length})
        </h3>
        <div className="space-y-2">
          {availableFilters.map((filt, idx) => (
            <div
              key={idx}
              className="flex items-center justify-between p-3 rounded-lg border border-slate-100 bg-slate-50 text-xs"
            >
              <div className="flex items-center gap-3">
                <BookMarked className="w-4 h-4 text-blue-600" />
                <span className="font-semibold text-slate-800">{filt}</span>
              </div>
              <span className="text-[11px] text-slate-500 font-mono">
                Fragmentação Automática Ativa
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};
