"use client";
import { useState } from "react";

interface Checagem { nome: string; ok: boolean; esperado: unknown; obtido: unknown; detalhe: string }

export default function Conferir() {
  const [lista, setLista] = useState<Checagem[] | null>(null);
  const [erro, setErro] = useState(""), [ocupado, setOcupado] = useState(false);
  async function rodar() {
    setOcupado(true); setErro("");
    try {
      const r = await fetch("/api/conferir");
      const j = await r.json();
      if (!r.ok) throw new Error(j.erro ?? "Falhou.");
      setLista(j.checagens);
    } catch (e) { setErro((e as Error).message); }
    setOcupado(false);
  }
  const fmt = (v: unknown) => typeof v === "number" ? v.toLocaleString("pt-BR", { maximumFractionDigits: 2 }) : String(v);
  return (
    <div>
      <button className="btn pq" onClick={rodar} disabled={ocupado}>{ocupado ? "Conferindo…" : "Conferir agora"}</button>
      {erro && <p className="erro">{erro}</p>}
      {lista && <>
        <p className="nota">{lista.filter((c) => c.ok).length} de {lista.length} checagens dentro do esperado.</p>
        <div className="tab-wrap"><table className="t"><thead><tr><th>Checagem</th><th className="n">Esperado</th><th className="n">Obtido</th><th>Situação</th></tr></thead><tbody>
          {lista.map((c, i) => <tr key={i}><td className="txt">{c.nome}<div className="micro">{c.detalhe}</div></td><td className="n">{fmt(c.esperado)}</td><td className="n">{fmt(c.obtido)}</td><td className={c.ok ? "ok" : "erro"}>{c.ok ? "ok" : "diverge"}</td></tr>)}
        </tbody></table></div>
      </>}
    </div>
  );
}
