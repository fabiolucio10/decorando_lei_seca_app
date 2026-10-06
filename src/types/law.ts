export interface LawArticle {
  id: string;
  discipline: string;
  lawName: string;
  articleNumber: string;
  text: string;
}

export interface FragmentedDevice {
  id: string;
  articleId: string;
  articleNumber: string;
  deviceLabel: string; // e.g. "Art. 5º, Inciso XLVIII"
  deviceType: 'caput' | 'inciso' | 'paragrafo' | 'alinea' | 'artigo_simples';
  rawText: string;
  charCount: number;
  isShort: boolean;
  caputContext?: string;
}

export interface Question {
  id: string;
  articleId: string;
  lawName: string;
  discipline: string;
  deviceLabel: string;
  deviceType: 'caput' | 'inciso' | 'paragrafo' | 'alinea' | 'artigo_simples';
  originalText: string;
  statement: string;
  correctAnswer: 1 | 0; // 1 = Certo, 0 = Errado
  caputText?: string;
  isShort: boolean;
  explanation: {
    statusText: string;
    detail: string;
    trickDesc?: string;
    literalText: string;
    realSituation: string;
    ruleApplication: string;
    ruleObjective: string;
    bizu?: string;
  };
}

export interface AnswerLog {
  questionId: string;
  userAnswer: 1 | 0;
  isCorrect: boolean;
  timestamp: string;
}

export interface StudyFilter {
  id: string;
  name: string;
  discipline: string;
  lawName: string;
  articleIds: string[];
  totalQuestions: number;
}
