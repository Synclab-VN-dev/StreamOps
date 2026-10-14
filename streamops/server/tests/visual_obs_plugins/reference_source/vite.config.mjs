import {defineConfig} from "vite";
import tailwind from "@tailwindcss/vite";

// Pinned MagicPath handles ?state directly; no transform required.
export default defineConfig({plugins:[tailwind()],esbuild:{jsx:"automatic"},server:{host:"127.0.0.1",port:5179,strictPort:true}});
