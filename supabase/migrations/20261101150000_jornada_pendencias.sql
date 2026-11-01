-- Jornada do paciente: lista de pendências que dependem de uma pessoa (decisões, pedidos ao Klingo, cadastros), salva à medida que as etapas avançam
-- para serem resolvidas todas de uma vez no fim das fases. Aparecem na aba Avisos (painel Atendimento, escopo "jornada") junto com a pendência dos
-- relatórios do Klingo. Fechar exige justificativa, como qualquer aviso; quem deixa de ser necessário é desativado (ativa = false) e some sozinho.
-- Só create, grant e insert, para o MCP do Supabase aplicar sem travar (ver CLAUDE.md).

create table if not exists public.jornada_pendencia (
  chave     text primary key,                                   -- vira "jornada|<chave>" em aviso.chave
  etapa     integer     not null,                               -- etapa do plano em que apareceu
  titulo    text        not null,
  texto     text        not null,
  nivel     text        not null default 'info' check (nivel in ('critico', 'atencao', 'info')),
  passos    jsonb       not null default '[]'::jsonb,           -- lista de textos: o que fazer
  ativa     boolean     not null default true,
  criada_em timestamptz not null default now()
);

alter table public.jornada_pendencia enable row level security;
create policy "jornada_pendencia_select" on public.jornada_pendencia for select to authenticated using (public.is_admin());
revoke all on public.jornada_pendencia from public, anon, authenticated;
grant select on public.jornada_pendencia to authenticated;
grant all    on public.jornada_pendencia to service_role;

comment on table public.jornada_pendencia is 'Pendências da Jornada do paciente que dependem de uma pessoa. jornada_pendencias_sincronizar() as publica na aba Avisos (escopo jornada).';

insert into public.jornada_pendencia (chave, etapa, titulo, texto, nivel, passos) values
  ('feriados', 2,
   'Cadastrar os feriados da coleta',
   'A coleta de 1 minuto trata feriado como dia sem expediente. Hoje só o 12/10/2026 está cadastrado; em um feriado que falta na lista o sistema segue lendo a cada minuto à toa, como se houvesse expediente.',
   'atencao',
   '["No SQL Editor do Supabase: update public.coleta_ritmo_config set feriados = array[''2026-11-02'',''2026-11-15'',''2026-12-25'',''2027-01-01'']::date[]; (use as datas em que a clínica NÃO atende).", "Confirme também o expediente de coleta (06:30–18:30, segunda a sábado) e o teto de espera da madrugada (60 min), que eu escolhi por padrão."]'::jsonb),
  ('prazos_colunas', 2,
   'Conferir o prazo de cada coluna do quadro',
   'Cada coluna tem um prazo antes de o card ficar atrasado. Escolhi valores iniciais sem conversar com a equipe: Novo contato 2 h, Orçamento 1 dia, Aguardando autorização 3 dias, Chegou 30 min, Em atendimento 2 h, Finalizado 30 min, Laudo pendente 2 dias, Laudo entregue 1 dia, Guia/faturamento 3 dias, NPS e retorno 3 dias.',
   'info',
   '["Diga quais prazos mudar. Para mudar sozinho: update public.jornada_coluna set sla_min = 60 where id = ''chegou'';"]'::jsonb),
  ('quem_atende_colunas', 2,
   'Definir quem cuida de cada coluna',
   'O quadro mostra tudo para todos, mas cada coluna precisa de um responsável (ex.: Chegou = recepção, Laudo pendente = laudos, Guia/faturamento = faturamento). Isso define as atribuições automáticas e os avisos de atraso.',
   'info',
   '["Liste, por coluna, o setor ou as pessoas responsáveis e o turno.", "Lembrete: quem for usar o quadro precisa da permissão ''jornada'' em Configurações (a opção entra quando a tela do quadro existir, etapa 3)."]'::jsonb),
  ('colunas_manuais_antes', 2,
   'Decidir se Novo contato, Orçamento e Aguardando autorização entram na primeira versão',
   'Essas três colunas não existem no Klingo: a equipe teria de registrar à mão cada contato (foi onde a aba CRM Ressonância antiga perdeu cobertura). Estão criadas no modelo, mas só valem se a equipe se comprometer a registrar todos os pedidos.',
   'atencao',
   '["Responda: começamos só da marcação em diante (recomendado) ou já com o registro de contato?", "Se entrar: quem registra, em que momento, e quem confere."]'::jsonb),
  ('juridico_portal', 2,
   'Validar com o jurídico o chat com o paciente (LGPD e prontuário)',
   'Antes do portal do paciente: (1) conversa que tenha informação clínica pode virar prontuário, que o CFM manda guardar por 20 anos, o que conflita com apagar a pedido do paciente; (2) base legal (tutela da saúde), aviso de privacidade, termo de uso, encarregado (DPO) e relatório de impacto (RIPD); (3) menores atendidos na Pediatria: a conta é do responsável legal.',
   'atencao',
   '["Consulte o jurídico ou o encarregado de dados sobre retenção das conversas, base legal e consentimento para contato.", "Anote as decisões aqui (justificativa ao fechar este aviso): prazo de guarda, o que o paciente pode pedir para apagar, quem é o encarregado."]'::jsonb),
  ('api_escrita_klingo', 2,
   'Perguntar ao suporte do Klingo se há API ou webhook para confirmar e remarcar',
   'Hoje a integração só LÊ relatórios. Se o paciente confirmar ou remarcar pelo site, o Klingo não fica sabendo e a equipe teria de dar baixa à mão. Com API de escrita (ou um webhook de eventos), a confirmação do portal vira automática e a leitura deixa de ser a única fonte.',
   'atencao',
   '["Pergunte ao suporte do Klingo: existe API para confirmar, cancelar e remarcar uma marcação? Existe webhook (aviso) quando uma marcação muda?", "Peça também o token e a documentação, se existirem."]'::jsonb),
  ('canal_aviso_paciente', 2,
   'Escolher como avisar o paciente para entrar no site (SMS, WhatsApp ou e-mail)',
   'O portal só funciona se o paciente receber um aviso com o link (confirmação, preparo, laudo disponível). Cada canal tem custo e regras: WhatsApp exige modelos de mensagem aprovados; SMS cobra por envio; e-mail é barato mas lido tarde.',
   'info',
   '["Escolha o canal principal e um reserva. O custo você disse que vê depois, mas o canal precisa ser definido antes da etapa de automações.", "Verifique se o Wellum (que a clínica já usa) oferece API de envio."]'::jsonb),
  ('catalogo_preparo', 2,
   'Preencher o preparo dos exames (jejum, contraste, duração) e quais convênios exigem autorização',
   'A aba CRM antiga tinha esse catálogo, mas as tabelas foram apagadas. As mensagens automáticas de preparo e o checklist por exame dependem dele. A orientação de preparo é conteúdo clínico: precisa vir da equipe técnica, não de mim.',
   'atencao',
   '["Monte uma planilha: exame (nome exato do Klingo), preparo, usa contraste (sim/não), duração em minutos.", "Outra: convênio, exige autorização (sim/não), prazo da autorização em dias úteis.", "Quando as tabelas forem criadas (etapa de automações), eu importo."]'::jsonb)
