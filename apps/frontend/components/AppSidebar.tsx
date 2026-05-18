"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Scale, FileSearch, FilePen, Clock, Settings, Filter, X,
  LayoutDashboard, MessageSquare,
} from "lucide-react";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@/components/ui/sidebar";
import { cn } from "@/lib/utils";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

const menuItems = [
  { title: "홈",             icon: LayoutDashboard, path: "/"                },
  { title: "법령 Q&A",       icon: MessageSquare,   path: "/chat"            },
  { title: "계약서 검토",     icon: FileSearch,      path: "/contract-review" },
  { title: "계약서 초안 작성", icon: FilePen,         path: "/contract-draft"  },
  { title: "히스토리",        icon: Clock,           path: "/history"         },
  { title: "설정",            icon: Settings,        path: "/settings"        },
];

const LAW_GROUPS = [
  {
    label: "근로계약",
    laws: [
      "근로기준법",
      "기간제 및 단시간근로자 보호 등에 관한 법률",
      "파견근로자 보호 등에 관한 법률",
      "최저임금법",
      "남녀고용평등과 일·가정 양립 지원에 관한 법률",
      "근로자퇴직급여 보장법",
    ],
  },
  {
    label: "하도급계약",
    laws: [
      "하도급거래 공정화에 관한 법률",
      "건설산업기본법",
    ],
  },
];

const LAW_ABBREV: Record<string, string> = {
  "기간제 및 단시간근로자 보호 등에 관한 법률": "기간제법",
  "파견근로자 보호 등에 관한 법률": "파견근로자법",
  "근로자퇴직급여 보장법": "퇴직급여법",
  "남녀고용평등과 일·가정 양립 지원에 관한 법률": "남녀고용평등법",
  "하도급거래 공정화에 관한 법률": "하도급법",
};

