const API_PORT = 8000;

/**
 * 백엔드 API base URL을 반환한다.
 *
 * 우선순위:
 * 1. NEXT_PUBLIC_API_URL 환경변수
 * 2. 브라우저 환경에서 window.location.hostname 기반 fallback
 * 3. SSR 환경 fallback (localhost)
 */
export function getApiBaseUrl(): string {
  if (process.env.NEXT_PUBLIC_API_URL) {
    return process.env.NEXT_PUBLIC_API_URL.replace(/\/$/, "");
  }

  if (typeof window !== "undefined") {
    return `${window.location.protocol}//${window.location.hostname}:${API_PORT}`;
  }

  return `http://localhost:${API_PORT}`;
}
