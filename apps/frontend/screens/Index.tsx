import { useState } from "react";
import { SidebarProvider } from "@/components/ui/sidebar";
import { AppSidebar } from "@/components/AppSidebar";
import { ChatContainer, Citation } from "@/components/ChatContainer";
import { LawReferencePanel } from "@/components/LawReferencePanel";
import { LawGraphPanel } from "@/components/LawGraphPanel";
import { GraphNodeDetailPanel } from "@/components/GraphNodeDetailPanel";
import { cn } from "@/lib/utils";
import type { GraphNode } from "@/lib/graph-types";

const Index = () => {
  const [citations, setCitations] = useState<Citation[]>([]);
  const [rightTab, setRightTab] = useState<"reference" | "graph">("reference");
  const [graphQuery, setGraphQuery] = useState<string>("");
  const [graphQuerySeq, setGraphQuerySeq] = useState<number>(0);
  const [selectedGraphNode, setSelectedGraphNode] = useState<GraphNode | null>(null);

  const handleQuestionSubmit = (question: string) => {
    setGraphQuery(question);
    setGraphQuerySeq((s) => s + 1);
    setSelectedGraphNode(null);
  };

  const handleNewChat = () => {
    setGraphQuery("");
    setGraphQuerySeq(0);
    setSelectedGraphNode(null);
  };

  return (
    <SidebarProvider>
      <div className="flex h-screen w-full overflow-hidden">
        <AppSidebar />
        <div className="flex flex-1 overflow-hidden">
          {/* Left: Chat */}
          <div className="flex flex-1 flex-col border-r border-border">
            <ChatContainer
              onCitationsChange={setCitations}
              onQuestionSubmit={handleQuestionSubmit}
              onNewChat={handleNewChat}
            />
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
                <div className="flex h-full flex-col">
                  <LawGraphPanel
                    lastQuery={graphQuery}
                    queryKey={graphQuerySeq}
                    isActive={rightTab === "graph"}
                    onNodeSelect={setSelectedGraphNode}
                  />
                  {selectedGraphNode && (
                    <GraphNodeDetailPanel node={selectedGraphNode} />
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </SidebarProvider>
  );
};

export default Index;
