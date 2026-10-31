import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./App.css";

export function mount(root: HTMLElement) {
  createRoot(root).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>,
  );
}
