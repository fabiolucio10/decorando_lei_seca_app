import { FragmentedDevice } from '../types/law';

// Regex para algarismos romanos de I a CCC (1 a 300+)
export const REGEX_ROMANO = '(?:M{0,4}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{1,3}))';

export function limparTextoLei(texto: string): string {
  if (!texto) return '';

  const padroesRemover = [
    /\((?:Redação|Incluído|Vigência|Regulamento|Vide)\s+dada?\s+pel[ao][^)]*\)/gi,
    /\((?:Incluído|Restabelecido|Acrescido)\s+pel[ao][^)]*\)/gi,
    /https?:\/\/\S+/gi,
    /\b\d{2}\/\d{2}\/\d{4},\s*\d{2}:\d{2}\b/gi,
    /DEL\d+compilado/gi,
    /\b\d+\/\d+\b/gi,
  ];

  let limpo = texto;
  for (const padrao of padroesRemover) {
    limpo = limpo.replace(padrao, '');
  }

  limpo = limpo.replace(/[ \t]+/g, ' ');
  limpo = limpo.replace(/\n\s*\n/g, '\n');

  return limpo.trim();
}

export function normalizarEstruturaDispositivo(texto: string): string {
  if (!texto) return '';

  let t = texto.replace(/\r/g, '\n');
  t = t.replace(/[ \t]+/g, ' ');

  // Quebra antes de parágrafos
  t = t.replace(/\s+(§\s*\d+º?|Parágrafo único)\s*/gi, '\n$1 ');

  // Quebra antes de incisos romanos (I até LXXIX e além)
  const regexInciso = new RegExp(`\\s+(?=${REGEX_ROMANO}\\s*[-–—.]\\s*)`, 'gi');
  t = t.replace(regexInciso, '\n');

  // Quebra antes de alíneas (a), b), c))
  t = t.replace(/\s+(?=[a-z]\s*[\)\-]\s*)/gi, '\n');

  // Quebra antes de itens numéricos (1., 2.)
  t = t.replace(/(?<=[;])\s+(?=\d+[\)\.-]\s*)/g, '\n');

  t = t.replace(/\n{2,}/g, '\n');
  return t.trim();
}

function ehMarcadorParagrafo(linha: string): boolean {
  return /^(§\s*\d+º?|Parágrafo único)\b/i.test(linha.trim());
}

function ehMarcadorInciso(linha: string): boolean {
  const regex = new RegExp(`^${REGEX_ROMANO}\\s*[-–—.]\\s*`, 'i');
  return regex.test(linha.trim());
}

function ehMarcadorAlinea(linha: string): boolean {
  return /^[a-z]\s*[\)\-]\s*/i.test(linha.trim());
}

interface BlocoExtraido {
  marcador: string | null;
  texto: string;
}

export function extrairBlocos(texto: string, tipo: 'paragrafo' | 'inciso' | 'alinea'): BlocoExtraido[] {
  const linhas = texto.split('\n').map((l) => l.trim()).filter(Boolean);
  if (linhas.length === 0) return [];

  const matcher =
    tipo === 'paragrafo' ? ehMarcadorParagrafo : tipo === 'inciso' ? ehMarcadorInciso : ehMarcadorAlinea;

  const blocos: BlocoExtraido[] = [];
  let atualMarcador: string | null = null;
  let atualTexto: string[] = [];

  for (const linha of linhas) {
    if (matcher(linha)) {
      if (atualMarcador !== null) {
        blocos.push({ marcador: atualMarcador, texto: atualTexto.join(' ').trim() });
      }

      let m: RegExpMatchArray | null = null;
      if (tipo === 'paragrafo') {
        m = linha.match(/^(§\s*\d+º?|Parágrafo único)/i);
      } else if (tipo === 'inciso') {
        m = linha.match(new RegExp(`^(${REGEX_ROMANO}\\s*[-–—.]\\s*)`, 'i'));
      } else {
        m = linha.match(/^([a-z]\s*[\)\-]\s*)/i);
      }

      atualMarcador = m ? m[1].trim() : linha.split(' ')[0];
      const rest = m ? linha.slice(m[0].length).trim() : linha;
      atualTexto = [rest];
    } else {
      if (atualMarcador !== null) {
        atualTexto.push(linha);
      } else {
        blocos.push({ marcador: null, texto: linha });
      }
    }
  }

  if (atualMarcador !== null) {
    blocos.push({ marcador: atualMarcador, texto: atualTexto.join(' ').trim() });
  }

  return blocos.filter((b) => b.texto.trim().length > 0);
}

