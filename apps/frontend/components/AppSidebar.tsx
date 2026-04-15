"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Scale, FileSearch, FilePen, Clock, Settings, Filter, X } from "lucide-react";
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
  { title: "법령 Q&A", icon: Scale, path: "/" },
  { title: "계약서 검토", icon: FileSearch, path: "/contract-review" },
  { title: "계약서 초안 작성", icon: FilePen, path: "/contract-draft" },
  { title: "히스토리", icon: Clock, path: "/history" },
  { title: "설정", icon: Settings, path: "/settings" },
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

const LAW_OPTIONS = LAW_GROUPS.flatMap((g) => g.laws);

/** 긴 법령명 약칭 — 툴팁으로 전체명 표시 */
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
      <SidebarHeader className="border-b border-sidebar-border px-4 py-4">
        {!collapsed && (
          <div className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary">
              <Scale className="h-4 w-4 text-primary-foreground" />
            </div>
            <div>
              <h2 className="text-sm font-semibold text-sidebar-foreground">AI 법무지원시스템</h2>
              <p className="text-xs text-muted-foreground">법령 기반 AI 법무 지원</p>
            </div>
          </div>
        )}
        {collapsed && (
          <div className="flex items-center justify-center">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary">
              <Scale className="h-4 w-4 text-primary-foreground" />
            </div>
          </div>
        )}
      </SidebarHeader>

      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupContent>
            <SidebarMenu>
              {menuItems.map((item) => {
                const isActive = pathname === item.path;
                return (
                  <SidebarMenuItem key={item.title}>
                    <SidebarMenuButton
                      asChild
                      isActive={isActive}
                      tooltip={item.title}
                      className={isActive ? "bg-sidebar-accent text-sidebar-accent-foreground font-medium" : ""}
                    >
                      <Link href={item.path}>
                        <item.icon className="h-4 w-4" />
                        {!collapsed && <span>{item.title}</span>}
                      </Link>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                );
              })}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter className="border-t border-sidebar-border">
        {pathname !== "/" ? null : collapsed ? (
          <Tooltip>
            <TooltipTrigger asChild>
              <div className="flex items-center justify-center py-3 cursor-default">
                <div className="relative">
                  <Filter className="h-4 w-4 text-muted-foreground" />
                  {selectedLaws.length > 0 && (
                    <span className="absolute -top-1 -right-1 flex h-3 w-3 items-center justify-center rounded-full bg-primary text-[8px] font-bold text-primary-foreground">
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
          <div className="px-4 py-4 space-y-2.5">
            {/* 헤더 */}
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-1.5">
                <Filter className="h-3 w-3 text-muted-foreground" />
                <span className="text-xs font-semibold text-foreground/70">법령 필터</span>
                {selectedLaws.length > 0 && (
                  <span className="rounded-full bg-primary px-1.5 py-px text-[10px] font-bold text-primary-foreground">
                    {selectedLaws.length}
                  </span>
                )}
              </div>
              {selectedLaws.length > 0 && (
                <button
                  type="button"
                  onClick={() => { setSelectedLaws([]); try { localStorage.removeItem(LAW_FILTER_KEY); } catch {} }}
                  className="text-[10px] text-muted-foreground underline transition-colors hover:text-foreground"
                >
                  전체 해제
                </button>
              )}
            </div>

            {/* 그룹별 칩 목록 */}
            <div className="space-y-2.5">
              {LAW_GROUPS.map((group) => (
                <div key={group.label}>
                  <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/50">
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
                                  ? "border-primary bg-primary/10 text-primary font-medium shadow-sm"
                                  : "border-border text-muted-foreground hover:border-primary/50 hover:text-foreground hover:shadow-sm"
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

            <p className={cn("text-[10px] text-muted-foreground/50", selectedLaws.length > 0 && "invisible")}>
              미선택 시 전체 법령 검색
            </p>
          </div>
        )}
      </SidebarFooter>
    </Sidebar>
  );
}
