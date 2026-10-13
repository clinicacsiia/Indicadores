# -*- coding: utf-8 -*-
"""Regras de negócio editáveis do modelo: padronização de procedimentos e modalidade derivada.

A origem (planilha 13280) traz o MESMO exame com nomes diferentes (tabelas de operadoras) e nomes truncados.
Na análise de cesta isso dilui os combos, então os nomes equivalentes são unificados aqui.

Somente equivalências EXATAS e óbvias entram em EQUIV (nome de origem -> nome padronizado).
Para desfazer/ajustar uma unificação, edite este arquivo e rode `python gerar_dashboard.py` de novo.
No dashboard também é possível alternar para o nome original (filtro "Nível do item").
"""
import re

EQUIV = {
    'CONSULTA': ['CONSULTA MEDICA'],
    'US TRANSVAGINAL P/ ENDOMETRIOSE': ['USG TRANSVAGINAL PARA DIAGNOSTICO DE ENDOMETRIOSE', 'US TRANSVAGINAL P/ ENDOMETRIOSE', 'TRANSVAGINAL PARA PESQUISA DE ENDOMETRIOSE P'],
    'DENSITOMETRIA ÓSSEA (2 SEGMENTOS)': ['DENSITOMETRIA ÓSSEA - 2 SEGMENTOS (COLUNA E FÊMUR)', 'DENSITOMETRIA ÓSSEA', 'DENSITOMETRIA'],
    'MAMOGRAFIA BILATERAL': ['MAMOGRAFIA BILATERAL', 'MAMOGRAFIA DIGITAL', 'MAMOGRAFIA DIGITAL BILATERAL', 'MAMOGRAFIA CONVENCIONAL BILATERAL'],
    'US MAMAS': ['US MAMAS', 'USG MAMA', 'USG MAMAS', 'ULTRA-SONOGRAFIA MAMARIA BILATERAL'],
    'US TRANSVAGINAL': ['US TRANSVAGINAL (INCLUI ABDOME INFERIOR FEMININO)', 'USG TRANSVAGINAL (INCLUI ABDOME INFERIOR)', 'US TRANSVAGINAL (INCLUI ABDOME INFERIOR FEMININ', 'US PÉLVICA TRANSVAGINAL (INCLUI ABDOME INFERIOR', 'ULTRA-SONOGRAFIA TRANSVAGINAL'],
    'US TRANSVAGINAL COM DOPPLER': ['USG TRANSVAGINAL C/ DOPPLER', 'ULTRA-SOM DOS OVÁRIOS, ÚTERO E ANEXOS COM DO'],
    'US PÉLVICA GINECOLÓGICA': ['USG PELVICA GINECOLOGICO', 'US ABDOME INFERIOR FEMININO (BEXIGA, ÚTERO, OVÁRIO E ANEXOS)'],
    'US ABDOME TOTAL': ['US ABDOME TOTAL (INCLUI PELVE)', 'ULTRA-SONOGRAFIA DE ABDOMEN TOTAL', 'USG ABDÔMEN TOTAL', 'US ABDOMEN TOTAL (INCLUI PELVE E RETROPERITÔNI'],
    'US ABDOME SUPERIOR': ['US ABDOME SUPERIOR (FÍGADO, VIAS BILIARES, VESÍCULA, PÂNCREAS, BAÇO)', 'USG ABDÔMEN SUPERIOR'],
    'US TIREOIDE': ['ULTRA-SONOGRAFIA DE TIREOIDE', 'USG TIREOIDE'],
    'US ESTRUTURAS SUPERFICIAIS': ['US ESTRUTURAS SUPERFICIAIS (CERVICAL OU AXILAS OU MÚSCULO OU TENDÃO)', 'US ESTRUTURAS SUPERFICIAIS (CERVICAL OU AXILAS'],
    'US ARTICULAR': ['US ARTICULAR (POR ARTICULAÇÃO)', 'USG ARTICULAÇÕES', 'ULTRA-SONOGRAFIA DE ARTICULACAO'],
    'US APARELHO URINÁRIO': ['ULTRA-SONOGRAFIA DE APARELHO URINARIO', 'US APARELHO URINÁRIO (RINS, URETERES E BEXIGA)', 'USG AP. URINÁRIO', 'US APARELHO URINÁRIO FEMININO (RINS, URETERES E'],
    'US OBSTÉTRICA': ['US OBSTÉTRICA', 'USG OBSTÉTRICO SIMPLES', 'USG OBSTÉTRICO 2º/3º T'],
    'US OBSTÉTRICA COM DOPPLER': ['US OBSTÉTRICA CONVENCIONAL COM DOPPLER COLO', 'US OBSTÉTRICA CONVENCIONAL COM DOPPLER COLORIDO', 'USG OBSTÉTRICO C/ DOPPLER'],
    'US OBSTÉTRICA MORFOLÓGICA': ['US OBSTÉTRICA MORFOLÓGICA', 'USG MORFOLÓGICO OBST 1º TRIM C/ DOPPLER', 'USG MORFOLOGICO OBST 2º TRIM C/ DOPPLER', 'USG MORFOLÓGICO OBST 2º TRIM'],
    'US OBSTÉTRICA 1º TRIMESTRE': ['USG OBSTÉTRICO 1º T', 'US OBSTÉTRICA 1º TRIMESTRE (ENDOVAGINAL)'],
    'US TRANSFONTANELA': ['USG TRANSFONTANELA', 'ULTRA-SONOGRAFIA TRANSFONTANELA'],
    'DOPPLER COLORIDO DE ÓRGÃO OU ESTRUTURA ISOLADA': ['DOPPLER COLORIDO DE ÓRGÃO OU ESTRUTURA ISOLADA (INCLUI CORAÇÃO)', 'DOPPLER CONVENCIONAL ORGAO/ESTRUTURA ISOLAD'],
    'DOPPLER DE CARÓTIDAS E VERTEBRAIS': ['DOPPLER CAROTIDAS E VERTEBRAIS', 'DOPPLER COLORIDO DE VASOS CERVICAIS ARTERIAIS BILATERAL (CARÓTIDAS'],
    'DOPPLER TRANSCRANIANO': ['DOPPLER COLORIDO TRANSCRANIANO', 'DOPPLER COLORIDO TRANSCRANIANO OU TRANSFONTANELA', 'ECODOPPLER TRANSCRANIANO'],
    'DOPPLER ARTERIAL DE MEMBRO INFERIOR': ['DOPPLER COLORIDO ARTERIAL DE MEMBRO INFERIOR - UNILATERAL', 'DOPPLER ARTERIAL MMII (CADA PERNA)'],
    'DOPPLER VENOSO DE MEMBRO INFERIOR': ['DOPPLER COLORIDO VENOSO DE MEMBRO INFERIOR - UNILATERAL', 'DOPPLER VENOSO MMII (CADA PERNA)'],
    'ELETROCARDIOGRAMA (ECG)': ['ECG CONVENCIONAL DE ATÉ 12 DERIVAÇÕES', 'ELETROCARDIOGRAMA - ECG', 'ELETROCARDIOGRAMA PEDIÁTRICO (CSI)'],
    'ELETROENCEFALOGRAMA (EEG)': ['ELETROENCEFALOGRAMA COM MAPEAMENTO CEREBRAL', 'ELETROENCEFALOGRAMA (MAPEAMENTO OU SONO/VIGÍLIA) COM SEDAÇÃO', 'ELETROENCEFALOGRAMA EM SONO E VIGÍLIA, ANALÓG', 'ELETROENCEFALOGRAMA EM SONO E VIGÍLIA'],
    'RX TÓRAX PA': ['RX TÓRAX PA (01 INCIDÊNCIA)', 'RX TÓRAX PA'],
    'RX ESÔFAGO-ESTÔMAGO-DUODENO': ['EREED RX ESOFAGO - HIATO - ESTOMAGO E DUODENO', 'RX ESÔFAGO - HIATO - ESTÔMAGO E DUODENO'],
    'ENEMA OPACO': ['CLISTER OU ENEMA OPACO (DUPLO CONTRASTE)', 'ENEMA OPACO'],
    'RX TRÂNSITO CÓLICO': ['RX TRÂNSITO COLÔNICO', 'RX DE TRÂNSITO CÓLICO SIMPLES', 'RX DE TRÂNSITO CÓLICO SEGMENTADO'],
    'RM COLUNA CERVICAL': ['RM DA COLUNA CERVICAL', 'RM COLUNA CERVICAL'],
    'RM CRÂNIO': ['RM DE CRÂNIO', 'RM CRÂNIO (ENCÉFALO)'],
    'RM ABDOME SUPERIOR': ['RM ABDOMEN SUPERIOR', 'RM ABDOME SUPERIOR (FÍGADO, PÂNCREAS, BAÇO, RINS, SUPRA-RENAIS, RETRO'],
    'RM BACIA (SACROILÍACAS)': ['RM BACIA (ARTICULAÇÕES SACROILÍACAS)', 'RM ARTICULAÇÕES BACIA (SACRO ILIACAS/INCLUI ATR'],
    'RM MAMA (BILATERAL)': ['RM DE MAMA (BILATERAL)', 'RM MAMA (BILATERAL)'],
    'RM ATM (BILATERAL)': ['RM DE ATM (BILATERAL)', 'RM ARTICULAÇÃO TEMPOROMANDIBULAR (BILATERAL)'],
    'RM CORAÇÃO (MORFOLÓGICO E FUNCIONAL)': ['RM CORAÇÃO - MORFOLÓGICO E FUNCIONAL', 'RNM DO CORAÇÃO - MORFOLÓGICO E FUNCIONAL'],
    'ANGIO-RM ARTERIAL DE CRÂNIO': ['ANGIO RM ARTERIAL CRANIO', 'ANGIO-RM ARTERIAL DE CRÂNIO'],
    'CONTRASTE RM': ['CONTRASTE RM - AMOR SAÚDE'],
    'CONTRASTE TC': ['CONTRASTE TC - AMOR SAÚDE', 'CONTRASTE TC'],
    'TC ABDOME TOTAL': ['TC ABDOME TOTAL (ABDOME SUPERIOR, PELVE E RETROPERITÔNIO)', 'TC DO ABDOME TOTAL (ABDOME SUPERIOR, PELVE E R'],
    'TC CRÂNIO': ['TC CRÂNIO OU SELA TÚRSICA OU ÓRBITAS', 'TC DO CRÂNIO'],
    'RX PÉ': ['RX PÉ OU PODODÁCTILO', 'RX PÉ DIREITO', 'RX PÉ ESQUERDO'],
    'RX MÃO': ['RX MÃO OU QUIRODÁCTILO', 'RX MÃO ESQUERDA', 'RX MÃO DIREITA'],
    'RX TORNOZELO': ['RX TORNOZELO ESQUERDO', 'RX TORNOZELO DIREITO', 'RX ARTICULAÇÃO TIBIOTÁRSICA (TORNOZELO)'],
    'RX PUNHO': ['RX PUNHO ESQUERDO', 'RX PUNHO DIREITO', 'RX PUNHO'],
    'RX COLUNA CERVICAL': ['RX COLUNA CERVICAL - 3 INCIDÊNCIAS', 'RX COLUNA CERVICAL'],
    'RX COLUNA LOMBO-SACRA': ['RX COLUNA LOMBO-SACRA -3 INCIDÊNCIAS', 'RX COLUNA LOMBO-SACRA - 5 INCIDÊNCIAS'],
    'RX COLUNA DORSAL': ['RX COLUNA DORSAL', 'RX COLUNA DORSAL - 2 INCIDÊNCIAS', 'RX COLUNA DORSAL - 4 INCIDÊNCIAS'],
    'RX ESCANOMETRIA': ['RX ESCANOMETRIA', 'ESCANOMETRIA'],
    'RX SEIOS DA FACE': ['RX SEIOS DA FACE 02 INCIDÊNCIAS', 'RX SEIOS DA FACE'],
    'RX ADENÓIDES / CAVUM': ['RX ADENÓIDES OU CAVUM', 'RX CAVUM'],
    'RX ABDOME SIMPLES': ['RX ABDOMEN SIMPLES', 'RX ABDÔMEN'],
    'COLPOSCOPIA': ['COLPOSCOPIA (CÉRVICE UTERINA E VAGINA)', 'COLPOSCOPIA'],
}

