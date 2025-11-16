// vite.config.ts
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react-swc';
import * as path from 'path'; // <--- Ensure this import is present if you use 'path'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  
  // *** ADD THIS RESOLVE BLOCK ***
  resolve: {
    alias: {
      // This tells Rollup that when it sees @/, it should look inside the src/ folder.
      '@': path.resolve(__dirname, './src'), 
    },
  },
  // ******************************
});