export function AppSidebar() {
  const { state } = useSidebar();
  const collapsed = state === "collapsed";
  const pathname = usePathname();
  const LAW_FILTER_KEY = "las_law_filter";

  const [selectedLaws, setSelectedLaws] = useState<string[]>([]);
  const [usageHovered, setUsageHovered] = useState(false);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(LAW_FILTER_KEY);
      if (raw) setSelectedLaws(JSON.parse(raw));
    } catch {}
  }, []);

  useEffect(() => {
    const handler = () => setSelectedLaws([]);
    window.addEventListener("las_law_filter_cleared", handler);
    return () => window.removeEventListener("las_law_filter_cleared", handler);
  }, []);

  const toggleLaw = (law: string) => {
    setSelectedLaws((prev) => {
      const next = prev.includes(law) ? prev.filter((l) => l !== law) : [...prev, law];
      try { localStorage.setItem(LAW_FILTER_KEY, JSON.stringify(next)); } catch {}
      return next;
    });
  };

  return (
    <Sidebar collapsible="icon">
      {/* 브랜드 */}
      <SidebarHeader className="border-b border-sidebar-border px-4 py-5" style={{ minHeight: 76 }}>
        {!collapsed && (
          <Link href="/" className="flex items-center gap-[10px] hover:opacity-80 transition-opacity">
            <div
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[10px] text-white"
              style={{ background: "linear-gradient(135deg,#5C70FF,#3D52F5)", boxShadow: "0 6px 14px rgba(61,82,245,.25)" }}
            >
              <Scale size={20} strokeWidth={1.9} />
            </div>
            <div style={{ paddingLeft: 2 }}>
              <div className="font-bold text-sidebar-foreground" style={{ fontSize: 14.5, letterSpacing: "-.01em", lineHeight: 1.2 }}>LAS</div>
              <div className="text-sidebar-foreground/50" style={{ fontSize: 11, marginTop: 1 }}>AI 법무지원시스템</div>
            </div>
          </Link>
        )}
        {collapsed && (
          <Link href="/" className="flex items-center justify-center hover:opacity-80 transition-opacity">
            <div
              className="flex h-9 w-9 items-center justify-center rounded-[10px] text-white"
              style={{ background: "linear-gradient(135deg,#5C70FF,#3D52F5)", boxShadow: "0 6px 14px rgba(61,82,245,.25)" }}
            >
              <Scale size={20} strokeWidth={1.9} />
            </div>
          </Link>
        )}
      </SidebarHeader>

      {/* 내비 */}
      <SidebarContent>
        <SidebarGroup className="!px-[14px] !py-1">
          <SidebarGroupContent>
            {!collapsed && (
              <div className="px-2 pb-2 pt-[14px] text-[10.5px] font-semibold uppercase tracking-[.08em] text-sidebar-foreground/40">
                메뉴
              </div>
            )}
            <SidebarMenu className="gap-[2px]">
              {menuItems.map((item) => {
                const isActive = pathname === item.path;
                return (
                  <SidebarMenuItem key={item.title} className="relative">
                    {isActive && !collapsed && (
                      <span className="pointer-events-none absolute left-0 top-[6px] bottom-[6px] w-[3px] rounded-r bg-primary z-10" />
                    )}
                    <SidebarMenuButton
                      asChild
                      isActive={isActive}
                      tooltip={item.title}
                      className={cn(
                        "h-auto rounded-lg gap-[10px] px-2 py-[9px]",
                        isActive
                          ? "bg-sidebar-accent text-sidebar-accent-foreground font-semibold"
                          : "font-medium text-sidebar-foreground/70 hover:bg-sidebar-accent/60 hover:text-sidebar-foreground"
                      )}
                    >
                      <Link href={item.path}>
                        <item.icon className="shrink-0" size={17} strokeWidth={1.7} />
                        <span style={{ fontSize: 13.5 }}>{item.title}</span>
                      </Link>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                );
              })}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter className="border-t border-sidebar-border p-0">
        {/* 법령 필터 — /chat 에서만 */}
        {pathname === "/chat" && (
          collapsed ? (
            <Tooltip>
              <TooltipTrigger asChild>
                <div className="flex items-center justify-center py-3 cursor-default">
                  <div className="relative">
                    <Filter className="h-4 w-4 text-sidebar-foreground/50" />
                    {selectedLaws.length > 0 && (
                      <span className="absolute -top-1 -right-1 flex h-3 w-3 items-center justify-center rounded-full bg-primary text-[8px] font-bold text-white">
                        {selectedLaws.length}
                      </span>
                    )}
                  </div>
                </div>
              </TooltipTrigger>
              <TooltipContent side="right">
                {selectedLaws.length > 0 ? selectedLaws.join(", ") : "법령 필터 없음"}
              </TooltipContent>
            </Tooltip>
          ) : (
            <div className="px-[14px] pt-3">
              <div className="rounded-xl px-3 py-2.5 space-y-2 bg-card border" style={{ borderColor: "hsl(var(--sidebar-background))" }}>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-1.5">
                    <Filter className="h-3 w-3 shrink-0 text-sidebar-foreground/50" />
                    <span className="font-semibold text-sidebar-foreground/70" style={{ fontSize: 11.5 }}>법령 필터</span>
                    {selectedLaws.length > 0 && (
                      <span className="rounded-full bg-primary px-1.5 py-px text-[10px] font-bold text-white">
                        {selectedLaws.length}
                      </span>
                    )}
                  </div>
                  {selectedLaws.length > 0 && (
                    <button
                      type="button"
                      onClick={() => { setSelectedLaws([]); try { localStorage.removeItem(LAW_FILTER_KEY); } catch {} }}
                      className="text-[10px] underline text-sidebar-foreground/50 transition-opacity hover:opacity-80"
                    >
                      전체 해제
                    </button>
                  )}
                </div>
                <div className="space-y-2">
                  {LAW_GROUPS.map((group) => (
                    <div key={group.label}>
                      <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-sidebar-foreground/40">
                        {group.label}
                      </p>
                      <div className="flex flex-wrap gap-1.5">
                        {group.laws.map((law) => {
                          const selected = selectedLaws.includes(law);
                          const label = LAW_ABBREV[law] ?? law;
                          return (
                            <Tooltip key={law}>
                              <TooltipTrigger asChild>
                                <button
                                  type="button"
                                  onClick={() => toggleLaw(law)}
                                  className={cn(
                                    "flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] transition-all",
                                    selected
                                      ? "border-primary/50 bg-primary/10 text-primary font-medium"
                                      : "border-sidebar-border text-sidebar-foreground/60 hover:border-sidebar-foreground/40 hover:text-sidebar-foreground"
                                  )}
                                >
                                  {label}
                                  {selected && <X className="h-2.5 w-2.5 shrink-0" />}
                                </button>
                              </TooltipTrigger>
                              {LAW_ABBREV[law] && (
                                <TooltipContent side="right" className="max-w-[200px] text-xs">
                                  {law}
                                </TooltipContent>
                              )}
                            </Tooltip>
                          );
                        })}
                      </div>
                    </div>
                  ))}
                </div>
                <p className={cn("text-[10px] text-sidebar-foreground/40", selectedLaws.length > 0 && "invisible")}>
                  미선택 시 전체 법령 검색
                </p>
              </div>
            </div>
          )
        )}

        {/* 사용량 미니 인디케이터 */}
        {!collapsed && (
          <div
            className="relative px-[14px] pb-[10px] pt-1"
            onMouseEnter={() => setUsageHovered(true)}
            onMouseLeave={() => setUsageHovered(false)}
          >
            <div className="h-[3px] rounded-full overflow-hidden bg-sidebar-border">
              <div className="h-full bg-primary" style={{ width: "64%" }} />
            </div>
            <div className="mt-[5px] flex justify-between text-sidebar-foreground/50" style={{ fontSize: 10.5 }}>
              <span>320 / 500 질의</span>
              <span className="font-semibold text-sidebar-foreground">64%</span>
            </div>
            {usageHovered && (
              <div className="absolute left-[14px] right-[14px] rounded-lg border border-sidebar-border bg-card px-[10px] py-[7px] text-sidebar-foreground z-[100] whitespace-nowrap" style={{ bottom: "calc(100% + 4px)", fontSize: 11.5 }}>
                법령 Q&A 84 · 검토 11 · 초안 6
              </div>
            )}
          </div>
        )}

        {/* 유저 프로필 */}
        <div className={cn("flex items-center gap-[10px] px-[14px] py-3 overflow-hidden", !collapsed && "border-t border-sidebar-border")}>
          <div
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-white font-bold"
            style={{ background: "linear-gradient(135deg,#7B91FF,#3D52F5)", fontSize: 13 }}
          >
            C
          </div>
          {!collapsed && (
            <div className="flex-1 min-w-0">
              <div className="font-semibold text-sidebar-foreground truncate" style={{ fontSize: 13 }}>씨지인사이드</div>
              <div className="truncate text-sidebar-foreground/50" style={{ fontSize: 11.5 }}>경영지원본부 · 법무팀</div>
            </div>
          )}
        </div>
      </SidebarFooter>
    </Sidebar>
  );
}
