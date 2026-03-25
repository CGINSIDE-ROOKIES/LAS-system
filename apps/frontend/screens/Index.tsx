import { SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";
import { AppSidebar } from "@/components/AppSidebar";
import { ChatContainer } from "@/components/ChatContainer";
import { LawReferencePanel } from "@/components/LawReferencePanel";
import { LawGraphPanel } from "@/components/LawGraphPanel";

const Index = () => {
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
              <ChatContainer />
            </div>

            {/* Right: Reference + Graph */}
            <div className="hidden w-[380px] shrink-0 flex-col lg:flex">
              <div className="flex-1 overflow-hidden border-b border-border">
                <LawReferencePanel />
              </div>
              <div className="h-[280px] shrink-0">
                <LawGraphPanel />
              </div>
            </div>
          </div>
        </div>
      </div>
    </SidebarProvider>
  );
};

export default Index;
