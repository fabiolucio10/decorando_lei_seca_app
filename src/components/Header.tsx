import React from 'react';
import { BookOpen, Scale, Sparkles, CheckCircle2 } from 'lucide-react';

interface HeaderProps {
  activeTab: string;
  setActiveTab: (tab: string) => void;
  stats: { total: number; hits: number; errors: number; rate: number };
}

export const Header: React.FC<HeaderProps> = ({ activeTab, setActiveTab, stats }) => {
  const navItems = [
    { id: 'resolver', label: 'Resolver Questões' },
    { id: 'comparador', label: 'Simulador de Fragmentação' },
    { id: 'cadernos', label: 'Cadernos & Filtros' },
    { id: 'codigo', label: 'Código Python (VS Code)' },
    { id: 'desempenho', label: 'Desempenho' },
  ];

  return (
    <header className="border-b border-slate-200 bg-white sticky top-0 z-40">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
        {/* Zone 1: Single text element wordmark */}
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-blue-600 text-white flex items-center justify-center font-bold text-base shadow-sm">
            ⚖
          </div>
          <span className="text-lg font-bold tracking-tight text-slate-900">
            Decorando Lei Seca
          </span>
          <span className="text-xs text-slate-400 hidden sm:inline">· Fragmentação Inteligente</span>
        </div>

        {/* Zone 2: 4-6 text navigation tabs */}
        <nav className="hidden md:flex items-center gap-1 sm:gap-2">
          {navItems.map((item) => {
            const isActive = activeTab === item.id;
            return (
              <button
                key={item.id}
                onClick={() => setActiveTab(item.id)}
                className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors whitespace-nowrap ${
                  isActive
                    ? 'bg-slate-100 text-slate-900 font-semibold'
                    : 'text-slate-600 hover:text-slate-900 hover:bg-slate-50'
                }`}
              >
                {item.label}
              </button>
            );
          })}
        </nav>

        {/* Zone 3: Quick metrics / actions */}
        <div className="flex items-center gap-4 text-xs">
          <div className="hidden sm:flex items-center gap-3 text-slate-600">
            <span>
              Respondidas: <strong className="font-mono tabular-nums text-slate-900">{stats.total}</strong>
            </span>
            <span aria-hidden="true" className="text-slate-300">·</span>
            <span>
              Aproveitamento:{' '}
              <strong className="font-mono tabular-nums text-emerald-700">
                {stats.rate.toFixed(1)}%
              </strong>
            </span>
          </div>

          <button
            onClick={() => setActiveTab('resolver')}
            className="px-3.5 py-1.5 text-xs font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors whitespace-nowrap shadow-sm"
          >
            Treinar Agora
          </button>
        </div>
      </div>

      {/* Mobile navigation bar */}
      <div className="md:hidden flex overflow-x-auto px-4 py-2 border-t border-slate-100 gap-2 bg-slate-50">
        {navItems.map((item) => {
          const isActive = activeTab === item.id;
          return (
            <button
              key={item.id}
              onClick={() => setActiveTab(item.id)}
              className={`px-3 py-1 text-xs font-medium rounded-md whitespace-nowrap ${
                isActive ? 'bg-blue-600 text-white' : 'text-slate-600 bg-white border border-slate-200'
              }`}
            >
              {item.label}
            </button>
          );
        })}
      </div>
    </header>
  );
};
