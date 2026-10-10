import {defineConfig} from "vite";
import tailwind from "@tailwindcss/vite";
export default defineConfig({plugins:[tailwind()], server:{host:"127.0.0.1",strictPort:true,port:5178}});
