import { useState } from "react";
import { Send } from "lucide-react";
import { Button } from "@/components/ui/button";

const exampleQuestions = [
  "근로계약서 작성 시 필수 기재사항은?",
  "연장근로수당 지급 기준은?",
  "하도급 계약에서 위법 소지가 있는 조항은?",
  "기간제 근로자 계약 시 주의사항은?",
];

interface QuestionInputProps {
  onSubmit: (question: string) => void;
  disabled?: boolean;
}

export function QuestionInput({ onSubmit, disabled }: QuestionInputProps) {
  const [value, setValue] = useState("");

  const handleSubmit = () => {
    if (!value.trim() || disabled) return;
    onSubmit(value.trim());
    setValue("");
  };

  return (
    <div className="space-y-3">
      <div className="relative">
        <textarea
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              handleSubmit();
            }
          }}
          placeholder="예: 근로계약서 작성 시 필수 기재사항은 무엇인가요?"
          disabled={disabled}
          className="w-full resize-none rounded-lg border border-border bg-card px-4 py-3 pr-12 text-sm text-foreground placeholder:text-muted-foreground focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary disabled:opacity-50"
          rows={3}
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
      <div className="flex flex-wrap gap-2">
        {exampleQuestions.map((q) => (
          <button
            key={q}
            onClick={() => onSubmit(q)}
            disabled={disabled}
            className="rounded-md border border-border bg-card px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:border-primary hover:text-primary disabled:opacity-50"
          >
            {q}
          </button>
        ))}
      </div>
    </div>
  );
}
