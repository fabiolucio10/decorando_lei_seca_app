import React, { useState } from 'react';
import { Question } from '../types/law';
import { ChevronRight, RotateCcw, Sparkles, BookOpen, Check, X, AlertTriangle, Lightbulb } from 'lucide-react';

interface QuestionSolverProps {
  questions: Question[];
  onAnswerQuestion: (questionId: string, answer: 1 | 0, isCorrect: boolean) => void;
  activeFilterName: string;
  onFilterChange: (filterName: string) => void;
  availableFilters: string[];
}

export const QuestionSolver: React.FC<QuestionSolverProps> = ({
  questions,
  onAnswerQuestion,
  activeFilterName,
  onFilterChange,
  availableFilters,
}) => {
  const [currentIndex, setCurrentIndex] = useState(0);
  const [selectedAnswer, setSelectedAnswer] = useState<1 | 0 | null>(null);
  const [answeredState, setAnsweredState] = useState<{
    [qId: string]: { answered: boolean; isCorrect: boolean; answer: 1 | 0 };
  }>({});
  const [showCaput, setShowCaput] = useState(false);
  const [isGeneratingAiExample, setIsGeneratingAiExample] = useState(false);
  const [aiExample, setAiExample] = useState<{
    situacaoReal: string;
    aplicacaoRegra: string;
    objetivoRegra: string;
    bizuMemorizacao?: string;
  } | null>(null);

  if (!questions || questions.length === 0) {
    return (
      <div className="bg-white rounded-xl border border-slate-200 p-8 text-center max-w-2xl mx-auto my-12">
        <p className="text-slate-600 mb-4">Nenhuma questão gerada para este caderno no momento.</p>
        <button
          onClick={() => onFilterChange(availableFilters[0] || '')}
          className="px-4 py-2 text-xs font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700"
        >
          Carregar Caderno Padrão
        </button>
      </div>
    );
  }

  const currentQ = questions[currentIndex] || questions[0];
  const isAnswered = Boolean(answeredState[currentQ.id]?.answered);
  const userResult = answeredState[currentQ.id];

  const handleSelectOption = (option: 1 | 0) => {
    if (isAnswered) return;
    setSelectedAnswer(option);
  };

  const handleConfirmAnswer = () => {
    if (selectedAnswer === null || isAnswered) return;
    const isCorrect = selectedAnswer === currentQ.correctAnswer;
    setAnsweredState((prev) => ({
      ...prev,
      [currentQ.id]: { answered: true, isCorrect, answer: selectedAnswer },
    }));
    onAnswerQuestion(currentQ.id, selectedAnswer, isCorrect);
  };

  const handleNext = () => {
    setSelectedAnswer(null);
    setShowCaput(false);
    setAiExample(null);
    if (currentIndex + 1 < questions.length) {
      setCurrentIndex(currentIndex + 1);
    } else {
      setCurrentIndex(0);
    }
  };

  const handleRestart = () => {
    setCurrentIndex(0);
    setSelectedAnswer(null);
    setShowCaput(false);
    setAiExample(null);
    setAnsweredState({});
  };

  const handleGenerateAiExample = async () => {
    setIsGeneratingAiExample(true);
    try {
      const res = await fetch('/api/gerar-exemplo-pratico', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          dispositivo: currentQ.deviceLabel,
          textoLegal: currentQ.originalText,
        }),
      });
      const data = await res.json();
      if (data.data) {
        setAiExample(data.data);
      }
    } catch (err) {
      console.error('Erro ao gerar exemplo com IA:', err);
    } finally {
      setIsGeneratingAiExample(false);
    }
  };

  const isSubDevice =
    currentQ.deviceType === 'inciso' ||
    currentQ.deviceType === 'paragrafo' ||
    currentQ.deviceType === 'alinea';

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      {/* Caderno selector & filter bar */}
      <div className="bg-white border border-slate-200 rounded-xl p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3 shadow-xs">
        <div className="flex items-center gap-3">
          <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
            Caderno Ativo:
          </span>
          <select
            value={activeFilterName}
            onChange={(e) => onFilterChange(e.target.value)}
            className="text-xs font-medium text-slate-800 bg-slate-50 border border-slate-300 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {availableFilters.map((filt) => (
              <option key={filt} value={filt}>
                {filt}
              </option>
            ))}
          </select>
        </div>

        <div className="flex items-center gap-2 text-xs text-slate-500">
          <span>
            {currentQ.discipline} · {currentQ.lawName}
          </span>
        </div>
      </div>

      {/* Main question card */}
      <div className="bg-white border border-slate-200 rounded-xl p-6 sm:p-8 shadow-xs">
        {/* Question progress and header */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between pb-4 border-b border-slate-100 gap-2">
          <div>
            <h2 className="text-lg font-bold text-slate-900">
              Questão {currentIndex + 1} de {questions.length}
            </h2>
            <div className="flex items-center gap-2 mt-1 text-xs text-slate-500">
              <span className="font-semibold text-blue-700">{currentQ.deviceLabel}</span>
              <span aria-hidden="true">·</span>
              <span>
                {currentQ.isShort ? 'Dispositivo Curto' : 'Dispositivo Fragmentado'} (
                <span className="font-mono tabular-nums">{currentQ.originalText.length}</span> caracteres)
              </span>
            </div>
          </div>

          <button
            onClick={handleRestart}
            className="self-start sm:self-auto flex items-center gap-1 text-xs text-slate-500 hover:text-slate-800 transition-colors"
            title="Reiniciar Caderno"
          >
            <RotateCcw className="w-3.5 h-3.5" />
            <span>Reiniciar</span>
          </button>
        </div>

        {/* Optional Caput context accordion for incisos, alíneas e parágrafos */}
        {isSubDevice && currentQ.caputText && (
          <div className="mt-4 bg-slate-50 border border-slate-200/80 rounded-lg p-3 text-xs">
            <div className="flex items-center justify-between">
              <span className="font-medium text-slate-700 flex items-center gap-1.5">
                <BookOpen className="w-3.5 h-3.5 text-blue-600" />
                Artigo Principal (Caput de Referência)
              </span>
              <button
                onClick={() => setShowCaput(!showCaput)}
                className="text-blue-600 hover:text-blue-800 font-medium cursor-pointer"
              >
                {showCaput ? 'Ocultar' : 'Ver Caput'}
              </button>
            </div>
            {showCaput && (
              <p className="mt-2 text-slate-600 italic border-t border-slate-200 pt-2 leading-relaxed">
                "{currentQ.caputText}"
              </p>
            )}
          </div>
        )}

        {/* Question Statement */}
        <div className="my-6">
          <p className="text-xs sm:text-sm font-semibold text-slate-700 mb-2">
            Com base na <span className="text-slate-900 font-bold">{currentQ.lawName}</span> e no dispositivo <span className="text-blue-700 font-bold">{currentQ.deviceLabel}</span>, julgue o item a seguir:
          </p>
          <div className="bg-slate-50/70 border-l-4 border-blue-500 p-4 rounded-r-lg">
            <p className="text-slate-800 text-sm sm:text-base leading-relaxed text-justify font-serif">
              "{(() => {
                const raw = currentQ.statement || '';
                const match = raw.match(/"([^"]+)"/);
                if (match) return match[1];
                return raw
                  .replace(/^Com base na [^:]+:\s*\n*/i, '')
                  .replace(/^De acordo com o [^:]+:\s*\n*/i, '')
                  .replace(/^"|"$/g, '');
              })()}"
            </p>
          </div>
        </div>

        {/* Answer Selection: Certo or Errado */}
        <div className="space-y-3 pt-2">
          <label className="text-xs font-semibold uppercase tracking-wider text-slate-500">
            A sua resposta:
          </label>
          <div className="grid grid-cols-2 gap-4">
            <button
              onClick={() => handleSelectOption(1)}
              disabled={isAnswered}
              className={`p-3.5 rounded-lg border text-sm font-semibold flex items-center justify-center gap-2 transition-all ${
                selectedAnswer === 1
                  ? 'border-emerald-600 bg-emerald-50/80 text-emerald-800 ring-2 ring-emerald-500/20'
                  : 'border-slate-200 hover:border-slate-300 bg-white text-slate-700 hover:bg-slate-50'
              } ${isAnswered ? 'cursor-default' : 'cursor-pointer'}`}
            >
              <Check className="w-4 h-4 text-emerald-600" />
              Certo
            </button>

            <button
              onClick={() => handleSelectOption(0)}
              disabled={isAnswered}
              className={`p-3.5 rounded-lg border text-sm font-semibold flex items-center justify-center gap-2 transition-all ${
                selectedAnswer === 0
                  ? 'border-rose-600 bg-rose-50/80 text-rose-800 ring-2 ring-rose-500/20'
                  : 'border-slate-200 hover:border-slate-300 bg-white text-slate-700 hover:bg-slate-50'
              } ${isAnswered ? 'cursor-default' : 'cursor-pointer'}`}
            >
              <X className="w-4 h-4 text-rose-600" />
              Errado
            </button>
          </div>

          {!isAnswered && (
            <div className="pt-2 flex justify-end">
              <button
                onClick={handleConfirmAnswer}
                disabled={selectedAnswer === null}
                className={`px-5 py-2.5 text-xs font-semibold rounded-lg text-white transition-colors shadow-xs ${
                  selectedAnswer !== null
                    ? 'bg-blue-600 hover:bg-blue-700 cursor-pointer'
                    : 'bg-slate-300 cursor-not-allowed'
                }`}
              >
                Confirmar Resposta
              </button>
            </div>
          )}
        </div>

        {/* Post-answer feedback & rich objective practical example */}
        {isAnswered && (
          <div className="mt-8 pt-6 border-t border-slate-200 space-y-5 animate-fadeIn">
            {/* Answer banner */}
            <div
              className={`p-4 rounded-xl flex items-center gap-3 ${
                userResult?.isCorrect
                  ? 'bg-emerald-50 text-emerald-900 border border-emerald-200'
                  : 'bg-rose-50 text-rose-900 border border-rose-200'
              }`}
            >
              <div
                className={`w-8 h-8 rounded-full flex items-center justify-center font-bold shrink-0 ${
                  userResult?.isCorrect ? 'bg-emerald-600 text-white' : 'bg-rose-600 text-white'
                }`}
              >
                {userResult?.isCorrect ? <Check className="w-5 h-5" /> : <X className="w-5 h-5" />}
              </div>
              <div>
                <p className="font-bold text-sm">
                  {userResult?.isCorrect ? '✨ Parabéns! Resposta Correta!' : '❌ Resposta Incorreta! Fique atento aos detalhes!'}
                </p>
                <p className="text-xs opacity-90 mt-0.5">
                  Gabarito oficial:{' '}
                  <strong>{currentQ.correctAnswer === 1 ? 'CERTO' : 'ERRADO'}</strong>
                  {currentQ.explanation.trickDesc && (
                    <span> — Pegadinha: {currentQ.explanation.trickDesc}</span>
                  )}
                </p>
              </div>
            </div>

            {/* Literal text of law */}
            <div className="bg-slate-50 rounded-lg p-4 border border-slate-200 text-xs sm:text-sm">
              <div className="flex items-center gap-2 font-semibold text-slate-800 mb-1.5">
                <BookOpen className="w-4 h-4 text-blue-600" />
                <span>Dispositivo Literal da Lei Seca ({currentQ.deviceLabel})</span>
              </div>
              <blockquote className="text-slate-700 italic border-l-2 border-blue-400 pl-3 my-1">
                "{currentQ.explanation.literalText}"
              </blockquote>
              {currentQ.caputText && currentQ.caputText.trim() !== currentQ.explanation.literalText.trim() && (
                <div className="mt-2.5 pt-2 border-t border-dashed border-slate-300 text-xs text-slate-600">
                  <span className="font-semibold text-blue-900">📜 Contexto do Artigo Principal (Caput de Origem):</span>
                  <p className="italic mt-0.5 text-slate-700">"{currentQ.caputText}"</p>
                </div>
              )}
            </div>

            {/* The requested Objective Practical Example tailored to the device */}
            <div className="bg-amber-50/60 rounded-xl p-5 border border-amber-200/80 text-xs sm:text-sm space-y-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 font-bold text-amber-900">
                  <Lightbulb className="w-4 h-4 text-amber-600" />
                  <span>Exemplo Prático e Objetivo da Vida Real</span>
                </div>
                <button
                  onClick={handleGenerateAiExample}
                  disabled={isGeneratingAiExample}
                  className="flex items-center gap-1 text-xs text-amber-800 hover:text-amber-950 underline font-medium cursor-pointer"
                  title="Gerar variação com inteligência artificial"
                >
                  <Sparkles className="w-3 h-3 text-amber-600" />
                  {isGeneratingAiExample ? 'Gerando...' : 'Gerar Novo Caso com IA'}
                </button>
              </div>

              <div className="text-slate-800 space-y-2 leading-relaxed">
                <p>
                  <strong>Situação Concreta:</strong>{' '}
                  {aiExample?.situacaoReal || currentQ.explanation.realSituation}
                </p>

                <p className="text-slate-700">
                  <strong>Aplicação Prática:</strong>{' '}
                  {aiExample?.aplicacaoRegra || currentQ.explanation.ruleApplication}
                </p>

                <p className="text-slate-700">
                  <strong>Objetivo da Regra:</strong>{' '}
                  {aiExample?.objetivoRegra || currentQ.explanation.ruleObjective}
                </p>

                {(aiExample?.bizuMemorizacao || currentQ.explanation.bizu) && (
                  <div className="mt-3 pt-2 border-t border-amber-200/60 text-amber-900 font-medium">
                    🎯 <strong>Bizu de Memorização:</strong>{' '}
                    {aiExample?.bizuMemorizacao || currentQ.explanation.bizu}
                  </div>
                )}
              </div>
            </div>

            {/* Next question button */}
            <div className="flex justify-end pt-2">
              <button
                onClick={handleNext}
                className="px-6 py-2.5 text-xs font-semibold rounded-lg text-white bg-blue-600 hover:bg-blue-700 flex items-center gap-2 transition-colors cursor-pointer shadow-xs"
              >
                <span>Próxima Questão</span>
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
