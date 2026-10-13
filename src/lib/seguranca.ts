import { createHash, createHmac, timingSafeEqual } from "node:crypto";
import { ambiente } from "./ambiente";

// ------------------------------------------------------------------ nome de usuário e senha (regras do legado _validar_nome/_validar_senha reconstruídas; ver docs/PREMISSAS.md)
const COMUNS = new Set(["12345678", "123456789", "1234567890", "password", "senha123", "senha1234", "qwerty123", "abc12345", "csi12345", "clinicacsi", "csi@1234", "admin123", "admin1234"]);

export function validarNome(nome: string): string | null {
  const n = nome.trim();
  if (!/^[A-Za-z0-9._-]{2,32}$/.test(n)) return "O usuário deve ter de 2 a 32 caracteres: letras, números, ponto, hífen ou sublinhado.";
  return null;
}

export function validarSenha(senha: string, usuario = ""): string | null {
  if (senha.length < 8) return "A senha deve ter pelo menos 8 caracteres.";
  if (senha.length > 128) return "A senha é longa demais (máximo de 128 caracteres).";
  if (!/[A-Za-z]/.test(senha) || !/\d/.test(senha)) return "A senha deve ter pelo menos uma letra e um número.";
  if (usuario && senha.toLowerCase().includes(usuario.trim().toLowerCase()) && usuario.trim().length >= 3) return "A senha não pode conter o nome de usuário.";
  if (COMUNS.has(senha.toLowerCase())) return "Essa senha é muito comum. Escolha outra.";
  return null;
}

// ------------------------------------------------------------------ origem (IP) sem guardar o IP
export const hashDeOrigem = (ip: string) => createHash("sha256").update(`${ambiente.segredoSessao}|${ip}`).digest("hex").slice(0, 32);
export function ipDe(req: Pick<Request, "headers">): string {
  return req.headers.get("x-forwarded-for")?.split(",")[0].trim() || req.headers.get("x-real-ip") || "desconhecido";
}

// ------------------------------------------------------------------ cookie de sessão assinado: sessão de 8 h e "derrubar as outras sessões"
export const SESSAO_HORAS = 8;
export const COOKIE_SESSAO = "csi_sessao";

export function assinarSessao(userId: string, emitidoEm = Date.now()): string {
  const corpo = `${userId}.${emitidoEm}`;
  return `${corpo}.${createHmac("sha256", ambiente.segredoSessao).update(corpo).digest("base64url")}`;
}

export function lerSessaoAssinada(valor: string | undefined): { userId: string; emitidoEm: number } | null {
  if (!valor) return null;
  const i = valor.lastIndexOf(".");
  if (i < 0) return null;
  const corpo = valor.slice(0, i), assinatura = valor.slice(i + 1);
  const esperado = createHmac("sha256", ambiente.segredoSessao).update(corpo).digest("base64url");
  const a = Buffer.from(assinatura), b = Buffer.from(esperado);
  if (a.length !== b.length || !timingSafeEqual(a, b)) return null;
  const [userId, t] = corpo.split(".");
  const emitidoEm = Number(t);
  if (!userId || !Number.isFinite(emitidoEm)) return null;
  if (Date.now() - emitidoEm > SESSAO_HORAS * 3600_000) return null;
  return { userId, emitidoEm };
}

// ------------------------------------------------------------------ POST: anti-CSRF simples (X-Painel: 1 + mesma origem), corpo até 1 MB
export const LIMITE_CORPO = 1_000_000;

export function validarPost(req: Request): Response | null {
  if (req.headers.get("x-painel") !== "1") return Response.json({ erro: "Pedido recusado." }, { status: 403 });
  const origem = req.headers.get("origin");
  if (origem) {
    try {
      if (new URL(origem).host !== (req.headers.get("x-forwarded-host") ?? req.headers.get("host"))) return Response.json({ erro: "Pedido recusado." }, { status: 403 });
    } catch { return Response.json({ erro: "Pedido recusado." }, { status: 403 }); }
  }
  const tam = Number(req.headers.get("content-length") ?? 0);
  if (tam > LIMITE_CORPO) return Response.json({ erro: "Pedido grande demais." }, { status: 413 });
  return null;
}

export async function lerJson<T = Record<string, unknown>>(req: Request): Promise<T | null> {
  try {
    const texto = await req.text();
    if (texto.length > LIMITE_CORPO) return null;
    return JSON.parse(texto || "{}") as T;
  } catch { return null; }
}

export function segredoConfere(cabecalho: string | null): boolean {
  if (!cabecalho) return false;
  const dado = cabecalho.replace(/^Bearer\s+/i, "");
  const a = Buffer.from(dado), b = Buffer.from(ambiente.cronSecret);
  return a.length === b.length && timingSafeEqual(a, b);
}
