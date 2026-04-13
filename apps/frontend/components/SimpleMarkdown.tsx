import React from "react";

interface Classes {
  p: string;
  ul: string;
  ol: string;
  li: string;
  h2: string;
  h3: string;
}

const DEFAULT_CLASSES: Classes = {
  p: "mb-2 last:mb-0 text-sm leading-relaxed",
  ul: "mb-2 last:mb-0 ml-4 list-disc space-y-1 text-sm",
  ol: "mb-2 last:mb-0 ml-4 list-decimal space-y-1 text-sm",
  li: "leading-relaxed",
  h2: "mb-1 mt-3 text-sm font-semibold first:mt-0",
  h3: "mb-1 mt-2 text-sm font-semibold first:mt-0",
};

function renderInline(text: string): React.ReactNode {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  if (parts.length === 1) return text;
  return (
    <>
      {parts.map((part, i) =>
        part.startsWith("**") && part.endsWith("**") ? (
          <strong key={i} className="font-semibold">
            {part.slice(2, -2)}
          </strong>
        ) : (
          <React.Fragment key={i}>{part}</React.Fragment>
        )
      )}
    </>
  );
}

interface SimpleMarkdownProps {
  children: string;
  classes?: Partial<Classes>;
}

export function SimpleMarkdown({ children, classes }: SimpleMarkdownProps) {
  const cls: Classes = { ...DEFAULT_CLASSES, ...classes };
  const lines = children.split("\n");
  const blocks: React.ReactNode[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    if (line.startsWith("## ")) {
      blocks.push(
        <h2 key={i} className={cls.h2}>
          {renderInline(line.slice(3).trim())}
        </h2>
      );
      i++;
    } else if (line.startsWith("### ")) {
      blocks.push(
        <h3 key={i} className={cls.h3}>
          {renderInline(line.slice(4).trim())}
        </h3>
      );
      i++;
    } else if (/^[-*] /.test(line)) {
      const items: React.ReactNode[] = [];
      const startI = i;
      while (i < lines.length && /^[-*] /.test(lines[i])) {
        items.push(
          <li key={i} className={cls.li}>
            {renderInline(lines[i].slice(2))}
          </li>
        );
        i++;
      }
      blocks.push(
        <ul key={`ul-${startI}`} className={cls.ul}>
          {items}
        </ul>
      );
    } else if (/^\d+\. /.test(line)) {
      const items: React.ReactNode[] = [];
      const startI = i;
      while (i < lines.length && /^\d+\. /.test(lines[i])) {
        items.push(
          <li key={i} className={cls.li}>
            {renderInline(lines[i].replace(/^\d+\. /, ""))}
          </li>
        );
        i++;
      }
      blocks.push(
        <ol key={`ol-${startI}`} className={cls.ol}>
          {items}
        </ol>
      );
    } else if (line.trim() === "") {
      i++;
    } else {
      const startI = i;
      const textParts: string[] = [];
      while (
        i < lines.length &&
        lines[i].trim() !== "" &&
        !lines[i].startsWith("#") &&
        !/^[-*] /.test(lines[i]) &&
        !/^\d+\. /.test(lines[i])
      ) {
        textParts.push(lines[i]);
        i++;
      }
      if (textParts.length > 0) {
        blocks.push(
          <p key={`p-${startI}`} className={cls.p}>
            {textParts.map((t, j) => (
              <React.Fragment key={j}>
                {j > 0 && " "}
                {renderInline(t)}
              </React.Fragment>
            ))}
          </p>
        );
      }
    }
  }

  return <>{blocks}</>;
}
