import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
    plugins: [react()],
    base: './', // Important for Electron
    server: {
        port: 5173,
        watch: {
            // Evita que el file-watcher de Windows vigile directorios pesados o
            // irrelevantes (estado del backend, entorno Python, modelos), lo que
            // provocaba crashes de Vite (UNKNOWN: watch) y recargas innecesarias.
            ignored: [
                '**/venv/**',
                '**/backend/demo_state/**',
                '**/projects/**',
                '**/memory_store/**',
                '**/node_modules/**',
                '**/*.onnx',
                '**/*.task',
            ],
        },
    }
})
