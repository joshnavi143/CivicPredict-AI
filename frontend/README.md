## Render deployment

The frontend reads the backend origin from `VITE_API_BASE_URL`. When it is not
set, local development uses `http://127.0.0.1:8000`.

For a Render Static Site configured from the repository root, set the Root
Directory to `frontend`, the Build Command to `npm ci && npm run build`, and the
Publish Directory to `dist`. Set `VITE_API_BASE_URL` to the backend's HTTPS
origin (for example, `https://civicpredict-api.onrender.com`) before building.
The root `render.yaml` also configures a rewrite to `/index.html`, so refreshing
React Router paths such as `/ai-predictions` serves the SPA.

# React + Vite

This template provides a minimal setup to get React working in Vite with HMR and some ESLint rules.

Currently, two official plugins are available:

- [@vitejs/plugin-react](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react) uses [Oxc](https://oxc.rs)
- [@vitejs/plugin-react-swc](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react-swc) uses [SWC](https://swc.rs/)

## React Compiler

The React Compiler is not enabled on this template because of its impact on dev & build performances. To add it, see [this documentation](https://react.dev/learn/react-compiler/installation).

## Expanding the ESLint configuration

If you are developing a production application, we recommend using TypeScript with type-aware lint rules enabled. Check out the [TS template](https://github.com/vitejs/vite/tree/main/packages/create-vite/template-react-ts) for information on how to integrate TypeScript and [`typescript-eslint`](https://typescript-eslint.io) in your project.
