import React from 'react';
import { BarChart3, CheckCircle2, XCircle, RotateCcw, Clock, Target } from 'lucide-react';

interface PerformanceDashboardProps {
  stats: {
    total: number;
    hits: number;
    errors: number;
    rate: number;
  };
  onResetStats: () => void;
  activeNotebookCount: number;
}

export const PerformanceDashboard: React.FC<PerformanceDashboardProps> = ({
  stats,
  onResetStats,
  activeNotebookCount,
}) => {
  return (
    <div className="max-w-5xl mx-auto space-y-6">
      {/* Header */}
      <div className="bg-white border border-slate-200 rounded-xl p-6 shadow-xs flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-lg font-bold text-slate-900 flex items-center gap-2">
            <BarChart3 className="w-5 h-5 text-blue-600" />
            Desempenho & Estatísticas de Memorização
          </h2>
          <p className="text-xs text-slate-600 mt-1">
            Acompanhe a sua taxa de acerto e evolução nos dispositivos fragmentados de lei seca.
          </p>
        </div>

        <button
          onClick={onResetStats}
          className="self-start sm:self-auto px-3.5 py-1.5 text-xs font-semibold rounded-lg border border-slate-200 text-slate-600 hover:text-rose-600 hover:border-rose-300 transition-colors flex items-center gap-1.5 cursor-pointer"
        >
          <RotateCcw className="w-3.5 h-3.5" />
          <span>Zerar Estatísticas</span>
        </button>
      </div>

      {/* 4 Metric cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-xs">
          <div className="text-xs font-medium text-slate-500 mb-1">Total Respondidas</div>
          <div className="text-2xl font-bold font-mono tabular-nums text-slate-900">
            {stats.total}
          </div>
          <div className="text-[11px] text-slate-400 mt-1">questões avaliadas</div>
        </div>

        <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-xs">
          <div className="text-xs font-medium text-slate-500 mb-1 flex items-center gap-1">
            <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" />
            Acertos
          </div>
          <div className="text-2xl font-bold font-mono tabular-nums text-emerald-600">
            {stats.hits}
          </div>
          <div className="text-[11px] text-emerald-700/80 mt-1">itens gabaritados</div>
        </div>

        <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-xs">
          <div className="text-xs font-medium text-slate-500 mb-1 flex items-center gap-1">
            <XCircle className="w-3.5 h-3.5 text-rose-600" />
            Erros
          </div>
          <div className="text-2xl font-bold font-mono tabular-nums text-rose-600">
            {stats.errors}
          </div>
          <div className="text-[11px] text-rose-700/80 mt-1">pegadinhas identificadas</div>
        </div>

        <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-xs">
          <div className="text-xs font-medium text-slate-500 mb-1 flex items-center gap-1">
            <Target className="w-3.5 h-3.5 text-blue-600" />
            Aproveitamento
          </div>
          <div className="text-2xl font-bold font-mono tabular-nums text-blue-700">
            {stats.rate.toFixed(1)}%
          </div>
          <div className="text-[11px] text-blue-600/80 mt-1">meta recomendada: &gt; 80%</div>
        </div>
      </div>

      {/* Progress visual bar */}
      <div className="bg-white border border-slate-200 rounded-xl p-6 shadow-xs space-y-3">
        <div className="flex items-center justify-between text-xs font-semibold text-slate-700">
          <span>Proporção de Acertos vs Erros</span>
          <span className="font-mono tabular-nums text-slate-500">
            {stats.hits} acertos / {stats.errors} erros
          </span>
        </div>
        <div className="w-full h-3 bg-slate-100 rounded-full overflow-hidden flex">
          <div
            className="bg-emerald-500 h-full transition-all duration-500"
            style={{ width: `${stats.total > 0 ? (stats.hits / stats.total) * 100 : 0}%` }}
          ></div>
          <div
            className="bg-rose-500 h-full transition-all duration-500"
            style={{ width: `${stats.total > 0 ? (stats.errors / stats.total) * 100 : 0}%` }}
          ></div>
        </div>
      </div>

      {/* Spaced repetition review card */}
      <div className="bg-gradient-to-br from-blue-50 to-indigo-50 border border-blue-200/80 rounded-xl p-6 text-xs sm:text-sm text-slate-800 space-y-2">
        <div className="flex items-center gap-2 font-bold text-blue-900">
          <Clock className="w-4 h-4 text-blue-600" />
          <span>Sistema de Repetição Espaçada (SRS) Ativo</span>
        </div>
        <p className="text-slate-600 leading-relaxed">
          Cada vez que você erra uma questão, o dispositivo fragmentado ganha maior prioridade e reaparecerá no seu ciclo
          de estudos nas próximas 24h. Quando você acerta repetidamente, o intervalo é espaçado para 3, 7, 15 e 30 dias.
        </p>
      </div>
    </div>
  );
};
