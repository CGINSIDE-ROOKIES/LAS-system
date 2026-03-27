const API_PORT = 8000;

/**
 * 백엔드 API base URL을 반환한다.
 *
 * 우선순위:
 * 1. NEXT_PUBLIC_API_URL 환경변수
 * 2. 브라우저 환경에서는 same-origin 상대 경로 사용
 * 3. SSR 환경에서는 BACKEND_INTERNAL_URL 환경변수
 * 4. 로컬 개발 fallback (localhost)
 */
export function getApiBaseUrl(): string {
  if (process.env.NEXT_PUBLIC_API_URL) {
    return process.env.NEXT_PUBLIC_API_URL.replace(/\/$/, "");
  }

  if (typeof window !== "undefined") {
    return "";
  }

  if (process.env.BACKEND_INTERNAL_URL) {
    return process.env.BACKEND_INTERNAL_URL.replace(/\/$/, "");
  }

  return `http://localhost:${API_PORT}`;
}