PADRAO = {}
for _canon, _origs in EQUIV.items():
    for _o in _origs:
        assert _o not in PADRAO or PADRAO[_o] == _canon, f'nome duplicado em EQUIV: {_o}'
        PADRAO[_o] = _canon


def padroniza(nome):
    return PADRAO.get(nome, nome)


# Modalidade derivada (a origem traz "Grupo do Procedimento" 100% vazio). Ordem importa: primeira regra que casar.
MODALIDADES = ['Consultas e avaliações', 'Ultrassonografia', 'Doppler', 'Ressonância', 'Tomografia',
               'Raio-X e contrastados', 'Mamografia', 'Densitometria', 'Cardio e neuro funcional',
               'Ginecologia (procedimentos)', 'Apoio (anestesia e contraste)']

_REGRAS_MODALIDADE = [
    ('Consultas e avaliações', ('CONSULTA', 'ATENDIMENTO AMBULATORIAL', 'TESTE DO DESENVOLVIMENTO')),
    ('Apoio (anestesia e contraste)', ('ANESTESIA', 'CONTRASTE', 'BISNAGA', 'PCTE EXCEPCIONAL')),
    ('Mamografia', ('MAMOGRAFIA', 'COMPRESSÃO LOCALIZADA')),
    ('Densitometria', ('DENSITOMETRIA',)),
    ('Cardio e neuro funcional', ('ECG', 'ELETROCARDIOGRAMA', 'ELETROENCEFALOGRAMA', 'EEGQ', 'OXIMETRIA', 'ECODOPPLERCARDIOGRAMA', 'ECOCARDIOGRAMA')),
    ('Ginecologia (procedimentos)', ('PREVENTIVO', 'COLPOSCOPIA', 'VULVOSCOPIA', 'COLETA DE MATERIAL', 'EXAME A FRESCO', 'GENOTIPAGEM', 'BIÓPSIA', 'CAUTERIZA', 'HISTEROSCOPIA')),
    ('Doppler', ('DOPPLER', 'ECODOPPLER TRANSCRANIANO')),
    ('Ressonância', ('RM ', 'RM-', 'RNM', 'ANGIO RM', 'ANGIO-RM', 'ARTRO-RM', 'HIDRO-RM', 'PCTE RM', 'ESTUDO FUNCIONAL')),
    ('Tomografia', ('TC ', 'ANGIOTOMOGRAFIA', 'PCTE TC')),
    ('Raio-X e contrastados', ('RX', 'EREED', 'ENEMA', 'CLISTER', 'URETROCISTOGRAFIA', 'HISTEROSSALPINGOGRAFIA', 'ESCANOMETRIA', 'INCIDÊNCIA ADICIONAL')),
    ('Ultrassonografia', ('US ', 'USG', 'ULTRA-SONOGRAFIA', 'ULTRA-SOM', 'TRANSVAGINAL', 'HISTEROSSONOSSALPINGOGRAFIA', 'ELASTOGRAFIA', 'OBSTÉTRICA:')),
]


