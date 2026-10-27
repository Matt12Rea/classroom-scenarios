import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
// Self-hosted fonts: bundled with the site, so no request goes to a font service.
import "@fontsource-variable/public-sans";
import "@fontsource-variable/source-serif-4";
import App from "./App.jsx";
import "./styles.css";

createRoot(document.getElementById("root")).render(<StrictMode><App /></StrictMode>);
