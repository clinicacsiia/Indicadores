// Chama uma Edge Function de sync (sync-relatorios-dw) com o JWT de quem está
// logado no site. Nenhuma chave privilegiada (service_role) existe no site;
// a Edge Function decide sozinha o que aquele JWT pode fazer.
export async function chamarEdgeFunction(nome: string, accessToken: string, corpo: unknown) {
  const res = await fetch(`${process.env.NEXT_PUBLIC_SUPABASE_URL}/functions/v1/${nome}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      apikey: process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
      Authorization: `Bearer ${accessToken}`,
    },
    body: JSON.stringify(corpo),
    signal: AbortSignal.timeout(280_000),
  });
  const payload = await res.json().catch(() => ({}));
  return { ok: res.ok, status: res.status, payload };
}
