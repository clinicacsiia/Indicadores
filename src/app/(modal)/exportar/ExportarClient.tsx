"use client";
import { useEffect, useMemo, useState } from "react";
import { juntarPdfs } from "@/lib/pdf-juntar";

interface Item { chave: string; modulo: string; visao: string; nome: string; grupo: string }
const rotulo = (ym: string) => { const [a, m] = ym.split("-"); return `${["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"][+m - 1]}/${a}`; };
const mesMais = (ym: string, n: number) => { const t = +ym.slice(0, 4) * 12 + (+ym.slice(5) - 1) + n; return `${Math.floor(t / 12)}-${String((t % 12) + 1).padStart(2, "0")}`; };

export default function ExportarClient({ itens }: { itens: Item[] }) {
  const [meses, setMeses] = useState<string[]>([]);
  const [hoje, setHoje] = useState("");
  const [de, setDe] = useState(""), [ate, setAte] = useState("");
  const [marcados, setMarcados] = useState<Set<string>>(new Set(itens.filter((i) => !i.visao).map((i) => i.chave)));
  const [modo, setModo] = useState<"junto" | "separado">("junto");
  const [estado, setEstado] = useState<{ msg: string; erro?: boolean } | null>(null);
  const [ocupado, setOcupado] = useState(false);

  useEffect(() => {
    fetch("/api/periodos").then((r) => r.json()).then((j: { meses: string[]; hoje: string }) => {
      const lista = [...new Set([...j.meses, j.hoje])].sort();
      setMeses(lista); setHoje(j.hoje); setDe(j.hoje); setAte(j.hoje);
    }).catch(() => setEstado({ msg: "Não consegui carregar os meses.", erro: true }));
  }, []);

  const atalhos = useMemo(() => hoje ? [
    ["Mês atual", hoje, hoje], ["Mês anterior", mesMais(hoje, -1), mesMais(hoje, -1)],
    ["Últimos 3 meses", mesMais(hoje, -2), hoje], ["Desde o início", meses[0] ?? hoje, hoje],
  ] as const : [], [hoje, meses]);

  const alternar = (c: string) => setMarcados((s) => { const n = new Set(s); n.has(c) ? n.delete(c) : n.add(c); return n; });
  const escolhidos = itens.filter((i) => marcados.has(i.chave));

  async function gerar(): Promise<{ nome: string; bytes: Uint8Array }[]> {
    const saida: { nome: string; bytes: Uint8Array }[] = [];
    for (let k = 0; k < escolhidos.length; k++) {
      const it = escolhidos[k];
      setEstado({ msg: `Gerando ${k + 1} de ${escolhidos.length}: ${it.nome}…` });
      const r = await fetch("/api/exportar-pdf", { method: "POST", headers: { "Content-Type": "application/json", "X-Painel": "1" }, body: JSON.stringify({ itens: [{ modulo: it.modulo, ...(it.visao ? { visao: it.visao } : {}) }], de, ate }) });
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).erro ?? "Não foi possível gerar o PDF.");
      saida.push({ nome: it.nome, bytes: new Uint8Array(await r.arrayBuffer()) });
    }
    return saida;
  }
  const baixar = (bytes: Uint8Array, arquivo: string) => {
    const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([bytes as BlobPart], { type: "application/pdf" })); a.download = arquivo; a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 30_000);
  };
  const executar = async (imprimir: boolean) => {
    if (!escolhidos.length) { setEstado({ msg: "Marque ao menos um item.", erro: true }); return; }
    setOcupado(true);
    try {
      const partes = await gerar();
      if (imprimir) {
        const junto = await juntarPdfs(partes.map((p) => ({ titulo: p.nome, bytes: p.bytes })));
        const f = document.createElement("iframe"); f.style.cssText = "position:fixed;width:0;height:0;border:0;visibility:hidden"; f.src = URL.createObjectURL(new Blob([junto as BlobPart], { type: "application/pdf" }));
        f.onload = () => { try { f.contentWindow?.print(); } catch { baixar(junto, "indicadores-csi.pdf"); } };
        document.body.appendChild(f);   // PDF num iframe escondido, como no legado
      } else if (modo === "junto") baixar(await juntarPdfs(partes.map((p) => ({ titulo: p.nome, bytes: p.bytes }))), "indicadores-csi.pdf");
      else partes.forEach((p) => baixar(p.bytes, `${p.nome.replace(/[^\w]+/g, "-").toLowerCase()}.pdf`));
      setEstado({ msg: "Pronto." });
    } catch (e) { setEstado({ msg: (e as Error).message, erro: true }); }
    setOcupado(false);
  };

  const grupos = [...new Set(itens.map((i) => i.grupo))];
  return (
    <div>
      <section>
        <h2>Período do relatório</h2>
        <div className="linha-form">
          <label>De<select value={de} onChange={(e) => { setDe(e.target.value); if (e.target.value > ate) setAte(e.target.value); }}>{meses.map((m) => <option key={m} value={m}>{rotulo(m)}</option>)}</select></label>
          <label>até<select value={ate} onChange={(e) => { setAte(e.target.value); if (e.target.value < de) setDe(e.target.value); }}>{meses.map((m) => <option key={m} value={m}>{rotulo(m)}</option>)}</select></label>
        </div>
        <div className="linha-form">{atalhos.map(([n, a, b]) => <button key={n} type="button" className="btn sec pq" onClick={() => { setDe(a); setAte(b); }}>{n}</button>)}</div>
      </section>
      {grupos.map((g) => (
        <section key={g}>
          <h2>{g}</h2>
          <div className="menus-escolha">{itens.filter((i) => i.grupo === g).map((i) => <label key={i.chave}><input type="checkbox" checked={marcados.has(i.chave)} onChange={() => alternar(i.chave)} /> {i.nome}</label>)}</div>
        </section>
      ))}
      <section>
        <div className="menus-escolha">
          <label><input type="radio" name="modo" checked={modo === "junto"} onChange={() => setModo("junto")} /> Tudo junto (um só PDF)</label>
          <label><input type="radio" name="modo" checked={modo === "separado"} onChange={() => setModo("separado")} /> Um por um</label>
        </div>
        <div className="linha-form">
          <button className="btn" disabled={ocupado} onClick={() => executar(false)}>Baixar marcados</button>
          <button className="btn sec" disabled={ocupado} onClick={() => executar(true)}>Imprimir marcados</button>
        </div>
        {estado && <p className={estado.erro ? "erro" : "nota"} role="status">{estado.msg}</p>}
        <p className="micro">Um PDF de todos os painéis com período longo pode levar alguns minutos.</p>
      </section>
    </div>
  );
}
