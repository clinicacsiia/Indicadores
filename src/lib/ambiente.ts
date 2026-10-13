/** Variáveis de ambiente. Segredos só no servidor (nunca NEXT_PUBLIC_): SUPABASE_SERVICE_ROLE_KEY, KLINGO_APP_TOKEN, CRON_SECRET. */
function exigir(nome: string): string {
  const v = process.env[nome];
  if (!v) throw new Error(`Variável de ambiente ausente: ${nome}`);
  return v;
}

export const ambiente = {
  get supabaseUrl() { return process.env.SUPABASE_URL || exigir("NEXT_PUBLIC_SUPABASE_URL"); },
  get anonKey() { return exigir("NEXT_PUBLIC_SUPABASE_ANON_KEY"); },
  get serviceRoleKey() { return exigir("SUPABASE_SERVICE_ROLE_KEY"); },
  get cronSecret() { return exigir("CRON_SECRET"); },
  /** Chave para assinar o cookie de sessão (padrão: o CRON_SECRET). */
  get segredoSessao() { return process.env.SESSAO_SEGREDO || exigir("CRON_SECRET"); },
};

/** E-mail sintético: o Supabase Auth exige e-mail; o usuário só digita o nome de usuário. */
export const DOMINIO_USUARIOS = "usuarios.csi.local";
export const emailDoUsuario = (usuario: string) => `${usuario.trim().toLowerCase()}@${DOMINIO_USUARIOS}`;
