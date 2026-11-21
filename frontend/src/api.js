const configuredApiBaseUrl = import.meta.env.VITE_API_BASE_URL?.trim();

export const API_BASE_URL = (
  configuredApiBaseUrl || "https://civicpredict-ai.onrender.com"
).replace(/\/+$/, "");
