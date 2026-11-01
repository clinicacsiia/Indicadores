-- Ajusta duas pendências da Jornada depois de medir (01/11/2026) e acrescenta a do endereço público do portal do paciente.
-- Só update e insert, para o MCP do Supabase aplicar sem travar (ver CLAUDE.md).

update public.jornada_pendencia
   set nivel = 'atencao',
       titulo = 'Acompanhar o espaço do banco (424 MB de 470 MB; ~1 MB por dia)',
       texto = 'O banco tem 424 MB e o freio da coleta está em 470 MB: acima disso a coleta do Klingo para sozinha e o quadro deixa de atualizar. Hoje cresce cerca de 1 MB por dia (cerca de 6 semanas de folga). 334 MB são o histórico dos relatórios; o da recepção (#13404) é o maior (21%). Dá para liberar uns 25 MB apagando versões antigas e execuções antigas da coleta, e isso faz o banco parar de crescer por um bom tempo.',
       passos = '["Se concordar, rode o script supabase/limpeza_historico.sql no SQL Editor do Supabase (o MCP não apaga linhas). Ele tem um passo que só mostra o que sairia, antes dos que apagam.", "Não rode VACUUM FULL na tabela fact_relatorio_linha: precisaria de uma cópia temporária de ~300 MB e passaria dos 500 MB do plano.", "A solução definitiva é subir o plano do Supabase. Avise quando estiver abaixo de 30 MB de folga."]'::jsonb
 where chave = 'banco_espaco';

insert into public.jornada_pendencia (chave, etapa, titulo, texto, nivel, passos) values
  ('dominio_portal', 6,
   'Dar um endereço público ao portal do paciente (hoje o paciente não consegue abrir)',
   'O projeto da Vercel está com a proteção por login da Vercel em todos os endereços ".vercel.app" (Vercel Authentication, "all except custom domains"). A página do paciente (/p/<código>) funciona, mas quem não é da equipe da Vercel cai numa tela de login da Vercel. Para o paciente abrir, o site precisa de um domínio próprio da clínica (protegido só pelo login do próprio site) ou de desligar essa proteção para produção.',
   'critico',
   '["Opção recomendada: na Vercel, em Settings > Domains, adicione um domínio ou subdomínio da clínica (por exemplo, atendimento.clinicacsi.com.br) e aponte o DNS como a Vercel indicar. Domínios próprios ficam fora da proteção da Vercel.", "Alternativa: em Settings > Deployment Protection, trocar \"Vercel Authentication\" para \"Only Preview Deployments\". Isso deixa o site de produção aberto no endereço .vercel.app (o login do próprio site continua exigido em tudo, menos em /p/).", "Variável opcional na Vercel (Production e Preview): PORTAL_SAL = um texto qualquer longo, para embaralhar o registro de tentativas por origem."]'::jsonb)
on conflict (chave) do nothing;