on conflict (chave) do nothing;

-- ---------------------------------------------------------------- publica tudo na aba Avisos
create or replace function public.jornada_pendencias_sincronizar()
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_linhas   jsonb := '[]'::jsonb;
  v_alertas  jsonb := '[]'::jsonb;
  v_url      text := 'https://clinicacsi.klingo.app/#/relatorio/';
  v_tem_novo boolean;
begin
  -- 1) relatórios do Klingo (resolve sozinho quando existirem)
  select exists (select 1 from public.dim_relatorio where ativo and nome ilike 'Jornada do Paciente%') into v_tem_novo;

  if not v_tem_novo then
    v_linhas := v_linhas || jsonb_build_array(jsonb_build_array(
      'NOVO: Jornada do Paciente - Marcações por Data do Exame',
      'Criar o relatório (uma linha por marcação) com filtro por Data do Exame (Agendado Para) e, se o Klingo permitir, por Alterado em.',
      'O #13825 só filtra pela data em que a marcação foi FEITA. Cancelamento, confirmação e atendimento de uma marcação antiga não aparecem sem reler o mês inteiro (~8,5 mil linhas, 16 s).'));
  end if;

  if not exists (
    select 1 from public.dim_relatorio_coluna c join public.dim_relatorio r on r.id = c.relatorio_id
    where r.klingo_id = '13404' and coalesce(c.titulo_klingo, c.rotulo) ~* 'id d[oa] atendimento'
  ) then
    v_linhas := v_linhas || jsonb_build_array(jsonb_build_array(
      '#13404 Fluxo na Recepção',
      'Acrescentar as colunas Id do Atendimento, Id da Marcação e Prontuário.',
      'Sem o Id, a recepção não se liga ao paciente: só dá para acompanhar em agregado.'));
  end if;

  if not exists (
    select 1 from public.dim_relatorio_coluna c join public.dim_relatorio r on r.id = c.relatorio_id
    where r.klingo_id = '13402' and coalesce(c.titulo_klingo, c.rotulo) ~* 'id d[oa] atendimento'
  ) then
    v_linhas := v_linhas || jsonb_build_array(jsonb_build_array(
      '#13402 Visão Gerencial de Produtividade',
      'Acrescentar as colunas Id do Atendimento, Id da Marcação e Prontuário.',
      'Sem o Id, o início, o fim e a duração do exame não se ligam ao paciente.'));
  end if;

  if jsonb_array_length(v_linhas) > 0 then
    v_alertas := v_alertas || jsonb_build_array(jsonb_build_object(
      'chave', 'jornada|jornada_relatorio_klingo',
      'tipo', 'jornada_relatorio_klingo',
      'escopo', 'jornada',
      'nivel', 'info',
      'persistente', true,
      'titulo', 'Jornada do paciente: relatórios do Klingo a criar ou alterar',
      'texto', 'Para acompanhar cada paciente da marcação ao atendimento, com atualização a cada minuto, o Klingo precisa entregar os dados de um jeito mais fácil: '
               || 'um relatório de marcações por data do exame e o Id do atendimento nos relatórios da recepção. Enquanto isso não existe, a coleta de 1 minuto só enxerga marcações novas.',
      'itens_total', jsonb_array_length(v_linhas),
      'itens', jsonb_build_object(
        'colunas', jsonb_build_array('Relatório', 'O que fazer', 'Por quê'),
        'linhas', v_linhas,
        'total', jsonb_array_length(v_linhas),
        'numericas', '[]'::jsonb),
      'guia', jsonb_build_object(
        'relatorios', jsonb_build_array(
          jsonb_build_object('id', 13825, 'nome', 'Agendamentos - Visão Consolidada por Marcação (modelo do novo relatório)', 'url', v_url || '13825'),
          jsonb_build_object('id', 13404, 'nome', 'Atendimentos - Tempos de Espera e Fluxo na Recepção - Mensal', 'url', v_url || '13404'),
          jsonb_build_object('id', 13402, 'nome', 'Atendimentos - Visão Gerencial de Produtividade, Espera e Receita - Mensal', 'url', v_url || '13402')),
        'passos', jsonb_build_array(
          'Duplique o relatório #13825 e chame de "Jornada do Paciente - Marcações por Data do Exame".',
          'Filtro de período: Data do Exame (Agendado Para). Se houver, inclua também o filtro "Alterado em" (última alteração da marcação).',
          'Uma linha por marcação, com estas colunas: Id da Marcação, Id do Atendimento, Prontuário, Data Agendado Em, Data Agendado Para (com hora), Procedimento, Unidade/Sala/Equipamento, Profissional solicitante, Operadora, Valor, Responsável (quem marcou).',
          'Situação da marcação: Status, Cancelamento - Motivo, data do cancelamento, Confirm Status, data e usuário da confirmação, Atendido (S/N), Observação.',
          'Dia do exame: Check-In (hora), início e fim do exame, situação do laudo (e data de liberação) e situação da autorização do convênio (e número).',
          'Paciente (só para a equipe, com permissão): nome, data de nascimento, celular, telefone, e-mail e responsável legal (Pediatria).',
          'Controle: uma coluna com a data e a hora da última alteração de cada marcação.',
          'Nos relatórios #13404 e #13402, inclua as colunas Id do Atendimento, Id da Marcação e Prontuário.',
          'Avise o Claude quando o relatório novo existir: ele cadastra o relatório (dim_relatorio), confere as colunas e libera a leitura de 1 minuto.'),
        'resolve', 'Quando existir um relatório ativo chamado "Jornada do Paciente ..." e os relatórios #13404 e #13402 tiverem a coluna Id do Atendimento, o aviso se resolve sozinho (conferido todo dia às 06:00).')));
  end if;

  -- 2) decisões e cadastros que dependem de uma pessoa (tabela jornada_pendencia)
  v_alertas := v_alertas || coalesce((
    select jsonb_agg(jsonb_build_object(
      'chave', 'jornada|' || p.chave,
      'tipo', p.chave,
      'escopo', 'jornada',
      'nivel', p.nivel,
      'persistente', true,
      'titulo', 'Jornada (etapa ' || p.etapa || '): ' || p.titulo,
      'texto', p.texto,
      'guia', jsonb_build_object('passos', p.passos, 'resolve', 'Feche com a justificativa da decisão tomada (o que ficou combinado). O aviso some quando a pendência é desativada.')
    ) order by p.etapa, p.criada_em, p.chave)
    from public.jornada_pendencia p where p.ativa
  ), '[]'::jsonb);

  return public.aviso_sincronizar('atendimento', array['jornada'], 0, v_alertas);
end;
$$;

revoke execute on function public.jornada_pendencias_sincronizar() from public, anon, authenticated;
grant  execute on function public.jornada_pendencias_sincronizar() to service_role;
