// vite.config.ts
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react-swc';
import * as path from 'path'; // <--- CRITICAL IMPORT

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  
  // *** THIS BLOCK RESOLVES BOTH AXIOS AND THE @/ ALIAS ***
  resolve: {
    alias: {
      // 1. Alias for your custom component imports (e.g., @/components/...)
      '@': path.resolve(__dirname, './src'), 
      
      // 2. (Optional but safer) Alias for external dependencies like axios
      'axios': path.resolve(__dirname, 'node_modules/axios/index.js'),
    },
  },
  // *******************************************************
});