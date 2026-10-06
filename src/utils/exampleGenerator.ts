import { Question, FragmentedDevice } from '../types/law';

interface PracticalExample {
  situacaoReal: string;
  aplicacaoRegra: string;
  objetivoRegra: string;
  bizu?: string;
}

export function gerarExemploObjetivo(deviceLabel: string, rawText: string): PracticalExample {
  const txt = rawText.toLowerCase();

  // Art. 5º, XVI - Direito de Reunião pacífica
  if (txt.includes('reunir') || txt.includes('reunião') || txt.includes('sem armas') || txt.includes('abertos ao público') || txt.includes('prévio aviso')) {
    return {
      situacaoReal: 'Um grupo de estudantes e trabalhadores organiza uma manifestação pacífica em praça pública contra o aumento das tarifas de ônibus. Eles NÃO precisam pedir autorização para a prefeitura ou para a polícia, mas devem apenas emitir um comunicado prévio para evitar que dois grupos usem o mesmo local no mesmo horário e para permitir que as autoridades organizem o trânsito e a segurança.',
      aplicacaoRegra: `• Aplicação no ${deviceLabel}: O direito de reunião é livre e independe de autorização estatal, exigindo-se apenas que seja pacífica, sem armas, em locais abertos ao público, sem frustrar reunião anterior e com prévio aviso à autoridade competente.`,
      objetivoRegra: 'Impedir que o Estado censure manifestações populares pacíficas e garantir a harmonia com o trânsito e a ordem pública.',
      bizu: 'Pegadinha clássica de banca: afirmar que "precisa de prévia autorização da polícia" (ERRADO!) ou que "dispensa prévio aviso" (ERRADO!). É INDEPENDENTE DE AUTORIZAÇÃO, mas EXIGE PRÉVIO AVISO.'
    };
  }

  // Pena de morte, trabalhos forçados, cruéis (Art. 5º, XLVII)
  if (txt.includes('pena de morte') || txt.includes('caráter perpétuo') || txt.includes('cruéis') || txt.includes('trabalhos forçados') || txt.includes('banimento')) {
    return {
      situacaoReal: 'No Brasil, o Código Penal Militar prevê pena de morte por fuzilamento apenas se houver guerra formalmente declarada pelo Presidente com autorização do Congresso Nacional. Em tempo de paz, nenhuma autoridade judicial pode aplicar pena de morte ou de caráter perpétuo.',
      aplicacaoRegra: `• Aplicação no ${deviceLabel}: Impede punições desumanas ou perpétuas no sistema penal brasileiro comum.`,
      objetivoRegra: 'Proteger a dignidade da pessoa humana e evitar punições estatais irreversíveis e cruéis.',
      bizu: 'Banca adora dizer que "não há pena de morte em hipótese alguma" (FALSO, há em caso de guerra declarada) ou que "pena de banimento é permitida" (FALSO, é expressamente vedada).'
    };
  }

  // Estabelecimentos distintos por crime, idade e sexo (Art. 5º, XLVIII)
  if (txt.includes('estabelecimentos distintos') || txt.includes('natureza do delito') || txt.includes('sexo do apenado')) {
    return {
      situacaoReal: 'Um jovem de 19 anos condenado por furto não violento não pode cumprir pena na mesma cela de um reincidente de 45 anos condenado por homicídio e latrocínio, e homens e mulheres devem cumprir penas em alas ou presídios separados.',
      aplicacaoRegra: `• Aplicação no ${deviceLabel}: O Estado é obrigado a individualizar o cumprimento da pena separando os presos por gênero, faixa etária e gravidade do delito cometido.`,
      objetivoRegra: 'Evitar o aliciamento de criminosos primários e resguardar a integridade dos reeducandos.',
      bizu: 'Critérios constitucionais de separação: natureza do delito, idade e sexo do apenado.'
    };
  }

  // Integridade física e moral dos presos (Art. 5º, XLIX)
  if (txt.includes('integridade física e moral') || txt.includes('assegurado aos presos') || txt.includes('respeito à integridade')) {
    return {
      situacaoReal: 'Durante uma revista de rotina em presídio, policiais penais agridem e humilham verbalmente detentos já rendidos e algemados. O Ministério Público ajuizou ação penal e os agentes foram condenados, pois a Constituição assegura que a perda temporária da liberdade não retira do apenado o direito ao respeito absoluto à sua integridade física e moral.',
      aplicacaoRegra: `• Aplicação no ${deviceLabel}: O Estado atua como garantidor compulsório da vida e da integridade física e moral de todas as pessoas presas sob sua custódia.`,
      objetivoRegra: 'Impedir torturas, sevícias e desumanização no cárcere, resguardando a dignidade da pessoa humana.',
      bizu: 'Pegadinha clássica de banca: restringir a garantia apenas à integridade "física" (ERRADO!) ou dizer que a integridade "moral" pode ser suprimida por falta disciplinar (ERRADO!). A garantia é FÍSICA E MORAL.'
    };
  }

  // Presidiárias e amamentação (Art. 5º, L)
  if (txt.includes('presidiária') || txt.includes('amamenta') || txt.includes('filhos')) {
    return {
      situacaoReal: 'Uma detenta dá à luz durante o cumprimento de pena em presídio feminino. O estabelecimento prisional é obrigado por lei a oferecer berçário e creche estruturada para que ela permaneça com o recém-nascido durante todo o período de amamentação.',
      aplicacaoRegra: `• Aplicação no ${deviceLabel}: Garante o direito subjetivo fundamental da mãe e do recém-nascido de permanecerem juntos durante o aleitamento materno.`,
      objetivoRegra: 'Proteger a infância e o desenvolvimento biológico saudável do bebê, independente do crime cometido pela mãe.',
      bizu: 'A garantia beneficia a criança e não pode ser restringida por sanção disciplinar imposta à mãe.'
    };
  }

  // Extradição de brasileiro nato vs naturalizado (Art. 5º, LI)
  if (txt.includes('extradit') || txt.includes('brasileiro nato') || txt.includes('naturalizado')) {
    return {
      situacaoReal: 'Roberto, brasileiro nato, comete assassinato nos EUA e foge para São Paulo. O governo americano solicita sua extradição. O STF nega imediatamente, pois brasileiro nato NUNCA é extraditado (responderá pelo crime na Justiça brasileira). Já Pierre, francês naturalizado brasileiro, pode ser extraditado se tiver cometido crime comum ANTES da naturalização ou se comprovado envolvimento em tráfico de drogas A QUALQUER TEMPO.',
      aplicacaoRegra: `• Aplicação no ${deviceLabel}: Trata de forma expressa a imunidade absoluta do nato e as duas exceções taxativas para o naturalizado.`,
      objetivoRegra: 'Proteger os cidadãos da jurisdição estrangeira e punir com rigor o tráfico ilícito transnacional.',
      bizu: 'Nato NUNCA é extraditado. Naturalizado pode em 2 casos: crime comum ANTES da naturalização OU tráfico de entorpecentes a qualquer tempo.'
    };
  }

  // Proteção de dados pessoais e meios digitais (Art. 5º, LXXIX)
  if (txt.includes('dados pessoais') || txt.includes('meios digitais')) {
    return {
      situacaoReal: 'Uma instituição bancária comercializa o histórico de compras de seus correntistas para agências de publicidade sem o expresso consentimento. O cliente pode acionar o Poder Judiciário fundamentando que a proteção de dados pessoais é garantia constitucional autônoma.',
      aplicacaoRegra: `• Aplicação no ${deviceLabel}: Eleva a privacidade de dados virtuais ao patamar de direito fundamental individual autônomo (Emenda Constitucional 115).`,
      objetivoRegra: 'Garantir a autodeterminação informativa no ambiente cibernético moderno.',
      bizu: 'Incluído pela EC 115/2022, é cláusula pétrea e protege inclusive dados tratados em ambiente digital.'
    };
  }

  // Domicílio e inviolabilidade da casa (Art. 5º, XI)
  if (txt.includes('casa é asilo') || txt.includes('inviolável') || txt.includes('domicílio')) {
    return {
      situacaoReal: 'Policiais desconfiam que há mercadoria contrabandeada em um imóvel. À noite, eles não podem ingressar sem o consentimento do morador, a menos que haja flagrante delito, desastre ou socorro. Durante o dia, com ordem judicial de busca e apreensão, a entrada é lícita mesmo sem permissão.',
      aplicacaoRegra: `• Aplicação no ${deviceLabel}: Limita a atuação policial garantindo a privacidade e a segurança no domicílio.`,
      objetivoRegra: 'Impedir buscas domiciliares abusivas sem controle judicial.',
      bizu: 'Por ordem judicial: SOMENTE DURANTE O DIA. A qualquer hora (dia ou noite): flagrante, desastre ou socorro.'
    };
  }

  // Prisão civil por dívida (Art. 5º, LXVII)
  if (txt.includes('prisão civil') || txt.includes('alimentícia') || txt.includes('depositário infiel')) {
    return {
      situacaoReal: 'Carlos deixa de pagar voluntariamente e sem justificativa 3 parcelas de pensão alimentícia devidas ao filho menor. O juiz decreta a prisão civil de 30 a 90 dias em regime fechado separado dos presos comuns.',
      aplicacaoRegra: `• Aplicação no ${deviceLabel}: Apenas a dívida de alimentos enseja prisão civil no Brasil hoje. O depositário infiel, embora citado no texto da CF, não pode ser preso segundo a Súmula Vinculante 25 do STF.`,
      objetivoRegra: 'Coagir o devedor a honrar a obrigação de subsistência de quem necessita de alimentos.',
      bizu: 'Na letra da lei: pensão e depositário infiel. Na jurisprudência (Súmula Vinculante 25): SOMENTE devedor de alimentos.'
    };
  }

  // Ação popular (Art. 5º, LXXIII)
  if (txt.includes('ação popular') || txt.includes('qualquer cidadão') || txt.includes('patrimônio público')) {
    return {
      situacaoReal: 'Mariana, cidadã em dia com a Justiça Eleitoral, descobre que o prefeito autorizou a demolição irregular de um prédio tombado como patrimônio histórico municipal. Ela protocola uma Ação Popular na Vara da Fazenda Pública para suspender a obra e anular o ato.',
      aplicacaoRegra: `• Aplicação no ${deviceLabel}: Legitimidade ativa exclusiva de "cidadão" (pessoa física com título de eleitor regular). Pessoa jurídica NÃO pode propor Ação Popular.`,
      objetivoRegra: 'Possibilitar o controle popular direto da moralidade administrativa e do patrimônio ambiental e histórico.',
      bizu: 'Isento de custas e sucumbência, SALVO comprovada má-fé. Autor tem que ser eleitor (cidadão).'
    };
  }

  // Competências privativas do Presidente (Art. 84)
  if (txt.includes('presidente da república') || txt.includes('sancionar') || txt.includes('promulgar') || txt.includes('vetar') || txt.includes('decretar')) {
    return {
      situacaoReal: 'O Presidente edita decreto extinguindo cargos públicos vagos sem criar novas despesas nem aumentar atribuições de órgãos. Esse ato é plenamente constitucional pois trata-se de decreto autônomo (Art. 84, VI, "b").',
      aplicacaoRegra: `• Aplicação no ${deviceLabel}: Demarca os atos que apenas o Chefe do Poder Executivo federal pode praticar diretamente.`,
      objetivoRegra: 'Manter a separação dos poderes e o equilíbrio republicano de governança federal.',
      bizu: 'Atenção aos incisos que admitem delegação: VI (organização adm.), XII (indulto) e XXV (prover cargos públicos nos termos da lei).'
    };
  }

  // Crimes hediondos, tortura, tráfico (Art. 5º, XLIII)
  if (txt.includes('tortura') || txt.includes('tráfico') || txt.includes('terrorismo') || txt.includes('hediondos')) {
    return {
      situacaoReal: 'Um investigado por tortura e tráfico de entorpecentes solicita fiança em audiência de custódia e, posteriormente, graça presidencial. O juiz nega de pronto, pois esses crimes são inafiançáveis e insuscetíveis de graça ou anistia.',
      aplicacaoRegra: `• Aplicação no ${deviceLabel}: Estabelece tratamento penal e processual mais rigoroso aos crimes graves (3T + H).`,
      objetivoRegra: 'Desestimular a prática de condutas que atentam gravemente contra bens jurídicos vitais.',
      bizu: '3T + H são INAFIANÇÁVEIS e INSUSCETÍVEIS de graça/anistia (mas NÃO são imprescritíveis; imprescritíveis são Racismo e Ação de grupos armados).'
    };
  }

  // Caso genérico contextualizado e de alto padrão
  return {
    situacaoReal: `Em um processo administrativo ou judicial perante o Tribunal competente, a autoridade pública é estritamente vinculada aos termos deste dispositivo (${deviceLabel}). A desobediência a esse mandamento enseja nulidade do ato e responsabilização formal.`,
    aplicacaoRegra: `• Aplicação no ${deviceLabel}: Fixa procedimento legal de observância cogente, vedando discricionariedade onde a lei determinou regra expressa.`,
    objetivoRegra: 'Assegurar a legalidade estrita, a previsibilidade dos atos públicos e a segurança jurídica.',
    bizu: 'Memorize os termos exatos de dever ("deverá") vs faculdade ("poderá") e os prazos expressos.'
  };
}

