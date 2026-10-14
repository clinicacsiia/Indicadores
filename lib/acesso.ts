// Supabase Auth exige email; quem digita só o usuário (ex.: "csiadmin")
// é mapeado para este domínio interno, que nunca recebe email.
export const DOMINIO_INTERNO = "csi.local";

// Quem pediu acesso e ainda não foi aprovado fica bloqueado no Auth por este tempo (na prática, até aprovar).
export const BLOQUEIO_PENDENTE = "876000h";
