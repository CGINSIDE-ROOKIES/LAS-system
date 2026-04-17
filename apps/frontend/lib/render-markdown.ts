/**
 * 경량 마크다운 → HTML 변환 (외부 패키지 없음)
 * 지원: ## ### 헤딩, **bold**, *italic*, - /* 불릿 리스트, 1. 순서 리스트
 */

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function inlineFormat(text: string): string {
  return escapeHtml(text)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g, "<em>$1</em>");
}

export function renderMarkdown(raw: string): string {
  const lines = raw.split("\n");
  const parts: string[] = [];
  let listType: "ul" | "ol" | null = null;

  const closeList = () => {
    if (listType) {
      parts.push(`</${listType}>`);
      listType = null;
    }
  };

  for (const line of lines) {
    const trimmed = line.trim();

    if (!trimmed) {
      closeList();
      continue;
    }

    const h2 = trimmed.match(/^##\s+(.+)/);
    const h3 = trimmed.match(/^###\s+(.+)/);
    const ul = trimmed.match(/^[-*•]\s+(.+)/);
    const ol = trimmed.match(/^\d+\.\s+(.+)/);

    if (h2) {
      closeList();
      parts.push(`<h2>${inlineFormat(h2[1])}</h2>`);
    } else if (h3) {
      closeList();
      parts.push(`<h3>${inlineFormat(h3[1])}</h3>`);
    } else if (ul) {
      if (listType !== "ul") { closeList(); parts.push("<ul>"); listType = "ul"; }
      parts.push(`<li>${inlineFormat(ul[1])}</li>`);
    } else if (ol) {
      if (listType !== "ol") { closeList(); parts.push("<ol>"); listType = "ol"; }
      parts.push(`<li>${inlineFormat(ol[1])}</li>`);
    } else {
      closeList();
      parts.push(`<p>${inlineFormat(trimmed)}</p>`);
    }
  }

  closeList();
  return parts.join("");
}
