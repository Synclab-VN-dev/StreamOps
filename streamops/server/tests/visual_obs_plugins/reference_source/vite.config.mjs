import {defineConfig} from "vite";
import tailwind from "@tailwindcss/vite";
export default defineConfig({plugins:[tailwind()],esbuild:{jsx:"automatic"},server:{host:"127.0.0.1",port:5179,strictPort:true}});
