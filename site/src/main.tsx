import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { Console } from "./console";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Console />
    <footer className="mx-auto max-w-6xl px-4 pb-10 font-mono text-xs text-muted sm:px-8">
      Static page. The arithmetic runs in this browser; nothing is sent to a server. The Python
      package is the reference implementation.{" "}
      <a className="text-oxide underline" href="https://github.com/chrislernunes/chronos">
        chrislernunes/chronos
      </a>
    </footer>
  </StrictMode>,
);