export function limparAssertiva(rawText: string): string {
  if (!rawText) return '';
  let t = rawText.trim();
  // Remove marcadores no início como "XLIX - ", "§ 1º - ", "Parágrafo único. ", "a) - "
  t = t.replace(/^(?:(?:M{0,4}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{1,3}))\s*[-–—.]\s*|§\s*\d+º?\s*[-–—.]?\s*|Parágrafo único\s*[-–—.]?\s*|[a-z]\s*[\)\-]\s*)/i, '').trim();
  // Remove pontuação residual no final como ;, : ou vírgula
  t = t.replace(/[\s;:,]+$/, '').trim();
  if (!t) return rawText.trim();
  // Garante primeira letra maiúscula e ponto final
  t = t.charAt(0).toUpperCase() + t.slice(1);
  if (!t.endsWith('.')) {
    t += '.';
  }
  return t;
}

const SUBSTITUICOES_LEI = [
  // Presos e Dignidade (Art. 5º, XLIX, XLVIII, L)
  {
    padrao: /\brespeito à integridade física e moral\b/i,
    sub: 'respeito à integridade física, sendo dispensada a tutela de sua integridade moral',
    desc: 'restrição indevida: a CF/88 assegura expressamente o respeito à integridade física E moral dos presos'
  },
  {
    padrao: /\bintegridade física e moral\b/i,
    sub: 'integridade física, mas não à integridade moral',
    desc: 'restrição indevida: a garantia constitucional abrange tanto a integridade física quanto a moral'
  },
  {
    padrao: /\bé assegurado aos presos o respeito\b/i,
    sub: 'é facultado à administração penitenciária restringir o respeito',
    desc: 'troca indevida de garantia fundamental cogente por faculdade administrativa'
  },
  {
    padrao: /\bestabelecimentos distintos, de acordo com a natureza do delito, a idade e o sexo\b/i,
    sub: 'estabelecimentos unificados, independentemente da natureza do delito, idade ou sexo',
    desc: 'supressão do critério constitucional de separação de presos por delito, idade e sexo'
  },
  {
    padrao: /\bpermanecer com seus filhos durante o período de amamentação\b/i,
    sub: 'permanecer com seus filhos apenas nos primeiros 15 dias de vida, vedada a amamentação no presídio',
    desc: 'supressão da garantia constitucional da presidiária de amamentar seus filhos'
  },

  // Penas e Extradição (Art. 5º, XLVII, LI, LII)
  {
    padrao: /\bsalvo em caso de guerra declarada\b/i,
    sub: 'mesmo em caso de guerra declarada',
    desc: 'supressão da única ressalva constitucional para a pena de morte no Brasil'
  },
  {
    padrao: /\bnenhum brasileiro será extraditado, salvo o naturalizado\b/i,
    sub: 'qualquer brasileiro, inclusive o nato, poderá ser extraditado por crime comum',
    desc: 'violação da imunidade absoluta do brasileiro nato contra extradição'
  },
  {
    padrao: /\bnenhum brasileiro será extraditado\b/i,
    sub: 'o brasileiro nato poderá ser extraditado em caso de tráfico de drogas',
    desc: 'o brasileiro nato NUNCA é extraditado, nem mesmo por tráfico de entorpecentes'
  },

  // Provas Ilícitas e Presunção de Inocência (Art. 5º, LVI, LVII)
  {
    padrao: /\bsão inadmissíveis, no processo, as provas obtidas por meios ilícitos\b/i,
    sub: 'são plenamente admissíveis no processo as provas obtidas por meios ilícitos, desde que úteis à verdade real',
    desc: 'inversão da regra constitucional de inadmissibilidade absoluta das provas ilícitas'
  },
  {
    padrao: /\btrânsito em julgado de sentença penal condenatória\b/i,
    sub: 'confirmação da condenação em julgamento de segundo grau',
    desc: 'antecipação indevida da culpabilidade antes do trânsito em julgado'
  },

  // Prisão Civil e Remédios (Art. 5º, LXVII, LXVIII, LXXIII)
  {
    padrao: /\bnão haverá prisão civil por dívida, salvo a do responsável pelo inadimplemento voluntário e inescusável de obrigação alimentícia e a do depositário infiel\b/i,
    sub: 'é admitida a prisão civil por qualquer dívida bancária ou contratual inadimplida',
    desc: 'generalização indevida da prisão civil, que só cabe para obrigação alimentícia'
  },
  {
    padrao: /\bqualquer cidadão é parte legítima para propor ação popular\b/i,
    sub: 'qualquer pessoa jurídica ou estrangeiro não eleitor é parte legítima para propor ação popular',
    desc: 'ação popular é remédio exclusivo de cidadão (pessoa física no gozo dos direitos políticos)'
  },
  {
    padrao: /\bisen[ts]o de custas judiciais e do ônus da sucumbência\b/i,
    sub: 'sujeito ao recolhimento prévio de custas judiciais e depósito recursal obrigatório',
    desc: 'cobrança indevida em ação popular constitucionalmente gratuita'
  },

  // Prazos e Conectivos Gerais
  { padrao: /\bdeverá\b/i, sub: 'poderá', desc: 'troca de obrigação legal ("deverá") por faculdade ("poderá")' },
  { padrao: /\bpoderá\b/i, sub: 'deverá obrigatoriamente', desc: 'troca de faculdade ("poderá") por imposição obrigatória' },
  { padrao: /\b24 \(vinte e quatro\) horas\b/i, sub: '48 (quarenta e oito) horas', desc: 'alteração de prazo legal de 24h para 48h' },
  { padrao: /\b48 \(quarenta e oito\) horas\b/i, sub: '24 (vinte e quatro) horas', desc: 'alteração de prazo legal de 48h para 24h' },
  { padrao: /\b30 \(trinta\) dias\b/i, sub: '15 (quinze) dias', desc: 'alteração de prazo legal de 30 para 15 dias' },
  { padrao: /\b15 \(quinze\) dias\b/i, sub: '30 (trinta) dias', desc: 'alteração de prazo legal de 15 para 30 dias' },
  { padrao: /\bpermitido\b/i, sub: 'vedado', desc: 'inversão de permissão para proibição taxativa' },
  { padrao: /\bvedado\b/i, sub: 'permitido', desc: 'inversão de proibição para permissão indevida' },
  { padrao: /\bexigido\b/i, sub: 'dispensado', desc: 'troca de exigência legal por dispensa' },
  { padrao: /\bdispensado\b/i, sub: 'exigido', desc: 'troca de dispensa por exigência indevida' },
  { padrao: /\bobrigatório\b/i, sub: 'facultativo', desc: 'troca de dever cogente por faculdade' },
  { padrao: /\bindependentemente de autorização judicial\b/i, sub: 'mediante prévia autorização judicial', desc: 'exigência descabida de autorização judicial prévia' },
  { padrao: /\bindependentemente de autorização\b/i, sub: 'desde que previamente autorizada pela autoridade competente', desc: 'exigência descabida de prévia autorização' },
  { padrao: /\bmediante autorização judicial\b/i, sub: 'independentemente de autorização judicial', desc: 'supressão indevida da reserva de jurisdição' }
];

