-- Trava de renovação dos painéis em Python.
--
-- Quando o painel abre com dados vencidos, o navegador pede a renovação (copiar do banco + refazer a página) em segundo plano.
-- Antes, cada abertura refazia tudo na hora e, com duas pessoas (ou duas abas) ao mesmo tempo, as duas gravavam o mesmo
-- painel/aba/mês: a troca atômica de uma apagava os lotes ainda em gravação da outra e a atualização falhava com
-- "Nenhum lote gravado para ..." (painel_publicar_mes). Agora só uma renovação por painel roda de cada vez: quem chega depois vê o
-- andamento da que já está rodando.
--
-- A linha some ao terminar; se a função da Vercel morrer no meio, a trava vence sozinha (o código ignora linhas com mais de 6 min).
create table if not exists public.painel_renovacao (
  painel       text        primary key,
  iniciado_em  timestamptz not null default now(),
  previsto_s   int         not null default 30,   -- quanto se espera que leve (mediana das últimas atualizações), para o aviso "faltam ~N s"
  usuario      text        not null default ''
);

comment on table public.painel_renovacao is 'Trava + andamento da renovação de um painel em Python (uma linha por painel enquanto renova). Acesso só pela service_role.';

alter table public.painel_renovacao enable row level security;
revoke all on public.painel_renovacao from public, anon, authenticated;
grant all on public.painel_renovacao to service_role;

-- Consultas do painel por (painel, usuario, criado_em): previsão de duração e "última atualização".
create index if not exists painel_atualizacao_painel_criado_idx on public.painel_atualizacao (painel, criado_em desc);
