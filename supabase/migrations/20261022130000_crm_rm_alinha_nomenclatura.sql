-- Alinha o CRM da RM à nomenclatura real do Klingo e do resto do sistema.
--
-- 1) forma_pagamento deixa de ser binário: o Klingo registra SUS (76 RM em set-out) e Cetrus
--    (antigo "SUS CURSO"), que o resto do sistema já trata como categoria própria.
-- 2) exame e convenio passam a vir do catálogo (nome exato do Klingo), não de uma lista inventada.
--    A conferência é feita na server action contra crm_rm_exame / crm_rm_convenio.
-- 3) unidade: a RM é toda em "CLÍNICA DE SAÚDE E IMAGEM - RM/TC" (= grupo CSI 2 no metas.json).
-- 4) identificação: sem código ou telefone a fila "retomar hoje" não serve — a atendente não acha
--    a pessoa. Os dois são opcionais e só aparecem nas listas de trabalho, nunca nos indicadores.
-- 5) primeira_resposta_em: "Demora na resposta" é motivo de perda; sem carimbo não dá para medir.
-- 6) origem_registro: quem digitou, com os mesmos nomes do campo "Origem" do Klingo. Não confundir
--    com `canal`, que é por onde o PACIENTE chegou (marketing).

alter table public.crm_rm_contato drop constraint if exists crm_rm_contato_exame_check;
alter table public.crm_rm_contato drop constraint if exists crm_rm_contato_forma_pagamento_check;
alter table public.crm_rm_agenda  drop constraint if exists crm_rm_agenda_forma_pagamento_check;
alter table public.crm_rm_agenda  drop constraint if exists crm_rm_agenda_exame_check;
alter table public.crm_rm_contato drop constraint if exists crm_rm_contato_convenio_check;
alter table public.crm_rm_contato drop constraint if exists crm_rm_contato_canal_check;

alter table public.crm_rm_contato add constraint crm_rm_contato_forma_pagamento_check
  check (forma_pagamento in ('Particular', 'Convênio', 'SUS', 'Cetrus'));
alter table public.crm_rm_agenda add constraint crm_rm_agenda_forma_pagamento_check
  check (forma_pagamento in ('Particular', 'Convênio', 'SUS', 'Cetrus'));
alter table public.crm_rm_contato add constraint crm_rm_contato_convenio_check
  check (convenio is null or char_length(convenio) <= 80);
alter table public.crm_rm_contato add constraint crm_rm_contato_canal_check
  check (canal in ('WhatsApp', 'Telefone', 'Site', 'Google', 'Instagram', 'Indicação médica', 'Presencial', 'Convênio / operadora', 'Retorno de paciente', 'Outro'));

alter table public.crm_rm_contato add column if not exists unidade text not null default 'CLÍNICA DE SAÚDE E IMAGEM - RM/TC';
alter table public.crm_rm_agenda  add column if not exists unidade text not null default 'CLÍNICA DE SAÚDE E IMAGEM - RM/TC';
alter table public.crm_rm_contato add column if not exists codigo_klingo text;
alter table public.crm_rm_contato add column if not exists telefone text;
alter table public.crm_rm_contato add column if not exists primeira_resposta_em timestamptz;
alter table public.crm_rm_contato add column if not exists origem_registro text;
alter table public.crm_rm_agenda  add column if not exists codigo_marcacao text;

alter table public.crm_rm_contato drop constraint if exists crm_rm_contato_codigo_klingo_check;
alter table public.crm_rm_contato add constraint crm_rm_contato_codigo_klingo_check
  check (codigo_klingo is null or codigo_klingo ~ '^[A-Za-z0-9.\-/ ]{1,30}$');
alter table public.crm_rm_contato drop constraint if exists crm_rm_contato_telefone_check;
alter table public.crm_rm_contato add constraint crm_rm_contato_telefone_check
  check (telefone is null or telefone ~ '^[0-9]{10,13}$');
alter table public.crm_rm_contato drop constraint if exists crm_rm_contato_origem_registro_check;
alter table public.crm_rm_contato add constraint crm_rm_contato_origem_registro_check
  check (origem_registro is null or origem_registro in ('TELEOPERADOR', 'RECEPCIONISTA', 'SAC/TEXTO', 'ENFERMEIRA', 'ADMINISTRATIVO'));
alter table public.crm_rm_agenda drop constraint if exists crm_rm_agenda_codigo_marcacao_check;
alter table public.crm_rm_agenda add constraint crm_rm_agenda_codigo_marcacao_check
  check (codigo_marcacao is null or codigo_marcacao ~ '^[0-9]{1,12}$');

comment on column public.crm_rm_contato.telefone is 'Opcional, só dígitos. Dado pessoal: existe para a atendente retomar o contato e aparece apenas nas listas de trabalho, nunca nos indicadores.';
comment on column public.crm_rm_contato.codigo_klingo is 'Código do paciente ou da marcação no Klingo. Preferir isto ao telefone: identifica sem guardar dado pessoal.';
comment on column public.crm_rm_contato.primeira_resposta_em is 'Quando a equipe respondeu pela primeira vez. Base do indicador de tempo de resposta.';
comment on column public.crm_rm_agenda.codigo_marcacao is 'Código da marcação no Klingo (coluna Marcacao do relatório 7 / id_marcacao do 260). Liga este horário ao sistema.';

create index if not exists crm_rm_contato_retorno_idx on public.crm_rm_contato (data_retorno) where data_retorno is not null;
create index if not exists crm_rm_agenda_codigo_idx on public.crm_rm_agenda (codigo_marcacao) where codigo_marcacao is not null;

-- Colunas novas entram nos grants por coluna (o resto continua bloqueado).
grant insert (unidade, codigo_klingo, telefone, primeira_resposta_em, origem_registro) on public.crm_rm_contato to authenticated;
grant update (codigo_klingo, telefone, primeira_resposta_em, exame, convenio, forma_pagamento) on public.crm_rm_contato to authenticated;
grant insert (unidade, codigo_marcacao) on public.crm_rm_agenda to authenticated;
grant update (codigo_marcacao, exame, forma_pagamento) on public.crm_rm_agenda to authenticated;
