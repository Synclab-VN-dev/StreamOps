import {defineConfig} from "vite";
import tailwind from "@tailwindcss/vite";

// The checked-in component remains byte-identical to the pinned MagicPath
// revision. This test-only Vite transform SELECTS an existing scenario branch,
// without changing UI markup, styling, or source artifacts on disk.
const scenarioPreview = () => ({
  name: "issue75-pinned-magicpath-scenario-selector",
  enforce: "pre",
  transform(code, id) {
    if (!id.replaceAll("\\", "/").endsWith("/src/components/generated/StreamOpsOBSPluginManager.tsx")) return null;
    const original = 'const [scenario, setScenario] = useState("normal");';
    if (code.split(original).length !== 2) {
      throw new Error("Pinned MagicPath scenario initializer drift");
    }
    const replacement = 'const [scenario, setScenario] = useState(() => { const requested = new URLSearchParams(window.location.search).get("state"); return ["normal","blocked"].includes(requested) ? requested : "normal"; });';
    return {code:code.replace(original, replacement),map:null};
  }
});
export default defineConfig({plugins:[scenarioPreview(),tailwind()],esbuild:{jsx:"automatic"},server:{host:"127.0.0.1",port:5179,strictPort:true}});
