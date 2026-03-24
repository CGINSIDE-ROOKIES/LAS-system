export const ERROR_MESSAGES = {
  TIMEOUT: "응답 시간이 초과되었습니다. 다시 시도해주세요.",
  NETWORK: "네트워크 연결을 확인해주세요.",
  SERVER: "서버 오류가 발생했습니다.",
  PIPELINE_ERROR: "검색 중 오류가 발생했습니다. 다시 시도해주세요.",
  VALIDATION_ERROR: "잘못된 요청입니다. 입력 내용을 확인해주세요.",
} as const;

export function sseErrorMessage(code: string): string {
  switch (code) {
    case "PIPELINE_ERROR":
      return ERROR_MESSAGES.PIPELINE_ERROR;
    case "INTERNAL_ERROR":
      return ERROR_MESSAGES.SERVER;
    case "VALIDATION_ERROR":
      return ERROR_MESSAGES.VALIDATION_ERROR;
    default:
      return ERROR_MESSAGES.SERVER;
  }
}
