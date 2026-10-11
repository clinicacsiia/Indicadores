import type { Metadata } from "next";
import { Brand } from "@/app/components/Brand";
import { LoginForm } from "./LoginForm";

export const metadata: Metadata = { title: "Entrar" };

// Arte decorativa: duas linhas de tendência, no mesmo desenho do gráfico do painel.
function ArteIndicadores() {
  return (
    <svg className="login-art" viewBox="0 0 600 300" preserveAspectRatio="none" fill="none" aria-hidden="true">
      <defs>
        <linearGradient id="arte-fundo" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#4fd1c0" stopOpacity="0.22" />
          <stop offset="1" stopColor="#4fd1c0" stopOpacity="0" />
        </linearGradient>
      </defs>
      <path
        d="M0 210 C60 190 90 150 150 160 S240 215 300 170 S410 80 470 110 S560 70 600 50 V300 H0Z"
        fill="url(#arte-fundo)"
      />
      <path
        d="M0 210 C60 190 90 150 150 160 S240 215 300 170 S410 80 470 110 S560 70 600 50"
        stroke="#4fd1c0"
        strokeWidth="2.5"
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
      />
      <path
        d="M0 240 C70 235 110 200 170 205 S260 245 320 215 S430 150 490 165 S560 130 600 120"
        stroke="#e39a52"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeOpacity="0.85"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}

export default function LoginPage() {
  return (
    <main className="login">
      <section className="login-hero" aria-hidden="false">
        <Brand />
        <div className="login-hero-copy">
          <h2>Os números da clínica, dia a dia.</h2>
          <p>Agendamentos, atendimentos finalizados e valores dos procedimentos num só lugar.</p>
        </div>
        <ArteIndicadores />
        <div className="login-foot">Clínica CSI · Acesso restrito à equipe</div>
      </section>

      <section className="login-panel">
        <div className="login-card">
          <div className="login-mobile-brand">
            <Brand />
          </div>
          <div>
            <h1>Entrar</h1>
            <p className="lede">Use o usuário e a senha da equipe para acessar os indicadores.</p>
          </div>
          <LoginForm />
        </div>
      </section>
    </main>
  );
}