export function criarQuestaoDeDispositivo(
  device: FragmentedDevice,
  lawName: string = 'Constituição Federal',
  discipline: string = 'Direito Constitucional',
  forcarGabarito?: 1 | 0
): Question {
  const isCorrect = forcarGabarito !== undefined ? forcarGabarito : Math.random() > 0.5 ? 1 : 0;
  const originalText = device.rawText;
  
  // Limpa assertiva sem marcadores romanos para ter leitura fluida e gramatical
  const baseAssertive = limparAssertiva(originalText);
  let statementText = baseAssertive;
  let trickDesc: string | undefined = undefined;

  // Se o dispositivo depende do Caput (ex: Art. 84 Compete privativamente...)
  if (device.caputContext && /compete\s+privativamente/i.test(device.caputContext)) {
    if (!/compete/i.test(statementText)) {
      statementText = `Compete privativamente ao Presidente da República ${statementText.charAt(0).toLowerCase()}${statementText.slice(1)}`;
    }
  }

  if (isCorrect === 0) {
    let replaced = false;
    for (const sub of SUBSTITUICOES_LEI) {
      if (sub.padrao.test(statementText)) {
        statementText = statementText.replace(sub.padrao, sub.sub);
        trickDesc = sub.desc;
        replaced = true;
        break;
      }
    }

    if (!replaced) {
      const inversoesSintaticas = [
        { padrao: /^É assegurado\b/i, sub: 'Não é assegurado', desc: 'inversão da garantia assegurada para negativa' },
        { padrao: /^São assegurados\b/i, sub: 'Não são assegurados', desc: 'inversão da garantia assegurada para negativa' },
        { padrao: /^São invioláveis\b/i, sub: 'Não são invioláveis', desc: 'supressão da inviolabilidade constitucional' },
        { padrao: /^Não haverá\b/i, sub: 'Será admitida a criação de', desc: 'inversão da vedação constitucional expressa' },
        { padrao: /^Nenhum brasileiro\b/i, sub: 'Qualquer brasileiro', desc: 'supressão da garantia constitucional' },
        { padrao: /^Ninguém será\b/i, sub: 'Qualquer pessoa poderá ser', desc: 'supressão de garantia individual' },
        { padrao: /\bnão será\b/i, sub: 'será', desc: 'supressão da partícula negativa "não"' },
        { padrao: /\bnão pode\b/i, sub: 'pode', desc: 'supressão da vedação legal "não pode"' }
      ];

      for (const inv of inversoesSintaticas) {
        if (inv.padrao.test(statementText)) {
          statementText = statementText.replace(inv.padrao, inv.sub);
          trickDesc = inv.desc;
          replaced = true;
          break;
        }
      }
    }

    if (!replaced) {
      const cleanEnd = statementText.replace(/\.$/, '');
      statementText = `${cleanEnd}, ressalvada decisão discricionária em sentido contrário da autoridade administrativa.`;
      trickDesc = 'criação de ressalva discricionária não prevista na literalidade da lei';
    }

    // Garante primeira maiúscula e ponto final
    statementText = statementText.charAt(0).toUpperCase() + statementText.slice(1);
    if (!statementText.endsWith('.')) statementText += '.';
  }

  const ex = gerarExemploObjetivo(device.deviceLabel, originalText);

  const statusText = isCorrect === 1 ? 'O item está CORRETO.' : 'O item está ERRADO.';
  const detail =
    isCorrect === 1
      ? 'O enunciado reproduz fielmente a literalidade e o sentido da lei seca.'
      : `O enunciado alterou a regra legal (${trickDesc || 'modificação substancial de termos'}).`;

  const promptCebraspe = `Com base na **${lawName}** e no disposto no **${device.deviceLabel}**, julgue o item a seguir:\n\n> "${statementText}"`;

  return {
    id: `q-${device.id}-${Date.now()}-${Math.floor(Math.random() * 1000)}`,
    articleId: device.articleId,
    lawName,
    discipline,
    deviceLabel: device.deviceLabel,
    deviceType: device.deviceType,
    originalText,
    statement: promptCebraspe,
    correctAnswer: isCorrect,
    caputText: device.caputContext,
    isShort: device.isShort,
    explanation: {
      statusText,
      detail,
      trickDesc,
      literalText: originalText,
      realSituation: ex.situacaoReal,
      ruleApplication: ex.aplicacaoRegra,
      ruleObjective: ex.objetivoRegra,
      bizu: ex.bizu,
    },
  };
}