export function obterCaput(textoCompleto: string): string {
  const normalizado = normalizarEstruturaDispositivo(limparTextoLei(textoCompleto));
  const regexDivisor = new RegExp(`^(?:§\\s*\\d+º?|Parágrafo único\\b|${REGEX_ROMANO}\\s*[-–—.]\\s*)`, 'im');
  const match = normalizado.search(regexDivisor);
  if (match !== -1) {
    const caput = normalizado.slice(0, match).trim();
    return caput.replace(/^Art\.\s*\d+[\w\-]*[.\º\ª]?\s*[-–—]?\s*/i, '').trim();
  }
  return normalizado.replace(/^Art\.\s*\d+[\w\-]*[.\º\ª]?\s*[-–—]?\s*/i, '').trim();
}

/**
 * Fragmenta completamente um artigo extenso em unidades normativas legíveis,
 * separando Caput, Incisos (I a LXXIX+), Parágrafos e Alíneas.
 */
export function fracionarArtigo(
  artigoNumero: string,
  textoOriginal: string,
  artigoId: string = '1'
): FragmentedDevice[] {
  const limpo = limparTextoLei(textoOriginal);
  const texto = normalizarEstruturaDispositivo(limpo);
  const caputGeral = obterCaput(texto);

  const paragrafos = extrairBlocos(texto, 'paragrafo');
  const incisos = extrairBlocos(texto, 'inciso');

  // Caso 1: Artigo simples sem incisos nem parágrafos
  if (paragrafos.length === 0 && incisos.length === 0) {
    const charCount = limpo.length;
    return [
      {
        id: `${artigoId}-caput`,
        articleId: artigoId,
        articleNumber: artigoNumero,
        deviceLabel: `${artigoNumero} (caput)`,
        deviceType: 'caput',
        rawText: limpo,
        charCount,
        isShort: charCount < 260,
      },
    ];
  }

  const dispositivos: FragmentedDevice[] = [];
  const numerosAdicionados = new Set<string>();

  // 1. Extração do Caput
  const regexPrimeiro = new RegExp(`^(?:§\\s*\\d+º?|Parágrafo único\\b|${REGEX_ROMANO}\\s*[-–—.]\\s*)`, 'im');
  const posPrimeiro = texto.search(regexPrimeiro);
  let caputTexto = posPrimeiro !== -1 ? texto.slice(0, posPrimeiro).trim() : texto;
  caputTexto = caputTexto.replace(/^Art\.\s*\d+[\w\-]*[.\º\ª]?\s*[-–—]?\s*/i, '').trim();

  if (caputTexto && caputTexto.length > 8) {
    const label = `${artigoNumero} (caput)`;
    dispositivos.push({
      id: `${artigoId}-caput`,
      articleId: artigoId,
      articleNumber: artigoNumero,
      deviceLabel: label,
      deviceType: 'caput',
      rawText: caputTexto,
      charCount: caputTexto.length,
      isShort: caputTexto.length < 260,
    });
    numerosAdicionados.add(label);
  }

  // 2. Extração dos Incisos do Caput (antes do primeiro parágrafo)
  const posParagrafo = texto.search(/^(?:§\s*\d+º?|Parágrafo único)\b/im);
  const trechoIncisosCaput = posParagrafo !== -1 ? texto.slice(0, posParagrafo) : texto;
  const incisosDoCaput = extrairBlocos(trechoIncisosCaput, 'inciso');

  for (const { marcador, texto: txtInciso } of incisosDoCaput) {
    if (!marcador || !txtInciso) continue;
    const marcLimpo = marcador.replace(/[-–—.]/g, '').trim();
    const label = `${artigoNumero}, Inciso ${marcLimpo}`;

    // Verifica se o inciso possui alíneas internas e se é longo (> 250 caracteres)
    const alineas = extrairBlocos(normalizarEstruturaDispositivo(txtInciso), 'alinea');
    if (alineas.length > 0 && txtInciso.length > 250) {
      // Adiciona cada alínea fragmentada
      for (const al of alineas) {
        if (!al.marcador) continue;
        const alLabel = `${label}, alínea ${al.marcador.replace(/[\)\-]/g, '').trim()}`;
        const rawContent = `${al.marcador} ${al.texto}`.trim();
        dispositivos.push({
          id: `${artigoId}-${marcLimpo}-${al.marcador}`,
          articleId: artigoId,
          articleNumber: artigoNumero,
          deviceLabel: alLabel,
          deviceType: 'alinea',
          rawText: rawContent,
          charCount: rawContent.length,
          isShort: rawContent.length < 260,
          caputContext: caputGeral,
        });
        numerosAdicionados.add(alLabel);
      }
    } else {
      const rawContent = `${marcador} ${txtInciso}`.trim();
      dispositivos.push({
        id: `${artigoId}-inc-${marcLimpo}`,
        articleId: artigoId,
        articleNumber: artigoNumero,
        deviceLabel: label,
        deviceType: 'inciso',
        rawText: rawContent,
        charCount: rawContent.length,
        isShort: rawContent.length < 260,
        caputContext: caputGeral,
      });
      numerosAdicionados.add(label);
    }
  }

  // 3. Extração dos Parágrafos
  for (const { marcador: marcPar, texto: txtPar } of paragrafos) {
    if (!marcPar || !txtPar) continue;
    const txtParNorm = normalizarEstruturaDispositivo(txtPar);
    const incisosDoPar = extrairBlocos(txtParNorm, 'inciso');
    const alineasDoPar = extrairBlocos(txtParNorm, 'alinea');

    if (incisosDoPar.length > 0 && txtPar.length > 250) {
      for (const inc of incisosDoPar) {
        if (!inc.marcador) continue;
        const subLabel = `${artigoNumero}, ${marcPar}, Inciso ${inc.marcador.replace(/[-–—.]/g, '').trim()}`;
        const rawContent = `${inc.marcador} ${inc.texto}`.trim();
        dispositivos.push({
          id: `${artigoId}-par-${marcPar}-${inc.marcador}`,
          articleId: artigoId,
          articleNumber: artigoNumero,
          deviceLabel: subLabel,
          deviceType: 'inciso',
          rawText: rawContent,
          charCount: rawContent.length,
          isShort: rawContent.length < 260,
          caputContext: caputGeral,
        });
        numerosAdicionados.add(subLabel);
      }
    } else if (alineasDoPar.length > 0 && txtPar.length > 250) {
      for (const al of alineasDoPar) {
        if (!al.marcador) continue;
        const subLabel = `${artigoNumero}, ${marcPar}, alínea ${al.marcador.replace(/[\)\-]/g, '').trim()}`;
        const rawContent = `${al.marcador} ${al.texto}`.trim();
        dispositivos.push({
          id: `${artigoId}-par-${marcPar}-${al.marcador}`,
          articleId: artigoId,
          articleNumber: artigoNumero,
          deviceLabel: subLabel,
          deviceType: 'alinea',
          rawText: rawContent,
          charCount: rawContent.length,
          isShort: rawContent.length < 260,
          caputContext: caputGeral,
        });
        numerosAdicionados.add(subLabel);
      }
    } else {
      const parLabel = `${artigoNumero}, ${marcPar}`;
      const rawContent = `${marcPar} ${txtPar}`.trim();
      dispositivos.push({
        id: `${artigoId}-par-${marcPar}`,
        articleId: artigoId,
        articleNumber: artigoNumero,
        deviceLabel: parLabel,
        deviceType: 'paragrafo',
        rawText: rawContent,
        charCount: rawContent.length,
        isShort: rawContent.length < 260,
        caputContext: caputGeral,
      });
      numerosAdicionados.add(parLabel);
    }
  }

  // 4. Varredura de segurança para incisos posteriores
  const todosIncisos = extrairBlocos(texto, 'inciso');
  for (const { marcador, texto: txtInciso } of todosIncisos) {
    if (!marcador || !txtInciso) continue;
    const marcLimpo = marcador.replace(/[-–—.]/g, '').trim();
    const label = `${artigoNumero}, Inciso ${marcLimpo}`;
    if (!numerosAdicionados.has(label)) {
      const rawContent = `${marcador} ${txtInciso}`.trim();
      dispositivos.push({
        id: `${artigoId}-inc-${marcLimpo}`,
        articleId: artigoId,
        articleNumber: artigoNumero,
        deviceLabel: label,
        deviceType: 'inciso',
        rawText: rawContent,
        charCount: rawContent.length,
        isShort: rawContent.length < 260,
        caputContext: caputGeral,
      });
      numerosAdicionados.add(label);
    }
  }

  return dispositivos.length > 0
    ? dispositivos
    : [
        {
          id: `${artigoId}-full`,
          articleId: artigoId,
          articleNumber: artigoNumero,
          deviceLabel: artigoNumero,
          deviceType: 'artigo_simples',
          rawText: limpo,
          charCount: limpo.length,
          isShort: limpo.length < 260,
        },
      ];
}
