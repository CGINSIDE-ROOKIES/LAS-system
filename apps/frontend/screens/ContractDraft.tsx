import { useState, useCallback } from "react";
import { SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";
import { AppSidebar } from "@/components/AppSidebar";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { toast } from "sonner";
import {
  Upload,
  FileText,
  Loader2,
  Download,
  RefreshCw,
  Pencil,
  AlertTriangle,
  CheckCircle2,
  Sparkles,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";

type DraftStatus = "idle" | "generating" | "ready";

interface ContractForm {
  templateType: string;
  partyA: string;
  partyARepresentative: string;
  partyAAddress: string;
  partyB: string;
  partyBRepresentative: string;
  partyBAddress: string;
  contractAmount: string;
  startDate: string;
  endDate: string;
  scope: string;
  paymentTerms: string;
  specialConditions: string;
}

const defaultForm: ContractForm = {
  templateType: "",
  partyA: "",
  partyARepresentative: "",
  partyAAddress: "",
  partyB: "",
  partyBRepresentative: "",
  partyBAddress: "",
  contractAmount: "",
  startDate: "",
  endDate: "",
  scope: "",
  paymentTerms: "",
  specialConditions: "",
};

const requiredFields: (keyof ContractForm)[] = [
  "templateType", "partyA", "partyB", "contractAmount", "startDate", "endDate", "scope", "paymentTerms",
];

const fieldLabels: Record<string, string> = {
  templateType: "계약서 유형",
  partyA: "갑 (원사업자)",
  partyB: "을 (수급사업자)",
  contractAmount: "계약 금액",
  startDate: "시작일",
  endDate: "종료일",
  scope: "업무 범위",
  paymentTerms: "대금 지급 조건",
};

// Generate mock draft based on form
function generateDraft(form: ContractForm): string {
  const type = form.templateType === "employment" ? "근로계약서" : "하도급 계약서";
  const partyALabel = form.templateType === "employment" ? "사용자" : "원사업자";
  const partyBLabel = form.templateType === "employment" ? "근로자" : "수급사업자";

  return `${type}

${form.partyA || "[갑 상호]"}(이하 "${partyALabel}"라 한다)과(와) ${form.partyB || "[을 상호]"}(이하 "${partyBLabel}"라 한다)은(는) 다음과 같이 계약을 체결한다.

제1조 (목적)
본 계약은 ${partyALabel}와 ${partyBLabel} 간의 ${form.scope || "[업무 범위]"}에 관한 기본적인 사항을 정함을 목적으로 한다.

제2조 (계약기간)
본 계약의 기간은 ${form.startDate || "[시작일]"}부터 ${form.endDate || "[종료일]"}까지로 한다. 계약기간의 변경은 양 당사자의 서면 합의에 의한다.

제3조 (대금)
① ${partyALabel}은 ${partyBLabel}에게 총 계약금액 ${form.contractAmount || "[금액]"}을 지급한다.
② ${form.paymentTerms || "[대금 지급 조건을 입력하세요]"}
③ ${partyALabel}은 목적물 수령일로부터 60일 이내에 대금을 지급하여야 한다.

제4조 (업무 범위)
${partyBLabel}은 다음 업무를 수행한다:
${form.scope || "[업무 범위를 입력하세요]"}

제5조 (납품 및 검수)
① ${partyBLabel}은 ${partyALabel}이 지정한 일시 및 장소에 목적물을 납품하여야 한다.
② ${partyALabel}은 납품일로부터 10영업일 이내에 검수를 완료하여야 한다.
③ 검수 기준 및 방법은 별첨에 따른다.

제6조 (지식재산권)
① 본 계약에 의하여 새롭게 개발된 산출물의 지식재산권은 ${partyALabel}에게 귀속된다.
② ${partyBLabel}이 기존에 보유한 기술 및 지식재산권은 ${partyBLabel}에게 유지된다.

제7조 (비밀유지)
양 당사자는 본 계약과 관련하여 알게 된 상대방의 영업비밀을 계약 종료일로부터 3년간 보호하여야 한다.

제8조 (손해배상)
일방 당사자의 귀책사유로 상대방에게 손해가 발생한 경우, 실제 발생한 손해에 한하여 배상한다. 손해배상 예정액은 계약금액을 초과하지 아니한다.

제9조 (계약 해지)
① 양 당사자는 상대방의 중대한 귀책사유가 있는 경우 30일 전 서면 통지 후 계약을 해지할 수 있다.
② 해지 시 기 수행된 업무에 대한 대금은 정산하여 지급한다.

제10조 (분쟁 해결)
본 계약에 관한 분쟁은 민사소송법에 따른 관할법원에서 해결한다.

${form.specialConditions ? `제11조 (특약사항)\n${form.specialConditions}` : ""}

본 계약의 성립을 증명하기 위하여 계약서 2부를 작성하고 양 당사자가 서명 날인 후 각 1부씩 보관한다.

${partyALabel}: ${form.partyA || "[갑 상호]"}
대표자: ${form.partyARepresentative || "[대표자명]"}
주소: ${form.partyAAddress || "[주소]"}
서명: ________________

${partyBLabel}: ${form.partyB || "[을 상호]"}
대표자: ${form.partyBRepresentative || "[대표자명]"}
주소: ${form.partyBAddress || "[주소]"}
서명: ________________`;
}

// Identify AI-filled vs user-filled sections
function getHighlightedSections(draft: string): { text: string; isAiFilled: boolean }[] {
  const placeholderRegex = /\[.*?\]/g;
  const parts: { text: string; isAiFilled: boolean }[] = [];
  let lastIndex = 0;
  let match;

  while ((match = placeholderRegex.exec(draft)) !== null) {
    if (match.index > lastIndex) {
      parts.push({ text: draft.slice(lastIndex, match.index), isAiFilled: false });
    }
    parts.push({ text: match[0], isAiFilled: true });
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < draft.length) {
    parts.push({ text: draft.slice(lastIndex), isAiFilled: false });
  }
  return parts;
}

const ContractDraft = () => {
  const [form, setForm] = useState<ContractForm>(defaultForm);
  const [draftStatus, setDraftStatus] = useState<DraftStatus>("idle");
  const [draftContent, setDraftContent] = useState("");
  const [isEditing, setIsEditing] = useState(false);
  const [uploadedTemplate, setUploadedTemplate] = useState<string | null>(null);

  const updateForm = useCallback((field: keyof ContractForm, value: string) => {
    setForm((prev) => ({ ...prev, [field]: value }));
  }, []);

  const missingFields = requiredFields.filter((f) => !form[f]);

  const handleGenerate = useCallback(async () => {
    if (missingFields.length > 0) {
      toast.error("필수 항목을 모두 입력해주세요.", {
        description: missingFields.map((f) => fieldLabels[f]).join(", "),
      });
      return;
    }
    setDraftStatus("generating");
    // Simulate generation delay
    await new Promise((r) => setTimeout(r, 2000));
    const draft = generateDraft(form);
    setDraftContent(draft);
    setDraftStatus("ready");
    setIsEditing(false);
    toast.success("계약서 초안이 생성되었습니다.");
  }, [form, missingFields]);

  const handleRegenerate = useCallback(async () => {
    setDraftStatus("generating");
    await new Promise((r) => setTimeout(r, 1500));
    const draft = generateDraft(form);
    setDraftContent(draft);
    setDraftStatus("ready");
    setIsEditing(false);
    toast.success("계약서 초안이 재생성되었습니다.");
  }, [form]);

  const handleDownload = useCallback(() => {
    const blob = new Blob([draftContent], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `계약서_초안_${new Date().toISOString().slice(0, 10)}.txt`;
    a.click();
    URL.revokeObjectURL(url);
    toast.success("문서가 다운로드되었습니다.");
  }, [draftContent]);

  const handleTemplateUpload = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      setUploadedTemplate(file.name);
      toast.success(`${file.name} 템플릿이 업로드되었습니다.`);
    }
  }, []);

  const highlightedParts = draftStatus === "ready" && !isEditing ? getHighlightedSections(draftContent) : [];
  const hasMissingPlaceholders = highlightedParts.some((p) => p.isAiFilled);

  return (
    <SidebarProvider>
      <div className="flex min-h-screen w-full">
        <AppSidebar />
        <div className="flex flex-1 flex-col">
          <header className="flex h-10 items-center border-b border-border px-2">
            <SidebarTrigger />
          </header>

          <div className="flex flex-1 overflow-hidden">
            {/* Left: Form Panel */}
            <div className="flex w-[420px] shrink-0 flex-col border-r border-border">
              <div className="border-b border-border px-4 py-3">
                <h1 className="text-lg font-semibold text-foreground">계약서 초안 작성</h1>
                <p className="text-xs text-muted-foreground">필요한 정보를 입력하면 AI가 계약서 초안을 자동 생성합니다.</p>
              </div>

              <ScrollArea className="flex-1">
                <div className="space-y-6 p-4">
                  {/* Template Selection */}
                  <Card>
                    <CardHeader className="pb-3">
                      <CardTitle className="text-sm">템플릿 선택</CardTitle>
                      <CardDescription className="text-xs">
                        기본 템플릿을 선택하거나 파일을 업로드하세요.
                      </CardDescription>
                    </CardHeader>
                    <CardContent className="space-y-3">
                      <div className="space-y-1.5">
                        <Label className="text-xs">계약서 유형 *</Label>
                        <Select value={form.templateType} onValueChange={(v) => updateForm("templateType", v)}>
                          <SelectTrigger className="text-sm">
                            <SelectValue placeholder="유형 선택" />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="employment">근로계약서</SelectItem>
                            <SelectItem value="subcontract">하도급 계약서</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>

                      <Separator />

                      <div className="space-y-1.5">
                        <Label className="text-xs">또는 템플릿 업로드</Label>
                        {uploadedTemplate ? (
                          <div className="flex items-center gap-2 rounded-md border border-border bg-muted/30 px-3 py-2 text-xs">
                            <FileText className="h-3.5 w-3.5 text-primary" />
                            <span className="flex-1 truncate">{uploadedTemplate}</span>
                            <Button variant="ghost" size="icon" className="h-5 w-5" onClick={() => setUploadedTemplate(null)}>
                              <X className="h-3 w-3" />
                            </Button>
                          </div>
                        ) : (
                          <label>
                            <div className="flex cursor-pointer items-center justify-center gap-2 rounded-md border border-dashed border-muted-foreground/30 px-3 py-3 text-xs text-muted-foreground transition-colors hover:border-primary/50 hover:bg-muted/50">
                              <Upload className="h-4 w-4" />
                              HWP, DOCX, PDF
                            </div>
                            <input type="file" className="hidden" accept=".hwp,.hwpx,.doc,.docx,.pdf" onChange={handleTemplateUpload} />
                          </label>
                        )}
                      </div>
                    </CardContent>
                  </Card>

                  {/* Party Information */}
                  <Card>
                    <CardHeader className="pb-3">
                      <CardTitle className="text-sm">당사자 정보</CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-4">
                      <div>
                        <p className="mb-2 text-xs font-medium text-muted-foreground">갑 (원사업자)</p>
                        <div className="space-y-2">
                          <div className="space-y-1">
                            <Label className="text-xs">상호 *</Label>
                            <Input value={form.partyA} onChange={(e) => updateForm("partyA", e.target.value)} placeholder="주식회사 OO" className="text-sm" />
                          </div>
                          <div className="space-y-1">
                            <Label className="text-xs">대표자</Label>
                            <Input value={form.partyARepresentative} onChange={(e) => updateForm("partyARepresentative", e.target.value)} placeholder="홍길동" className="text-sm" />
                          </div>
                          <div className="space-y-1">
                            <Label className="text-xs">주소</Label>
                            <Input value={form.partyAAddress} onChange={(e) => updateForm("partyAAddress", e.target.value)} placeholder="서울시 강남구..." className="text-sm" />
                          </div>
                        </div>
                      </div>

                      <Separator />

                      <div>
                        <p className="mb-2 text-xs font-medium text-muted-foreground">을 (수급사업자)</p>
                        <div className="space-y-2">
                          <div className="space-y-1">
                            <Label className="text-xs">상호 *</Label>
                            <Input value={form.partyB} onChange={(e) => updateForm("partyB", e.target.value)} placeholder="주식회사 △△" className="text-sm" />
                          </div>
                          <div className="space-y-1">
                            <Label className="text-xs">대표자</Label>
                            <Input value={form.partyBRepresentative} onChange={(e) => updateForm("partyBRepresentative", e.target.value)} placeholder="김철수" className="text-sm" />
                          </div>
                          <div className="space-y-1">
                            <Label className="text-xs">주소</Label>
                            <Input value={form.partyBAddress} onChange={(e) => updateForm("partyBAddress", e.target.value)} placeholder="서울시 서초구..." className="text-sm" />
                          </div>
                        </div>
                      </div>
                    </CardContent>
                  </Card>

                  {/* Contract Details */}
                  <Card>
                    <CardHeader className="pb-3">
                      <CardTitle className="text-sm">계약 조건</CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-3">
                      <div className="space-y-1">
                        <Label className="text-xs">계약 금액 *</Label>
                        <Input value={form.contractAmount} onChange={(e) => updateForm("contractAmount", e.target.value)} placeholder="500,000,000원" className="text-sm" />
                      </div>
                      <div className="grid grid-cols-2 gap-2">
                        <div className="space-y-1">
                          <Label className="text-xs">시작일 *</Label>
                          <Input type="date" value={form.startDate} onChange={(e) => updateForm("startDate", e.target.value)} className="text-sm" />
                        </div>
                        <div className="space-y-1">
                          <Label className="text-xs">종료일 *</Label>
                          <Input type="date" value={form.endDate} onChange={(e) => updateForm("endDate", e.target.value)} className="text-sm" />
                        </div>
                      </div>
                      <div className="space-y-1">
                        <Label className="text-xs">업무 범위 *</Label>
                        <Textarea value={form.scope} onChange={(e) => updateForm("scope", e.target.value)} placeholder="소프트웨어 설계, 개발, 테스트 및 유지보수" className="min-h-[60px] text-sm" />
                      </div>
                      <div className="space-y-1">
                        <Label className="text-xs">대금 지급 조건 *</Label>
                        <Textarea value={form.paymentTerms} onChange={(e) => updateForm("paymentTerms", e.target.value)} placeholder="착수금 30%, 중간금 40%, 잔금 30%를 각 단계 완료 후 30일 이내 지급" className="min-h-[60px] text-sm" />
                      </div>
                      <div className="space-y-1">
                        <Label className="text-xs">특약사항</Label>
                        <Textarea value={form.specialConditions} onChange={(e) => updateForm("specialConditions", e.target.value)} placeholder="추가 특약이 있으면 입력하세요" className="min-h-[60px] text-sm" />
                      </div>
                    </CardContent>
                  </Card>

                  {/* Generate Button */}
                  <div className="space-y-2">
                    {missingFields.length > 0 && (
                      <p className="text-xs text-muted-foreground">
                        미입력 필수 항목: {missingFields.map((f) => fieldLabels[f]).join(", ")}
                      </p>
                    )}
                    <Button className="w-full gap-2" onClick={handleGenerate} disabled={draftStatus === "generating"}>
                      {draftStatus === "generating" ? (
                        <><Loader2 className="h-4 w-4 animate-spin" /> 생성 중...</>
                      ) : (
                        <><Sparkles className="h-4 w-4" /> 초안 생성</>
                      )}
                    </Button>
                  </div>
                </div>
              </ScrollArea>
            </div>

            {/* Right: Preview Panel */}
            <div className="flex flex-1 flex-col">
              <div className="flex items-center justify-between border-b border-border px-4 py-2">
                <h2 className="text-sm font-semibold text-foreground">초안 미리보기</h2>
                {draftStatus === "ready" && (
                  <div className="flex items-center gap-1">
                    <Button variant="outline" size="sm" className="text-xs" onClick={() => setIsEditing(!isEditing)}>
                      <Pencil className="mr-1 h-3 w-3" />
                      {isEditing ? "미리보기" : "편집"}
                    </Button>
                    <Button variant="outline" size="sm" className="text-xs" onClick={handleRegenerate}>
                      <RefreshCw className="mr-1 h-3 w-3" />
                      재생성
                    </Button>
                    <Button size="sm" className="text-xs" onClick={handleDownload}>
                      <Download className="mr-1 h-3 w-3" />
                      다운로드
                    </Button>
                  </div>
                )}
              </div>

              {draftStatus === "idle" && (
                <div className="flex flex-1 flex-col items-center justify-center text-center">
                  <FileText className="h-16 w-16 text-muted-foreground/20" />
                  <p className="mt-4 text-sm text-muted-foreground">
                    좌측 양식을 작성하고 "초안 생성" 버튼을 클릭하세요.
                  </p>
                  <p className="text-xs text-muted-foreground">
                    AI가 입력된 정보를 기반으로 계약서 초안을 자동 생성합니다.
                  </p>
                </div>
              )}

              {draftStatus === "generating" && (
                <div className="flex flex-1 flex-col items-center justify-center text-center">
                  <Loader2 className="h-10 w-10 animate-spin text-primary" />
                  <p className="mt-4 text-sm font-medium text-foreground">초안을 생성하고 있습니다...</p>
                  <p className="text-xs text-muted-foreground">입력된 정보와 관련 법령을 기반으로 작성 중</p>
                </div>
              )}

              {draftStatus === "ready" && (
                <ScrollArea className="flex-1">
                  <div className="p-6">
                    {/* Notices */}
                    {hasMissingPlaceholders && !isEditing && (
                      <div className="mb-4 flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3">
                        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
                        <div>
                          <p className="text-xs font-medium text-destructive">미입력 항목이 있습니다</p>
                          <p className="text-xs text-muted-foreground">
                            [대괄호]로 표시된 부분은 정보가 부족하여 자동 생성되지 않았습니다. 좌측 양식에서 추가 입력하거나 편집 모드에서 직접 수정하세요.
                          </p>
                        </div>
                      </div>
                    )}

                    {!hasMissingPlaceholders && !isEditing && (
                      <div className="mb-4 flex items-start gap-2 rounded-lg border border-primary/30 bg-primary/5 p-3">
                        <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                        <div>
                          <p className="text-xs font-medium text-primary">초안 생성 완료</p>
                          <p className="text-xs text-muted-foreground">
                            모든 필수 항목이 반영되었습니다. 내용을 검토한 후 다운로드하세요.
                          </p>
                        </div>
                      </div>
                    )}

                    {/* Legal caution */}
                    <div className="mb-4 flex items-start gap-2 rounded-lg bg-muted/50 p-3">
                      <Badge variant="secondary" className="text-[10px]">법적 주의</Badge>
                      <p className="text-xs text-muted-foreground">
                        AI가 생성한 초안은 참고용입니다. 최종 계약 체결 전 법률 전문가의 검토를 받으시기 바랍니다.
                      </p>
                    </div>

                    {/* Draft Content */}
                    {isEditing ? (
                      <Textarea
                        value={draftContent}
                        onChange={(e) => setDraftContent(e.target.value)}
                        className="min-h-[600px] font-mono text-sm leading-relaxed"
                      />
                    ) : (
                      <Card>
                        <CardContent className="p-6">
                          <div className="whitespace-pre-wrap font-mono text-sm leading-relaxed text-foreground">
                            {highlightedParts.map((part, idx) =>
                              part.isAiFilled ? (
                                <span
                                  key={idx}
                                  className="rounded bg-destructive/10 px-0.5 text-destructive"
                                >
                                  {part.text}
                                </span>
                              ) : (
                                <span key={idx}>{part.text}</span>
                              )
                            )}
                          </div>
                        </CardContent>
                      </Card>
                    )}
                  </div>
                </ScrollArea>
              )}
            </div>
          </div>
        </div>
      </div>
    </SidebarProvider>
  );
};

export default ContractDraft;
