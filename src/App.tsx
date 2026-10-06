import React, { useState, useMemo } from 'react';
import { SAMPLE_LAWS } from './data/sampleLaws';
import { fracionarArtigo } from './utils/fragmentation';
import { criarQuestaoDeDispositivo } from './utils/exampleGenerator';
import { Question } from './types/law';
import { Header } from './components/Header';
import { QuestionSolver } from './components/QuestionSolver';
import { FragmentationLab } from './components/FragmentationLab';
import { PythonCodeViewer } from './components/PythonCodeViewer';
import { NotebookCreator } from './components/NotebookCreator';
import { PerformanceDashboard } from './components/PerformanceDashboard';

export default function App() {
  const [activeTab, setActiveTab] = useState<string>('resolver');
  const [activeFilterName, setActiveFilterName] = useState<string>(
    'CF/88 - Art. 5º Direitos Fundamentais (79 Incisos Fragmentados)'
  );

  // Stats state
  const [stats, setStats] = useState({
    total: 0,
    hits: 0,
    errors: 0,
    rate: 0,
  });

  // Pre-generate questions for standard filters
  const [cadernosState, setCadernosState] = useState<{ [name: string]: Question[] }>(() => {
    const art5 = SAMPLE_LAWS.find((l) => l.id === 'cf-art5')!;
    const art84 = SAMPLE_LAWS.find((l) => l.id === 'cf-art84')!;
    const art37 = SAMPLE_LAWS.find((l) => l.id === 'cf-art37')!;
    const art13b = SAMPLE_LAWS.find((l) => l.id === 'cpp-art13b')!;

    // Art 5 fragmentado
    const devsArt5 = fracionarArtigo(art5.articleNumber, art5.text, art5.id);
    const questionsArt5 = devsArt5.map((d, idx) =>
      criarQuestaoDeDispositivo(d, art5.lawName, art5.discipline, idx % 2 === 0 ? 1 : 0)
    );

    // Art 84 fragmentado
    const devsArt84 = fracionarArtigo(art84.articleNumber, art84.text, art84.id);
    const questionsArt84 = devsArt84.map((d, idx) =>
      criarQuestaoDeDispositivo(d, art84.lawName, art84.discipline, idx % 2 === 0 ? 1 : 0)
    );

    // Art 37 fragmentado
    const devsArt37 = fracionarArtigo(art37.articleNumber, art37.text, art37.id);
    const questionsArt37 = devsArt37.map((d, idx) =>
      criarQuestaoDeDispositivo(d, art37.lawName, art37.discipline, idx % 2 === 0 ? 1 : 0)
    );

    // CPP fragmentado
    const devsCpp = fracionarArtigo(art13b.articleNumber, art13b.text, art13b.id);
    const questionsCpp = devsCpp.map((d, idx) =>
      criarQuestaoDeDispositivo(d, art13b.lawName, art13b.discipline, idx % 2 === 0 ? 1 : 0)
    );

    return {
      'CF/88 - Art. 5º Direitos Fundamentais (79 Incisos Fragmentados)': questionsArt5,
      'CF/88 - Art. 84 Competências do Presidente (Fragmentado)': questionsArt84,
      'CF/88 - Art. 37 Administração Pública': questionsArt37,
      'CPP - Art. 13-B Localização e Telecomunicações': questionsCpp,
    };
  });

  const availableFilters = Object.keys(cadernosState);
  const currentQuestions = cadernosState[activeFilterName] || cadernosState[availableFilters[0]] || [];

  const handleAnswerQuestion = (questionId: string, answer: 1 | 0, isCorrect: boolean) => {
    setStats((prev) => {
      const newTotal = prev.total + 1;
      const newHits = prev.hits + (isCorrect ? 1 : 0);
      const newErrors = prev.errors + (isCorrect ? 0 : 1);
      const newRate = newTotal > 0 ? (newHits / newTotal) * 100 : 0;
      return {
        total: newTotal,
        hits: newHits,
        errors: newErrors,
        rate: newRate,
      };
    });
  };

  const handleResetStats = () => {
    setStats({ total: 0, hits: 0, errors: 0, rate: 0 });
  };

  const handleCreateNotebook = (
    name: string,
    discipline: string,
    lawName: string,
    articleIds: string[],
    questionCount: number
  ) => {
    const selectedArticles = SAMPLE_LAWS.filter((l) => articleIds.includes(l.id));
    const allDevices = selectedArticles.flatMap((art) =>
      fracionarArtigo(art.articleNumber, art.text, art.id)
    );

    const generatedQs: Question[] = [];
    for (let i = 0; i < questionCount; i++) {
      const dev = allDevices[i % allDevices.length];
      generatedQs.push(
        criarQuestaoDeDispositivo(dev, lawName, discipline, i % 2 === 0 ? 1 : 0)
      );
    }

    setCadernosState((prev) => ({
      ...prev,
      [name]: generatedQs,
    }));
    setActiveFilterName(name);
    setActiveTab('resolver');
  };

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 flex flex-col font-sans">
      <Header
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        stats={stats}
      />

      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {activeTab === 'resolver' && (
          <QuestionSolver
            questions={currentQuestions}
            onAnswerQuestion={handleAnswerQuestion}
            activeFilterName={activeFilterName}
            onFilterChange={setActiveFilterName}
            availableFilters={availableFilters}
          />
        )}

        {activeTab === 'comparador' && <FragmentationLab />}

        {activeTab === 'codigo' && <PythonCodeViewer />}

        {activeTab === 'cadernos' && (
          <NotebookCreator
            onCreateNotebook={handleCreateNotebook}
            availableFilters={availableFilters}
          />
        )}

        {activeTab === 'desempenho' && (
          <PerformanceDashboard
            stats={stats}
            onResetStats={handleResetStats}
            activeNotebookCount={availableFilters.length}
          />
        )}
      </main>

      <footer className="border-t border-slate-200 bg-white py-6 text-center text-xs text-slate-500">
        <div className="max-w-7xl mx-auto px-4 flex flex-col sm:flex-row items-center justify-between gap-2">
          <span>Decorando Lei Seca · Sistema de Memorização e Fragmentação Legal</span>
          <span className="font-mono text-slate-400">Streamlit & Web Edition · 2026</span>
        </div>
      </footer>
    </div>
  );
}
