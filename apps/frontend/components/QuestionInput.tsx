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
          className="block w-full resize-none rounded-[14px] border border-input bg-card px-[18px] py-[15px] pr-[52px] text-sm text-foreground placeholder:text-muted-foreground/50 focus:border-primary focus:outline-none focus:[box-shadow:0_0_0_3px_hsl(var(--primary)/0.1)] disabled:opacity-50 transition-shadow"
          style={{ minHeight: "52px", maxHeight: "200px", borderColor: "hsl(var(--border))", lineHeight: "1.5" }}
        />
        <Button
          size="icon"
          onClick={handleSubmit}
          disabled={!value.trim() || disabled}
          className="absolute top-1/2 -translate-y-1/2 right-[8px] h-9 w-9 rounded-[10px] hover:bg-primary/90"
        >
          <Send className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}
