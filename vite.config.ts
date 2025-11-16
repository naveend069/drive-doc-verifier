// vite.config.ts
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react-swc'; // Assuming this is your plugin
import * as path from 'path'; // <--- NEW IMPORT NEEDED

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  
  // *** ADD THIS RESOLVE BLOCK ***
  resolve: {
    // This tells Vite to handle imports that normally point to node_modules
    // by resolving them to the absolute path from the current directory.
    alias: {
      'axios': path.resolve(__dirname, 'node_modules/axios/index.js'),
    }
  }
  // ******************************
});