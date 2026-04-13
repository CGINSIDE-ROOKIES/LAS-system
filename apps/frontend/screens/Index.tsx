import { useState } from "react";
import { SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";
import { AppSidebar } from "@/components/AppSidebar";
import { ChatContainer, Citation } from "@/components/ChatContainer";
import { LawReferencePanel } from "@/components/LawReferencePanel";
import { LawGraphPanel } from "@/components/LawGraphPanel";
import { useSettings } from "@/hooks/useSettings";

const Index = () => {
  const [citations, setCitations] = useState<Citation[]>([]);
  const { showLawGraph } = useSettings();

  return (
    <SidebarProvider>
      <div className="flex h-screen w-full overflow-hidden">
        <AppSidebar />
        <div className="flex flex-1 flex-col">
          {/* Minimal header with sidebar trigger only */}
          <header className="flex h-10 items-center border-b border-border px-2">
            <SidebarTrigger />
          </header>

          {/* Two-column layout */}
          <div className="flex flex-1 overflow-hidden">
            {/* Left: Chat */}
            <div className="flex flex-1 flex-col border-r border-border">
              <ChatContainer onCitationsChange={setCitations} />
            </div>

            {/* Right: Reference + Graph */}
            <div className="hidden w-[380px] shrink-0 flex-col lg:flex">
              <div className={`overflow-hidden ${showLawGraph ? "flex-1 border-b border-border" : "flex-1"}`}>
                <LawReferencePanel citations={citations} />
              </div>
              {showLawGraph && (
                <div className="h-[280px] shrink-0">
                  <LawGraphPanel />
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
