import { useState, useRef, useEffect } from "react";
import { Send } from "lucide-react";
import { Button } from "@/components/ui/button";

interface QuestionInputProps {
  onSubmit: (question: string) => void;
  disabled?: boolean;
}

export function QuestionInput({ onSubmit, disabled }: QuestionInputProps) {
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    const next = Math.min(el.scrollHeight, 200);
    el.style.height = `${next}px`;
    el.style.overflowY = el.scrollHeight > 200 ? "auto" : "hidden";
  }, [value]);

  const handleSubmit = () => {
    if (!value.trim() || disabled) return;
    onSubmit(value.trim());
    setValue("");
  };

  return (
    <div className="space-y-3">
      <div className="relative">
        <textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              handleSubmit();
            }
          }}
          placeholder="근로계약서 작성 시 필수 기재사항은 무엇인가요?"
          disabled={disabled}
          rows={1}
          className="w-full resize-none rounded-lg border border-border bg-card px-4 py-3 pr-12 text-sm text-foreground placeholder:text-muted-foreground/50 focus:border-primary/60 focus:outline-none focus:[box-shadow:0_0_0_3px_hsl(var(--primary)/0.08),0_0_10px_hsl(var(--primary)/0.12)] disabled:opacity-50"
          style={{ minHeight: "44px", maxHeight: "200px" }}
        />
        <Button
          size="icon"
          onClick={handleSubmit}
          disabled={!value.trim() || disabled}
          className="absolute bottom-3 right-3 h-8 w-8 rounded-md"
        >
          <Send className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}
