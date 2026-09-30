import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import App from "./App.tsx";
import { getInitialTheme, setTheme } from "./lib/theme";

// Applied before render so pages without a toggle (e.g. /login) get the theme too.
setTheme(getInitialTheme());

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
