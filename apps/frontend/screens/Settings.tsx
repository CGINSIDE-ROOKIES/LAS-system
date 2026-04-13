import { useState, useEffect } from "react";
import { SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";
import { AppSidebar } from "@/components/AppSidebar";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { toast } from "sonner";
import { Save } from "lucide-react";

interface Settings {
  model: string;
  topK: number;
  answerDetail: string;
  streamingResponse: boolean;
  showCitations: boolean;
  showLawGraph: boolean;
  showFollowUpQuestions: boolean;
}

const defaultSettings: Settings = {
  model: "gemini",
  topK: 5,
  answerDetail: "normal",
  streamingResponse: true,
  showCitations: true,
  showLawGraph: true,
  showFollowUpQuestions: true,
};

const Settings = () => {
  const [settings, setSettings] = useState<Settings>(defaultSettings);

  useEffect(() => {
    const saved = localStorage.getItem("legal-ai-settings");
    if (saved) {
      try {
        setSettings({ ...defaultSettings, ...JSON.parse(saved) });
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
              {/* TODO: per-request 모델 변경은 현재 미지원. 백엔드에서 모델 파라미터 수신 지원 시 활성화 */}
              <Card>
                <CardHeader>
                  <CardTitle className="text-lg">모델 설정</CardTitle>
                  <CardDescription>
                    사용할 LLM 모델을 설정합니다.
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-6">
                  <div className="space-y-2">
                    <Label htmlFor="model" className="text-muted-foreground">LLM 모델</Label>
                    <Select
                      value={settings.model}
                      onValueChange={(value) =>
                        setSettings((prev) => ({ ...prev, model: value }))
                      }
                      disabled
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
                    <p className="text-xs text-muted-foreground">
                      현재 모델 변경은 지원되지 않습니다. 추후 업데이트 예정입니다.
                    </p>
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="answerDetail">답변 상세도</Label>
                    <Select
                      value={settings.answerDetail}
                      onValueChange={(value) =>
                        setSettings((prev) => ({ ...prev, answerDetail: value }))
                      }
                    >
                      <SelectTrigger id="answerDetail" className="w-full max-w-xs">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="brief">간략</SelectItem>
                        <SelectItem value="normal">보통 (기본)</SelectItem>
                        <SelectItem value="detailed">상세</SelectItem>
                      </SelectContent>
                    </Select>
                    <p className="text-xs text-muted-foreground">
                      상세할수록 더 긴 답변을 제공합니다.
                    </p>
                  </div>
                </CardContent>
              </Card>

              {/* Retrieval Settings */}
              <Card>
                <CardHeader>
                  <CardTitle className="text-lg">검색 설정</CardTitle>
                  <CardDescription>
                    법령 검색 설정을 구성합니다.
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-6">
                  <div className="space-y-2">
                    <Label htmlFor="topk">검색 범위</Label>
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
                        <SelectItem value="5">빠른 검색 (기본)</SelectItem>
                        <SelectItem value="10">일반 검색</SelectItem>
                        <SelectItem value="20">정밀 검색</SelectItem>
                      </SelectContent>
                    </Select>
                    <p className="text-xs text-muted-foreground">
                      범위가 넓을수록 더 많은 법령을 참조하여 답변합니다.
                    </p>
                  </div>
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
                      <Label htmlFor="followUp">후속 질문 추천</Label>
                      <p className="text-xs text-muted-foreground">
                        답변 후 관련 후속 질문을 추천합니다.
                      </p>
                    </div>
                    <Switch
                      id="followUp"
                      checked={settings.showFollowUpQuestions}
                      onCheckedChange={(checked) =>
                        setSettings((prev) => ({ ...prev, showFollowUpQuestions: checked }))
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
