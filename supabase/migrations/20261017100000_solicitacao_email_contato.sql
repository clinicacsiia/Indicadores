-- E-mail de contato informado por quem pede acesso na tela de login (o administrador vê na aprovação).
-- Não é o login: o usuário continua sendo o nome escolhido.
alter table public.profiles
  add column if not exists email_contato text;

comment on column public.profiles.email_contato is 'E-mail válido informado por quem pediu acesso na tela de login, para o administrador entrar em contato. Vazio para usuários criados direto pelo administrador.';
