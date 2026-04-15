import { useState } from "react";
import { SidebarProvider } from "@/components/ui/sidebar";
import { AppSidebar } from "@/components/AppSidebar";
import { ChatContainer, Citation } from "@/components/ChatContainer";
import { LawReferencePanel } from "@/components/LawReferencePanel";
import { LawGraphPanel } from "@/components/LawGraphPanel";
import { cn } from "@/lib/utils";

const Index = () => {
  const [citations, setCitations] = useState<Citation[]>([]);
  const [rightTab, setRightTab] = useState<"reference" | "graph">("reference");

  return (
    <SidebarProvider>
      <div className="flex h-screen w-full overflow-hidden">
        <AppSidebar />
        <div className="flex flex-1 overflow-hidden">
          {/* Left: Chat */}
          <div className="flex flex-1 flex-col border-r border-border">
            <ChatContainer onCitationsChange={setCitations} />
          </div>

          {/* Right: 탭 패널 */}
          <div className="hidden w-[380px] shrink-0 flex-col lg:flex">
            {/* 탭 바 */}
            <div className="flex shrink-0 border-b border-border">
              {(["reference", "graph"] as const).map((tab) => (
                <button
                  key={tab}
                  type="button"
                  onClick={() => setRightTab(tab)}
                  className={cn(
                    "flex-1 py-2.5 text-xs font-medium transition-colors",
                    rightTab === tab
                      ? "border-b-2 border-primary text-primary"
                      : "text-muted-foreground hover:text-foreground"
                  )}
                >
                  {tab === "reference" ? "관련 법령" : "법령 그래프"}
                </button>
              ))}
            </div>

            {/* 패널 콘텐츠 */}
            <div className="flex-1 overflow-hidden">
              {rightTab === "reference" ? (
                <LawReferencePanel citations={citations} />
              ) : (
                <LawGraphPanel />
              )}
            </div>
          </div>
        </div>
      </div>
    </SidebarProvider>
  );
};

export default Index;