def modalidade(nome_padronizado):
    u = nome_padronizado.upper()
    for mod, prefixos in _REGRAS_MODALIDADE:
        if u.startswith(prefixos):
            return mod
    return 'Outros'


def titulo(txt):
    """Title Case para nomes próprios (operadoras): 'HOSPITAL SANTA IZABEL' -> 'Hospital Santa Izabel'."""
    sufixo = ''
    if txt.upper().endswith(' S/A'):
        txt, sufixo = txt[:-4], ' S/A'
    partes = re.split(r'([\s/\-\(\),:]+)', txt)
    out, primeiro = [], True
    for p in partes:
        if not p or re.fullmatch(r'[\s/\-\(\),:]+', p):
            out.append(p)
            continue
        u = p.upper()
        if u in _SIGLAS:
            out.append(u)
        elif u in _LIGACOES and not primeiro:
            out.append(p.lower())
        else:
            out.append(p[:1].upper() + p[1:].lower())
        primeiro = False
    return ''.join(out) + sufixo


# Rótulos legíveis (a origem vem em CAIXA ALTA)
_SIGLAS = {'US', 'USG', 'RM', 'TC', 'RX', 'ECG', 'EEG', 'EEGQ', 'MMII', 'ATM', 'HPV', 'PCTE', 'CSI', 'PA', 'SUS', 'CASSI', 'GEAP',
           'TRT', 'S/A', 'EREED', 'RNM', 'DR.', 'AP.', 'MMSS', 'OBST', 'TV'}
_LIGACOES = {'DE', 'DO', 'DA', 'DOS', 'DAS', 'E', 'OU', 'PARA', 'COM', 'EM', 'NO', 'NA', 'POR', 'P/', 'C/', 'A', 'AO'}


def bonito(txt):
    partes = re.split(r'([\s/\-\(\),:]+)', txt)
    out, primeiro = [], True
    for p in partes:
        if not p or re.fullmatch(r'[\s/\-\(\),:]+', p):
            out.append(p)
            continue
        u = p.upper()
        if u in _SIGLAS:
            out.append(u)
        elif u in _LIGACOES and not primeiro:
            out.append(p.lower())
        elif re.fullmatch(r'[\d\.ºª]+', p):
            out.append(p)
        else:
            out.append(p.lower() if not primeiro else p.lower().capitalize())
        primeiro = False
    s = ''.join(out)
    # cauterização etc. já vem em caixa mista: normaliza primeira letra
    return s[:1].upper() + s[1:]
