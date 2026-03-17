import { useState, useEffect } from "react";
import { SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";
import { AppSidebar } from "@/components/AppSidebar";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Slider } from "@/components/ui/slider";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Checkbox } from "@/components/ui/checkbox";
import { toast } from "sonner";
import { Save } from "lucide-react";

interface Settings {
  model: string;
  temperature: number;
  hybridSearch: boolean;
  topK: number;
  rrfRanking: boolean;
  lawFilters: string[];
  streamingResponse: boolean;
  showCitations: boolean;
  showLawGraph: boolean;
}

const defaultSettings: Settings = {
  model: "gemini",
  temperature: 0.7,
  hybridSearch: true,
  topK: 10,
  rrfRanking: true,
  lawFilters: [],
  streamingResponse: true,
  showCitations: true,
  showLawGraph: true,
};

const lawOptions = [
  { id: "labor", label: "근로기준법 (Labor Standards Act)" },
  { id: "subcontract", label: "하도급법 (Subcontracting Act)" },
  { id: "minwage", label: "최저임금법 (Minimum Wage Act)" },
];

const Settings = () => {
  const [settings, setSettings] = useState<Settings>(defaultSettings);

  useEffect(() => {
    const saved = localStorage.getItem("legal-ai-settings");
    if (saved) {
      try {
        setSettings(JSON.parse(saved));
      } catch (e) {
        console.error("Failed to parse settings:", e);
      }
    }
  }, []);

  const handleSave = () => {
    localStorage.setItem("legal-ai-settings", JSON.stringify(settings));
    toast.success("설정이 저장되었습니다.", {
      description: "변경사항이 적용됩니다.",
    });
  };

  const toggleLawFilter = (lawId: string) => {
    setSettings((prev) => ({
      ...prev,
      lawFilters: prev.lawFilters.includes(lawId)
        ? prev.lawFilters.filter((id) => id !== lawId)
        : [...prev.lawFilters, lawId],
    }));
  };

  return (
    <SidebarProvider>
      <div className="flex min-h-screen w-full">
        <AppSidebar />
        <div className="flex flex-1 flex-col">
          <header className="flex h-10 items-center border-b border-border px-2">
            <SidebarTrigger />
          </header>

          <div className="flex-1 overflow-auto bg-muted/30 p-6">
            <div className="mx-auto max-w-3xl space-y-6">
              <div>
                <h1 className="text-2xl font-semibold text-foreground">설정</h1>
                <p className="text-sm text-muted-foreground">
                  AI 법률 Q&A 시스템 설정을 관리합니다.
                </p>
              </div>

              {/* Model Settings */}
              <Card>
                <CardHeader>
                  <CardTitle className="text-lg">모델 설정</CardTitle>
                  <CardDescription>
                    사용할 LLM 모델과 생성 파라미터를 설정합니다.
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-6">
                  <div className="space-y-2">
                    <Label htmlFor="model">LLM 모델</Label>
                    <Select
                      value={settings.model}
                      onValueChange={(value) =>
                        setSettings((prev) => ({ ...prev, model: value }))
                      }
                    >
                      <SelectTrigger id="model" className="w-full max-w-xs">
                        <SelectValue placeholder="모델 선택" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="gemini">Gemini</SelectItem>
                        <SelectItem value="openai">OpenAI</SelectItem>
                        <SelectItem value="kt-midm">KT midm</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="space-y-3">
                    <div className="flex items-center justify-between">
                      <Label htmlFor="temperature">Temperature</Label>
                      <span className="text-sm font-medium text-muted-foreground">
                        {settings.temperature.toFixed(1)}
                      </span>
                    </div>
                    <Slider
                      id="temperature"
                      min={0}
                      max={1}
                      step={0.1}
                      value={[settings.temperature]}
                      onValueChange={([value]) =>
                        setSettings((prev) => ({ ...prev, temperature: value }))
                      }
                      className="max-w-xs"
                    />
                    <p className="text-xs text-muted-foreground">
                      낮을수록 일관된 답변, 높을수록 창의적인 답변을 생성합니다.
                    </p>
                  </div>
                </CardContent>
              </Card>

              {/* Retrieval Settings */}
              <Card>
                <CardHeader>
                  <CardTitle className="text-lg">검색 설정</CardTitle>
                  <CardDescription>
                    법령 검색 및 문서 검색 설정을 구성합니다.
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-6">
                  <div className="flex items-center justify-between">
                    <div className="space-y-0.5">
                      <Label htmlFor="hybrid">하이브리드 검색</Label>
                      <p className="text-xs text-muted-foreground">
                        벡터 검색과 키워드 검색을 결합합니다.
                      </p>
                    </div>
                    <Switch
                      id="hybrid"
                      checked={settings.hybridSearch}
                      onCheckedChange={(checked) =>
                        setSettings((prev) => ({ ...prev, hybridSearch: checked }))
                      }
                    />
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="topk">Top-K 결과</Label>
                    <Select
                      value={settings.topK.toString()}
                      onValueChange={(value) =>
                        setSettings((prev) => ({ ...prev, topK: parseInt(value) }))
                      }
                    >
                      <SelectTrigger id="topk" className="w-full max-w-xs">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="5">5개</SelectItem>
                        <SelectItem value="10">10개</SelectItem>
                        <SelectItem value="20">20개</SelectItem>
                      </SelectContent>
                    </Select>
                    <p className="text-xs text-muted-foreground">
                      검색 결과로 반환할 최대 문서 수입니다.
                    </p>
                  </div>

                  <div className="flex items-center justify-between">
                    <div className="space-y-0.5">
                      <Label htmlFor="rrf">RRF 랭킹</Label>
                      <p className="text-xs text-muted-foreground">
                        Reciprocal Rank Fusion을 사용하여 결과를 정렬합니다.
                      </p>
                    </div>
                    <Switch
                      id="rrf"
                      checked={settings.rrfRanking}
                      onCheckedChange={(checked) =>
                        setSettings((prev) => ({ ...prev, rrfRanking: checked }))
                      }
                    />
                  </div>
                </CardContent>
              </Card>

              {/* Law Filter */}
              <Card>
                <CardHeader>
                  <CardTitle className="text-lg">법령 필터</CardTitle>
                  <CardDescription>
                    검색 대상 법령을 선택합니다. 선택하지 않으면 전체 법령을 검색합니다.
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <div className="space-y-3">
                    {lawOptions.map((law) => (
                      <div key={law.id} className="flex items-center space-x-3">
                        <Checkbox
                          id={law.id}
                          checked={settings.lawFilters.includes(law.id)}
                          onCheckedChange={() => toggleLawFilter(law.id)}
                        />
                        <Label
                          htmlFor={law.id}
                          className="cursor-pointer text-sm font-normal"
                        >
                          {law.label}
                        </Label>
                      </div>
                    ))}
                  </div>
                  {settings.lawFilters.length === 0 && (
                    <p className="mt-3 text-xs text-muted-foreground">
                      ⓘ 선택된 법령이 없어 전체 법령에서 검색합니다.
                    </p>
                  )}
                </CardContent>
              </Card>

              {/* Response Settings */}
              <Card>
                <CardHeader>
                  <CardTitle className="text-lg">응답 설정</CardTitle>
                  <CardDescription>
                    AI 응답 표시 방식을 설정합니다.
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-6">
                  <div className="flex items-center justify-between">
                    <div className="space-y-0.5">
                      <Label htmlFor="streaming">스트리밍 응답</Label>
                      <p className="text-xs text-muted-foreground">
                        답변을 실시간으로 스트리밍합니다.
                      </p>
                    </div>
                    <Switch
                      id="streaming"
                      checked={settings.streamingResponse}
                      onCheckedChange={(checked) =>
                        setSettings((prev) => ({ ...prev, streamingResponse: checked }))
                      }
                    />
                  </div>

                  <div className="flex items-center justify-between">
                    <div className="space-y-0.5">
                      <Label htmlFor="citations">근거 조문 표시</Label>
                      <p className="text-xs text-muted-foreground">
                        답변에 참조된 법령 조문을 표시합니다.
                      </p>
                    </div>
                    <Switch
                      id="citations"
                      checked={settings.showCitations}
                      onCheckedChange={(checked) =>
                        setSettings((prev) => ({ ...prev, showCitations: checked }))
                      }
                    />
                  </div>

                  <div className="flex items-center justify-between">
                    <div className="space-y-0.5">
                      <Label htmlFor="graph">법령 관계 그래프 표시</Label>
                      <p className="text-xs text-muted-foreground">
                        관련 법령 간의 관계를 그래프로 시각화합니다.
                      </p>
                    </div>
                    <Switch
                      id="graph"
                      checked={settings.showLawGraph}
                      onCheckedChange={(checked) =>
                        setSettings((prev) => ({ ...prev, showLawGraph: checked }))
                      }
                    />
                  </div>
                </CardContent>
              </Card>

              {/* Save Button */}
              <div className="flex justify-end">
                <Button onClick={handleSave} className="gap-2">
                  <Save className="h-4 w-4" />
                  설정 저장
                </Button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </SidebarProvider>
  );
};

export default Settings;
